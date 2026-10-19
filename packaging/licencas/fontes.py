# SPDX-License-Identifier: GPL-3.0-or-later
"""Junta o código-fonte dos componentes de terceiros de uma versão do Arruma.

Lê os componentes-*.json gerados pelas construções de Windows e macOS (terceiros.py) e
descarrega o código-fonte exato de cada componente: o arquivo .src.tar.zst do MSYS2, o arquivo
original, os remendos e a receita do Homebrew, ou o sdist do PyPI. O resultado é um ficheiro .tar
por sistema, que acompanha os instaladores (na mesma execução do GitHub Actions e, nas versões
publicadas, na mesma página de Releases): é assim que se cumpre a GPL e a LGPL sem ter de
prometer o envio do código-fonte mais tarde.

Uso:
  python fontes.py --verificar componentes-*.json        só confirma que cada endereço existe
  python fontes.py --saida PASTA componentes-*.json      descarrega e cria os arquivos .tar
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

AGENTE = "Arruma-fontes/1.0 (+https://github.com/franciscovazquezreis/Arruma)"


def _pedido(url: str, metodo: str = "GET", tentativas: int = 4):
    erro: Exception | None = None
    for n in range(tentativas):
        try:
            pedido = urllib.request.Request(url, method=metodo, headers={"User-Agent": AGENTE})
            return urllib.request.urlopen(pedido, timeout=120)
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                raise
            erro = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            erro = e
        time.sleep(2 ** (n + 1))
    raise erro  # type: ignore[misc]


def _transferir(url: str, ficheiro: Path, tentativas: int = 4) -> str:
    """Descarrega url para ficheiro (através de um .part) e devolve o SHA-256.

    Repete quando a rede falha a meio, e só dá a transferência por boa quando chegaram todos os
    bytes anunciados. Um 404 ou 410 sai logo como HTTPError."""
    parcial = ficheiro.with_name(ficheiro.name + ".part")
    erro: Exception | None = None
    for n in range(tentativas):
        try:
            pedido = urllib.request.Request(url, headers={"User-Agent": AGENTE})
            with urllib.request.urlopen(pedido, timeout=120) as resposta, open(parcial, "wb") as f:
                esperado = resposta.headers.get("Content-Length")
                soma, total = hashlib.sha256(), 0
                while bloco := resposta.read(1 << 20):
                    f.write(bloco)
                    soma.update(bloco)
                    total += len(bloco)
            if esperado and esperado.isdigit() and int(esperado) != total:
                raise ConnectionError(f"transferência incompleta ({total} de {esperado} bytes)")
            os.replace(parcial, ficheiro)
            return soma.hexdigest()
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                parcial.unlink(missing_ok=True)
                raise
            erro = e
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            erro = e
        time.sleep(2 ** (n + 1))
    parcial.unlink(missing_ok=True)
    raise ConnectionError(f"{url}: {erro}")


def _existe(url: str) -> bool:
    for metodo in ("HEAD", "GET"):
        try:
            with _pedido(url, metodo) as resposta:
                return resposta.status < 400
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return False
            if metodo == "GET":
                return False
        except Exception:  # noqa: BLE001
            if metodo == "GET":
                return False
    return False


def _sdist(nome: str, versao: str) -> str | None:
    try:
        with _pedido(f"https://pypi.org/pypi/{urllib.parse.quote(nome)}/{urllib.parse.quote(versao)}/json") as r:
            dados = json.load(r)
    except Exception:  # noqa: BLE001
        return None
    for ficheiro in dados.get("urls", []):
        if ficheiro.get("packagetype") == "sdist":
            return ficheiro["url"]
    return None


def enderecos(indices: list[Path]) -> dict[str, list[tuple[str, str]]]:
    """Para cada sistema, a lista (componente, endereço) do código-fonte, sem repetições."""
    por_sistema: dict[str, list[tuple[str, str]]] = {}
    CARGO.clear()
    for indice in indices:
        dados = json.loads(indice.read_text(encoding="utf-8"))
        sistema = dados["sistema"]
        lista = por_sistema.setdefault(sistema, [])
        vistos = {u for _, u in lista}
        for comp in dados["componentes"]:
            rotulo = f"{comp['nome']} {comp['versao']}"
            if comp.get("cargo"):
                CARGO.setdefault(sistema, set()).add(rotulo)
            for fonte in comp["fontes"]:
                if fonte.get("tipo") == "pypi":
                    url = _sdist(fonte["nome"], fonte["versao"]) or \
                        f"pypi:{fonte['nome']}=={fonte['versao']} (sem sdist)"
                else:
                    url = fonte["url"]
                if url not in vistos:
                    vistos.add(url)
                    lista.append((rotulo, url))
    return por_sistema


# Componentes com bibliotecas Rust, por sistema (preenchido por enderecos()).
CARGO: dict[str, set[str]] = {}


def _extrair(arquivo: Path, destino: Path) -> None:
    """Abre um .tar (gz, xz, bz2 ou zst) com o Python, sem depender do tar do sistema (no MSYS2,
    o tar é um programa POSIX que lê mal os caminhos do Windows)."""
    destino.mkdir(parents=True, exist_ok=True)
    if arquivo.name.endswith(".zst"):
        dados: io.BytesIO | None = None
        try:
            from compression import zstd  # Python 3.14 ou mais recente
            dados = io.BytesIO(zstd.decompress(arquivo.read_bytes()))
        except ImportError:
            if not shutil.which("zstd"):
                raise RuntimeError(f"falta o zstd para abrir {arquivo.name}") from None
            with open(arquivo, "rb") as entrada:
                dados = io.BytesIO(subprocess.run(["zstd", "-dc"], stdin=entrada, capture_output=True,
                                                  check=True).stdout)
        tar = tarfile.open(fileobj=dados)
    else:
        tar = tarfile.open(arquivo)
    with tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(destino, filter="data")
        else:  # Python sem a correção de segurança de 2023; as fontes vêm de endereços conhecidos
            tar.extractall(destino)


# «cargo update …» numa receita do MSYS2 (prepare()), com ou sem o caminho do cargo antes.
_CARGO_UPDATE = re.compile(r"^[ \t]*(?:\S*/)?cargo[ \t]+update(?:[ \t]+([^\n#]*))?[ \t]*(?:#.*)?$", re.M)


def _vendorizar(rotulo: str, arquivos: list[Path], trabalho: Path) -> tuple[Path, bool]:
    """Descarrega para <raiz>/vendor as crates exatas que o componente compila.

    Abre o código-fonte do componente (arquivo do MSYS2 ou original), repete as alterações ao
    Cargo.lock que a receita do MSYS2 faz em prepare() e usa «cargo vendor --locked». Quando o
    código-fonte não traz Cargo.lock (o libimagequant, por exemplo, resolve as versões no momento
    em que é compilado), gera-se um agora. Devolve a raiz do projeto e se o Cargo.lock foi gerado."""
    if not shutil.which("cargo"):
        raise RuntimeError("falta o cargo (Rust) para juntar as bibliotecas Rust")
    comandos: list[str] = []
    originais: list[Path] = []
    for arquivo in arquivos:
        if arquivo.name.endswith((".src.tar.zst", ".src.tar.gz", ".src.tar.xz")):
            pasta = trabalho / "receita"
            _extrair(arquivo, pasta)
            for pkgbuild in pasta.rglob("PKGBUILD"):
                texto = pkgbuild.read_text(encoding="utf-8", errors="replace")
                comandos += [c.strip() for c in _CARGO_UPDATE.findall(texto) if "$" not in c]
            originais += [f for f in pasta.rglob("*") if f.is_file() and
                          re.search(r"\.(tar\.(xz|gz|bz2|zst)|tgz)$", f.name) and
                          not f.name.endswith((".src.tar.zst", ".src.tar.gz", ".src.tar.xz"))]
        elif re.search(r"\.(tar\.(xz|gz|bz2)|tgz)$", arquivo.name):
            originais.append(arquivo)
    codigo = trabalho / "codigo"
    for original in originais:
        _extrair(original, codigo)
    locks = sorted(codigo.glob("*/Cargo.lock"))
    gerado = not locks
    if not originais:
        raise RuntimeError(f"{rotulo}: nenhum arquivo de código-fonte entre {[a.name for a in arquivos]}")
    if gerado:
        manifestos = sorted(codigo.glob("*/Cargo.toml"))
        if not manifestos:
            raise RuntimeError(f"{rotulo}: o código-fonte não tem Cargo.toml")
        raiz = manifestos[0].parent
        comandos_cargo = [["cargo", "generate-lockfile"]]
    else:
        raiz = locks[0].parent
        comandos_cargo = []
    comandos_cargo += [["cargo", "update", *shlex.split(a)] for a in comandos]
    for cmd in comandos_cargo + [["cargo", "vendor", "--locked", "--versioned-dirs", "vendor"]]:
        feito = subprocess.run(cmd, cwd=raiz, capture_output=True, text=True)
        if feito.returncode:
            raise RuntimeError(f"{' '.join(cmd)}: {feito.stderr.strip()[-800:]}")
    return raiz, gerado


def _pacote_cargo(texto: str) -> dict:
    """Secção [package] de um Cargo.toml (com o tomllib, ou à mão no Python 3.10)."""
    try:
        import tomllib
        return tomllib.loads(texto).get("package", {})
    except ImportError:
        secao = re.search(r"^\[package\]\s*$(.*?)(?=^\[|\Z)", texto, re.M | re.S)
        campos = re.findall(r'^([\w-]+)\s*=\s*"((?:[^"\\]|\\.)*)"', secao.group(1) if secao else "", re.M)
        return dict(campos)


def _crates_de(raiz: Path) -> list[dict]:
    """Nome, versão, licença e pasta de cada crate em <raiz>/vendor."""
    lista = []
    for manifesto in sorted((raiz / "vendor").glob("*/Cargo.toml")):
        pacote = _pacote_cargo(manifesto.read_text(encoding="utf-8"))
        autores = pacote.get("authors")
        lista.append({"nome": pacote.get("name", "?"), "versao": pacote.get("version", "?"),
                      "licenca": pacote.get("license") or "",
                      "ficheiro_licenca": pacote.get("license-file") or "", "pasta": manifesto.parent,
                      "autores": ", ".join(autores) if isinstance(autores, list) else ""})
    return lista


def _aviso_lock_gerado(quando: str) -> str:
    return ("O código-fonte deste componente não traz Cargo.lock: as versões foram resolvidas quando\n"
            f"{quando} e podem diferir ligeiramente das que o distribuidor compilou.\n")


_ABRANGE = ("Inclui todas as do Cargo.lock: as que ficam dentro da biblioteca compilada e também as que\n"
            "só servem para a compilar ou testar, para outros sistemas ou para programas que não vêm\n"
            "no Arruma.\n")


def crates(rotulo: str, arquivos: list[Path], destino: Path) -> Path:
    """Código-fonte das bibliotecas Rust (crates) que o componente compila, num .tar.gz com o
    Cargo.lock usado, o código de cada crate (com os textos das licenças) e uma lista com o
    nome, a versão e a licença de cada uma."""
    trabalho = Path(tempfile.mkdtemp(prefix="arruma-cargo-"))
    try:
        raiz, gerado = _vendorizar(rotulo, arquivos, trabalho)
        lista = [f"{c['nome']} {c['versao']}: {c['licenca'] or 'ver ' + (c['ficheiro_licenca'] or '?')}"
                 for c in _crates_de(raiz)]
        nome = re.sub(r"[^A-Za-z0-9.+-]+", "-", rotulo)
        (raiz / "CRATES.txt").write_text(
            f"Bibliotecas Rust (crates) do Cargo.lock de {rotulo}, com a licença de cada uma.\n" + _ABRANGE +
            "O código e os textos das licenças estão na pasta vendor/.\n"
            + (_aviso_lock_gerado("este arquivo foi criado") if gerado else "") + "\n" + "\n".join(lista) + "\n",
            encoding="utf-8")
        saida = destino / f"{nome}-crates.tar.gz"
        with tarfile.open(saida, "w:gz") as tar:
            for parte in ("CRATES.txt", "Cargo.lock", "vendor"):
                tar.add(raiz / parte, arcname=f"{nome}-crates/{parte}")
        print(f"ok    {rotulo}: {len(lista)} bibliotecas Rust em {saida.name}")
        return saida
    finally:
        shutil.rmtree(trabalho, ignore_errors=True)


# Ficheiros com o texto da licença ou os avisos de copyright de cada crate. Também se procuram em
# subpastas (o regex-syntax, por exemplo, traz o aviso da Unicode em src/unicode_tables), exceto
# nas de testes e exemplos.
_TEXTO_CRATE = re.compile(r"^(licen[cs]e|copying|copyright|notice|unlicense|authors)", re.I)
_PASTAS_SEM_TEXTOS = {"tests", "test", "examples", "example", "benches", "fuzz", ".github"}


def _textos_do_crate(pasta: Path, ficheiro_licenca: str) -> list[Path]:
    encontrados = []
    for ficheiro in sorted(pasta.rglob("*")):
        relativo = ficheiro.relative_to(pasta)
        if (ficheiro.is_file() and _TEXTO_CRATE.match(ficheiro.name)
                and not _PASTAS_SEM_TEXTOS.intersection(p.lower() for p in relativo.parts[:-1])):
            encontrados.append(ficheiro)
    if ficheiro_licenca:
        extra = pasta / ficheiro_licenca
        if (extra.is_file() and extra.resolve().is_relative_to(pasta.resolve())
                and extra.resolve() not in {f.resolve() for f in encontrados}):
            encontrados.append(extra)
    return encontrados


def copiar_textos_crates(raiz: Path, destino: Path, rotulo: str, gerado: bool = False) -> dict:
    """Copia para destino os textos das licenças de cada crate em <raiz>/vendor, sem repetir os
    que são iguais (o texto da Apache-2.0, por exemplo), e escreve destino/CRATES.txt com a lista.
    Devolve o número de crates, as licenças de todas e as das que não trazem nenhum texto."""
    textos = destino / "textos"
    textos.mkdir(parents=True, exist_ok=True)
    vistos: dict[str, str] = {}
    linhas = []
    sem_texto: set[str] = set()
    lista = _crates_de(raiz)
    for crate in lista:
        pasta: Path = crate["pasta"]
        usados: list[str] = []
        for ficheiro in _textos_do_crate(pasta, crate["ficheiro_licenca"]):
            dados = ficheiro.read_bytes()
            soma = hashlib.sha256(dados).hexdigest()[:12]
            if soma not in vistos:
                nome = f"{soma}-{re.sub(r'[^A-Za-z0-9._-]+', '_', ficheiro.name)}"
                (textos / nome).write_bytes(dados)
                vistos[soma] = f"textos/{nome}"
            onde = ficheiro.parent.relative_to(pasta).as_posix()
            referencia = vistos[soma] + (f" ({onde})" if onde != "." else "")
            if referencia not in usados:
                usados.append(referencia)
        licenca = crate["licenca"] or "ver o ficheiro da licença"
        autores = f" (autores: {crate['autores']})" if crate["autores"] and not usados else ""
        if not usados:
            sem_texto.add(licenca)
        detalhe = ", ".join(usados) if usados else "o pacote não traz o texto; ver ../../textos-padrao"
        linhas.append(f"{crate['nome']} {crate['versao']}: {licenca}{autores}\n  {detalhe}")
    (destino / "CRATES.txt").write_text(
        f"Bibliotecas Rust (crates) do Cargo.lock de {rotulo}, com a licença de cada uma e os textos\n"
        "que cada pacote traz (os textos iguais aparecem uma só vez, na pasta textos).\n" + _ABRANGE
        + (_aviso_lock_gerado("esta lista foi criada") if gerado else "") + "\n" + "\n".join(linhas) + "\n",
        encoding="utf-8")
    return {"n": len(lista), "gerado": gerado, "sem_texto": sorted(sem_texto),
            "licencas": sorted({c["licenca"] or "ver o ficheiro da licença" for c in lista})}


def textos_crates(rotulo: str, urls: list[str], destino: Path) -> dict:
    """Descarrega o código-fonte do componente, junta as crates e copia os textos das licenças
    para destino (usado pelo arruma.spec, para irem dentro do instalador)."""
    trabalho = Path(tempfile.mkdtemp(prefix="arruma-crates-"))
    try:
        arquivos = []
        for url in urls:
            obtido = _obter(url, trabalho)
            if isinstance(obtido, str):
                raise RuntimeError(f"{rotulo}: não foi possível descarregar {url} ({obtido})")
            arquivos.append(trabalho / obtido[0])
        raiz, gerado = _vendorizar(rotulo, arquivos, trabalho / "cargo")
        return copiar_textos_crates(raiz, destino, rotulo, gerado)
    finally:
        shutil.rmtree(trabalho, ignore_errors=True)


def _alternativas(url: str) -> list[str]:
    """O MSYS2 guarda alguns arquivos antigos comprimidos com gzip ou xz em vez de zstd."""
    if url.startswith("https://repo.msys2.org/") and url.endswith(".src.tar.zst"):
        base = url[:-len(".zst")]
        return [url, base + ".gz", base + ".xz"]
    return [url]


def verificar(por_sistema: dict[str, list[tuple[str, str]]]) -> int:
    falhas = 0
    for sistema, lista in sorted(por_sistema.items()):
        print(f"== {sistema}: {len(lista)} endereços")
        for rotulo, url in lista:
            ok = url.startswith("http") and any(_existe(u) for u in _alternativas(url))
            print(f"{'ok   ' if ok else 'FALTA'} {rotulo}: {url}")
            falhas += not ok
        for rotulo in sorted(CARGO.get(sistema, ())):
            with tempfile.TemporaryDirectory(prefix="arruma-verificar-") as tmp:
                try:
                    arquivos = [obtido[0] for obtido in (_obter(u, Path(tmp)) for r, u in lista if r == rotulo)
                                if not isinstance(obtido, str)]
                    crates(rotulo, [Path(tmp) / a for a in arquivos], Path(tmp))
                except (RuntimeError, subprocess.CalledProcessError, OSError) as e:
                    print(f"FALTA {rotulo}: bibliotecas Rust ({e})")
                    falhas += 1
    return falhas


def _obter(url: str, pasta: Path) -> tuple[str, str, str] | str:
    """Descarrega o código-fonte para pasta: (ficheiro, SHA-256, endereço usado) ou o motivo da falha."""
    if "://" not in url:
        return "endereço inválido"
    for alternativa in _alternativas(url):
        nome = Path(urllib.parse.unquote(urllib.parse.urlparse(alternativa).path)).name or "fonte"
        if (pasta / nome).exists():
            nome = hashlib.sha256(alternativa.encode()).hexdigest()[:8] + "-" + nome
        try:
            return nome, _transferir(alternativa, pasta / nome), alternativa
        except urllib.error.HTTPError:
            continue  # 404/410: tenta a alternativa seguinte
        except ConnectionError as e:
            return str(e)
    return "não existe"


def descarregar(por_sistema: dict[str, list[tuple[str, str]]], saida: Path, versao: str) -> int:
    falhas = 0
    saida.mkdir(parents=True, exist_ok=True)
    for sistema, lista in sorted(por_sistema.items()):
        pasta = saida / f"fontes-{sistema}"
        pasta.mkdir(parents=True, exist_ok=True)
        somas = []
        obtidos: dict[str, list[Path]] = {}
        for rotulo, url in lista:
            obtido = _obter(url, pasta)
            if isinstance(obtido, str):
                print(f"FALTA {rotulo}: {url} ({obtido})")
                falhas += 1
                continue
            nome, soma, alternativa = obtido
            # Linhas «#» com a origem; as outras no formato de sha256sum -c.
            somas += [f"# {rotulo}; {alternativa}", f"{soma}  {nome}"]
            obtidos.setdefault(rotulo, []).append(pasta / nome)
            print(f"ok    {rotulo}: {nome}")
        for rotulo in sorted(CARGO.get(sistema, ())):
            try:
                tar_crates = crates(rotulo, obtidos.get(rotulo, []), pasta)
            except (RuntimeError, subprocess.CalledProcessError, OSError) as e:
                print(f"FALTA {rotulo}: bibliotecas Rust ({e})")
                falhas += 1
                continue
            soma = hashlib.sha256(tar_crates.read_bytes()).hexdigest()
            somas += [f"# {rotulo}: bibliotecas Rust (cargo vendor --locked)", f"{soma}  {tar_crates.name}"]
        (pasta / "SHA256SUMS.txt").write_text("\n".join(somas) + "\n", encoding="utf-8")
        arquivo = saida / f"Arruma-{versao}-codigo-fonte-terceiros-{sistema}.tar"
        with tarfile.open(arquivo, "w") as tar:
            tar.add(pasta, arcname=f"Arruma-{versao}-codigo-fonte-terceiros-{sistema}")
        shutil.rmtree(pasta)  # já está no .tar; no Windows são perto de 700 MB
        print(f"{arquivo} ({arquivo.stat().st_size / 1e6:.0f} MB)")
    return falhas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("indices", nargs="+", type=Path)
    ap.add_argument("--verificar", action="store_true")
    ap.add_argument("--saida", type=Path)
    args = ap.parse_args()
    por_sistema = enderecos(args.indices)
    if args.verificar:
        falhas = verificar(por_sistema)
    else:
        if not args.saida:
            ap.error("indica --saida ou --verificar")
        versao = json.loads(args.indices[0].read_text(encoding="utf-8"))["versao"]
        falhas = descarregar(por_sistema, args.saida, versao)
    if falhas:
        print(f"{falhas} componentes sem código-fonte disponível.", file=sys.stderr)
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
