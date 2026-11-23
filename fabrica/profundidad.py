"""Mapas de profundidad para el modo 3D (parallax 2.5D sobre imágenes fijas).

Fuente principal: Depth Anything V2 Small (ONNX, licencia Apache-2.0) con onnxruntime, que ya
viene instalado como dependencia de Piper. Si el modelo no está descargado o falla, se usa una
estimación heurística (suelo cerca, zonas nítidas delante) para que el vídeo salga igualmente
con relieve.

Convención: 0 = lejos, 1 = cerca.

Descarga del modelo:  python -m fabrica.profundidad descargar
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from .utils import log

L = log("profundidad")

MODELO_URL = ("https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/"
              "onnx/model.onnx")
MODELO_RUTA = Path("models/depth_anything_v2_small.onnx")
LADO_RED = 518          # lado largo de entrada de la red (múltiplo de 14)
_MEDIA = np.array([0.485, 0.456, 0.406], np.float32)
_DESV = np.array([0.229, 0.224, 0.225], np.float32)


@lru_cache(maxsize=2)
def _sesion(ruta: str):
    import onnxruntime as ort
    opts = ort.SessionOptions()
    opts.log_severity_level = 3
    return ort.InferenceSession(ruta, opts, providers=["CPUExecutionProvider"])


def _red(img: np.ndarray, ruta: Path) -> np.ndarray:
    h, w = img.shape[:2]
    esc = LADO_RED / max(h, w)
    rh, rw = max(14, round(h * esc / 14) * 14), max(14, round(w * esc / 14) * 14)
    x = cv2.resize(img, (rw, rh), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    x = ((x - _MEDIA) / _DESV).transpose(2, 0, 1)[None].astype(np.float32)
    s = _sesion(str(ruta))
    salida = s.run(None, {s.get_inputs()[0].name: x})[0]
    disp = np.squeeze(salida).astype(np.float32)          # disparidad: mayor = más cerca
    return cv2.resize(disp, (w, h), interpolation=cv2.INTER_CUBIC)


def heuristica(img: np.ndarray) -> np.ndarray:
    """Profundidad aproximada sin modelo: gradiente vertical + nitidez local + centro."""
    h, w = img.shape[:2]
    peq = cv2.resize(img, (max(32, w // 4), max(32, h // 4)), interpolation=cv2.INTER_AREA)
    gris = cv2.cvtColor(peq, cv2.COLOR_RGB2GRAY).astype(np.float32)
    ph, pw = gris.shape
    yy, xx = np.mgrid[0:ph, 0:pw].astype(np.float32)
    vertical = yy / max(1, ph - 1)                        # abajo (suelo) más cerca
    nitidez = cv2.GaussianBlur(np.abs(cv2.Laplacian(gris, cv2.CV_32F)), (0, 0), 6)
    nitidez /= float(np.percentile(nitidez, 98)) + 1e-6
    centro = 1 - np.sqrt(((xx - pw / 2) / (pw / 2)) ** 2 + ((yy - ph / 2) / (ph / 2)) ** 2) / 1.42
    d = 0.55 * vertical + 0.30 * np.clip(nitidez, 0, 1) + 0.15 * centro
    return cv2.resize(d, (w, h), interpolation=cv2.INTER_CUBIC)


def _normalizar(d: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(d, (2, 98))
    return np.clip((d - lo) / max(1e-6, hi - lo), 0, 1).astype(np.float32)


def suavizar(d: np.ndarray) -> np.ndarray:
    """Dilata lo cercano antes de suavizar: al mover la cámara se estira el fondo (apenas se
    nota) en vez de deformar el contorno de las figuras del primer plano."""
    h, w = d.shape[:2]
    k = max(3, (min(h, w) // 90) | 1)
    d = cv2.dilate(d, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    d = cv2.GaussianBlur(d, (0, 0), max(2.0, min(h, w) / 160))
    return np.clip(d, 0, 1).astype(np.float32)


def estimar(img: np.ndarray, raiz: str | Path = ".", modelo: str | Path | None = None
            ) -> tuple[np.ndarray, str]:
    """Devuelve (profundidad 0..1 del mismo tamaño que img, método usado)."""
    ruta = Path(modelo) if modelo else MODELO_RUTA
    if not ruta.is_absolute():
        ruta = Path(raiz) / ruta
    metodo = "heuristica"
    d = None
    if ruta.exists():
        try:
            d = _red(img, ruta)
            metodo = "depth-anything-v2"
        except Exception as e:  # sin onnxruntime, modelo corrupto, sin memoria...
            L.warning("Profundidad con red falló (%s); uso heurística", e)
    if d is None:
        d = heuristica(img)
    return suavizar(_normalizar(d)), metodo


def descargar(raiz: str | Path = ".") -> Path:
    import requests
    destino = Path(raiz) / MODELO_RUTA
    if destino.exists() and destino.stat().st_size > 1_000_000:
        print(f"Ya está: {destino}")
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".part")
    print(f"Descargando modelo de profundidad (~100 MB) a {destino}…")
    with requests.get(MODELO_URL, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for trozo in r.iter_content(1 << 20):
                f.write(trozo)
    tmp.replace(destino)
    print("Listo.")
    return destino


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "descargar":
        descargar()
    else:
        print("Uso: python -m fabrica.profundidad descargar")
