"""Obtención única del refresh token de TikTok (Login Kit, flujo con PKCE en tu PC)."""
from __future__ import annotations

import hashlib
import secrets
import urllib.parse
import webbrowser

import requests

from ..config import Config

SCOPES = "user.info.basic,video.publish,video.upload,video.list"


def flujo(cfg: Config) -> int:
    clave, secreto = cfg.secreto("TIKTOK_CLIENT_KEY"), cfg.secreto("TIKTOK_CLIENT_SECRET")
    redirect = cfg.secreto("TIKTOK_REDIRECT_URI")
    if not (clave and secreto and redirect):
        print("Rellena TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET y TIKTOK_REDIRECT_URI en .env")
        return 1
    verificador = secrets.token_urlsafe(64)[:96]
    reto = hashlib.sha256(verificador.encode()).hexdigest()  # TikTok usa hex SHA256 en PKCE
    estado = secrets.token_urlsafe(16)
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": clave, "scope": SCOPES, "response_type": "code",
        "redirect_uri": redirect, "state": estado, "code_challenge": reto,
        "code_challenge_method": "S256"})
    print("Abre esta URL, autoriza y pega aquí la URL completa a la que te redirige:\n", url)
    webbrowser.open(url)
    vuelta = input("\nURL de vuelta: ").strip()
    q = urllib.parse.parse_qs(urllib.parse.urlparse(vuelta).query)
    if q.get("state", [""])[0] != estado:
        print("El parámetro state no coincide; repite el proceso.")
        return 1
    r = requests.post("https://open.tiktokapis.com/v2/oauth/token/", timeout=60, data={
        "client_key": clave, "client_secret": secreto, "code": q["code"][0],
        "grant_type": "authorization_code", "redirect_uri": redirect,
        "code_verifier": verificador})
    d = r.json()
    if "refresh_token" not in d:
        print("Error:", d)
        return 1
    from ..cli import guardar_en_env
    guardar_en_env(cfg, "TIKTOK_REFRESH_TOKEN", d["refresh_token"])
    print("\nListo: TIKTOK_REFRESH_TOKEN guardado en .env.")
    return 0
