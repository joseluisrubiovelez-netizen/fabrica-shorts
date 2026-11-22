from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from conftest import crear_video

from fabrica import scheduler
from fabrica.db import APROBADO, PENDIENTE, PUBLICADO

MAD = ZoneInfo("Europe/Madrid")


def test_huecos_respetan_hora_y_jitter(cfg):
    cad = cfg["cadencia"]
    for d in range(30):
        dia = date(2026, 12, 1) + timedelta(days=d)
        hs = scheduler.huecos_del_dia(dia, cad, "Europe/Madrid")
        assert len(hs) == cad["videos_por_dia"]
        for h, base in zip(hs, sorted(cad["horas"])):
            hh, mm = map(int, base.split(":"))
            nominal = datetime(dia.year, dia.month, dia.day, hh, mm, tzinfo=MAD)
            assert abs((h - nominal).total_seconds()) <= cad["jitter_minutos"] * 60
        assert hs == sorted(hs)


def test_jitter_estable_y_variado(cfg):
    cad = cfg["cadencia"]
    a = scheduler.huecos_del_dia(date(2026, 12, 3), cad, "Europe/Madrid")
    b = scheduler.huecos_del_dia(date(2026, 12, 3), cad, "Europe/Madrid")
    assert a == b
    minutos = {scheduler.huecos_del_dia(date(2026, 12, 1) + timedelta(days=i), cad,
                                        "Europe/Madrid")[0].minute for i in range(20)}
    assert len(minutos) > 3   # no siempre a la misma hora exacta


def test_cambio_de_hora(cfg):
    # Último domingo de marzo 2027: las horas locales se mantienen
    hs = scheduler.huecos_del_dia(date(2027, 3, 28), cfg["cadencia"], "Europe/Madrid")
    assert all(h.utcoffset() == timedelta(hours=2) for h in hs)


def test_vencidos_y_perdidos(cfg, db):
    dia = date(2026, 12, 2)
    hs = scheduler.huecos_del_dia(dia, cfg["cadencia"], "Europe/Madrid")
    ahora = hs[1] + timedelta(minutes=5)
    pend, perd = scheduler.huecos_vencidos(ahora, cfg, db)
    assert hs[1] in pend
    assert hs[2] not in pend                         # futuro
    tarde = hs[0] + timedelta(hours=5)
    pend, perd = scheduler.huecos_vencidos(tarde, cfg, db)
    assert hs[0] in perd


def test_procesar_publica_en_orden_y_no_repite(cfg, db):
    v1 = crear_video(db, APROBADO)
    v2 = crear_video(db, APROBADO)
    crear_video(db, PENDIENTE)                         # no aprobado: no se publica
    hs = scheduler.huecos_del_dia(date(2026, 12, 2), cfg["cadencia"], "Europe/Madrid")
    publicados = []
    fn = lambda v: publicados.append(v["id"]) or True  # noqa: E731
    ahora = hs[0] + timedelta(minutes=1)
    assert scheduler.procesar_huecos(ahora, cfg, db, fn) == [scheduler.clave_hueco(hs[0])]
    # Segunda ejecución en el mismo hueco: no vuelve a publicar
    assert scheduler.procesar_huecos(ahora + timedelta(minutes=30), cfg, db, fn) == []
    ahora2 = hs[1] + timedelta(minutes=1)
    scheduler.procesar_huecos(ahora2, cfg, db, fn)
    assert publicados == [v1, v2]
    assert db.video(v1)["estado"] == PUBLICADO


def test_hueco_sin_video_avisa_una_vez(cfg, db):
    class N:
        def __init__(self):
            self.mensajes = []

        def enviar(self, t):
            self.mensajes.append(t)
    n = N()
    hs = scheduler.huecos_del_dia(date(2026, 12, 2), cfg["cadencia"], "Europe/Madrid")
    ahora = hs[0] + timedelta(minutes=1)
    scheduler.procesar_huecos(ahora, cfg, db, lambda v: True, n)
    scheduler.procesar_huecos(ahora + timedelta(minutes=20), cfg, db, lambda v: True, n)
    assert len(n.mensajes) == 1


def test_fallo_de_publicacion_reintenta_en_siguiente_ciclo(cfg, db):
    v = crear_video(db, APROBADO)
    hs = scheduler.huecos_del_dia(date(2026, 12, 2), cfg["cadencia"], "Europe/Madrid")
    ahora = hs[0] + timedelta(minutes=1)
    assert scheduler.procesar_huecos(ahora, cfg, db, lambda x: False) == []
    assert db.video(v)["estado"] == APROBADO
    assert scheduler.procesar_huecos(ahora + timedelta(hours=1), cfg, db, lambda x: True)
    assert db.video(v)["estado"] == PUBLICADO


def test_proximo_hueco(cfg):
    ahora = datetime(2026, 12, 2, 23, 59, tzinfo=timezone.utc)
    h = scheduler.proximo_hueco(ahora, cfg)
    assert h > ahora and h.date() == date(2026, 12, 3)
