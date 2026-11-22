"""Carga de config.yaml y variables de entorno (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

RAIZ = Path(__file__).resolve().parent.parent
MODOS = ("dry-run", "review", "auto")


@dataclass
class Config:
    datos: dict[str, Any]
    raiz: Path = RAIZ
    env: dict[str, str] = field(default_factory=dict)

    # Acceso cómodo: cfg["cadencia"]["horas"]
    def __getitem__(self, k: str) -> Any:
        return self.datos[k]

    def get(self, k: str, defecto: Any = None) -> Any:
        return self.datos.get(k, defecto)

    @property
    def modo(self) -> str:
        return self.datos["modo"]

    @property
    def dir_datos(self) -> Path:
        d = Path(self.env.get("FABRICA_DATOS") or (self.raiz / "data"))
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def ruta_db(self) -> Path:
        return self.dir_datos / "fabrica.db"

    def secreto(self, nombre: str) -> str | None:
        v = self.env.get(nombre)
        return v.strip() if v and v.strip() else None

    def serie(self, serie_id: str) -> dict[str, Any]:
        for s in self.datos["series"]:
            if s["id"] == serie_id:
                return s
        raise KeyError(f"Serie desconocida: {serie_id}")


def cargar_config(ruta: str | Path | None = None, modo: str | None = None,
                  cargar_env: bool = True) -> Config:
    ruta = Path(ruta) if ruta else RAIZ / "config.yaml"
    with open(ruta, encoding="utf-8") as f:
        datos = yaml.safe_load(f)
    if cargar_env:
        try:
            from dotenv import load_dotenv
            load_dotenv(RAIZ / ".env", override=False)
        except ImportError:
            pass
    env = dict(os.environ)
    modo = modo or env.get("FABRICA_MODO") or datos.get("modo", "review")
    if modo not in MODOS:
        raise ValueError(f"Modo '{modo}' no válido. Usa uno de {MODOS}")
    datos["modo"] = modo
    validar(datos)
    return Config(datos=datos, env=env)


def validar(d: dict[str, Any]) -> None:
    errores = []
    if not d.get("series"):
        errores.append("Debe haber al menos una serie")
    pesos = sum(float(s.get("peso", 0)) for s in d.get("series", []))
    if d.get("series") and abs(pesos - 1.0) > 0.05:
        errores.append(f"Los pesos de las series suman {pesos:.2f}, deben sumar 1")
    cad = d.get("cadencia", {})
    if len(cad.get("horas", [])) < cad.get("videos_por_dia", 0):
        errores.append("Hay menos horas que videos_por_dia")
    v = d.get("video", {})
    if v.get("duracion_min", 0) >= v.get("duracion_max", 1):
        errores.append("duracion_min debe ser menor que duracion_max")
    if errores:
        raise ValueError("config.yaml inválido: " + "; ".join(errores))
