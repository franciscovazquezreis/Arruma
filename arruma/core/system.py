"""Diferenças entre Linux, Windows e macOS: pastas pessoais, pastas do sistema, ficheiros ocultos,
pastas de configuração e localização de programas auxiliares (Ollama, pdftotext, Tesseract)."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = not IS_WINDOWS and not IS_MAC

HOME = Path.home()

# Nome do Lixo em cada sistema, com as contrações certas (o Lixo / a Reciclagem).
if IS_WINDOWS:
    TRASH_NAME, TRASH_TO, TRASH_IN, TRASH_FROM = "Reciclagem", "para a Reciclagem", "na Reciclagem", "da Reciclagem"
    FILE_MANAGER = "Explorador de Ficheiros"
else:
    TRASH_NAME, TRASH_TO, TRASH_IN, TRASH_FROM = "Lixo", "para o Lixo", "no Lixo", "do Lixo"
    FILE_MANAGER = "Finder" if IS_MAC else "gestor de ficheiros"

# Sem janela de consola a piscar no Windows quando se chama um programa auxiliar.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0


# --------------------------------------------------------------------------- pastas pessoais

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

# Nomes com que o Windows e o macOS em português de Portugal mostram estas pastas (no disco
# chamam-se Documents, Downloads…). No Linux mostra-se o nome real, que já vem traduzido.
if IS_WINDOWS:
    DISPLAY_NAMES = {"DESKTOP": "Ambiente de Trabalho", "DOWNLOAD": "Transferências", "DOCUMENTS": "Documentos",
                     "PICTURES": "Imagens", "VIDEOS": "Vídeos", "MUSIC": "Música"}
elif IS_MAC:
    DISPLAY_NAMES = {"DESKTOP": "Secretária", "DOWNLOAD": "Descargas", "DOCUMENTS": "Documentos",
                     "PICTURES": "Imagens", "VIDEOS": "Filmes", "MUSIC": "Música"}
else:
    DISPLAY_NAMES = {}


def _xdg_user_dirs() -> dict[str, Path]:
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


def _mac_user_dirs() -> dict[str, Path]:
    return {"DESKTOP": HOME / "Desktop", "DOWNLOAD": HOME / "Downloads", "DOCUMENTS": HOME / "Documents",
            "MUSIC": HOME / "Music", "PICTURES": HOME / "Pictures", "VIDEOS": HOME / "Movies",
            "TEMPLATES": HOME / "Templates", "PUBLICSHARE": HOME / "Public"}


_KNOWN_FOLDERS = {
    "DESKTOP": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "DOWNLOAD": "374DE290-123F-4565-9164-39C4925E467B",
    "DOCUMENTS": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "MUSIC": "4BD8D571-6D19-48D3-BE97-422220080E43",
    "PICTURES": "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "VIDEOS": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
}


def _windows_user_dirs() -> dict[str, Path]:
    """Pastas conhecidas do Windows (seguem redirecionamentos, por exemplo para o OneDrive)."""
    dirs = {k: HOME / v for k, v in _XDG_DEFAULTS.items()}
    dirs["PUBLICSHARE"] = Path(os.environ.get("PUBLIC") or r"C:\Users\Public")
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]

        get_path = ctypes.windll.shell32.SHGetKnownFolderPath
        get_path.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
                             ctypes.POINTER(ctypes.c_wchar_p)]
        free = ctypes.windll.ole32.CoTaskMemFree
        free.argtypes = [ctypes.c_void_p]
        for key, text in _KNOWN_FOLDERS.items():
            u = uuid.UUID(text)
            guid = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
            out = ctypes.c_wchar_p()
            if get_path(ctypes.byref(guid), 0, None, ctypes.byref(out)) == 0 and out.value:
                dirs[key] = Path(out.value)
            if out:
                free(ctypes.cast(out, ctypes.c_void_p))
    except (OSError, AttributeError, ValueError):
        pass
    return dirs


def user_dirs() -> dict[str, Path]:
    """Pastas pessoais (DESKTOP, DOWNLOAD, DOCUMENTS, MUSIC, PICTURES, VIDEOS, TEMPLATES, PUBLICSHARE)."""
    if IS_WINDOWS:
        return _windows_user_dirs()
    if IS_MAC:
        return _mac_user_dirs()
    return _xdg_user_dirs()


def config_dir() -> Path:
    if IS_WINDOWS:
        base = Path(os.environ.get("APPDATA") or HOME / "AppData" / "Roaming") / "Arruma"
    elif IS_MAC:
        base = HOME / "Library" / "Application Support" / "Arruma"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "arruma"
    base.mkdir(parents=True, exist_ok=True)
    return base


def data_dir() -> Path:
    if IS_WINDOWS or IS_MAC:
        return config_dir()
    base = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local" / "share") / "arruma"
    base.mkdir(parents=True, exist_ok=True)
    return base


# --------------------------------------------------------------------------- pastas protegidas

def system_paths() -> list[str]:
    """Pastas do sistema operativo onde o Arruma nunca mexe."""
    if IS_WINDOWS:
        env = os.environ
        drive = env.get("SystemDrive", "C:")
        paths = [env.get("SystemRoot") or drive + r"\Windows", env.get("ProgramFiles") or drive + r"\Program Files",
                 env.get("ProgramFiles(x86)") or drive + r"\Program Files (x86)", env.get("ProgramW6432", ""),
                 env.get("ProgramData") or drive + r"\ProgramData"]
        paths += [drive + "\\" + n for n in ("$Recycle.Bin", "System Volume Information", "Recovery", "PerfLogs",
                                             "Boot", "Config.Msi", "$WinREAgent", "Intel", "AMD", "NVIDIA")]
        paths += [drive + r"\Users\Default", drive + r"\Users\All Users", drive + r"\Users\Default User"]
        return [p for p in paths if p]
    if IS_MAC:
        return ["/System", "/Library", "/Applications", "/bin", "/sbin", "/usr", "/private", "/etc", "/var",
                "/tmp", "/cores", "/opt", "/dev", "/Network", "/nix"]
    return ["/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64", "/libx32", "/opt", "/proc", "/root",
            "/run", "/sbin", "/snap", "/srv", "/sys", "/tmp", "/usr", "/var", "/lost+found"]


def program_data_dirs() -> list[Path]:
    """Pastas de configuração e dados de programas dentro da pasta pessoal."""
    if IS_WINDOWS:
        dirs = [HOME / "AppData"]
        for var in ("APPDATA", "LOCALAPPDATA"):
            if os.environ.get(var):
                dirs.append(Path(os.environ[var]))
        return dirs
    dirs = [HOME / ".config", HOME / ".local", HOME / ".cache"]
    if IS_MAC:
        dirs.append(HOME / "Library")
    return dirs


def temp_dir() -> str:
    return os.path.realpath(tempfile.gettempdir())


# Nomes de pastas que pertencem ao sistema ou a programas, em cada sistema operativo.
if IS_WINDOWS:
    PROTECTED_NAMES = {
        "AppData": "dados de programas do Windows",
        "Application Data": "dados de programas do Windows",
        "Local Settings": "dados de programas do Windows",
        "Saved Games": "jogos guardados",
        "Searches": "pesquisas guardadas do Windows",
        "Links": "atalhos do Windows",
        "Contacts": "contactos do Windows",
        "Favorites": "favoritos do Windows",
        "3D Objects": "pasta do sistema",
        "Recent": "pasta do sistema",
        "SendTo": "pasta do sistema",
        "Start Menu": "pasta do sistema",
        "My Documents": "atalho do sistema",
        "iCloudDrive": "pasta sincronizada (iCloud)",
        "Google Drive": "pasta sincronizada (Google Drive)",
        "Creative Cloud Files": "pasta sincronizada (Adobe)",
        "$Recycle.Bin": "Reciclagem",
        "System Volume Information": "pasta do sistema",
    }
elif IS_MAC:
    PROTECTED_NAMES = {
        "Library": "biblioteca de programas do macOS",
        "Applications": "aplicações instaladas",
        "Google Drive": "pasta sincronizada (Google Drive)",
        "Creative Cloud Files": "pasta sincronizada (Adobe)",
        "Backups.backupdb": "cópias do Time Machine",
    }
else:
    PROTECTED_NAMES = {}

# Pastas que no macOS são «ficheiros» (aplicações, bibliotecas de fotografias, documentos do
# Pages…): nunca se entra nelas nem se mexe no conteúdo, em nenhum sistema.
PACKAGE_SUFFIXES = (
    ".app", ".photoslibrary", ".photolibrary", ".musiclibrary", ".tvlibrary", ".imovielibrary",
    ".fcpbundle", ".logicx", ".band", ".bundle", ".framework", ".plugin", ".kext", ".pages", ".numbers",
    ".key", ".rtfd", ".sparsebundle", ".xcodeproj", ".xcworkspace", ".playground", ".lrlibrary",
    ".lrdata", ".aplibrary", ".pkg", ".mpkg", ".docarchive", ".lproj",
)


def is_package_dir(name: str) -> bool:
    return name.lower().endswith(PACKAGE_SUFFIXES)


_FILE_ATTRIBUTE_HIDDEN = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 2)
_FILE_ATTRIBUTE_SYSTEM = getattr(stat, "FILE_ATTRIBUTE_SYSTEM", 4)
_FILE_ATTRIBUTE_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_UF_HIDDEN = getattr(stat, "UF_HIDDEN", 0x8000)


def is_hidden_entry(entry: os.DirEntry) -> bool:
    """Ficheiros ocultos: começados por ponto e, no Windows e no macOS, marcados como ocultos."""
    if entry.name.startswith("."):
        return True
    if IS_WINDOWS or IS_MAC:
        try:
            st = entry.stat(follow_symlinks=False)
        except OSError:
            return False
        if IS_WINDOWS:
            return bool(getattr(st, "st_file_attributes", 0) & (_FILE_ATTRIBUTE_HIDDEN | _FILE_ATTRIBUTE_SYSTEM))
        return bool(getattr(st, "st_flags", 0) & _UF_HIDDEN)
    return False


def is_link_entry(entry: os.DirEntry) -> bool:
    """Atalhos simbólicos e, no Windows, junções e outros pontos de reanálise de pastas."""
    if entry.is_symlink():
        return True
    if IS_WINDOWS:
        is_junction = getattr(entry, "is_junction", None)
        if is_junction is not None and is_junction():
            return True
        try:
            if entry.is_dir(follow_symlinks=False):
                return bool(getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
                            & _FILE_ATTRIBUTE_REPARSE_POINT)
        except OSError:
            return False
    return False


# --------------------------------------------------------------------------- todo o computador

def _windows_drives() -> list[str]:
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        mask = kernel32.GetLogicalDrives()
        system_drive = (os.environ.get("SystemDrive") or "C:").upper()
        drives = []
        for i in range(26):
            if not mask & (1 << i):
                continue
            letter = f"{chr(65 + i)}:"
            root = letter + "\\"
            # 2 = removível (pen USB), 3 = disco fixo; ficam de fora rede, CD e discos virtuais
            if letter != system_drive and kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)) in (2, 3):
                drives.append(root)
        return drives
    except (OSError, AttributeError):
        return []


def computer_roots() -> list[str]:
    """Pastas de utilizador e discos montados em todo o computador (sem pastas do sistema)."""
    from .fsutil import is_within

    roots: list[str] = []

    def add(path: Path | str) -> None:
        try:
            rp = os.path.realpath(path)
        except OSError:
            return
        if not os.path.isdir(rp) or not os.access(rp, os.R_OK | os.W_OK | os.X_OK):
            return
        if rp == os.path.realpath("/") or any(is_within(rp, r) or is_within(r, rp) for r in roots):
            return
        roots.append(rp)

    add(HOME)
    if IS_WINDOWS:
        for d in _windows_drives():
            add(d)
    elif IS_MAC:
        try:
            for entry in sorted(Path("/Volumes").iterdir()):
                if entry.is_dir() and os.path.realpath(entry) != "/":
                    add(entry)
        except OSError:
            pass
    else:
        try:
            for entry in sorted(Path("/home").iterdir()):
                if entry.is_dir():
                    add(entry)
        except OSError:
            pass
        user = os.environ.get("USER") or HOME.name
        for mb in (Path("/media") / user, Path("/run/media") / user, Path("/media"), Path("/mnt")):
            try:
                for entry in sorted(mb.iterdir()):
                    if entry.is_dir() and entry.name != user:
                        add(entry)
            except OSError:
                continue
    return roots or [os.path.realpath(HOME)]


def is_filesystem_root(path: str) -> bool:
    p = Path(path)
    return p.parent == p


def is_whole_computer_path(path: str) -> bool:
    """«/» no Linux e no macOS; a raiz do disco do sistema (C:\\) no Windows."""
    if not is_filesystem_root(path):
        return False
    if IS_WINDOWS:
        drive = os.path.splitdrive(path)[0].upper()
        return drive == (os.environ.get("SystemDrive") or "C:").upper()
    return True


def is_external_mount(path: str) -> bool:
    if IS_WINDOWS:
        drive = os.path.splitdrive(path)[0].upper()
        return bool(drive) and drive != (os.environ.get("SystemDrive") or "C:").upper()
    if IS_MAC:
        return path.startswith("/Volumes/")
    return path.startswith(("/media/", "/run/media/", "/mnt/"))


# --------------------------------------------------------------------------- programas auxiliares

def _app_dirs() -> list[Path]:
    dirs = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        meipass = Path(getattr(sys, "_MEIPASS", exe_dir))
        dirs += [meipass / "bin", meipass, exe_dir / "bin", exe_dir]
        if IS_MAC:
            dirs.append(exe_dir.parent / "Resources" / "bin")
    return dirs


def _executable_in(dirs: list[Path], exe: str) -> str | None:
    for d in dirs:
        cand = d / exe
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return None


def find_tool(name: str) -> str | None:
    """Procura um programa junto do Arruma, no PATH e nos sítios habituais de cada sistema.

    Os programas que vêm com o Arruma têm prioridade: outro pdftotext no PATH pode ser de
    outra versão ou do Xpdf, com opções diferentes. As aplicações abertas a partir do Finder
    não herdam o PATH do Terminal, por isso no macOS também se procura nas pastas do Homebrew."""
    exe = name + ".exe" if IS_WINDOWS else name
    found = _executable_in(_app_dirs(), exe) or shutil.which(name)
    if found:
        return found
    extra: list[Path] = []
    if IS_MAC:
        extra += [Path("/opt/homebrew/bin"), Path("/usr/local/bin"), Path("/opt/local/bin")]
        if name == "ollama":
            extra.append(Path("/Applications/Ollama.app/Contents/Resources"))
    elif IS_WINDOWS:
        local = Path(os.environ.get("LOCALAPPDATA") or HOME / "AppData" / "Local")
        pf = Path(os.environ.get("ProgramFiles") or r"C:\Program Files")
        pf86 = Path(os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)")
        extra += [local / "Programs" / "Ollama", pf / "Ollama", pf / "Tesseract-OCR", pf86 / "Tesseract-OCR",
                  local / "Programs" / "Tesseract-OCR", local / "Tesseract-OCR"]
    else:
        extra += [Path("/usr/local/bin"), HOME / ".local" / "bin"]
    return _executable_in(extra, exe)


def run_quiet(cmd: list[str], timeout: int) -> str:
    """Corre um programa auxiliar e devolve o que escreveu (vazio se falhar)."""
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False, creationflags=NO_WINDOW)
        return res.stdout.decode("utf-8", "ignore")
    except (OSError, subprocess.TimeoutExpired):
        return ""


def start_detached(cmd: list[str]) -> None:
    """Arranca um programa em segundo plano, independente do Arruma."""
    kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
    if IS_WINDOWS:
        kwargs["creationflags"] = NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0) | \
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)


def ollama_install_steps(model: str) -> tuple[str, str]:
    """Texto e comandos para instalar o Ollama neste sistema."""
    if IS_WINDOWS:
        return ("Descarrega e instala o Ollama para Windows a partir de https://ollama.com/download/windows. "
                "Depois abre o PowerShell e descarrega o modelo (cerca de 2 GB):",
                f"ollama pull {model}")
    if IS_MAC:
        return ("Descarrega a aplicação Ollama para macOS em https://ollama.com/download/mac, arrasta-a para a "
                "pasta Aplicações e abre-a uma vez. Depois, no Terminal, descarrega o modelo (cerca de 2 GB):",
                f"ollama pull {model}")
    return ("Só precisas de internet uma única vez para instalar o Ollama e descarregar o modelo (cerca de 2 GB). "
            "No Terminal:",
            "curl -fsSL https://ollama.com/install.sh | sh\n"
            "sudo systemctl start ollama || (ollama serve >/dev/null 2>&1 & sleep 2)\n"
            f"ollama pull {model}")


def ocr_install_hint() -> str:
    if IS_WINDOWS:
        return "opcional: instala o Tesseract OCR para Windows com o idioma português"
    if IS_MAC:
        return "opcional: brew install tesseract tesseract-lang poppler"
    return "opcional: sudo apt install tesseract-ocr-por"
