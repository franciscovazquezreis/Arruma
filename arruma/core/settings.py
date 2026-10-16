"""Definições do utilizador, guardadas em ~/.config/arruma/definicoes.json."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    path = Path(base) / "arruma"
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    path = Path(base) / "arruma"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Settings:
    # Inteligência artificial local (Ollama)
    use_ai: bool = True
    ollama_url: str = "http://127.0.0.1:11434"
    model: str = ""  # vazio = escolher automaticamente

    # Organização
    photos_by_month: bool = True
    rename_unclear: bool = True
    remove_empty_dirs: bool = True
    clean_junk: bool = True
    include_hidden: bool = False
    excluded: list[str] = field(default_factory=list)

    @classmethod
    def load(cls) -> "Settings":
        path = config_dir() / "definicoes.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> None:
        path = config_dir() / "definicoes.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def copy(self) -> "Settings":
        return Settings(**{**asdict(self), "excluded": list(self.excluded)})
