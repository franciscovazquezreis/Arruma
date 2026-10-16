"""Categorias, extensões, áreas temáticas e palavras-chave (português de Portugal)."""

from __future__ import annotations

import re

from .fsutil import strip_accents

# --------------------------------------------------------------------------- tipos

DOCUMENT = "documento"
BOOK = "livro"
IMAGE = "imagem"
VIDEO = "video"
AUDIO = "audio"
ARCHIVE = "arquivo"
INSTALLER = "instalador"
CODE = "codigo"
OTHER = "outro"
JUNK = "temporario"

# rótulo, cor (gráficos), ícone
KIND_INFO: dict[str, tuple[str, str, str]] = {
    DOCUMENT: ("Documentos", "#3b82f6", "x-office-document"),
    BOOK: ("Livros", "#6366f1", "x-office-document"),
    IMAGE: ("Imagens", "#22c55e", "image-x-generic"),
    VIDEO: ("Vídeos", "#ef4444", "video-x-generic"),
    AUDIO: ("Música e áudio", "#a855f7", "audio-x-generic"),
    ARCHIVE: ("Arquivos comprimidos", "#f59e0b", "package-x-generic"),
    INSTALLER: ("Instaladores", "#14b8a6", "application-x-executable"),
    CODE: ("Código", "#64748b", "text-x-script"),
    OTHER: ("Outros", "#9ca3af", "text-x-generic"),
    JUNK: ("Temporários", "#78716c", "user-trash"),
}

KIND_ORDER = [DOCUMENT, BOOK, IMAGE, VIDEO, AUDIO, ARCHIVE, INSTALLER, CODE, OTHER, JUNK]

_EXT: dict[str, list[str]] = {
    DOCUMENT: ["pdf", "doc", "docx", "odt", "rtf", "txt", "md", "xls", "xlsx", "ods", "csv",
               "ppt", "pptx", "odp", "pages", "numbers", "key", "tex", "wpd", "xps", "oxps",
               "ics", "vcf", "eml", "msg"],
    BOOK: ["epub", "mobi", "azw", "azw3", "fb2", "djvu", "cbz", "cbr"],
    IMAGE: ["jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "webp", "heic", "heif", "avif",
            "svg", "ico", "psd", "xcf", "kra", "ai", "eps", "raw", "cr2", "cr3", "nef", "arw",
            "dng", "orf", "rw2", "raf"],
    VIDEO: ["mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "mpg", "mpeg", "3gp",
            "mts", "m2ts", "ts", "vob", "ogv"],
    AUDIO: ["mp3", "flac", "ogg", "oga", "opus", "wav", "m4a", "aac", "wma", "aiff", "aif",
            "alac", "amr", "mid", "midi"],
    ARCHIVE: ["zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz", "zst", "lz", "lzma",
              "tar.gz", "tar.bz2", "tar.xz", "tar.zst", "cab"],
    INSTALLER: ["deb", "rpm", "appimage", "run", "flatpak", "flatpakref", "snap", "exe", "msi",
                "dmg", "pkg", "apk", "iso", "img"],
    CODE: ["py", "js", "ts", "jsx", "tsx", "sh", "bash", "c", "h", "cpp", "hpp", "cc", "java",
           "kt", "rs", "go", "rb", "php", "pl", "lua", "r", "swift", "cs", "html", "htm", "css",
           "scss", "json", "yaml", "yml", "toml", "xml", "sql", "ipynb", "ini", "conf", "cfg"],
    JUNK: ["part", "crdownload", "partial", "tmp", "temp", "bak", "old", "swp", "~"],
}

EXT_TO_KIND: dict[str, str] = {}
for _kind, _exts in _EXT.items():
    for _e in _exts:
        EXT_TO_KIND[_e] = _kind

JUNK_NAMES = {"thumbs.db", ".ds_store", "desktop.ini", "ehthumbs.db", ".directory"}

TEXT_EXTRACTABLE = {"pdf", "doc", "docx", "odt", "rtf", "txt", "md", "xls", "xlsx", "ods",
                    "csv", "ppt", "pptx", "odp", "tex", "eml"}

