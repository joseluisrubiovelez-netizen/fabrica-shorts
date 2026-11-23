"""Voz en off con Gemini TTS (Google AI Studio, plan gratuito), con Piper como respaldo.

Adaptado de granja-de-reels/scripts/voz_gemini.py. Plan gratuito: 3 peticiones/min y 10/día, así
que se hace UNA sola petición por vídeo: todos los segmentos (gancho, escenas, CTA) separados por
<long pause>, y después se corta por los silencios. Los cortes se montan con las mismas pausas que
la voz de Piper (voz._montar), de modo que subtítulos, escenas y QA no cambian.

El audio bruto se guarda junto al vídeo para que los reintentos de QA no gasten otra petición.
Un 429 nunca se reintenta: se marca el día como agotado y la fábrica sigue con Piper.
"""
from __future__ import annotations

import base64
import io
import itertools
import math
import subprocess
import time
import wave
from pathlib import Path

import numpy as np
import requests

from .utils import ffmpeg_bin, log
from .voz import PAUSA_INICIAL, Locucion, _montar, _recortar_silencio

L = log("voz_gemini")

URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
MODELO = "gemini-3.8-flash-tts"
SR = 24000
SEPARADOR = " <long pause> "
ESTILO = ("Narrador de historias de misterio en español de España, con acento peninsular castellano "
          "(no latinoamericano). Voz grave y cercana, tono de confidencia que crea tensión, ritmo "
          "ágil pero sin atropellarse; pausa breve tras cada punto.")
VOCES = {"Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede", "Callirrhoe",
         "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba", "Despina", "Erinome", "Algenib",
         "Rasalgethi", "Laomedeia", "Achernar", "Alnilam", "Schedar", "Gacrux", "Pulcherrima",
         "Achird", "Zubenelgenubi", "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat"}
LICENCIA = ("Gemini API TTS (Google AI Studio, plan gratuito); voz sintética, Google no reclama "
            "la propiedad del audio generado")


GANCHO_FIN_MAX = 2.85       # s: el QA exige que el gancho termine antes de ~3 s
GANCHO_ACELERACION_MAX = 1.35


def ajustar_gancho(trozo: np.ndarray, sr: int, fin_max: float = GANCHO_FIN_MAX,
                   tope: float = GANCHO_ACELERACION_MAX) -> np.ndarray:
    """Acelera solo el gancho si, tras la pausa inicial, no acabaría antes de `fin_max`.
    Gemini narra con más calma que Piper y el gancho se pasaba de 3 s en casi todos los vídeos."""
    dur = len(trozo) / sr
    disponible = fin_max - PAUSA_INICIAL
    if dur <= disponible:
        return trozo
    factor = min(tope, dur / disponible)
    L.info("Gancho de %.2fs: lo acelero x%.2f para que acabe antes de %.1fs", dur, factor, fin_max)
    return atempo(trozo, sr, factor)


class GeminiVozError(RuntimeError):
    """Fallo recuperable: la fábrica pasa a Piper."""


class CuotaTTSAgotada(GeminiVozError):
    pass


# ----------------------------------------------------------------------------- API
def pedir_audio(texto: str, clave: str, voz: str, modelo: str = MODELO, estilo: str = ESTILO
                ) -> bytes:
    if voz not in VOCES:
        raise GeminiVozError(f"voz desconocida «{voz}»")
    cuerpo = {"model": modelo,
              "input": [{"type": "user_input", "content": [{
                  "type": "text", "text": texto,
                  "annotations": [{"type": "speech_metadata", "style": estilo}]}]}],
              "response_format": {"type": "audio"},
              "generation_config": {"speech_config": [{"voice": voz}]}}
    for intento in range(3):
        try:
            r = requests.post(URL, json=cuerpo, headers={"x-goog-api-key": clave}, timeout=180)
        except requests.RequestException as e:
            if intento < 2:
                time.sleep(5)
                continue
            raise GeminiVozError(f"error de red ({e.__class__.__name__})") from e
        if r.status_code == 429:   # cupo agotado: nunca se reintenta
            raise CuotaTTSAgotada("Gemini TTS: cupo gratuito agotado (429)")
        if r.status_code in (500, 502, 503) and intento < 2:
            time.sleep(5 * (intento + 1))
            continue
        if r.status_code >= 400:
            raise GeminiVozError(f"HTTP {r.status_code} {r.text[:300]}")
        return audio_de(r.json())
    raise GeminiVozError("sin respuesta")


