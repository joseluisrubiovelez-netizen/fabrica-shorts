"""Orquestación: guion -> voz -> subtítulos -> visuales -> audio -> montaje -> QA (con reintentos)."""
from __future__ import annotations

import json
import random
import shutil
import time
from pathlib import Path
from typing import Any

from . import audio, guiones, imagenes, qa, render, subtitulos, voz
from .config import Config
from .db import APROBADO, DB, DESCARTADO, DRY, PENDIENTE
from .notify import Notificador
from .utils import log

L = log("pipeline")

AVISO_IA_FICCION = "Relato de ficción. Narración e imágenes generadas con IA."
AVISO_IA_HIST = "Narración e imágenes generadas con IA a partir de fuentes documentadas."


def componer_metadatos(g: dict[str, Any], serie: dict[str, Any],
                       assets: list[dict[str, Any]]) -> dict[str, Any]:
    ficcion = serie["tipo"] != "historico"
    desc = g["descripcion"].strip()
    if ficcion and not desc.lower().startswith("relato de ficción"):
        desc = f"{AVISO_IA_FICCION}\n\n{desc}"
    else:
        desc = f"{desc}\n\n{AVISO_IA_FICCION if ficcion else AVISO_IA_HIST}"
    if g.get("fuentes"):
        desc += "\n\nFuentes:\n" + "\n".join(f"- {f}" for f in g["fuentes"])
    creditos = sorted({a["atribucion"] for a in assets if a.get("atribucion")})
    if creditos:
        desc += "\n\nCréditos: " + "; ".join(creditos)
    titulo = g["titulo"].strip()
    return {
        "titulo": titulo,
        "serie": serie["nombre"],
        "es_ficcion": ficcion,
        "descripcion": desc,
        "hashtags": g["hashtags"],
        "texto_youtube": f"{desc}\n\n{' '.join(g['hashtags']['youtube'])}",
        "texto_tiktok": f"{titulo} {' '.join(g['hashtags']['tiktok'])}\n"
                        f"{AVISO_IA_FICCION if ficcion else AVISO_IA_HIST}",
        "texto_instagram": f"{titulo}\n\n{desc}\n\n{' '.join(g['hashtags']['instagram'])}",
    }


def _estado_final(modo: str) -> str:
    return {"dry-run": DRY, "review": PENDIENTE, "auto": APROBADO}[modo]


def producir(cfg: Config, db: DB, guion_row: Any, notif: Notificador | None = None) -> int | None:
    g = json.loads(guion_row["json"])
    serie = cfg.serie(g["serie"])
    video_id = db.crear_video(guion_row["id"], g["serie"], g["titulo"])
    db.marcar_guion_usado(guion_row["id"])
    num_serie = db.con.execute("SELECT COUNT(*) FROM videos WHERE serie=?", (g["serie"],)
                               ).fetchone()[0]
    max_int = 1 + int(cfg["qa"]["max_reintentos"])
    ultimo_qa: dict[str, Any] = {}
    for intento in range(max_int):
        t0 = time.time()
        carpeta = cfg.dir_datos / "videos" / f"{video_id:05d}" / f"intento{intento}"
        if carpeta.exists():
            shutil.rmtree(carpeta)
        carpeta.mkdir(parents=True)
        rng = random.Random(f"{video_id}-{intento}")
        db.borrar_assets(video_id)
        try:
            res = _producir_intento(cfg, db, g, serie, video_id, carpeta, rng, num_serie, intento)
        except Exception as e:  # un fallo de un proveedor no debe tumbar la ejecución
            L.exception("Vídeo %d intento %d falló", video_id, intento)
            db.evento("error", "pipeline", f"video {video_id} intento {intento}: {e}")
            ultimo_qa = {"ok": False, "fallos": [f"excepción: {e}"]}
            continue
        ruta, resultado, meta = res
        ultimo_qa = resultado.como_dict()
        ultimo_qa["segundos_generacion"] = round(time.time() - t0, 1)
        db.actualizar_video(video_id, intentos=intento + 1, qa_json=ultimo_qa)
        if resultado.ok:
            final = cfg.dir_datos / "videos" / f"{video_id:05d}" / "final.mp4"
            shutil.copy2(ruta, final)
            estado = _estado_final(cfg.modo)
            db.actualizar_video(video_id, estado=estado, ruta=str(final),
                                duracion=resultado.metricas.get("duracion"), meta_json=meta)
            L.info("Vídeo %d listo (%s) en %.0fs: %s", video_id, estado, time.time() - t0, final)
            if notif and estado == PENDIENTE:
                notif.pedir_aprobacion(video_id, final, meta)
            return video_id
        L.warning("QA falló en vídeo %d intento %d: %s", video_id, intento, resultado.fallos)
    db.actualizar_video(video_id, estado=DESCARTADO, qa_json=ultimo_qa)
    db.evento("error", "qa", f"video {video_id} descartado tras {max_int} intentos: "
                             f"{ultimo_qa.get('fallos')}")
    if notif:
        notif.enviar(f"❌ Vídeo {video_id} descartado tras {max_int} intentos.\n"
                     f"Motivos: {ultimo_qa.get('fallos')}")
    return None


