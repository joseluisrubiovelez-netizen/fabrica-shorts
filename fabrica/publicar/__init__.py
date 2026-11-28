"""Publicación con APIs oficiales y plan B manual (aviso por Telegram) cuando no hay acceso."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ..config import Config
from ..db import DB
from ..db import PUBLICADO as VIDEO_PUBLICADO
from ..scheduler import clave_hueco, hueco_actual
from ..utils import log

L = log("publicar")

PUBLICADO = "publicado"
MANUAL = "manual_pendiente"
ERROR = "error"
BLOQUEADO = "bloqueado"           # la plataforma veta la API: se guarda el vídeo y se reintenta
KV_REINTENTO = "hueco_reintento_bloqueados"


class ErrorPublicacion(RuntimeError):
    pass


class TokenCaducado(ErrorPublicacion):
    pass


class CuotaAgotada(ErrorPublicacion):
    pass


class SinCredenciales(ErrorPublicacion):
    pass


class PlataformaBloqueada(ErrorPublicacion):
    pass


def _subidor(nombre: str) -> Callable[..., dict[str, Any]]:
    if nombre == "youtube":
        from .youtube import subir
    elif nombre == "tiktok":
        from .tiktok import subir
    elif nombre == "instagram":
        from .instagram import subir
    else:
        raise ValueError(nombre)
    return subir


def plataformas_activas(cfg: Config) -> list[str]:
    return [p for p, c in cfg["plataformas"].items() if c.get("activo")]


def publicar_video(cfg: Config, db: DB, video: Any, notif=None, almacen=None,
                   subidores: dict[str, Callable[..., dict[str, Any]]] | None = None) -> bool:
    """Publica en cada plataforma activa (idempotente). Devuelve True si en todas quedó
    publicado, avisado para subida manual o retenido por bloqueo (para no frenar la cola)."""
    meta = json.loads(video["meta_json"])
    ruta = Path(video["ruta"]) if video["ruta"] else None
    if (ruta is None or not ruta.exists()) and almacen is not None:
        ruta = almacen.descargar(video["id"])
    if ruta is None or not ruta.exists():
        raise ErrorPublicacion(f"vídeo {video['id']}: no se encuentra el archivo")
    todo_ok = True
    for plat in plataformas_activas(cfg):
        previa = db.publicacion(video["id"], plat)
        if previa and previa["estado"] in (PUBLICADO, MANUAL):
            continue
        pc = cfg["plataformas"][plat]
        texto = meta.get(f"texto_{plat}", meta["descripcion"])
        if plat == "tiktok" and pc.get("modo", "manual") == "manual":
            _manual(db, notif, plat, video["id"], ruta, texto, "modo manual configurado")
            continue
        subir = (subidores or {}).get(plat) or _subidor(plat)
        try:
            res = subir(cfg, ruta, meta, pc)
            db.fijar_publicacion(video["id"], plat, PUBLICADO, res.get("id"), res.get("url"),
                                 sumar_intento=True)
            for aviso in res.get("avisos", []):
                db.evento("aviso", plat, aviso)
                if notif:
                    notif.enviar(f"⚠️ {plat}: {aviso}")
            L.info("Publicado vídeo %s en %s: %s", video["id"], plat, res.get("url"))
        except SinCredenciales as e:
            _manual(db, notif, plat, video["id"], ruta, texto, str(e))
        except PlataformaBloqueada as e:
            # No suma intentos: al desbloquearse debe conservar sus reintentos normales.
            db.fijar_publicacion(video["id"], plat, BLOQUEADO, error=str(e))
            db.evento("error", plat, f"vídeo {video['id']}: {e}")
            if notif and not (previa and previa["estado"] == BLOQUEADO):
                notif.enviar(
                    f"🚫 {plat} ha bloqueado el acceso ({e}). El vídeo #{video['id']} NO se ha "
                    f"publicado ahí: queda guardado y se reintentará (uno por hueco).\n"
                    f"Revisa las alertas en developers.facebook.com. Si prefieres subirlo a mano "
                    f"o no publicarlo, toca /descartar_{video['id']}")
        except (TokenCaducado, CuotaAgotada) as e:
            todo_ok = False
            db.fijar_publicacion(video["id"], plat, ERROR, error=str(e), sumar_intento=True)
            db.evento("error", plat, str(e))
            if notif:
                notif.enviar(f"🔑 {plat}: {e}")
        except Exception as e:  # noqa: BLE001
            todo_ok = False
            db.fijar_publicacion(video["id"], plat, ERROR, error=str(e)[:500], sumar_intento=True)
            db.evento("error", plat, f"vídeo {video['id']}: {e}")
            intentos = (db.publicacion(video["id"], plat) or {"intentos": 0})["intentos"]
            if intentos >= 3:
                _manual(db, notif, plat, video["id"], ruta, texto,
                        f"falló {intentos} veces: {e}")
                todo_ok = True
    if todo_ok and almacen is not None and not _retenido(db, video["id"]):
        almacen.borrar(video["id"])
    return todo_ok


def _retenido(db: DB, video_id: int) -> bool:
    return db.con.execute("SELECT 1 FROM publicaciones WHERE video_id=? AND estado=?",
                          (video_id, BLOQUEADO)).fetchone() is not None


def reintentar_retenidos(ahora: datetime, cfg: Config, db: DB, notif=None, almacen=None,
                         subidores: dict[str, Callable[..., dict[str, Any]]] | None = None
                         ) -> int | None:
    """Reintenta, como mucho una vez por hueco, un vídeo ya publicado al que le falta una
    plataforma bloqueada. Devuelve su número, o None si no tocaba reintentar nada."""
    hueco = hueco_actual(ahora, cfg)
    if hueco is None or db.kv_get(KV_REINTENTO) == clave_hueco(hueco):
        return None
    # El que lleva más tiempo sin probarse; ERROR = falló por otra causa al reintentar.
    fila = db.con.execute(
        "SELECT p.video_id, p.plataforma FROM publicaciones p JOIN videos v ON v.id=p.video_id "
        "WHERE v.estado=? AND p.estado IN (?, ?) ORDER BY p.actualizado, p.video_id LIMIT 1",
        (VIDEO_PUBLICADO, BLOQUEADO, ERROR)).fetchone()
    if fila is None or fila["plataforma"] not in plataformas_activas(cfg):
        return None
    db.kv_set(KV_REINTENTO, clave_hueco(hueco))
    vid, plat = fila["video_id"], fila["plataforma"]
    try:
        publicar_video(cfg, db, db.video(vid), notif, almacen, subidores)
    except Exception as e:  # noqa: BLE001  (p. ej. no se pudo descargar el vídeo)
        L.exception("Reintento del vídeo %s", vid)
        previa = db.publicacion(vid, plat)
        db.fijar_publicacion(vid, plat, previa["estado"], error=str(e)[:500])
        db.evento("error", plat, f"reintento del vídeo {vid}: {e}")
        return vid
    nueva = db.publicacion(vid, plat)
    if notif and nueva["estado"] == PUBLICADO:
        notif.enviar(f"✅ {plat}: vídeo #{vid} publicado al reintentar. {nueva['url'] or ''}")
    return vid


def abandonar_retenidos(db: DB, video_id: int, almacen=None) -> list[str]:
    """Deja de reintentar un vídeo retenido (pasa a manual). Devuelve las plataformas."""
    filas = db.con.execute(
        "SELECT plataforma FROM publicaciones WHERE video_id=? AND estado IN (?, ?)",
        (video_id, BLOQUEADO, ERROR)).fetchall()
    plats = [f["plataforma"] for f in filas]
    for plat in plats:
        db.fijar_publicacion(video_id, plat, MANUAL, error="abandonado con /descartar")
    if plats and almacen is not None:
        almacen.borrar(video_id)
    return plats


def _manual(db: DB, notif, plat: str, video_id: int, ruta: Path, texto: str, motivo: str) -> None:
    db.fijar_publicacion(video_id, plat, MANUAL, error=motivo)
    L.info("Vídeo %s en %s: subida manual (%s)", video_id, plat, motivo)
    if notif:
        notif.aviso_subida_manual(plat, video_id, ruta, texto)