def audio_de(resp: dict) -> bytes:
    for st in resp.get("steps", []):
        if st.get("type") != "model_output":
            continue
        for c in st.get("content", []):
            if c.get("type") == "audio" and c.get("data"):
                return base64.b64decode(c["data"])
    raise GeminiVozError("la respuesta no trae audio")


def a_pcm(datos: bytes) -> tuple[np.ndarray, int]:
    """PCM 16 bit mono, tanto si llega con cabecera WAV como en bruto (s16le 24 kHz)."""
    if datos[:4] == b"RIFF":
        with wave.open(io.BytesIO(datos), "rb") as w:
            sr, canales = w.getframerate(), w.getnchannels()
            x = np.frombuffer(w.readframes(w.getnframes()), np.int16)
        if canales > 1:
            x = x.reshape(-1, canales).mean(axis=1).astype(np.int16)
        return x, sr
    return np.frombuffer(datos[: len(datos) // 2 * 2], np.int16).copy(), SR


def guardar_wav(x: np.ndarray, sr: int, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(ruta), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(x.astype(np.int16).tobytes())


def leer_wav(ruta: Path) -> tuple[np.ndarray, int]:
    return a_pcm(ruta.read_bytes())


def atempo(x: np.ndarray, sr: int, factor: float) -> np.ndarray:
    """Cambia la velocidad sin cambiar el tono (ffmpeg atempo)."""
    if abs(factor - 1.0) < 0.005:
        return x
    r = subprocess.run([ffmpeg_bin(), "-v", "error", "-f", "s16le", "-ar", str(sr), "-ac", "1",
                        "-i", "-", "-af", f"atempo={factor:.4f}", "-f", "s16le", "-"],
                       input=x.astype(np.int16).tobytes(), capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.int16).copy()


# ----------------------------------------------------------------------------- corte por silencios
def silencios(x: np.ndarray, sr: int, umbral_db: float = -35.0, minimo: float = 0.30
              ) -> list[tuple[float, float]]:
    """[(inicio, fin)] de los tramos por debajo de umbral_db (dBFS) durante al menos `minimo` s."""
    paso = int(0.02 * sr)
    if len(x) < paso:
        return []
    n = len(x) // paso
    tramas = x[: n * paso].astype(np.float32).reshape(n, paso) / 32768.0
    db = 20 * np.log10(np.sqrt((tramas ** 2).mean(axis=1)) + 1e-9)
    res, ini = [], None
    for i, silencio in enumerate(db < umbral_db):
        if silencio and ini is None:
            ini = i
        elif not silencio and ini is not None:
            if (i - ini) * paso / sr >= minimo:
                res.append((ini * paso / sr, i * paso / sr))
            ini = None
    if ini is not None and (n - ini) * paso / sr >= minimo:
        res.append((ini * paso / sr, n * paso / sr))
    return res


def _tramos(cortes, total: float, n: int) -> list[tuple[float, float]]:
    bordes = [0.0] + [c for s in cortes for c in s] + [total]
    return [(bordes[2 * i], bordes[2 * i + 1]) for i in range(n)]


def elegir_cortes(sil: list[tuple[float, float]], total: float, palabras: list[int]
                  ) -> list[tuple[float, float]] | None:
    """Elige N-1 silencios: premia los largos y castiga que el ritmo (palabras/s) varíe entre
    segmentos (una pausa natural dentro de una escena puede ser más larga que la de corte)."""
    n = len(palabras)
    if n == 1:
        return []
    cand = sorted(sorted(sil, key=lambda s: s[1] - s[0], reverse=True)[:14])
    mejor, mejor_p = None, None
    for comb in itertools.combinations(cand, n - 1):
        tr = _tramos(comb, total, n)
        if any(b - a < 0.4 for a, b in tr):
            continue
        med = sum(palabras) / sum(b - a for a, b in tr)
        disp = sum(math.log((p / (b - a)) / med) ** 2 for p, (a, b) in zip(palabras, tr))
        punt = sum(b - a for a, b in comb) - disp
        if mejor_p is None or punt > mejor_p:
            mejor, mejor_p = list(comb), punt
    return mejor


def cortar(x: np.ndarray, sr: int, textos: list[str]) -> list[np.ndarray]:
    """Parte el audio completo en un trozo por texto. Lanza GeminiVozError si no cuadra."""
    total = len(x) / sr
    palabras = [max(1, len(t.split())) for t in textos]
    n = len(textos)
    sil = [(a, b) for a, b in silencios(x, sr) if a > 0.2 and b < total - 0.2]
    cortes = elegir_cortes(sil, total, palabras) if len(sil) >= n - 1 else None
    if cortes is None:
        raise GeminiVozError(f"solo {len(sil)} silencios para {n - 1} cortes")
    tramos = _tramos(cortes, total, n)
    ritmo = sum(palabras) / sum(b - a for a, b in tramos)
    malos = [i for i, (p, (a, b)) in enumerate(zip(palabras, tramos))
             if not 0.45 <= (p / max(0.1, b - a)) / ritmo <= 2.2]
    if malos:
        raise GeminiVozError(f"el corte no cuadra con los segmentos {malos}")
    return [_recortar_silencio(x[int(a * sr): int(b * sr)], sr) for a, b in tramos]


# ----------------------------------------------------------------------------- locución
def generar_locucion(segmentos_texto: list[str], salida: Path, dur_min: float, dur_max: float,
                     clave: str | None, voz: str, velocidad: float = 1.0,
                     bruto: Path | None = None, modelo: str = MODELO,
                     estilo: str = ESTILO) -> tuple[Locucion, bool]:
    """Devuelve (locución, hizo_peticion). Reutiliza `bruto` si existe (reintentos sin coste)."""
    textos = [" ".join(t.replace("*", "").split()) for t in segmentos_texto]
    pidio = False
    if bruto and bruto.exists():
        x, sr = leer_wav(bruto)
        L.info("Reutilizo la voz de Gemini ya generada (%s)", bruto.name)
    else:
        if not clave:
            raise GeminiVozError("falta GEMINI_API_KEY")
        x, sr = a_pcm(pedir_audio(SEPARADOR.join(textos), clave, voz, modelo, estilo))
        pidio = True
        if bruto:
            guardar_wav(x, sr, bruto)
    n_escenas = len(textos) - 2
    factor = velocidad
    for _ in range(3):
        trozos = cortar(atempo(x, sr, factor), sr, textos)
        trozos[0] = ajustar_gancho(trozos[0], sr)
        audio, tramos, voz_seg = _montar(trozos, sr, n_escenas)
        dur = len(audio) / sr
        objetivo = dur_max - 2.0 if dur > dur_max - 0.5 else dur_min + 2.0 if dur < dur_min + 0.5 \
            else None
        if objetivo is None:
            break
        nuevo = max(0.85, min(1.25, factor * dur / objetivo))
        if abs(nuevo - factor) < 0.01:
            break
        L.info("Voz Gemini de %.1fs fuera de rango; velocidad x%.2f -> x%.2f", dur, factor, nuevo)
        factor = nuevo
    guardar_wav(audio, sr, salida)
    return Locucion(salida, len(audio) / sr, sr, tramos, 1.0 / factor, voz_seg), pidio
