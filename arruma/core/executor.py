"""Aplicação do plano com registo de cada operação, e anulação."""

from __future__ import annotations

import errno
import os
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .db import Database
from .fsutil import is_within, unique_path


@dataclass
class Result:
    session_id: int
    ok: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    bytes_moved: int = 0


def safe_move(src: str, dst: str) -> None:
    """Move sem nunca substituir um ficheiro existente."""
    if os.path.lexists(dst):
        raise FileExistsError(errno.EEXIST, "Já existe", dst)
    try:
        os.rename(src, dst)
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
        # Discos diferentes: copiar, verificar e só depois remover o original.
        if os.path.isdir(src) and not os.path.islink(src):
            shutil.copytree(src, dst, symlinks=True)
            shutil.rmtree(src)
        else:
            shutil.copy2(src, dst, follow_symlinks=False)
            if os.path.getsize(src) != os.path.getsize(dst):
                os.remove(dst)
                raise OSError("A cópia não ficou igual ao original.") from e
            os.remove(src)


def trash(path: str) -> None:
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio
    Gio.File.new_for_path(path).trash(None)


def restore_from_trash(orig: str) -> None:
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio
    root = Gio.File.new_for_uri("trash:///")
    enum = root.enumerate_children("standard::name,trash::orig-path,trash::deletion-date",
                                   Gio.FileQueryInfoFlags.NONE, None)
    best: tuple[str, str] | None = None
    for info in enum:
        path = info.get_attribute_byte_string("trash::orig-path")
        if path == orig:
            date = info.get_attribute_string("trash::deletion-date") or ""
            if best is None or date > best[0]:
                best = (date, info.get_name())
    if best is None:
        raise FileNotFoundError("O ficheiro já não está no Lixo.")
    if os.path.lexists(orig):
        raise FileExistsError("Já existe um ficheiro no local original.")
    os.makedirs(os.path.dirname(orig), exist_ok=True)
    root.get_child(best[1]).move(Gio.File.new_for_path(orig), Gio.FileCopyFlags.NONE, None, None)


ProgressFn = Callable[[int, int, str], None]


class Executor:
    def __init__(self, db: Database):
        self.db = db

    def apply(self, actions, root: str, title: str, cleanup_dirs: list[str] | None = None,
              protect: set[str] | None = None, remove_empty: bool = True,
              progress: ProgressFn | None = None, cancel: threading.Event | None = None) -> Result:
        sid = self.db.new_session(root, title)
        res = Result(sid)
        seq = 0
        protect = {os.path.normpath(p) for p in (protect or set())} | {os.path.normpath(root)}
        total = len(actions)

        def log(op, src, dst=None, status="ok", error=None):
            nonlocal seq
            self.db.log_op(sid, seq, op, src, dst, status, error)
            seq += 1

        for n, a in enumerate(actions):
            if cancel is not None and cancel.is_set():
                break
            if progress:
                progress(n, total, a.src)
            try:
                if a.op in ("move", "move_dir"):
                    if not os.path.lexists(a.src):
                        raise FileNotFoundError("O ficheiro já não existe no local original.")
                    dst = Path(a.dst)
                    missing = []
                    p = dst.parent
                    while not p.exists():
                        missing.append(p)
                        p = p.parent
                    for d in reversed(missing):
                        d.mkdir()
                        log("mkdir", str(d))
                    if os.path.lexists(dst):
                        dst = unique_path(dst)
                    safe_move(a.src, str(dst))
                    a.dst = str(dst)
                    log(a.op, a.src, str(dst))
                    res.bytes_moved += a.size
                elif a.op == "trash":
                    trash(a.src)
                    log("trash", a.src)
                elif a.op == "rmdir":
                    self._remove_empty_tree(a.src, log)
                res.ok += 1
            except Exception as e:  # cada erro fica registado e o resto continua
                msg = getattr(e, "strerror", None) or str(e)
                res.errors.append((a.src, msg))
                log(a.op, a.src, a.dst or None, "erro", msg)

        if remove_empty:
            for d in sorted(set(cleanup_dirs or []), key=lambda x: x.count(os.sep), reverse=True):
                nd = os.path.normpath(d)
                if nd in protect or not is_within(nd, root):
                    continue
                try:
                    if os.path.isdir(nd) and not os.listdir(nd):
                        os.rmdir(nd)
                        log("rmdir", nd)
                except OSError:
                    pass

        self.db.finish_session(sid, res.ok, len(res.errors))
        if progress:
            progress(total, total, "")
        return res

    def _remove_empty_tree(self, top: str, log) -> None:
        for dirpath, dirs, files in os.walk(top, topdown=False):
            if files:
                raise OSError("A pasta já não está vazia.")
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
                log("rmdir", dirpath)
        if os.path.exists(top):
            raise OSError("A pasta já não está vazia.")

    def undo(self, session_id: int, progress: ProgressFn | None = None) -> Result:
        ops = [o for o in self.db.ops(session_id) if o["status"] == "ok"]
        res = Result(session_id)
        total = len(ops)
        for n, o in enumerate(reversed(ops)):
            if progress:
                progress(n, total, o["src"])
            try:
                op, src, dst = o["op"], o["src"], o["dst"]
                if op in ("move", "move_dir"):
                    if not os.path.lexists(dst):
                        raise FileNotFoundError("O ficheiro já não está onde foi colocado.")
                    os.makedirs(os.path.dirname(src), exist_ok=True)
                    safe_move(dst, src)
                elif op == "mkdir":
                    try:
                        os.rmdir(src)
                    except OSError:
                        pass  # entretanto tem outros ficheiros: fica
                elif op == "rmdir":
                    os.makedirs(src, exist_ok=True)
                elif op == "trash":
                    restore_from_trash(src)
                res.ok += 1
            except Exception as e:
                res.errors.append((o["src"], getattr(e, "strerror", None) or str(e)))
        self.db.mark_undone(session_id)
        if progress:
            progress(total, total, "")
        return res
