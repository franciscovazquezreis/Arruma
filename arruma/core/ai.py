# SPDX-License-Identifier: GPL-3.0-or-later
"""Cliente da IA local (Ollama). Só comunica com servidores neste computador.

Modelos pequenos (3 a 4 mil milhões de parâmetros) erram pouco quando a tarefa é fechada e
erram muito quando têm liberdade. Por isso:
- cada pedido leva um único documento (em lotes, os modelos pequenos trocam os resultados);
- a categoria é escolhida de uma lista fixa, imposta pelo esquema JSON (nunca há pastas com
  nomes inventados);
- o título e a data só são aceites se baterem certo com o texto do próprio documento.
"""

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

from . import taxonomy as tx
from .fsutil import sanitize_name, strip_accents
from .system import IS_MAC, find_tool, start_detached

PREFERRED_MODELS = ["qwen2.5:3b", "qwen3:4b", "gemma3:4b", "qwen2.5:7b", "llama3.2:3b",
                    "qwen2.5:1.5b", "gemma2:2b", "llama3.1:8b", "mistral:7b"]
RECOMMENDED_MODEL = "qwen2.5:3b"
PROMPT_VERSION = 2  # muda sempre que o pedido muda, para não reaproveitar respostas antigas
_NOT_CHAT = ("embed", "minilm", "bge-", "nomic", "snowflake", "all-mpnet", "whisper")
TEXT_LIMIT = 1500


class AIError(Exception):
    pass


@dataclass
class AIStatus:
    ok: bool
    version: str = ""
    models: list[str] = field(default_factory=list)
    model: str = ""
    error: str = ""
    running: bool = False  # o Ollama respondeu (mesmo que ainda não tenha nenhum modelo)


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


# --------------------------------------------------------------------------- pedido

def _categories_text() -> str:
    lines = []
    for area, desc, subs in tx.TAXONOMY:
        for sub, sub_desc in subs:
            lines.append(f"- {tx.category_label(area, sub)}: {sub_desc}")
        if subs:
            lines.append(f"- {area}: outros documentos de {desc} que não encaixam acima")
        else:
            lines.append(f"- {area}: {desc}")
    return "\n".join(lines)


SYSTEM_PROMPT = (
    "És um arquivista que ajuda uma pessoa em Portugal a arrumar os ficheiros do computador. "
    "Recebes UM documento (ou uma pasta descrita pelos nomes dos ficheiros que contém) e respondes "
    "só com JSON.\n\n"
    "Campos:\n"
    "- \"titulo\": o que é o documento, em 3 a 8 palavras de português de Portugal: tipo de documento, "
    "entidade e assunto. Usa só o que está escrito no texto; nunca inventes nomes de empresas ou pessoas. "
    "Sem datas e sem extensão. Se o texto não deixar claro o que é, escreve \"\".\n"
    "- \"categoria\": exatamente um dos valores da lista abaixo. Decide pelo conteúdo do texto; o nome do "
    "ficheiro é só uma pista. Na dúvida, escolhe \"Outros\": é melhor do que adivinhar.\n"
    "- \"data\": a data de emissão do documento, no formato AAAA-MM-DD (ou AAAA-MM), só se estiver escrita "
    "no texto; caso contrário \"\".\n"
    "- \"confianca\": de 0 a 1, quão certo estás da categoria.\n\n"
    f"Categorias:\n{_categories_text()}"
)

