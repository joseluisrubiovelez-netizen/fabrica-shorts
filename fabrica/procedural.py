"""Recursos generados por código propio (sin licencias de terceros).

Se usan como respaldo sin conexión: fondos atmosféricos, música ambiental y efectos de sonido.
"""
from __future__ import annotations

import hashlib
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

LICENCIA_PROPIA = "Propia: generado proceduralmente por el código del proyecto (sin terceros)"
SR = 44100


def _rng(semilla: str) -> np.random.Generator:
    return np.random.default_rng(int(hashlib.sha256(semilla.encode()).hexdigest()[:12], 16))


# ----------------------------------------------------------------------------- imágenes
def _ruido(rng: np.random.Generator, w: int, h: int, octavas: int = 4) -> np.ndarray:
    total = np.zeros((h, w), np.float32)
    amp, escala = 1.0, 6
    for _ in range(octavas):
        peq = rng.random((max(2, int(h / w * escala)), escala)).astype(np.float32)
        img = Image.fromarray((peq * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
        total += amp * (np.asarray(img, np.float32) / 255.0)
        amp *= 0.5
        escala *= 2
    total -= total.min()
    return total / max(1e-6, total.max())


def _arbol(d: ImageDraw.ImageDraw, x: float, base: float, alto: float, rng, color) -> None:
    d.line([(x, base), (x, base - alto)], fill=color, width=int(max(3, alto / 45)))
    for _ in range(int(alto / 30)):
        y = base - rng.uniform(0.25, 1.0) * alto
        largo = rng.uniform(0.1, 0.35) * alto * (1 - (base - y) / alto + 0.3)
        lado = rng.choice([-1, 1])
        d.line([(x, y), (x + lado * largo, y - rng.uniform(5, 0.25 * largo))], fill=color,
               width=int(max(2, alto / 120)))


def _casa(d: ImageDraw.ImageDraw, x: float, base: float, ancho: float, rng, color,
          ventana: bool) -> None:
    alto = ancho * rng.uniform(0.7, 1.1)
    d.rectangle([x, base - alto, x + ancho, base], fill=color)
    d.polygon([(x - ancho * 0.08, base - alto), (x + ancho / 2, base - alto - ancho * 0.55),
               (x + ancho * 1.08, base - alto)], fill=color)
    if rng.random() < 0.5:  # campanario
        cx = x + ancho * 0.7
        d.rectangle([cx, base - alto - ancho * 0.9, cx + ancho * 0.18, base - alto], fill=color)
    if ventana:
        vw = ancho * 0.12
        vx, vy = x + ancho * rng.uniform(0.2, 0.6), base - alto * rng.uniform(0.45, 0.75)
        d.rectangle([vx, vy, vx + vw, vy + vw * 1.4], fill=(255, 196, 110))


def imagen(prompt: str, ruta: Path, ancho: int = 1350, alto: int = 2400,
           tinte: tuple[float, float, float] = (1.0, 1.0, 1.0)) -> Path:
    """Fondo atmosférico según palabras clave del prompt (bosque, casa, pasillo, mar, carretera...)."""
    rng = _rng(prompt)
    p = prompt.lower()
    w, h = ancho, alto
    # Cielo degradado oscuro
    arriba = np.array([18, 24, 34], np.float32) * np.array(tinte, np.float32)
    abajo = np.array([58, 62, 70], np.float32) * np.array(tinte, np.float32)
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    cielo = arriba * (1 - t) + abajo * t
    base = np.broadcast_to(cielo, (h, w, 3)).copy()
    niebla = _ruido(rng, w, h)[:, :, None]
    base = base + niebla * 45
    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)

    if rng.random() < 0.6 and not any(k in p for k in ("corridor", "hallway", "room", "interior")):
        r = rng.uniform(60, 120)
        cx, cy = rng.uniform(0.2, 0.8) * w, rng.uniform(0.2, 0.34) * h
        halo = Image.new("L", (w, h), 0)
        ImageDraw.Draw(halo).ellipse([cx - r * 3, cy - r * 3, cx + r * 3, cy + r * 3], fill=70)
        halo = halo.filter(ImageFilter.GaussianBlur(r))
        img = Image.composite(Image.new("RGB", (w, h), (200, 205, 215)), img, halo)
        d = ImageDraw.Draw(img)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(222, 222, 210))

    sil = (8, 9, 12)
    horizonte = h * rng.uniform(0.62, 0.72)
    if any(k in p for k in ("corridor", "hallway", "room", "door", "stair", "interior", "apartment")):
        # Pasillo en perspectiva con una puerta entreabierta al fondo
        fx, fy, fw, fh = w * 0.38, h * 0.38, w * 0.24, h * 0.22
        d.rectangle([0, 0, w, h], fill=(14, 13, 12))
        d.polygon([(0, 0), (fx, fy), (fx, fy + fh), (0, h)], fill=(30, 27, 24))
        d.polygon([(w, 0), (fx + fw, fy), (fx + fw, fy + fh), (w, h)], fill=(24, 22, 20))
        d.polygon([(0, h), (fx, fy + fh), (fx + fw, fy + fh), (w, h)], fill=(20, 18, 16))
        d.rectangle([fx, fy, fx + fw, fy + fh], fill=(40, 36, 30))
        d.rectangle([fx + fw * 0.3, fy + fh * 0.25, fx + fw * 0.7, fy + fh], fill=(4, 4, 5))
        d.rectangle([fx + fw * 0.3, fy + fh * 0.25, fx + fw * 0.36, fy + fh], fill=(230, 180, 110))
    elif any(k in p for k in ("sea", "lake", "water", "coast", "river", "well")):
        d.rectangle([0, horizonte, w, h], fill=(16, 22, 30))
        for _ in range(60):
            y = rng.uniform(horizonte, h)
            x = rng.uniform(0, w)
            d.line([(x, y), (x + rng.uniform(20, 140), y)], fill=(70, 80, 95), width=2)
    elif any(k in p for k in ("road", "path", "track", "train", "tunnel")):
        d.rectangle([0, horizonte, w, h], fill=(14, 15, 16))
        d.polygon([(w * 0.47, horizonte), (w * 0.53, horizonte), (w * 0.95, h), (w * 0.05, h)],
                  fill=(34, 34, 36))
        for i in range(8):
            y0 = horizonte + (h - horizonte) * (i / 8) ** 1.6
            y1 = horizonte + (h - horizonte) * ((i + 0.5) / 8) ** 1.6
            d.line([(w / 2, y0), (w / 2, y1)], fill=(150, 140, 110), width=int(3 + i * 2))
    else:
        # Colinas
        xs = np.linspace(0, w, 40)
        ys = horizonte + np.cumsum(rng.normal(0, 12, 40))
        d.polygon([(0, h)] + list(zip(xs, ys)) + [(w, h)], fill=(14, 16, 19))
    if any(k in p for k in ("forest", "tree", "wood", "pine", "bosque")) or rng.random() < 0.35:
        for _ in range(int(rng.integers(5, 12))):
            _arbol(d, rng.uniform(0, w), h * rng.uniform(0.85, 1.0), h * rng.uniform(0.35, 0.7),
                   rng, sil)
    if any(k in p for k in ("house", "village", "church", "monastery", "chapel", "farm",
                            "building", "hermitage", "castle", "town")):
        _casa(d, w * rng.uniform(0.15, 0.55), horizonte + 40, w * rng.uniform(0.25, 0.4),
              rng, sil, ventana=True)

    # Niebla baja y viñeta
    niebla2 = _ruido(rng, w, h, 3)
    grad = np.clip((np.linspace(0, 1, h)[:, None] - 0.45) * 1.8, 0, 1)
    alfa = (niebla2 * grad * 150).astype(np.uint8)
    img = Image.composite(Image.new("RGB", (w, h), (150, 158, 168)), img, Image.fromarray(alfa))
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    vin = np.clip(1.15 - dist * 0.55, 0.25, 1)[:, :, None]
    arr = np.asarray(img, np.float32) * vin
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    img.save(ruta, quality=92)
    return ruta