EXIF_EXT = {"jpg", "jpeg", "tif", "tiff", "webp", "png", "heic", "dng", "cr2", "nef", "arw"}
GRAPHIC_EXT = {"svg", "ico", "psd", "xcf", "kra", "ai", "eps"}

FONT_EXT = {"ttf", "otf", "woff", "woff2", "pfb"}
TORRENT_EXT = {"torrent"}


def kind_for(name: str, ext: str) -> str:
    lower = name.lower()
    if lower in JUNK_NAMES or lower.startswith("~$") or lower.endswith("~"):
        return JUNK
    if lower.startswith(".~lock.") and lower.endswith("#"):
        return JUNK
    for double in ("tar.gz", "tar.bz2", "tar.xz", "tar.zst"):
        if lower.endswith("." + double):
            return ARCHIVE
    return EXT_TO_KIND.get(ext, OTHER)


# --------------------------------------------------------------------------- áreas temáticas

AREAS: dict[str, list[str]] = {
    "Finanças": ["Faturas e Recibos", "Banco", "Impostos", "Seguros", "Salários", "Investimentos"],
    "Saúde": ["Exames e Análises", "Receitas", "Consultas"],
    "Casa": ["Contratos e Escrituras", "Condomínio", "Obras e Manutenção", "Eletrodomésticos"],
    "Trabalho": ["Contratos", "Relatórios", "Apresentações", "Reuniões", "Projetos"],
    "Educação": ["Certificados e Diplomas", "Cursos e Formações", "Apontamentos", "Trabalhos"],
    "Pessoal": ["Identificação", "Currículos", "Cartas", "Família"],
    "Jurídico": ["Contratos", "Processos", "Procurações"],
    "Veículos": ["Documentação", "Seguro", "Manutenção"],
    "Viagens": ["Bilhetes e Reservas", "Roteiros"],
    "Compras e Garantias": ["Garantias", "Manuais", "Encomendas"],
    "Livros e Leituras": [],
    "Outros": [],
}

AREA_ICONS = {
    "Finanças": "💶", "Saúde": "🩺", "Casa": "🏠", "Trabalho": "💼", "Educação": "🎓",
    "Pessoal": "🪪", "Jurídico": "⚖️", "Veículos": "🚗", "Viagens": "✈️",
    "Compras e Garantias": "🛒", "Livros e Leituras": "📚", "Outros": "📁",
}

