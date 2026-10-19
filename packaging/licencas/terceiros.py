# SPDX-License-Identifier: GPL-3.0-or-later
"""Avisos dos componentes de outros autores incluídos nas versões de Windows e macOS.

O arruma.spec chama gerar() depois do Analysis do PyInstaller. Cada ficheiro recolhido é
atribuído ao pacote de onde vem (MSYS2 no Windows; Homebrew ou pip no macOS) e, numa pasta
própria, ficam a lista dos componentes (LEIA-ME.txt e componentes.json), os textos das
licenças e as receitas de construção. O fontes.py usa o componentes.json para juntar o
código-fonte correspondente a cada versão publicada.
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
COMPILADOS_COM_CARGO = {"librsvg", "rav1e"}

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


@dataclass
class Resultado:
    componentes: dict[str, Componente]
    desconhecidos: list[tuple[str, str]]
    entradas: list[tuple[str, str, str]]


def _corrigir_licenca(nome: str, licenca: str) -> str:
    return LICENCAS_CORRIGIDAS.get(nome, licenca) or "não indicada"


_INCOMPATIVEL = re.compile(r"(?<!L)GPL-2\.0-only|MPL-1\.1")


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


def escolher_licenca(licenca: str) -> str:
    """Opção usada quando a licença deixa escolher: a primeira compatível com a GPL-3.0 ou posterior."""
    expr = _sem_parenteses(licenca)
    termos = _dividir(expr, "AND")
    if len(termos) > 1:
        return " AND ".join(escolher_licenca(t) for t in termos)
    alternativas = _dividir(expr, "OR")
    if len(alternativas) == 1:
        return expr
    for alternativa in alternativas:
        if not _INCOMPATIVEL.search(alternativa):
            return escolher_licenca(alternativa)
    return escolher_licenca(alternativas[0])


def _textos_padrao(licenca: str) -> list[str]:
    nomes: list[str] = []
    for marca, textos in TEXTOS_POR_LICENCA:
        if marca in licenca:
            nomes += [t for t in textos if t not in nomes]
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
        for dist in importlib.metadata.distributions():
            for f in dist.files or []:
                try:
                    self.dono.setdefault(_normalizar(str(dist.locate_file(f))), dist)
                except (OSError, ValueError):
                    continue

    def pacote_de(self, caminho: str) -> str | None:
        dist = self.dono.get(_normalizar(caminho))
        return f"{dist.metadata['Name']}/{dist.version}" if dist else None

    def componente(self, chave: str) -> Componente:
        nome, versao = chave.split("/", 1)
        dist = importlib.metadata.distribution(nome)
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
                    comp.notas.append(f"Portions of this software are copyright © {datetime.date.today().year} "
                                      "The FreeType Project (https://freetype.org). All rights reserved.")
                if comp.nome in COMPILADOS_COM_CARGO:
                    comp.cargo = True
                    comp.notas.append(f"Inclui bibliotecas Rust (crates) ligadas estaticamente, listadas no Cargo.lock "
                                      f"do código-fonte do {comp.nome}; cada uma tem a sua licença (sobretudo MIT, "
                                      "Apache-2.0 e MPL-2.0). O arquivo de código-fonte de cada versão publicada traz "
                                      "o código e os textos das licenças de todas elas.")
                resultado[comp.chave] = comp
        return resultado


def _pasta_segura(nome: str, usadas: set[str]) -> str:
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", nome).strip(" .") or "componente"
    pasta, n = base, 2
    while pasta.casefold() in usadas:
        pasta, n = f"{base}-{n}", n + 1
    usadas.add(pasta.casefold())
    return pasta


def escrever(componentes: dict[str, Componente], destino: Path, versao: str, sistema: str,
             projeto: Path, referencia: str = "", publicada: bool = False) -> list[tuple[str, str, str]]:
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
        escolha = escolher_licenca(comp.licenca)
        if escolha != comp.licenca:
            bloco.append(f"  Distribuído nos termos de: {escolha}")
        if comp.pagina:
            bloco.append(f"  Página: {comp.pagina}")
        bloco += [f"  Código-fonte: {u}" for u in fontes]
        if copiados:
            bloco.append("  Textos: " + ", ".join(copiados))
        bloco += [f"  Nota: {n}" for n in comp.notas]
        linhas_comp.append("\n".join(bloco))
    for nome in sorted(precisos):
        shutil.copyfile(projeto / "LICENSE" if nome == "GPL-3.0.txt" else TEXTOS_PADRAO / nome, padrao / nome)
    origem_txt = {"windows": "MSYS2 (https://www.msys2.org)", "macos": "Homebrew (https://brew.sh) e PyPI"}[sistema]
    if sistema == "macos":
        alteracoes = ("O Arruma usa-os sem os alterar, exceto no que o PyInstaller faz em qualquer aplicação para\n"
                      "macOS: reescreve os caminhos das bibliotecas dinâmicas e a assinatura de cada binário e\n"
                      "volta a gerar os typelibs e as caches do GTK (ver packaging/pyinstaller/arruma.spec no\n"
                      "código-fonte do Arruma).")
    else:
        alteracoes = "O Arruma usa-os sem os alterar."
    referencia = referencia or f"etiqueta v{versao}"
    if publicada:
        fontes_txt = (f"- Esta versão está publicada em {REPOSITORIO}/releases, onde está também, no\n"
                      "  mesmo sítio, um arquivo com o código-fonte correspondente de todos os componentes\n"
                      "  desta lista.")
    else:
        fontes_txt = ("- Esta é uma versão de teste, que não foi publicada em Releases: o código-fonte de\n"
                      "  cada componente está no endereço indicado na lista abaixo. As versões publicadas\n"
                      f"  em {REPOSITORIO}/releases trazem também esse código-fonte no mesmo sítio.")
    cabecalho = f"""Arruma {versao}: componentes de outros autores
