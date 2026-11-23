import json

from conftest import crear_video, guion_valido

from fabrica import cli, guiones, pipeline
from fabrica.db import APROBADO, DESCARTADO, DRY, PENDIENTE


class NotifFalso:
    def __init__(self, comandos=None):
        self.mensajes, self.comandos, self.aprobaciones = [], comandos or [], []

    def enviar(self, t):
        self.mensajes.append(t)

    def leer_comandos(self):
        return self.comandos

    def pedir_aprobacion(self, vid, ruta, meta):
        self.aprobaciones.append(vid)


def test_aprobar_y_descartar(db):
    a = crear_video(db, PENDIENTE)
    b = crear_video(db, PENDIENTE)
    n = NotifFalso()
    cli.aplicar_comandos(db, n, [("aprobar", a), ("descartar", b), ("aprobar", 999)])
    assert db.video(a)["estado"] == APROBADO
    assert db.video(b)["estado"] == DESCARTADO
    assert any("No existe" in m for m in n.mensajes)


def test_no_se_aprueba_lo_ya_publicado(db):
    a = crear_video(db, "publicado")
    cli.aplicar_comandos(db, NotifFalso(), [("aprobar", a)])
    assert db.video(a)["estado"] == "publicado"


def test_estado_final_segun_modo():
    assert pipeline._estado_final("dry-run") == DRY
    assert pipeline._estado_final("review") == PENDIENTE
    assert pipeline._estado_final("auto") == APROBADO


def test_semillas_no_se_repiten(cfg, db):
    n1 = guiones.generar_lote(cfg, db, "expedientes")
    n2 = guiones.generar_lote(cfg, db, "expedientes")
    assert n1 > 0 and n2 == 0          # los temas ya usados no se vuelven a guardar


def test_rellenar_cola_respeta_objetivo_y_maximo(cfg, db, monkeypatch):
    def producir_falso(cfg_, db_, fila, notif=None):
        g = json.loads(fila["json"])
        vid = db_.crear_video(fila["id"], g["serie"], g["titulo"])
        db_.marcar_guion_usado(fila["id"])
        db_.actualizar_video(vid, estado=PENDIENTE)
        return vid
    monkeypatch.setattr(pipeline, "producir", producir_falso)
    hechos = pipeline.rellenar_cola(cfg, db, maximo=2)
    assert len(hechos) == 2
    cfg.datos["cadencia"]["cola_objetivo"] = 2
    assert pipeline.rellenar_cola(cfg, db, maximo=5) == []   # cola llena


def test_series_se_reparten_por_peso(cfg, db):
    for _ in range(10):
        crear_video(db, PENDIENTE, serie="expedientes")
    assert guiones.elegir_serie(cfg, db) != "expedientes"


def test_ciclo_aprueba_por_telegram_y_publica_en_hueco(cfg, db, monkeypatch):
    import argparse
    from datetime import date, timedelta

    import fabrica.publicar as pub
    from fabrica import scheduler
    vid = crear_video(db, PENDIENTE)
    n = NotifFalso(comandos=[("aprobar", vid)])
    publicados = []
    monkeypatch.setattr(cli, "_contexto", lambda modo: (cfg, db, n))
    monkeypatch.setattr(pub, "publicar_video",
                        lambda c, d, v, nt, alm: publicados.append(v["id"]) or True)
    monkeypatch.setattr(pipeline, "rellenar_cola", lambda *a, **k: [])
    hueco = scheduler.huecos_del_dia(date(2026, 12, 1), cfg["cadencia"], "Europe/Madrid")[0]
    ahora = (hueco + timedelta(minutes=2)).isoformat()   # martes: no toca informe
    assert cli.cmd_ciclo(argparse.Namespace(modo=None, ahora=ahora)) == 0
    assert publicados == [vid]
    assert db.video(vid)["estado"] == "publicado"
    assert any("aprobado" in m for m in n.mensajes)


def test_ciclo_dry_run_no_publica(cfg, db, monkeypatch):
    import argparse

    import fabrica.publicar as pub
    cfg.datos["modo"] = "dry-run"
    crear_video(db, APROBADO)
    monkeypatch.setattr(cli, "_contexto", lambda modo: (cfg, db, NotifFalso()))
    monkeypatch.setattr(pub, "publicar_video", lambda *a: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(pipeline, "rellenar_cola", lambda *a, **k: [])
    assert cli.cmd_ciclo(argparse.Namespace(modo=None, ahora="2026-12-01T21:00:00+00:00")) == 0


def test_metadatos_marcan_ficcion_e_ia(cfg):
    g = guion_valido()
    meta = pipeline.componer_metadatos(g, cfg.serie("expedientes"),
                                       [{"atribucion": "Vídeo de X en Pexels"}])
    assert meta["descripcion"].startswith("Relato de ficción")
    assert "IA" in meta["descripcion"] and "Pexels" in meta["descripcion"]
    assert meta["es_ficcion"] is True


def test_interpretar_comandos_de_telegram():
    from fabrica.notify import interpretar
    aviso = {"caption": "🎬 Vídeo #7 listo para revisar\n\nToca /aprobar_7 o /descartar_7"}
    assert interpretar({"text": "/aprobar 5"}) == ("aprobar", 5)
    assert interpretar({"text": "/aprobar_5"}) == ("aprobar", 5)
    assert interpretar({"text": "/descartar_12@fabrica_bot"}) == ("descartar", 12)
    assert interpretar({"text": "/aprobar", "reply_to_message": aviso}) == ("aprobar", 7)
    assert interpretar({"text": "/aprobar"}) == ("aprobar", None)
    assert interpretar({"text": "/estado"}) == ("estado", None)
    assert interpretar({"text": "hola"}) is None


def test_aprobar_sin_numero_pide_el_numero(db):
    n = NotifFalso()
    cli.aplicar_comandos(db, n, [("aprobar", None)])
    assert any("Falta el número" in m for m in n.mensajes)
