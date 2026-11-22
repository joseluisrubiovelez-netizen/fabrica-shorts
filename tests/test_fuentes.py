import copy
import random

from conftest import guion_valido

from fabrica import fuentes, guiones

ART = {"titulo": "Santa Compaña", "url": "https://es.wikipedia.org/wiki/Santa_Compa%C3%B1a",
       "texto": "La Santa Compaña es una leyenda gallega... " * 20}


def _guion_hist():
    g = copy.deepcopy(guion_valido())
    g.pop("fuentes", None)
    g["es_ficcion"] = False
    return g


def _llamador(veredicto):
    def llamar(prompt):
        if "verificador" in prompt:
            return veredicto
        assert "EXCLUSIVAMENTE" in prompt and ART["texto"][:30] in prompt
        return _guion_hist()
    return llamar


def _generar(cfg, db, llamar, monkeypatch):
    monkeypatch.setattr(fuentes, "obtener_articulo", lambda c, t: ART)
    return fuentes.generar(cfg, db, cfg.serie("espana_oculta"), llamar,
                           [("cronologica", "pregunta")],
                           {"estructuras": guiones.ESTRUCTURAS, "ganchos": guiones.TIPOS_GANCHO},
                           guiones.SFX, random.Random(1))


def test_guion_verificado_lleva_la_fuente(cfg, db, monkeypatch):
    ok = {"afirmaciones": [{"texto": "x", "respaldada": True}]}
    res = _generar(cfg, db, _llamador(ok), monkeypatch)
    assert len(res) == 1
    assert res[0]["fuentes"] == [ART["url"]] and res[0]["es_ficcion"] is False
    assert guiones.validar_guion(res[0], "historico") == []


def test_afirmacion_sin_respaldo_descarta(cfg, db, monkeypatch):
    malo = {"afirmaciones": [{"texto": "En 1842 ardió el teatro", "respaldada": False}]}
    assert _generar(cfg, db, _llamador(malo), monkeypatch) == []
    assert db.con.execute("SELECT COUNT(*) FROM eventos WHERE componente='verificacion'"
                          ).fetchone()[0] == 1


def test_verificador_vacio_no_cuenta_como_ok():
    assert fuentes.no_respaldadas({}) and fuentes.no_respaldadas({"afirmaciones": []})


def test_tema_no_se_repite_y_agota_intentos(cfg, db, monkeypatch):
    monkeypatch.setattr(fuentes, "temas", lambda c: [{"articulo": "A", "tipo": "leyenda"}])
    rng = random.Random(0)
    fuentes.marcar(db, "A", usado=True)
    assert fuentes.elegir_tema(cfg, db, rng) is None
    monkeypatch.setattr(fuentes, "temas", lambda c: [{"articulo": "B", "tipo": "leyenda"}])
    for _ in range(3):
        fuentes.marcar(db, "B", usado=False)
    assert fuentes.elegir_tema(cfg, db, rng) is None


def test_fuente_no_https_invalida():
    g = guion_valido(es_ficcion=False, fuentes=["Archivo de la Niebla"])
    assert any("https" in e for e in guiones.validar_guion(g, "historico"))
