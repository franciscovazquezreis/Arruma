"""Cliente da IA local (Ollama). Só comunica com servidores neste computador."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from .fsutil import sanitize_name, strip_accents
from .taxonomy import AREAS

PREFERRED_MODELS = ["qwen2.5:3b", "qwen3:4b", "gemma3:4b", "qwen2.5:7b", "llama3.2:3b",
                    "qwen2.5:1.5b", "gemma2:2b", "llama3.1:8b", "mistral:7b"]
RECOMMENDED_MODEL = "qwen2.5:3b"
_NOT_CHAT = ("embed", "minilm", "bge-", "nomic", "snowflake", "all-mpnet", "whisper")


class AIError(Exception):
    pass


@dataclass
class AIStatus:
    ok: bool
    version: str = ""
    models: list[str] = field(default_factory=list)
    model: str = ""
    error: str = ""


def _is_loopback(host: str) -> bool:
    if host in ("localhost", "localhost.localdomain"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        try:
            return all(ipaddress.ip_address(a[4][0]).is_loopback for a in socket.getaddrinfo(host, None))
        except OSError:
            return False


class LocalAI:
    def __init__(self, url: str, model: str = ""):
        parsed = urlparse(url.strip() or "http://127.0.0.1:11434")
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise AIError("Endereço inválido.")
        if not _is_loopback(parsed.hostname):
            raise AIError("Por privacidade, o Arruma só usa uma IA a correr neste computador "
                          "(localhost / 127.0.0.1).")
        self.base = f"{parsed.scheme}://{parsed.netloc}"
        self.model = model

    # ------------------------------------------------------------------ HTTP
    def _request(self, path: str, body: dict | None = None, timeout: float = 5) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={"Content-Type": "application/json"},
                                     method="POST" if body is not None else "GET")
        # Sem proxies: o pedido nunca sai do computador.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:300]
            raise AIError(f"O Ollama respondeu com erro {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, socket.timeout) as e:
            raise AIError("Não foi possível contactar o Ollama. Está instalado e a correr?") from e
        except ValueError as e:
            raise AIError("Resposta inválida do Ollama.") from e

    # ------------------------------------------------------------------ estado
    def _try_autostart(self) -> bool:
        import shutil
        import subprocess
        import time
        binary = shutil.which("ollama") or ("/usr/local/bin/ollama" if Path("/usr/local/bin/ollama").exists() else None)
        if not binary:
            return False
        try:
            subprocess.Popen([binary, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError:
            return False
        for _ in range(12):
            time.sleep(0.4)
            try:
                self._request("/api/version", timeout=1.5)
                return True
            except AIError:
                continue
        return False

    def check(self) -> AIStatus:
        try:
            version = self._request("/api/version").get("version", "")
            tags = self._request("/api/tags").get("models", [])
        except AIError as e:
            if self._try_autostart():
                try:
                    version = self._request("/api/version").get("version", "")
                    tags = self._request("/api/tags").get("models", [])
                except AIError as e2:
                    return AIStatus(ok=False, error=str(e2))
            else:
                return AIStatus(ok=False, error=str(e))
        models = [m.get("name", "") for m in tags if m.get("name")]
        chat_models = [m for m in models if not any(x in m.lower() for x in _NOT_CHAT)]
        model = self.pick_model(chat_models)
        if not model:
            return AIStatus(ok=False, version=version, models=chat_models,
                            error="O Ollama está a correr, mas ainda não tem nenhum modelo instalado. "
                                  f"Executa: ollama pull {RECOMMENDED_MODEL}")
        self.model = model
        return AIStatus(ok=True, version=version, models=chat_models, model=model)

    def pick_model(self, models: list[str]) -> str:
        if self.model and self.model in models:
            return self.model
        for pref in PREFERRED_MODELS:
            for m in models:
                if m == pref or m.split(":")[0] == pref.split(":")[0] and pref in m:
                    return m
        for pref in PREFERRED_MODELS:
            for m in models:
                if m.split(":")[0] == pref.split(":")[0]:
                    return m
        return models[0] if models else ""

    # ------------------------------------------------------------------ classificação
    def classify(self, items: list[dict], timeout: float = 300) -> dict[int, dict]:
        """items: [{"id": int, "nome": str, "pasta": str, "texto": str, "tipo": "documento"|"pasta"}]"""
        if not self.model:
            raise AIError("Nenhum modelo selecionado.")
        areas_txt = "\n".join(
            f"- {a}: {', '.join(subs) if subs else '(sem subáreas)'}" for a, subs in AREAS.items())
        system = (
            "És um arquivista que ajuda uma pessoa em Portugal a organizar os seus ficheiros pessoais.\n"
            "Para cada item (um documento, ou uma pasta descrita pelos nomes dos ficheiros que contém), decide:\n"
            "- \"area\": exatamente UMA das áreas da lista.\n"
            "- \"subarea\": de preferência uma das subáreas sugeridas para essa área; se nenhuma servir, "
            "uma subárea curta (1 a 3 palavras) ou \"\".\n"
            "- \"titulo\": título curto e claro em português de Portugal (3 a 8 palavras) que diga o que é, "
            "incluindo a entidade quando for evidente (ex.: \"Fatura EDP eletricidade\", "
            "\"Análises clínicas Hospital de Santa Maria\", \"Contrato de arrendamento\"). Sem datas, sem extensão.\n"
            "- \"data\": data principal do documento (AAAA-MM-DD ou AAAA-MM) só se aparecer claramente; senão \"\".\n"
            "- \"confianca\": de 0 a 1, quão certo estás da área.\n"
            "Se não houver informação suficiente, usa a área \"Outros\" e confiança baixa.\n\n"
            f"Áreas e subáreas sugeridas:\n{areas_txt}\n\nResponde apenas com JSON."
        )
        payload = {"itens": [{k: v for k, v in it.items() if v} for it in items]}
        schema = {
            "type": "object",
            "properties": {"itens": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "area": {"type": "string", "enum": list(AREAS)},
                    "subarea": {"type": "string"},
                    "titulo": {"type": "string"},
                    "data": {"type": "string"},
                    "confianca": {"type": "number"},
                },
                "required": ["id", "area", "subarea", "titulo", "data", "confianca"],
            }}},
            "required": ["itens"],
        }
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            "stream": False,
            "format": schema,
            "options": {"temperature": 0, "num_ctx": 6144},
            "keep_alive": "15m",
        }
        if re.search(r"qwen3|deepseek-r1|gpt-oss|magistral", self.model):
            body["think"] = False
        try:
            resp = self._request("/api/chat", body, timeout=timeout)
        except AIError as e:
            if "format" in str(e) or "schema" in str(e):  # versões antigas do Ollama
                body["format"] = "json"
                resp = self._request("/api/chat", body, timeout=timeout)
            else:
                raise
        content = (resp.get("message") or {}).get("content", "")
        try:
            data = json.loads(content)
        except ValueError:
            m = re.search(r"\{.*\}", content, re.S)
            if not m:
                raise AIError("A IA devolveu uma resposta que não se consegue ler.")
            data = json.loads(m.group(0))
        out: dict[int, dict] = {}
        for raw in data.get("itens", []) if isinstance(data, dict) else []:
            try:
                out[int(raw.get("id"))] = validate_result(raw)
            except (TypeError, ValueError):
                continue
        return out


def _canon(text: str) -> str:
    return strip_accents(text.lower()).strip()


def validate_result(raw: dict) -> dict:
    area = str(raw.get("area", "")).strip()
    if area not in AREAS:
        match = [a for a in AREAS if _canon(a) == _canon(area)]
        area = match[0] if match else "Outros"
    sub = str(raw.get("subarea", "")).strip()
    canon_subs = {_canon(s): s for s in AREAS[area]}
    if _canon(sub) in canon_subs:
        sub = canon_subs[_canon(sub)]
    elif sub and len(sub) <= 32 and len(sub.split()) <= 4 and _canon(sub) != _canon(area):
        sub = sanitize_name(sub[:1].upper() + sub[1:])
    else:
        sub = ""
    title = str(raw.get("titulo", "")).strip()
    title = re.sub(r"\.(pdf|docx?|odt|xlsx?|txt)$", "", title, flags=re.I)
    title = sanitize_name(title, 70) if title else ""
    if title == "Sem nome":
        title = ""
    date = str(raw.get("data", "")).strip()
    if not re.fullmatch(r"(19|20)\d{2}-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?", date):
        date = ""
    elif int(date[:4]) > datetime.now().year + 1:
        date = ""
    try:
        conf = max(0.0, min(1.0, float(raw.get("confianca", 0.5))))
    except (TypeError, ValueError):
        conf = 0.5
    return {"area": area, "subarea": sub, "titulo": title, "data": date, "confianca": conf}
