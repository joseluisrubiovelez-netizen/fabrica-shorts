"""QA automático: técnico, audio, silencios, subtítulos, gancho, licencias e imagen."""
from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageStat

from .subtitulos import Cue
from .utils import ffmpeg_bin, ffprobe, log

L = log("qa")


@dataclass
class ResultadoQA:
    fallos: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    metricas: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.fallos

    def como_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "fallos": self.fallos, "avisos": self.avisos,
                "metricas": self.metricas}


# ----------------------------------------------------------------------------- funciones puras
def evaluar_tecnico(probe: dict[str, Any], cfg_video: dict[str, Any], r: ResultadoQA) -> None:
    vs = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"]
    aus = [s for s in probe.get("streams", []) if s.get("codec_type") == "audio"]
    if not vs:
        r.fallos.append("sin pista de vídeo")
        return
    v = vs[0]
    dur = float(probe.get("format", {}).get("duration", 0))
    r.metricas.update(duracion=round(dur, 2), ancho=v.get("width"), alto=v.get("height"))
    if (v.get("width"), v.get("height")) != (cfg_video["ancho"], cfg_video["alto"]):
        r.fallos.append(f"resolución {v.get('width')}x{v.get('height')} != "
                        f"{cfg_video['ancho']}x{cfg_video['alto']}")
    if v.get("codec_name") != "h264":
        r.fallos.append(f"códec de vídeo {v.get('codec_name')} (se exige h264)")
    if v.get("pix_fmt") != "yuv420p":
        r.fallos.append(f"pix_fmt {v.get('pix_fmt')} (se exige yuv420p)")
    num, _, den = str(v.get("r_frame_rate", "0/1")).partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0
    if abs(fps - cfg_video["fps"]) > 0.5:
        r.fallos.append(f"fps {fps:.2f} != {cfg_video['fps']}")
    if not aus:
        r.fallos.append("sin pista de audio")
    elif aus[0].get("codec_name") != "aac":
        r.fallos.append(f"códec de audio {aus[0].get('codec_name')} (se exige aac)")
    if not cfg_video["duracion_min"] <= dur <= cfg_video["duracion_max"]:
        r.fallos.append(f"duración {dur:.1f}s fuera de {cfg_video['duracion_min']}-"
                        f"{cfg_video['duracion_max']}s")


def evaluar_loudness(lufs: float | None, rango: Iterable[float], r: ResultadoQA) -> None:
    lo, hi = rango
    r.metricas["lufs"] = lufs
    if lufs is None:
        r.fallos.append("no se pudo medir la sonoridad")
    elif not lo <= lufs <= hi:
        r.fallos.append(f"sonoridad {lufs:.1f} LUFS fuera de [{lo}, {hi}]")


def evaluar_silencios(silencios: list[tuple[float, float]], duracion: float, max_s: float,
                      r: ResultadoQA) -> None:
    r.metricas["silencios"] = [(round(a, 2), round(b, 2)) for a, b in silencios]
    for ini, fin in silencios:
        if ini < 0.05 and fin > 0.7:
            r.fallos.append(f"el audio tarda {fin:.2f}s en empezar (gancho tardío)")
        elif fin < duracion - 0.9 and fin - ini > max_s:
            r.fallos.append(f"silencio de {fin - ini:.1f}s en {ini:.1f}s")


