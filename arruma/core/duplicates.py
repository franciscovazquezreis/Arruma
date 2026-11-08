# SPDX-License-Identifier: GPL-3.0-or-later
"""Deteção de ficheiros duplicados (conteúdo exatamente igual)."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .fsutil import path_parts
from .scanner import FileItem

CHUNK = 64 * 1024
# «foto (1).jpg» (navegadores), «foto - Cópia.jpg» (Windows), «Cópia de foto.jpg» (Google Drive),
# «foto copy.jpg» (macOS), «foto (outra cópia).jpg» (Nemo, Nautilus), «foto_1.jpg», «foto - 2.jpg».
_COPY_MARK = re.compile(r"(\(\d+\)|\bc[oó]pia\b|\bcopy\b|_\d$| - \d$)", re.I)


def has_copy_mark(name: str) -> bool:
    return bool(_COPY_MARK.search(os.path.splitext(name)[0]))


def _name_rank(f: FileItem):
    # Sem «(1)» nem «cópia» no nome, depois o nome mais curto e, por fim, a mais antiga.
    return has_copy_mark(f.name), len(f.name), f.mtime, f.name


@dataclass
class DupGroup:
    size: int
    files: list[FileItem]  # por pasta e, em cada pasta, primeiro a que não tem «(1)» nem «cópia» no nome
    # Tamanho e data de modificação (em ns) de cada cópia quando foi comparada: antes de a enviar para o
    # Lixo, se nada mudou, não é preciso voltar a ler tudo (ver check_copy).
    sigs: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def wasted(self) -> int:
        return self.size * (len(self.files) - 1)

    @property
    def folders(self) -> tuple[str, ...]:
        """As pastas onde estão as cópias, cada uma uma vez."""
        return tuple(sorted({f.parent for f in self.files}, key=lambda p: (p.casefold(), p)))

    @property
    def title(self) -> str:
        """O nome que representa o grupo: o que não tem «(1)» nem «cópia»."""
        return min(self.files, key=_name_rank).name

    def keeping(self, folder: str) -> set[str]:
        """O que vai para o Lixo quando ficam as cópias de «folder»: as das outras pastas. Dentro de «folder» só
        vai o que já vinha marcado (com «(1)» ou «cópia» no nome, ao lado de uma cópia sem essa marca): um nome
        escolhido, como «Avó 90 anos.jpg», fica mesmo que haja outra cópia com outro nome na mesma pasta."""
        here = {f.path for f in self.files if f.parent == folder}
        return {f.path for f in self.files if f.path not in here} | (self.suggested() & here)

    def suggested(self) -> set[str]:
        """O que vem marcado à partida para ir para o Lixo: só as cópias com «(1)», «cópia» ou «copy» no nome
        que estão na mesma pasta que uma cópia sem essa marca (a mesma transferência feita duas vezes, por
        exemplo). Entre pastas diferentes não se marca nada: só o utilizador sabe qual das pastas é a boa."""
        out: set[str] = set()
        for folder in self.folders:
            here = [f for f in self.files if f.parent == folder]
            if any(not has_copy_mark(f.name) for f in here):
                out |= {f.path for f in here if has_copy_mark(f.name)}
        return out


def short_names(folders: Iterable[str]) -> dict[str, str]:
    """Nomes curtos e distintos para mostrar as pastas: o último nome do caminho e, se duas pastas tiverem
    o mesmo, também os nomes de cima («2023/Fotos» e «2024/Fotos»)."""
    parts = {f: path_parts(f, "") for f in set(folders)}  # a primeira parte é o disco («/» ou «C:\»)
    depth = dict.fromkeys(parts, 1)
    while True:
        names = {f: f if depth[f] >= len(parts[f]) else os.sep.join(parts[f][-depth[f]:]) for f in parts}
        seen: dict[str, list[str]] = defaultdict(list)
        for f, n in names.items():
            seen[n.casefold()].append(f)
        grow = [f for same in seen.values() if len(same) > 1 for f in same if depth[f] < len(parts[f])]
        if not grow:
            return names
        for f in grow:
            depth[f] += 1


# Ficheiros só na nuvem (OneDrive, iCloud): lê-los obrigava a descarregá-los, e enviá-los para o Lixo apaga-os
# também na nuvem e nos outros dispositivos. Ficam fora da procura.
_RECALL = 0x400000 | 0x40000 | 0x1000  # Windows: RECALL_ON_DATA_ACCESS, RECALL_ON_OPEN, OFFLINE
_SF_DATALESS = 0x40000000  # macOS


def _cloud_only(st: os.stat_result) -> bool:
    return bool(getattr(st, "st_file_attributes", 0) & _RECALL or getattr(st, "st_flags", 0) & _SF_DATALESS)


class NotACopy(Exception):
    """A cópia marcada já não pode ir para o Lixo como duplicada: fica onde está."""


def _same_content(a: str, b: str) -> bool:
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            x, y = fa.read(1024 * 1024), fb.read(1024 * 1024)
            if x != y:
                return False
            if not x:
                return True


def check_copy(path: str, keepers: list[str], sigs: dict[str, tuple[int, int]]) -> None:
    """Confirma, mesmo antes de enviar «path» para o Lixo, que continua igual, byte a byte, a pelo menos uma
    das cópias que ficam. Desde a procura, o ficheiro pode ter sido alterado (e deixado de ser uma cópia) ou a
    cópia que ficava pode ter sido apagada ou alterada; se for assim, levanta NotACopy e o ficheiro fica."""
    try:
        st = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        raise FileNotFoundError("O ficheiro já não existe no local original.") from None
    if not stat.S_ISREG(st.st_mode):
        raise NotACopy("Ficou onde estava: já não é o ficheiro que foi comparado.")
    unchanged = sigs.get(path) == (st.st_size, st.st_mtime_ns)
    for k in keepers:
        try:
            kst = os.stat(k, follow_symlinks=False)
        except OSError:
            continue
        if not stat.S_ISREG(kst.st_mode) or kst.st_size != st.st_size:
            continue
        if st.st_ino and (kst.st_dev, kst.st_ino) == (st.st_dev, st.st_ino):
            raise NotACopy("Ficou onde estava: é o mesmo ficheiro que a cópia que fica, com outro caminho.")
        if unchanged and sigs.get(k) == (kst.st_size, kst.st_mtime_ns):
            return
        try:
            if _same_content(path, k):
                return
        except OSError:
            continue
    raise NotACopy("Ficou onde estava: mudou desde a procura e já não é igual a nenhuma das cópias que ficam.")


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
    sigs: dict[str, tuple[int, int]] = {}
    for same_size in candidates:
        by_partial: dict[str, list[FileItem]] = defaultdict(list)
        seen: set[tuple[int, int]] = set()
        for f in same_size:
            if cancel is not None and cancel.is_set():
                raise InterruptedError()
            done += 1
            if progress and done % 20 == 0:
                progress(done, total, f.name)
            try:
                st = os.stat(f.path)
                if st.st_size != f.size or _cloud_only(st):  # mudou desde a análise, ou só está na nuvem
                    continue
                # Dois caminhos para o mesmo ficheiro (ligações físicas, a mesma pasta montada em dois sítios)
                # não são cópias: enviar um para o Lixo levava o único que existe.
                if st.st_ino:
                    if (st.st_dev, st.st_ino) in seen:
                        continue
                    seen.add((st.st_dev, st.st_ino))
                sigs[f.path] = (st.st_size, st.st_mtime_ns)
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
                    g = sorted(g, key=lambda f: (f.parent.casefold(), f.parent, _name_rank(f)))
                    groups.append(DupGroup(g[0].size, g, {f.path: sigs[f.path] for f in g}))
    if progress:
        progress(total, total, "")
    # As cópias nas mesmas pastas ficam juntas, por ordem do nome (a escolha costuma ser a mesma para todas);
    # primeiro as pastas onde se liberta mais espaço.
    by_folders: dict[tuple[str, ...], int] = defaultdict(int)
    for g in groups:
        by_folders[g.folders] += g.wasted
    groups.sort(key=lambda g: (-by_folders[g.folders], g.folders, g.title.casefold(), -g.wasted))
    return groups
