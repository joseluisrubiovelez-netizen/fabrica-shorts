"""Guiones históricos verificables: se escriben SOLO con el texto de una fuente y se verifican.

1. Tema de una lista curada (seeds/temas_historicos.yaml).
2. Texto del artículo con la API oficial de Wikipedia (MediaWiki Action API).
3. El LLM escribe el guion usando solo ese texto.
4. Un segundo paso del LLM comprueba cada afirmación contra la fuente; si alguna no está
   respaldada, el guion se descarta.
"""
from __future__ import annotations

import hashlib
import json
import random
import time
from pathlib import Path
from typing import Any, Callable

import requests
import yaml

from .config import Config
from .db import DB
from .utils import log

L = log("fuentes")
API = "https://es.wikipedia.org/w/api.php"
UA = "FabricaShortsMisterio/0.1 (herramienta personal sin fines de scraping)"
MAX_TEXTO = 7000


def temas(cfg: Config) -> list[dict[str, str]]:
    ruta = Path(cfg.raiz) / "seeds" / "temas_historicos.yaml"
    return yaml.safe_load(ruta.read_text(encoding="utf-8")) if ruta.exists() else []


def obtener_articulo(cfg: Config, titulo: str) -> dict[str, str] | None:
    clave = hashlib.sha1(titulo.encode()).hexdigest()
    cache = cfg.dir_datos / "cache" / f"wiki_{clave}.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < 30 * 86400:
        return json.loads(cache.read_text(encoding="utf-8"))
    r = requests.get(API, timeout=30, headers={"User-Agent": UA}, params={
        "action": "query", "prop": "extracts|info", "explaintext": 1, "redirects": 1,
        "inprop": "url", "titles": titulo, "format": "json", "formatversion": 2})
    r.raise_for_status()
    paginas = r.json().get("query", {}).get("pages", [])
    if not paginas or paginas[0].get("missing") or len(paginas[0].get("extract", "")) < 400:
        L.warning("Artículo no disponible o demasiado corto: %s", titulo)
        return None
    p = paginas[0]
    art = {"titulo": p["title"], "url": p["fullurl"], "texto": p["extract"][:MAX_TEXTO]}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(art, ensure_ascii=False), encoding="utf-8")
    return art


def elegir_tema(cfg: Config, db: DB, rng: random.Random) -> dict[str, str] | None:
    usados = set(json.loads(db.kv_get("historicos_usados", "[]") or "[]"))
    intentos = json.loads(db.kv_get("historicos_intentos", "{}") or "{}")
    libres = [t for t in temas(cfg) if t["articulo"] not in usados
              and intentos.get(t["articulo"], 0) < 3]
    return rng.choice(libres) if libres else None


def marcar(db: DB, articulo: str, usado: bool) -> None:
    if usado:
        usados = json.loads(db.kv_get("historicos_usados", "[]") or "[]")
        db.kv_set("historicos_usados", json.dumps(sorted(set(usados) | {articulo}),
                                                  ensure_ascii=False))
    else:
        intentos = json.loads(db.kv_get("historicos_intentos", "{}") or "{}")
        intentos[articulo] = intentos.get(articulo, 0) + 1
        db.kv_set("historicos_intentos", json.dumps(intentos, ensure_ascii=False))


