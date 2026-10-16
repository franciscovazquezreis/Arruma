"""Enviar para o Lixo (Reciclagem no Windows) e recuperar de lá, em cada sistema operativo.

send_to_trash() devolve, quando o sistema o diz, onde o ficheiro ficou no Lixo; esse caminho é
guardado no histórico e ajuda a anular a operação mais tarde."""

from __future__ import annotations

import os
from pathlib import Path

from .system import IS_MAC, IS_WINDOWS, TRASH_FROM, TRASH_IN


def send_to_trash(path: str) -> str | None:
    if IS_WINDOWS:
        return _win_trash(path)
    if IS_MAC:
        return _mac_trash(path)
    return _gio_trash(path)


def restore(orig: str, trashed: str | None = None) -> None:
    """Devolve ao local original um ficheiro enviado para o Lixo pelo Arruma."""
    if os.path.lexists(orig):
        raise FileExistsError("Já existe um ficheiro no local original.")
    if IS_WINDOWS:
        _win_restore(orig)
    elif IS_MAC:
        _mac_restore(orig, trashed)
    else:
        _gio_restore(orig)


# --------------------------------------------------------------------------- Linux (GIO)

def _gio_trash(path: str) -> str | None:
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio
    Gio.File.new_for_path(path).trash(None)
    return None


def _mount_point(path: str) -> str:
    p = os.path.realpath(os.path.dirname(path))
    while not os.path.ismount(p) and os.path.dirname(p) != p:
        p = os.path.dirname(p)
    return p


def _freedesktop_find(orig: str) -> tuple[Path, Path] | None:
    """Procura no Lixo segundo a norma freedesktop (a que o GIO e o Nemo usam), sem precisar do GVFS.
    Devolve (ficheiro no Lixo, .trashinfo) da remoção mais recente."""
    from urllib.parse import unquote
    home_trash = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "Trash"
    top = _mount_point(orig)
    uid = str(os.getuid()) if hasattr(os, "getuid") else ""
    places = [(home_trash, None), (Path(top) / f".Trash-{uid}", top), (Path(top) / ".Trash" / uid, top)]
    best: tuple[str, Path, Path] | None = None
    for trash_dir, base in places:
        try:
            infos = list((trash_dir / "info").glob("*.trashinfo"))
        except OSError:
            continue
        for info in infos:
            try:
                lines = info.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            fields = dict(line.split("=", 1) for line in lines if "=" in line)
            path = unquote(fields.get("Path", ""))
            if base and path and not path.startswith("/"):
                path = os.path.join(base, path)
            if path == orig:
                date = fields.get("DeletionDate", "")
                stored = trash_dir / "files" / info.name[:-len(".trashinfo")]
                if os.path.lexists(stored) and (best is None or date > best[0]):
                    best = (date, stored, info)
    return (best[1], best[2]) if best else None


def _gio_restore(orig: str) -> None:
    found = _freedesktop_find(orig)
    if found is not None:
        stored, info = found
        os.makedirs(os.path.dirname(orig), exist_ok=True)
        os.rename(stored, orig)
        try:
            info.unlink()
        except OSError:
            pass
        return
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
        raise FileNotFoundError(f"O ficheiro já não está {TRASH_IN}.")
    os.makedirs(os.path.dirname(orig), exist_ok=True)
    root.get_child(best[1]).move(Gio.File.new_for_path(orig), Gio.FileCopyFlags.NONE, None, None)


# --------------------------------------------------------------------------- Windows

def _win_trash(path: str) -> str | None:
    import ctypes
    from ctypes import wintypes

    drive = os.path.splitdrive(os.path.abspath(path))[0]
    # Pens USB e unidades de rede não têm Reciclagem: o Windows apagaria de vez. Não arriscar.
    if ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(drive + "\\")) != 3:
        raise OSError("Esta unidade não tem Reciclagem; o ficheiro não foi apagado.")

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    op = SHFILEOPSTRUCTW(None, FO_DELETE, os.path.abspath(path) + "\0", None,
                         FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI, False, None, None)
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if code or op.fAnyOperationsAborted or os.path.lexists(path):
        raise OSError(f"Não foi possível enviar para a Reciclagem (código {code}).")
    return None


def _current_user_sid() -> str | None:
    try:
        import ctypes
        from ctypes import wintypes
        advapi32, kernel32 = ctypes.windll.advapi32, ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                                 ctypes.POINTER(wintypes.DWORD)]
        advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
            return None
        try:
            size = wintypes.DWORD()
            advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # 1 = TokenUser
            buf = ctypes.create_string_buffer(size.value)
            if not advapi32.GetTokenInformation(token, 1, buf, size, ctypes.byref(size)):
                return None
            sid_ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
            text = wintypes.LPWSTR()
            if not advapi32.ConvertSidToStringSidW(sid_ptr, ctypes.byref(text)):
                return None
            sid = text.value
            kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
            return sid
        finally:
            kernel32.CloseHandle(token)
    except (OSError, AttributeError):
        return None