# ----------------------------------------------------------------------------- audio
def guardar_wav(x: np.ndarray, ruta: Path, sr: int = SR) -> Path:
    x = np.clip(x, -1, 1)
    if x.ndim == 1:
        x = np.stack([x, x], axis=1)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(ruta), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((x * 32767).astype(np.int16).tobytes())
    return ruta


def _paso_bajo(x: np.ndarray, k: int) -> np.ndarray:
    c = np.cumsum(np.insert(x, 0, 0))
    y = (c[k:] - c[:-k]) / k
    return np.pad(y, (0, len(x) - len(y)), mode="edge")


def musica(duracion: float, semilla: str, sr: int = SR) -> np.ndarray:
    """Drone ambiental en tonalidad menor, distinto por semilla (variedad entre vídeos)."""
    rng = _rng("musica" + semilla)
    n = int(duracion * sr)
    t = np.arange(n) / sr
    raiz = float(rng.choice([55.0, 61.74, 65.41, 73.42, 82.41]))
    acorde = [1.0, 1.189, 1.498] if rng.random() < 0.7 else [1.0, 1.189, 1.414]
    y = np.zeros(n)
    for i, r in enumerate(acorde):
        f = raiz * r * (2 if i else 1)
        lfo = 0.55 + 0.45 * np.sin(2 * np.pi * rng.uniform(0.03, 0.09) * t + rng.uniform(0, 6))
        for armonico, amp in ((1, 1.0), (2, 0.35), (3, 0.15)):
            det = 1 + rng.uniform(-0.003, 0.003)
            y += amp * lfo * np.sin(2 * np.pi * f * armonico * det * t) / (i + 1.5)
    viento = _paso_bajo(rng.normal(0, 1, n), 60)
    viento *= 0.6 + 0.4 * np.sin(2 * np.pi * 0.07 * t)
    y = y / np.max(np.abs(y)) * 0.55 + viento / np.max(np.abs(viento)) * 0.25
    # Notas de "campanita" ocasionales
    for _ in range(int(duracion / rng.uniform(6, 10))):
        t0 = rng.uniform(1, max(1.5, duracion - 3))
        i0 = int(t0 * sr)
        f = raiz * float(rng.choice([4, 4.757, 5.993, 8]))
        tt = np.arange(min(n - i0, int(4 * sr))) / sr
        y[i0:i0 + len(tt)] += 0.18 * np.sin(2 * np.pi * f * tt) * np.exp(-tt * 1.2)
    fade = int(1.5 * sr)
    env = np.ones(n)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    return y * env / max(1e-6, np.max(np.abs(y))) * 0.7


