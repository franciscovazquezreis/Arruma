# SPDX-License-Identifier: GPL-3.0-or-later
"""Avisos dos componentes de outros autores incluídos nas versões de Windows e macOS.

O arruma.spec chama gerar() depois do Analysis do PyInstaller. Cada ficheiro recolhido é
atribuído ao pacote de onde vem (MSYS2 no Windows; Homebrew ou pip no macOS) e, numa pasta
própria, ficam a lista dos componentes (LEIA-ME.txt e componentes.json), os textos das
licenças e as receitas de construção. O fontes.py usa o componentes.json para juntar o
código-fonte correspondente, que acompanha os instaladores sempre que outras pessoas os podem
descarregar (ver .github/workflows/construir.yml).
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPOSITORIO = "https://github.com/franciscovazquezreis/Arruma"
# Nome do artefacto do GitHub Actions com o código-fonte de terceiros (ver construir.yml).
ARTEFACTO_FONTES = "arruma-codigo-fonte-terceiros"
TEXTOS_PADRAO = Path(__file__).with_name("textos")
IGNORAR_TIPOS = {"SYMLINK", "DEPENDENCY", "OPTION"}
PREFIXO_MSYS2 = "mingw-w64-ucrt-x86_64-"

# Licenças que os metadados dos pacotes indicam mal ou de forma incompleta (verificadas nos
# ficheiros COPYING de cada projeto). A chave é o nome curto do pacote MSYS2 ou da fórmula.
LICENCAS_CORRIGIDAS = {
    "poppler": "(GPL-2.0-only OR GPL-3.0-only) AND GPL-2.0-or-later",
    "cairo": "LGPL-2.1-only OR MPL-1.1",
    "python-cairo": "LGPL-2.1-only OR MPL-1.1",
    "py3cairo": "LGPL-2.1-only OR MPL-1.1",
    "gtk3": "LGPL-2.0-or-later",
    "gtk+3": "LGPL-2.0-or-later",
    "pango": "LGPL-2.0-or-later",
    "libiconv": "LGPL-2.1-or-later",
    "gettext-runtime": "LGPL-2.1-or-later",
    "libgcc": "GPL-3.0-or-later WITH GCC-exception-3.1",
    "libstdc++": "GPL-3.0-or-later WITH GCC-exception-3.1",
    "adwaita-icon-theme": "LGPL-3.0-or-later OR CC-BY-SA-3.0",
    "adwaita-icon-theme-legacy": "LGPL-3.0-or-later OR CC-BY-SA-3.0",
    "libimagequant": "GPL-3.0-or-later",
    "jbigkit": "GPL-2.0-or-later",  # cabeçalhos de libjbig/jbig.c («or any later version»)
    "freetype": "FTL OR GPL-2.0-or-later",  # LICENSE.TXT do próprio FreeType
    "libdatrie": "LGPL-2.1-or-later",
    "bzip2": "bzip2-1.0.6",
    "libpng": "libpng-2.0",
    "libjpeg-turbo": "IJG AND BSD-3-Clause AND Zlib",
    "sqlite3": "blessing",
    "fontconfig": "HPND-sell-variant AND Unicode-3.0 AND MIT-Modern-Variant AND MIT",
    "pyinstaller": "GPL-2.0-or-later WITH Bootloader-exception AND Apache-2.0",
    "pyinstaller-hooks-contrib": "Apache-2.0 AND GPL-2.0-or-later",
}

# Textos-padrão que acompanham cada família de licenças (além dos ficheiros do próprio pacote).
TEXTOS_POR_LICENCA = [
    ("LGPL-3.0", ["LGPL-3.0.txt", "GPL-3.0.txt"]),
    ("LGPL-2.0", ["LGPL-2.0.txt"]),
    ("LGPL-2.1", ["LGPL-2.1.txt"]),
    ("GPL-3.0", ["GPL-3.0.txt"]),
    ("GPL-2.0", ["GPL-2.0.txt"]),
    ("MPL-2.0", ["MPL-2.0.txt"]),
    ("Apache-2.0", ["Apache-2.0.txt"]),
]

# Componentes que incluem bibliotecas Rust (crates) descarregadas durante a compilação.
COMPILADOS_COM_CARGO = {"librsvg", "rav1e", "libimagequant", "cryptography"}

# Ficheiros criados durante a instalação ou a construção, que nenhum pacote declara.
GERADOS = {
    "loaders.cache": ("gdk-pixbuf2", "gdk-pixbuf"),
    "gschemas.compiled": ("glib2", "glib"),
    "giomodule.cache": ("glib2", "glib"),
    "icon-theme.cache": ("gtk-update-icon-cache", "gtk+3"),
    "immodules.cache": ("gtk3", "gtk+3"),
}

NOME_LICENCA = re.compile(r"^(copying|copyright|licen[cs]e|notice|unlicense|(l?gpl|mpl|mit|bsd|apache|ftl)\b)", re.I)


@dataclass
class Componente:
    chave: str
    nome: str
    versao: str
    licenca: str
    origem: str
    pagina: str = ""
    fontes: list[dict] = field(default_factory=list)
    textos: list[str] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)
    ficheiros: int = 0
    cargo: bool = False  # inclui bibliotecas Rust (crates) cujo código-fonte o fontes.py junta à parte
    crates: str = ""  # pasta com os textos das licenças dessas crates (ver juntar_textos_crates())
    n_crates: int = 0
    crates_lock_gerado: bool = False  # o código-fonte não traz Cargo.lock; gerou-se um na construção
    crates_sem_texto: list[str] = field(default_factory=list)  # licenças das crates que não trazem texto


@dataclass
class Resultado:
    componentes: dict[str, Componente]
    desconhecidos: list[tuple[str, str]]
    entradas: list[tuple[str, str, str]]


def _corrigir_licenca(nome: str, licenca: str) -> str:
    return LICENCAS_CORRIGIDAS.get(nome, licenca) or "não indicada"


# Licenças que não se podem combinar com a GPL versão 3 ou posterior, segundo a lista da FSF
# (https://www.gnu.org/licenses/license-list.html). No SPDX, os identificadores antigos sem
# -only/-or-later (GPL-2.0, GPL-1.0) valem como -only. As exceções de ligação (WITH) não contam:
# por prudência, uma GPL-2.0-only com exceção também para a construção.
_INCOMPATIVEIS = {i.casefold() for i in (
    "GPL-1.0", "GPL-1.0-only", "GPL-2.0", "GPL-2.0-only", "GPL-2.0-with-autoconf-exception",
    "GPL-2.0-with-bison-exception", "GPL-2.0-with-classpath-exception", "GPL-2.0-with-font-exception",
    "GPL-2.0-with-GCC-exception", "AGPL-1.0", "AGPL-1.0-only", "MPL-1.0", "MPL-1.1",
    "MPL-2.0-no-copyleft-exception", "NPL-1.0", "NPL-1.1", "CDDL-1.0", "CDDL-1.1", "EPL-1.0", "EPL-2.0",
    "CPL-1.0", "IPL-1.0", "CPAL-1.0", "OpenSSL", "BSD-4-Clause", "BSD-4-Clause-UC", "Apache-1.0",
    "Apache-1.1", "PHP-3.0", "PHP-3.01", "QPL-1.0", "Artistic-1.0", "Artistic-1.0-Perl", "Artistic-1.0-cl8",
    "OSL-1.0", "OSL-1.1", "OSL-2.0", "OSL-2.1", "OSL-3.0", "AFL-1.1", "AFL-1.2", "AFL-2.0", "AFL-2.1",
    "AFL-3.0", "EUPL-1.0", "EUPL-1.1", "MS-PL", "MS-RL", "OFL-1.0", "OFL-1.1", "LPPL-1.2", "LPPL-1.3a",
    "SISSL", "SPL-1.0", "RPSL-1.0", "Condor-1.1", "gnuplot", "xinetd", "YPL-1.1", "CNRI-Python",
)}
# Famílias em que uma versão posterior já é compatível, para os identificadores com «+».
_FAMILIAS_COM_VERSAO_COMPATIVEL = {f.casefold() for f in (
    "GPL", "LGPL", "AGPL", "MPL", "Apache", "CC-BY-SA", "EUPL", "Artistic")}
_ID_SPDX = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]*")


def _compativel(termo: str) -> bool:
    licenca = termo.split(" WITH ")[0].strip().casefold()
    if licenca.endswith("+"):  # «+» no SPDX: esta versão ou qualquer posterior
        base = licenca[:-1]
        familia = re.sub(r"-\d.*$", "", base)
        return familia in _FAMILIAS_COM_VERSAO_COMPATIVEL or _compativel(base)
    # CC-BY-SA até à 3.0, incluindo as adaptações a cada país (CC-BY-SA-3.0-DE…); a 4.0 é compatível.
    return licenca not in _INCOMPATIVEIS and not licenca.startswith(
        ("cc-by-nc", "cc-by-nd", "cc-by-sa-1", "cc-by-sa-2", "cc-by-sa-3"))


def _conhecida(termo: str) -> bool:
    """O termo é um identificador SPDX (e não texto livre, «não indicada» ou LicenseRef-…)."""
    licenca = termo.split(" WITH ")[0].strip()
    return bool(_ID_SPDX.fullmatch(licenca)) and not licenca.casefold().startswith(("licenseref-", "documentref-"))


def _dividir(expr: str, operador: str) -> list[str]:
    """Divide uma expressão SPDX pelo operador, só ao nível de topo (fora de parênteses)."""
    partes, nivel, inicio, i, alvo = [], 0, 0, 0, f" {operador} "
    while i < len(expr):
        if expr[i] == "(":
            nivel += 1
        elif expr[i] == ")":
            nivel -= 1
        elif nivel == 0 and expr.startswith(alvo, i):
            partes.append(expr[inicio:i].strip())
            i += len(alvo)
            inicio = i
            continue
        i += 1
    partes.append(expr[inicio:].strip())
    return partes


def _sem_parenteses(expr: str) -> str:
    expr = expr.strip()
    while expr.startswith("(") and expr.endswith(")"):
        interior, nivel = expr[1:-1], 0
        for c in interior:
            nivel += (c == "(") - (c == ")")
            if nivel < 0:
                return expr
        expr = interior.strip()
    return expr


def _resolver(expr: str) -> str | None:
    """A primeira opção de expr compatível com a GPL-3.0 ou posterior, ou None se não houver."""
    expr = _sem_parenteses(expr)
    for alternativa in _dividir(expr, "OR"):  # no SPDX, o OR liga menos do que o AND
        termos = _dividir(alternativa, "AND")
        if len(termos) == 1 and _sem_parenteses(termos[0]) == termos[0]:
            if _compativel(termos[0]):
                return termos[0]
            continue
        partes = [_resolver(t) for t in termos]
        if all(partes):
            return " AND ".join(partes)  # type: ignore[arg-type]
    return None


def escolher_licenca(licenca: str) -> str:
    """Opção usada quando a licença deixa escolher: a primeira compatível com a GPL-3.0 ou posterior.

    Sem escolha (sem OR), devolve a licença tal como está. Com escolha mas sem nenhuma opção
    compatível, falha, para que a construção pare em vez de publicar um aviso errado."""
    expr = _sem_parenteses(licenca)
    if " OR " not in expr:
        return expr
    escolha = _resolver(expr)
    if escolha is None:
        raise ValueError(f"nenhuma opção de «{licenca}» é compatível com a GPL versão 3 ou posterior")
    return escolha


# Componentes que só formam um agregado com o Arruma (ficheiros de dados, não código que corre
# dentro dele), por isso podem ter uma licença que não se combinaria com a GPL-3.0.
AGREGADOS = {"hicolor-icon-theme"}


def escolha_do_componente(comp: Componente) -> str:
    """A licença usada para o componente (ver escolher_licenca), com o nome dele em caso de erro."""
    try:
        return escolher_licenca(comp.licenca)
    except ValueError as e:
        if comp.nome in AGREGADOS:
            return comp.licenca
        raise ValueError(f"{comp.nome} {comp.versao}: {e}") from None


def incompativeis(componentes: dict[str, Componente]) -> list[str]:
    """Componentes cuja licença, já com a escolha feita, não se pode combinar com a GPL-3.0 ou posterior
    ou não é um identificador SPDX conhecido (texto livre, «não indicada», LicenseRef-…)."""
    maus = []
    for comp in sorted(componentes.values(), key=lambda c: c.nome.casefold()):
        if comp.nome in AGREGADOS:
            continue
        escolha = escolha_do_componente(comp)
        termos = re.split(r"\s+AND\s+", re.sub(r"[()]", " ", escolha).strip())
        if not all(_conhecida(t) and _compativel(t) for t in termos):
            maus.append(f"{comp.nome} {comp.versao} ({escolha})")
    return maus


def _textos_padrao(licenca: str) -> list[str]:
    nomes: list[str] = []
    for marca, textos in TEXTOS_POR_LICENCA:
        if marca in licenca:
            nomes += [t for t in textos if t not in nomes]
    return nomes


def _licenca_crate_spdx(licenca: str) -> str:
    """As crates antigas escrevem «MIT/Apache-2.0» para dizer «MIT OR Apache-2.0»."""
    return re.sub(r"\s*/\s*", " OR ", licenca)


def problemas_crates(licencas: list[str], sem_texto: list[str]) -> list[str]:
    """Licenças de crates que não se podem combinar com a GPL-3.0 ou posterior (ou que não são
    identificadores SPDX), e licenças de crates sem texto para as quais não há texto-padrão."""
    problemas = []
    for licenca in licencas:
        try:
            escolha = escolher_licenca(_licenca_crate_spdx(licenca))
        except ValueError:
            problemas.append(f"incompatível com a GPL-3.0: {licenca}")
            continue
        termos = re.split(r"\s+AND\s+", re.sub(r"[()]", " ", escolha).strip())
        if not all(_conhecida(t) and _compativel(t) for t in termos):
            problemas.append(f"incompatível com a GPL-3.0 ou desconhecida: {licenca}")
    for licenca in sem_texto:
        if not _textos_padrao_crates([_licenca_crate_spdx(licenca)]):
            problemas.append(f"sem texto no pacote nem texto-padrão: {licenca}")
    return problemas


def _textos_padrao_crates(licencas: list[str]) -> list[str]:
    """Textos-padrão para as crates que não trazem o texto da licença (com a MIT e a BSD-2-Clause,
    que nos componentes vêm sempre no próprio pacote)."""
    nomes: list[str] = []
    for licenca in licencas:
        extra = (["MIT.txt"] if re.search(r"\bMIT\b(?![-\w])", licenca) else []) + \
                (["BSD-2-Clause.txt"] if re.search(r"\bBSD-2-Clause\b(?![-\w])", licenca) else [])
        nomes += [t for t in _textos_padrao(licenca) + extra if t not in nomes]
    return nomes


def _normalizar(caminho: str) -> str:
    return os.path.realpath(caminho).replace("\\", "/")


def ficheiros_recolhidos(*listas) -> list[tuple[str, str]]:
    """(caminho de origem, tipo) de tudo o que o PyInstaller vai copiar, sem repetições."""
    vistos: dict[str, str] = {}
    for lista in listas:
        for entrada in lista:
            origem, tipo = entrada[1], entrada[2]
            if tipo in IGNORAR_TIPOS or not origem or origem == "-" or not os.path.isfile(origem):
                continue
            vistos.setdefault(origem, tipo)
    return sorted(vistos.items())


# --------------------------------------------------------------------------- MSYS2 (Windows)
def _secoes(caminho: Path) -> dict[str, list[str]]:
    """Lê os ficheiros desc e files da base de dados local do pacman (%SECÇÃO% e valores)."""
    secoes: dict[str, list[str]] = {}
    atual = None
    for linha in caminho.read_text(encoding="utf-8", errors="replace").splitlines():
        if len(linha) > 2 and linha.startswith("%") and linha.endswith("%"):
            atual = linha[1:-1]
            secoes[atual] = []
        elif not linha:
            atual = None
        elif atual:
            secoes[atual].append(linha)
    return secoes


def licenca_msys2(valores: list[str]) -> str:
    """Converte o campo %LICENSE% do MSYS2: valores «spdx:» separados significam OU."""
    partes = []
    for valor in valores:
        valor = valor.strip().rstrip(",")
        if valor.upper() in ("OR", "AND") or not valor:
            continue
        if valor.startswith("documentation:"):
            continue
        partes.append(valor[5:] if valor.startswith("spdx:") else valor)
    if len(partes) > 1:
        return " OR ".join(f"({p})" if " " in p else p for p in partes)
    return partes[0] if partes else ""


class Msys2:
    origem = "msys2"

    def __init__(self, raiz: str | None = None):
        self.raiz = (raiz or self._descobrir_raiz()).replace("\\", "/").rstrip("/")
        self.pacotes: dict[str, dict[str, list[str]]] = {}
        self.ficheiros: dict[str, list[str]] = {}
        self.dono: dict[str, str] = {}
        local = Path(self.raiz) / "var" / "lib" / "pacman" / "local"
        for pasta in sorted(local.iterdir()):
            if not (pasta / "desc").is_file():
                continue
            desc = _secoes(pasta / "desc")
            nome = desc.get("NAME", [pasta.name])[0]
            self.pacotes[nome] = desc
            lista = [f for f in _secoes(pasta / "files").get("FILES", []) if not f.endswith("/")]
            self.ficheiros[nome] = lista
            for f in lista:
                self.dono[f"{self.raiz}/{f}".casefold()] = nome

    @staticmethod
    def _descobrir_raiz() -> str:
        try:
            saida = subprocess.run(["cygpath", "-m", "/"], capture_output=True, text=True, timeout=60).stdout.strip()
            if saida:
                return saida
        except OSError:
            pass
        return str(Path(sys.prefix).parent)  # sys.prefix é <raiz>/ucrt64

    def pastas_dados(self) -> list[str]:
        return [f"{self.raiz}/ucrt64/share"]

    @staticmethod
    def curto(nome: str) -> str:
        return nome[len(PREFIXO_MSYS2):] if nome.startswith(PREFIXO_MSYS2) else nome

    def pacote_de(self, caminho: str) -> str | None:
        normal = _normalizar(caminho).casefold()
        dono = self.dono.get(normal)
        if dono is None and "/__pycache__/" in normal:
            try:
                fonte = importlib.util.source_from_cache(_normalizar(caminho))
                dono = self.dono.get(_normalizar(fonte).casefold())
            except ValueError:
                pass
        return dono

    def pacote_por_nome(self, curto: str) -> str | None:
        nome = PREFIXO_MSYS2 + curto
        return nome if nome in self.pacotes else None

    def componente(self, nome: str) -> Componente:
        desc = self.pacotes[nome]
        versao = desc.get("VERSION", ["?"])[0]
        base = desc.get("BASE", [nome])[0]
        curto = self.curto(nome)
        repo = "mingw" if nome.startswith("mingw-w64-") else "msys"
        licenca = _corrigir_licenca(curto, licenca_msys2(desc.get("LICENSE", [])))
        textos = [f"{self.raiz}/{f}" for f in self.ficheiros.get(nome, []) if "/share/licenses/" in f"/{f}"]
        return Componente(
            chave=f"msys2:{nome}", nome=curto, versao=versao, licenca=licenca, origem=self.origem,
            pagina=desc.get("URL", [""])[0],
            fontes=[{"tipo": "msys2", "url": f"https://repo.msys2.org/{repo}/sources/{base}-{versao}.src.tar.zst"}],
            textos=textos,
        )


# --------------------------------------------------------------------------- Homebrew (macOS)
def _executar(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=600,
                          env={**os.environ, "HOMEBREW_NO_AUTO_UPDATE": "1", "HOMEBREW_NO_ENV_HINTS": "1"}).stdout


class Homebrew:
    origem = "homebrew"

    def __init__(self, prefixo: str | None = None, cellar: str | None = None):
        self.prefixo = _normalizar(prefixo or _executar(["brew", "--prefix"]).strip())
        self.cellar = _normalizar(cellar or _executar(["brew", "--cellar"]).strip())
        self.info: dict[str, dict] = {}

    def pastas_dados(self) -> list[str]:
        return [f"{self.prefixo}/share"]

    def keg_de(self, caminho: str) -> tuple[str, str] | None:
        normal = _normalizar(caminho)
        if not normal.startswith(self.cellar + "/"):
            return None
        partes = normal[len(self.cellar) + 1:].split("/")
        return (partes[0], partes[1]) if len(partes) >= 3 else None

    def pacote_de(self, caminho: str) -> str | None:
        keg = self.keg_de(caminho)
        if keg:
            return f"{keg[0]}/{keg[1]}"
        nome = os.path.basename(caminho)
        if nome.endswith(".typelib"):
            # O PyInstaller recompila os typelibs a partir do .gir de cada fórmula.
            gir = Path(self.prefixo) / "share" / "gir-1.0" / (nome[:-len(".typelib")] + ".gir")
            keg = self.keg_de(str(gir)) if gir.exists() else None
            if keg:
                return f"{keg[0]}/{keg[1]}"
        return None

    def pacote_por_nome(self, formula: str) -> str | None:
        rack = Path(self.cellar) / formula
        if not rack.is_dir():
            return None
        versoes = sorted(p.name for p in rack.iterdir() if p.is_dir())
        return f"{formula}/{versoes[-1]}" if versoes else None

    def carregar_info(self, formulas: list[str]) -> None:
        if not formulas:
            return
        dados = json.loads(_executar(["brew", "info", "--json=v2", "--formula", *formulas]))
        for f in dados.get("formulae", []):
            self.info[f["name"]] = f

    def componente(self, chave: str) -> Componente:
        formula, versao = chave.split("/", 1)
        keg = Path(self.cellar) / formula / versao
        info = self.info.get(formula, {})
        licenca = _corrigir_licenca(formula, info.get("license") or "")
        fontes: list[dict] = []
        sbom = keg / "sbom.spdx.json"
        if sbom.is_file():
            try:
                for pacote in json.loads(sbom.read_text(encoding="utf-8")).get("packages", []):
                    spdx = pacote.get("SPDXID", "")
                    url = pacote.get("downloadLocation", "")
                    if url.startswith("http") and spdx.startswith(("SPDXRef-Archive-", "SPDXRef-Patch-")):
                        fontes.append({"tipo": "url", "url": url})
            except (OSError, ValueError):
                pass
        if not fontes and info.get("urls", {}).get("stable", {}).get("url"):
            fontes.append({"tipo": "url", "url": info["urls"]["stable"]["url"]})
        cabeca, receita = info.get("tap_git_head"), info.get("ruby_source_path")
        if cabeca and receita:
            raw = f"https://raw.githubusercontent.com/Homebrew/homebrew-core/{cabeca}"
            fontes.append({"tipo": "url", "url": f"{raw}/{receita}"})
            for remendo in info.get("patches", []) or []:
                if isinstance(remendo, dict) and remendo.get("file"):
                    fontes.append({"tipo": "url", "url": f"{raw}/{remendo['file']}"})
        textos = [str(p) for p in sorted(keg.iterdir()) if p.is_file() and NOME_LICENCA.match(p.name)]
        receita_local = keg / ".brew" / f"{formula}.rb"
        if receita_local.is_file():
            textos.append(str(receita_local))
        return Componente(chave=f"homebrew:{chave}", nome=formula, versao=versao, licenca=licenca,
                          origem=self.origem, pagina=info.get("homepage", ""), fontes=fontes, textos=textos)


# --------------------------------------------------------------------------- pip (macOS)
class Pip:
    origem = "pypi"

    def __init__(self):
        self.dono: dict[str, importlib.metadata.Distribution] = {}
        self.por_chave: dict[str, importlib.metadata.Distribution] = {}
        self.sites: set[str] = set()
        self.por_modulo: dict[tuple[str, str], importlib.metadata.Distribution] = {}
        for dist in importlib.metadata.distributions():
            self._registar(dist)

    @staticmethod
    def _nome(nome: str) -> str:
        return re.sub(r"[-_.]+", "_", nome).lower()

    def _registar(self, dist: importlib.metadata.Distribution) -> None:
        for f in dist.files or []:
            try:
                self.dono.setdefault(_normalizar(str(dist.locate_file(f))), dist)
            except (OSError, ValueError):
                continue

    def _site_de(self, real: str) -> None:
        """Lê os .dist-info da pasta site-packages onde o ficheiro está de facto. Há fórmulas do
        Homebrew que instalam pacotes Python cujo registo não fica visível no sys.path (por
        exemplo, o typing_extensions dentro da fórmula pydantic)."""
        partes = real.split("/")
        if "site-packages" not in partes:
            return
        site = "/".join(partes[:len(partes) - partes[::-1].index("site-packages")])
        if site in self.sites:
            return
        self.sites.add(site)
        for info in sorted(Path(site).glob("*.dist-info")):
            dist = importlib.metadata.PathDistribution(info)
            self._registar(dist)
            # Os pacotes do Homebrew não trazem RECORD: fica o nome do módulo (ou o top_level.txt).
            modulos = (dist.read_text("top_level.txt") or "").split() or [dist.metadata["Name"] or ""]
            for modulo in modulos:
                self.por_modulo.setdefault((site, self._nome(modulo)), dist)

    def _por_modulo(self, real: str) -> importlib.metadata.Distribution | None:
        partes = real.split("/")
        if "site-packages" not in partes:
            return None
        fim = len(partes) - partes[::-1].index("site-packages")
        if fim >= len(partes):
            return None
        site, primeiro = "/".join(partes[:fim]), partes[fim]
        if primeiro.endswith(".dist-info"):
            return None
        modulo = primeiro.split(".", 1)[0] if primeiro.endswith((".py", ".so", ".pyd")) or ".cpython-" in primeiro \
            else primeiro
        return self.por_modulo.get((site, self._nome(modulo)))

    def pacote_de(self, caminho: str) -> str | None:
        real = _normalizar(caminho)
        dist = self.dono.get(real)
        if dist is None:
            self._site_de(real)
            dist = self.dono.get(real) or self._por_modulo(real)
        if dist is None:
            return None
        chave = f"{dist.metadata['Name']}/{dist.version}"
        self.por_chave.setdefault(chave, dist)
        return chave

    def componente(self, chave: str) -> Componente:
        nome, versao = chave.split("/", 1)
        dist = self.por_chave.get(chave) or importlib.metadata.distribution(nome)
        meta = dist.metadata
        licenca = meta.get("License-Expression") or ""
        if not licenca:
            curta = (meta.get("License") or "").strip()
            licenca = curta if curta and len(curta) < 80 and "\n" not in curta else ""
        if not licenca:
            licenca = "; ".join(c.split("::")[-1].strip() for c in meta.get_all("Classifier") or []
                                if c.startswith("License ::"))
        pagina = ""
        for url in meta.get_all("Project-URL") or []:
            rotulo, _, endereco = url.partition(",")
            if re.sub("[^a-z]", "", rotulo.lower()) in ("homepage", "home", "source", "repository", "sourcecode"):
                pagina = endereco.strip()
                break
        pagina = pagina or meta.get("Home-page") or ""
        textos = []
        for f in dist.files or []:
            partes = Path(str(f)).parts
            if partes and partes[0].endswith(".dist-info") and (
                    "licenses" in partes or NOME_LICENCA.match(partes[-1])):
                textos.append(str(dist.locate_file(f)))
        info = getattr(dist, "_path", None)  # pasta .dist-info (sem RECORD, como no Homebrew)
        if not textos and info and Path(info).is_dir():
            textos = [str(f) for f in sorted(Path(info).rglob("*")) if f.is_file() and
                      ("licenses" in f.relative_to(info).parts or NOME_LICENCA.match(f.name))]
        return Componente(chave=f"pypi:{chave}", nome=meta["Name"], versao=versao,
                          licenca=_corrigir_licenca(meta["Name"].lower(), licenca), origem=self.origem,
                          pagina=pagina, fontes=[{"tipo": "pypi", "nome": meta["Name"], "versao": versao}],
                          textos=textos)


# --------------------------------------------------------------------------- inventário
class Inventario:
    def __init__(self, resolvedores, projeto: Path, trabalho: Path):
        self.resolvedores = resolvedores
        # Código do próprio Arruma (o ambiente Python do macOS também fica dentro do projeto).
        self.proprios = [_normalizar(str(projeto / d)) + "/" for d in ("arruma", "packaging")]
        self.trabalho = _normalizar(str(trabalho))
        self.contagem: dict[tuple[int, str], int] = {}
        self.desconhecidos: list[tuple[str, str]] = []

    def _contar(self, indice: int, chave: str) -> None:
        self.contagem[(indice, chave)] = self.contagem.get((indice, chave), 0) + 1

    def _por_nome(self, nomes: tuple[str, str]) -> tuple[int, str] | None:
        for i, r in enumerate(self.resolvedores):
            procura = getattr(r, "pacote_por_nome", None)
            if procura:
                for nome in nomes:
                    chave = procura(nome)
                    if chave:
                        return i, chave
        return None

    def atribuir(self, caminho: str, tipo: str) -> None:
        normal = _normalizar(caminho)
        if normal.startswith(tuple(self.proprios)):
            return
        for i, r in enumerate(self.resolvedores):
            chave = r.pacote_de(caminho)
            if chave:
                self._contar(i, chave)
                return
        nome = os.path.basename(normal)
        if nome == "gschemas.compiled" and self._esquemas(normal):
            return
        if nome in GERADOS:
            achado = self._por_nome(GERADOS[nome])
            if achado:
                self._contar(*achado)
                return
        if nome == "base_library.zip":
            for i, r in enumerate(self.resolvedores):
                chave = r.pacote_de(sys.executable) or r.pacote_de(os.path.join(sys.base_prefix, "bin", "python3"))
                if chave:
                    self._contar(i, chave)
                    return
        if normal.startswith(self.trabalho + "/"):
            achado = self._pyinstaller()
            if achado:
                self._contar(*achado)
                return
        self.desconhecidos.append((caminho, tipo))

    def _esquemas(self, compilado: str) -> bool:
        """O gschemas.compiled que o PyInstaller compila junta os esquemas de vários pacotes
        (glib, gtk3, gsettings-desktop-schemas...): conta cada pacote que forneceu um esquema."""
        pasta = Path(compilado).parent
        for antecessor in Path(compilado).parents:
            if antecessor.name == "_pyi_gschema_compilation":
                pasta = antecessor
                break
        donos: set[tuple[int, str]] = set()
        for fonte in sorted(pasta.rglob("*")) if pasta.is_dir() else []:
            if not fonte.is_file() or not fonte.name.endswith((".gschema.xml", ".gschema.override", ".enums.xml")):
                continue
            for i, r in enumerate(self.resolvedores):
                for dados in getattr(r, "pastas_dados", lambda: [])():
                    original = Path(dados) / "glib-2.0" / "schemas" / fonte.name
                    chave = r.pacote_de(str(original)) if original.exists() else None
                    if chave:
                        donos.add((i, chave))
                        break
                else:
                    continue
                break
        if donos:
            glib = self._por_nome(GERADOS["gschemas.compiled"])  # o compilador vem do glib
            if glib:
                donos.add(glib)
        for dono in donos:
            self._contar(*dono)
        return bool(donos)

    def _pyinstaller(self) -> tuple[int, str] | None:
        try:
            import PyInstaller
        except ImportError:
            return None
        for i, r in enumerate(self.resolvedores):
            chave = r.pacote_de(PyInstaller.__file__)
            if chave:
                return i, chave
        return None

    def componentes(self) -> dict[str, Componente]:
        pyi = self._pyinstaller()
        if pyi and pyi not in self.contagem:
            self.contagem[pyi] = 0  # o carregador vai dentro do executável e não aparece nas listas
        por_resolvedor: dict[int, list[str]] = {}
        for (i, chave) in self.contagem:
            por_resolvedor.setdefault(i, []).append(chave)
        resultado: dict[str, Componente] = {}
        for i, chaves in por_resolvedor.items():
            r = self.resolvedores[i]
            if hasattr(r, "carregar_info"):
                r.carregar_info(sorted({c.split("/", 1)[0] for c in chaves}))
            for chave in sorted(chaves):
                comp = r.componente(chave)
                comp.ficheiros = self.contagem[(i, chave)]
                if pyi == (i, chave):
                    comp.licenca = LICENCAS_CORRIGIDAS["pyinstaller"]
                    comp.notas.append("O carregador (bootloader) do PyInstaller vai dentro do Arruma.exe / "
                                      "Arruma.app; a exceção da sua licença permite distribuí-lo assim.")
                if comp.nome == "freetype" and escolher_licenca(comp.licenca).startswith("FTL"):
                    comp.notas.append(f"Portions of this software are copyright © {_ano_freetype(comp)} "
                                      "The FreeType Project (https://freetype.org). All rights reserved.")
                if comp.nome in COMPILADOS_COM_CARGO:
                    comp.cargo = True  # a nota sobre as crates depende da versão (ver escrever())
                resultado[comp.chave] = comp
        return resultado


def _ano_freetype(comp: Componente) -> int:
    """Ano da versão da FreeType, que a FTL pede no aviso («Portions of this software are copyright © <ano>»).

    Vem do cabeçalho freetype.h instalado com o pacote («Copyright (C) 1996-AAAA»), que se procura
    a partir dos textos da licença (share/licenses/freetype no MSYS2, raiz do keg no Homebrew)."""
    anos: list[int] = []
    for texto in comp.textos:
        for pasta in list(Path(texto).parents)[:4]:
            cabecalho = pasta / "include" / "freetype2" / "freetype" / "freetype.h"
            if cabecalho.is_file():
                anos += [int(a) for a in re.findall(r"Copyright \(C\) \d{4}-(\d{4})",
                                                     cabecalho.read_text(encoding="utf-8", errors="replace"))]
    if not anos:
        for texto in comp.textos:
            if Path(texto).is_file():
                anos += [int(a) for a in re.findall(r"\b(?:19|20)\d{2}\b",
                                                     Path(texto).read_text(encoding="utf-8", errors="replace"))]
    return max(anos) if anos else datetime.date.today().year


def _pasta_segura(nome: str, usadas: set[str]) -> str:
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", nome).strip(" .") or "componente"
    pasta, n = base, 2
    while pasta.casefold() in usadas:
        pasta, n = f"{base}-{n}", n + 1
    usadas.add(pasta.casefold())
    return pasta


def escrever(componentes: dict[str, Componente], destino: Path, versao: str, sistema: str,
             projeto: Path, referencia: str = "", publicada: bool = False,
             execucao: str = "") -> list[tuple[str, str, str]]:
    """Escreve a pasta de licenças e devolve as entradas a juntar ao a.datas do PyInstaller."""
    if destino.exists():
        shutil.rmtree(destino)
    destino.mkdir(parents=True)
    (destino / "Arruma").mkdir()
    shutil.copyfile(projeto / "LICENSE", destino / "Arruma" / "LICENSE")
    padrao = destino / "textos-padrao"
    padrao.mkdir()
    usadas = {"arruma", "textos-padrao"}
    precisos: set[str] = set()
    origem_txt, distribuidor = {
        "windows": ("pelo MSYS2 (https://www.msys2.org)", "o MSYS2"),
        "macos": ("pelo Homebrew (https://brew.sh) e pelo PyPI (https://pypi.org)", "o Homebrew"),
    }[sistema]
    linhas_comp: list[str] = []
    for comp in sorted(componentes.values(), key=lambda c: c.nome.casefold()):
        pasta = _pasta_segura(comp.nome, usadas)
        copiados = []
        for i, texto in enumerate(comp.textos):
            origem = Path(texto)
            if not origem.is_file():
                continue
            nome = re.sub(r'[<>:"/\\|?*]', "_", origem.name)
            if (destino / pasta / nome).exists():
                nome = f"{i}-{nome}"
            (destino / pasta).mkdir(exist_ok=True)
            shutil.copyfile(origem, destino / pasta / nome)
            copiados.append(f"{pasta}/{nome}")
        precisos.update(_textos_padrao(comp.licenca))
        comp.textos = copiados
        fontes = [f["url"] if "url" in f else f"https://pypi.org/project/{f['nome']}/{f['versao']}/#files"
                  for f in comp.fontes]
        bloco = [f"{comp.nome} {comp.versao}", f"  Licença: {comp.licenca}"]
        escolha = escolha_do_componente(comp)
        if escolha != comp.licenca:
            bloco.append(f"  Distribuído nos termos de: {escolha}")
        if comp.pagina:
            bloco.append(f"  Página: {comp.pagina}")
        bloco += [f"  Código-fonte: {u}" for u in fontes]
        if copiados:
            bloco.append("  Textos: " + ", ".join(copiados))
        notas = list(comp.notas)
        if comp.crates and Path(comp.crates).is_dir():
            shutil.copytree(comp.crates, destino / pasta / "crates")
            precisos.update(_textos_padrao_crates([_licenca_crate_spdx(lic) for lic in comp.crates_sem_texto]))
            comp.crates = f"{pasta}/crates"
            bloco.append(f"  Bibliotecas Rust: {comp.crates}/CRATES.txt ({comp.n_crates} crates do Cargo.lock, "
                         "com os textos das licenças)")
        if comp.cargo:
            arquivo = re.sub(r"[^A-Za-z0-9.+-]+", "-", f"{comp.nome} {comp.versao}")  # como no fontes.py
            if comp.crates_lock_gerado:
                lock_txt = (f"listadas num Cargo.lock gerado na construção do Arruma (o código-fonte do {comp.nome} "
                            f"não traz um, e as versões podem não ser exatamente as que {distribuidor} compilou)")
            else:
                lock_txt = f"listadas no Cargo.lock do código-fonte do {comp.nome}"
            textos_txt = (f"A lista, com a licença de cada uma e os textos que cada pacote traz, está em "
                          f"{comp.crates}. " if comp.crates else
                          "Os textos das licenças delas não foram incluídos nesta construção; estão, com o código, "
                          "no código-fonte de terceiros das versões publicadas. ")
            onde = (f"O código delas está no código-fonte de terceiros que acompanha esta versão (ficheiro "
                    f"{arquivo}-crates.tar.gz)." if publicada or execucao else
                    "O packaging/licencas/fontes.py do Arruma junta esse código-fonte." if not comp.crates else
                    "O código delas está no código-fonte de terceiros das versões publicadas (o "
                    "packaging/licencas/fontes.py do Arruma junta-o).")
            notas.append(f"Inclui bibliotecas Rust (crates) ligadas estaticamente, {lock_txt}; cada uma tem a sua "
                         f"licença (sobretudo MIT e Apache-2.0). {textos_txt}{onde}")
        bloco += [f"  Nota: {n}" for n in notas]
        linhas_comp.append("\n".join(bloco))
    for nome in sorted(precisos):
        shutil.copyfile(projeto / "LICENSE" if nome == "GPL-3.0.txt" else TEXTOS_PADRAO / nome, padrao / nome)
    if sistema == "macos":
        alteracoes = ("O Arruma usa-os sem os alterar, exceto no que o PyInstaller faz em qualquer aplicação para\n"
                      "macOS: reescreve os caminhos das bibliotecas dinâmicas e a assinatura de cada binário e\n"
                      "volta a gerar os typelibs e as caches do GTK (ver packaging/pyinstaller/arruma.spec no\n"
                      "código-fonte do Arruma).")
    else:
        alteracoes = "O Arruma usa-os sem os alterar."
    referencia = referencia or f"etiqueta v{versao}"
    tar = f"Arruma-{versao}-codigo-fonte-terceiros-{sistema}.tar"
    if publicada:
        fontes_txt = ("- Esta versão está publicada em\n"
                      f"  {REPOSITORIO}/releases/tag/v{versao}.\n"
                      f"  Na mesma página está o ficheiro {tar},\n"
                      "  com o código-fonte correspondente de todos os componentes desta lista.")
    elif execucao:
        fontes_txt = ("- Esta é uma versão de teste, que não foi publicada em Releases. O código-fonte\n"
                      "  correspondente de todos os componentes desta lista está na mesma execução do\n"
                      f"  GitHub Actions que a construiu, no artefacto «{ARTEFACTO_FONTES}»:\n"
                      f"  {execucao}\n"
                      "  e fica disponível durante o mesmo tempo que os instaladores.")
    else:
        fontes_txt = ("- Esta versão não é acompanhada do código-fonte dos componentes, que está no\n"
                      "  endereço indicado para cada um na lista abaixo. Quem a distribuir tem de cumprir\n"
                      "  a GPL e a LGPL, por exemplo disponibilizando esse código-fonte no mesmo sítio.\n"
                      f"  As versões publicadas em {REPOSITORIO}/releases\n"
                      "  trazem-no na mesma página.")
    cabecalho = f"""Arruma {versao}: componentes de outros autores
