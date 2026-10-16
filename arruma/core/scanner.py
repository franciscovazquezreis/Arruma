"""Análise (leitura) de uma pasta: ficheiros, subpastas, pastas protegidas."""

from __future__ import annotations

import fnmatch
import os
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import taxonomy as tx
from .fsutil import HOME, display_path, is_generic_dir_name, is_within, normalize_roots, split_ext
from .system import PROTECTED_NAMES, is_hidden_entry, is_link_entry, is_package_dir

# Pastas de projetos de programação: nunca são desmontadas.
PROJECT_MARKERS = {
    ".git", ".hg", ".svn", "package.json", "pyproject.toml", "setup.py", "setup.cfg",
    "requirements.txt", "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts",
    "CMakeLists.txt", "Makefile", "meson.build", "composer.json", "Gemfile", "pubspec.yaml",
    "mix.exs", ".venv", "venv", "node_modules", ".idea", ".vscode", "Dockerfile",
}
PROJECT_GLOBS = ["*.sln", "*.csproj", "*.xcodeproj", "*.Rproj", "*.kdev4"]

# Bibliotecas geridas por outros programas: mexer-lhes estraga essas aplicações.
LIBRARY_MARKERS = {
    "metadata.db": "biblioteca do Calibre",
    "digikam4.db": "biblioteca do digiKam",
    "library.darktable": "biblioteca do darktable",
    "steamapps": "biblioteca do Steam",
    ".nomedia": "pasta marcada para ignorar",
    ".arruma-ignorar": "pasta marcada para ignorar",
    ".arruma-ignore": "pasta marcada para ignorar",
    "zotero.sqlite": "biblioteca do Zotero",
}
LIBRARY_GLOBS = {"*.lrcat": "catálogo do Lightroom", "*.vbox": "máquina virtual",
                 "*.vmx": "máquina virtual", "*.qcow2": "máquina virtual"}

PROTECTED_DIR_NAMES = {
    "snap": "pasta de aplicações Snap",
    "VirtualBox VMs": "máquinas virtuais",
    "Calibre Library": "biblioteca do Calibre",
    "Biblioteca do calibre": "biblioteca do Calibre",
    "Zotero": "biblioteca do Zotero",
    "Dropbox": "pasta sincronizada (Dropbox)",
    "Nextcloud": "pasta sincronizada (Nextcloud)",
    "ownCloud": "pasta sincronizada (ownCloud)",
    "OneDrive": "pasta sincronizada (OneDrive)",
    "MEGA": "pasta sincronizada (MEGA)",
    "pCloudDrive": "pasta sincronizada (pCloud)",
    "Insync": "pasta sincronizada (Insync)",
    "Steam": "biblioteca do Steam",
    "Games": "jogos instalados",
    "Jogos": "jogos instalados",
    "AppImages": "aplicações instaladas",
    "Applications": "aplicações instaladas",
    "Aplicações": "aplicações instaladas",
    "bin": "programas do utilizador",
    "go": "área de trabalho de Go",
    "Modelos": "modelos de documentos do sistema",
    "Templates": "modelos de documentos do sistema",
    "Público": "pasta pública partilhada",
    "Public": "pasta pública partilhada",
    "__pycache__": "ficheiros internos de Python",
    "node_modules": "dependências de programação",
    "site-packages": "dependências de programação",
    "lost+found": "pasta de recuperação do disco",
    ".Trash-1000": "Lixo do sistema",
    ".Trashes": "Lixo do sistema",
    **PROTECTED_NAMES,
}


@dataclass(slots=True)
class FileItem:
    path: str
    name: str
    ext: str
    size: int
    mtime: float
    kind: str
    parent: str


@dataclass
class FolderInfo:
    path: str
    name: str
    depth: int
    generic: bool
    protected: str | None = None  # motivo, se protegida
    children: list[str] = field(default_factory=list)
    direct_files: int = 0
    total_files: int = 0
    total_size: int = 0
    kinds: Counter = field(default_factory=Counter)
    empty: bool = False


@dataclass
class ScanResult:
    root: str
    files: list[FileItem]
    folders: dict[str, FolderInfo]
    protected: list[tuple[str, str]]
    skipped_hidden: int
    skipped_links: int
    errors: list[tuple[str, str]]
    total_size: int
    by_kind: dict[str, tuple[int, int]]  # kind -> (count, size)
    roots: list[str] = field(default_factory=list)
    whole_computer: bool = False
    cancelled: bool = False

    def __post_init__(self) -> None:
        if not self.roots:
            self.roots = [self.root]

    @property
    def title(self) -> str:
        if self.whole_computer:
            return "Todo o computador"
        if len(self.roots) == 1:
            return os.path.basename(self.roots[0]) or self.roots[0]
        if len(self.roots) == 2:
            return f"{os.path.basename(self.roots[0])} e {os.path.basename(self.roots[1])}"
        return f"{len(self.roots)} pastas selecionadas"

    @property
    def subtitle(self) -> str:
        return " · ".join(display_path(r) for r in self.roots)


