"""Regras de classificação de cada ficheiro (sem IA) e construção do destino."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime

from . import taxonomy as tx
from .extract import audio_tags, date_from_name, image_info, plausible
from .fsutil import is_unclear_name, sanitize_name, split_ext, strip_accents
from .scanner import FileItem
from .settings import Settings
from .system import TRASH_TO

KIND_BASE = {
    tx.DOCUMENT: "documents", tx.BOOK: "documents", tx.IMAGE: "pictures", tx.VIDEO: "videos",
    tx.AUDIO: "music", tx.ARCHIVE: "archives", tx.INSTALLER: "installers", tx.CODE: "code",
    tx.OTHER: "other",
}

SCREENSHOT_RE = re.compile(r"(screenshot|screen ?shot|captura de ecr[aã]|captura de tela|"
                           r"ecr[aã] de \d|scrot|flameshot|spectacle|gnome-screenshot)", re.I)
SCREENREC_RE = re.compile(r"(screencast|screen ?record|grava[cç][aã]o (de|do) ecr[aã]|kazam|"
                          r"simplescreenrecorder|peek)", re.I)
CAMERA_RE = re.compile(r"^(img|dsc|dscn|dscf|pxl|vid|mvimg|mov|gopr|gh\d\d|dji|sam|wp|photo|foto|"
                       r"p|pano|burst|imag)[_\-]?\d{3,}", re.I)
MESSENGER_RE = re.compile(r"(-wa\d{3,}|whatsapp|telegram|signal-\d)", re.I)
VOICE_RE = re.compile(r"(^ptt-|^aud-|grava[cç][aã]o|recording|voice|nota de voz|memo de voz|^rec_)", re.I)
MOVIE_RE = re.compile(r"(s\d{2}e\d{2}|1080p|720p|2160p|\b4k\b|x264|x265|hevc|bluray|web-?dl|webrip|hdtv)", re.I)


# Etiquetas que os programas põem quando não sabem o artista ou o álbum.
_PLACEHOLDER_TAGS = {
    "unknown", "unknown artist", "unknown album", "artista desconhecido", "album desconhecido",
    "desconhecido", "sem titulo", "untitled", "no artist", "no album", "<unknown>", "[unknown]",
    "track", "faixa", "audiotrack",
}
_VARIOUS = {"various artists", "varios artistas", "various", "va", "compilation", "compilacao"}


def real_tag(value: str, artist: bool = False) -> str:
    """Devolve a etiqueta só se tiver significado (sem «Unknown Artist», «Track 02»…)."""
    v = (value or "").strip()
    canon = strip_accents(v.lower())
    if artist and canon in _VARIOUS:
        return "Vários artistas"
    if not v or canon in _PLACEHOLDER_TAGS or re.fullmatch(r"(track|faixa|pista)\s*\d*", canon):
        return ""
    return v


@dataclass
class Placement:
    base: str
    rel: tuple[str, ...]
    new_name: str | None = None
    reason: str = ""
    confidence: float = 0.9
    source: str = "regras"  # regras | metadados | palavras-chave | IA | manual
    area: str | None = None
    trash: bool = False
    trash_default: bool = True
    optional_levels: int = 0  # últimos níveis de «rel» que só se criam se houver itens suficientes
    month_level: bool = False  # o último nível de «rel» é um mês (fotografias)
    year_level: bool = False   # há um nível de ano (só se cria se algum ano tiver itens suficientes)


def nice_date(dt: datetime, day: bool = True) -> str:
    month = tx.MONTHS_PT[dt.month - 1]
    return f"{dt.day} de {month} de {dt.year}" if day else f"{month} de {dt.year}"


def month_folder(dt: datetime) -> str:
    return f"{dt.year}-{dt.month:02d} {tx.MONTHS_PT[dt.month - 1].capitalize()}"




def junk_placement(item: FileItem) -> Placement:
    lower = item.name.lower()
    age_days = (time.time() - item.mtime) / 86400
    if lower in tx.JUNK_NAMES:
        return Placement("", (), reason="Ficheiro de sistema criado automaticamente (miniaturas/definições "
                         "de pasta). Não faz falta.", trash=True, trash_default=True)
    if lower.startswith("~$") or lower.startswith(".~lock."):
        return Placement("", (), reason="Ficheiro de bloqueio deixado por um editor de documentos.",
                         trash=True, trash_default=age_days > 1)
    if item.ext in ("part", "crdownload", "partial"):
        return Placement("", (), reason=f"Transferência incompleta (parada há {int(age_days)} dias).",
                         trash=True, trash_default=age_days > 2)
    return Placement("", (), reason="Ficheiro temporário ou cópia de segurança automática. "
                     f"Confirma antes de enviar {TRASH_TO}.", trash=True, trash_default=False,
                     confidence=0.5)


def classify_simple(item: FileItem, settings: Settings) -> Placement | None:
    """Classifica tudo o que não precisa de ler o conteúdo. Devolve None para documentos."""
    k = item.kind
    stem, ext = split_ext(item.name)
    ext_label = ext.lower() or "sem extensão"
    mdate = datetime.fromtimestamp(item.mtime)

    if k == tx.JUNK:
        return junk_placement(item)

    if k == tx.DOCUMENT:
        return None

    if k == tx.BOOK:
        return Placement("documents", ("Livros e Leituras",), area="Livros e Leituras",
                         reason=f"Livro digital ({ext_label}).", confidence=0.95)

    if k == tx.IMAGE:
        if SCREENSHOT_RE.search(item.name):
            dt = date_from_name(item.name) or mdate
            return Placement("pictures", ("Capturas de ecrã", str(dt.year)), year_level=True,
                             reason=f"Captura de ecrã de {nice_date(dt, day=False)}.", confidence=0.95)
        if item.ext in tx.GRAPHIC_EXT:
            return Placement("pictures", ("Gráficos e Ilustrações",),
                             reason=f"Ficheiro de design ou ilustração ({ext_label}).", confidence=0.85)
        info = image_info(item.path) if item.ext in tx.EXIF_EXT else {}
        exif_date = info.get("date")
        name_date = plausible(date_from_name(item.name))
        camera_name = bool(CAMERA_RE.match(stem))
        messenger = bool(MESSENGER_RE.search(item.name))
        if info.get("camera") or exif_date or camera_name or messenger:
            dt = exif_date or name_date or mdate
            if exif_date:
                why = "data registada pela câmara"
                source = "metadados"
            elif name_date:
                why = "data no nome do ficheiro"
                source = "regras"
            else:
                why = "data de modificação do ficheiro"
                source = "regras"
            if messenger and not info.get("camera"):
                # Imagens recebidas (memes, fotografias de documentos…) não se misturam com as
                # fotografias tiradas pela pessoa.
                return Placement("pictures", ("Recebidas por mensagem", str(dt.year)), year_level=True,
                                 reason=f"Imagem recebida por mensagem a {nice_date(dt)} ({why}).",
                                 confidence=0.85, source=source)
            cam = f", câmara {info['camera']}" if info.get("camera") else ""
            rel = ("Fotografias", str(dt.year), month_folder(dt)) if settings.photos_by_month \
                else ("Fotografias", str(dt.year))
            return Placement("pictures", rel, reason=f"Fotografia de {nice_date(dt)} ({why}{cam}).",
                             confidence=0.95 if exif_date else 0.8, source=source,
                             month_level=settings.photos_by_month, year_level=True)
        return Placement("pictures", (),
                         reason="Imagem sem dados de câmara (provavelmente transferida ou criada "
                                "num programa).", confidence=0.7)

    if k == tx.VIDEO:
        if SCREENREC_RE.search(item.name):
            return Placement("videos", ("Gravações de ecrã",), reason="Gravação do ecrã.", confidence=0.9)
        if MOVIE_RE.search(item.name) or item.size > 700 * 1024 * 1024 and not CAMERA_RE.match(stem):
            return Placement("videos", ("Filmes e Séries",),
                             reason="Parece um filme ou episódio de série (nome/tamanho).", confidence=0.75)
        name_date = plausible(date_from_name(item.name))
        if CAMERA_RE.match(stem) or MESSENGER_RE.search(item.name) or name_date:
            dt = name_date or mdate
            return Placement("videos", ("Vídeos pessoais", str(dt.year)), year_level=True,
                             reason=f"Vídeo gravado em {nice_date(dt, day=False)}.", confidence=0.8)
        return Placement("videos", (), reason="Vídeo sem informação de data ou origem.", confidence=0.6)

    if k == tx.AUDIO:
        if VOICE_RE.search(item.name) or item.ext == "amr":
            return Placement("music", ("Gravações de voz",), reason="Gravação de voz ou nota áudio.",
                             confidence=0.85)
        tags = audio_tags(item.path)
        artist = real_tag(tags.get("albumartist", ""), artist=True) or real_tag(tags.get("artist", ""), artist=True)
        album = real_tag(tags.get("album", ""))
        title = real_tag(tags.get("title", ""))
        if artist:
            artist = sanitize_name(artist, 60)
            album = sanitize_name(album, 60) if album else ""
            rel = (artist, album) if album else (artist,)
            new_name = None
            if settings.rename_unclear and title and is_unclear_name(stem):
                new_name = sanitize_name(f"{artist} - {title}") + ext
            desc = f"Música de {artist}" + (f", álbum «{album}»" if album else "")
            return Placement("music", rel, new_name=new_name, reason=f"{desc} (etiquetas do ficheiro).",
                             confidence=0.95, source="metadados", optional_levels=1 if album else 0)
        return Placement("music", (), reason="Áudio sem etiquetas de artista ou álbum.", confidence=0.6)

    if k == tx.ARCHIVE:
        return Placement("archives", (), reason=f"Arquivo comprimido ({ext_label}). Depois de extraído, "
                         "muitas vezes já não é preciso.", confidence=0.95)
    if k == tx.INSTALLER:
        what = "Imagem de disco" if item.ext in ("iso", "img") else "Instalador de programa"
        return Placement("installers", (), reason=f"{what} ({ext_label}).", confidence=0.95)
    if k == tx.CODE:
        return Placement("code", (), reason=f"Ficheiro de código ou configuração ({ext_label}).",
                         confidence=0.8)

    # Outros
    if item.ext in tx.FONT_EXT:
        return Placement("other", ("Tipos de letra",), reason="Tipo de letra (fonte).", confidence=0.9)
    if item.ext in tx.TORRENT_EXT:
        return Placement("other", ("Torrents",), reason="Ficheiro torrent.", confidence=0.9)
    return Placement("other", (), reason=f"Tipo de ficheiro não reconhecido ({ext_label}).", confidence=0.4)


def document_placement(item: FileItem, settings: Settings, area: str, sub: str, conf: float,
                       source: str, reason: str, title: str = "", date: str = "") -> Placement:
    rel = (area, sub) if sub else (area,)
    new_name = None
    stem, ext = split_ext(item.name)
    if settings.rename_unclear and title and is_unclear_name(stem):
        prefix = f"{date} " if date else ""
        new_name = sanitize_name(prefix + title) + ext.lower()
    return Placement("documents", rel, new_name=new_name, reason=reason, confidence=conf,
                     source=source, area=area, optional_levels=1 if sub else 0)
