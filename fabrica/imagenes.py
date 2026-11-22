"""Visuales por escena: Cloudflare Workers AI (FLUX), Pexels, Pixabay y respaldo procedural."""
from __future__ import annotations

import base64
import hashlib
import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from . import procedural
from .config import Config
from .utils import log

L = log("imagenes")
TIMEOUT = 90
NEGATIVO = ("no text, no letters, no watermark, no logo, no gore, no blood, "
            "no recognizable faces, no celebrities")
PERSONAS = re.compile(r"\b(man|woman|men|women|people|person|girl|boy|child|kid|couple|"
                      r"portrait|face|model|selfie|crowd)\b", re.I)

LIC_PEXELS = "Pexels License: uso comercial gratuito, atribución no obligatoria"
LIC_PIXABAY = "Pixabay Content License: uso comercial gratuito, atribución no obligatoria"
LIC_FLUX = "FLUX.1 [schnell] (Apache 2.0) vía Cloudflare Workers AI; salida de uso comercial"


@dataclass
class Visual:
    tipo: str            # imagen | clip
    ruta: Path
    proveedor: str
    fuente: str
    licencia: str
    prompt: str
    atribucion: str | None = None


class SinVisual(RuntimeError):
    pass


def _cache_get(cfg: Config, url: str, params: dict[str, Any], headers: dict[str, str]) -> Any:
    """Caché de 24 h de búsquedas (obligatoria en Pixabay, cortesía en Pexels)."""
    clave = hashlib.sha1((url + json.dumps(params, sort_keys=True)).encode()).hexdigest()
    ruta = cfg.dir_datos / "cache" / f"{clave}.json"
    if ruta.exists() and time.time() - ruta.stat().st_mtime < 86400:
        return json.loads(ruta.read_text(encoding="utf-8"))
    r = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
    if r.status_code == 429:
        raise SinVisual(f"{url}: límite de peticiones (429)")
    r.raise_for_status()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(r.text, encoding="utf-8")
    return r.json()


def _descargar(url: str, ruta: Path) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=TIMEOUT) as r:
        r.raise_for_status()
        with open(ruta, "wb") as f:
            for trozo in r.iter_content(1 << 16):
                f.write(trozo)
    return ruta


# ----------------------------------------------------------------------------- IA
def cloudflare(cfg: Config, prompt: str, ruta: Path) -> Visual:
    cuenta, token = cfg.secreto("CLOUDFLARE_ACCOUNT_ID"), cfg.secreto("CLOUDFLARE_API_TOKEN")
    if not (cuenta and token):
        raise SinVisual("Cloudflare no configurado")
    modelo = cfg["proveedores"].get("cloudflare_modelo", "@cf/black-forest-labs/flux-1-schnell")
    url = f"https://api.cloudflare.com/client/v4/accounts/{cuenta}/ai/run/{modelo}"
    cuerpo = {"prompt": f"{prompt}. {NEGATIVO}"[:2000], "steps": 6}
    r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=cuerpo,
                      timeout=TIMEOUT)
    if r.status_code == 429 or (r.status_code >= 400 and "neuron" in r.text.lower()):
        raise SinVisual("Cloudflare: cuota diaria de neuronas agotada")
    if r.status_code >= 400:
        raise SinVisual(f"Cloudflare HTTP {r.status_code}: {r.text[:200]}")
    datos = r.json()
    b64 = (datos.get("result") or {}).get("image")
    if not b64:
        raise SinVisual(f"Cloudflare: respuesta sin imagen {str(datos)[:200]}")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(base64.b64decode(b64))
    return Visual("imagen", ruta, "cloudflare", modelo, LIC_FLUX, prompt)


# ----------------------------------------------------------------------------- stock
def pexels_clip(cfg: Config, consulta: str, ruta: Path, rng: random.Random) -> Visual:
    clave = cfg.secreto("PEXELS_API_KEY")
    if not clave:
        raise SinVisual("Pexels no configurado")
    datos = _cache_get(cfg, "https://api.pexels.com/videos/search",
                       {"query": consulta, "orientation": "portrait", "per_page": 20},
                       {"Authorization": clave})
    candidatos = []
    for v in datos.get("videos", []):
        if PERSONAS.search(v.get("url", "").replace("-", " ")):
            continue
        if not 4 <= v.get("duration", 0) <= 40:
            continue
        ficheros = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4"
                    and (f.get("height") or 0) >= 1280 and (f.get("height") or 0) <= 2560]
        if ficheros:
            candidatos.append((v, min(ficheros, key=lambda f: f["height"])))
    if not candidatos:
        raise SinVisual(f"Pexels: sin clips válidos para '{consulta}'")
    v, f = rng.choice(candidatos)
    _descargar(f["link"], ruta)
    autor = (v.get("user") or {}).get("name")
    return Visual("clip", ruta, "pexels", v["url"], LIC_PEXELS, consulta,
                  atribucion=f"Vídeo de {autor} en Pexels" if autor else None)


