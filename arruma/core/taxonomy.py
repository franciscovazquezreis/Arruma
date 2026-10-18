# SPDX-License-Identifier: GPL-3.0-or-later
"""Categorias, extensões, áreas temáticas e palavras-chave (português de Portugal)."""

from __future__ import annotations

import re
import sys

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
    ARCHIVE: ("Ficheiros comprimidos", "#f59e0b", "package-x-generic"),
    INSTALLER: ("Instaladores", "#14b8a6", "application-x-executable"),
    CODE: ("Código", "#64748b", "text-x-script"),
    OTHER: ("Outros", "#9ca3af", "text-x-generic"),
    JUNK: ("Temporários", "#78716c", "user-trash"),
}

KIND_ORDER = [DOCUMENT, BOOK, IMAGE, VIDEO, AUDIO, ARCHIVE, INSTALLER, CODE, OTHER, JUNK]

_EXT: dict[str, list[str]] = {
    DOCUMENT: ["pdf", "doc", "docx", "odt", "rtf", "txt", "md", "xls", "xlsx", "ods", "csv",
               "ppt", "pptx", "odp", "pages", "numbers", "key", "tex", "wpd", "xps", "oxps",
               "ics", "vcf", "eml", "msg", "html", "htm", "mhtml", "mht", "xml"],
    BOOK: ["epub", "mobi", "azw", "azw3", "fb2", "djvu", "cbz", "cbr"],
    IMAGE: ["jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "webp", "heic", "heif", "avif",
            "svg", "ico", "psd", "xcf", "kra", "ai", "eps", "raw", "cr2", "cr3", "nef", "arw",
            "dng", "orf", "rw2", "raf"],
    VIDEO: ["mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "mpg", "mpeg", "3gp",
            "mts", "m2ts", "vob", "ogv"],
    AUDIO: ["mp3", "flac", "ogg", "oga", "opus", "wav", "m4a", "aac", "wma", "aiff", "aif",
            "alac", "amr", "mid", "midi"],
    ARCHIVE: ["zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz", "zst", "lz", "lzma",
              "tar.gz", "tar.bz2", "tar.xz", "tar.zst", "cab"],
    INSTALLER: ["deb", "rpm", "appimage", "run", "flatpak", "flatpakref", "snap", "exe", "msi",
                "dmg", "pkg", "apk", "iso", "img"],
    CODE: ["py", "js", "ts", "jsx", "tsx", "sh", "bash", "c", "h", "cpp", "hpp", "cc", "java",
           "kt", "rs", "go", "rb", "php", "pl", "lua", "r", "swift", "cs", "css", "scss", "json",
           "yaml", "yml", "toml", "sql", "ipynb", "ini", "conf", "cfg", "ps1", "bat"],
    JUNK: ["part", "crdownload", "partial", "tmp", "temp", "bak", "old", "swp", "~"],
}

EXT_TO_KIND: dict[str, str] = {}
for _kind, _exts in _EXT.items():
    for _e in _exts:
        EXT_TO_KIND[_e] = _kind

# Ficheiros criados automaticamente pelo sistema. No macOS o Finder recria o .DS_Store logo a
# seguir e no Windows o desktop.ini define o aspeto e o nome traduzido das pastas: aí não se tocam.
JUNK_NAMES = {"thumbs.db", ".ds_store", "desktop.ini", "ehthumbs.db", ".directory"}
if sys.platform == "darwin":
    JUNK_NAMES.discard(".ds_store")
elif sys.platform == "win32":
    JUNK_NAMES.discard("desktop.ini")

TEXT_EXTRACTABLE = {"pdf", "doc", "docx", "odt", "rtf", "txt", "md", "xls", "xlsx", "ods",
                    "csv", "ppt", "pptx", "odp", "tex", "eml", "html", "htm", "xml"}

EXIF_EXT = {"jpg", "jpeg", "tif", "tiff", "webp", "png", "heic", "dng", "cr2", "nef", "arw"}
GRAPHIC_EXT = {"svg", "ico", "psd", "xcf", "kra", "ai", "eps"}

FONT_EXT = {"ttf", "otf", "woff", "woff2", "pfb"}
TORRENT_EXT = {"torrent"}


