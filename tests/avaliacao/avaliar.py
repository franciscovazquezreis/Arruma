# SPDX-License-Identifier: GPL-3.0-or-later
"""Corre o planeador do Arruma sobre o corpus de avaliação e guarda o plano em JSON.

Funciona com qualquer versão do código (antiga ou nova), porque só usa a API pública
scan() + Planner(...).build(). Nada é alterado no disco: o plano não é aplicado.

Uso: python3 avaliar.py --codigo <pasta com o pacote arruma> --corpus <pasta> --saida plano.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--codigo", required=True, help="pasta que contém o pacote «arruma»")
    ap.add_argument("--corpus", required=True, help="pasta criada pelo gerar_corpus.py")
    ap.add_argument("--saida", required=True)
    ap.add_argument("--modelo", default="qwen2.5:3b")
    ap.add_argument("--sem-ia", action="store_true")
    args = ap.parse_args()

    sys.path.insert(0, os.path.abspath(args.codigo))
    import arruma
    from arruma.core import taxonomy as tx
    from arruma.core.db import Database
    from arruma.core.planner import MODE_INSIDE, Planner
    from arruma.core.scanner import scan
    from arruma.core.settings import Settings

    tmp = Path(tempfile.mkdtemp(prefix="arruma-aval-"))
    work = tmp / "Bagunça"
    shutil.copytree(Path(args.corpus) / "Bagunça", work)
    settings = Settings(use_ai=not args.sem_ia, model=args.modelo)

    started = time.monotonic()
    result = scan(str(work))
    plan = Planner(result, settings, MODE_INSIDE, db=Database(tmp / "avaliacao.db")).build()
    seconds = time.monotonic() - started

    def rel(path: str) -> str:
        return os.path.relpath(path, work).replace(os.sep, "/") if path else ""

    existing = sorted(rel(str(p)) for p in work.rglob("*") if p.is_dir())
    out = {
        "versao": getattr(arruma, "__version__", "?"),
        "modelo": plan.ai_model,
        "documentos_ia": plan.ai_count,
        "notas": plan.notes,
        "segundos": round(seconds, 1),
        "areas": {area: list(subs) for area, subs in tx.AREAS.items()},
        "pastas_existentes": existing,
        "mantidas": [rel(p) for p, _ in plan.respected],
        "acoes": [{
            "op": a.op,
            "origem": rel(a.src),
            "destino": rel(a.dst),
            "fonte": a.source,
            "certeza": round(a.confidence, 2),
            "motivo": a.reason,
        } for a in plan.actions],
    }
    Path(args.saida).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(plan.actions)} ações em {seconds:.0f} s; IA: {plan.ai_model or 'nenhuma'} "
          f"({plan.ai_count} documentos). Notas: {plan.notes}")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
