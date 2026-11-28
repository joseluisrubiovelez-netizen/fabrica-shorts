from datetime import date, timedelta
from pathlib import Path

import pytest
from conftest import crear_video

from fabrica import analytics
from fabrica.cli import aplicar_comandos
from fabrica.db import APROBADO
from fabrica.db import PUBLICADO as VIDEO_PUBLICADO
from fabrica.publicar import (BLOQUEADO, ERROR, MANUAL, PUBLICADO, CuotaAgotada,
                              PlataformaBloqueada, SinCredenciales, instagram, publicar_video,
                              reintentar_retenidos)
from fabrica.publicar.youtube import cuerpo_video
from fabrica.scheduler import huecos_del_dia

@pytest.fixture
def video(db, tmp_path):
    ruta = tmp_path / "v.mp4"
    ruta.write_bytes(b"0" * 100)
    vid = crear_video(db, APROBADO, ruta=str(ruta))
    return db.video(vid)


class Notif:
    def __init__(self):
        self.manuales, self.mensajes = [], []

    def aviso_subida_manual(self, plat, vid, ruta, texto):
        self.manuales.append(plat)

    def enviar(self, t):
        self.mensajes.append(t)


def test_publica_y_es_idempotente(cfg, db, video):
    llamadas = []

    def ok(plat):
        def f(cfg_, ruta, meta, pc):
            llamadas.append(plat)
            return {"id": f"{plat}-1", "url": f"https://x/{plat}"}
        return f
    subs = {"youtube": ok("youtube"), "instagram": ok("instagram")}
    n = Notif()
    assert publicar_video(cfg, db, video, n, subidores=subs)
    assert sorted(llamadas) == ["instagram", "youtube"]
    assert n.manuales == ["tiktok"]                    # TikTok en modo manual por defecto
    assert publicar_video(cfg, db, video, n, subidores=subs)
    assert len(llamadas) == 2                          # no se vuelve a subir
    assert db.publicacion(video["id"], "youtube")["estado"] == PUBLICADO
    assert db.publicacion(video["id"], "tiktok")["estado"] == MANUAL


def test_sin_credenciales_pasa_a_manual(cfg, db, video):
    def sin(*a):
        raise SinCredenciales("falta token")
    n = Notif()
    ok = publicar_video(cfg, db, video, n, subidores={"youtube": sin, "instagram": sin})
    assert ok and sorted(n.manuales) == ["instagram", "tiktok", "youtube"]


def test_cuota_agotada_avisa_y_reintenta_despues(cfg, db, video):
    def cuota(*a):
        raise CuotaAgotada("cuota")
    n = Notif()
    subs = {"youtube": cuota, "instagram": lambda *a: {"id": "i", "url": None}}
    assert not publicar_video(cfg, db, video, n, subidores=subs)
    assert any("cuota" in m for m in n.mensajes)
    subs["youtube"] = lambda *a: {"id": "y", "url": None}
    assert publicar_video(cfg, db, video, n, subidores=subs)


def test_error_repetido_acaba_en_manual(cfg, db, video):
    def roto(*a):
        raise RuntimeError("500")
    n = Notif()
    subs = {"youtube": roto, "instagram": lambda *a: {"id": "i", "url": None}}
    resultados = [publicar_video(cfg, db, video, n, subidores=subs) for _ in range(3)]
    assert resultados == [False, False, True]
    assert "youtube" in n.manuales


def test_youtube_marca_ia_y_no_infantil():
    meta = {"titulo": "Título", "texto_youtube": "desc", "hashtags": {"youtube": ["#Shorts"]}}
    c = cuerpo_video(meta, {"privacidad": "public"})
    assert c["status"]["containsSyntheticMedia"] is True
    assert c["status"]["selfDeclaredMadeForKids"] is False
    assert c["snippet"]["title"].endswith("#Shorts")


def test_analitica_no_inventa(cfg, db, video):
    db.fijar_publicacion(video["id"], "youtube", PUBLICADO, "yt1", "https://y")
    db.fijar_publicacion(video["id"], "instagram", PUBLICADO, "ig1", None)
    estado = analytics.recoger(cfg, db, fetchers={
        "youtube": lambda c, ids: {"yt1": {"vistas": 120, "retencion_pct": 71.5}},
        "instagram": lambda c, ids: {}})
    texto = analytics.informe(cfg, db, estado).read_text(encoding="utf-8")
    assert "120" in texto and "71.5 %" in texto
    assert "sin datos" in texto                         # Instagram sin datos: no se estima
    assert estado["instagram"] == "0/1 con datos"


# ---------- plataforma bloqueada: se retiene el vídeo y se reintenta ----------

class AlmacenFalso:
    def __init__(self):
        self.borrados = []

    def descargar(self, vid):
        return None

    def borrar(self, vid):
        self.borrados.append(vid)


def _bloqueado(*a):
    raise PlataformaBloqueada("Instagram: API access blocked.")


def _ok(*a):
    return {"id": "x", "url": "https://x/reel"}


