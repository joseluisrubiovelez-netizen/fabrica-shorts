import pytest
from conftest import crear_video

from fabrica import analytics
from fabrica.db import APROBADO
from fabrica.publicar import MANUAL, PUBLICADO, CuotaAgotada, SinCredenciales, publicar_video
from fabrica.publicar.youtube import cuerpo_video


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
