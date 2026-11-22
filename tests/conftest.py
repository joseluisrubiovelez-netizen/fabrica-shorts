import json
import os
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from fabrica.config import cargar_config  # noqa: E402
from fabrica.db import DB  # noqa: E402


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    for k in list(os.environ):
        if k.endswith(("_API_KEY", "_TOKEN", "_SECRET", "_CHAT_ID")) or k.startswith(
                ("YOUTUBE_", "TIKTOK_", "INSTAGRAM_", "CLOUDFLARE_", "TELEGRAM_", "FABRICA_")):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FABRICA_DATOS", str(tmp_path / "data"))
    c = cargar_config(modo="review", cargar_env=False)
    return c


@pytest.fixture
def db(cfg):
    d = DB(cfg.ruta_db)
    yield d
    d.cerrar()


def guion_valido(**cambios):
    g = json.loads((RAIZ / "seeds" / "guiones.json").read_text(encoding="utf-8"))[0]
    g.update(cambios)
    return g


@pytest.fixture
def guion():
    return guion_valido()


def crear_video(db, estado, serie="expedientes", meta=None, ruta=None):
    g = guion_valido()
    gid = db.guardar_guion(serie, g["tema"] + str(estado), "x", "semillas", g)
    vid = db.crear_video(gid, serie, g["titulo"])
    meta = meta or {"titulo": g["titulo"], "descripcion": "d", "hashtags": g["hashtags"],
                    "texto_youtube": "y", "texto_tiktok": "t", "texto_instagram": "i"}
    db.actualizar_video(vid, estado=estado, meta_json=meta, ruta=ruta)
    return vid