def kind_for(name: str, ext: str, size: int = 0) -> str:
    lower = name.lower()
    if lower in JUNK_NAMES or lower.startswith("~$") or lower.endswith("~"):
        return JUNK
    if lower.startswith(".~lock.") and lower.endswith("#"):
        return JUNK
    for double in ("tar.gz", "tar.bz2", "tar.xz", "tar.zst"):
        if lower.endswith("." + double):
            return ARCHIVE
    if ext == "ts":  # vídeo MPEG-TS (gravações de televisão) ou código TypeScript
        return VIDEO if size > 1024 * 1024 else CODE
    return EXT_TO_KIND.get(ext, OTHER)


# --------------------------------------------------------------------------- áreas temáticas

# Lista fechada de áreas e subáreas. A IA só pode escolher daqui, por isso as pastas criadas
# têm sempre nomes conhecidos. As descrições orientam a IA nos casos de fronteira.
TAXONOMY: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("Finanças", "dinheiro, contas, impostos e seguros", [
        ("Faturas e Recibos", "faturas, recibos, talões e contas de eletricidade, água, gás ou telecomunicações"),
        ("Banco", "extratos, cartões, transferências, empréstimos e cartas do banco"),
        ("Impostos", "IRS, IMI, IUC, IVA, Autoridade Tributária e Segurança Social"),
        ("Seguros", "apólices e sinistros de seguros de saúde, casa ou vida (o seguro do carro vai para Veículos)"),
        ("Salários", "recibos de vencimento e declarações da entidade patronal"),
        ("Investimentos", "fundos, ações, certificados de aforro e PPR"),
    ]),
    ("Saúde", "saúde e medicina", [
        ("Exames e Análises", "análises clínicas, radiografias, ecografias e outros exames"),
        ("Receitas médicas", "receitas e guias de tratamento com medicamentos"),
        ("Consultas e Relatórios", "relatórios médicos, consultas, atestados e baixas"),
    ]),
    ("Casa", "habitação", [
        ("Escrituras e Arrendamento", "escrituras, contratos de arrendamento, caderneta predial e licenças"),
        ("Condomínio", "atas, quotas e comunicações do condomínio"),
        ("Obras e Manutenção", "orçamentos, obras e reparações na casa"),
    ]),
    ("Trabalho", "vida profissional", [
        ("Contratos e Propostas", "contratos de trabalho ou de prestação de serviços e propostas a clientes"),
        ("Projetos", "planos, requisitos, documentação e acompanhamento de projetos"),
        ("Reuniões", "atas, notas e convocatórias de reuniões de trabalho"),
        ("Relatórios", "relatórios de atividade, análises e estudos"),
        ("Apresentações", "diapositivos e apresentações"),
    ]),
    ("Educação", "estudos e formação", [
        ("Certificados e Diplomas", "certificados, diplomas e certidões de habilitações"),
        ("Cursos e Formações", "materiais, manuais do formando e planos de cursos e formações"),
        ("Apontamentos", "apontamentos, resumos, fichas e exercícios de estudo"),
        ("Trabalhos académicos", "teses, dissertações e trabalhos escolares"),
    ]),
    ("Pessoal", "identificação e vida pessoal", [
        ("Identificação", "cartão de cidadão, passaporte, carta de condução e certidões"),
        ("Currículos", "currículos, cartas de apresentação e candidaturas a empregos"),
        ("Cartas e Correspondência", "cartas e comunicações pessoais"),
    ]),
    ("Jurídico", "assuntos legais", [
        ("Processos e Tribunal", "tribunais, citações, notificações judiciais e advogados"),
        ("Procurações e Notariado", "procurações, atos notariais, testamentos e heranças"),
        ("Contratos e Acordos", "outros contratos e acordos entre partes"),
    ]),
    ("Veículos", "automóveis e outros veículos", [
        ("Documentação e Inspeções", "documento único automóvel, registo e inspeções periódicas"),
        ("Seguro automóvel", "apólices e cartas verdes do seguro automóvel"),
        ("Manutenção e Reparações", "revisões, oficina e pneus"),
    ]),
    ("Viagens", "viagens e férias", [
        ("Bilhetes e Reservas", "bilhetes, cartões de embarque e reservas de alojamento"),
        ("Roteiros", "roteiros, guias e planeamento de viagens"),
    ]),
    ("Compras e Garantias", "compras e equipamentos", [
        ("Garantias", "certificados de garantia e comprovativos de compra de equipamentos"),
        ("Manuais de instruções", "manuais de instruções de aparelhos e equipamentos"),
        ("Encomendas", "confirmações e envios de encomendas"),
    ]),
    ("Livros e Leituras", "livros, revistas e artigos para ler", []),
    ("Lazer", "culinária, desporto, passatempos e espetáculos", []),
    ("Outros", "tudo o que não encaixa claramente nas outras áreas", []),
]

