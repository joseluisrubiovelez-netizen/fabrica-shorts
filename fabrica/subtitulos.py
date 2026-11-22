"""Subtítulos palabra a palabra: Whisper local (faster-whisper, MIT) alineado con el guion."""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .utils import log, normalizar

L = log("subtitulos")


@dataclass
class Palabra:
    texto: str
    ini: float
    fin: float


@dataclass
class Cue:
    palabras: list[Palabra]

    @property
    def ini(self) -> float:
        return self.palabras[0].ini

    @property
    def fin(self) -> float:
        return self.palabras[-1].fin

    @property
    def texto(self) -> str:
        return " ".join(p.texto for p in self.palabras)


@lru_cache(maxsize=1)
def _modelo(nombre: str):
    import os
    # Evita que los hilos OpenMP de CTranslate2 se queden girando y ralenticen el montaje
    os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")
    from faster_whisper import WhisperModel
    return WhisperModel(nombre, device="cpu", compute_type="int8")


def _cargar_16k(audio: Path):
    """Decodifica con FFmpeg a float32 mono 16 kHz (evita depender de PyAV)."""
    import subprocess

    import numpy as np

    from .utils import ffmpeg_bin
    r = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(audio), "-ac", "1", "-ar", "16000",
                        "-f", "f32le", "-"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.float32).copy()


def transcribir(audio: Path, modelo: str, pista: str) -> list[Palabra]:
    segmentos, _ = _modelo(modelo).transcribe(_cargar_16k(audio), language="es",
                                               word_timestamps=True,
                                               initial_prompt=pista[:800], vad_filter=False,
                                               beam_size=5)
    palabras = []
    for s in segmentos:
        for w in s.words or []:
            palabras.append(Palabra(w.word.strip(), float(w.start), float(w.end)))
    return palabras


def alinear(guion: list[str], whisper: list[Palabra], tramos: list[tuple[float, float]] | None = None
            ) -> list[Palabra]:
    """Usa el texto exacto del guion con los tiempos de Whisper (corrige errores de transcripción)."""
    a = [normalizar(w) for w in guion]
    b = [normalizar(w.texto) for w in whisper]
    tiempos: list[tuple[float, float] | None] = [None] * len(guion)
    for bloque in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_matching_blocks():
        for k in range(bloque.size):
            w = whisper[bloque.b + k]
            tiempos[bloque.a + k] = (w.ini, w.fin)
    # Interpolar huecos sin coincidencia
    n = len(guion)
    i = 0
    while i < n:
        if tiempos[i] is not None:
            i += 1
            continue
        j = i
        while j < n and tiempos[j] is None:
            j += 1
        t0 = tiempos[i - 1][1] if i > 0 else (tramos[0][0] if tramos else 0.0)
        t1 = tiempos[j][0] if j < n else (t0 + 0.35 * (j - i))
        pesos = [max(1, len(guion[k])) for k in range(i, j)]
        total = sum(pesos)
        acc = t0
        for k, p in zip(range(i, j), pesos):
            d = (t1 - t0) * p / total
            tiempos[k] = (acc, acc + d)
            acc += d
        i = j
    return [Palabra(g, t[0], t[1]) for g, t in zip(guion, tiempos)]  # type: ignore[index]


def proporcional(segmentos: list[str], marcas: list[tuple[float, float]]) -> list[Palabra]:
    """Respaldo sin Whisper: reparte cada segmento por longitud de palabra."""
    res: list[Palabra] = []
    for texto, (ini, fin) in zip(segmentos, marcas):
        ws = texto.split()
        total = sum(len(w) + 2 for w in ws)
        acc = ini
        for w in ws:
            d = (fin - ini) * (len(w) + 2) / total
            res.append(Palabra(w, acc, acc + d))
            acc += d
    return res


def agrupar(palabras: list[Palabra], max_palabras: int = 3, max_chars: int = 16) -> list[Cue]:
    cues: list[Cue] = []
    actual: list[Palabra] = []
    for p in palabras:
        largo = sum(len(x.texto) + 1 for x in actual) + len(p.texto)
        hueco = actual and p.ini - actual[-1].fin > 0.45
        if actual and (len(actual) >= max_palabras or largo > max_chars or hueco):
            cues.append(Cue(actual))
            actual = []
        actual.append(p)
        if p.texto[-1:] in ".?!…:;":
            cues.append(Cue(actual))
            actual = []
    if actual:
        cues.append(Cue(actual))
    # Duración mínima legible por cue
    for i, c in enumerate(cues):
        sig = cues[i + 1].ini if i + 1 < len(cues) else c.fin + 0.5
        if c.fin - c.ini < 0.45:
            c.palabras[-1].fin = min(sig, c.ini + 0.45)
    return cues