def parse_recycle_index(data: bytes) -> tuple[str | None, int]:
    """Lê um ficheiro $I da Reciclagem: (caminho original, data de remoção em FILETIME)."""
    if len(data) < 24:
        return None, 0
    version = int.from_bytes(data[0:8], "little")
    deleted = int.from_bytes(data[16:24], "little")
    if version == 1:
        raw = data[24:24 + 520]
    elif version == 2 and len(data) >= 28:
        n = int.from_bytes(data[24:28], "little")
        raw = data[28:28 + 2 * n]
    else:
        return None, 0
    path = raw.decode("utf-16-le", "ignore").split("\0", 1)[0]
    return (path or None), deleted


def find_in_recycle_bin(orig: str, bin_root: Path) -> tuple[Path, Path] | None:
    """Procura na Reciclagem (pasta $Recycle.Bin) o ficheiro removido de «orig» mais recente."""
    candidates = []
    sid = _current_user_sid() if IS_WINDOWS else None
    if sid:
        candidates.append(bin_root / sid)
    try:
        candidates += [p for p in bin_root.iterdir() if p.is_dir() and p not in candidates]
    except OSError:
        pass
    # O Windows guarda o caminho com os nomes longos (C:\Users\Ana…), nunca a forma curta 8.3 (ANA~1).
    target = os.path.normcase(os.path.realpath(orig))
    best: tuple[int, Path] | None = None
    for folder in candidates:
        try:
            infos = list(folder.glob("$I*"))
        except OSError:
            continue
        for info in infos:
            try:
                path, deleted = parse_recycle_index(info.read_bytes())
            except OSError:
                continue
            if path and os.path.normcase(os.path.realpath(path)) == target and (best is None or deleted > best[0]):
                best = (deleted, info)
    if best is None:
        return None
    info = best[1]
    return info, info.with_name("$R" + info.name[2:])


def _win_restore(orig: str) -> None:
    drive = os.path.splitdrive(os.path.abspath(orig))[0]
    found = find_in_recycle_bin(orig, Path(drive + "\\") / "$Recycle.Bin")
    if found is None or not os.path.lexists(found[1]):
        raise FileNotFoundError(f"O ficheiro já não está {TRASH_IN}.")
    info, content = found
    os.makedirs(os.path.dirname(orig), exist_ok=True)
    os.rename(content, orig)
    try:
        info.unlink()
    except OSError:
        pass


# --------------------------------------------------------------------------- macOS

def _mac_trash(path: str) -> str | None:
    """Usa NSFileManager (o mesmo mecanismo do Finder) através do runtime de Objective-C."""
    import ctypes
    import ctypes.util
    from ctypes import POINTER, byref, c_bool, c_char_p, c_void_p

    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    ctypes.cdll.LoadLibrary(ctypes.util.find_library("Foundation"))
    objc.objc_getClass.restype = c_void_p
    objc.objc_getClass.argtypes = [c_char_p]
    objc.sel_registerName.restype = c_void_p
    objc.sel_registerName.argtypes = [c_char_p]
    msg_send = ctypes.cast(objc.objc_msgSend, c_void_p).value

    def send(restype, obj, selector: bytes, *args, argtypes=()):
        fn = ctypes.CFUNCTYPE(restype, c_void_p, c_void_p, *argtypes)(msg_send)
        return fn(obj, objc.sel_registerName(selector), *args)

    def cls(name: bytes):
        return objc.objc_getClass(name)

    pool = send(c_void_p, send(c_void_p, cls(b"NSAutoreleasePool"), b"alloc"), b"init")
    try:
        ns_path = send(c_void_p, cls(b"NSString"), b"stringWithUTF8String:", os.path.abspath(path).encode("utf-8"),
                       argtypes=(c_char_p,))
        url = send(c_void_p, cls(b"NSURL"), b"fileURLWithPath:", ns_path, argtypes=(c_void_p,))
        manager = send(c_void_p, cls(b"NSFileManager"), b"defaultManager")
        result, error = c_void_p(), c_void_p()
        ok = send(c_bool, manager, b"trashItemAtURL:resultingItemURL:error:", url, byref(result), byref(error),
                  argtypes=(c_void_p, POINTER(c_void_p), POINTER(c_void_p)))
        if not ok:
            message = "erro desconhecido"
            if error.value:
                desc = send(c_void_p, error, b"localizedDescription")
                if desc:
                    message = send(c_char_p, desc, b"UTF8String").decode("utf-8", "ignore")
            raise OSError(f"Não foi possível enviar para o Lixo: {message}")
        if result.value:
            trashed = send(c_void_p, result, b"path")
            if trashed:
                return send(c_char_p, trashed, b"UTF8String").decode("utf-8")
        return None
    finally:
        send(None, pool, b"drain")


def _mac_restore(orig: str, trashed: str | None) -> None:
    if not trashed or not os.path.lexists(trashed):
        raise FileNotFoundError(f"O ficheiro já não está {TRASH_IN}. Se ainda lá estiver, usa «Pôr de volta» no Finder.")
    os.makedirs(os.path.dirname(orig), exist_ok=True)
    try:
        os.rename(trashed, orig)
    except OSError as e:
        raise OSError(f"O macOS não deixou tirar o ficheiro {TRASH_FROM}. Usa «Pôr de volta» no Finder.") from e
