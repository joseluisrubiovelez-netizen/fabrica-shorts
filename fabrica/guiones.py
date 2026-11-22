"""Ideación y guiones: esquema JSON, validación, variedad, deduplicación y proveedores."""
from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

from . import llm
from .config import Config
from .db import DB
from .utils import jaccard, log, normalizar, tokens_clave

L = log("guiones")

ESTRUCTURAS = {
    "in_medias_res": "Empieza en el momento más tenso y luego explica cómo se llegó ahí.",
    "cronologica": "Narra en orden, con marcas de tiempo concretas (hora, fecha) que aceleran.",
    "cuenta_atras": "Organiza el relato en 3 detalles numerados, del menos al más inquietante.",
    "documento_encontrado": "Lee un documento, nota o registro encontrado, con citas literales.",
    "testimonio": "Primera persona, frases cortas, como quien lo cuenta en voz baja.",
    "dato_imposible": "Parte de un dato concreto que no cuadra y tira del hilo.",
    "dos_versiones": "Presenta la explicación oficial y luego la que nadie quiso contar.",
    "pregunta_al_espectador": "Interpela al espectador y le hace partícipe del misterio.",
}

TIPOS_GANCHO = {
    "pregunta": "una pregunta inquietante y concreta",
    "afirmacion_imposible": "una afirmación que parece imposible",
    "advertencia": "una advertencia directa al espectador",
    "dato_concreto": "un dato concreto (hora, número, lugar) que engancha",
    "sonido": "la descripción de un sonido extraño",
    "segunda_persona": "una situación en segunda persona ('Imagina que...')",
}

SFX = ["ninguno", "viento", "latido", "golpe", "estatica", "campana", "puerta", "goteo"]

# Lista mínima de seguridad (regla 7) y de copyright/personas reales (regla 2).
PROHIBIDAS = [
    "descuartiz", "decapit", "mutilad", "violaci", "violad", "sexo", "sexual", "desnud",
    "tortur", "suicid", "autolesi", "pornogr", "sangre a borbotones", "vísceras", "visceras",
    "disney", "marvel", "harry potter", "stephen king", "pennywise", "freddy krueger",
    "iker jiménez", "iker jimenez", "cuarto milenio", "netflix", "warner",
]

PALABRAS_MIN, PALABRAS_MAX = 55, 115
GANCHO_MAX_PALABRAS = 9


def texto_narrado(g: dict[str, Any]) -> str:
    partes = [g["gancho"]] + [e["narracion"] for e in g["escenas"]] + [g.get("cta", "")]
    return " ".join(p.strip() for p in partes if p and p.strip())


def validar_guion(g: dict[str, Any], serie_tipo: str = "ficcion") -> list[str]:
    errores: list[str] = []
    for campo in ("titulo", "tema", "gancho", "escenas", "descripcion", "hashtags", "cta"):
        if not g.get(campo):
            errores.append(f"falta '{campo}'")
    if errores:
        return errores
    if len(g["titulo"]) > 90:
        errores.append("título demasiado largo (>90)")
    if len(g["gancho"].split()) > GANCHO_MAX_PALABRAS:
        errores.append(f"gancho demasiado largo (>{GANCHO_MAX_PALABRAS} palabras, no cabe en 3 s)")
    escenas = g["escenas"]
    if not 3 <= len(escenas) <= 8:
        errores.append("debe haber entre 3 y 8 escenas")
    for i, e in enumerate(escenas):
        for campo in ("narracion", "prompt_imagen"):
            if not str(e.get(campo, "")).strip():
                errores.append(f"escena {i + 1}: falta '{campo}'")
        if e.get("sfx", "ninguno") not in SFX:
            errores.append(f"escena {i + 1}: sfx '{e.get('sfx')}' no permitido")
    n = len(texto_narrado(g).split())
    if not PALABRAS_MIN <= n <= PALABRAS_MAX:
        errores.append(f"{n} palabras narradas; deben ser {PALABRAS_MIN}-{PALABRAS_MAX} (20-45 s)")
    for plat in ("youtube", "tiktok", "instagram"):
        if not g["hashtags"].get(plat):
            errores.append(f"faltan hashtags de {plat}")
    if serie_tipo == "historico":
        if not g.get("fuentes"):
            errores.append("serie histórica sin fuentes verificables")
        if g.get("es_ficcion") is True:
            errores.append("serie histórica marcada como ficción")
        if not all(str(f).startswith("https://") for f in g.get("fuentes") or []):
            errores.append("las fuentes deben ser URLs https verificables")
    elif g.get("es_ficcion") is not True:
        errores.append("serie de ficción debe tener es_ficcion=true")
    bajo = json.dumps(g, ensure_ascii=False).lower()
    for p in PROHIBIDAS:
        if p in bajo:
            errores.append(f"contenido no permitido: '{p}'")
    return errores


