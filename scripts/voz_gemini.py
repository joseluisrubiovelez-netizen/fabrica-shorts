"""Locución por escena con Gemini TTS.

Uso:
    python -I scripts/voz_gemini.py episodio episodes/<id>/storyboard.json --voz Puck

Genera una pista WAV por escena en episodes/<id>/audio/ (escena_01.wav, escena_02.wav...),
además de gancho.wav / cta.wav si el storyboard los trae, y un manifest.json con duraciones.
Las pistas que ya existen no se regeneran (ahorra cuota) salvo con --forzar.

El storyboard puede ser un guion de la fábrica ({gancho, escenas:[{narracion}], cta}) o una lista
de escenas con el texto en narracion / texto / voz / locucion / narration / text / voiceover.
Necesita GEMINI_API_KEY en el entorno o en .env.
"""
from __future__ import annotations

import argparse
import json
import wave
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))   # con python -I no se añade el directorio actual

from fabrica import voz_gemini  # noqa: E402
from fabrica.config import cargar_config  # noqa: E402

CLAVES_TEXTO = ("narracion", "narración", "texto", "voz", "locucion", "locución", "narration",
                "text", "voiceover", "voice_over", "dialogo", "diálogo")


def _texto(escena: object) -> str:
    if isinstance(escena, str):
        return escena.strip()
    if isinstance(escena, dict):
        for k in CLAVES_TEXTO:
            v = escena.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, list) and all(isinstance(x, str) for x in v):
                return " ".join(x.strip() for x in v if x.strip())
    return ""


def pistas_de_storyboard(sb: object) -> list[tuple[str, str]]:
    """Devuelve [(nombre_archivo_sin_extension, texto)] en orden de reproducción."""
    if isinstance(sb, list):
        escenas, gancho, cta = sb, "", ""
    elif isinstance(sb, dict):
        escenas = sb.get("escenas") or sb.get("scenes") or sb.get("shots") or []
        gancho = sb.get("gancho") or sb.get("hook") or ""
        cta = sb.get("cta") or ""
    else:
        raise ValueError("storyboard no reconocido: se esperaba un objeto o una lista")
    pistas: list[tuple[str, str]] = []
    if isinstance(gancho, str) and gancho.strip():
        pistas.append(("gancho", gancho.strip()))
    for i, e in enumerate(escenas, 1):
        n = e.get("numero") or e.get("id") or i if isinstance(e, dict) else i
        n = n if isinstance(n, int) else i
        t = _texto(e)
        if t:
            pistas.append((f"escena_{n:02d}", t))
    if isinstance(cta, str) and cta.strip():
        pistas.append(("cta", cta.strip()))
    if not any(nombre.startswith("escena_") for nombre, _ in pistas):
        raise ValueError("el storyboard no tiene escenas con texto para narrar")
    return pistas


def cmd_episodio(a: argparse.Namespace) -> int:
    sb_ruta = Path(a.storyboard)
    sb = json.loads(sb_ruta.read_text(encoding="utf-8"))
    pistas = pistas_de_storyboard(sb)
    cfg = cargar_config()
    clave = cfg.secreto("GEMINI_API_KEY")
    if not clave:
        print("Falta GEMINI_API_KEY (en el entorno o en .env)", file=sys.stderr)
        return 2
    gcfg = (cfg["proveedores"].get("voz") or {}).get("gemini") or {}
    voz = a.voz or gcfg.get("voz", voz_gemini.VOZ_POR_DEFECTO)
    modelos = [a.modelo] if a.modelo else gcfg.get("modelos")
    estilo = a.estilo if a.estilo is not None else gcfg.get("estilo",
                                                              voz_gemini.ESTILO_POR_DEFECTO)
    salida = sb_ruta.parent / "audio"
    salida.mkdir(parents=True, exist_ok=True)
    manifest = {"voz": voz, "storyboard": sb_ruta.name, "pistas": []}
    for nombre, texto in pistas:
        ruta = salida / f"{nombre}.wav"
        if ruta.exists() and not a.forzar:
            print(f"= {ruta} (ya existe)")
        else:
            pcm, sr = voz_gemini.sintetizar(texto, clave, voz, modelos, estilo or None)
            if a.velocidad != 1.0:
                pcm = voz_gemini.cambiar_tempo(pcm, sr, a.velocidad)
            voz_gemini.guardar_wav(pcm, sr, ruta)
            print(f"+ {ruta} ({len(pcm) / sr:.1f}s)")
        with wave.open(str(ruta), "rb") as w:
            dur = w.getnframes() / w.getframerate()
        manifest["pistas"].append({"archivo": ruta.name, "texto": texto,
                                   "duracion_s": round(dur, 3)})
    manifest["duracion_total_s"] = round(sum(p["duracion_s"] for p in manifest["pistas"]), 3)
    (salida / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print(f"Listo: {len(manifest['pistas'])} pistas, {manifest['duracion_total_s']:.1f}s "
          f"en {salida}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Locución con Gemini TTS")
    sub = p.add_subparsers(dest="orden", required=True)
    e = sub.add_parser("episodio", help="una pista por escena de un storyboard")
    e.add_argument("storyboard", help="ruta a episodes/<id>/storyboard.json")
    e.add_argument("--voz", help="voz precompilada de Gemini (por defecto la de config.yaml: Puck)")
    e.add_argument("--modelo", help="modelo TTS (por defecto los de config.yaml)")
    e.add_argument("--estilo", help="instrucción de estilo; '' para leer el texto sin más")
    e.add_argument("--velocidad", type=float, default=1.0, help=">1 más rápido (atempo)")
    e.add_argument("--forzar", action="store_true", help="regenera pistas ya existentes")
    e.set_defaults(f=cmd_episodio)
    a = p.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
