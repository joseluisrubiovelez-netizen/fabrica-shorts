"""Publicación con APIs oficiales y plan B manual (aviso por Telegram) cuando no hay acceso."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ..config import Config
from ..db import DB
from ..utils import log

L = log("publicar")

PUBLICADO = "publicado"
MANUAL = "manual_pendiente"
ERROR = "error"


class ErrorPublicacion(RuntimeError):
    pass


class TokenCaducado(ErrorPublicacion):
    pass


class CuotaAgotada(ErrorPublicacion):
    pass


class SinCredenciales(ErrorPublicacion):
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
    """Publica en cada plataforma activa (idempotente). Devuelve True si quedó publicado o
    avisado para subida manual en todas."""
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
    if todo_ok and almacen is not None:
        almacen.borrar(video["id"])
    return todo_ok


def _manual(db: DB, notif, plat: str, video_id: int, ruta: Path, texto: str, motivo: str) -> None:
    db.fijar_publicacion(video_id, plat, MANUAL, error=motivo)
    L.info("Vídeo %s en %s: subida manual (%s)", video_id, plat, motivo)
    if notif:
        notif.aviso_subida_manual(plat, video_id, ruta, texto)