def es_repetido(g: dict[str, Any], temas_previos: list[str], ganchos_previos: list[str],
                umbral_tema: float = 0.5, umbral_gancho: float = 0.6) -> str | None:
    tk = tokens_clave(g["tema"] + " " + g["titulo"])
    for t in temas_previos:
        if jaccard(tk, set(t.split())) >= umbral_tema:
            return f"tema demasiado parecido a uno anterior: '{t[:60]}'"
    gk = tokens_clave(g["gancho"])
    inicio = " ".join(normalizar(g["gancho"]).split()[:2])
    for h in ganchos_previos[:40]:
        if jaccard(gk, tokens_clave(h)) >= umbral_gancho:
            return "gancho demasiado parecido a uno reciente"
    if inicio and sum(1 for h in ganchos_previos[:8]
                      if " ".join(normalizar(h).split()[:2]) == inicio) >= 2:
        return "el gancho empieza igual que varios recientes"
    return None


def clave_tema(g: dict[str, Any]) -> str:
    return " ".join(sorted(tokens_clave(g["tema"] + " " + g["titulo"])))


def elegir_serie(cfg: Config, db: DB, rng: random.Random | None = None) -> str:
    """Elige la serie con mayor déficit respecto a su peso en los últimos 30 vídeos."""
    rng = rng or random.Random()
    filas = db.con.execute("SELECT serie FROM videos ORDER BY id DESC LIMIT 30").fetchall()
    cuenta = Counter(r[0] for r in filas)
    total = max(1, len(filas))
    deficit = {s["id"]: float(s["peso"]) - cuenta.get(s["id"], 0) / total for s in cfg["series"]}
    mejor = max(deficit.values())
    candidatas = [s for s, d in deficit.items() if d >= mejor - 0.05]
    return rng.choice(sorted(candidatas))


def elegir_variedad(db: DB, rng: random.Random, n: int) -> list[tuple[str, str]]:
    """Combina estructura y tipo de gancho evitando los usados recientemente."""
    recientes = [json.loads(r[0]) for r in
                 db.con.execute("SELECT json FROM guiones ORDER BY id DESC LIMIT 12")]
    usadas_e = Counter(g.get("estructura") for g in recientes)
    usadas_g = Counter(g.get("tipo_gancho") for g in recientes)
    est = sorted(ESTRUCTURAS, key=lambda e: (usadas_e[e], rng.random()))
    gan = sorted(TIPOS_GANCHO, key=lambda t: (usadas_g[t], rng.random()))
    return [(est[i % len(est)], gan[i % len(gan)]) for i in range(n)]


def construir_prompt(cfg: Config, serie: dict[str, Any], combinaciones: list[tuple[str, str]],
                     temas_previos: list[str]) -> str:
    historico = serie["tipo"] == "historico"
    pedidos = "\n".join(
        f"- Guion {i + 1}: estructura '{e}' ({ESTRUCTURAS[e]}); gancho tipo '{t}' ({TIPOS_GANCHO[t]})."
        for i, (e, t) in enumerate(combinaciones))
    evitar = "; ".join(temas_previos[-60:]) or "ninguno"
    reglas_hist = (
        "Es contenido HISTÓRICO/FOLCLÓRICO REAL de España: solo hechos verificables, sin inventar "
        "fechas, cifras ni nombres. Si es una leyenda, dilo ('cuenta la leyenda...'). Incluye en "
        "'fuentes' 1-3 URLs públicas fiables (Wikipedia en español, webs oficiales, prensa). "
        "es_ficcion=false."
        if historico else
        "Es FICCIÓN: lugares y personas inventados (nunca reales). es_ficcion=true. "
        "La descripción debe empezar por 'Relato de ficción.'")
    return f"""Eres guionista de un canal de Shorts de misterio y terror SUAVE en castellano de España.
Serie: "{serie['nombre']}". Premisa: {serie['premisa']}
{reglas_hist}

Escribe {len(combinaciones)} guiones DISTINTOS entre sí, uno por cada pedido:
{pedidos}

Reglas obligatorias:
- Castellano de España natural (vosotros, expresiones peninsulares), frases cortas para voz en off.
- Duración narrada 25-40 s: entre 70 y 100 palabras en total (gancho + escenas + cta).
- 'gancho': máximo 9 palabras, se dice en el primer segundo y debe atrapar.
- Arco: gancho -> desarrollo -> giro o cliffhanger -> 'cta' suave (p. ej. invitar a seguir la serie),
  sin pedir likes de forma agresiva.
- 4 a 6 escenas. Cada escena: 'narracion' (lo que se dice), 'texto_pantalla' (0-4 palabras o ""),
  'prompt_imagen' (en INGLÉS, describe la imagen sin personas reconocibles ni caras en primer plano),
  'busqueda_stock' (2-3 palabras en inglés para buscar un clip de stock), 'sfx' (uno de {SFX}).
- Terror SUAVE: nada de gore, violencia gráfica, contenido sexual, autolesiones ni nada dirigido a menores.
- Sin personas reales, famosos, marcas ni personajes con copyright.
- 'titulo' <= 70 caracteres, intrigante y sin clickbait engañoso.
- 'hashtags': listas por plataforma (youtube incluye #Shorts; 3-6 cada una, en español).
- No repitas estos temas ya usados: {evitar}

Devuelve SOLO un objeto JSON: {{"guiones": [ ... ]}} donde cada guion tiene exactamente:
{{"tema": str, "titulo": str, "estructura": str, "tipo_gancho": str, "es_ficcion": bool,
"gancho": str, "escenas": [{{"narracion": str, "texto_pantalla": str, "prompt_imagen": str,
"busqueda_stock": str, "sfx": str}}], "cta": str, "descripcion": str,
"hashtags": {{"youtube": [str], "tiktok": [str], "instagram": [str]}}, "fuentes": [str]}}"""