def _producir_intento(cfg: Config, db: DB, g: dict[str, Any], serie: dict[str, Any],
                      video_id: int, carpeta: Path, rng: random.Random, num_serie: int,
                      intento: int):
    vcfg, pv = cfg["video"], cfg["proveedores"]
    crono = _Crono(video_id)
    # 1) Voz
    segmentos = [g["gancho"]] + [e["narracion"] for e in g["escenas"]] + [g["cta"]]
    modelo_voz = str(cfg.raiz / pv["voz"]["modelo"])
    velocidad = float(pv["voz"].get("velocidad", 1.0)) * (1.0 + 0.03 * intento)
    loc = voz.generar_locucion(segmentos, modelo_voz, carpeta / "voz.wav",
                               vcfg["duracion_min"], vcfg["duracion_max"], velocidad)
    crono("voz")
    db.registrar_asset(video_id, "voz", "piper", Path(modelo_voz).name, pv["voz"]["licencia"],
                       str(loc.ruta))
    # 2) Subtítulos palabra a palabra
    palabras_guion = " ".join(segmentos).split()
    try:
        wh = subtitulos.transcribir(loc.ruta, pv["whisper"]["modelo"], " ".join(segmentos))
        palabras = subtitulos.alinear(palabras_guion, wh, loc.tramos_escena)
    except Exception as e:
        L.warning("Whisper no disponible (%s); uso alineación proporcional", e)
        db.evento("aviso", "subtitulos", f"whisper: {e}")
        palabras = subtitulos.proporcional(segmentos, loc.marcas_segmento)
    cues = subtitulos.agrupar(palabras)
    crono("subtitulos")
    fin_gancho = palabras[len(g["gancho"].split()) - 1].fin
    # 3) Visuales
    escenas: list[render.Escena] = []
    movs = render.elegir_movimientos(len(g["escenas"]), rng)
    prop_stock = float(pv.get("proporcion_stock", 0.25))
    for i, (esc, (ini, fin)) in enumerate(zip(g["escenas"], loc.tramos_escena)):
        usar_stock = i > 0 and rng.random() < prop_stock   # la 1.ª siempre IA (miniatura)
        vis = imagenes.visual_para_escena(cfg, serie, esc, carpeta, i, rng, usar_stock)
        db.registrar_asset(video_id, "visual", vis.proveedor, vis.fuente, vis.licencia,
                           str(vis.ruta), vis.prompt, vis.atribucion)
        escenas.append(render.Escena(vis.tipo, vis.ruta, ini, fin, movs[i],
                                     esc.get("texto_pantalla", "")))
    crono("visuales")
    # 4) Música + SFX y mezcla
    sfx = [(ini + 0.05, e.get("sfx", "ninguno")) for e, (ini, _) in
           zip(g["escenas"], loc.tramos_escena)]
    fondo, recursos = audio.construir_fondo(
        loc.duracion, sfx, f"{video_id}-{intento}", cfg.raiz, carpeta,
        cfg["audio"]["musica_db"], cfg["audio"]["sfx_db"], rng)
    for rec in recursos:
        db.registrar_asset(video_id, rec.tipo, rec.proveedor, rec.fuente, rec.licencia, rec.ruta,
                           atribucion=rec.atribucion)
    mezcla = audio.mezclar(loc.ruta, fondo, carpeta / "mezcla.wav", cfg["audio"]["lufs_objetivo"])
    crono("audio")
    # 5) Montaje
    pal = serie.get("paleta", {})
    estilo = render.Estilo(saturacion=pal.get("saturacion", 0.8),
                           contraste=pal.get("contraste", 1.08),
                           tinte=tuple(pal.get("tinte", (1, 1, 1))),
                           fuente=serie.get("fuente"))
    etiqueta = serie.get("etiqueta_pantalla", serie["nombre"]).upper()
    if serie["tipo"] == "historico":
        etiqueta_sup = f"{etiqueta} · {serie['nombre'].upper()}"
    else:
        # Si el guion ya cita un número ("Expediente 184"), la etiqueta usa ese mismo
        import re
        m = re.search(r"expediente\s+(\d+)", " ".join([g["titulo"], g["gancho"]] +
                                                      [e["narracion"] for e in g["escenas"]]), re.I)
        numero = int(m.group(1)) if m else num_serie
        etiqueta_sup = f"{etiqueta} Nº {numero:03d} · FICCIÓN"
    salida = carpeta / "video.mp4"
    render.montar(escenas, cues, mezcla, salida, gancho=g["gancho"], etiqueta_sup=etiqueta_sup,
                  estilo=estilo, duracion=loc.duracion, W=vcfg["ancho"], H=vcfg["alto"],
                  fps=vcfg["fps"], crf=vcfg.get("crf", 20), raiz=str(cfg.raiz))
    crono("montaje")
    # 6) QA
    assets = [dict(r) for r in db.assets_de(video_id)]
    resultado = qa.revisar(salida, cfg=cfg.datos, voz=loc.ruta, cues=cues,
                           fin_gancho=fin_gancho, assets=assets)
    crono("qa")
    meta = componer_metadatos(g, serie, assets)
    meta["tiempos_s"] = crono.tiempos
    meta["proveedores_visuales"] = sorted({a["proveedor"] for a in assets if a["tipo"] == "visual"})
    return salida, resultado, meta


