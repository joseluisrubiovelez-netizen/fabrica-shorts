from fabrica import qa
from fabrica.subtitulos import Cue, Palabra, agrupar, alinear, proporcional

VIDEO = {"ancho": 1080, "alto": 1920, "fps": 30, "duracion_min": 20, "duracion_max": 45}


def probe(w=1080, h=1920, vc="h264", ac="aac", dur=30.0, fps="30/1", pix="yuv420p"):
    s = [{"codec_type": "video", "width": w, "height": h, "codec_name": vc, "r_frame_rate": fps,
          "pix_fmt": pix}]
    if ac:
        s.append({"codec_type": "audio", "codec_name": ac})
    return {"streams": s, "format": {"duration": str(dur)}}


def test_tecnico_ok():
    r = qa.ResultadoQA()
    qa.evaluar_tecnico(probe(), VIDEO, r)
    assert r.ok, r.fallos


def test_tecnico_detecta_errores():
    r = qa.ResultadoQA()
    qa.evaluar_tecnico(probe(w=1920, h=1080, vc="hevc", ac=None, dur=60, fps="25/1"), VIDEO, r)
    texto = " ".join(r.fallos)
    for clave in ("resolución", "códec de vídeo", "sin pista de audio", "duración", "fps"):
        assert clave in texto


def test_loudness():
    r = qa.ResultadoQA()
    qa.evaluar_loudness(-14.0, (-17.5, -11), r)
    assert r.ok
    qa.evaluar_loudness(-25.0, (-17.5, -11), r)
    qa.evaluar_loudness(None, (-17.5, -11), r)
    assert len(r.fallos) == 2


def test_silencios():
    r = qa.ResultadoQA()
    qa.evaluar_silencios([(29.5, 30.1)], 30.1, 1.3, r)   # silencio final: permitido
    assert r.ok
    qa.evaluar_silencios([(10.0, 12.0)], 30.0, 1.3, r)   # hueco en medio
    qa.evaluar_silencios([(0.0, 1.2)], 30.0, 1.3, r)     # arranque tardío
    assert len(r.fallos) == 2


def cues_ritmo(pps, n=30):
    return agrupar([Palabra(f"p{i}", 0.2 + i / pps, 0.2 + (i + 0.9) / pps) for i in range(n)])


def test_subtitulos_legibles():
    r = qa.ResultadoQA()
    qa.evaluar_subtitulos(cues_ritmo(3.0), 30, 4.6, r)
    assert r.ok, r.fallos


def test_subtitulos_demasiado_rapidos_o_ausentes():
    r = qa.ResultadoQA()
    qa.evaluar_subtitulos(cues_ritmo(7.0), 30, 4.6, r)
    assert any("rápidos" in f for f in r.fallos)
    r2 = qa.ResultadoQA()
    qa.evaluar_subtitulos([], 30, 4.6, r2)
    assert not r2.ok


def test_subtitulo_tardio():
    r = qa.ResultadoQA()
    cues = [Cue([Palabra("hola", 1.5, 1.9)])]
    qa.evaluar_subtitulos(cues, 30, 4.6, r)
    assert any("primer subtítulo" in f for f in r.fallos)


def test_gancho_tres_segundos():
    r = qa.ResultadoQA()
    qa.evaluar_gancho(2.7, r)
    assert r.ok
    qa.evaluar_gancho(4.1, r)
    assert not r.ok


def test_licencias_obligatorias():
    ok = [{"id": 1, "tipo": "voz", "fuente": "piper", "licencia": "CC0"},
          {"id": 2, "tipo": "visual", "fuente": "x", "licencia": "Pexels"},
          {"id": 3, "tipo": "musica", "fuente": "y", "licencia": "propia"}]
    r = qa.ResultadoQA()
    qa.evaluar_licencias(ok, r)
    assert r.ok
    r2 = qa.ResultadoQA()
    qa.evaluar_licencias(ok[:2] + [{"id": 4, "tipo": "musica", "fuente": None, "licencia": ""}], r2)
    assert any("sin fuente/licencia" in f for f in r2.fallos)
    r3 = qa.ResultadoQA()
    qa.evaluar_licencias(ok[:1], r3)
    assert any("visual" in f for f in r3.fallos)


def test_brillo():
    r = qa.ResultadoQA()
    qa.evaluar_brillo([30, 25, 40], r)
    assert r.ok
    qa.evaluar_brillo([30, 2.0], r)
    assert not r.ok


def test_alinear_corrige_errores_de_whisper():
    guion = "Expediente doce. Valdemora, un pueblo".split()
    whisper = [Palabra("expediente", 0.1, 0.6), Palabra("12", 0.6, 0.9),
               Palabra("Valde", 1.0, 1.3), Palabra("un", 1.4, 1.5), Palabra("pueblo", 1.5, 1.9)]
    res = alinear(guion, whisper)
    assert [p.texto for p in res] == guion            # texto exacto del guion
    assert res[0].ini == 0.1 and res[-1].fin == 1.9
    assert all(a.fin <= b.ini + 1e-6 for a, b in zip(res, res[1:]))


def test_proporcional_respeta_tramos():
    res = proporcional(["hola mundo", "otra frase aquí"], [(0.0, 1.0), (2.0, 3.0)])
    assert len(res) == 5
    assert res[1].fin <= 1.0 + 1e-6 and res[2].ini >= 2.0


def test_agrupar_limita_longitud():
    pal = [Palabra(w, i * 0.3, i * 0.3 + 0.25) for i, w in
           enumerate("esto es una frase bastante larga para probar los cortes.".split())]
    for c in agrupar(pal):
        assert len(c.palabras) <= 3
