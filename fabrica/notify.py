"""Avisos y aprobaciones por Telegram (Bot API oficial, gratuita). Sin Telegram: solo log."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import requests

from .config import Config
from .db import DB
from .utils import log

L = log("avisos")
API = "https://api.telegram.org/bot{token}/{metodo}"
LIMITE_VIDEO = 49 * 1024 * 1024
COMANDO = re.compile(r"^/(aprobar|descartar|estado)(?:@\w+)?(?:\s+(\d+))?", re.I)


class Notificador:
    def __init__(self, cfg: Config, db: DB):
        self.db = db
        self.token = cfg.secreto("TELEGRAM_BOT_TOKEN")
        self.chat = cfg.secreto("TELEGRAM_CHAT_ID")
        self.activo = bool(cfg["notificaciones"].get("telegram") and self.token and self.chat)
        if not self.activo:
            L.info("Telegram no configurado: los avisos solo irán al log")

    def _llamar(self, metodo: str, **kw: Any) -> dict[str, Any] | None:
        if not self.activo:
            return None
        try:
            r = requests.post(API.format(token=self.token, metodo=metodo), timeout=120, **kw)
            datos = r.json()
            if not datos.get("ok"):
                L.warning("Telegram %s: %s", metodo, datos.get("description"))
            return datos
        except requests.RequestException as e:
            L.warning("Telegram %s falló: %s", metodo, e)
            return None

    def enviar(self, texto: str) -> None:
        L.info("AVISO: %s", texto)
        self._llamar("sendMessage", data={"chat_id": self.chat, "text": texto[:4000]})

    def enviar_video(self, ruta: Path, texto: str) -> bool:
        if not self.activo:
            L.info("AVISO (vídeo %s): %s", ruta, texto)
            return False
        if ruta.stat().st_size > LIMITE_VIDEO:
            self.enviar(texto + f"\n(El vídeo supera 50 MB; descárgalo de {ruta})")
            return False
        with open(ruta, "rb") as f:
            r = self._llamar("sendVideo", data={"chat_id": self.chat, "caption": texto[:1000],
                                                "supports_streaming": "true"},
                             files={"video": (ruta.name, f, "video/mp4")})
        return bool(r and r.get("ok"))

    def pedir_aprobacion(self, video_id: int, ruta: Path, meta: dict[str, Any]) -> None:
        extra = ""
        if "Fuentes:" in meta.get("descripcion", ""):
            extra = "\n" + meta["descripcion"][meta["descripcion"].index("Fuentes:"):][:400]
            extra += "\n⚠️ Histórico: comprueba los hechos con la fuente antes de aprobar."
        texto = (f"🎬 Vídeo #{video_id} listo para revisar\n{meta.get('serie', '')}: "
                 f"{meta['titulo']}{extra}\n\nResponde /aprobar {video_id} o /descartar {video_id}")
        self.enviar_video(ruta, texto)

    def aviso_subida_manual(self, plataforma: str, video_id: int, ruta: Path,
                            texto: str) -> None:
        guia = {"tiktok": "Sube a TikTok, pega el texto y activa «Contenido generado por IA».",
                "instagram": "Sube como Reel, pega el texto y activa la etiqueta «IA».",
                "youtube": "Sube como Short y marca «Contenido alterado o sintético: Sí»."}
        self.enviar_video(ruta, f"📲 Publica a mano en {plataforma} el vídeo #{video_id}.\n"
                                f"{guia.get(plataforma, '')}\n\nTexto:\n{texto}")

    def leer_comandos(self) -> list[tuple[str, int | None]]:
        """Lee /aprobar N y /descartar N enviados SOLO desde el chat configurado."""
        if not self.activo:
            return []
        offset = int(self.db.kv_get("telegram_offset", "0") or 0)
        datos = self._llamar("getUpdates", data={"offset": offset + 1, "timeout": 0})
        if not datos or not datos.get("ok"):
            return []
        cmds: list[tuple[str, int | None]] = []
        for u in datos.get("result", []):
            offset = max(offset, u["update_id"])
            msg = u.get("message") or {}
            if str((msg.get("chat") or {}).get("id")) != str(self.chat):
                continue
            m = COMANDO.match((msg.get("text") or "").strip())
            if m:
                cmds.append((m.group(1).lower(), int(m.group(2)) if m.group(2) else None))
        self.db.kv_set("telegram_offset", str(offset))
        return cmds
