"""Voz en off con Gemini TTS (voces precompiladas: Puck, Kore, Charon...). REST oficial, sin SDK.

La API devuelve PCM 16 bits mono a 24 kHz en base64. Gemini no tiene "length_scale", así que la
velocidad se ajusta después con el filtro atempo de FFmpeg (mantiene el tono).
"""
from __future__ import annotations

import base64
import re
import subprocess
import time
import wave
from pathlib import Path

import numpy as np
import requests

from .llm import CuotaAgotada, LLMError
from .utils import ffmpeg_bin, log

L = log("voz_gemini")

URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
MODELOS_POR_DEFECTO = ["gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts"]
VOZ_POR_DEFECTO = "Puck"
ESTILO_POR_DEFECTO = ("Narra en castellano de España, como un narrador de misterio: "
                      "voz grave, pausada e inquietante, sin exagerar")
SR = 24000
TIMEOUT = 120


def _texto_con_estilo(texto: str, estilo: str | None) -> str:
    return f"{estilo.strip().rstrip(':')}: {texto}" if estilo else texto


def sintetizar(texto: str, clave: str, voz: str = VOZ_POR_DEFECTO,
               modelos: list[str] | None = None, estilo: str | None = ESTILO_POR_DEFECTO
               ) -> tuple[np.ndarray, int]:
    """Devuelve (muestras int16 mono, frecuencia). Prueba los modelos en orden."""
    ultimo: Exception | None = None
    for modelo in modelos or MODELOS_POR_DEFECTO:
        try:
            return _sintetizar_modelo(texto, clave, voz, modelo, estilo)
        except LLMError as e:
            L.warning("Gemini TTS %s falló: %s", modelo, e)
            ultimo = e
    assert ultimo is not None
    raise ultimo


def _sintetizar_modelo(texto: str, clave: str, voz: str, modelo: str, estilo: str | None
                       ) -> tuple[np.ndarray, int]:
    cuerpo = {
        "contents": [{"parts": [{"text": _texto_con_estilo(texto, estilo)}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voz}}},
        },
    }
    r = None
    for intento in range(3):   # 500/503 son frecuentes y temporales
        try:
            r = requests.post(URL.format(modelo=modelo), json=cuerpo,
                              headers={"x-goog-api-key": clave}, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise LLMError(f"error de red ({e.__class__.__name__})") from e
        if r.status_code not in (500, 502, 503) or intento == 2:
            break
        time.sleep(6 * (intento + 1))
    assert r is not None
    if r.status_code == 429:
        raise CuotaAgotada(f"Gemini TTS {modelo}: cuota agotada (429)")
    if r.status_code >= 400:
        raise LLMError(f"HTTP {r.status_code} {r.text[:300]}")
    datos = r.json()
    try:
        parte = next(p["inlineData"] for p in datos["candidates"][0]["content"]["parts"]
                     if "inlineData" in p)
    except (KeyError, IndexError, StopIteration) as e:
        raise LLMError(f"respuesta sin audio {str(datos)[:300]}") from e
    m = re.search(r"rate=(\d+)", parte.get("mimeType", ""))
    sr = int(m.group(1)) if m else SR
    pcm = np.frombuffer(base64.b64decode(parte["data"]), dtype="<i2").astype(np.int16)
    if len(pcm) == 0:
        raise LLMError("audio vacío")
    return pcm, sr


def cambiar_tempo(x: np.ndarray, sr: int, factor: float) -> np.ndarray:
    """factor > 1 acelera. Usa atempo de FFmpeg (no altera el tono)."""
    if abs(factor - 1.0) < 0.01:
        return x
    factor = max(0.5, min(2.0, factor))
    r = subprocess.run([ffmpeg_bin(), "-v", "error", "-f", "s16le", "-ar", str(sr), "-ac", "1",
                        "-i", "pipe:0", "-filter:a", f"atempo={factor:.4f}",
                        "-f", "s16le", "-ar", str(sr), "-ac", "1", "pipe:1"],
                       input=x.astype("<i2").tobytes(), capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"atempo falló: {r.stderr.decode(errors='replace')[-500:]}")
    return np.frombuffer(r.stdout, dtype="<i2").astype(np.int16)


def guardar_wav(x: np.ndarray, sr: int, ruta: Path) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(ruta), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(x.astype("<i2").tobytes())
    return ruta