(Third-party components included in this build, their licenses and where to get their source code.)

O Arruma é software livre: podes redistribuí-lo e alterá-lo nos termos da GNU General
Public License, versão 3 ou (à tua escolha) qualquer versão posterior. É distribuído sem
qualquer garantia. O texto da licença está em Arruma/LICENSE. Código-fonte do Arruma:
{REPOSITORIO} ({referencia}).

Esta versão para {'Windows' if sistema == 'windows' else 'macOS'} inclui os componentes abaixo, de outros autores, tal como
são distribuídos {origem_txt}.
As alterações que {distribuidor} tenha aplicado estão incluídas no código-fonte de cada
componente. {alteracoes}
A combinação é distribuída nos termos da GPL versão 3 ou posterior. Cada componente mantém
a sua licença; os textos estão na pasta com o nome do componente e, para as licenças mais
comuns, em textos-padrao. Quando uma licença deixa escolher, a opção usada aparece em
«Distribuído nos termos de» e é sempre compatível com a GPL versão 3 ou posterior. Os
programas que o Arruma apenas executa (no Windows, pdftotext e pdftoppm) e os ficheiros de
dados (temas de ícones) formam com ele apenas um agregado (secção 5 da GPL versão 3), a que
a licença do Arruma não se estende.

Código-fonte dos componentes
{fontes_txt}
- Se o código-fonte de algum componente deixar de estar disponível, abre um pedido em
  {REPOSITORIO}/issues.