def pixabay_clip(cfg: Config, consulta: str, ruta: Path, rng: random.Random) -> Visual:
    clave = cfg.secreto("PIXABAY_API_KEY")
    if not clave:
        raise SinVisual("Pixabay no configurado")
    datos = _cache_get(cfg, "https://pixabay.com/api/videos/",
                       {"key": clave, "q": consulta, "safesearch": "true", "per_page": 20}, {})
    candidatos = [h for h in datos.get("hits", []) if not PERSONAS.search(h.get("tags", ""))
                  and 4 <= h.get("duration", 0) <= 40]
    if not candidatos:
        raise SinVisual(f"Pixabay: sin clips válidos para '{consulta}'")
    h = rng.choice(candidatos)
    variantes = h["videos"]
    f = next((variantes[k] for k in ("large", "medium") if variantes.get(k, {}).get("url")), None)
    if not f:
        raise SinVisual("Pixabay: clip sin fichero descargable")
    _descargar(f["url"], ruta)
    return Visual("clip", ruta, "pixabay", h["pageURL"], LIC_PIXABAY, consulta,
                  atribucion=f"Vídeo de {h.get('user')} en Pixabay")


def pixabay_imagen(cfg: Config, consulta: str, ruta: Path, rng: random.Random) -> Visual:
    clave = cfg.secreto("PIXABAY_API_KEY")
    if not clave:
        raise SinVisual("Pixabay no configurado")
    datos = _cache_get(cfg, "https://pixabay.com/api/",
                       {"key": clave, "q": consulta, "orientation": "vertical",
                        "image_type": "photo", "safesearch": "true", "per_page": 30}, {})
    candidatos = [h for h in datos.get("hits", []) if not PERSONAS.search(h.get("tags", ""))]
    if not candidatos:
        raise SinVisual(f"Pixabay: sin imágenes para '{consulta}'")
    h = rng.choice(candidatos)
    _descargar(h["largeImageURL"], ruta)
    return Visual("imagen", ruta, "pixabay", h["pageURL"], LIC_PIXABAY, consulta,
                  atribucion=f"Imagen de {h.get('user')} en Pixabay")


# ----------------------------------------------------------------------------- orquestación
def visual_para_escena(cfg: Config, serie: dict[str, Any], escena: dict[str, Any],
                       carpeta: Path, indice: int, rng: random.Random,
                       usar_stock: bool) -> Visual:
    prompt = f"{escena['prompt_imagen']}. Style: {serie['estilo_visual']}"
    consulta = escena.get("busqueda_stock") or "fog night"
    proveedores = list(cfg["proveedores"]["imagenes"])
    orden: list[str] = []
    if usar_stock:
        orden += [p for p in ("pexels", "pixabay") if p in proveedores]
    orden += [p for p in proveedores if p not in orden]
    errores = []
    for p in orden:
        try:
            if p == "cloudflare":
                return cloudflare(cfg, prompt, carpeta / f"escena{indice}.jpg")
            if p == "pexels" and usar_stock:
                return pexels_clip(cfg, consulta, carpeta / f"escena{indice}.mp4", rng)
            if p == "pixabay":
                if usar_stock:
                    return pixabay_clip(cfg, consulta, carpeta / f"escena{indice}.mp4", rng)
                return pixabay_imagen(cfg, consulta, carpeta / f"escena{indice}.jpg", rng)
            if p == "procedural":
                ruta = procedural.imagen(escena["prompt_imagen"] + serie["id"] + str(indice),
                                         carpeta / f"escena{indice}.jpg",
                                         tinte=tuple(serie.get("paleta", {}).get("tinte", (1, 1, 1))))
                return Visual("imagen", ruta, "procedural", "generado localmente",
                              procedural.LICENCIA_PROPIA, escena["prompt_imagen"])
        except (SinVisual, requests.RequestException) as e:
            errores.append(f"{p}: {e}")
            L.info("Escena %d: %s no disponible (%s)", indice, p, e)
    raise SinVisual("; ".join(errores))
