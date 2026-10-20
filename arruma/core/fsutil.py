# SPDX-License-Identifier: GPL-3.0-or-later
"""Utilitários de sistema de ficheiros: nomes, tamanhos, caminhos únicos e pastas permitidas."""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

from .system import (HOME, IS_MAC, IS_WINDOWS, computer_roots, is_whole_computer_path, program_data_dirs,
                     system_paths, temp_dir, user_dirs)

xdg_user_dirs = user_dirs  # nome antigo


# --------------------------------------------------------------------------- formatação

def human_size(n: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    if i == 0:
        return f"{int(n)} B"
    txt = f"{n:.1f}" if n < 100 else f"{n:.0f}"
    return f"{txt.replace('.', ',')} {units[i]}"


def human_count(n: int) -> str:
    return f"{n:,}".replace(",", "\u00a0")


def plural(n: int, singular: str, plural_: str) -> str:
    return f"{human_count(n)} {singular if n == 1 else plural_}"


def display_path(path: str | Path) -> str:
    """Caminho legível: ~/Documentos/… em vez de /home/utilizador/Documentos/… (no Windows fica completo)."""
    p = str(path)
    if IS_WINDOWS:
        return p
    home = str(HOME)
    if p == home:
        return "~"
    if p.startswith(home + os.sep):
        return "~" + p[len(home):]
    return p


def strip_accents(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text)
    return "".join(c for c in norm if not unicodedata.combining(c))


# --------------------------------------------------------------------------- nomes

_GENERIC_DIR = re.compile(
    r"^(nova pasta|new folder|untitled folder|pasta sem t[ií]tulo|sem t[ií]tulo|untitled|"
    r"novo|nova|new|temp|tmp|misc|diversos|v[aá]rios|outros|stuff|coisas|lixo|old|"
    r"antigo|antigos|teste|test|ficheiros|files|folder|pasta|desktop|downloads?|"
    r"transfer[eê]ncias?|organizar|por organizar|para organizar|arrumar)"
    r"[\s_\-]*(\(?\d+\)?)?$",
    re.IGNORECASE,
)


def is_generic_dir_name(name: str) -> bool:
    """Pastas sem significado próprio, cujo conteúdo pode ser redistribuído."""
    n = name.strip()
    if _GENERIC_DIR.match(n):
        return True
    compact = re.sub(r"[\s_\-\.]", "", n)
    if compact.isdigit() and len(compact) > 4 and not re.fullmatch(r"(19|20)\d{2}(\d{2}){0,2}", compact):
        return True
    if re.fullmatch(r"[0-9a-f]{12,}", compact.lower()):
        return True
    return False


_UNCLEAR_FILE = re.compile(
    r"(scan|scanned|scanner|digitaliza[cç][aã]o|doc|docs|document|documento|file|ficheiro|"
    r"arquivo|untitled|sem t[ií]tulo|novo documento( de texto)?|new document|download|"
    r"print|impress[aã]o|output|export|img|image|imagem|pdf|attachment|anexo|unnamed|"
    r"temp|tmp|teste?|test|c[oó]pia de .*|copy of .*|fatura|invoice|recibo|receipt|"
    # uma só palavra genérica não diz qual é o documento («Contrato.pdf», «ata.pdf»)
    r"contrato|relat[oó]rio|ata|manual|certificado|extrato|carta|receita|declara[cç][aã]o|"
    r"comprovativo|or[cç]amento|proposta|apresenta[cç][aã]o|notas?|garantia|encomenda|bilhete|"
    r"reserva|livro|procura[cç][aã]o|inspe[cç][aã]o|seguro|ap[oó]lice|an[aá]lises|exame)"
    r"[\s_\-\.]*\d*",
    re.IGNORECASE,
)


def is_unclear_name(stem: str) -> bool:
    """Nomes que não dizem o que o ficheiro é (scan_003, 8f3a2c…, Documento (1))."""
    s = stem.strip().lower()
    s = re.sub(r"[\s_\-\.]*\(\d+\)$", "", s)
    if not s:
        return True
    if _UNCLEAR_FILE.fullmatch(s):
        return True
    if re.fullmatch(r"[\d\s_\-\.]+", s):
        return True
    if re.fullmatch(r"[0-9a-f]{8,}", s.replace("-", "")):
        return True
    if re.fullmatch(r"[a-z]{0,5}[\s_\-]?\d{4,}([\s_\-]\d+)*", s):
        return True
    letters = sum(c.isalpha() for c in s)
    return len(s) >= 10 and letters / len(s) < 0.35


_BAD_CHARS = re.compile(r'[\x00-\x1f/\\:*?"<>|]')
_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)", re.IGNORECASE)


def sanitize_name(name: str, maxlen: int = 110) -> str:
    """Nome de ficheiro/pasta seguro e portátil (também para pens USB e Windows)."""
    name = _BAD_CHARS.sub(" ", unicodedata.normalize("NFC", name))
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > maxlen:
        name = name[:maxlen].rstrip(" .")
    if _RESERVED.match(name):  # nomes proibidos no Windows (CON, NUL, COM1…)
        name = "_" + name
    return name or "Sem nome"


