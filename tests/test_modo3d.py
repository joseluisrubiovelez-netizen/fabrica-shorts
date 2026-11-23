"""Modo 3D: mapa de profundidad y parallax sobre imágenes fijas."""
import numpy as np
import pytest
from PIL import Image

from fabrica import profundidad, render


def _escena_sintetica(tmp_path, movimiento="pan_der"):
    """Cielo arriba (lejos) y un bloque nítido abajo (cerca)."""
    img = np.zeros((480, 270, 3), np.uint8)
    img[:240] = (40, 60, 120)
    img[240:] = (90, 70, 50)
    img[300:440:8, 60:210] = 255          # textura nítida en primer plano
    ruta = tmp_path / "esc.png"
    Image.fromarray(img).save(ruta)
    return render.Escena("imagen", ruta, 0.0, 2.0, movimiento)


def test_heuristica_suelo_mas_cerca_que_cielo(tmp_path):
    img = np.asarray(Image.open(_escena_sintetica(tmp_path).ruta).convert("RGB"))
    d, metodo = profundidad.estimar(img, tmp_path, modelo="no_existe.onnx")
    assert metodo == "heuristica"
    assert d.shape == img.shape[:2] and d.dtype == np.float32
    assert 0.0 <= d.min() and d.max() <= 1.0
    assert d[400:].mean() > d[:150].mean() + 0.2


def test_modelo_roto_cae_a_heuristica(tmp_path):
    roto = tmp_path / "roto.onnx"
    roto.write_bytes(b"esto no es un modelo")
    img = np.full((64, 64, 3), 128, np.uint8)
    _, metodo = profundidad.estimar(img, tmp_path, modelo=roto)
    assert metodo == "heuristica"


@pytest.mark.parametrize("mov", render.MOVIMIENTOS)
def test_parallax_parte_y_acaba_simetrico(mov):
    ox0, oy0, zp0 = render.parametros_parallax(mov, 0.0, 10.0, 1.0)
    ox1, oy1, zp1 = render.parametros_parallax(mov, 1.0, 10.0, 1.0)
    assert (ox0, oy0, zp0) != (ox1, oy1, zp1)          # siempre hay movimiento 3D
    assert abs(ox0 + ox1) < 1e-9 and abs(oy0 + oy1) < 1e-9


def test_modo3d_desde_config():
    m = render.Modo3D.desde({"activo": True, "intensidad": 1.5})
    assert m.activo and m.intensidad == 1.5 and m.desenfoque_fondo == 0.5
    assert not render.Modo3D.desde(None).activo


def test_fuente_imagen_3d_genera_fotogramas_y_mueve_planos(tmp_path):
    esc = _escena_sintetica(tmp_path)
    W, H = 108, 192
    plano = render.FuenteImagen(esc, W, H, render.Estilo())
    m3d = render.FuenteImagen(esc, W, H, render.Estilo(),
                              render.Modo3D(activo=True, modelo="no_existe.onnx"), str(tmp_path))
    assert m3d.metodo_prof == "heuristica"
    for t in (0.0, 1.0, 2.0):
        f = m3d.frame(t)
        assert f.shape == (H, W, 3) and f.dtype == np.uint8
    # El 3D no es el mismo encuadre que el Ken Burns plano
    assert np.abs(m3d.frame(1.8).astype(int) - plano.frame(1.8).astype(int)).mean() > 0.5
    # Y la imagen se mueve entre el principio y el final
    assert np.abs(m3d.frame(0.0).astype(int) - m3d.frame(2.0).astype(int)).mean() > 2


def test_modo3d_inactivo_no_calcula_profundidad(tmp_path):
    f = render.FuenteImagen(_escena_sintetica(tmp_path), 108, 192, render.Estilo(),
                            render.Modo3D(activo=False))
    assert f.prof is None and f.metodo_prof == ""
