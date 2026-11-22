"""Clientes mínimos de LLM con capa gratuita (Gemini, Groq). Sin SDKs: solo REST oficial."""
from __future__ import annotations

import json
import re
import time
from typing import Any

import requests

from .utils import log

L = log("llm")
TIMEOUT = 120


class LLMError(RuntimeError):
    pass


class CuotaAgotada(LLMError):
    pass


def extraer_json(texto: str) -> Any:
    """Extrae el primer bloque JSON válido de una respuesta de LLM."""
    texto = texto.strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto)
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        pass
    for abre, cierra in (("[", "]"), ("{", "}")):
        i, j = texto.find(abre), texto.rfind(cierra)
        if i != -1 and j > i:
            try:
                return json.loads(texto[i:j + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError("La respuesta del LLM no contiene JSON válido")


def gemini(prompt: str, clave: str, modelo: str, temperatura: float = 1.0) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
    cuerpo = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperatura, "responseMimeType": "application/json"},
    }
    for intento in range(3):   # 503 "high demand" es frecuente y temporal
        try:
            r = requests.post(url, json=cuerpo, headers={"x-goog-api-key": clave},
                              timeout=TIMEOUT)
        except requests.RequestException as e:
            raise LLMError(f"Gemini {modelo}: error de red ({e.__class__.__name__})") from e
        if r.status_code not in (500, 502, 503) or intento == 2:
            break
        time.sleep(8 * (intento + 1))
    if r.status_code == 429:
        raise CuotaAgotada(f"Gemini {modelo}: cuota agotada (429)")
    if r.status_code >= 400:
        raise LLMError(f"Gemini {modelo}: HTTP {r.status_code} {r.text[:300]}")
    datos = r.json()
    try:
        return "".join(p.get("text", "") for p in datos["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError) as e:
        raise LLMError(f"Gemini: respuesta inesperada {str(datos)[:300]}") from e


def groq(prompt: str, clave: str, modelo: str, temperatura: float = 1.0) -> str:
    try:
        r = _post_groq(clave, modelo, temperatura, prompt)
    except requests.RequestException as e:
        raise LLMError(f"Groq {modelo}: error de red ({e.__class__.__name__})") from e
    if r.status_code == 429:
        raise CuotaAgotada(f"Groq {modelo}: cuota agotada (429)")
    if r.status_code >= 400:
        raise LLMError(f"Groq {modelo}: HTTP {r.status_code} {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"]


def _post_groq(clave: str, modelo: str, temperatura: float, prompt: str) -> requests.Response:
    return requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {clave}"},
        json={"model": modelo, "temperature": temperatura,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "user", "content": prompt}]},
        timeout=TIMEOUT)