def _publicar_bloqueado(cfg, db, video, n, almacen):
    ok = publicar_video(cfg, db, video, n, almacen,
                        subidores={"youtube": _ok, "instagram": _bloqueado})
    if ok:
        db.actualizar_video(video["id"], estado=VIDEO_PUBLICADO)
    return ok


def _hueco(cfg, dias=0):
    """Un momento justo después del primer hueco de un día fijo."""
    h = huecos_del_dia(date(2026, 11, 23) + timedelta(days=dias), cfg["cadencia"],
                       cfg["zona_horaria"])[0]
    return h + timedelta(minutes=1)


def test_instagram_reconoce_el_bloqueo():
    class R:
        def json(self):
            return {"error": {"code": 200, "message": "API access blocked."}}
    with pytest.raises(PlataformaBloqueada):
        instagram._comprobar(R())


def test_bloqueo_retiene_el_video_y_no_frena_la_cola(cfg, db, video):
    n, alm = Notif(), AlmacenFalso()
    for _ in range(4):
        assert _publicar_bloqueado(cfg, db, video, n, alm)   # YouTube sale: la cola avanza
    pub = db.publicacion(video["id"], "instagram")
    assert pub["estado"] == BLOQUEADO and pub["intentos"] == 0
    assert alm.borrados == []                               # el archivo se conserva
    assert "instagram" not in n.manuales
    avisos = [m for m in n.mensajes if "bloque" in m.lower()]
    assert len(avisos) == 1 and f"/descartar_{video['id']}" in avisos[0]


def test_reintento_publica_al_desbloquear(cfg, db, video):
    n, alm = Notif(), AlmacenFalso()
    _publicar_bloqueado(cfg, db, video, n, alm)
    assert reintentar_retenidos(_hueco(cfg), cfg, db, n, alm,
                                subidores={"instagram": _ok}) == video["id"]
    assert db.publicacion(video["id"], "instagram")["estado"] == PUBLICADO
    assert alm.borrados == [video["id"]]
    assert any("https://x/reel" in m for m in n.mensajes)


def test_reintento_uno_por_hueco(cfg, db, video):
    n, alm, llamadas = Notif(), AlmacenFalso(), []

    def sigue(*a):
        llamadas.append(1)
        _bloqueado()
    _publicar_bloqueado(cfg, db, video, n, alm)
    subs = {"instagram": sigue}
    reintentar_retenidos(_hueco(cfg), cfg, db, n, alm, subidores=subs)
    reintentar_retenidos(_hueco(cfg) + timedelta(hours=1), cfg, db, n, alm, subidores=subs)
    assert len(llamadas) == 1
    reintentar_retenidos(_hueco(cfg, dias=1), cfg, db, n, alm, subidores=subs)
    assert len(llamadas) == 2 and alm.borrados == []


def test_sin_hueco_no_reintenta(cfg, db, video):
    n, alm = Notif(), AlmacenFalso()
    _publicar_bloqueado(cfg, db, video, n, alm)
    madrugada = _hueco(cfg).replace(hour=8, minute=0)
    assert reintentar_retenidos(madrugada, cfg, db, n, alm, subidores={"instagram": _ok}) is None


def test_error_distinto_en_reintento_sigue_retenido_hasta_manual(cfg, db, video):
    n, alm = Notif(), AlmacenFalso()
    _publicar_bloqueado(cfg, db, video, n, alm)

    def roto(*a):
        raise RuntimeError("500")
    for dia in range(2):
        reintentar_retenidos(_hueco(cfg, dia), cfg, db, n, alm, subidores={"instagram": roto})
    assert db.publicacion(video["id"], "instagram")["estado"] == ERROR
    reintentar_retenidos(_hueco(cfg, 2), cfg, db, n, alm, subidores={"instagram": roto})
    assert db.publicacion(video["id"], "instagram")["estado"] == MANUAL
    assert alm.borrados == [video["id"]]


def test_archivo_perdido_no_rompe_el_ciclo(cfg, db, video):
    n, alm = Notif(), AlmacenFalso()
    _publicar_bloqueado(cfg, db, video, n, alm)
    Path(video["ruta"]).unlink()
    reintentar_retenidos(_hueco(cfg), cfg, db, n, alm, subidores={"instagram": _ok})
    assert db.publicacion(video["id"], "instagram")["estado"] == BLOQUEADO


def test_descartar_deja_de_reintentar(cfg, db, video):
    n, alm = Notif(), AlmacenFalso()
    _publicar_bloqueado(cfg, db, video, n, alm)
    aplicar_comandos(db, n, [("descartar", video["id"])], alm)
    assert db.publicacion(video["id"], "instagram")["estado"] == MANUAL
    assert db.video(video["id"])["estado"] == VIDEO_PUBLICADO   # YouTube ya salió
    assert alm.borrados == [video["id"]]
    assert reintentar_retenidos(_hueco(cfg), cfg, db, n, alm,
                                subidores={"instagram": _ok}) is None
