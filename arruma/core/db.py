"""Base de dados local (SQLite): histórico de operações e cache da IA."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .settings import data_dir

_LOCK = threading.Lock()
_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created REAL NOT NULL,
    root TEXT NOT NULL,
    title TEXT NOT NULL,
    n_ok INTEGER DEFAULT 0,
    n_err INTEGER DEFAULT 0,
    undone INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    seq INTEGER NOT NULL,
    op TEXT NOT NULL,
    src TEXT NOT NULL,
    dst TEXT,
    status TEXT NOT NULL,
    error TEXT,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ops_session ON ops(session_id);
CREATE TABLE IF NOT EXISTS ai_cache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created REAL NOT NULL
);
"""


class Database:
    def __init__(self, path: Path | None = None):
        self.path = path or (data_dir() / "arruma.db")
        with self.connect() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def connect(self):
        with _LOCK:
            conn = sqlite3.connect(self.path, timeout=30)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    # ------------------------------------------------------------------ sessões
    def new_session(self, root: str, title: str) -> int:
        with self.connect() as c:
            cur = c.execute("INSERT INTO sessions(created, root, title) VALUES (?,?,?)",
                            (time.time(), root, title))
            return int(cur.lastrowid)

    def log_op(self, session_id: int, seq: int, op: str, src: str, dst: str | None,
               status: str = "ok", error: str | None = None) -> None:
        with self.connect() as c:
            c.execute("INSERT INTO ops(session_id, seq, op, src, dst, status, error, ts) "
                      "VALUES (?,?,?,?,?,?,?,?)",
                      (session_id, seq, op, src, dst, status, error, time.time()))

    def finish_session(self, session_id: int, n_ok: int, n_err: int) -> None:
        with self.connect() as c:
            c.execute("UPDATE sessions SET n_ok=?, n_err=? WHERE id=?", (n_ok, n_err, session_id))

    def mark_undone(self, session_id: int) -> None:
        with self.connect() as c:
            c.execute("UPDATE sessions SET undone=1 WHERE id=?", (session_id,))

    def sessions(self, limit: int = 100) -> list[sqlite3.Row]:
        with self.connect() as c:
            return list(c.execute("SELECT * FROM sessions WHERE n_ok > 0 ORDER BY id DESC LIMIT ?", (limit,)))

    def ops(self, session_id: int) -> list[sqlite3.Row]:
        with self.connect() as c:
            return list(c.execute("SELECT * FROM ops WHERE session_id=? ORDER BY seq", (session_id,)))

    # ------------------------------------------------------------------ cache IA
    def cache_get(self, key: str) -> dict | None:
        with self.connect() as c:
            row = c.execute("SELECT value FROM ai_cache WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def cache_put(self, key: str, value: dict) -> None:
        with self.connect() as c:
            c.execute("INSERT OR REPLACE INTO ai_cache(key, value, created) VALUES (?,?,?)",
                      (key, json.dumps(value, ensure_ascii=False), time.time()))