def _llamar_json(cfg: Config, nombre: str, prompt: str) -> Any:
    prov = cfg["proveedores"]
    if nombre == "gemini":
        clave = cfg.secreto("GEMINI_API_KEY")
        if not clave:
            raise llm.LLMError("GEMINI_API_KEY no configurada")
        ultimo: Exception | None = None
        for modelo in prov.get("gemini_modelos", ["gemini-flash-latest"]):
            try:
                return llm.extraer_json(llm.gemini(prompt, clave, modelo))
            except llm.LLMError as e:
                ultimo = e
                L.warning("%s", e)
        raise llm.LLMError(str(ultimo))
    if nombre == "groq":
        clave = cfg.secreto("GROQ_API_KEY")
        if not clave:
            raise llm.LLMError("GROQ_API_KEY no configurada")
        return llm.extraer_json(llm.groq(prompt, clave, prov["groq_modelo"]))
    raise llm.LLMError(f"Proveedor de guiones desconocido: {nombre}")


def _llamar_proveedor(cfg: Config, nombre: str, prompt: str) -> list[dict[str, Any]]:
    return normalizar_respuesta(_llamar_json(cfg, nombre, prompt))


def normalizar_respuesta(datos: Any) -> list[dict[str, Any]]:
    """Acepta {"guiones": [...]}, una lista suelta o un único guion; descarta lo demás."""
    if isinstance(datos, dict):
        datos = datos.get("guiones", [datos] if "escenas" in datos else [])
    if not isinstance(datos, list):
        return []
    return [g for g in datos if isinstance(g, dict)]


def _historicos(cfg: Config, db: DB, serie: dict[str, Any], proveedor: str,
                rng: random.Random, n: int) -> list[dict[str, Any]]:
    """Serie histórica: guion basado SOLO en una fuente y verificado afirmación a afirmación."""
    from . import fuentes
    return fuentes.generar(cfg, db, serie, lambda p: _llamar_json(cfg, proveedor, p),
                           elegir_variedad(db, rng, n),
                           {"estructuras": ESTRUCTURAS, "ganchos": TIPOS_GANCHO}, SFX, rng)


def cargar_semillas(cfg: Config) -> list[dict[str, Any]]:
    ruta = Path(cfg.raiz) / "seeds" / "guiones.json"
    if not ruta.exists():
        return []
    return json.loads(ruta.read_text(encoding="utf-8"))


def generar_lote(cfg: Config, db: DB, serie_id: str | None = None,
                 rng: random.Random | None = None) -> int:
    """Genera un lote de guiones válidos y no repetidos para una serie. Devuelve cuántos guardó."""
    rng = rng or random.Random()
    serie_id = serie_id or elegir_serie(cfg, db, rng)
    serie = cfg.serie(serie_id)
    n = int(cfg["proveedores"].get("guiones_por_lote", 5))
    temas = db.temas_previos()
    ganchos = db.ganchos_recientes()
    guardados = 0
    for proveedor in cfg["proveedores"]["guiones"]:
        try:
            if proveedor == "semillas":
                candidatos = [g for g in cargar_semillas(cfg) if g.get("serie") == serie_id]
            elif serie["tipo"] == "historico":
                candidatos = _historicos(cfg, db, serie, proveedor, rng, min(n, 2))
            else:
                prompt = construir_prompt(cfg, serie, elegir_variedad(db, rng, n), temas)
                candidatos = _llamar_proveedor(cfg, proveedor, prompt)
        except llm.LLMError as e:
            L.warning("Proveedor %s no disponible: %s", proveedor, e)
            db.evento("aviso", "guiones", f"{proveedor}: {e}")
            continue
        for g in candidatos:
            g["serie"] = serie_id
            try:
                errores = validar_guion(g, serie["tipo"])
                motivo = None if errores else es_repetido(g, temas, ganchos)
            except (AttributeError, TypeError, KeyError) as e:   # JSON con forma inesperada
                errores, motivo = [f"formato inesperado: {e}"], None
            if errores or motivo:
                L.info("Guion descartado (%s): %s", g.get("titulo", "?"), errores or motivo)
                continue
            clave = clave_tema(g)
            db.guardar_guion(serie_id, g["tema"], clave, proveedor, g)
            temas.append(clave)
            ganchos.insert(0, g["gancho"])
            guardados += 1
        if guardados:
            L.info("Guardados %d guiones de '%s' con %s", guardados, serie_id, proveedor)
            return guardados
    return guardados