class ScanCancelled(Exception):
    pass


def _protection_reason(path: str, name: str, entries: list[str], is_root: bool) -> str | None:
    if not is_root and name in PROTECTED_DIR_NAMES:
        return PROTECTED_DIR_NAMES[name]
    if not is_root and is_package_dir(name):
        return "pacote de aplicação ou biblioteca (é um ficheiro só)"
    names = set(entries)
    for marker, why in LIBRARY_MARKERS.items():
        if marker in names:
            return why
    for pattern, why in LIBRARY_GLOBS.items():
        if any(fnmatch.fnmatch(e, pattern) for e in entries):
            return why
    if is_root:
        return None
    if names & PROJECT_MARKERS or any(fnmatch.fnmatch(e, g) for g in PROJECT_GLOBS for e in entries):
        return "projeto de programação"
    return None


# No Windows o os.scandir junta caminhos com «\», mas o Python do MSYS2 dentro do Git Bash usa «/»:
# normalizar evita misturas que estragariam as comparações de caminhos.
_norm = os.path.normpath if os.altsep else (lambda p: p)


def scan(root: str | Path | list[str | Path] | tuple[str | Path, ...],
         include_hidden: bool = False,
         excluded: list[str] | None = None,
         progress: Callable[[int, str], None] | None = None,
         cancel: threading.Event | None = None) -> ScanResult:
    roots, whole_computer = normalize_roots(root)
    excluded = [str(Path(e).expanduser()) for e in (excluded or [])]
    files: list[FileItem] = []
    folders: dict[str, FolderInfo] = {}
    protected: list[tuple[str, str]] = []
    errors: list[tuple[str, str]] = []
    hidden = links = 0

    stack: list[FolderInfo] = []
    for r in reversed(roots):
        r_info = FolderInfo(path=r, name=os.path.basename(r) or r, depth=0, generic=False)
        folders[r] = r_info
        stack.append(r_info)
    last_report = 0

    while stack:
        if cancel is not None and cancel.is_set():
            raise ScanCancelled()
        info = stack.pop()
        try:
            with os.scandir(info.path) as it:
                entries = list(it)
        except OSError as e:
            errors.append((info.path, e.strerror or str(e)))
            continue

        reason = _protection_reason(info.path, info.name, [e.name for e in entries], info.depth == 0)
        if reason:
            info.protected = reason
            protected.append((info.path, reason))
            continue

        if not entries:
            info.empty = True

        subdirs: list[FolderInfo] = []
        for entry in entries:
            name = entry.name
            entry_path = _norm(entry.path)
            if not include_hidden and name.lower() not in tx.JUNK_NAMES and is_hidden_entry(entry):
                hidden += 1
                continue
            try:
                if is_link_entry(entry):
                    links += 1
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if any(is_within(entry_path, ex) for ex in excluded):
                        protected.append((entry_path, "excluída nas definições"))
                        continue
                    sub = FolderInfo(path=entry_path, name=name, depth=info.depth + 1,
                                     generic=is_generic_dir_name(name))
                    folders[entry_path] = sub
                    info.children.append(entry_path)
                    subdirs.append(sub)
                elif entry.is_file(follow_symlinks=False):
                    st = entry.stat(follow_symlinks=False)
                    _, ext = split_ext(name)
                    ext = ext.lower().lstrip(".")
                    kind = tx.kind_for(name, ext, st.st_size)
                    files.append(FileItem(entry_path, name, ext, st.st_size, st.st_mtime, kind, info.path))
                    info.direct_files += 1
                    info.total_files += 1
                    info.total_size += st.st_size
                    info.kinds[kind] += 1
            except OSError as e:
                errors.append((entry_path, e.strerror or str(e)))

        stack.extend(reversed(subdirs))
        if progress is not None and len(files) - last_report >= 250:
            last_report = len(files)
            progress(len(files), info.path)

    # Totais recursivos (das pastas mais profundas para cima)
    for info in sorted(folders.values(), key=lambda f: f.depth, reverse=True):
        if info.protected or info.depth == 0:
            continue
        parent = folders.get(os.path.dirname(info.path))
        if parent is not None:
            parent.total_files += info.total_files
            parent.total_size += info.total_size
            parent.kinds.update(info.kinds)

    by_kind: dict[str, list[int]] = {}
    total = 0
    for f in files:
        c = by_kind.setdefault(f.kind, [0, 0])
        c[0] += 1
        c[1] += f.size
        total += f.size

    primary_root = roots[0] if len(roots) == 1 else os.path.commonpath(roots)
    if progress is not None:
        progress(len(files), primary_root)

    return ScanResult(root=primary_root, roots=roots, whole_computer=whole_computer,
                      files=files, folders=folders, protected=protected,
                      skipped_hidden=hidden, skipped_links=links, errors=errors,
                      total_size=total, by_kind={k: (v[0], v[1]) for k, v in by_kind.items()})


def is_home(path: str) -> bool:
    return os.path.realpath(path) == os.path.realpath(HOME)