AREAS: dict[str, list[str]] = {area: [s for s, _ in subs] for area, _, subs in TAXONOMY}
AREA_DESCRIPTIONS: dict[str, str] = {area: desc for area, desc, _ in TAXONOMY}
SUB_DESCRIPTIONS: dict[tuple[str, str], str] = {
    (area, s): d for area, _, subs in TAXONOMY for s, d in subs}

AREA_ICONS = {
    "Finanças": "💶", "Saúde": "🩺", "Casa": "🏠", "Trabalho": "💼", "Educação": "🎓",
    "Pessoal": "🪪", "Jurídico": "⚖️", "Veículos": "🚗", "Viagens": "✈️",
    "Compras e Garantias": "🛒", "Livros e Leituras": "📚", "Lazer": "🎨", "Outros": "📁",
}

CATEGORY_SEP = " › "


def category_label(area: str, sub: str = "") -> str:
    return f"{area}{CATEGORY_SEP}{sub}" if sub else area


# Rótulos que a IA pode escolher: cada subárea e também cada área sozinha (para documentos da
# área que não encaixam em nenhuma subárea).
CATEGORY_LABELS: list[str] = []
for _area, _desc, _subs in TAXONOMY:
    for _s, _ in _subs:
        CATEGORY_LABELS.append(category_label(_area, _s))
    CATEGORY_LABELS.append(_area)


def _canon(text: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(text.lower())).strip()


_LABEL_INDEX = {_canon(lbl): lbl for lbl in CATEGORY_LABELS}
_AREA_INDEX = {_canon(a): a for a in AREAS}


def parse_category(label: str) -> tuple[str, str]:
    """Converte um rótulo devolvido pela IA em (área, subárea), sempre dentro da taxonomia."""
    text = _canon(str(label).replace(">", "›").replace("/", "›").replace("»", "›"))
    text = re.sub(r"\s*›\s*", " › ", text)
    found = _LABEL_INDEX.get(text)
    if found is None:
        head, _, tail = text.partition(" › ")
        area = _AREA_INDEX.get(head)
        if area is None:
            return "Outros", ""
        canon_subs = {_canon(s): s for s in AREAS[area]}
        return area, canon_subs.get(tail, "")
    area, _, sub = found.partition(CATEGORY_SEP)
    return area, sub


# --------------------------------------------------------------------------- palavras-chave