_KEYWORDS: list[tuple[str, str, list[str]]] = [
    ("Finanças", "Faturas e Recibos", ["fatura", "factura", "fatura-recibo", "recibo", "invoice",
                                       "receipt", "total a pagar", "nota de credito", "atcud",
                                       "valor a pagar", "referencia multibanco"]),
    ("Finanças", "Impostos", ["irs", "irc", "imi", "iuc", "autoridade tributaria", "portal das financas",
                              "declaracao de rendimentos", "nota de liquidacao", "modelo 3", "e-fatura",
                              "imposto"]),
    ("Finanças", "Banco", ["extrato", "iban", "saldo disponivel", "movimentos", "bank statement",
                           "cartao de credito", "transferencia bancaria", "credito habitacao",
                           "emprestimo", "comprovativo de transferencia"]),
    ("Finanças", "Seguros", ["apolice", "seguradora", "tomador do seguro", "premio de seguro",
                             "condicoes particulares"]),
    ("Finanças", "Salários", ["recibo de vencimento", "vencimento base", "salario", "payslip",
                              "seguranca social", "remuneracao", "subsidio de ferias"]),
    ("Saúde", "Exames e Análises", ["analises clinicas", "hemograma", "radiografia", "ecografia",
                                    "tac", "ressonancia", "laboratorio", "valores de referencia"]),
    ("Saúde", "Receitas", ["receita medica", "medicamento", "posologia", "farmacia", "dci"]),
    ("Saúde", "Consultas", ["consulta", "hospital", "centro de saude", "medico", "diagnostico",
                            "utente", "sns", "clinica"]),
    ("Casa", "Contratos e Escrituras", ["escritura", "arrendamento", "senhorio", "inquilino",
                                        "caderneta predial", "contrato promessa", "habitacao"]),
    ("Casa", "Condomínio", ["condominio", "assembleia de condominos", "fracao", "administracao do predio"]),
    ("Casa", "Obras e Manutenção", ["orcamento", "remodelacao", "canalizador", "eletricista", "obras"]),
    ("Casa", "Eletrodomésticos", ["frigorifico", "maquina de lavar", "esquentador", "caldeira"]),
    ("Trabalho", "Contratos", ["contrato de trabalho", "entidade empregadora", "periodo experimental",
                               "trabalhador"]),
    ("Trabalho", "Relatórios", ["relatorio", "report", "sumario executivo", "conclusoes"]),
    ("Trabalho", "Apresentações", ["apresentacao", "slides"]),
    ("Trabalho", "Reuniões", ["ata", "ordem de trabalhos", "minutes", "reuniao"]),
    ("Educação", "Certificados e Diplomas", ["certificado", "diploma", "certidao de habilitacoes",
                                             "aproveitamento", "certificate"]),
    ("Educação", "Cursos e Formações", ["formacao", "curso", "modulo", "formando", "workshop", "webinar"]),
    ("Educação", "Apontamentos", ["apontamentos", "resumo", "exercicios", "capitulo", "universidade",
                                  "faculdade", "escola", "aula", "teste de avaliacao"]),
    ("Pessoal", "Identificação", ["cartao de cidadao", "passaporte", "bilhete de identidade",
                                  "certidao de nascimento", "carta de conducao", "titulo de residencia"]),
    ("Pessoal", "Currículos", ["curriculum", "curriculo", "cv", "experiencia profissional",
                               "habilitacoes literarias", "europass", "resume"]),
    ("Pessoal", "Cartas", ["exmo", "exma", "atenciosamente", "cumprimentos"]),
    ("Jurídico", "Processos", ["tribunal", "processo n", "advogado", "notificacao", "citacao", "sentenca"]),
    ("Jurídico", "Procurações", ["procuracao", "procurador"]),
    ("Jurídico", "Contratos", ["clausula", "outorgante", "contraente"]),
    ("Veículos", "Documentação", ["matricula", "documento unico automovel", "dua", "inspecao periodica",
                                  "ipo", "livrete"]),
    ("Veículos", "Seguro", ["carta verde", "seguro automovel", "seguro auto"]),
    ("Veículos", "Manutenção", ["revisao", "oficina", "pneus", "quilometros"]),
    ("Viagens", "Bilhetes e Reservas", ["boarding pass", "cartao de embarque", "reserva", "booking",
                                        "check-in", "voo", "flight", "hotel", "alojamento", "itinerario"]),
    ("Compras e Garantias", "Garantias", ["garantia", "warranty", "talao"]),
    ("Compras e Garantias", "Manuais", ["manual", "instrucoes", "user guide", "guia do utilizador",
                                        "user manual", "quick start"]),
    ("Compras e Garantias", "Encomendas", ["encomenda", "envio", "amazon", "worten", "fnac",
                                           "aliexpress", "tracking"]),
]

_COMPILED = [
    (area, sub, [re.compile(r"\b" + re.escape(k) + r"\b") for k in words])
    for area, sub, words in _KEYWORDS
]


def normalize(text: str) -> str:
    return strip_accents(text.lower())


def keyword_classify(name: str, text: str) -> tuple[str, str, float, list[str]]:
    """Classificação rápida por palavras-chave. Devolve (área, subárea, confiança, pistas)."""
    n_name = normalize(re.sub(r"[_\-\.]+", " ", name))
    n_text = normalize(text[:6000])
    best = ("Outros", "", 0.0, [])
    for area, sub, patterns in _COMPILED:
        score = 0.0
        hits = []
        for pat in patterns:
            in_name = bool(pat.search(n_name))
            count = len(pat.findall(n_text)) if n_text else 0
            if in_name or count:
                hits.append(pat.pattern[2:-2].replace("\\", ""))
            score += 2.5 * in_name + min(count, 4)
        if score > best[2]:
            best = (area, sub, score, hits)
    area, sub, score, hits = best
    if score <= 0:
        return "Outros", "", 0.15, []
    conf = min(0.85, 0.3 + 0.1 * score)
    return area, sub, conf, hits[:4]


MONTHS_PT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
             "setembro", "outubro", "novembro", "dezembro"]