_EXAMPLES = [
    ("Ficheiro: doc_0412.pdf\nPasta: Transferências\nTexto:\nÁguas do Planalto, E.M. Fatura n.º FA 2024/00871 "
     "Data de emissão: 15-01-2024 Consumo de água: 12 m3 Total a pagar: 21,40 EUR",
     {"titulo": "Fatura Águas do Planalto consumo de água", "categoria": "Finanças › Faturas e Recibos",
      "data": "2024-01-15", "confianca": 0.95}),
    ("Ficheiro: manual.pdf\nPasta: Transferências\nTexto:\nManual de acolhimento do colaborador. Bem-vindo à "
     "Metalúrgica Vale do Sorraia. Horários, férias, regras de segurança no posto de trabalho e contactos "
     "dos recursos humanos.",
     {"titulo": "Manual de acolhimento Metalúrgica Vale do Sorraia", "categoria": "Trabalho",
      "data": "", "confianca": 0.8}),
    ("Ficheiro: IMG_3301.pdf\nPasta: Transferências\nTexto:\n(sem texto legível)",
     {"titulo": "", "categoria": "Outros", "data": "", "confianca": 0.1}),
]

_SCHEMA = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string"},
        "categoria": {"type": "string", "enum": tx.CATEGORY_LABELS},
        "data": {"type": "string"},
        "confianca": {"type": "number"},
    },
    "required": ["titulo", "categoria", "data", "confianca"],
}


def user_message(item: dict) -> str:
    if item.get("tipo") == "pasta":
        return (f"Pasta: {item.get('nome', '')}\nDentro de: {item.get('pasta', '')}\n"
                f"Ficheiros que contém: {item.get('texto', '')}")
    text = (item.get("texto") or "").strip()[:TEXT_LIMIT] or "(sem texto legível)"
    return f"Ficheiro: {item.get('nome', '')}\nPasta: {item.get('pasta', '')}\nTexto:\n{text}"