def prompt_guion(serie: dict[str, Any], art: dict[str, str], tipo: str, estructura: str,
                 desc_estructura: str, tipo_gancho: str, desc_gancho: str, sfx: list[str]) -> str:
    marco = ("Es una LEYENDA o creencia popular: preséntala siempre como tal ('cuenta la leyenda', "
             "'según la tradición'), nunca como un hecho." if tipo == "leyenda" else
             "Es un SUCESO documentado: cuenta solo lo que dice la fuente y, si hay polémica, "
             "presenta las distintas posturas sin tomar partido.")
    return f"""Eres guionista de un canal de Shorts de misterio en castellano de España.
Serie: "{serie['nombre']}". {marco}

TEXTO FUENTE (artículo "{art['titulo']}" de Wikipedia):
<<<
{art['texto']}
>>>

REGLA PRINCIPAL: usa EXCLUSIVAMENTE hechos que aparezcan en el TEXTO FUENTE. No añadas fechas,
cifras, nombres, lugares, citas ni sucesos que no estén en él. Si dudas de algo, no lo digas.
No menciones a personas vivas. No inventes citas textuales.

Formato: estructura '{estructura}' ({desc_estructura}); gancho tipo '{tipo_gancho}' ({desc_gancho}).
- 70-100 palabras en total (gancho + escenas + cta), frases cortas para voz en off.
- 'gancho': máximo 9 palabras. 4-5 escenas. Terror SUAVE, sin gore ni violencia explícita.
- Cada escena: 'narracion', 'texto_pantalla' (0-4 palabras o ""), 'prompt_imagen' (en inglés, sin
  caras reconocibles), 'busqueda_stock' (2-3 palabras en inglés), 'sfx' (uno de {sfx}).
- 'titulo' <= 70 caracteres. 'hashtags' por plataforma (youtube incluye #Shorts).

Devuelve SOLO JSON: {{"tema": str, "titulo": str, "estructura": "{estructura}",
"tipo_gancho": "{tipo_gancho}", "es_ficcion": false, "gancho": str, "escenas": [{{"narracion": str,
"texto_pantalla": str, "prompt_imagen": str, "busqueda_stock": str, "sfx": str}}], "cta": str,
"descripcion": str, "hashtags": {{"youtube": [str], "tiktok": [str], "instagram": [str]}}}}"""


def prompt_verificacion(art: dict[str, str], narracion: str) -> str:
    return f"""Eres verificador de datos. Compara la NARRACIÓN con el TEXTO FUENTE.

TEXTO FUENTE:
<<<
{art['texto']}
>>>

NARRACIÓN:
<<<
{narracion}
>>>

Divide la narración en afirmaciones de hecho (fechas, lugares, cifras, sucesos, atribuciones).
Una afirmación está respaldada solo si el TEXTO FUENTE la dice o la implica claramente. Las frases
presentadas como leyenda están respaldadas si la fuente recoge esa leyenda. Las llamadas a la acción
y las preguntas retóricas no son afirmaciones.

Devuelve SOLO JSON: {{"afirmaciones": [{{"texto": str, "respaldada": bool, "motivo": str}}]}}"""


def no_respaldadas(veredicto: Any) -> list[str]:
    afs = (veredicto or {}).get("afirmaciones")
    if not isinstance(afs, list) or not afs:
        return ["el verificador no devolvió afirmaciones"]
    return [a.get("texto", "?") for a in afs if a.get("respaldada") is not True]


def generar(cfg: Config, db: DB, serie: dict[str, Any], llamar: Callable[[str], Any],
            combinaciones: list[tuple[str, str]], descripciones: dict[str, dict[str, str]],
            sfx: list[str], rng: random.Random) -> list[dict[str, Any]]:
    """Devuelve guiones históricos verificados. `llamar(prompt) -> JSON` usa el proveedor LLM."""
    res = []
    for estructura, tipo_gancho in combinaciones:
        tema = elegir_tema(cfg, db, rng)
        if tema is None:
            L.warning("No quedan temas históricos disponibles: añade más a temas_historicos.yaml")
            break
        try:
            art = obtener_articulo(cfg, tema["articulo"])
        except requests.RequestException as e:
            L.warning("Wikipedia no disponible (%s)", e)
            break
        if art is None:
            marcar(db, tema["articulo"], usado=False)
            continue
        g = llamar(prompt_guion(serie, art, tema.get("tipo", "leyenda"), estructura,
                                descripciones["estructuras"][estructura], tipo_gancho,
                                descripciones["ganchos"][tipo_gancho], sfx))
        if isinstance(g, dict) and "guiones" in g:
            g = (g["guiones"] or [None])[0]
        if not isinstance(g, dict) or not g.get("escenas"):
            marcar(db, tema["articulo"], usado=False)
            continue
        from .guiones import texto_narrado
        malas = no_respaldadas(llamar(prompt_verificacion(art, texto_narrado(g))))
        if malas:
            L.warning("Guion histórico '%s' descartado: afirmaciones sin respaldo %s",
                      g.get("titulo"), malas[:3])
            db.evento("aviso", "verificacion", f"{tema['articulo']}: {malas[:3]}")
            marcar(db, tema["articulo"], usado=False)
            continue
        g.update(es_ficcion=False, fuentes=[art["url"]], tema=f"{art['titulo']} {g.get('tema', '')}",
                 verificado=True)
        marcar(db, tema["articulo"], usado=True)
        res.append(g)
    return res
