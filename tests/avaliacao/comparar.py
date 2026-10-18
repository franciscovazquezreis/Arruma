# SPDX-License-Identifier: GPL-3.0-or-later
"""Compara dois planos (antes/depois) do avaliar.py e escreve um relatório em Markdown.

Uso: python3 comparar.py --antes antes.json --depois depois.json --esperado esperado.json --saida relatorio.md
(qualquer um dos planos pode faltar; nesse caso o relatório mostra só o outro).
"""

from __future__ import annotations

import argparse
import json
import posixpath
from collections import defaultdict
from pathlib import Path


def analisar(plano: dict, esperado: dict[str, list[str]]) -> dict:
    areas: dict[str, list[str]] = plano["areas"]
    existentes = set(plano["pastas_existentes"]) | {"."}
    por_origem = {a["origem"]: a for a in plano["acoes"]}

    def area_de(destino: str) -> tuple[str, int]:
        partes = destino.split("/")
        for i, p in enumerate(partes[:-1]):
            if p in areas:
                return p, i
        return "?", -1

    documentos = []
    inventadas: set[str] = set()
    for rel, aceites in esperado.items():
        a = por_origem.get(rel)
        destino = a["destino"] if a and a["op"] == "move" else rel
        area, i = area_de(destino)
        partes = destino.split("/")
        if i >= 0 and len(partes) - i > 2 and partes[i + 1] not in areas[area]:
            inventadas.add(f"{area}/{partes[i + 1]}")
        documentos.append({
            "ficheiro": rel, "aceites": aceites, "destino": destino, "area": area,
            "certo": area in aceites, "fonte": a["fonte"] if a else "fica",
            "certeza": a["certeza"] if a else None,
        })

    # Árvore final das pastas novas
    filhos: dict[str, set[str]] = defaultdict(set)
    for a in plano["acoes"]:
        if a["op"] not in ("move", "move_dir") or not a["destino"]:
            continue
        caminho = a["destino"]
        while True:
            pai = posixpath.dirname(caminho) or "."
            filhos[pai].add(caminho)
            if pai == ".":
                break
            caminho = pai
    novas = sorted(d for d in filhos if d not in existentes)
    singulares = [d for d in novas if len(filhos[d]) == 1]
    profundidade = max((d.count("/") + 1 for d in novas), default=0)
    renomeados = [(a["origem"], posixpath.basename(a["destino"])) for a in plano["acoes"]
                  if a["op"] == "move" and posixpath.basename(a["destino"]) != posixpath.basename(a["origem"])]
    return {
        "documentos": documentos,
        "certos": sum(d["certo"] for d in documentos),
        "total": len(documentos),
        "novas": novas,
        "filhos": filhos,
        "singulares": singulares,
        "inventadas": sorted(inventadas),
        "profundidade": profundidade,
        "renomeados": renomeados,
        "plano": plano,
    }


def arvore(r: dict) -> list[str]:
    linhas: list[str] = []
    filhos = r["filhos"]
    novas = set(r["novas"])

    def desenhar(pasta: str, nivel: int) -> None:
        for filho in sorted(filhos.get(pasta, ())):
            nome = posixpath.basename(filho)
            if filho in filhos:
                marca = " (nova)" if filho in novas else ""
                linhas.append(f"{'    ' * nivel}{nome}/{marca}  [{len(filhos[filho])}]")
                desenhar(filho, nivel + 1)
            else:
                linhas.append(f"{'    ' * nivel}{nome}")
    desenhar(".", 0)
    return linhas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--antes")
    ap.add_argument("--depois")
    ap.add_argument("--esperado", required=True)
    ap.add_argument("--saida", required=True)
    args = ap.parse_args()
    esperado = json.loads(Path(args.esperado).read_text(encoding="utf-8"))
    versoes = {}
    for nome, ficheiro in (("Antes", args.antes), ("Depois", args.depois)):
        if ficheiro and Path(ficheiro).exists():
            versoes[nome] = analisar(json.loads(Path(ficheiro).read_text(encoding="utf-8")), esperado)
    if not versoes:
        raise SystemExit("Nenhum plano para comparar.")

    md: list[str] = ["# Avaliação da organização com IA local", ""]
    nomes = list(versoes)
    md.append("| Indicador | " + " | ".join(nomes) + " |")
    md.append("|---|" + "---|" * len(nomes))

    def linha(rotulo: str, fn) -> None:
        md.append(f"| {rotulo} | " + " | ".join(str(fn(versoes[n])) for n in nomes) + " |")

    linha("Versão / modelo", lambda r: f"{r['plano']['versao']} / {r['plano']['modelo'] or 'sem IA'}")
    linha("Documentos lidos pela IA", lambda r: r["plano"]["documentos_ia"])
    linha("Documentos na área certa", lambda r: f"{r['certos']} de {r['total']}")
    linha("Pastas novas", lambda r: len(r["novas"]))
    linha("Pastas novas com um só item", lambda r: len(r["singulares"]))
    linha("Subpastas fora da taxonomia (inventadas)", lambda r: len(r["inventadas"]))
    linha("Profundidade máxima", lambda r: r["profundidade"])
    linha("Ficheiros com nome novo", lambda r: len(r["renomeados"]))
    linha("Tempo (s)", lambda r: r["plano"]["segundos"])
    md.append("")
    for n in nomes:
        notas = versoes[n]["plano"]["notas"]
        if notas:
            md.append(f"**Notas ({n}):** " + " ".join(notas))
            md.append("")

    md += ["## Documentos", "", "| Ficheiro | Esperado | " + " | ".join(nomes) + " |",
           "|---|---|" + "---|" * len(nomes)]
    for i, doc in enumerate(next(iter(versoes.values()))["documentos"]):
        celulas = []
        for n in nomes:
            d = versoes[n]["documentos"][i]
            marca = "✅" if d["certo"] else "❌"
            celulas.append(f"{marca} `{d['destino']}` ({d['fonte']})")
        md.append(f"| `{doc['ficheiro']}` | {', '.join(doc['aceites'])} | " + " | ".join(celulas) + " |")
    md.append("")

    for n in nomes:
        r = versoes[n]
        md += [f"## Árvore proposta: {n}", "", "```"] + arvore(r) + ["```", ""]
        if r["inventadas"]:
            md.append("Subpastas inventadas: " + ", ".join(f"`{x}`" for x in r["inventadas"]))
            md.append("")
        if r["renomeados"]:
            md.append(f"Nomes novos ({n}):")
            md.append("")
            md += [f"- `{a}` → `{b}`" for a, b in r["renomeados"]]
            md.append("")
    Path(args.saida).write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
