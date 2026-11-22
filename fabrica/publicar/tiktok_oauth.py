"""Obtención única del refresh token de TikTok (Login Kit para web) y prueba de publicación.

Los mensajes van en castellano e inglés porque se usan en el vídeo de demostración que revisa TikTok.
"""
from __future__ import annotations

import secrets
import time
import urllib.parse
import webbrowser

import requests

from ..config import Config

# Solo los ámbitos configurados en la app (si se pide uno no configurado, TikTok rechaza el login)
SCOPES = "user.info.basic,video.publish,video.upload"


def flujo(cfg: Config) -> int:
    clave, secreto = cfg.secreto("TIKTOK_CLIENT_KEY"), cfg.secreto("TIKTOK_CLIENT_SECRET")
    redirect = cfg.secreto("TIKTOK_REDIRECT_URI")
    if not (clave and secreto and redirect):
        print("Rellena TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET y TIKTOK_REDIRECT_URI en .env")
        return 1
    estado = secrets.token_urlsafe(16)
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": clave, "scope": SCOPES, "response_type": "code",
        "redirect_uri": redirect, "state": estado})
    print("== Relatos 3am Publisher: conectar TikTok / connect TikTok (Login Kit) ==")
    print("Se abre TikTok para autorizar. / Opening TikTok to authorize the app...")
    webbrowser.open(url)
    vuelta = input("\nPega la URL de vuelta / Paste the redirect URL: ").strip()
    q = urllib.parse.parse_qs(urllib.parse.urlparse(vuelta).query)
    if q.get("state", [""])[0] != estado or "code" not in q:
        print("La URL no es válida (state/code). / Invalid redirect URL. Repite / Try again.")
        return 1
    r = requests.post("https://open.tiktokapis.com/v2/oauth/token/", timeout=60,
                      headers={"Content-Type": "application/x-www-form-urlencoded"},
                      data={"client_key": clave, "client_secret": secreto,
                            "code": q["code"][0], "grant_type": "authorization_code",
                            "redirect_uri": redirect})
    d = r.json()
    if "refresh_token" not in d:
        print("Error:", d.get("error"), d.get("error_description"))
        return 1
    from ..cli import guardar_en_env
    from ..tokens import AlmacenTokens
    guardar_en_env(cfg, "TIKTOK_REFRESH_TOKEN", d["refresh_token"])
    AlmacenTokens(cfg).set("tiktok", {"access_token": d["access_token"],
                                      "expira": time.time() + int(d.get("expires_in", 86400)),
                                      "refresh_token": d["refresh_token"]})
    info = requests.get("https://open.tiktokapis.com/v2/user/info/?fields=display_name,avatar_url",
                        headers={"Authorization": f"Bearer {d['access_token']}"}, timeout=30).json()
    nombre = ((info.get("data") or {}).get("user") or {}).get("display_name", "?")
    print(f"\nConectado como / Connected as: {nombre}  (user.info.basic)")
    print("Listo: token guardado de forma segura. / Done: token stored securely.")
    return 0