class _Crono:
    def __init__(self, video_id: int):
        self.video_id, self.t, self.tiempos = video_id, time.time(), {}

    def __call__(self, etapa: str) -> None:
        ahora = time.time()
        self.tiempos[etapa] = round(ahora - self.t, 1)
        L.info("Vídeo %d · %s: %.1fs", self.video_id, etapa, ahora - self.t)
        self.t = ahora


def en_cola(db: DB) -> int:
    return len(db.videos_en_estado(PENDIENTE, APROBADO))


def asegurar_guiones(cfg: Config, db: DB, serie_id: str) -> Any | None:
    disponibles = db.guiones_disponibles(serie_id)
    if not disponibles:
        guiones.generar_lote(cfg, db, serie_id)
        disponibles = db.guiones_disponibles(serie_id)
    if not disponibles:   # probar con cualquier serie
        disponibles = db.guiones_disponibles()
    return disponibles[0] if disponibles else None


def rellenar_cola(cfg: Config, db: DB, notif: Notificador | None = None,
                  maximo: int | None = None) -> list[int]:
    objetivo = int(cfg["cadencia"]["cola_objetivo"])
    maximo = maximo if maximo is not None else int(cfg["cadencia"]["max_generar_por_ejecucion"])
    hechos: list[int] = []
    intentos = 0
    while (cfg.modo == "dry-run" or en_cola(db) < objetivo) and len(hechos) < maximo \
            and intentos < maximo * 2:
        intentos += 1
        serie_id = guiones.elegir_serie(cfg, db)
        fila = asegurar_guiones(cfg, db, serie_id)
        if fila is None:
            msg = "No hay guiones disponibles (cuota de LLM agotada y semillas consumidas)."
            L.error(msg)
            db.evento("error", "guiones", msg)
            if notif:
                notif.enviar("⚠️ " + msg)
            break
        vid = producir(cfg, db, fila, notif)
        if vid:
            hechos.append(vid)
    return hechos
