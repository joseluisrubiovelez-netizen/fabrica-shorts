import copy
import json

import pytest
from conftest import RAIZ, guion_valido

from fabrica import guiones, llm


def test_todas_las_semillas_son_validas(cfg):
    for g in json.loads((RAIZ / "seeds" / "guiones.json").read_text(encoding="utf-8")):
        assert guiones.validar_guion(g, cfg.serie(g["serie"])["tipo"]) == [], g["titulo"]


@pytest.mark.parametrize("cambio,esperado", [
    ({"gancho": "uno dos tres cuatro cinco seis siete ocho nueve diez once doce"}, "gancho"),
    ({"es_ficcion": False}, "ficción"),
    ({"descripcion": "un relato sexual"}, "no permitido"),
    ({"titulo": "Historia de Harry Potter"}, "no permitido"),
    ({"hashtags": {"youtube": ["#a"], "tiktok": [], "instagram": ["#b"]}}, "tiktok"),
])
def test_validacion_detecta_problemas(cambio, esperado):
    g = guion_valido(**cambio)
    errores = guiones.validar_guion(g, "ficcion")
    assert any(esperado in e for e in errores), errores


def test_historico_exige_fuentes():
    g = guion_valido(es_ficcion=False, fuentes=[])
    assert any("fuentes" in e for e in guiones.validar_guion(g, "historico"))


def test_longitud_narrada():
    g2 = copy.deepcopy(guion_valido())
    g2["escenas"] = g2["escenas"][:3]
    for e in g2["escenas"]:
        e["narracion"] = "Corto."
    assert any("palabras" in e for e in guiones.validar_guion(g2, "ficcion"))


def test_repeticion_de_tema_y_gancho():
    g = guion_valido()
    previo = guiones.clave_tema(g)
    assert guiones.es_repetido(g, [previo], []) is not None
    assert guiones.es_repetido(g, [], [g["gancho"]]) is not None
    assert guiones.es_repetido(g, ["algo totalmente distinto"], ["otro gancho diferente"]) is None


def test_variedad_sin_repetir_combinaciones(db):
    import random
    combos = guiones.elegir_variedad(db, random.Random(1), 5)
    assert len({e for e, _ in combos}) == 5
    assert len({t for _, t in combos}) == 5


def test_prompt_incluye_reglas(cfg):
    p = guiones.construir_prompt(cfg, cfg.serie("espana_oculta"),
                                 [("cronologica", "pregunta")], ["tema viejo"])
    assert "verificables" in p and "tema viejo" in p and "SUAVE" in p


def test_extraer_json_tolerante():
    assert llm.extraer_json('```json\n{"guiones": []}\n```') == {"guiones": []}
    assert llm.extraer_json('Aquí tienes: {"a": 1} gracias') == {"a": 1}
    with pytest.raises(llm.LLMError):
        llm.extraer_json("nada")


def test_proveedor_caido_pasa_al_siguiente(cfg, db, monkeypatch):
    def caer(*a, **k):
        raise llm.LLMError("503")
    monkeypatch.setattr(guiones, "_llamar_proveedor", caer)
    n = guiones.generar_lote(cfg, db, "lo_que_oi")
    assert n > 0
    assert db.con.execute("SELECT proveedor FROM guiones").fetchone()[0] == "semillas"
