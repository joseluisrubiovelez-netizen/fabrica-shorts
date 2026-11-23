"""Efecto 3D (parallax 2.5D) para cualquier imagen: la convierte en un clip de vídeo en el que la
cámara se mueve entre los planos de la escena, con el fondo ligeramente desenfocado.

Herramienta autónoma (no necesita la fábrica). Requisitos: Python 3.10+, FFmpeg y
`pip install -r requirements.txt`. La primera vez descarga el modelo de profundidad
Depth Anything V2 Small (~100 MB, licencia Apache-2.0) en ./modelos/.

Ejemplos:
  python efecto3d.py foto.jpg
  python efecto3d.py carpeta_de_imagenes --formato horizontal --dur 4 --mov aleatorio
  python efecto3d.py a.jpg b.jpg c.jpg --unir --salida mi_video.mp4
  python efecto3d.py foto.png --intensidad 1.5 --desenfoque 0 --guardar-profundidad
"""
from __future__ import annotations

import argparse
import math
import random
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

AQUI = Path(__file__).resolve().parent
MODELO_URL = ("https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/"
              "onnx/model.onnx")
MODELO_DEF = AQUI / "modelos" / "depth_anything_v2_small.onnx"
EXTENSIONES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
FORMATOS = {"vertical": (1080, 1920), "horizontal": (1920, 1080), "cuadrado": (1080, 1080),
            "4k-vertical": (2160, 3840), "4k-horizontal": (3840, 2160)}
MOVIMIENTOS = ["zoom_in", "zoom_out", "pan_izq", "pan_der", "pan_arriba", "pan_abajo",
               "zoom_in_izq", "zoom_out_der", "orbita"]
TRANSICION = 0.35  # fundido entre imágenes con --unir (segundos)


# ---------------------------------------------------------------- profundidad (0 lejos, 1 cerca)
@lru_cache(maxsize=1)
def _sesion(ruta: str):
    import onnxruntime as ort
    o = ort.SessionOptions()
    o.log_severity_level = 3
    return ort.InferenceSession(ruta, o, providers=["CPUExecutionProvider"])


