"""TikTok Content Posting API (Direct Post). Gratuita; sin auditoría solo permite SELF_ONLY."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import requests

from ..config import Config
from ..tokens import AlmacenTokens
from ..utils import log
from . import CuotaAgotada, ErrorPublicacion, SinCredenciales, TokenCaducado

L = log("tiktok")
BASE = "https://open.tiktokapis.com"
TIMEOUT = 60


def token_acceso(cfg: Config) -> str:
    almacen = AlmacenTokens(cfg)
    guardado = almacen.get("tiktok")
    if guardado.get("access_token") and guardado.get("expira", 0) > time.time() + 300:
        return guardado["access_token"]
    clave, secreto = cfg.secreto("TIKTOK_CLIENT_KEY"), cfg.secreto("TIKTOK_CLIENT_SECRET")
    refresh = guardado.get("refresh_token") or cfg.secreto("TIKTOK_REFRESH_TOKEN")
    if not (clave and secreto and refresh):
        raise SinCredenciales("TikTok sin credenciales de API en .env")
    r = requests.post(f"{BASE}/v2/oauth/token/", timeout=TIMEOUT,
                      headers={"Content-Type": "application/x-www-form-urlencoded"},
                      data={"client_key": clave, "client_secret": secreto,
                            "grant_type": "refresh_token", "refresh_token": refresh})
    datos = r.json()
    if "access_token" not in datos:
        raise TokenCaducado(f"TikTok: no se pudo renovar el token ({datos}). "
                            "Repite `python -m fabrica token-tiktok`.")
    almacen.set("tiktok", {"access_token": datos["access_token"],
                           "expira": time.time() + int(datos.get("expires_in", 86400)),
                           "refresh_token": datos.get("refresh_token", refresh)})
    return datos["access_token"]


def _post(token: str, ruta: str, cuerpo: dict[str, Any]) -> dict[str, Any]:
    r = requests.post(f"{BASE}{ruta}", json=cuerpo, timeout=TIMEOUT,
                      headers={"Authorization": f"Bearer {token}",
                               "Content-Type": "application/json; charset=UTF-8"})
    datos = r.json()
    err = (datos.get("error") or {})
    codigo = err.get("code", "ok")
    if codigo != "ok":
        if codigo in ("access_token_invalid", "scope_not_authorized"):
            raise TokenCaducado(f"TikTok: {codigo} {err.get('message')}")
        if codigo in ("rate_limit_exceeded", "spam_risk_too_many_posts"):
            raise CuotaAgotada(f"TikTok: {codigo} {err.get('message')}")
        raise ErrorPublicacion(f"TikTok {ruta}: {codigo} {err.get('message')}")
    return datos.get("data", {})


def subir(cfg: Config, ruta: Path, meta: dict[str, Any], pc: dict[str, Any]) -> dict[str, Any]:
    token = token_acceso(cfg)
    avisos: list[str] = []
    info = _post(token, "/v2/post/publish/creator_info/query/", {})
    opciones = info.get("privacy_level_options", [])
    privacidad = pc.get("privacidad", "SELF_ONLY")
    if privacidad not in opciones:
        avisos.append(f"Privacidad {privacidad} no disponible (opciones: {opciones}); "
                      "uso SELF_ONLY. ¿Falta la auditoría de la app?")
        privacidad = "SELF_ONLY"
    tam = ruta.stat().st_size
    if tam > 64 * 1024 * 1024:
        raise ErrorPublicacion("TikTok: el vídeo supera 64 MB (subida en un solo trozo)")
    titulo = meta["texto_tiktok"][:2200]
    init = _post(token, "/v2/post/publish/video/init/", {
        "post_info": {"title": titulo, "privacy_level": privacidad,
                      "disable_duet": False, "disable_comment": False, "disable_stitch": False,
                      "video_cover_timestamp_ms": 1000,
                      "is_aigc": True},                      # regla 1: etiqueta IA nativa
        "source_info": {"source": "FILE_UPLOAD", "video_size": tam, "chunk_size": tam,
                        "total_chunk_count": 1}})
    with open(ruta, "rb") as f:
        r = requests.put(init["upload_url"], data=f, timeout=600,
                         headers={"Content-Type": "video/mp4", "Content-Length": str(tam),
                                  "Content-Range": f"bytes 0-{tam - 1}/{tam}"})
    if r.status_code >= 300:
        raise ErrorPublicacion(f"TikTok: subida HTTP {r.status_code} {r.text[:200]}")
    publish_id = init["publish_id"]
    for _ in range(40):
        time.sleep(6)
        st = _post(token, "/v2/post/publish/status/fetch/", {"publish_id": publish_id})
        estado = st.get("status")
        if estado == "PUBLISH_COMPLETE":
            ids = st.get("publicaly_available_post_id") or []
            pid = str(ids[0]) if ids else publish_id
            return {"id": pid, "url": f"https://www.tiktok.com/video/{pid}" if ids else None,
                    "avisos": avisos}
        if estado == "FAILED":
            raise ErrorPublicacion(f"TikTok: publicación fallida ({st.get('fail_reason')})")
    avisos.append("TikTok sigue procesando el vídeo; revisa la app.")
    return {"id": publish_id, "url": None, "avisos": avisos}


def metricas(cfg: Config, ids: list[str]) -> dict[str, dict[str, Any]]:
    """Requiere el scope video.list. TikTok no ofrece retención por API: se deja vacía."""
    ids = [i for i in ids if i and i.isdigit()]
    if not ids:
        return {}
    token = token_acceso(cfg)
    r = requests.post(f"{BASE}/v2/video/query/?fields=id,view_count,like_count,comment_count,"
                      "share_count", json={"filters": {"video_ids": ids[:20]}}, timeout=TIMEOUT,
                      headers={"Authorization": f"Bearer {token}"})
    res = {}
    for v in (r.json().get("data") or {}).get("videos", []):
        res[str(v["id"])] = {"vistas": v.get("view_count"), "likes": v.get("like_count"),
                             "comentarios": v.get("comment_count"),
                             "compartidos": v.get("share_count")}
    return res