def evaluar_subtitulos(cues: list[Cue], duracion: float, max_pps: float, r: ResultadoQA,
                       max_chars: int = 26) -> None:
    if not cues:
        r.fallos.append("no hay subtítulos")
        return
    palabras = sum(len(c.palabras) for c in cues)
    habla = max(0.1, cues[-1].fin - cues[0].ini)
    pps = palabras / habla
    r.metricas.update(subtitulos=len(cues), palabras_por_segundo=round(pps, 2))
    if pps > max_pps:
        r.fallos.append(f"{pps:.1f} palabras/s: subtítulos demasiado rápidos para leer")
    if cues[0].ini > 1.0:
        r.fallos.append(f"el primer subtítulo aparece en {cues[0].ini:.2f}s (>1 s)")
    cortos = [c for c in cues if c.fin - c.ini < 0.3]
    if len(cortos) > max(1, len(cues) // 8):
        r.fallos.append(f"{len(cortos)} subtítulos duran menos de 0,3 s")
    largos = [c.texto for c in cues if len(c.texto) > max_chars]
    if largos:
        r.fallos.append(f"subtítulos demasiado largos: {largos[:2]}")
    if cues[-1].fin > duracion + 0.2:
        r.fallos.append("hay subtítulos después del final del vídeo")


def evaluar_gancho(fin_gancho: float, r: ResultadoQA, limite: float = 3.2) -> None:
    r.metricas["fin_gancho_s"] = round(fin_gancho, 2)
    if fin_gancho > limite:
        r.fallos.append(f"el gancho termina en {fin_gancho:.1f}s (máx. {limite - 0.2:.0f} s)")


def evaluar_licencias(assets: list[dict[str, Any]], r: ResultadoQA) -> None:
    tipos = {a["tipo"] for a in assets}
    for t in ("voz", "visual", "musica"):
        if t not in tipos:
            r.fallos.append(f"no hay ningún recurso '{t}' registrado")
    sin = [f"{a['tipo']}#{a.get('id')}" for a in assets
           if not (a.get("licencia") and a.get("fuente"))]
    if sin:
        r.fallos.append(f"recursos sin fuente/licencia registrada: {sin}")
    r.metricas["recursos"] = len(assets)


def evaluar_brillo(medias: list[float], r: ResultadoQA, minimo: float = 10.0) -> None:
    r.metricas["brillo_muestras"] = [round(m, 1) for m in medias]
    if medias and min(medias) < minimo:
        r.fallos.append(f"fotograma casi negro (brillo {min(medias):.1f})")


# ----------------------------------------------------------------------------- mediciones
def medir_lufs(ruta: Path) -> float | None:
    p = subprocess.run([ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(ruta), "-af",
                        "ebur128=framelog=quiet", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", p.stderr)
    return float(m[-1]) if m else None


def medir_silencios(ruta: Path, minimo: float = 0.6, umbral_db: int = -40
                    ) -> list[tuple[float, float]]:
    p = subprocess.run([ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(ruta), "-af",
                        f"silencedetect=noise={umbral_db}dB:d={minimo}", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    inicios = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", p.stderr)]
    fines = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", p.stderr)]
    return list(zip(inicios, fines + [float("inf")] * (len(inicios) - len(fines))))


def medir_brillo(ruta: Path, tiempos: list[float]) -> list[float]:
    medias = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, t in enumerate(tiempos):
            png = Path(tmp) / f"f{i}.png"
            subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(ruta),
                            "-frames:v", "1", str(png)], capture_output=True)
            if png.exists():
                medias.append(ImageStat.Stat(Image.open(png).convert("L")).mean[0])
    return medias


def revisar(ruta: Path, *, cfg: dict[str, Any], voz: Path, cues: list[Cue], fin_gancho: float,
            assets: list[dict[str, Any]]) -> ResultadoQA:
    r = ResultadoQA()
    if not ruta.exists():
        r.fallos.append("el archivo de vídeo no existe")
        return r
    probe = ffprobe(ruta)
    evaluar_tecnico(probe, cfg["video"], r)
    dur = float(probe["format"]["duration"])
    evaluar_loudness(medir_lufs(ruta), cfg["qa"]["lufs_rango"], r)
    # Los silencios se miden sobre la voz (la música los taparía)
    evaluar_silencios(medir_silencios(voz), dur, cfg["qa"]["silencio_max_s"], r)
    evaluar_subtitulos(cues, dur, cfg["qa"]["palabras_por_segundo_max"], r)
    evaluar_gancho(fin_gancho, r)
    evaluar_licencias(assets, r)
    evaluar_brillo(medir_brillo(ruta, [0.5, dur * 0.5, dur * 0.85]), r)
    nivel = "OK" if r.ok else "FALLO"
    L.info("QA %s %s: %s", nivel, ruta.name, r.fallos or r.metricas)
    return r
