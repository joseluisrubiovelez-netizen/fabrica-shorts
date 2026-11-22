"""Analítica semanal desde las APIs oficiales. Solo se informan datos devueltos por las APIs."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from .config import Config
from .db import DB
from .utils import log

L = log("analitica")


def _fetchers() -> dict[str, Callable[..., dict[str, dict[str, Any]]]]:
    from .publicar import instagram, tiktok, youtube
    hoy = date.today()
    return {
        "youtube": lambda cfg, ids: youtube.metricas(cfg, ids, (hoy - timedelta(days=90)).isoformat(),
                                                     hoy.isoformat()),
        "tiktok": tiktok.metricas,
        "instagram": instagram.metricas,
    }


def recoger(cfg: Config, db: DB, fetchers: dict[str, Callable] | None = None) -> dict[str, str]:
    """Guarda en la BD las métricas de hoy. Devuelve el estado por plataforma."""
    fetchers = fetchers or _fetchers()
    hoy = date.today().isoformat()
    estado: dict[str, str] = {}
    pubs = [p for p in db.publicaciones("publicado") if p["id_externo"]]
    por_plat: dict[str, list[Any]] = defaultdict(list)
    for p in pubs:
        por_plat[p["plataforma"]].append(p)
    for plat, filas in por_plat.items():
        try:
            datos = fetchers[plat](cfg, [f["id_externo"] for f in filas])
        except Exception as e:  # noqa: BLE001
            estado[plat] = f"error: {e}"
            db.evento("aviso", "analitica", f"{plat}: {e}")
            continue
        for f in filas:
            m = datos.get(f["id_externo"])
            if m:
                db.guardar_metrica(f["id"], hoy, **m)
        estado[plat] = f"{sum(1 for f in filas if f['id_externo'] in datos)}/{len(filas)} con datos"
    return estado


def _fmt(v: Any, dec: int = 0, suf: str = "") -> str:
    if v is None:
        return "sin datos"
    return f"{v:,.{dec}f}{suf}".replace(",", ".") if isinstance(v, (int, float)) else str(v)


def informe(cfg: Config, db: DB, estado: dict[str, str] | None = None,
            salida: Path | None = None) -> Path:
    hoy = date.today()
    filas = db.con.execute("""
        SELECT v.id, v.titulo, v.serie, v.programado_para, p.plataforma, p.url, m.vistas, m.likes,
               m.comentarios, m.compartidos, m.retencion_pct, m.duracion_media_s, m.fecha
        FROM publicaciones p JOIN videos v ON v.id = p.video_id
        LEFT JOIN metricas m ON m.id = (SELECT id FROM metricas WHERE publicacion_id = p.id
                                        ORDER BY fecha DESC LIMIT 1)
        WHERE p.estado = 'publicado' ORDER BY v.id DESC""").fetchall()
    lin = [f"# Informe semanal — {hoy.isoformat()}", "",
           "Datos obtenidos de las APIs oficiales. «sin datos» = la API no devolvió ese valor "
           "(no se estima nada).", ""]
    if estado:
        lin += ["## Estado de la recogida", ""] + [f"- **{k}**: {v}" for k, v in estado.items()] + [""]
    manuales = db.con.execute("SELECT COUNT(*) FROM publicaciones WHERE estado='manual_pendiente'"
                              ).fetchone()[0]
    lin += [f"- Publicaciones por API: {len(filas)}",
            f"- Subidas manuales avisadas (sin métricas por API): {manuales}", ""]
    if not filas:
        lin += ["Todavía no hay publicaciones con datos."]
    else:
        lin += ["## Por vídeo", "",
                "| Vídeo | Serie | Plataforma | Vistas | Likes | Coment. | Retención media | "
                "Duración media vista |", "|---|---|---|---|---|---|---|---|"]
        for f in filas:
            titulo = f["titulo"][:40].replace("|", "/")
            enlace = f"[{titulo}]({f['url']})" if f["url"] else titulo
            lin.append(f"| {enlace} | {f['serie']} | {f['plataforma']} | {_fmt(f['vistas'])} | "
                       f"{_fmt(f['likes'])} | {_fmt(f['comentarios'])} | "
                       f"{_fmt(f['retencion_pct'], 1, ' %')} | "
                       f"{_fmt(f['duracion_media_s'], 1, ' s')} |")
        lin += ["", "## Por serie (suma de vistas con datos)", ""]
        series: dict[str, list[int]] = defaultdict(list)
        horas: dict[str, list[int]] = defaultdict(list)
        for f in filas:
            if f["vistas"] is not None:
                series[f["serie"]].append(f["vistas"])
                if f["programado_para"]:
                    horas[f["programado_para"][11:13] + "h"].append(f["vistas"])
        for s, vs in sorted(series.items(), key=lambda x: -sum(x[1])):
            lin.append(f"- **{s}**: {sum(vs):,} vistas en {len(vs)} publicaciones "
                       f"(media {sum(vs) / len(vs):,.0f})".replace(",", "."))
        if horas:
            lin += ["", "## Por hora de publicación (media de vistas)", ""]
            for h, vs in sorted(horas.items()):
                lin.append(f"- {h}: {sum(vs) / len(vs):,.0f} (n={len(vs)})".replace(",", "."))
    salida = salida or (cfg.dir_datos / "informes" / f"informe-{hoy.isoformat()}.md")
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text("\n".join(lin) + "\n", encoding="utf-8")
    return salida


def toca_informe(db: DB, hoy: date | None = None) -> bool:
    hoy = hoy or date.today()
    ultimo = db.kv_get("ultimo_informe")
    return hoy.weekday() == 0 and ultimo != hoy.isoformat()


def marcar_informe(db: DB, hoy: date | None = None) -> None:
    db.kv_set("ultimo_informe", (hoy or date.today()).isoformat())


def resumen_json(db: DB) -> str:
    return json.dumps({"eventos": [dict(r) for r in db.con.execute(
        "SELECT nivel, componente, mensaje, creado FROM eventos ORDER BY id DESC LIMIT 20")]},
        ensure_ascii=False, indent=2)
