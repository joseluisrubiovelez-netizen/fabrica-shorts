"""Utilidades compartidas: logging, normalización de texto, ffprobe, reintentos."""
from __future__ import annotations

import json
import logging
import random
import re
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def log(nombre: str) -> logging.Logger:
    return logging.getLogger(f"fabrica.{nombre}")


STOPWORDS = set("""
a al algo algun alguna algunas alguno algunos ante antes aqui asi aun cada como con contra
cual cuando de del desde donde dos el ella ellas ellos en entre era eran es esa esas ese eso
esos esta estaba estas este esto estos fue fueron ha habia han hasta hay la las le les lo los
mas me mi mis muy nada ni no nos nuestra o otra otro para pero poco por que quien se sea ser
si sin sobre su sus tambien tan te tiene todo todos tu un una unas uno unos y ya yo
""".split())


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9ñ ]+", " ", t).strip()


def tokens_clave(texto: str) -> set[str]:
    return {w for w in normalizar(texto).split() if len(w) > 2 and w not in STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def ffmpeg_bin() -> str:
    b = shutil.which("ffmpeg")
    if not b:
        raise RuntimeError("FFmpeg no está instalado o no está en el PATH")
    return b


def ffprobe_bin() -> str:
    b = shutil.which("ffprobe")
    if not b:
        raise RuntimeError("ffprobe no está instalado o no está en el PATH")
    return b


def ejecutar(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    if r.returncode != 0:
        raise RuntimeError(f"Fallo ejecutando {cmd[0]}: {r.stderr[-1500:]}")
    return r


def ffprobe(ruta: str | Path) -> dict[str, Any]:
    r = ejecutar([ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format",
                  "-show_streams", str(ruta)])
    return json.loads(r.stdout)


def duracion_audio(ruta: str | Path) -> float:
    return float(ffprobe(ruta)["format"]["duration"])


def reintentar(fn: Callable[[], T], intentos: int = 3, espera: float = 2.0,
               excepciones: tuple[type[BaseException], ...] = (Exception,),
               nombre: str = "operación") -> T:
    ultimo: BaseException | None = None
    for i in range(intentos):
        try:
            return fn()
        except excepciones as e:  # noqa: PERF203
            ultimo = e
            if i < intentos - 1:
                pausa = espera * (2 ** i) + random.uniform(0, 1)
                log("reintentos").warning("%s falló (%s). Reintento en %.1fs", nombre, e, pausa)
                time.sleep(pausa)
    assert ultimo is not None
    raise ultimo
