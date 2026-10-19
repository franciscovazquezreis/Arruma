# SPDX-License-Identifier: GPL-3.0-or-later
"""Junta o código-fonte dos componentes de terceiros de uma versão do Arruma.

Lê os componentes-*.json gerados pelas construções de Windows e macOS (terceiros.py) e
descarrega o código-fonte exato de cada componente: o arquivo .src.tar.zst do MSYS2, o arquivo
original, os remendos e a receita do Homebrew, ou o sdist do PyPI. O resultado é um arquivo .tar
por sistema, publicado na mesma versão (Releases) que os instaladores, como pedem a GPL e a LGPL.

Uso:
  python fontes.py --verificar componentes-*.json        só confirma que cada endereço existe
  python fontes.py --saida PASTA componentes-*.json      descarrega e cria os arquivos .tar
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
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
    for indice in indices:
        dados = json.loads(indice.read_text(encoding="utf-8"))
        sistema = dados["sistema"]
        lista = por_sistema.setdefault(sistema, [])
        vistos = {u for _, u in lista}
        for comp in dados["componentes"]:
            rotulo = f"{comp['nome']} {comp['versao']}"
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
    return falhas


def descarregar(por_sistema: dict[str, list[tuple[str, str]]], saida: Path, versao: str) -> int:
    falhas = 0
    saida.mkdir(parents=True, exist_ok=True)
    for sistema, lista in sorted(por_sistema.items()):
        pasta = saida / f"fontes-{sistema}"
        pasta.mkdir(parents=True, exist_ok=True)
        somas = []
        for rotulo, url in lista:
            for alternativa in _alternativas(url) if url.startswith("http") else []:
                nome = Path(urllib.parse.urlparse(alternativa).path).name or "fonte"
                if (pasta / nome).exists():
                    nome = hashlib.sha256(alternativa.encode()).hexdigest()[:8] + "-" + nome
                try:
                    with _pedido(alternativa) as resposta, open(pasta / nome, "wb") as f:
                        soma = hashlib.sha256()
                        while bloco := resposta.read(1 << 20):
                            f.write(bloco)
                            soma.update(bloco)
                    somas.append(f"{soma.hexdigest()}  {nome}  ({rotulo}; {alternativa})")
                    print(f"ok    {rotulo}: {nome}")
                    break
                except urllib.error.HTTPError as e:
                    if e.code not in (404, 410):
                        raise
            else:
                print(f"FALTA {rotulo}: {url}")
                falhas += 1
        (pasta / "SHA256SUMS.txt").write_text("\n".join(somas) + "\n", encoding="utf-8")
        arquivo = saida / f"Arruma-{versao}-codigo-fonte-terceiros-{sistema}.tar"
        with tarfile.open(arquivo, "w") as tar:
            tar.add(pasta, arcname=f"Arruma-{versao}-codigo-fonte-terceiros-{sistema}")
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
