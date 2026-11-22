import base64
import importlib.util
import json
from pathlib import Path

import numpy as np

from fabrica import voz, voz_gemini

RAIZ = Path(__file__).resolve().parent.parent


class _Resp:
    status_code = 200

    def __init__(self, n=24000):
        pcm = (np.sin(np.arange(n) / 10) * 8000).astype("<i2").tobytes()
        self._d = {"candidates": [{"content": {"parts": [{"inlineData": {
            "mimeType": "audio/L16;codec=pcm;rate=24000", "data": base64.b64encode(pcm).decode()}}]}}]}

    def json(self):
        return self._d


def test_sintetizar_envia_voz_puck(monkeypatch):
    enviado = {}

    def post(url, json, headers, timeout):
        enviado.update(url=url, cuerpo=json)
        return _Resp()
    monkeypatch.setattr(voz_gemini.requests, "post", post)
    pcm, sr = voz_gemini.sintetizar("Hola", "k", "Puck", ["m-tts"], None)
    assert sr == 24000 and len(pcm) == 24000
    vc = enviado["cuerpo"]["generationConfig"]["speechConfig"]["voiceConfig"]
    assert vc["prebuiltVoiceConfig"]["voiceName"] == "Puck"
    assert "m-tts" in enviado["url"]


def test_locucion_gemini(monkeypatch, tmp_path):
    monkeypatch.setattr(voz_gemini.requests, "post", lambda *a, **k: _Resp(24000 * 5))
    loc = voz.generar_locucion(["g", "e1", "e2", "cta"], "", tmp_path / "v.wav", 10, 45,
                               gemini={"clave": "k", "voz": "Puck"})
    assert loc.sr == 24000 and len(loc.tramos_escena) == 2 and loc.ruta.exists()


def test_script_episodio(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("vg", RAIZ / "scripts" / "voz_gemini.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(voz_gemini.requests, "post", lambda *a, **k: _Resp())
    ep = tmp_path / "episodes" / "ep1"
    ep.mkdir(parents=True)
    sb = ep / "storyboard.json"
    sb.write_text(json.dumps({"gancho": "G", "escenas": [{"narracion": "uno"}, {"texto": "dos"}],
                              "cta": "C"}), encoding="utf-8")
    assert mod.main(["episodio", str(sb), "--voz", "Puck"]) == 0
    nombres = sorted(p.name for p in (ep / "audio").iterdir())
    assert nombres == ["cta.wav", "escena_01.wav", "escena_02.wav", "gancho.wav", "manifest.json"]
    assert json.loads((ep / "audio" / "manifest.json").read_text())["voz"] == "Puck"