def _con_red(img: np.ndarray, modelo: Path) -> np.ndarray:
    h, w = img.shape[:2]
    e = 518 / max(h, w)
    rh, rw = max(14, round(h * e / 14) * 14), max(14, round(w * e / 14) * 14)
    x = cv2.resize(img, (rw, rh), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    x = ((x - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]).transpose(2, 0, 1)[None]
    s = _sesion(str(modelo))
    disp = np.squeeze(s.run(None, {s.get_inputs()[0].name: x.astype(np.float32)})[0])
    return cv2.resize(disp.astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)


def _heuristica(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    g = cv2.cvtColor(cv2.resize(img, (max(32, w // 4), max(32, h // 4))),
                     cv2.COLOR_RGB2GRAY).astype(np.float32)
    ph, pw = g.shape
    yy, xx = np.mgrid[0:ph, 0:pw].astype(np.float32)
    nit = cv2.GaussianBlur(np.abs(cv2.Laplacian(g, cv2.CV_32F)), (0, 0), 6)
    nit = np.clip(nit / (np.percentile(nit, 98) + 1e-6), 0, 1)
    centro = 1 - np.hypot((xx - pw / 2) / (pw / 2), (yy - ph / 2) / (ph / 2)) / 1.42
    d = 0.55 * yy / max(1, ph - 1) + 0.30 * nit + 0.15 * centro
    return cv2.resize(d, (w, h), interpolation=cv2.INTER_CUBIC)


def profundidad(img: np.ndarray, modelo: Path | None) -> tuple[np.ndarray, str]:
    d, metodo = None, "aproximada (sin modelo)"
    if modelo and modelo.exists():
        try:
            d, metodo = _con_red(img, modelo), "Depth Anything V2"
        except Exception as e:
            print(f"  aviso: el modelo falló ({e}); uso la estimación aproximada")
    if d is None:
        d = _heuristica(img)
    lo, hi = np.percentile(d, (2, 98))
    d = np.clip((d - lo) / max(1e-6, hi - lo), 0, 1).astype(np.float32)
    # Dilatar lo cercano: al mover la cámara se estira el fondo, no el borde de las figuras
    h, w = d.shape
    k = max(3, (min(h, w) // 90) | 1)
    d = cv2.dilate(d, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    d = cv2.GaussianBlur(d, (0, 0), max(2.0, min(h, w) / 160))
    return np.clip(d, 0, 1).astype(np.float32), metodo


def descargar_modelo(destino: Path) -> Path:
    import requests
    if destino.exists() and destino.stat().st_size > 1_000_000:
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    print(f"Descargando el modelo de profundidad (~100 MB) en {destino} …")
    tmp = destino.with_suffix(".part")
    with requests.get(MODELO_URL, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        hecho = 0
        with open(tmp, "wb") as f:
            for trozo in r.iter_content(1 << 20):
                f.write(trozo)
                hecho += len(trozo)
                if total:
                    print(f"\r  {hecho * 100 // total:3d} %", end="", flush=True)
    print()
    tmp.replace(destino)
    return destino


# ---------------------------------------------------------------- cámara 3D
def _ease(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return 0.5 - 0.5 * math.cos(math.pi * x)


def parallax(mov: str, p: float, amp: float, intensidad: float) -> tuple[float, float, float]:
    """Desplazamiento x/y y zoom diferencial del plano más cercano en el instante p (0..1)."""
    q = 2 * p - 1
    ox = -amp * q if "izq" in mov else amp * q if "der" in mov else 0.0
    oy = -amp * q if mov == "pan_arriba" else amp * q if mov == "pan_abajo" else 0.0
    zp = 0.0
    if "zoom_in" in mov:
        zp = 0.09 * intensidad * p
    elif "zoom_out" in mov:
        zp = 0.09 * intensidad * (1 - p)
    if mov in ("zoom_in", "zoom_out"):
        ox = 0.45 * amp * q
    if mov == "orbita":
        ox, zp = 1.4 * amp * q, 0.03 * intensidad
    return ox, oy, zp


class Toma:
    """Una imagen con su mapa de profundidad, lista para dar fotogramas 3D."""

    def __init__(self, ruta: Path, W: int, H: int, mov: str, intensidad: float,
                 desenfoque: float, modelo: Path | None):
        img = Image.open(ruta).convert("RGB")
        e = max(W * 1.2 / img.width, H * 1.2 / img.height)
        img = img.resize((math.ceil(img.width * e), math.ceil(img.height * e)), Image.LANCZOS)
        self.img = np.ascontiguousarray(np.asarray(img))
        self.prof, self.metodo = profundidad(self.img, modelo)
        if desenfoque > 0:
            borroso = cv2.GaussianBlur(self.img, (0, 0), max(1.0, W / 220))
            peso = (min(1.0, desenfoque) * (1 - self.prof) ** 2)[:, :, None]
            self.img = np.ascontiguousarray((self.img * (1 - peso) + borroso * peso)
                                            .astype(np.uint8))
        self.W, self.H, self.mov, self.intensidad = W, H, mov, intensidad
        k = 4  # el desplazamiento es suave: se calcula a 1/4 de resolución y se amplía
        self.u, self.v = np.meshgrid(np.arange(W // k, dtype=np.float32) * k + (k - 1) / 2,
                                     np.arange(H // k, dtype=np.float32) * k + (k - 1) / 2)

    def frame(self, p: float) -> np.ndarray:
        p = _ease(p)
        ih, iw = self.img.shape[:2]
        m = self.mov
        z = (1.0 + 0.16 * p if "zoom_in" in m else 1.16 - 0.16 * p if "zoom_out" in m
             else 1.14)
        bw = min(iw, ih * self.W / self.H) / z
        bh = bw * self.H / self.W
        cx = 0.85 - 0.7 * p if "izq" in m else 0.15 + 0.7 * p if "der" in m else 0.5
        cy = 0.85 - 0.7 * p if m == "pan_arriba" else 0.15 + 0.7 * p if m == "pan_abajo" else 0.5
        x0, y0 = (iw - bw) * cx, (ih - bh) * cy
        s = self.W / bw
        ox, oy, zp = parallax(m, p, 0.035 * self.intensidad * bw, self.intensidad)
        bx, by = x0 + self.u / s, y0 + self.v / s
        ccx, ccy = x0 + bw / 2, y0 + bh / 2
        mx, my = bx, by
        for _ in range(2):
            d = cv2.remap(self.prof, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            f = 1.0 / (1.0 + zp * d)
            mx, my = ccx + (bx - ccx) * f + ox * d, ccy + (by - ccy) * f + oy * d
        mx = cv2.resize(mx, (self.W, self.H), interpolation=cv2.INTER_LINEAR)
        my = cv2.resize(my, (self.W, self.H), interpolation=cv2.INTER_LINEAR)
        return cv2.remap(self.img, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


# ---------------------------------------------------------------- vídeo
def ffmpeg() -> str:
    b = shutil.which("ffmpeg")
    if b:
        return b
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        sys.exit("No encuentro FFmpeg. Instálalo (winget install ffmpeg) o "
                 "pip install imageio-ffmpeg")


def escribir(tomas: list[Toma], dur: float, fps: int, salida: Path, crf: int) -> None:
    W, H = tomas[0].W, tomas[0].H
    salida.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [ffmpeg(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(salida)],
        stdin=subprocess.PIPE)
    n_tomas = len(tomas)
    n = int(round(dur * n_tomas * fps))
    T = TRANSICION if n_tomas > 1 else 0.0

    def prog(k: int, t: float) -> float:
        return (t - k * dur + T / 2) / (dur + T)

    try:
        for i in range(n):
            t = i / fps
            k = min(n_tomas - 1, int(t // dur))
            fr = tomas[k].frame(prog(k, t))
            fin_k = (k + 1) * dur
            if k + 1 < n_tomas and t > fin_k - T / 2:
                a = _ease((t - (fin_k - T / 2)) / T)
                fr = cv2.addWeighted(fr, 1 - a, tomas[k + 1].frame(prog(k + 1, t)), a, 0)
            elif k > 0 and t < k * dur + T / 2:
                a = _ease((t - (k * dur - T / 2)) / T)
                fr = cv2.addWeighted(tomas[k - 1].frame(prog(k - 1, t)), 1 - a, fr, a, 0)
            assert proc.stdin is not None
            proc.stdin.write(np.ascontiguousarray(fr).tobytes())
            if i % fps == 0:
                print(f"\r  {i * 100 // n:3d} %", end="", flush=True)
        assert proc.stdin is not None
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("FFmpeg falló al codificar")
        print("\r  100 %")
    finally:
        if proc.poll() is None:
            proc.kill()


def tamano(formato: str, ruta: Path) -> tuple[int, int]:
    if formato in FORMATOS:
        return FORMATOS[formato]
    if formato == "original":
        w, h = Image.open(ruta).size
        e = min(1.0, 1920 / max(w, h))
        return int(w * e) // 2 * 2, int(h * e) // 2 * 2
    try:
        w, h = (int(x) for x in formato.lower().split("x"))
        return w // 2 * 2, h // 2 * 2
    except ValueError:
        sys.exit(f"Formato no válido: {formato}. Usa {', '.join(FORMATOS)}, original o ANCHOxALTO")


def recoger(entradas: list[str]) -> list[Path]:
    rutas: list[Path] = []
    for e in entradas:
        p = Path(e)
        if p.is_dir():
            rutas += sorted(x for x in p.iterdir() if x.suffix.lower() in EXTENSIONES)
        elif p.suffix.lower() in EXTENSIONES and p.exists():
            rutas.append(p)
        else:
            print(f"Ignoro {e}: no es una imagen")
    return rutas


def main(argv: list[str] | None = None) -> int:
    for flujo in (sys.stdout, sys.stderr):  # consolas de Windows sin UTF-8: nunca romper
        try:
            flujo.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap =argparse.ArgumentParser(description="Convierte imágenes en clips con efecto 3D.")
    ap.add_argument("entradas", nargs="+", help="imágenes o carpetas con imágenes")
    ap.add_argument("--formato", default="vertical",
                    help="vertical (1080x1920), horizontal, cuadrado, 4k-vertical, "
                         "4k-horizontal, original o ANCHOxALTO")
    ap.add_argument("--dur", type=float, default=5.0, help="segundos por imagen (5)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--mov", default="aleatorio",
                    help=f"movimiento de cámara: {', '.join(MOVIMIENTOS)} o aleatorio")
    ap.add_argument("--intensidad", type=float, default=1.0, help="0.5 suave · 1 · 1.5 marcado")
    ap.add_argument("--desenfoque", type=float, default=0.5, help="desenfoque del fondo 0..1")
    ap.add_argument("--unir", action="store_true", help="un solo vídeo con todas las imágenes")
    ap.add_argument("--salida", help="carpeta de salida (o archivo .mp4 con --unir)")
    ap.add_argument("--calidad", type=int, default=18, help="CRF de H.264: menor = mejor (18)")
    ap.add_argument("--guardar-profundidad", action="store_true",
                    help="guarda también el mapa de profundidad en PNG")
    ap.add_argument("--modelo", help="ruta a otro .onnx de Depth Anything")
    ap.add_argument("--sin-modelo", action="store_true",
                    help="no descarga ni usa el modelo (estimación aproximada)")
    ap.add_argument("--semilla", type=int, help="para que 'aleatorio' salga siempre igual")
    a = ap.parse_args(argv)

    if a.mov != "aleatorio" and a.mov not in MOVIMIENTOS:
        ap.error(f"--mov debe ser uno de: {', '.join(MOVIMIENTOS)} o aleatorio")
    rutas = recoger(a.entradas)
    if not rutas:
        ap.error("no hay imágenes que procesar")
    modelo = None
    if not a.sin_modelo:
        modelo = Path(a.modelo) if a.modelo else MODELO_DEF
        if not modelo.exists() and not a.modelo:
            try:
                descargar_modelo(modelo)
            except Exception as e:
                print(f"No se pudo descargar el modelo ({e}); uso la estimación aproximada")
                modelo = None
    rng = random.Random(a.semilla)
    movs: list[str] = []
    for _ in rutas:
        if a.mov != "aleatorio":
            movs.append(a.mov)
        else:
            movs.append(rng.choice([m for m in MOVIMIENTOS if not movs or m != movs[-1]]))
    W, H = tamano(a.formato, rutas[0])

    def preparar(ruta: Path, mov: str, carpeta: Path) -> Toma:
        print(f"{ruta.name}: {mov}")
        t = Toma(ruta, W, H, mov, a.intensidad, a.desenfoque, modelo)
        print(f"  profundidad: {t.metodo}")
        if a.guardar_profundidad:
            carpeta.mkdir(parents=True, exist_ok=True)
            Image.fromarray((t.prof * 255).astype(np.uint8)).save(
                carpeta / f"{ruta.stem}_profundidad.png")
        return t

    if a.unir:
        destino = Path(a.salida) if a.salida else rutas[0].parent / "salida_3d" / "video_3d.mp4"
        if destino.suffix.lower() != ".mp4":
            destino = destino / "video_3d.mp4"
        tomas = [preparar(r, m, destino.parent) for r, m in zip(rutas, movs)]
        escribir(tomas, a.dur, a.fps, destino, a.calidad)
        print(f"Listo: {destino.resolve()}")
        return 0
    for r, m in zip(rutas, movs):
        carpeta = Path(a.salida) if a.salida else r.parent / "salida_3d"
        destino = carpeta / f"{r.stem}_3d.mp4"
        escribir([preparar(r, m, carpeta)], a.dur, a.fps, destino, a.calidad)
        print(f"  -> {destino.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
