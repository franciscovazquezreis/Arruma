# SPDX-License-Identifier: GPL-3.0-or-later
"""Deteção de ficheiros duplicados (conteúdo exatamente igual)."""

from __future__ import annotations

import hashlib
import os
import re
import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

from .fsutil import is_within, user_dirs
from .scanner import FileItem

CHUNK = 64 * 1024
_COPY_MARK = re.compile(r"(\(\d+\)|c[oó]pia|copy|_\d$| - \d$)", re.I)


@dataclass
class DupGroup:
    size: int
    files: list[FileItem]
    keep: str

    @property
    def wasted(self) -> int:
        return self.size * (len(self.files) - 1)

    @property
    def keep_file(self) -> FileItem:
        """A cópia que o Arruma sugere manter."""
        return next(f for f in self.files if f.path == self.keep)


def _partial_hash(path: str, size: int) -> str:
    """Resumo rápido: o ficheiro inteiro até 2×CHUNK; acima disso, só o início e o fim (os que
    coincidem são depois comparados por inteiro em _full_hash)."""
    h = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as fh:
        if size <= 2 * CHUNK:
            h.update(fh.read())
        else:
            h.update(fh.read(CHUNK))
            fh.seek(-CHUNK, os.SEEK_END)
            h.update(fh.read(CHUNK))
    return h.hexdigest()


def _full_hash(path: str, cancel: threading.Event | None) -> str:
    h = hashlib.blake2b(digest_size=32)
    with open(path, "rb") as fh:
        while chunk := fh.read(1024 * 1024):
            if cancel is not None and cancel.is_set():
                raise InterruptedError()
            h.update(chunk)
    return h.hexdigest()


def choose_keep(files: list[FileItem]) -> str:
    """Mantém a cópia com melhor nome e local mais "arrumado"."""
    xdg = user_dirs()
    inboxes = [str(xdg["DOWNLOAD"]), str(xdg["DESKTOP"])]

    def score(f: FileItem):
        stem = os.path.splitext(f.name)[0]
        return (
            bool(_COPY_MARK.search(stem)),
            any(is_within(f.path, i) for i in inboxes),
            f.mtime,
            len(f.path),
        )
    return min(files, key=score).path


def find_duplicates(files: list[FileItem], min_size: int = 1,
                    progress: Callable[[int, int, str], None] | None = None,
                    cancel: threading.Event | None = None) -> list[DupGroup]:
    by_size: dict[int, list[FileItem]] = defaultdict(list)
    for f in files:
        if f.size >= min_size:
            by_size[f.size].append(f)
    candidates = [g for g in by_size.values() if len(g) > 1]
    total = sum(len(g) for g in candidates)
    done = 0
    groups: list[DupGroup] = []
    for same_size in candidates:
        by_partial: dict[str, list[FileItem]] = defaultdict(list)
        for f in same_size:
            if cancel is not None and cancel.is_set():
                raise InterruptedError()
            done += 1
            if progress and done % 20 == 0:
                progress(done, total, f.name)
            try:
                by_partial[_partial_hash(f.path, f.size)].append(f)
            except OSError:
                continue
        for same_partial in by_partial.values():
            if len(same_partial) < 2:
                continue
            if same_partial[0].size <= 2 * CHUNK:  # o resumo parcial já leu o ficheiro inteiro
                full_groups = {"x": same_partial}
            else:
                full_groups = defaultdict(list)
                for f in same_partial:
                    try:
                        full_groups[_full_hash(f.path, cancel)].append(f)
                    except OSError:
                        continue
            for g in full_groups.values():
                if len(g) > 1:
                    groups.append(DupGroup(g[0].size, sorted(g, key=lambda f: f.path), choose_keep(g)))
    if progress:
        progress(total, total, "")
    groups.sort(key=lambda g: g.wasted, reverse=True)
    return groups