Componentes ({len(componentes)}):
"""
    (destino / "LEIA-ME.txt").write_text(cabecalho + "\n\n".join(linhas_comp) + "\n", encoding="utf-8")
    (destino / "componentes.json").write_text(json.dumps(
        {"versao": versao, "sistema": sistema, "referencia": referencia, "publicada": publicada,
         "execucao": execucao,
         "componentes": [asdict(c) for c in componentes.values()]},
        ensure_ascii=False, indent=2), encoding="utf-8")
    entradas = []
    for f in sorted(destino.rglob("*")):
        if f.is_file():
            entradas.append(("licencas/" + f.relative_to(destino).as_posix(), str(f), "DATA"))
    return entradas


def gerar(analise, destino: Path, projeto: Path, trabalho: Path, versao: str,
          referencia: str = "", publicada: bool = False, execucao: str = "") -> Resultado:
    """Inventário completo para o arruma.spec (Windows com MSYS2, macOS com Homebrew e pip)."""
    if sys.platform == "win32":
        resolvedores, sistema = [Msys2()], "windows"
    elif sys.platform == "darwin":
        # Primeiro o pip: há fórmulas do Homebrew que trazem pacotes Python de outros projetos
        # (por exemplo, typing_extensions dentro da fórmula pydantic).
        resolvedores, sistema = [Pip(), Homebrew()], "macos"
    else:
        raise SystemExit("O inventário de licenças só existe para Windows e macOS.")
    inv = Inventario(resolvedores, projeto, trabalho)
    for caminho, tipo in ficheiros_recolhidos(analise.binaries, analise.datas, analise.pure, analise.scripts):
        inv.atribuir(caminho, tipo)
    componentes = inv.componentes()
    juntar_textos_crates(componentes, trabalho / "crates")
    entradas = escrever(componentes, destino, versao, sistema, projeto, referencia, publicada, execucao)
    return Resultado(componentes, inv.desconhecidos, entradas)


def _url_fonte(fonte: dict) -> str:
    if fonte.get("tipo") == "pypi":
        import fontes
        return fontes._sdist(fonte["nome"], fonte["versao"]) or ""
    return fonte.get("url", "")


def juntar_textos_crates(componentes: dict[str, Componente], trabalho: Path) -> None:
    """Junta os textos das licenças das bibliotecas Rust de cada componente compilado com o cargo,
    para irem dentro do instalador (a MIT e a Apache-2.0 pedem que acompanhem cada cópia).

    No GitHub Actions, qualquer falha faz parar a construção, tal como uma crate com licença
    incompatível com a GPL-3.0 ou sem texto nenhum (nem no pacote nem nos textos-padrão). Numa
    construção local sem cargo ou sem rede, o aviso diz que esses textos não foram incluídos."""
    import fontes

    no_ci = os.environ.get("GITHUB_ACTIONS") == "true"
    feitos: dict[tuple[str, str], dict] = {}
    for comp in sorted(componentes.values(), key=lambda c: c.chave):
        if not comp.cargo:
            continue
        chave = (comp.nome, comp.versao)  # o mesmo pacote pode vir do pip e do Homebrew
        if chave not in feitos:
            destino = trabalho / re.sub(r"[^A-Za-z0-9.+-]+", "-", f"{comp.nome}-{comp.versao}")
            shutil.rmtree(destino, ignore_errors=True)
            try:
                urls = [_url_fonte(f) for f in comp.fontes]
                if not all(urls):
                    raise RuntimeError("não foi possível saber onde está o código-fonte (PyPI sem resposta?)")
                info = fontes.textos_crates(f"{comp.nome} {comp.versao}", urls, destino)
                print(f"Bibliotecas Rust de {comp.nome} {comp.versao}: {info['n']} crates")
            except Exception as e:  # noqa: BLE001 (numa construção local, qualquer falha só dá um aviso)
                if no_ci:
                    raise SystemExit(f"Não foi possível juntar os textos das bibliotecas Rust de {comp.nome}: {e}")
                print(f"AVISO: textos das bibliotecas Rust de {comp.nome} não incluídos ({e})")
                feitos[chave] = {"pasta": "", "n": 0, "gerado": False, "sem_texto": []}
                continue
            problemas = problemas_crates(info.get("licencas", []), info["sem_texto"])
            if problemas:
                mensagem = f"Bibliotecas Rust de {comp.nome}: " + "; ".join(problemas)
                if no_ci:
                    raise SystemExit(mensagem)
                print(f"AVISO: {mensagem}")
            feitos[chave] = {"pasta": str(destino), **info}
        info = feitos[chave]
        comp.crates, comp.n_crates = info["pasta"], info["n"]
        comp.crates_lock_gerado, comp.crates_sem_texto = info["gerado"], list(info["sem_texto"])