def sfx(nombre: str, semilla: str = "", sr: int = SR) -> np.ndarray:
    rng = _rng(nombre + semilla)

    def tt(seg: float) -> np.ndarray:
        return np.arange(int(seg * sr)) / sr

    if nombre == "viento":
        t = tt(3.0)
        x = _paso_bajo(rng.normal(0, 1, len(t)), 25) * np.sin(np.pi * t / 3.0) ** 2
    elif nombre == "latido":
        t = tt(0.25)
        golpe = np.sin(2 * np.pi * 55 * t) * np.exp(-t * 22)
        x = np.zeros(int(2.4 * sr))
        for ini in (0.0, 0.28, 1.0, 1.28, 2.0):
            i = int(ini * sr)
            seg = golpe[: len(x) - i] * (0.7 if ini % 1 else 1.0)
            x[i:i + len(seg)] += seg
    elif nombre == "golpe":
        t = tt(1.8)
        f = 70 * np.exp(-t * 2) + 30
        x = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 2.5)
        x[: int(0.02 * sr)] += rng.normal(0, 0.6, int(0.02 * sr))
    elif nombre == "estatica":
        t = tt(1.6)
        x = rng.normal(0, 0.5, len(t)) * (rng.random(len(t)) < 0.35)
        x = _paso_bajo(x, 3) * (0.5 + 0.5 * np.sin(2 * np.pi * 7 * t))
    elif nombre == "campana":
        t = tt(4.0)
        x = sum(a * np.sin(2 * np.pi * 220 * r * t) * np.exp(-t * d)
                for r, a, d in ((1, 1, 0.9), (2.76, 0.5, 1.4), (5.4, 0.3, 2.2), (8.93, 0.15, 3)))
    elif nombre == "puerta":
        t = tt(1.6)
        f = 180 + 120 * np.sin(2 * np.pi * 0.6 * t) + rng.normal(0, 8, len(t))
        fase = np.cumsum(f) / sr
        x = np.sign(np.sin(2 * np.pi * fase)) * 0.3 * np.sin(np.pi * t / 1.6)
        x = _paso_bajo(x, 4)
    elif nombre == "goteo":
        x = np.zeros(int(2.5 * sr))
        for ini in (0.1, 0.9, 1.6, 2.2):
            t = tt(0.12)
            gota = np.sin(2 * np.pi * (1400 - 6000 * t) * t) * np.exp(-t * 40)
            i = int(ini * sr)
            x[i:i + len(gota)] += gota[: len(x) - i]
    else:
        return np.zeros(1)
    x = np.asarray(x, dtype=np.float64)
    return x / max(1e-6, np.max(np.abs(x))) * 0.9