# (área, subárea, palavras fortes, palavras fracas). Sem acentos e em minúsculas.
# Uma palavra fraca sozinha nunca decide: é preciso pelo menos uma forte.
_KEYWORDS: list[tuple[str, str, list[str], list[str]]] = [
    ("Finanças", "Faturas e Recibos",
     ["fatura", "factura", "fatura-recibo", "fatura simplificada", "nota de credito", "atcud",
      "invoice", "receipt", "recibo"],
     ["total a pagar", "valor a pagar", "referencia multibanco", "data limite de pagamento",
      "debito direto", "nif", "iva", "contribuinte"]),
    ("Finanças", "Banco",
     ["extrato", "iban", "bank statement", "comprovativo de transferencia", "transferencia bancaria",
      "credito habitacao", "emprestimo", "cartao de credito", "cartao de debito", "conta a ordem",
      "saldo disponivel", "saldo final"],
     ["saldo", "movimentos", "bic", "swift", "deposito", "taeg", "taxa anual nominal"]),
    ("Finanças", "Impostos",
     ["irs", "irc", "imi", "iuc", "imt", "autoridade tributaria", "portal das financas",
      "declaracao de rendimentos", "nota de liquidacao", "liquidacao de irs", "modelo 3",
      "declaracao periodica do iva", "seguranca social direta"],
     ["imposto", "financas", "coleta", "reembolso", "sujeito passivo", "rendimento coletavel"]),
    ("Finanças", "Seguros",
     ["apolice", "seguradora", "tomador do seguro", "premio de seguro", "condicoes particulares",
      "condicoes gerais", "participacao de sinistro", "sinistro"],
     ["seguro", "cobertura", "franquia", "capital seguro"]),
    ("Finanças", "Salários",
     ["recibo de vencimento", "vencimento base", "payslip", "subsidio de ferias", "subsidio de natal",
      "subsidio de alimentacao", "remuneracao base", "liquido a receber"],
     ["salario", "remuneracao", "seguranca social", "retencao na fonte", "horas extra"]),
    ("Finanças", "Investimentos",
     ["fundo de investimento", "carteira de titulos", "certificados de aforro", "certificados do tesouro",
      "dividendos", "corretora", "plano poupanca reforma"],
     ["ppr", "acoes", "obrigacoes", "rendimento", "juros"]),
    ("Saúde", "Exames e Análises",
     ["analises clinicas", "hemograma", "radiografia", "ecografia", "ressonancia magnetica",
      "tomografia", "eletrocardiograma", "electrocardiograma", "mamografia", "colesterol",
      "glicemia", "valores de referencia", "tac"],
     ["laboratorio", "exame", "resultado", "colheita"]),
    ("Saúde", "Receitas médicas",
     ["receita medica", "guia de tratamento", "posologia", "dci", "medicamento", "comprimidos"],
     ["farmacia", "dose", "embalagens"]),
    ("Saúde", "Consultas e Relatórios",
     ["relatorio medico", "centro de saude", "baixa medica", "atestado medico",
      "declaracao medica", "certificado de incapacidade", "diagnostico", "numero de utente"],
     ["hospital", "clinica", "medico", "medica", "consulta", "utente", "enfermagem", "sns", "doente"]),
    ("Casa", "Escrituras e Arrendamento",
     ["escritura", "contrato de arrendamento", "arrendamento", "senhorio", "inquilino", "arrendatario",
      "caderneta predial", "registo predial", "licenca de utilizacao", "contrato promessa de compra e venda"],
     ["renda", "fracao", "imovel", "habitacao"]),
    ("Casa", "Condomínio",
     ["condominio", "assembleia de condominos", "administracao do condominio", "quotas do condominio"],
     ["condominos", "quotas", "fracao"]),
    ("Casa", "Obras e Manutenção",
     ["obras", "remodelacao", "empreitada", "canalizador", "canalizacao", "eletricista",
      "orcamento de obra"],
     ["orcamento", "reparacao", "manutencao", "pintura", "azulejo"]),
    ("Trabalho", "Contratos e Propostas",
     ["contrato de trabalho", "contrato trabalho", "contrato de prestacao de servicos",
      "proposta de prestacao de servicos", "proposta comercial", "proposta de servicos",
      "entidade empregadora", "periodo experimental", "acordo de confidencialidade"],
     ["trabalhador", "proposta", "cliente", "honorarios", "retribuicao"]),
    ("Trabalho", "Projetos",
     ["caderno de encargos", "cronograma", "plano de projeto", "project plan",
      "user stories", "backlog", "sprint", "roadmap", "especificacao funcional"],
     ["requisitos", "projeto", "project", "entregaveis", "milestone", "equipa de desenvolvimento"]),
    ("Trabalho", "Reuniões",
     ["ordem de trabalhos", "ata da reuniao", "reuniao de", "convocatoria", "meeting minutes",
      "minutes of meeting", "pontos discutidos"],
     ["reuniao", "participantes", "ata", "agenda"]),
    ("Trabalho", "Relatórios",
     ["relatorio de atividades", "relatorio anual", "relatorio de progresso", "sumario executivo",
      "executive summary", "relatorio de contas"],
     ["relatorio", "report", "conclusoes", "analise"]),
    ("Trabalho", "Apresentações",
     ["slides", "diapositivos", "pptx", "ppt", "odp"],
     ["apresentacao", "agenda", "obrigado"]),
    ("Educação", "Certificados e Diplomas",
     ["certificado de habilitacoes", "certificado de formacao", "diploma", "certidao de habilitacoes",
      "certificado de conclusao", "certificate of completion", "concluiu com aproveitamento",
      "certifica-se que"],
     ["certificado", "aproveitamento", "classificacao final"]),
    ("Educação", "Cursos e Formações",
     ["ufcd", "formando", "formandos", "plano de sessao", "manual do formando", "manual de formacao",
      "acao de formacao", "curso de formacao", "instituto do emprego e formacao profissional",
      "iefp", "webinar", "workshop"],
     ["formacao", "curso", "modulo", "sessao", "formador"]),
    ("Educação", "Apontamentos",
     ["apontamentos", "sebenta", "resumo da materia", "exercicios resolvidos", "ficha de trabalho",
      "teste de avaliacao", "exame nacional"],
     ["capitulo", "exercicio", "exercicios", "aula", "materia", "universidade", "faculdade", "escola"]),
    ("Educação", "Trabalhos académicos",
     ["dissertacao", "tese de mestrado", "tese de doutoramento", "trabalho de grupo", "monografia",
      "relatorio de estagio", "orientador"],
     ["bibliografia", "referencias bibliograficas", "introducao", "abstract"]),
    ("Pessoal", "Identificação",
     ["cartao de cidadao", "passaporte", "bilhete de identidade", "certidao de nascimento",
      "certidao de casamento", "carta de conducao", "titulo de residencia", "autorizacao de residencia"],
     ["nacionalidade", "naturalidade", "filiacao", "data de nascimento", "data de validade"]),
    ("Pessoal", "Currículos",
     ["curriculum vitae", "curriculo", "europass", "experiencia profissional", "habilitacoes literarias",
      "carta de motivacao", "carta de apresentacao", "candidatura", "cv"],
     ["competencias", "resume", "linkedin", "linguas"]),
    ("Pessoal", "Cartas e Correspondência",
     ["carta registada", "aviso de rececao"],
     ["exmo", "exma", "exmos", "atenciosamente", "com os melhores cumprimentos"]),
    ("Jurídico", "Processos e Tribunal",
     ["tribunal", "sentenca", "citacao", "acordao", "ministerio publico", "advogado",
      "solicitador", "agente de execucao", "contestacao", "peticao inicial", "providencia cautelar"],
     ["notificacao", "processo n", "processo", "juiz", "requerimento", "autor", "reu"]),
    ("Jurídico", "Procurações e Notariado",
     ["procuracao", "procurador", "notario", "cartorio", "reconhecimento de assinatura",
      "termo de autenticacao", "habilitacao de herdeiros", "testamento", "partilhas"],
     ["outorgante", "poderes"]),
    ("Jurídico", "Contratos e Acordos",
     ["contrato de comodato", "contrato de mutuo", "contrato de cessao", "contrato de doacao",
      "acordo de partilha", "contraente"],
     ["primeiro outorgante", "segundo outorgante", "clausula primeira", "clausula", "contrato", "acordo",
      "partes"]),
    ("Veículos", "Documentação e Inspeções",
     ["documento unico automovel", "certificado de matricula", "inspecao periodica",
      "centro de inspecoes", "livrete", "titulo de registo de propriedade", "ipo"],
     ["matricula", "veiculo", "viatura", "automovel", "quilometros"]),
    ("Veículos", "Seguro automóvel",
     ["carta verde", "seguro automovel", "seguro auto", "seguro carro",
      "certificado internacional de seguro automovel"],
     ["matricula", "condutor", "veiculo"]),
    ("Veículos", "Manutenção e Reparações",
     ["mudanca de oleo", "filtro de oleo", "pastilhas de travao", "correia de distribuicao", "pneus",
      "revisao dos"],
     ["oficina", "revisao", "reparacao", "quilometros", "km"]),
    ("Viagens", "Bilhetes e Reservas",
     ["boarding pass", "cartao de embarque", "e-ticket", "bilhete eletronico", "confirmacao de reserva",
      "booking confirmation", "numero da reserva", "check-in", "voo", "flight"],
     ["hotel", "alojamento", "reserva", "booking", "itinerario", "partida", "chegada"]),
    ("Viagens", "Roteiros",
     ["roteiro", "itinerario de viagem", "guia de viagem", "o que visitar", "travel guide"],
     ["visitar", "turismo", "pontos de interesse"]),
    ("Compras e Garantias", "Garantias",
     ["certificado de garantia", "warranty", "prazo de garantia", "garantia de"],
     ["garantia", "talao", "de serie", "data de compra"]),
    ("Compras e Garantias", "Manuais de instruções",
     ["manual de instrucoes", "manual do utilizador", "user manual", "user guide", "guia do utilizador",
      "instrucoes de utilizacao", "instrucoes de seguranca", "guia de inicio rapido", "quick start guide",
      "owner's manual"],
     ["manual", "instrucoes", "aparelho"]),
    ("Compras e Garantias", "Encomendas",
     ["a sua encomenda", "confirmacao da encomenda", "numero da encomenda", "order confirmation",
      "order number", "tracking number", "numero de seguimento"],
     ["encomenda", "envio", "portes", "entrega", "artigos"]),
    ("Livros e Leituras", "",
     ["isbn", "todos os direitos reservados", "all rights reserved", "1.a edicao"],
     ["capitulo", "prefacio", "indice", "romance", "autora", "autor"]),
    ("Lazer", "",
     ["ingredientes", "modo de preparacao", "partitura", "plano de treino"],
     ["desporto", "concerto", "espetaculo", "jogo"]),
]


