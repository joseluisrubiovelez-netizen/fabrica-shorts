"""Programación de publicaciones en huecos horarios de España (con desfase aleatorio estable)."""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .config import Config
from .db import APROBADO, DB, PUBLICADO
from .utils import log

L = log("scheduler")

PUBLICADO_H = "publicado"
PERDIDO = "perdido"
SIN_VIDEO = "sin_video"
EN_CURSO = "en_curso"
FALLIDO = "fallido"


def _jitter(fecha: date, hora: str, maximo: int) -> int:
    if maximo <= 0:
        return 0
    h = int(hashlib.sha256(f"{fecha.isoformat()}|{hora}".encode()).hexdigest()[:8], 16)
    return h % (2 * maximo + 1) - maximo


def huecos_del_dia(fecha: date, cad: dict[str, Any], tz: str) -> list[datetime]:
    zona = ZoneInfo(tz)
    res = []
    for hora in sorted(cad["horas"])[: int(cad["videos_por_dia"])]:
        hh, mm = (int(x) for x in hora.split(":"))
        base = datetime(fecha.year, fecha.month, fecha.day, hh, mm, tzinfo=zona)
        res.append(base + timedelta(minutes=_jitter(fecha, hora, int(cad.get("jitter_minutos", 0)))))
    return res


def clave_hueco(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")


def huecos_vencidos(ahora: datetime, cfg: Config, db: DB) -> tuple[list[datetime], list[datetime]]:
    """Devuelve (pendientes_a_publicar, perdidos). Revisa hoy y ayer en hora de España."""
    tz = cfg["zona_horaria"]
    local = ahora.astimezone(ZoneInfo(tz))
    tol = timedelta(hours=float(cfg["cadencia"].get("tolerancia_retraso_horas", 3)))
    pendientes, perdidos = [], []
    for dia in (local.date() - timedelta(days=1), local.date()):
        for h in huecos_del_dia(dia, cfg["cadencia"], tz):
            fila = db.hueco(clave_hueco(h))
            if fila and fila["estado"] in (PUBLICADO_H, PERDIDO):
                continue
            if h > local:
                continue
            (pendientes if local - h <= tol else perdidos).append(h)
    return pendientes, perdidos


def hueco_actual(ahora: datetime, cfg: Config) -> datetime | None:
    """El último hueco ya alcanzado que sigue dentro de la tolerancia, o None."""
    tz = cfg["zona_horaria"]
    local = ahora.astimezone(ZoneInfo(tz))
    tol = timedelta(hours=float(cfg["cadencia"].get("tolerancia_retraso_horas", 3)))
    vigentes = [h for dia in (local.date() - timedelta(days=1), local.date())
                for h in huecos_del_dia(dia, cfg["cadencia"], tz)
                if timedelta(0) <= local - h <= tol]
    return max(vigentes, default=None)


def proximo_hueco(ahora: datetime, cfg: Config) -> datetime:
    tz = cfg["zona_horaria"]
    local = ahora.astimezone(ZoneInfo(tz))
    for d in range(0, 3):
        for h in huecos_del_dia(local.date() + timedelta(days=d), cfg["cadencia"], tz):
            if h > local:
                return h
    raise RuntimeError("No hay huecos configurados")


def siguiente_video(db: DB) -> Any | None:
    """El aprobado más antiguo que no tenga hueco asignado."""
    return db.con.execute(
        "SELECT * FROM videos WHERE estado=? AND id NOT IN "
        "(SELECT video_id FROM huecos WHERE video_id IS NOT NULL AND estado IN (?, ?)) "
        "ORDER BY id LIMIT 1", (APROBADO, PUBLICADO_H, EN_CURSO)).fetchone()


def procesar_huecos(ahora: datetime, cfg: Config, db: DB, publicar_fn, notif=None) -> list[str]:
    """Publica en los huecos vencidos. `publicar_fn(video_row) -> bool` (éxito)."""
    hechos: list[str] = []
    pendientes, perdidos = huecos_vencidos(ahora, cfg, db)
    for h in perdidos:
        clave = clave_hueco(h)
        db.fijar_hueco(clave, None, PERDIDO)
        db.evento("aviso", "scheduler", f"hueco {clave} perdido (sin ejecutar a tiempo)")
    for h in pendientes:
        clave = clave_hueco(h)
        fila = db.hueco(clave)
        video = db.video(fila["video_id"]) if fila and fila["video_id"] else siguiente_video(db)
        if video is None:
            if not fila or fila["estado"] != SIN_VIDEO:
                db.fijar_hueco(clave, None, SIN_VIDEO)
                msg = f"Hueco {clave}: no hay vídeos aprobados en cola."
                db.evento("aviso", "scheduler", msg)
                if notif:
                    notif.enviar("⚠️ " + msg)
            continue
        db.fijar_hueco(clave, video["id"], EN_CURSO)
        ok = False
        try:
            ok = bool(publicar_fn(video))
        except Exception as e:  # el error concreto ya se registra en publicar
            L.exception("Fallo publicando vídeo %s", video["id"])
            db.evento("error", "scheduler", f"hueco {clave} vídeo {video['id']}: {e}")
        db.fijar_hueco(clave, video["id"], PUBLICADO_H if ok else FALLIDO)
        if ok:
            db.actualizar_video(video["id"], estado=PUBLICADO, programado_para=clave)
            hechos.append(clave)
    return hechos
