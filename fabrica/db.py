"""SQLite: cola de vídeos, historial de ideas, licencias, publicaciones, métricas y eventos."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY,
    serie TEXT NOT NULL,
    tema TEXT NOT NULL,
    tema_norm TEXT NOT NULL,
    creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS guiones (
    id INTEGER PRIMARY KEY,
    serie TEXT NOT NULL,
    idea_id INTEGER REFERENCES ideas(id),
    proveedor TEXT NOT NULL,
    json TEXT NOT NULL,
    usado INTEGER NOT NULL DEFAULT 0,
    creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY,
    guion_id INTEGER REFERENCES guiones(id),
    serie TEXT NOT NULL,
    titulo TEXT NOT NULL,
    estado TEXT NOT NULL,
    ruta TEXT,
    duracion REAL,
    intentos INTEGER NOT NULL DEFAULT 0,
    qa_json TEXT,
    meta_json TEXT,
    programado_para TEXT,
    creado TEXT NOT NULL,
    actualizado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY,
    video_id INTEGER REFERENCES videos(id),
    tipo TEXT NOT NULL,
    proveedor TEXT NOT NULL,
    fuente TEXT,
    licencia TEXT,
    atribucion TEXT,
    ruta TEXT,
    prompt TEXT,
    creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS publicaciones (
    id INTEGER PRIMARY KEY,
    video_id INTEGER NOT NULL REFERENCES videos(id),
    plataforma TEXT NOT NULL,
    estado TEXT NOT NULL,
    id_externo TEXT,
    url TEXT,
    intentos INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    actualizado TEXT NOT NULL,
    UNIQUE(video_id, plataforma)
);
CREATE TABLE IF NOT EXISTS metricas (
    id INTEGER PRIMARY KEY,
    publicacion_id INTEGER NOT NULL REFERENCES publicaciones(id),
    fecha TEXT NOT NULL,
    vistas INTEGER,
    likes INTEGER,
    comentarios INTEGER,
    compartidos INTEGER,
    retencion_pct REAL,
    duracion_media_s REAL,
    datos_json TEXT,
    UNIQUE(publicacion_id, fecha)
);
CREATE TABLE IF NOT EXISTS huecos (
    slot TEXT PRIMARY KEY,
    video_id INTEGER REFERENCES videos(id),
    estado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY,
    nivel TEXT NOT NULL,
    componente TEXT NOT NULL,
    mensaje TEXT NOT NULL,
    creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
    clave TEXT PRIMARY KEY,
    valor TEXT
);
"""

