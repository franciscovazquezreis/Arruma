# SPDX-License-Identifier: GPL-3.0-or-later
"""Base de dados local (SQLite): histórico de operações e cache da IA."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .system import data_dir

_LOCK = threading.Lock()
_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created REAL NOT NULL,
    root TEXT NOT NULL,
    title TEXT NOT NULL,
    n_ok INTEGER DEFAULT 0,
    n_err INTEGER DEFAULT 0,
    undone INTEGER DEFAULT 0,
    finished INTEGER DEFAULT 1
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
            self._migrate(c)

    @staticmethod
    def _migrate(c: sqlite3.Connection) -> None:
        """Atualiza o histórico de versões anteriores, que não sabiam se uma arrumação tinha chegado ao fim.
        Uma arrumação interrompida (o Arruma fechado a meio) ficava com 0 alterações e escondida do Histórico:
        passa a aparecer, com as contagens tiradas das operações registadas, e pode ser anulada."""
        def columns():
            return {row["name"] for row in c.execute("PRAGMA table_info(sessions)")}
        if "finished" in columns():
            return
        c.execute("BEGIN IMMEDIATE")  # outra janela do Arruma pode estar a abrir o mesmo histórico
        if "finished" in columns():
            return
        c.execute("ALTER TABLE sessions ADD COLUMN finished INTEGER DEFAULT 1")
        c.execute("UPDATE sessions SET finished = 0, "
                  "n_ok = (SELECT COUNT(*) FROM ops WHERE session_id = sessions.id AND status = 'ok' "
                  "AND op != 'mkdir'), "
                  "n_err = (SELECT COUNT(*) FROM ops WHERE session_id = sessions.id AND status = 'erro') "
                  "WHERE n_ok = 0 AND EXISTS (SELECT 1 FROM ops WHERE session_id = sessions.id AND status = 'ok' "
                  "AND op IN ('move', 'move_dir', 'trash'))")

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
        """A sessão fica por terminar («finished» a 0) até finish_session()."""
        with self.connect() as c:
            cur = c.execute("INSERT INTO sessions(created, root, title, finished) VALUES (?,?,?,0)",
                            (time.time(), root, title))
            return int(cur.lastrowid)

    def log_op(self, session_id: int, seq: int, op: str, src: str, dst: str | None,
               status: str = "ok", error: str | None = None, counts: tuple[int, int] | None = None) -> int:
        """«counts» (alterações feitas, erros) até aqui: ficam gravadas com a operação, para que uma arrumação
        interrompida a meio apareça logo no Histórico com o que chegou a fazer. Devolve o número da operação."""
        with self.connect() as c:
            cur = c.execute("INSERT INTO ops(session_id, seq, op, src, dst, status, error, ts) "
                            "VALUES (?,?,?,?,?,?,?,?)",
                            (session_id, seq, op, src, dst, status, error, time.time()))
            if counts is not None:
                c.execute("UPDATE sessions SET n_ok=?, n_err=? WHERE id=?", (*counts, session_id))
            if status == "ok" and op != "mkdir":
                # Outra janela do Arruma pode ter anulado esta sessão enquanto esta ainda a aplicava: o que
                # chega depois fica por anular («Anular o resto»).
                c.execute("UPDATE sessions SET undone=2 WHERE id=? AND undone=1", (session_id,))
            return int(cur.lastrowid)

    def drop_op(self, op_id: int) -> None:
        """Apaga uma operação registada antes de ser feita que acabou por falhar (o erro é registado à parte)."""
        with self.connect() as c:
            c.execute("DELETE FROM ops WHERE id=?", (op_id,))

    def set_op_dst(self, op_id: int, dst: str | None) -> None:
        with self.connect() as c:
            c.execute("UPDATE ops SET dst=? WHERE id=?", (dst, op_id))

    def finish_session(self, session_id: int, n_ok: int, n_err: int) -> None:
        with self.connect() as c:
            c.execute("UPDATE sessions SET n_ok=?, n_err=?, finished=1 WHERE id=?", (n_ok, n_err, session_id))

    def mark_op_undone(self, op_id: int) -> None:
        """Operação já anulada: se se voltar a anular a sessão, só se tenta o que falta."""
        with self.connect() as c:
            c.execute("UPDATE ops SET status='anulada' WHERE id=?", (op_id,))

    def mark_undone(self, session_id: int) -> None:
        """«undone»: 1 quando já não falta anular nada; 2 (anulada em parte) quando alguma operação falhou ou
        se parou a meio e ficou alguma coisa por anular; 0 quando nada chegou a ser anulado."""
        with self.connect() as c:
            left = c.execute("SELECT COUNT(*) FROM ops WHERE session_id=? AND status='ok' AND op != 'mkdir'",
                             (session_id,)).fetchone()[0]
            some = c.execute("SELECT COUNT(*) FROM ops WHERE session_id=? AND status='anulada'",
                             (session_id,)).fetchone()[0]
            c.execute("UPDATE sessions SET undone=? WHERE id=?", (1 if not left else 2 if some else 0, session_id))

    # «n_left»: o que ainda falta anular. As pastas criadas pelo Arruma não contam: saem quando ficam vazias.
    _SESSION = ("SELECT s.*, (SELECT COUNT(*) FROM ops o WHERE o.session_id = s.id AND o.status = 'ok' "
                "AND o.op != 'mkdir') AS n_left FROM sessions s")

    def sessions(self, limit: int = 100) -> list[sqlite3.Row]:
        """As sessões que mudaram alguma coisa, da mais recente para a mais antiga. Uma que não chegou ao fim
        aparece se tiver feito alguma operação, mesmo antes de a contar."""
        with self.connect() as c:
            return list(c.execute(self._SESSION + " WHERE s.n_ok > 0 OR (NOT s.finished AND EXISTS (SELECT 1 "
                                  "FROM ops o WHERE o.session_id = s.id AND o.status IN ('ok', 'anulada'))) "
                                  "ORDER BY s.id DESC LIMIT ?", (limit,)))

    def session(self, session_id: int) -> sqlite3.Row | None:
        with self.connect() as c:
            return c.execute(self._SESSION + " WHERE s.id = ?", (session_id,)).fetchone()

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
