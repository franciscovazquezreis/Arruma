"""Extração de texto e metadados de ficheiros, só com ferramentas locais."""

from __future__ import annotations

import html
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from .system import find_tool, run_quiet

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _clean(text: str, limit: int) -> str:
    return _WS.sub(" ", html.unescape(text)).strip()[:limit]


def _xml_text(data: bytes) -> str:
    text = data.decode("utf-8", "ignore")
    text = re.sub(r"</(w:p|text:p|a:p|text:h)>", "\n", text)
    return _TAG.sub(" ", text)


def _zip_text(path: str, members: list[str], limit: int) -> str:
    out = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        for pattern in members:
            for n in sorted(n for n in names if re.fullmatch(pattern, n)):
                with z.open(n) as fh:
                    out.append(_xml_text(fh.read(2_000_000)))
                if sum(map(len, out)) > limit * 3:
                    break
    return _clean(" ".join(out), limit)


def _strings(path: str, limit: int) -> str:
    """Texto legível em formatos binários antigos (.doc, .xls, .ppt)."""
    with open(path, "rb") as fh:
        data = fh.read(3_000_000)
    utf16 = re.findall(rb"(?:[\x20-\x7e\xc0-\xff]\x00){5,}", data)
    parts = [p.decode("utf-16-le", "ignore") for p in utf16]
    if sum(map(len, parts)) < 200:
        parts += [p.decode("latin-1") for p in re.findall(rb"[\x20-\x7e\xc0-\xff]{5,}", data)]
    return _clean(" ".join(parts), limit)


def _ocr_pdf(path: str, limit: int) -> str:
    tesseract, pdftoppm = find_tool("tesseract"), find_tool("pdftoppm")
    if not (tesseract and pdftoppm):
        return ""
    with tempfile.TemporaryDirectory(prefix="arruma-ocr-") as tmp:
        base = str(Path(tmp) / "p")
        run_quiet([pdftoppm, "-f", "1", "-l", "1", "-r", "150", "-png", path, base], 60)
        pngs = sorted(Path(tmp).glob("p*.png"))
        if not pngs:
            return ""
        for lang in ("por+eng", "eng"):
            text = run_quiet([tesseract, str(pngs[0]), "-", "-l", lang], 90)
            if text.strip():
                return _clean(text, limit)
    return ""


def has_ocr() -> bool:
    return bool(find_tool("tesseract") and find_tool("pdftoppm"))


def _pdf_text(path: str, limit: int) -> str:
    """Texto das duas primeiras páginas: pdftotext (Poppler) ou, se faltar, a biblioteca pypdf."""
    pdftotext = find_tool("pdftotext")
    if pdftotext:
        return _clean(run_quiet([pdftotext, "-l", "2", "-q", "-enc", "UTF-8", path, "-"], 20), limit)
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        return _clean(" ".join((page.extract_text() or "") for page in reader.pages[:2]), limit)
    except Exception:  # pypdf não instalado ou PDF estranho/cifrado
        return ""


def extract_text(path: str, ext: str, limit: int = 2000) -> str:
    """Primeiros caracteres de texto do documento (vazio se não for possível)."""
    try:
        if ext == "pdf":
            text = _pdf_text(path, limit)
            if len(text) < 40:
                text = _ocr_pdf(path, limit) or text
            return text
        if ext == "docx":
            return _zip_text(path, [r"word/document\.xml"], limit)
        if ext == "xlsx":
            return _zip_text(path, [r"xl/sharedStrings\.xml"], limit)
        if ext == "pptx":
            return _zip_text(path, [r"ppt/slides/slide\d+\.xml"], limit)
        if ext in ("odt", "ods", "odp"):
            return _zip_text(path, [r"content\.xml"], limit)
        if ext in ("txt", "md", "csv", "tex", "eml"):
            with open(path, "rb") as fh:
                raw = fh.read(limit * 4)
            try:
                return _clean(raw.decode("utf-8"), limit)
            except UnicodeDecodeError:
                return _clean(raw.decode("latin-1"), limit)
        if ext == "rtf":
            with open(path, "rb") as fh:
                raw = fh.read(200_000).decode("latin-1", "ignore")
            raw = re.sub(r"\\'([0-9a-f]{2})", lambda m: bytes.fromhex(m.group(1)).decode("cp1252", "ignore"), raw)
            raw = re.sub(r"\\[a-z]+-?\d* ?|[{}]", " ", raw)
            return _clean(raw, limit)
        if ext in ("doc", "xls", "ppt"):
            return _strings(path, limit)
        if ext in ("html", "htm", "xml"):
            with open(path, "rb") as fh:
                raw = fh.read(limit * 20)
            try:
                markup = raw.decode("utf-8")
            except UnicodeDecodeError:
                markup = raw.decode("latin-1")
            markup = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", markup)
            return _clean(_TAG.sub(" ", markup), limit)
    except (OSError, zipfile.BadZipFile, KeyError, ValueError, RuntimeError):
        return ""
    return ""


# --------------------------------------------------------------------------- datas

_DATE_PATTERNS = [
    re.compile(r"(?<!\d)((?:19|20)\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])(?!\d)"),
    re.compile(r"(?<!\d)(0[1-9]|[12]\d|3[01])[-_.](0[1-9]|1[0-2])[-_.]((?:19|20)\d{2})(?!\d)"),
]


def date_from_name(name: str) -> datetime | None:
    m = _DATE_PATTERNS[0].search(name)
    try:
        if m:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = _DATE_PATTERNS[1].search(name)
        if m:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None
    return None


def plausible(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.year < 1990 or dt.year > datetime.now().year + 1:
        return None
    return dt


# --------------------------------------------------------------------------- imagens e áudio

def image_info(path: str) -> dict:
    info: dict = {}
    try:
        from PIL import Image
        with Image.open(path) as img:
            info["width"], info["height"] = img.size
            exif = img.getexif()
            if not exif:
                return info
            make = str(exif.get(271, "") or "").strip("\x00 ")
            model = str(exif.get(272, "") or "").strip("\x00 ")
            if make or model:
                info["camera"] = model if make and make.split()[0].lower() in model.lower() else f"{make} {model}".strip()
            sub = exif.get_ifd(0x8769)
            raw = sub.get(36867) or sub.get(36868) or exif.get(306)
            if raw:
                try:
                    info["date"] = plausible(datetime.strptime(str(raw).strip("\x00 ")[:19], "%Y:%m:%d %H:%M:%S"))
                except ValueError:
                    pass
            if exif.get_ifd(0x8825):
                info["gps"] = True
    except Exception:  # Pillow pode lançar vários tipos de erro com ficheiros estranhos
        pass
    return info


def fix_mojibake(text: str) -> str:
    """Corrige etiquetas UTF-8 lidas como Latin-1 («JosÃ© Afonso» → «José Afonso»)."""
    if "Ã" in text or "Â" in text:
        try:
            return text.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return text


def audio_tags(path: str) -> dict:
    try:
        import mutagen
        f = mutagen.File(path, easy=True)
        if not f or not f.tags:
            return {}

        def first(key: str) -> str:
            v = f.tags.get(key)
            return fix_mojibake(str(v[0]).strip()) if v else ""
        return {
            "albumartist": first("albumartist"),
            "artist": first("artist"),
            "album": first("album"),
            "title": first("title"),
            "year": first("date")[:4],
            "duration": getattr(f.info, "length", 0) or 0,
        }
    except Exception:
        return {}
