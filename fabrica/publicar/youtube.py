"""YouTube Data API v3 (subida) y YouTube Analytics API (métricas). Ambas gratuitas."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import Config
from ..utils import log
from . import CuotaAgotada, ErrorPublicacion, SinCredenciales, TokenCaducado

L = log("youtube")
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def credenciales(cfg: Config):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    cid, secreto = cfg.secreto("YOUTUBE_CLIENT_ID"), cfg.secreto("YOUTUBE_CLIENT_SECRET")
    refresh = cfg.secreto("YOUTUBE_REFRESH_TOKEN")
    if not (cid and secreto and refresh):
        raise SinCredenciales("YouTube sin credenciales OAuth en .env")
    cred = Credentials(None, refresh_token=refresh, client_id=cid, client_secret=secreto,
                       token_uri="https://oauth2.googleapis.com/token", scopes=SCOPES)
    try:
        cred.refresh(Request())
    except RefreshError as e:
        raise TokenCaducado(
            "El refresh token de YouTube ha caducado o fue revocado. Si la app OAuth está en "
            "modo 'Testing' caduca a los 7 días: pásala a 'In production' y repite "
            f"`python -m fabrica token-youtube`. Detalle: {e}") from e
    return cred


def _servicio(cfg: Config, nombre: str = "youtube", version: str = "v3"):
    from googleapiclient.discovery import build
    return build(nombre, version, credentials=credenciales(cfg), cache_discovery=False)


def cuerpo_video(meta: dict[str, Any], pc: dict[str, Any]) -> dict[str, Any]:
    titulo = meta["titulo"]
    if "#shorts" not in titulo.lower() and len(titulo) <= 90:
        titulo = f"{titulo} #Shorts"
    tags = [h.lstrip("#") for h in meta["hashtags"]["youtube"]][:15]
    return {
        "snippet": {
            "title": titulo[:100],
            "description": meta["texto_youtube"][:4900],
            "tags": tags,
            "categoryId": str(pc.get("categoria_id", "24")),
            "defaultLanguage": "es",
            "defaultAudioLanguage": "es-ES",
        },
        "status": {
            "privacyStatus": pc.get("privacidad", "public"),
            "selfDeclaredMadeForKids": False,      # regla 7: no dirigido a menores
            "containsSyntheticMedia": True,         # regla 1: etiqueta nativa de contenido IA
            "embeddable": True,
        },
    }


def subir(cfg: Config, ruta: Path, meta: dict[str, Any], pc: dict[str, Any]) -> dict[str, Any]:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    yt = _servicio(cfg)
    cuerpo = cuerpo_video(meta, pc)
    media = MediaFileUpload(str(ruta), mimetype="video/mp4", chunksize=8 * 1024 * 1024,
                            resumable=True)
    try:
        req = yt.videos().insert(part="snippet,status", body=cuerpo, media_body=media)
        resp = None
        while resp is None:
            _, resp = req.next_chunk()
    except HttpError as e:
        texto = str(e)
        if e.resp.status == 403 and ("quota" in texto.lower() or "uploadLimitExceeded" in texto):
            raise CuotaAgotada(f"YouTube: cuota diaria agotada ({texto[:200]})") from e
        if e.resp.status == 401:
            raise TokenCaducado(f"YouTube: credenciales inválidas ({texto[:200]})") from e
        raise ErrorPublicacion(f"YouTube HTTP {e.resp.status}: {texto[:300]}") from e
    vid = resp["id"]
    avisos = []
    pedido = cuerpo["status"]["privacyStatus"]
    real = (resp.get("status") or {}).get("privacyStatus")
    if pedido == "public" and real and real != "public":
        avisos.append("YouTube dejó el vídeo en '%s'. Si tu proyecto de Google Cloud no ha pasado "
                      "la auditoría de la API, los vídeos subidos por API quedan privados: pide "
                      "la auditoría (ver SETUP.md) o cámbialo a público a mano en YouTube Studio."
                      % real)
    return {"id": vid, "url": f"https://www.youtube.com/shorts/{vid}", "avisos": avisos}


def metricas(cfg: Config, ids: list[str], inicio: str, fin: str) -> dict[str, dict[str, Any]]:
    """Métricas reales por vídeo. Retención = averageViewPercentage."""
    if not ids:
        return {}
    yta = _servicio(cfg, "youtubeAnalytics", "v2")
    res: dict[str, dict[str, Any]] = {}
    for i in range(0, len(ids), 50):
        lote = ids[i:i + 50]
        r = yta.reports().query(
            ids="channel==MINE", startDate=inicio, endDate=fin, dimensions="video",
            metrics="views,likes,comments,shares,averageViewDuration,averageViewPercentage",
            filters="video==" + ",".join(lote), maxResults=50).execute()
        cols = [c["name"] for c in r.get("columnHeaders", [])]
        for fila in r.get("rows", []) or []:
            d = dict(zip(cols, fila))
            res[d["video"]] = {"vistas": d.get("views"), "likes": d.get("likes"),
                               "comentarios": d.get("comments"), "compartidos": d.get("shares"),
                               "duracion_media_s": d.get("averageViewDuration"),
                               "retencion_pct": d.get("averageViewPercentage")}
    return res


def obtener_refresh_token(client_id: str, client_secret: str) -> str:
    """Flujo OAuth local (una sola vez, en tu PC). Abre el navegador para autorizar."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    flujo = InstalledAppFlow.from_client_config(
        {"installed": {"client_id": client_id, "client_secret": client_secret,
                       "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                       "token_uri": "https://oauth2.googleapis.com/token",
                       "redirect_uris": ["http://localhost"]}}, SCOPES)
    cred = flujo.run_local_server(port=0, prompt="consent", access_type="offline")
    return cred.refresh_token
