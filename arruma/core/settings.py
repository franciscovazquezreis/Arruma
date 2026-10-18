# SPDX-License-Identifier: GPL-3.0-or-later
"""Definições do utilizador, guardadas em definicoes.json na pasta de configuração do Arruma
(~/.config/arruma no Linux, %APPDATA%\\Arruma no Windows, ~/Library/Application Support/Arruma no macOS)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields

from .system import config_dir


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