def build_messages(item: dict) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for question, answer in _EXAMPLES:
        messages.append({"role": "user", "content": question})
        messages.append({"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)})
    messages.append({"role": "user", "content": user_message(item)})
    return messages


# --------------------------------------------------------------------------- cliente

class LocalAI:
    def __init__(self, url: str, model: str = ""):
        from urllib.parse import urlparse
        parsed = urlparse(url.strip() or "http://127.0.0.1:11434")
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise AIError("Endereço inválido.")
        if not _is_loopback(parsed.hostname):
            raise AIError("Por privacidade, o Arruma só usa uma IA a correr neste computador "
                          "(localhost / 127.0.0.1).")
        self.base = f"{parsed.scheme}://{parsed.netloc}"
        self.model = model
        self._json_only = False  # versões antigas do Ollama não aceitam esquemas JSON

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
        import time
        app = Path("/Applications/Ollama.app")
        try:
            if IS_MAC and app.exists():
                start_detached(["open", "-g", "-a", str(app)])  # a aplicação arranca o servidor
            else:
                binary = find_tool("ollama")
                if not binary:
                    return False
                start_detached([binary, "serve"])
        except OSError:
            return False
        for _ in range(20):
            time.sleep(0.4)
            try:
                self._request("/api/version", timeout=1.5)
                return True
            except AIError:
                continue
        return False

    def check(self, autostart: bool = True) -> AIStatus:
        """Estado do Ollama. Se estiver parado, tenta arrancá-lo, exceto com «autostart» falso: com a IA
        desligada nas Definições, o Arruma só vê o estado e não arranca o Ollama."""
        try:
            version = self._request("/api/version").get("version", "")
            tags = self._request("/api/tags").get("models", [])
        except AIError as e:
            if autostart and self._try_autostart():
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
            return AIStatus(ok=False, version=version, models=chat_models, running=True,
                            error="O Ollama está a correr, mas ainda não tem nenhum modelo instalado. "
                                  f"Executa: ollama pull {RECOMMENDED_MODEL}")
        self.model = model
        return AIStatus(ok=True, version=version, models=chat_models, model=model, running=True)

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
    def classify_item(self, item: dict, timeout: float = 180) -> dict:
        """item: {"nome", "pasta", "texto", "tipo": "documento" | "pasta"}. Devolve o resultado validado."""
        if not self.model:
            raise AIError("Nenhum modelo selecionado.")
        body = {
            "model": self.model,
            "messages": build_messages(item),
            "stream": False,
            "format": "json" if self._json_only else _SCHEMA,
            "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 160},
            "keep_alive": "15m",
        }
        if re.search(r"qwen3|deepseek-r1|gpt-oss|magistral", self.model):
            body["think"] = False
        try:
            resp = self._request("/api/chat", body, timeout=timeout)
        except AIError as e:
            if not self._json_only and ("format" in str(e) or "schema" in str(e)):
                self._json_only = True
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
            try:
                data = json.loads(m.group(0))
            except ValueError as e:
                raise AIError("A IA devolveu uma resposta que não se consegue ler.") from e
        if not isinstance(data, dict):
            raise AIError("A IA devolveu uma resposta que não se consegue ler.")
        if item.get("tipo") == "pasta":
            return validate_result(data)
        return validate_result(data, item.get("texto", ""), f"{item.get('nome', '')} {item.get('pasta', '')}")

    def classify(self, items: list[dict], timeout: float = 180) -> dict[int, dict]:
        """Compatibilidade: classifica vários itens, um pedido de cada vez."""
        return {int(it["id"]): self.classify_item(it, timeout) for it in items}


# --------------------------------------------------------------------------- validação

def _canon(text: str) -> str:
    return strip_accents(str(text).lower()).strip()


_MONTHS = {_canon(m) for m in tx.MONTHS_PT}
_ACRONYMS = {"irs", "irc", "iva", "imi", "iuc", "imt", "sns", "cv", "nif", "iban", "ufcd", "iefp",
             "pdf", "ipo", "dua", "ppr", "cpe", "atcud"}
_DOC_WORDS = {
    "fatura", "faturas", "recibo", "recibos", "contrato", "relatorio", "certificado", "declaracao",
    "extrato", "manual", "ata", "carta", "proposta", "orcamento", "receita", "analises", "exame",
    "exames", "consulta", "seguro", "apolice", "bilhete", "reserva", "cartao", "curriculo", "procuracao",
    "citacao", "notificacao", "garantia", "encomenda", "livro", "apresentacao", "apontamentos",
    "comprovativo", "nota", "notas", "plano", "pedido", "aviso", "guia", "ficha", "inspecao",
    "confirmacao", "convocatoria", "reuniao", "diploma", "liquidacao", "demonstracao", "documento",
}
for _area, _desc, _subs in tx.TAXONOMY:
    for _w in re.findall(r"\w+", _canon(_area + " " + " ".join(s for s, _ in _subs))):
        _DOC_WORDS.add(_w)
_GENERIC_TITLE = {"documento", "documentos", "ficheiro", "arquivo", "pdf", "texto", "scan",
                  "digitalizacao", "digitalizado", "imagem", "sem", "titulo", "desconhecido",
                  "untitled", "outro", "outros", "nome", "dados", "informacao", "geral", "diversos",
                  "varios", "pagina", "copia", "legivel", "conteudo", "de", "do", "da", "dos", "das"}


def clean_title(raw, text: str = "", source: str = "") -> str:
    """Título curto e seguro para nome de ficheiro, ou "" se for vago ou não bater com o texto."""
    title = str(raw or "").strip().strip("\"'«»“”")
    title = re.sub(r"\.(pdf|docx?|odt|xlsx?|pptx?|txt|eml|jpe?g|png)$", "", title, flags=re.I)
    title = re.sub(r"\b\d{4}-\d{2}(-\d{2})?\b|\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b", " ", title)
    title = re.sub(r"\s+", " ", title).strip(" -_,.;:")
    words = re.findall(r"\w+", title)
    if len(words) < 2 or len(words) > 12:
        return ""
    if all(_canon(w) in _GENERIC_TITLE or len(w) <= 2 or w.isdigit() for w in words):
        return ""
    if text or source:
        # Nomes próprios (palavras com maiúscula a meio do título) têm de existir no documento:
        # é assim que se apanham empresas ou pessoas inventadas pela IA.
        hay = _canon(f"{text} {source}")
        hay_compact = re.sub(r"\W+", "", hay)
        for i, w in enumerate(words):
            cw = _canon(w)
            if i == 0 or len(w) < 3 or not w[0].isupper():
                continue
            if cw in _ACRONYMS or cw in _DOC_WORDS or cw in _MONTHS:
                continue
            if cw not in hay and cw not in hay_compact:
                return ""
    letters = [c for c in title if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.6:
        title = " ".join(w if len(w) <= 4 else w.capitalize() for w in title.split())
    # Palavras comuns copiadas em maiúsculas de um cabeçalho («ATA», «FATURA») ficam normais.
    title = " ".join(w.lower() if w.isupper() and len(w) > 1 and _canon(w) in _DOC_WORDS else w
                     for w in title.split())
    title = title[0].upper() + title[1:]
    title = sanitize_name(title, 70)
    return "" if title == "Sem nome" else title


_MONTH_WORDS = [
    (_canon(name), _canon(name)[:3]) for name in tx.MONTHS_PT
]


def _date_in_text(text: str, year: int, month: int, day: int | None) -> str:
    """Até onde a data está escrita no texto: "dia", "mes" ou ""."""
    t = _canon(text)
    y, m = f"{year:04d}", f"{month:02d}"
    name, short = _MONTH_WORDS[month - 1]
    months = rf"(?:0?{month}|{name}|{short}\.?)"
    if day is not None:
        d = rf"0?{day}"
        if re.search(rf"{y}[-/.]{m}[-/.]{day:02d}(?!\d)", t) or \
                re.search(rf"(?<!\d){d}[-/. ]+(?:de\s+)?{months}[-/. ]+(?:de\s+)?{y}(?!\d)", t):
            return "dia"
    if re.search(rf"{y}[-/.]{m}(?!\d)", t) or re.search(rf"(?<!\d){months}[-/. ]+(?:de\s+)?{y}(?!\d)", t):
        return "mes"
    return ""


def clean_date(raw, text: str = "", source: str = "") -> str:
    """Data AAAA-MM-DD ou AAAA-MM plausível e escrita no documento; senão "".

    Se o texto só tiver o mês («janeiro de 2025»), fica AAAA-MM: o dia não se inventa."""
    date = str(raw or "").strip()
    m = re.fullmatch(r"((?:19|20)\d{2})-(0[1-9]|1[0-2])(?:-(0[1-9]|[12]\d|3[01]))?", date)
    if not m:
        return ""
    year, month = int(m.group(1)), int(m.group(2))
    day = int(m.group(3)) if m.group(3) else None
    try:
        datetime(year, month, day or 1)
    except ValueError:
        return ""
    if year < 1990 or year > datetime.now().year + 1:
        return ""
    if not (text or source):
        return date
    found = _date_in_text(f"{text} {source}", year, month, day)
    if found == "dia":
        return date
    if found == "mes":
        return f"{year:04d}-{month:02d}"
    return ""


def validate_result(raw: dict, text: str = "", source: str = "") -> dict:
    """Normaliza a resposta da IA. A área e a subárea saem sempre da taxonomia fixa."""
    if raw.get("categoria"):
        area, sub = tx.parse_category(raw["categoria"])
    else:  # formato antigo: {"area": ..., "subarea": ...}
        area, sub = tx.parse_category(str(raw.get("area", "")))
        if raw.get("subarea") and not sub:
            area, sub = tx.parse_category(tx.category_label(area, str(raw["subarea"])))
    try:
        conf = max(0.0, min(1.0, float(raw.get("confianca", 0.5))))
    except (TypeError, ValueError):
        conf = 0.5
    return {
        "area": area,
        "subarea": sub,
        "titulo": clean_title(raw.get("titulo"), text, source),
        "data": clean_date(raw.get("data"), text, source),
        "confianca": conf,
    }
