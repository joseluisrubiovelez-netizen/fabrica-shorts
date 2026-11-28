"""Línea de órdenes: python -m fabrica <orden>."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import cargar_config
from .db import APROBADO, DB, DESCARTADO, DRY, PENDIENTE, PUBLICADO
from .publicar import BLOQUEADO, abandonar_retenidos
from .utils import log

L = log("cli")


def _contexto(modo: str | None):
    from .notify import Notificador
    cfg = cargar_config(modo=modo)
    db = DB(cfg.ruta_db)
    return cfg, db, Notificador(cfg, db)


def cmd_generar(a) -> int:
    from . import pipeline
    cfg, db, notif = _contexto(a.modo)
    ids = pipeline.rellenar_cola(cfg, db, notif, maximo=a.n)
    print(f"Generados: {ids}")
    return 0 if ids else 1


def cmd_guiones(a) -> int:
    from . import guiones
    cfg, db, _ = _contexto(a.modo)
    n = guiones.generar_lote(cfg, db, a.serie)
    print(f"Guiones nuevos: {n}")
    return 0


def aplicar_comandos(db: DB, notif, comandos, almacen=None) -> None:
    for orden, vid in comandos:
        if orden == "estado":
            notif.enviar(texto_estado(db))
            continue
        if vid is None:
            notif.enviar(f"Falta el número del vídeo. Escribe /{orden}_N (por ejemplo "
                         f"/{orden}_5) o responde al mensaje del vídeo con /{orden}.")
            continue
        fila = db.video(vid)
        if not fila:
            notif.enviar(f"No existe el vídeo #{vid}")
            continue
        if orden == "aprobar" and fila["estado"] == PENDIENTE:
            db.actualizar_video(vid, estado=APROBADO)
            notif.enviar(f"✅ Vídeo #{vid} aprobado: se publicará en el próximo hueco.")
        elif orden == "descartar" and fila["estado"] in (PENDIENTE, APROBADO):
            db.actualizar_video(vid, estado=DESCARTADO)
            notif.enviar(f"🗑️ Vídeo #{vid} descartado.")
        elif (orden == "descartar" and fila["estado"] == PUBLICADO
              and (plats := abandonar_retenidos(db, vid, almacen))):
            notif.enviar(f"🗑️ Vídeo #{vid}: ya no se reintentará en {', '.join(plats)}.")
        else:
            notif.enviar(f"El vídeo #{vid} está en estado '{fila['estado']}'; no se cambia.")


def texto_estado(db: DB) -> str:
    c = dict(db.con.execute("SELECT estado, COUNT(*) FROM videos GROUP BY estado").fetchall())
    ev = db.con.execute("SELECT nivel, mensaje FROM eventos WHERE nivel='error' "
                        "ORDER BY id DESC LIMIT 3").fetchall()
    lineas = [f"Pendientes de aprobar: {c.get(PENDIENTE, 0)}", f"Aprobados en cola: "
              f"{c.get(APROBADO, 0)}", f"Publicados: {c.get(PUBLICADO, 0)}",
              f"Descartados: {c.get(DESCARTADO, 0)}", f"Dry-run: {c.get(DRY, 0)}"]
    retenidos = db.publicaciones(BLOQUEADO)
    if retenidos:
        lineas.append("Retenidos por bloqueo: " + ", ".join(
            f"#{r['video_id']} ({r['plataforma']})" for r in retenidos))
    if ev:
        lineas.append("Últimos errores: " + " | ".join(e["mensaje"][:120] for e in ev))
    return "\n".join(lineas)


def cmd_ciclo(a) -> int:
    """Lo que ejecuta el programador cada hora."""
    from . import analytics, pipeline, scheduler
    from .almacen import Almacen
    from .publicar import publicar_video, reintentar_retenidos
    cfg, db, notif = _contexto(a.modo)
    almacen = Almacen(cfg)
    ahora = datetime.fromisoformat(a.ahora) if a.ahora else datetime.now(timezone.utc)
    L.info("Ciclo en modo %s (%s)", cfg.modo, ahora.isoformat())
    aplicar_comandos(db, notif, notif.leer_comandos(), almacen)
    if cfg.modo != "dry-run":
        # Antes de los huecos: así no reintenta en el acto lo que acaba de bloquearse.
        reintentar_retenidos(ahora, cfg, db, notif, almacen)
        hechos = scheduler.procesar_huecos(
            ahora, cfg, db, lambda v: publicar_video(cfg, db, v, notif, almacen), notif)
        if hechos:
            L.info("Huecos publicados: %s", hechos)
    nuevos = pipeline.rellenar_cola(cfg, db, notif)
    for vid in nuevos:
        fila = db.video(vid)
        if fila and fila["ruta"]:
            almacen.guardar(vid, Path(fila["ruta"]))
    if cfg.modo != "dry-run":
        if pipeline.en_cola(db) < int(cfg["cadencia"]["videos_por_dia"]):
            pend = len(db.videos_en_estado(PENDIENTE))
            if pend and db.kv_get("aviso_cola") != ahora.date().isoformat():
                notif.enviar(f"⏳ Quedan pocos vídeos aprobados. Tienes {pend} esperando "
                             "revisión (/aprobar_N).")
                db.kv_set("aviso_cola", ahora.date().isoformat())
        if analytics.toca_informe(db, ahora.date()):
            estado = analytics.recoger(cfg, db)
            ruta = analytics.informe(cfg, db, estado)
            analytics.marcar_informe(db, ahora.date())
            notif.enviar(f"📊 Informe semanal generado: {ruta.name}\n{estado}")
    return 0


def cmd_aprobar(a) -> int:
    _, db, notif = _contexto(None)
    aplicar_comandos(db, notif, [("aprobar", a.id)])
    return 0


def cmd_descartar(a) -> int:
    from .almacen import Almacen
    cfg, db, notif = _contexto(None)
    aplicar_comandos(db, notif, [("descartar", a.id)], Almacen(cfg))
    return 0


def cmd_publicar(a) -> int:
    from .almacen import Almacen
    from .publicar import publicar_video
    cfg, db, notif = _contexto(a.modo)
    if cfg.modo == "dry-run":
        print("En dry-run no se publica nada.")
        return 1
    fila = db.video(a.id)
    if not fila or fila["estado"] not in (APROBADO, PENDIENTE):
        print("El vídeo no existe o no está pendiente/aprobado.")
        return 1
    ok = publicar_video(cfg, db, fila, notif, Almacen(cfg))
    if ok:
        db.actualizar_video(a.id, estado=PUBLICADO)
    print("Publicado" if ok else "Hubo errores: revisa `estado`")
    return 0 if ok else 1


def cmd_estado(a) -> int:
    _, db, _ = _contexto(None)
    print(texto_estado(db))
    for r in db.con.execute("SELECT id, serie, estado, titulo, duracion FROM videos "
                            "ORDER BY id DESC LIMIT 15"):
        print(f"  #{r['id']:>4} {r['estado']:<22} {r['serie']:<14} {r['duracion'] or 0:>5.1f}s "
              f"{r['titulo'][:50]}")
    return 0


def cmd_informe(a) -> int:
    from . import analytics
    cfg, db, _ = _contexto(None)
    estado = analytics.recoger(cfg, db) if not a.sin_recoger else None
    print(analytics.informe(cfg, db, estado))
    return 0


def cmd_clave(a) -> int:
    from .tokens import generar_clave
    print(generar_clave())
    return 0


def cmd_token_youtube(a) -> int:
    from .publicar.youtube import obtener_refresh_token
    cfg = cargar_config()
    cid, sec = cfg.secreto("YOUTUBE_CLIENT_ID"), cfg.secreto("YOUTUBE_CLIENT_SECRET")
    if not (cid and sec):
        print("Rellena YOUTUBE_CLIENT_ID y YOUTUBE_CLIENT_SECRET en .env primero.")
        return 1
    tok = obtener_refresh_token(cid, sec)
    guardar_en_env(cfg, "YOUTUBE_REFRESH_TOKEN", tok)
    print("\nListo: YOUTUBE_REFRESH_TOKEN guardado en .env (añádelo también a los Secrets de "
          "GitHub cuando subas el proyecto).")
    return 0


def guardar_en_env(cfg, clave: str, valor: str) -> None:
    """Escribe una clave en .env sin mostrarla por pantalla."""
    import re
    ruta = cfg.raiz / ".env"
    texto = ruta.read_text(encoding="utf-8-sig") if ruta.exists() else ""
    linea = f"{clave}={valor}"
    if re.search(rf"(?m)^{clave}=.*$", texto):
        texto = re.sub(rf"(?m)^{clave}=.*$", lambda _: linea, texto)
    else:
        texto += f"\n{linea}\n"
    ruta.write_text(texto, encoding="utf-8")


def cmd_token_tiktok(a) -> int:
    from .publicar.tiktok_oauth import flujo
    return flujo(cargar_config())


def cmd_prueba_tiktok(a) -> int:
    """Publica un vídeo concreto en TikTok (privado salvo auditoría). Se usa en la demo."""
    import json
    from pathlib import Path as _P

    from .publicar.tiktok import subir
    cfg = cargar_config()
    ruta = _P(a.video)
    if not ruta.exists():
        print("No existe el vídeo", ruta)
        return 1
    meta = {"titulo": a.titulo, "texto_tiktok": a.titulo + " #misterio #relatos"}
    junto = ruta.parent.parent / "meta.json"
    if junto.exists():
        meta.update(json.loads(junto.read_text(encoding="utf-8")))
    pc = dict(cfg["plataformas"]["tiktok"])
    print("== Relatos 3am Publisher: Content Posting API (Direct Post) ==")
    print(f"Vídeo / Video: {ruta.name}  ·  Etiqueta IA / AI label: is_aigc = true")
    print("Subiendo (FILE_UPLOAD) y publicando... / Uploading and posting...")
    res = subir(cfg, ruta, meta, pc)
    print(f"\nPublicado / Posted: id={res.get('id')}  url={res.get('url') or '(privado / private)'}")
    for aviso in res.get("avisos", []):
        print("Aviso / Note:", aviso)
    return 0


def cmd_prueba_youtube(a) -> int:
    """Sube un vídeo concreto a YouTube en privado. Se usa en la grabación para la auditoría."""
    from pathlib import Path as _P

    from .publicar.youtube import cuerpo_video, subir
    cfg = cargar_config()
    ruta = _P(a.video)
    if not ruta.exists():
        print("No existe el vídeo", ruta)
        return 1
    meta = {"titulo": a.titulo, "hashtags": {"youtube": ["#Shorts", "#misterio"]},
            "texto_youtube": "Relato de ficción. Narración e imágenes generadas con IA."}
    pc = dict(cfg["plataformas"]["youtube"], privacidad="private")
    cuerpo = cuerpo_video(meta, pc)
    print("== Relatos 3am Publisher: YouTube Data API v3 (videos.insert) ==")
    print(f"Vídeo / Video: {ruta.name}")
    print(f"Título / Title: {cuerpo['snippet']['title']}")
    print("Privacidad / Privacy: private  ·  containsSyntheticMedia = true (etiqueta IA)"
          "  ·  selfDeclaredMadeForKids = false")
    print("Subiendo... / Uploading...")
    res = subir(cfg, ruta, meta, pc)
    print(f"\nSubido / Uploaded: {res['url']}")
    return 0


def cmd_verificar(a) -> int:
    cfg = cargar_config(modo=a.modo)
    claves = {
        "Guiones": ["GEMINI_API_KEY", "GROQ_API_KEY"],
        "Imágenes IA": ["CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"],
        "Stock": ["PEXELS_API_KEY", "PIXABAY_API_KEY"],
        "YouTube": ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"],
        "TikTok": ["TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN"],
        "Instagram": ["INSTAGRAM_USER_ID", "INSTAGRAM_ACCESS_TOKEN"],
        "Telegram": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"],
        "Tokens cifrados": ["FABRICA_CLAVE_TOKENS"],
    }
    print(f"Modo: {cfg.modo}")
    for grupo, ks in claves.items():
        estado = ", ".join(f"{k}={'OK' if cfg.secreto(k) else 'falta'}" for k in ks)
        print(f"- {grupo}: {estado}")
    voz = cfg.raiz / cfg["proveedores"]["voz"]["modelo"]
    print(f"- Voz Piper: {'OK' if voz.exists() else 'falta (ejecuta make setup)'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="fabrica", description="Fábrica de Shorts de misterio")
    p.add_argument("--modo", choices=["dry-run", "review", "auto"], help="sobrescribe config.yaml")
    sub = p.add_subparsers(dest="orden", required=True)
    g = sub.add_parser("generar", help="genera vídeos hasta llenar la cola")
    g.add_argument("--n", type=int, default=1)
    g.set_defaults(f=cmd_generar)
    s = sub.add_parser("guiones", help="genera un lote de guiones")
    s.add_argument("--serie")
    s.set_defaults(f=cmd_guiones)
    c = sub.add_parser("ciclo", help="ejecución programada (cada hora)")
    c.add_argument("--ahora", help="fecha/hora ISO para pruebas")
    c.set_defaults(f=cmd_ciclo)
    for nombre, fn in (("aprobar", cmd_aprobar), ("descartar", cmd_descartar),
                       ("publicar", cmd_publicar)):
        x = sub.add_parser(nombre)
        x.add_argument("id", type=int)
        x.set_defaults(f=fn)
    sub.add_parser("estado").set_defaults(f=cmd_estado)
    i = sub.add_parser("informe", help="informe semanal de analítica")
    i.add_argument("--sin-recoger", action="store_true")
    i.set_defaults(f=cmd_informe)
    sub.add_parser("clave", help="genera FABRICA_CLAVE_TOKENS").set_defaults(f=cmd_clave)
    sub.add_parser("token-youtube", help="OAuth de YouTube (una vez)").set_defaults(
        f=cmd_token_youtube)
    sub.add_parser("token-tiktok", help="OAuth de TikTok (una vez)").set_defaults(
        f=cmd_token_tiktok)
    sub.add_parser("verificar", help="comprueba claves y modelos").set_defaults(f=cmd_verificar)
    pt = sub.add_parser("prueba-tiktok", help="publica un vídeo concreto en TikTok (demo)")
    pt.add_argument("video")
    pt.add_argument("--titulo", default="Relato de ficción · Relatos 3am")
    pt.set_defaults(f=cmd_prueba_tiktok)
    py_ = sub.add_parser("prueba-youtube", help="sube un vídeo concreto a YouTube en privado")
    py_.add_argument("video")
    py_.add_argument("--titulo", default="Las sombras ausentes · Relatos 3am")
    py_.set_defaults(f=cmd_prueba_youtube)
    a = p.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
