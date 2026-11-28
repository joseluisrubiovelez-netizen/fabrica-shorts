"""Instagram API (con inicio de sesión de Instagram): publicación de Reels por subida reanudable.

No necesita página de Facebook. En modo desarrollo funciona con tu propia cuenta (rol de tester).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import requests

from ..config import Config
from ..tokens import AlmacenTokens
from ..utils import log
from . import (CuotaAgotada, ErrorPublicacion, PlataformaBloqueada, SinCredenciales,
               TokenCaducado)

L = log("instagram")
TIMEOUT = 60
RENOVAR_DIAS = 30


def _version(cfg: Config) -> str:
    return cfg["plataformas"]["instagram"].get("api_version", "v23.0")


def es_token_facebook(tok: str) -> bool:
    """Los tokens del inicio de sesión unificado de Meta (usuario del sistema) empiezan por EAA."""
    return tok.startswith("EAA")


def host(tok: str) -> str:
    return "graph.facebook.com" if es_token_facebook(tok) else "graph.instagram.com"


def token(cfg: Config) -> tuple[str, str]:
    almacen = AlmacenTokens(cfg)
    g = almacen.get("instagram")
    tok = g.get("access_token") or cfg.secreto("INSTAGRAM_ACCESS_TOKEN")
    uid = cfg.secreto("INSTAGRAM_USER_ID")
    if not (tok and uid):
        raise SinCredenciales("Instagram sin token/ID de usuario en .env")
    if es_token_facebook(tok):
        return tok, uid   # token de usuario del sistema: no caduca, no se renueva
    # Los tokens de Instagram de larga duración caducan a los 60 días: se renuevan cada 30.
    if time.time() - g.get("renovado", 0) > RENOVAR_DIAS * 86400:
        r = requests.get("https://graph.instagram.com/refresh_access_token", timeout=TIMEOUT,
                         params={"grant_type": "ig_refresh_token", "access_token": tok})
        d = r.json()
        if "access_token" in d:
            tok = d["access_token"]
            almacen.set("instagram", {"access_token": tok, "renovado": time.time()})
        elif g.get("renovado"):
            if "api access blocked" in str(d.get("error", "")).lower():
                _comprobar(r)   # lanza PlataformaBloqueada: no es un token caducado
            raise TokenCaducado(f"Instagram: no se pudo renovar el token ({d.get('error')})")
    return tok, uid


def _comprobar(r: requests.Response) -> dict[str, Any]:
    d = r.json()
    if "error" in d:
        e = d["error"]
        # Veto de Meta a la app o a la cuenta de desarrollador: no se arregla reintentando ya.
        if "api access blocked" in str(e.get("message", "")).lower():
            raise PlataformaBloqueada(f"Instagram: {e.get('message')}")
        if e.get("code") == 190:
            raise TokenCaducado(f"Instagram: token inválido ({e.get('message')})")
        if e.get("code") in (4, 9, 17, 32, 613) or "limit" in str(e.get("message", "")).lower():
            raise CuotaAgotada(f"Instagram: límite alcanzado ({e.get('message')})")
        raise ErrorPublicacion(f"Instagram: {e.get('message')}")
    return d


def subir(cfg: Config, ruta: Path, meta: dict[str, Any], pc: dict[str, Any]) -> dict[str, Any]:
    tok, uid = token(cfg)
    v = _version(cfg)
    base = f"https://{host(tok)}/{v}"
    cont = _comprobar(requests.post(f"{base}/{uid}/media", timeout=TIMEOUT, data={
        "media_type": "REELS", "upload_type": "resumable",
        "caption": meta["texto_instagram"][:2200], "share_to_feed": "true",
        "is_ai_generated": "true",                         # regla 1: etiqueta "Info de IA"
        "access_token": tok}))
    cid = cont["id"]
    tam = ruta.stat().st_size
    with open(ruta, "rb") as f:
        r = requests.post(f"https://rupload.facebook.com/ig-api-upload/{v}/{cid}", data=f,
                          timeout=600, headers={"Authorization": f"OAuth {tok}", "offset": "0",
                                                "file_size": str(tam)})
    if r.status_code >= 300:
        raise ErrorPublicacion(f"Instagram: subida HTTP {r.status_code} {r.text[:200]}")
    for _ in range(40):
        time.sleep(6)
        st = _comprobar(requests.get(f"{base}/{cid}", timeout=TIMEOUT,
                                     params={"fields": "status_code,status", "access_token": tok}))
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise ErrorPublicacion(f"Instagram: procesado fallido ({st.get('status')})")
    else:
        raise ErrorPublicacion("Instagram: el vídeo no terminó de procesarse a tiempo")
    pub = _comprobar(requests.post(f"{base}/{uid}/media_publish", timeout=TIMEOUT,
                                   data={"creation_id": cid, "access_token": tok}))
    mid = pub["id"]
    info = _comprobar(requests.get(f"{base}/{mid}", timeout=TIMEOUT,
                                   params={"fields": "permalink", "access_token": tok}))
    return {"id": mid, "url": info.get("permalink"), "avisos": []}


def metricas(cfg: Config, ids: list[str]) -> dict[str, dict[str, Any]]:
    tok, _ = token(cfg)
    base = f"https://{host(tok)}/{_version(cfg)}"
    res = {}
    for mid in ids:
        r = requests.get(f"{base}/{mid}/insights", timeout=TIMEOUT, params={
            "metric": "views,reach,likes,comments,shares,saved,ig_reels_avg_watch_time",
            "access_token": tok}).json()
        if "error" in r:
            L.warning("Instagram métricas %s: %s", mid, r["error"].get("message"))
            continue
        d = {m["name"]: (m.get("values") or [{}])[0].get("value") for m in r.get("data", [])}
        media_ms = d.get("ig_reels_avg_watch_time")
        res[mid] = {"vistas": d.get("views"), "likes": d.get("likes"),
                    "comentarios": d.get("comments"), "compartidos": d.get("shares"),
                    "duracion_media_s": media_ms / 1000 if media_ms is not None else None,
                    "datos": {"alcance": d.get("reach"), "guardados": d.get("saved")}}
    return res
