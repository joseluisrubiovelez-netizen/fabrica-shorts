"""Música y efectos bajo la voz: biblioteca con licencia registrada o generación procedural.

Mezcla con FFmpeg: ducking (sidechaincompress) de la música bajo la voz y normalización a -14 LUFS.
"""
from __future__ import annotations

import random
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from . import procedural
from .utils import ejecutar, ffmpeg_bin, log

L = log("audio")
SR = procedural.SR


@dataclass
class RecursoAudio:
    tipo: str          # musica | sfx
    proveedor: str
    fuente: str
    licencia: str
    ruta: str | None
    atribucion: str | None = None


def biblioteca(carpeta: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Solo devuelve archivos con licencia declarada en licencias.yaml (regla 3)."""
    meta_ruta = carpeta / "licencias.yaml"
    if not meta_ruta.exists():
        return []
    meta = yaml.safe_load(meta_ruta.read_text(encoding="utf-8")) or {}
    res = []
    for nombre, info in meta.items():
        p = carpeta / nombre
        if p.exists() and info and info.get("licencia") and info.get("fuente"):
            res.append((p, info))
    return res


def _leer_wav_ffmpeg(ruta: Path, duracion: float | None = None) -> np.ndarray:
    args = [ffmpeg_bin(), "-v", "error"]
    if duracion:
        args += ["-stream_loop", "-1"]
    args += ["-i", str(ruta)]
    if duracion:
        args += ["-t", f"{duracion:.2f}"]
    args += ["-ac", "2", "-ar", str(SR), "-f", "s16le", "-"]
    import subprocess
    r = subprocess.run(args, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="replace")[-500:])
    return np.frombuffer(r.stdout, np.int16).reshape(-1, 2).astype(np.float64) / 32768


def construir_fondo(duracion: float, sfx_por_escena: list[tuple[float, str]], semilla: str,
                    raiz: Path, carpeta: Path, musica_db: float, sfx_db: float,
                    rng: random.Random) -> tuple[Path, list[RecursoAudio]]:
    n = int(duracion * SR)
    recursos: list[RecursoAudio] = []
    musicas = biblioteca(raiz / "assets" / "musica")
    if musicas:
        ruta, info = rng.choice(musicas)
        m = _leer_wav_ffmpeg(ruta, duracion)[:n]
        recursos.append(RecursoAudio("musica", info.get("proveedor", "biblioteca"), info["fuente"],
                                     info["licencia"], str(ruta), info.get("atribucion")))
    else:
        mono = procedural.musica(duracion, semilla)
        m = np.stack([mono, mono], axis=1)[:n]
        recursos.append(RecursoAudio("musica", "procedural", "generado localmente",
                                     procedural.LICENCIA_PROPIA, None))
    m = np.pad(m, ((0, max(0, n - len(m))), (0, 0)))
    fade = int(1.2 * SR)
    env = np.ones(n)
    env[:fade] = np.linspace(0.2, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    fondo = m * env[:, None] * 10 ** (musica_db / 20) / max(1e-6, np.max(np.abs(m)))

    sfx_lib = {p.stem.split("_")[0]: (p, info) for p, info in biblioteca(raiz / "assets" / "sfx")}
    for t0, nombre in sfx_por_escena:
        if nombre in ("", "ninguno", None):
            continue
        if nombre in sfx_lib:
            p, info = sfx_lib[nombre]
            x = _leer_wav_ffmpeg(p)
            recursos.append(RecursoAudio("sfx", info.get("proveedor", "biblioteca"), info["fuente"],
                                         info["licencia"], str(p), info.get("atribucion")))
        else:
            mono = procedural.sfx(nombre, semilla + str(t0))
            x = np.stack([mono, mono], axis=1)
            recursos.append(RecursoAudio("sfx", "procedural", f"sfx:{nombre}",
                                         procedural.LICENCIA_PROPIA, None))
        i0 = int(max(0.0, t0) * SR)
        x = x[: max(0, n - i0)] * 10 ** (sfx_db / 20) / max(1e-6, np.max(np.abs(x)))
        fondo[i0:i0 + len(x)] += x
    ruta_fondo = carpeta / "fondo.wav"
    procedural.guardar_wav(fondo, ruta_fondo)
    return ruta_fondo, recursos


def mezclar(voz: Path, fondo: Path, salida: Path, lufs: float = -14.0) -> Path:
    filtro = (
        "[0:a]aresample=44100,aformat=channel_layouts=stereo,highpass=f=70,"
        "acompressor=threshold=-20dB:ratio=3:attack=5:release=80,asplit=2[v1][v2];"
        "[1:a][v2]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=350[bg];"
        "[v1][bg]amix=inputs=2:duration=longest:normalize=0,"
        f"loudnorm=I={lufs}:TP=-1.5:LRA=9[out]")
    ejecutar([ffmpeg_bin(), "-y", "-v", "error", "-i", str(voz), "-i", str(fondo),
              "-filter_complex", filtro, "-map", "[out]", "-ar", "44100", str(salida)])
    return salida


def duracion_wav(ruta: Path) -> float:
    with wave.open(str(ruta), "rb") as w:
        return w.getnframes() / w.getframerate()
