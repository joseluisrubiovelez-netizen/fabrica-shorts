"""Voz en off con Piper TTS (local, voz es_ES-davefx: dataset CC0)."""
from __future__ import annotations

import io
import wave
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from .utils import log

L = log("voz")

PAUSA_INICIAL = 0.12
PAUSA_TRAS_GANCHO = 0.35
PAUSA_ESCENA = 0.28
PAUSA_CTA = 0.45


@dataclass
class Locucion:
    ruta: Path
    duracion: float
    sr: int
    # (inicio, fin) en segundos de cada escena visual
    tramos_escena: list[tuple[float, float]]
    length_scale: float
    # (inicio, fin) de la voz de cada segmento [gancho, escenas..., cta]
    marcas_segmento: list[tuple[float, float]]


@lru_cache(maxsize=2)
def _voz(modelo: str):
    from piper import PiperVoice
    return PiperVoice.load(modelo)


def sintetizar(texto: str, modelo: str, length_scale: float) -> tuple[np.ndarray, int]:
    from piper import SynthesisConfig
    voz = _voz(modelo)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        voz.synthesize_wav(texto, w, syn_config=SynthesisConfig(length_scale=length_scale,
                                                                noise_scale=0.6,
                                                                noise_w_scale=0.75))
    buf.seek(0)
    with wave.open(buf, "rb") as r:
        sr = r.getframerate()
        datos = np.frombuffer(r.readframes(r.getnframes()), dtype=np.int16)
    return _recortar_silencio(datos, sr), sr


def _recortar_silencio(x: np.ndarray, sr: int, umbral: int = 350) -> np.ndarray:
    activo = np.where(np.abs(x) > umbral)[0]
    if len(activo) == 0:
        return x
    margen = int(0.03 * sr)
    return x[max(0, activo[0] - margen): min(len(x), activo[-1] + margen)]


def _montar(segmentos: list[np.ndarray], sr: int, n_escenas: int
            ) -> tuple[np.ndarray, list[tuple[float, float]], list[tuple[float, float]]]:
    """segmentos = [gancho, escena1..N, cta]. Devuelve audio, tramos por escena y marcas de voz."""
    partes: list[np.ndarray] = [np.zeros(int(PAUSA_INICIAL * sr), np.int16)]
    t = PAUSA_INICIAL
    marcas: list[float] = []
    voz_seg: list[tuple[float, float]] = []
    for i, seg in enumerate(segmentos):
        marcas.append(t)
        partes.append(seg)
        voz_seg.append((t, t + len(seg) / sr))
        t += len(seg) / sr
        if i == len(segmentos) - 1:
            pausa = 0.6
        elif i == 0:
            pausa = PAUSA_TRAS_GANCHO
        elif i == len(segmentos) - 2:
            pausa = PAUSA_CTA
        else:
            pausa = PAUSA_ESCENA
        partes.append(np.zeros(int(pausa * sr), np.int16))
        t += pausa
    audio = np.concatenate(partes)
    total = len(audio) / sr
    # Escena 1 arranca en 0 (incluye gancho); la última incluye el CTA.
    inicios = [0.0] + [marcas[i + 1] - 0.05 for i in range(1, n_escenas)]
    fines = inicios[1:] + [total]
    return audio, list(zip(inicios, fines)), voz_seg


def generar_locucion(segmentos_texto: list[str], modelo: str, salida: Path,
                     dur_min: float, dur_max: float, velocidad: float = 1.0) -> Locucion:
    n_escenas = len(segmentos_texto) - 2
    ls = velocidad
    for _ in range(3):
        segs, sr = [], 22050
        for texto in segmentos_texto:
            a, sr = sintetizar(texto, modelo, ls)
            segs.append(a)
        audio, tramos, voz_seg = _montar(segs, sr, n_escenas)
        dur = len(audio) / sr
        objetivo = None
        if dur > dur_max - 0.5:
            objetivo = dur_max - 2.0
        elif dur < dur_min + 0.5:
            objetivo = dur_min + 2.0
        if objetivo is None:
            break
        nuevo = max(0.82, min(1.18, ls * objetivo / dur))
        if abs(nuevo - ls) < 0.01:
            break
        L.info("Locución de %.1fs fuera de rango; ajusto length_scale %.2f -> %.2f", dur, ls, nuevo)
        ls = nuevo
    salida.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(salida), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(audio.tobytes())
    return Locucion(salida, len(audio) / sr, sr, tramos, ls, voz_seg)