(Third-party components included in this build, with their licenses and source code.)

O Arruma é software livre: podes redistribuí-lo e alterá-lo nos termos da GNU General
Public License, versão 3 ou (à tua escolha) qualquer versão posterior. É distribuído sem
qualquer garantia. O texto da licença está em Arruma/LICENSE. Código-fonte do Arruma:
{REPOSITORIO} ({referencia}).

Esta versão para {'Windows' if sistema == 'windows' else 'macOS'} inclui os componentes abaixo, de outros autores, tal como
são distribuídos pelo {origem_txt}, que podem ter aplicado as suas próprias alterações
(incluídas no código-fonte de cada componente). {alteracoes}
A combinação é distribuída nos termos da GPL versão 3 ou posterior. Cada componente mantém
a sua licença; os textos estão na pasta com o nome do componente e, para as licenças mais
comuns, em textos-padrao. Quando uma licença deixa escolher, a opção usada aparece em
«Distribuído nos termos de» e é sempre compatível com a GPL versão 3 ou posterior. Os
programas que o Arruma apenas executa (no Windows, pdftotext e pdftoppm) e os ficheiros de
dados (temas de ícones) ficam apenas agregados à combinação.

Código-fonte dos componentes
{fontes_txt}
- Durante pelo menos três anos a contar da data desta versão, qualquer pessoa pode pedir
  uma cópia completa desse código-fonte, sem custos, em {REPOSITORIO}/issues.

Componentes ({len(componentes)}):
"""
    (destino / "LEIA-ME.txt").write_text(cabecalho + "\n\n".join(linhas_comp) + "\n", encoding="utf-8")
    (destino / "componentes.json").write_text(json.dumps(
        {"versao": versao, "sistema": sistema, "referencia": referencia, "publicada": publicada,
         "componentes": [asdict(c) for c in componentes.values()]},
        ensure_ascii=False, indent=2), encoding="utf-8")
    entradas = []
    for f in sorted(destino.rglob("*")):
        if f.is_file():
            entradas.append(("licencas/" + f.relative_to(destino).as_posix(), str(f), "DATA"))
    return entradas


def gerar(analise, destino: Path, projeto: Path, trabalho: Path, versao: str,
          referencia: str = "", publicada: bool = False) -> Resultado:
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
    entradas = escrever(componentes, destino, versao, sistema, projeto, referencia, publicada)
    return Resultado(componentes, inv.desconhecidos, entradas)
