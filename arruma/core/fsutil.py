"""Utilitários de sistema de ficheiros: pastas XDG, nomes, tamanhos, caminhos únicos."""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

HOME = Path.home()

_XDG_DEFAULTS = {
    "DESKTOP": "Desktop",
    "DOWNLOAD": "Downloads",
    "DOCUMENTS": "Documents",
    "MUSIC": "Music",
    "PICTURES": "Pictures",
    "VIDEOS": "Videos",
    "TEMPLATES": "Templates",
    "PUBLICSHARE": "Public",
}


def xdg_user_dirs() -> dict[str, Path]:
    """Lê ~/.config/user-dirs.dirs (pastas pessoais na língua do sistema)."""
    dirs = {k: HOME / v for k, v in _XDG_DEFAULTS.items()}
    cfg = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "user-dirs.dirs"
    try:
        for line in cfg.read_text(encoding="utf-8").splitlines():
            m = re.match(r'^\s*XDG_([A-Z]+)_DIR\s*=\s*"(.*)"\s*$', line)
            if not m:
                continue
            key, value = m.group(1), m.group(2).replace("$HOME", str(HOME))
            path = Path(value)
            if path != HOME:  # pastas desativadas apontam para $HOME
                dirs[key] = path
    except OSError:
        pass
    return dirs


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
    """Caminho legível: ~/Documentos/… em vez de /home/utilizador/Documentos/…"""
    p = str(path)
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
    r"temp|tmp|teste?|test|c[oó]pia de .*|copy of .*|fatura|invoice|recibo|receipt)"
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


def sanitize_name(name: str, maxlen: int = 110) -> str:
    """Nome de ficheiro/pasta seguro e portátil (também para pens USB e Windows)."""
    name = _BAD_CHARS.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > maxlen:
        name = name[:maxlen].rstrip(" .")
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


def unique_path(path: Path, taken: set[str] | None = None) -> Path:
    """Devolve um caminho livre, acrescentando « (2)», « (3)»… se necessário."""
    taken = taken if taken is not None else set()
    if not os.path.lexists(path) and str(path) not in taken:
        return path
    stem, ext = split_ext(path.name)
    i = 2
    while True:
        cand = path.with_name(f"{stem} ({i}){ext}")
        if not os.path.lexists(cand) and str(cand) not in taken:
            return cand
        i += 1


def is_within(path: str | Path, base: str | Path) -> bool:
    p, b = str(path), str(base).rstrip(os.sep)
    return p == b or p.startswith(b + os.sep)


SYSTEM_PATHS = ["/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64", "/libx32",
                "/opt", "/proc", "/root", "/run", "/sbin", "/snap", "/srv", "/sys", "/tmp",
                "/usr", "/var", "/lost+found"]

COMPUTER_TOKEN = "__COMPUTER__"


def expand_computer_roots() -> list[str]:
    """Pastas de utilizador e discos/partições montados em todo o computador."""
    roots: list[str] = []
    if HOME.is_dir() and os.access(HOME, os.R_OK | os.W_OK | os.X_OK):
        roots.append(str(HOME.resolve()))
    home_parent = Path("/home")
    if home_parent.is_dir():
        try:
            for entry in sorted(home_parent.iterdir()):
                if entry.is_dir() and os.access(entry, os.R_OK | os.W_OK | os.X_OK):
                    rp = str(entry.resolve())
                    if rp not in roots:
                        roots.append(rp)
        except OSError:
            pass
    user = os.environ.get("USER") or HOME.name
    mount_bases = [Path("/media") / user, Path("/run/media") / user, Path("/media"), Path("/mnt")]
    for mb in mount_bases:
        if not mb.is_dir():
            continue
        try:
            for entry in sorted(mb.iterdir()):
                if not entry.is_dir() or entry.name == user:
                    continue
                if os.access(entry, os.R_OK | os.W_OK | os.X_OK):
                    rp = str(entry.resolve())
                    if not any(is_within(rp, r) or is_within(r, rp) for r in roots):
                        roots.append(rp)
        except OSError:
            continue
    return roots or [str(HOME.resolve())]


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
            p = str(Path(s).expanduser().resolve())
            if p == "/":
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
    if p == "/":
        return None
    for sp in SYSTEM_PATHS:
        if p == sp or (p.startswith(sp + os.sep) and not p.startswith("/tmp/")):
            return "Esta é uma pasta do sistema. Por segurança, o Arruma não lhe toca."
    if p == "/tmp":
        return "Esta é uma pasta do sistema. Por segurança, o Arruma não lhe toca."
    hidden_cfg = [HOME / ".config", HOME / ".local", HOME / ".cache"]
    if any(is_within(p, h) for h in hidden_cfg):
        return "Esta pasta contém configurações de programas e não deve ser reorganizada."
    if not Path(p).is_dir():
        return "A pasta não existe."
    if not os.access(p, os.W_OK | os.X_OK):
        return "Não tens permissão para alterar esta pasta."
    return None