def _compile(word: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])")


_COMPILED = [
    (area, sub, [(_compile(k), k) for k in strong], [(_compile(k), k) for k in weak])
    for area, sub, strong, weak in _KEYWORDS
]

KEYWORD_MIN_SCORE = 3.0


def normalize(text: str) -> str:
    return strip_accents(text.lower())


def keyword_classify(name: str, text: str) -> tuple[str, str, float, list[str]]:
    """Classificação rápida por palavras-chave. Devolve (área, subárea, confiança, pistas).

    Cada palavra forte vale 3 pontos no nome do ficheiro e 2 por ocorrência no texto (3 se for uma
    expressão de várias palavras), até 3 ocorrências; cada palavra fraca vale 1 no nome e 0,5 por
    ocorrência (até 2). Só conta um grupo com pelo menos uma palavra forte e 3 pontos; se duas áreas
    ficarem perto, a confiança desce.
    """
    n_name = normalize(re.sub(r"[_\-\.]+", " ", name))
    n_text = normalize(text[:6000])
    candidates: list[tuple[float, str, str, list[str]]] = []
    for area, sub, strong, weak in _COMPILED:
        score, hits, has_strong = 0.0, [], False
        for weight_name, weight_text, cap, words in ((3.0, 2.0, 3, strong), (1.0, 0.5, 2, weak)):
            for pat, word in words:
                in_name = bool(pat.search(n_name))
                count = len(pat.findall(n_text)) if n_text else 0
                if in_name or count:
                    hits.append(word)
                    has_strong = has_strong or words is strong
                # Expressões fortes com várias palavras («cartão de cidadão») são muito específicas.
                w_text = 3.0 if words is strong and " " in word else weight_text
                score += weight_name * in_name + w_text * min(count, cap)
        if has_strong:
            candidates.append((score, area, sub, hits))
    if not candidates:
        return "Outros", "", 0.15, []
    candidates.sort(key=lambda c: c[0], reverse=True)
    score, area, sub, hits = candidates[0]
    if score < KEYWORD_MIN_SCORE:
        return "Outros", "", 0.15, []
    conf = min(0.85, 0.35 + 0.06 * score)
    rival = next((c[0] for c in candidates[1:] if c[1] != area), 0.0)
    if rival >= 0.75 * score:
        conf = min(conf, 0.5)
    return area, sub, conf, hits[:4]


MONTHS_PT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
             "setembro", "outubro", "novembro", "dezembro"]