# Estados de un vídeo
GENERANDO = "generando"
PENDIENTE = "pendiente_aprobacion"   # modo review
APROBADO = "aprobado"                 # listo para su hueco
PUBLICADO = "publicado"
DESCARTADO = "descartado"
DRY = "dry_run"


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, ruta: str | Path):
        self.ruta = str(ruta)
        self.con = sqlite3.connect(self.ruta)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")
        self.con.executescript(ESQUEMA)
        self.con.commit()

    def cerrar(self) -> None:
        self.con.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.con
            self.con.commit()
        except Exception:
            self.con.rollback()
            raise

    # ---------- ideas / guiones ----------
    def temas_previos(self, serie: str | None = None) -> list[str]:
        q = "SELECT tema_norm FROM ideas" + (" WHERE serie=?" if serie else "")
        return [r[0] for r in self.con.execute(q, (serie,) if serie else ())]

    def guardar_guion(self, serie: str, tema: str, tema_norm: str, proveedor: str,
                      guion: dict[str, Any]) -> int:
        with self.tx() as c:
            idea_id = c.execute(
                "INSERT INTO ideas(serie, tema, tema_norm, creado) VALUES (?,?,?,?)",
                (serie, tema, tema_norm, ahora_iso())).lastrowid
            return c.execute(
                "INSERT INTO guiones(serie, idea_id, proveedor, json, creado) VALUES (?,?,?,?,?)",
                (serie, idea_id, proveedor, json.dumps(guion, ensure_ascii=False), ahora_iso())
            ).lastrowid

    def guiones_disponibles(self, serie: str | None = None) -> list[sqlite3.Row]:
        q = "SELECT * FROM guiones WHERE usado=0" + (" AND serie=?" if serie else "") + " ORDER BY id"
        return list(self.con.execute(q, (serie,) if serie else ()))

    def marcar_guion_usado(self, guion_id: int, usado: int = 1) -> None:
        with self.tx() as c:
            c.execute("UPDATE guiones SET usado=? WHERE id=?", (usado, guion_id))

    def ganchos_recientes(self, n: int = 30) -> list[str]:
        filas = self.con.execute("SELECT json FROM guiones ORDER BY id DESC LIMIT ?", (n,))
        return [json.loads(r[0]).get("gancho", "") for r in filas]

    # ---------- vídeos ----------
    def crear_video(self, guion_id: int, serie: str, titulo: str) -> int:
        t = ahora_iso()
        with self.tx() as c:
            return c.execute(
                "INSERT INTO videos(guion_id, serie, titulo, estado, creado, actualizado) "
                "VALUES (?,?,?,?,?,?)", (guion_id, serie, titulo, GENERANDO, t, t)).lastrowid

    def actualizar_video(self, video_id: int, **campos: Any) -> None:
        if not campos:
            return
        campos["actualizado"] = ahora_iso()
        for k in ("qa_json", "meta_json"):
            if k in campos and not isinstance(campos[k], str):
                campos[k] = json.dumps(campos[k], ensure_ascii=False)
        sets = ", ".join(f"{k}=?" for k in campos)
        with self.tx() as c:
            c.execute(f"UPDATE videos SET {sets} WHERE id=?", (*campos.values(), video_id))

    def video(self, video_id: int) -> sqlite3.Row | None:
        return self.con.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()

    def videos_en_estado(self, *estados: str) -> list[sqlite3.Row]:
        marcas = ",".join("?" * len(estados))
        return list(self.con.execute(
            f"SELECT * FROM videos WHERE estado IN ({marcas}) ORDER BY id", estados))

    # ---------- licencias ----------
    def registrar_asset(self, video_id: int, tipo: str, proveedor: str, fuente: str | None,
                        licencia: str | None, ruta: str | None = None, prompt: str | None = None,
                        atribucion: str | None = None) -> int:
        with self.tx() as c:
            return c.execute(
                "INSERT INTO assets(video_id, tipo, proveedor, fuente, licencia, atribucion, ruta, "
                "prompt, creado) VALUES (?,?,?,?,?,?,?,?,?)",
                (video_id, tipo, proveedor, fuente, licencia, atribucion, ruta, prompt, ahora_iso())
            ).lastrowid

    def assets_de(self, video_id: int) -> list[sqlite3.Row]:
        return list(self.con.execute("SELECT * FROM assets WHERE video_id=?", (video_id,)))

    def borrar_assets(self, video_id: int) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM assets WHERE video_id=?", (video_id,))

    # ---------- huecos de publicación ----------
    def hueco(self, slot: str) -> sqlite3.Row | None:
        return self.con.execute("SELECT * FROM huecos WHERE slot=?", (slot,)).fetchone()

    def fijar_hueco(self, slot: str, video_id: int | None, estado: str) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO huecos(slot, video_id, estado) VALUES (?,?,?) "
                      "ON CONFLICT(slot) DO UPDATE SET video_id=excluded.video_id, "
                      "estado=excluded.estado", (slot, video_id, estado))

    # ---------- publicaciones ----------
    def publicacion(self, video_id: int, plataforma: str) -> sqlite3.Row | None:
        return self.con.execute("SELECT * FROM publicaciones WHERE video_id=? AND plataforma=?",
                                (video_id, plataforma)).fetchone()

    def fijar_publicacion(self, video_id: int, plataforma: str, estado: str,
                          id_externo: str | None = None, url: str | None = None,
                          error: str | None = None, sumar_intento: bool = False) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO publicaciones(video_id, plataforma, estado, id_externo, url, intentos, "
                "error, actualizado) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(video_id, plataforma) DO UPDATE SET estado=excluded.estado, "
                "id_externo=COALESCE(excluded.id_externo, id_externo), "
                "url=COALESCE(excluded.url, url), intentos=intentos+?, error=excluded.error, "
                "actualizado=excluded.actualizado",
                (video_id, plataforma, estado, id_externo, url, 1 if sumar_intento else 0, error,
                 ahora_iso(), 1 if sumar_intento else 0))

    def publicaciones(self, estado: str | None = None) -> list[sqlite3.Row]:
        if estado:
            return list(self.con.execute("SELECT * FROM publicaciones WHERE estado=?", (estado,)))
        return list(self.con.execute("SELECT * FROM publicaciones"))

    # ---------- métricas ----------
    def guardar_metrica(self, publicacion_id: int, fecha: str, **m: Any) -> None:
        datos = json.dumps(m.pop("datos", {}), ensure_ascii=False)
        with self.tx() as c:
            c.execute(
                "INSERT INTO metricas(publicacion_id, fecha, vistas, likes, comentarios, compartidos, "
                "retencion_pct, duracion_media_s, datos_json) VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(publicacion_id, fecha) DO UPDATE SET vistas=excluded.vistas, "
                "likes=excluded.likes, comentarios=excluded.comentarios, "
                "compartidos=excluded.compartidos, retencion_pct=excluded.retencion_pct, "
                "duracion_media_s=excluded.duracion_media_s, datos_json=excluded.datos_json",
                (publicacion_id, fecha, m.get("vistas"), m.get("likes"), m.get("comentarios"),
                 m.get("compartidos"), m.get("retencion_pct"), m.get("duracion_media_s"), datos))

    # ---------- eventos / kv ----------
    def evento(self, nivel: str, componente: str, mensaje: str) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO eventos(nivel, componente, mensaje, creado) VALUES (?,?,?,?)",
                      (nivel, componente, mensaje[:2000], ahora_iso()))

    def kv_get(self, clave: str, defecto: str | None = None) -> str | None:
        r = self.con.execute("SELECT valor FROM kv WHERE clave=?", (clave,)).fetchone()
        return r[0] if r else defecto

    def kv_set(self, clave: str, valor: str) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO kv(clave, valor) VALUES (?,?) "
                      "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor", (clave, valor))
