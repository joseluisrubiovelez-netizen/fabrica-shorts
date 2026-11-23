"""Montaje 1080x1920: movimiento Ken Burns/parallax, clips, transiciones, textos y subtítulos.

Los fotogramas se componen en Python (Pillow) y se envían por tubería a FFmpeg (H.264 + AAC).
"""
from __future__ import annotations

import math
import random
import subprocess
import textwrap
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from .subtitulos import Cue
from .utils import ffmpeg_bin, log

L = log("render")

MOVIMIENTOS = ["zoom_in", "zoom_out", "pan_izq", "pan_der", "pan_arriba", "pan_abajo",
               "zoom_in_izq", "zoom_out_der"]
TRANSICION = 0.35
AMARILLO = (255, 211, 77, 255)
BLANCO = (255, 255, 255, 255)

FUENTES = [
    "fonts/Anton-Regular.ttf",
    "fonts/BebasNeue-Regular.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/impact.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


@lru_cache(maxsize=32)
def fuente(tam: int, preferida: str | None = None, raiz: str = ".") -> ImageFont.FreeTypeFont:
    candidatas = ([preferida] if preferida else []) + FUENTES
    for c in candidatas:
        p = Path(c) if Path(c).is_absolute() else Path(raiz) / c
        if p.exists():
            return ImageFont.truetype(str(p), tam)
    return ImageFont.load_default(tam)


@dataclass
class Escena:
    tipo: str                 # imagen | clip
    ruta: Path
    ini: float
    fin: float
    movimiento: str
    texto_pantalla: str = ""


@dataclass
class Estilo:
    saturacion: float = 0.8
    contraste: float = 1.08
    tinte: tuple[float, float, float] = (1.0, 1.0, 1.0)
    etiqueta: str = ""
    fuente: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _ease(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return 0.5 - 0.5 * math.cos(math.pi * x)


def graduar(img: Image.Image, e: Estilo) -> Image.Image:
    img = ImageEnhance.Color(img).enhance(e.saturacion)
    img = ImageEnhance.Contrast(img).enhance(e.contraste)
    arr = np.asarray(img, np.float32) * np.array(e.tinte, np.float32)
    h, w = arr.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    arr *= np.clip(1.12 - d * 0.42, 0.45, 1.0)[:, :, None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


@dataclass
class Modo3D:
    """Parallax 2.5D: cada píxel se mueve según su profundidad, como una cámara real."""
    activo: bool = False
    intensidad: float = 1.0          # separación entre planos (0.5 suave, 1.5 marcado)
    desenfoque_fondo: float = 0.5    # 0 = todo nítido, 1 = fondo muy desenfocado
    modelo: str | None = None        # ruta al .onnx (por defecto models/depth_anything_...)

    @classmethod
    def desde(cls, d: dict[str, Any] | None) -> "Modo3D":
        d = d or {}
        return cls(activo=bool(d.get("activo", False)),
                   intensidad=float(d.get("intensidad", 1.0)),
                   desenfoque_fondo=float(d.get("desenfoque_fondo", 0.5)),
                   modelo=d.get("modelo"))


def parametros_parallax(movimiento: str, p: float, amp: float, intensidad: float
                        ) -> tuple[float, float, float]:
    """(desplazamiento x, desplazamiento y, zoom diferencial) del plano más cercano.

    Los cercanos se desplazan más que el fondo en el sentido del barrido y crecen más al
    acercarse: es lo que el ojo lee como profundidad."""
    q = 2 * p - 1
    ox = oy = 0.0
    if "izq" in movimiento:
        ox = -amp * q
    elif "der" in movimiento:
        ox = amp * q
    if movimiento == "pan_arriba":
        oy = -amp * q
    elif movimiento == "pan_abajo":
        oy = amp * q
    zp = 0.0
    if "zoom_in" in movimiento:
        zp = 0.09 * intensidad * p
    elif "zoom_out" in movimiento:
        zp = 0.09 * intensidad * (1 - p)
    if movimiento in ("zoom_in", "zoom_out"):
        ox = 0.45 * amp * q          # leve órbita lateral para que el relieve se note
    return ox, oy, zp


class FuenteImagen:
    """Imagen fija con movimiento de cámara suave (subpíxel, sin temblores).

    Con el modo 3D activo, la imagen se separa en planos según un mapa de profundidad y la
    cámara se mueve entre ellos (parallax), con el fondo ligeramente desenfocado."""

    def __init__(self, esc: Escena, W: int, H: int, estilo: Estilo,
                 modo3d: Modo3D | None = None, raiz: str = "."):
        img = Image.open(esc.ruta).convert("RGB")
        escala = max(W * 1.2 / img.width, H * 1.2 / img.height)
        img = img.resize((math.ceil(img.width * escala), math.ceil(img.height * escala)),
                         Image.LANCZOS)
        self.img = np.ascontiguousarray(np.asarray(graduar(img, estilo)))
        self.W, self.H, self.esc = W, H, esc
        self.dur = (esc.fin - esc.ini) + TRANSICION
        self.modo3d = modo3d if modo3d and modo3d.activo else None
        self.prof: np.ndarray | None = None
        self.metodo_prof = ""
        if self.modo3d:
            from . import profundidad
            self.prof, self.metodo_prof = profundidad.estimar(self.img, raiz, self.modo3d.modelo)
            dof = max(0.0, min(1.0, self.modo3d.desenfoque_fondo))
            if dof > 0:
                borroso = cv2.GaussianBlur(self.img, (0, 0), max(1.0, W / 220))
                peso = (dof * (1 - self.prof) ** 2)[:, :, None]
                self.img = np.ascontiguousarray(
                    (self.img * (1 - peso) + borroso * peso).astype(np.uint8))
            # El desplazamiento es suave: se calcula a 1/4 de resolución y se amplía. La
            # muestra i corresponde al píxel k·i + (k-1)/2 (centros de cv2.resize).
            k = 4
            self.u, self.v = np.meshgrid(
                np.arange(W // k, dtype=np.float32) * k + (k - 1) / 2,
                np.arange(H // k, dtype=np.float32) * k + (k - 1) / 2)

    def _frame_3d(self, x0: float, y0: float, bw: float, bh: float, s: float,
                  p: float) -> np.ndarray:
        assert self.modo3d is not None and self.prof is not None
        amp = 0.035 * self.modo3d.intensidad * bw
        ox, oy, zp = parametros_parallax(self.esc.movimiento, p, amp, self.modo3d.intensidad)
        bx = x0 + self.u / s
        by = y0 + self.v / s
        cx, cy = x0 + bw / 2, y0 + bh / 2
        mx, my = bx, by
        for _ in range(2):  # la profundidad se lee donde cae la muestra: 2 pasadas bastan
            d = cv2.remap(self.prof, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            f = 1.0 / (1.0 + zp * d)
            mx = cx + (bx - cx) * f + ox * d
            my = cy + (by - cy) * f + oy * d
        tam = (self.W, self.H)
        mx = cv2.resize(mx, tam, interpolation=cv2.INTER_LINEAR)
        my = cv2.resize(my, tam, interpolation=cv2.INTER_LINEAR)
        return cv2.remap(self.img, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

    def frame(self, t: float) -> np.ndarray:
        p = _ease((t - self.esc.ini + TRANSICION / 2) / self.dur)
        ih, iw = self.img.shape[:2]
        m = self.esc.movimiento
        z0, z1 = 1.0, 1.0
        if "zoom_in" in m:
            z0, z1 = 1.0, 1.16
        elif "zoom_out" in m:
            z0, z1 = 1.16, 1.0
        else:
            z0 = z1 = 1.14
        z = z0 + (z1 - z0) * p
        # Ventana (en píxeles de la imagen fuente) con la proporción de salida
        bw = min(iw, ih * self.W / self.H) / z
        bh = bw * self.H / self.W
        libre_x, libre_y = iw - bw, ih - bh
        cx, cy = 0.5, 0.5
        if "izq" in m:
            cx = 0.85 - 0.7 * p
        elif "der" in m:
            cx = 0.15 + 0.7 * p
        if m == "pan_arriba":
            cy = 0.85 - 0.7 * p
        elif m == "pan_abajo":
            cy = 0.15 + 0.7 * p
        x0, y0 = libre_x * cx, libre_y * cy
        s = self.W / bw
        if self.modo3d:
            return self._frame_3d(x0, y0, bw, bh, s, p)
        M = np.float32([[s, 0, -x0 * s], [0, s, -y0 * s]])
        return cv2.warpAffine(self.img, M, (self.W, self.H), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REFLECT)

    def cerrar(self) -> None:
        pass


class FuenteClip:
    """Clip de stock decodificado por FFmpeg a 1080x1920, graduado y en bucle si es corto."""

    def __init__(self, esc: Escena, W: int, H: int, fps: int, estilo: Estilo):
        self.W, self.H, self.fps, self.esc = W, H, fps, esc
        self.t0 = esc.ini - TRANSICION / 2
        dur = (esc.fin - esc.ini) + TRANSICION + 0.5
        r, g, b = estilo.tinte
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={fps},"
              f"eq=saturation={estilo.saturacion}:contrast={estilo.contraste},"
              f"colorchannelmixer=rr={r}:gg={g}:bb={b},vignette=PI/4.5")
        self.proc = subprocess.Popen(
            [ffmpeg_bin(), "-v", "error", "-stream_loop", "-1", "-i", str(esc.ruta), "-t",
             f"{dur:.2f}", "-an", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            stdout=subprocess.PIPE)
        self.idx = -1
        self.ultimo = np.zeros((H, W, 3), np.uint8)

    def frame(self, t: float) -> np.ndarray:
        objetivo = int((t - self.t0) * self.fps)
        tam = self.W * self.H * 3
        while self.idx < objetivo:
            datos = self.proc.stdout.read(tam) if self.proc.stdout else b""
            if len(datos) < tam:
                break
            self.ultimo = np.frombuffer(datos, np.uint8).reshape(self.H, self.W, 3)
            self.idx += 1
        return self.ultimo

    def cerrar(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()


def _caja_texto(texto: str, tam: int, ancho_max: int, estilo: Estilo, raiz: str,
                color=BLANCO, caja: bool = True) -> Image.Image:
    f = fuente(tam, estilo.fuente, raiz)
    chars = max(8, int(ancho_max / (tam * 0.55)))
    lineas = textwrap.wrap(texto, width=chars) or [""]
    medidas = [f.getbbox(l) for l in lineas]
    alto_l = int(tam * 1.18)
    w = max(m[2] - m[0] for m in medidas) + 60
    h = alto_l * len(lineas) + 40
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if caja:
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=22, fill=(0, 0, 0, 150))
    for i, l in enumerate(lineas):
        lw = f.getbbox(l)[2]
        d.text(((w - lw) / 2, 20 + i * alto_l), l, font=f, fill=color,
               stroke_width=max(2, tam // 18), stroke_fill=(0, 0, 0, 255))
    return img


class Capa:
    """Overlay RGBA precalculado en numpy para componer rápido sobre el fotograma."""

    def __init__(self, img: Image.Image):
        arr = np.asarray(img.convert("RGBA"), np.float32)
        self.rgb = arr[:, :, :3]
        self.a = arr[:, :, 3:4] / 255.0
        self.h, self.w = arr.shape[:2]

    def pegar(self, base: np.ndarray, cx: float, y: int, alfa: float = 1.0) -> None:
        if alfa <= 0:
            return
        H, W = base.shape[:2]
        x0 = int(cx - self.w / 2)
        xa, ya = max(0, x0), max(0, y)
        xb, yb = min(W, x0 + self.w), min(H, y + self.h)
        if xb <= xa or yb <= ya:
            return
        a = self.a[ya - y:yb - y, xa - x0:xb - x0] * alfa
        roi = base[ya:yb, xa:xb].astype(np.float32)
        base[ya:yb, xa:xb] = (roi * (1 - a) + self.rgb[ya - y:yb - y, xa - x0:xb - x0] * a
                              ).astype(np.uint8)


class Subtitulador:
    """Pre-renderiza cada cue con la palabra activa resaltada."""

    def __init__(self, cues: list[Cue], W: int, estilo: Estilo, raiz: str, tam: int = 76):
        self.cues, self.W, self.estilo, self.raiz, self.tam = cues, W, estilo, raiz, tam
        self.cache: dict[tuple[int, int], Capa] = {}
        self.f = fuente(tam, estilo.fuente, raiz)

    def _render(self, ci: int, wi: int) -> Capa:
        cue = self.cues[ci]
        palabras = [p.texto.upper() for p in cue.palabras]
        esp = self.f.getbbox(" ")[2] or self.tam // 3
        anchos = [self.f.getbbox(p)[2] for p in palabras]
        lineas: list[list[int]] = [[]]
        ancho_lin = 0
        for i, a in enumerate(anchos):
            if lineas[-1] and ancho_lin + a > self.W - 170:
                lineas.append([])
                ancho_lin = 0
            lineas[-1].append(i)
            ancho_lin += a + esp
        alto_l = int(self.tam * 1.15)
        img = Image.new("RGBA", (self.W, alto_l * len(lineas) + 30), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for li, idxs in enumerate(lineas):
            total = sum(anchos[i] for i in idxs) + esp * (len(idxs) - 1)
            x = (self.W - total) / 2
            for i in idxs:
                d.text((x, 10 + li * alto_l), palabras[i], font=self.f,
                       fill=AMARILLO if i == wi else BLANCO,
                       stroke_width=7, stroke_fill=(0, 0, 0, 255))
                x += anchos[i] + esp
        return Capa(img)

    def en(self, t: float) -> Capa | None:
        for ci, c in enumerate(self.cues):
            if c.ini - 0.05 <= t < c.fin + 0.08:
                wi = 0
                for i, p in enumerate(c.palabras):
                    if t >= p.ini - 0.03:
                        wi = i
                clave = (ci, wi)
                if clave not in self.cache:
                    self.cache[clave] = self._render(ci, wi)
                return self.cache[clave]
        return None


def montar(escenas: list[Escena], cues: list[Cue], audio: Path, salida: Path, *,
           gancho: str, etiqueta_sup: str, estilo: Estilo, duracion: float, W: int = 1080,
           H: int = 1920, fps: int = 30, crf: int = 20, raiz: str = ".",
           preset: str = "veryfast", modo3d: Modo3D | None = None) -> Path:
    fuentes: list[Any] = []
    for e in escenas:
        fuentes.append(FuenteClip(e, W, H, fps, estilo) if e.tipo == "clip"
                       else FuenteImagen(e, W, H, estilo, modo3d, raiz))
    metodos = sorted({f.metodo_prof for f in fuentes if getattr(f, "metodo_prof", "")})
    if metodos:
        L.info("Modo 3D activo (profundidad: %s)", ", ".join(metodos))
    sub = Subtitulador(cues, W, estilo, raiz)
    capa_gancho = Capa(_caja_texto(gancho.upper(), 84, W - 200, estilo, raiz))
    fin_gancho = min(2.9, escenas[0].fin)
    capa_etq = Capa(_caja_texto(etiqueta_sup, 38, W - 300, estilo, raiz,
                                color=(235, 235, 235, 255)))
    capas_esc = [(Capa(_caja_texto(e.texto_pantalla.upper(), 58, W - 260, estilo, raiz,
                                   color=AMARILLO, caja=False)) if e.texto_pantalla else None)
                 for e in escenas]

    salida.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg_bin(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
           f"{W}x{H}", "-r", str(fps), "-i", "-", "-i", str(audio),
           "-vf", "noise=alls=6:allf=t+u,format=yuv420p", "-c:v", "libx264", "-preset", preset,
           "-crf", str(crf), "-profile:v", "high", "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
           "-shortest", "-movflags", "+faststart", str(salida)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    n = int(math.ceil(duracion * fps))
    try:
        for i in range(n):
            t = i / fps
            k = next((j for j, e in enumerate(escenas) if t < e.fin), len(escenas) - 1)
            frame = fuentes[k].frame(t)
            # Fundido cruzado entre escenas
            if k + 1 < len(escenas) and t > escenas[k].fin - TRANSICION / 2:
                a = _ease((t - (escenas[k].fin - TRANSICION / 2)) / TRANSICION)
                frame = cv2.addWeighted(frame, 1 - a, fuentes[k + 1].frame(t), a, 0)
            elif k > 0 and t < escenas[k].ini + TRANSICION / 2:
                a = _ease((t - (escenas[k].ini - TRANSICION / 2)) / TRANSICION)
                frame = cv2.addWeighted(fuentes[k - 1].frame(t), 1 - a, frame, a, 0)
            lienzo = np.array(frame, dtype=np.uint8, copy=True)
            capa_etq.pegar(lienzo, W / 2, 140, 0.92)
            if t < fin_gancho:
                # Durante el gancho solo se ve el texto grande (los subtítulos lo repetirían)
                alfa = 1.0 if t < fin_gancho - 0.25 else (fin_gancho - t) / 0.25
                capa_gancho.pegar(lienzo, W / 2, int(H * 0.27), alfa)
            else:
                if capas_esc[k] is not None:
                    dt = t - max(escenas[k].ini, fin_gancho)
                    capas_esc[k].pegar(lienzo, W / 2, int(H * 0.28), min(1.0, dt / 0.3))
                s = sub.en(t)
                if s is not None:
                    s.pegar(lienzo, W / 2, int(H * 0.60))
            if t > duracion - 0.45:
                lienzo = (lienzo * max(0.0, (duracion - t) / 0.45)).astype(np.uint8)
            assert proc.stdin is not None
            proc.stdin.write(lienzo.tobytes())
        assert proc.stdin is not None
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        if proc.wait() != 0:
            raise RuntimeError(f"FFmpeg falló al codificar: {err[-1000:]}")
    finally:
        for f in fuentes:
            f.cerrar()
        if proc.poll() is None:
            proc.kill()
    return salida


def elegir_movimientos(n: int, rng: random.Random) -> list[str]:
    res: list[str] = []
    for _ in range(n):
        opciones = [m for m in MOVIMIENTOS if not res or m != res[-1]]
        res.append(rng.choice(opciones))
    return res


def iterar_tiempos(duracion: float, fps: int) -> Iterator[float]:
    for i in range(int(math.ceil(duracion * fps))):
        yield i / fps
