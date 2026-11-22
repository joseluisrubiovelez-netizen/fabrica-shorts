"""Almacén cifrado de tokens que rotan (TikTok, Instagram) para poder guardarlos en un repo público.

Clave: FABRICA_CLAVE_TOKENS (Fernet, generada con `python -m fabrica clave`). Sin clave no se
persiste nada: se usan solo las variables de entorno y se avisa.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Config
from .utils import log

L = log("tokens")


class AlmacenTokens:
    def __init__(self, cfg: Config):
        self.ruta: Path = cfg.dir_datos / "tokens.enc"
        clave = cfg.secreto("FABRICA_CLAVE_TOKENS")
        self.fernet = None
        if clave:
            from cryptography.fernet import Fernet
            self.fernet = Fernet(clave.encode())
        self._datos: dict[str, Any] | None = None

    def _cargar(self) -> dict[str, Any]:
        if self._datos is None:
            self._datos = {}
            if self.fernet and self.ruta.exists():
                try:
                    self._datos = json.loads(self.fernet.decrypt(self.ruta.read_bytes()))
                except Exception as e:  # clave cambiada o archivo dañado
                    L.error("No se pudo descifrar tokens.enc: %s", e)
        return self._datos

    def get(self, plataforma: str) -> dict[str, Any]:
        return dict(self._cargar().get(plataforma, {}))

    def set(self, plataforma: str, valores: dict[str, Any]) -> None:
        datos = self._cargar()
        datos[plataforma] = {**datos.get(plataforma, {}), **valores}
        if not self.fernet:
            L.warning("Sin FABRICA_CLAVE_TOKENS: el token renovado de %s no se guardará", plataforma)
            return
        self.ruta.write_bytes(self.fernet.encrypt(json.dumps(datos).encode()))


def generar_clave() -> str:
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()