def split_ext(name: str) -> tuple[str, str]:
    lower = name.lower()
    for double in (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst"):
        if lower.endswith(double):
            return name[: -len(double)], name[-len(double):]
    stem, ext = os.path.splitext(name)
    if not stem:  # ".bashrc"
        return name, ""
    return stem, ext


def path_key(path: str | Path) -> str:
    """Chave para comparar caminhos: no Windows e no macOS «Faturas» e «faturas» são a mesma pasta."""
    p = os.path.normpath(str(path))
    if IS_WINDOWS:
        return os.path.normcase(p)
    if IS_MAC:
        return unicodedata.normalize("NFC", p).casefold()
    return p


def unique_path(path: Path, taken: set[str] | None = None) -> Path:
    """Devolve um caminho livre, acrescentando « (2)», « (3)»… se necessário.

    «taken» tem as chaves (path_key) dos destinos já reservados no plano."""
    taken = taken if taken is not None else set()
    if not os.path.lexists(path) and path_key(path) not in taken:
        return path
    stem, ext = split_ext(path.name)
    i = 2
    while True:
        cand = path.with_name(f"{stem} ({i}){ext}")
        if not os.path.lexists(cand) and path_key(cand) not in taken:
            return cand
        i += 1


def is_within(path: str | Path, base: str | Path) -> bool:
    p, b = str(path), str(base)
    if IS_WINDOWS:
        p, b = os.path.normcase(p), os.path.normcase(b)
    b = b.rstrip(os.sep) if len(b) > 1 and not b.endswith(":" + os.sep) else b
    if p == b:
        return True
    return p.startswith(b if b.endswith(os.sep) else b + os.sep)


def common_root(paths: list[str]) -> str | None:
    """Pasta comum a todos os caminhos, ou None se não houver (no Windows, pastas em discos diferentes)."""
    try:
        return os.path.commonpath(paths) or None
    except ValueError:
        return None


def path_parts(path: str, anchor: str) -> list[str]:
    """Partes de «path» a partir de «anchor». Sem âncora (discos diferentes), a primeira parte é o disco
    («D:\\»), e os.path.join("", *partes) volta a dar o caminho."""
    if anchor:
        rel = os.path.relpath(path, anchor)
        return [] if rel == "." else [p for p in rel.split(os.path.sep) if p]
    drive, rest = os.path.splitdrive(path)
    return [drive + os.path.sep] + [p for p in rest.split(os.path.sep) if p]


SYSTEM_PATHS = system_paths()

COMPUTER_TOKEN = "__COMPUTER__"


def expand_computer_roots() -> list[str]:
    """Pastas de utilizador e discos/partições montados em todo o computador."""
    return computer_roots()


def normalize_roots(paths: str | Path | list[str | Path] | tuple[str | Path, ...]) -> tuple[list[str], bool]:
    """Normaliza uma ou várias pastas (ou Todo o computador) e remove pastas já contidas noutras."""
    if isinstance(paths, (str, Path)):
        raw_list = [paths]
    else:
        raw_list = list(paths)
    whole_computer = False
    expanded: list[str] = []
    for item in raw_list:
        s = str(item)
        if s in (COMPUTER_TOKEN, "/"):
            whole_computer = True
            expanded.extend(expand_computer_roots())
        else:
            p = os.path.normpath(str(Path(s).expanduser().resolve()))
            if is_whole_computer_path(p):
                whole_computer = True
                expanded.extend(expand_computer_roots())
            else:
                expanded.append(p)
    # Ordenar do caminho mais curto para o mais longo e eliminar subpastas redundantes
    unique: list[str] = []
    for p in sorted(set(expanded), key=lambda x: (x.count(os.sep), x)):
        if not any(is_within(p, existing) for existing in unique):
            unique.append(p)
    return unique, whole_computer


def check_root_allowed(path: Path | str) -> str | None:
    """Devolve uma mensagem de erro se a pasta não puder ser organizada com segurança."""
    if str(path) in (COMPUTER_TOKEN, "/"):
        return None
    p = str(Path(path).resolve())
    if is_whole_computer_path(p):
        return None
    tmp = temp_dir()
    in_temp = is_within(p, tmp) and os.path.normcase(p) != os.path.normcase(tmp)
    if not in_temp:
        for sp in SYSTEM_PATHS:
            if is_within(p, sp):
                return "Esta é uma pasta do sistema. Por segurança, o Arruma não lhe toca."
        if any(is_within(p, str(h)) for h in program_data_dirs()):
            return "Esta pasta contém configurações de programas e não deve ser reorganizada."
    if not Path(p).is_dir():
        return "A pasta não existe."
    if not os.access(p, os.W_OK | os.X_OK):
        return "Não tens permissão para alterar esta pasta."
    return None
