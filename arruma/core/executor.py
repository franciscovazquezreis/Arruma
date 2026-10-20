# SPDX-License-Identifier: GPL-3.0-or-later
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
from .trash import restore as restore_from_trash
from .trash import send_to_trash


@dataclass
class Result:
    session_id: int
    ok: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    bytes_moved: int = 0
    cancelled: bool = False  # parou a meio, a pedido


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


ProgressFn = Callable[[int, int, str], None]


class Executor:
    def __init__(self, db: Database):
        self.db = db
        self.running: int | None = None  # a sessão a ser aplicada agora (o Histórico mostra-a «a decorrer»)

    def apply(self, actions, root: str, title: str, cleanup_dirs: list[str] | None = None,
              protect: set[str] | None = None, remove_empty: bool = True,
              progress: ProgressFn | None = None, cancel: threading.Event | None = None,
              roots: list[str] | None = None) -> Result:
        """«roots»: as pastas analisadas (por defeito, só «root»). Só se removem pastas vazias dentro delas;
        com pastas em discos diferentes (C: e D:), «root» é apenas a primeira."""
        sid = self.db.new_session(root, title)
        self.running = sid
        try:
            return self._apply(sid, actions, root, cleanup_dirs, protect, remove_empty, progress, cancel, roots)
        finally:
            self.running = None

    def _apply(self, sid, actions, root, cleanup_dirs, protect, remove_empty, progress, cancel, roots) -> Result:
        res = Result(sid)
        seq = 0
        protect = {os.path.normpath(p) for p in [*(protect or ()), *(roots or ()), root]}
        total = len(actions)

        def log(op, src, dst=None, status="ok", error=None):
            # Cada operação grava também as contagens: se o Arruma fechar a meio, o que já foi feito
            # aparece no Histórico e pode ser anulado.
            nonlocal seq
            self.db.log_op(sid, seq, op, src, dst, status, error, (res.ok, len(res.errors)))
            seq += 1

        for n, a in enumerate(actions):
            if cancel is not None and cancel.is_set():
                res.cancelled = True
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
                    res.ok += 1
                    res.bytes_moved += a.size
                    log(a.op, a.src, str(dst))
                elif a.op == "trash":
                    where = send_to_trash(a.src)
                    res.ok += 1
                    log("trash", a.src, where)
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
                if nd in protect or not any(is_within(nd, r) for r in (roots or [root])):
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

    def undo(self, session_id: int, progress: ProgressFn | None = None,
             cancel: threading.Event | None = None) -> Result:
        """Devolve cada item ao sítio onde estava, do último para o primeiro. Cada operação anulada fica
        marcada logo: se alguma falhar (ou se parar a meio), anular outra vez só tenta o que falta."""
        ops = [o for o in self.db.ops(session_id) if o["status"] == "ok"]
        res = Result(session_id)
        total = len(ops)
        for n, o in enumerate(reversed(ops)):
            if cancel is not None and cancel.is_set():
                res.cancelled = True
                break
            if progress:
                progress(n, total, o["src"])
            try:
                op, src, dst = o["op"], o["src"], o["dst"]
                done = True
                if op in ("move", "move_dir"):
                    here, back = os.path.lexists(dst), os.path.lexists(src)
                    if not here and not back:
                        raise FileNotFoundError("O ficheiro já não está onde foi colocado.")
                    if here and back:
                        raise FileExistsError(errno.EEXIST, "Já existe um item com o mesmo nome no local original.")
                    if here:  # se só está no local original, já lá voltou (à mão)
                        os.makedirs(os.path.dirname(src), exist_ok=True)
                        safe_move(dst, src)
                elif op == "mkdir":
                    try:
                        os.rmdir(src)
                    except FileNotFoundError:
                        pass
                    except OSError:
                        done = False  # entretanto tem outros ficheiros: fica, e tenta-se de novo ao anular o resto
                elif op == "rmdir":
                    os.makedirs(src, exist_ok=True)
                elif op == "trash":
                    restore_from_trash(src, dst)
                if done:
                    self.db.mark_op_undone(o["id"])
                res.ok += 1
            except Exception as e:
                res.errors.append((o["src"], getattr(e, "strerror", None) or str(e)))
        self.db.mark_undone(session_id)
        if progress:
            progress(total, total, "")
        return res
