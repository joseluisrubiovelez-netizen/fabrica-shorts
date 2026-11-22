"""Almacén de vídeos en cola entre ejecuciones de GitHub Actions (assets de una Release).

En local no hace nada: los vídeos ya están en data/videos.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .config import Config
from .utils import log

L = log("almacen")
ETIQUETA = "cola-videos"


class Almacen:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.activo = os.environ.get("GITHUB_ACTIONS") == "true" and bool(shutil.which("gh"))

    def _nombre(self, video_id: int) -> str:
        return f"video-{video_id:05d}.mp4"

    def _gh(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["gh", "release", *args], capture_output=True, text=True)

    def _asegurar_release(self) -> None:
        if self._gh("view", ETIQUETA).returncode != 0:
            self._gh("create", ETIQUETA, "--title", "Cola de vídeos (automático)", "--notes",
                     "Vídeos generados pendientes de publicar. Se borran al publicarse.",
                     "--prerelease")

    def guardar(self, video_id: int, ruta: Path) -> None:
        if not self.activo:
            return
        self._asegurar_release()
        destino = ruta.with_name(self._nombre(video_id))
        shutil.copy2(ruta, destino)
        r = self._gh("upload", ETIQUETA, str(destino), "--clobber")
        if r.returncode != 0:
            L.error("No se pudo subir el vídeo %d a la release: %s", video_id, r.stderr)

    def descargar(self, video_id: int) -> Path | None:
        if not self.activo:
            return None
        carpeta = self.cfg.dir_datos / "videos" / f"{video_id:05d}"
        carpeta.mkdir(parents=True, exist_ok=True)
        r = self._gh("download", ETIQUETA, "--pattern", self._nombre(video_id), "--dir",
                     str(carpeta), "--clobber")
        ruta = carpeta / self._nombre(video_id)
        return ruta if r.returncode == 0 and ruta.exists() else None

    def borrar(self, video_id: int) -> None:
        if self.activo:
            self._gh("delete-asset", ETIQUETA, self._nombre(video_id), "--yes")
