import base64
from pathlib import Path

import numpy as np
import pytest
from conftest import crear_video

from fabrica import pipeline, voz, voz_gemini
from fabrica.voz_gemini import SR


def _tono(seg, f=220.0):
    t = np.arange(int(seg * SR)) / SR
    return (8000 * np.sin(2 * np.pi * f * t)).astype(np.int16)


def _sil(seg):
    return np.zeros(int(seg * SR), np.int16)


def _habla(palabras, ritmo=2.5):
    """Simula voz: bloques de 0,3 s con micro-pausas de 0,1 s (no cuentan como corte)."""
    partes = []
    for _ in range(max(1, int(palabras / ritmo / 0.4))):
        partes += [_tono(0.3), _sil(0.1)]
    return np.concatenate(partes)


def _episodio(palabras, pausa=0.9):
    partes = [_sil(0.3)]
    for p in palabras:
        partes += [_habla(p), _sil(pausa)]
    return np.concatenate(partes)


def test_silencios_detecta_pausas_largas_y_no_las_micro():
    x = np.concatenate([_tono(1), _sil(0.5), _habla(10), _sil(0.8), _tono(1)])
    sil = voz_gemini.silencios(x, SR)
    assert len(sil) == 2
    assert abs((sil[0][1] - sil[0][0]) - 0.5) < 0.05


def test_cortar_un_trozo_por_segmento():
    textos = ["uno dos tres cuatro cinco", "a b c d e f g h i j", "x y z w v u t s", "fin fin fin"]
    x = _episodio([len(t.split()) for t in textos])
    trozos = voz_gemini.cortar(x, SR, textos)
    assert len(trozos) == 4
    assert all(len(t) > 0.3 * SR for t in trozos)


def test_cortar_ignora_una_pausa_interna_si_rompe_el_ritmo():
    # El 2.º segmento (20 palabras) tiene una pausa dramática más larga que las de corte
    textos = ["g " * 8, "e " * 20, "e " * 10, "c " * 6]
    x = np.concatenate([_sil(0.3), _habla(8), _sil(0.7), _habla(10), _sil(0.75), _habla(10),
                        _sil(0.7), _habla(10), _sil(0.7), _habla(6), _sil(0.5)])
    trozos = voz_gemini.cortar(x, SR, textos)
    assert len(trozos[1]) > 1.6 * len(trozos[2])


def test_cortar_sin_silencios_suficientes_falla():
    with pytest.raises(voz_gemini.GeminiVozError):
        voz_gemini.cortar(_tono(6), SR, ["a b", "c d", "e f"])


def test_a_pcm_bruto_y_audio_de():
    x = _tono(0.2)
    resp = {"steps": [{"type": "model_output", "content": [
        {"type": "audio", "data": base64.b64encode(x.tobytes()).decode()}]}]}
    y, sr = voz_gemini.a_pcm(voz_gemini.audio_de(resp))
    assert sr == SR and np.array_equal(x, y)
    with pytest.raises(voz_gemini.GeminiVozError):
        voz_gemini.audio_de({"steps": []})


def test_generar_locucion_reutiliza_bruto_sin_peticion(tmp_path, monkeypatch):
    textos = ["gancho " * 6, "escena " * 14, "escena " * 14, "escena " * 14, "sigue " * 4]
    bruto = tmp_path / "bruto.wav"
    voz_gemini.guardar_wav(_episodio([len(t.split()) for t in textos]), SR, bruto)
    monkeypatch.setattr(voz_gemini, "pedir_audio", lambda *a, **k: pytest.fail("no debe pedir"))
    loc, pidio = voz_gemini.generar_locucion(textos, tmp_path / "voz.wav", 1, 120, None, "Charon",
                                             bruto=bruto)
    assert not pidio and loc.ruta.exists()
    assert len(loc.tramos_escena) == 3 and len(loc.marcas_segmento) == 5


def _fake_piper(segmentos, modelo, salida, dmin, dmax, vel):
    Path(salida).parent.mkdir(parents=True, exist_ok=True)
    Path(salida).write_bytes(b"")
    return voz.Locucion(Path(salida), 30.0, 22050, [(0, 30)], vel, [(0, 30)])


@pytest.fixture
def con_gemini(cfg, monkeypatch):
    cfg.datos["proveedores"]["voz"]["gemini"] = {"activo": True, "voz": "Charon",
                                                 "max_peticiones_dia": 2}
    cfg.env["GEMINI_API_KEY"] = "clave-de-prueba"
    monkeypatch.setattr(voz, "generar_locucion", _fake_piper)
    return cfg


def test_429_marca_el_dia_y_pasa_a_piper(con_gemini, db, tmp_path, monkeypatch):
    def cuota(*a, **k):
        raise voz_gemini.CuotaTTSAgotada("429")
    monkeypatch.setattr(voz_gemini, "pedir_audio", cuota)
    vid = crear_video(db, "generando")
    loc = pipeline._locucion(con_gemini, db, vid, ["a", "b", "c"], tmp_path / "v" / "i0", 0)
    assert loc.sr == 22050
    assert db.kv_get("gemini_tts_agotado") == pipeline._hoy(con_gemini)
    assert [a["proveedor"] for a in db.assets_de(vid)] == ["piper"]
    # Con el día agotado ya no se vuelve a pedir
    monkeypatch.setattr(voz_gemini, "pedir_audio", lambda *a, **k: pytest.fail("no debe pedir"))
    pipeline._locucion(con_gemini, db, vid, ["a", "b", "c"], tmp_path / "w" / "i0", 0)


def test_limite_propio_diario(con_gemini, db, tmp_path, monkeypatch):
    db.kv_set(f"gemini_tts_peticiones:{pipeline._hoy(con_gemini)}", "2")
    monkeypatch.setattr(voz_gemini, "pedir_audio", lambda *a, **k: pytest.fail("no debe pedir"))
    vid = crear_video(db, "generando")
    assert pipeline._locucion(con_gemini, db, vid, ["a", "b", "c"], tmp_path / "v" / "i0", 0
                              ).sr == 22050


def test_gemini_ok_cuenta_peticion_y_guarda_bruto(con_gemini, db, tmp_path, monkeypatch):
    textos = ["gancho " * 6, "escena " * 14, "escena " * 14, "sigue " * 4]
    datos = _episodio([len(t.split()) for t in textos]).tobytes()
    monkeypatch.setattr(voz_gemini, "pedir_audio", lambda *a, **k: datos)
    con_gemini.datos["video"]["duracion_min"] = 1
    vid = crear_video(db, "generando")
    loc = pipeline._locucion(con_gemini, db, vid, textos, tmp_path / "v" / "intento0", 0)
    assert loc.sr == SR
    assert db.kv_get(f"gemini_tts_peticiones:{pipeline._hoy(con_gemini)}") == "1"
    assert (tmp_path / "v" / "voz_gemini_bruto.wav").exists()
    assert [a["proveedor"] for a in db.assets_de(vid)] == ["gemini-tts"]
