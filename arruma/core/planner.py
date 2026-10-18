# SPDX-License-Identifier: GPL-3.0-or-later
"""Construção do plano de organização (nada é alterado aqui)."""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import taxonomy as tx
from .ai import PROMPT_VERSION, AIError, LocalAI
from .classifier import KIND_BASE, Placement, classify_simple, document_placement
from .db import Database
from .extract import date_from_name, extract_text, image_info, plausible
from .fsutil import is_within, path_key, sanitize_name, split_ext, unique_path, user_dirs
from .system import is_external_mount
from .scanner import FileItem, FolderInfo, ScanResult, is_home
from .settings import Settings

MODE_INSIDE = "inside"
MODE_PERSONAL = "personal"

INSIDE_NAMES = {
    "documents": "Documentos", "pictures": "Imagens", "videos": "Vídeos", "music": "Música",
    "archives": "Ficheiros comprimidos", "installers": "Instaladores", "code": "Código",
    "other": "Outros ficheiros",
}
BASE_LABELS = INSIDE_NAMES

# Uma subpasta nova (subárea, álbum) só se cria se ficar com pelo menos MIN_GROUP itens;
# com menos, os ficheiros ficam na pasta de cima. Não se criam pastas para um só ficheiro.
MIN_GROUP = 3
# As fotografias de um ano só se dividem por meses a partir deste número.
MONTH_SPLIT_MIN = 40
_MONTH_DIR = re.compile(r"^(19|20)\d{2}-(0[1-9]|1[0-2])\b")


@dataclass
class Action:
    id: int
    op: str            # move | move_dir | trash | rmdir
    src: str
    dst: str
    kind: str
    size: int
    reason: str
    confidence: float
    source: str
    renamed: bool = False
    enabled: bool = True
    area: str | None = None
    base_key: str = ""
    count: int = 1

    @property
    def src_name(self) -> str:
        return os.path.basename(self.src)

    @property
    def dst_name(self) -> str:
        return os.path.basename(self.dst) if self.dst else ""


@dataclass
class Plan:
    root: str
    mode: str
    bases: dict[str, str]
    actions: list[Action]
    respected: list[tuple[str, str]] = field(default_factory=list)
    cleanup_dirs: list[str] = field(default_factory=list)
    ai_model: str = ""
    ai_count: int = 0
    notes: list[str] = field(default_factory=list)
    roots: list[str] = field(default_factory=list)
    whole_computer: bool = False

    def __post_init__(self) -> None:
        if not self.roots:
            self.roots = [self.root]

    @property
    def title(self) -> str:
        if self.whole_computer:
            return "Todo o computador"
        if len(self.roots) == 1:
            return os.path.basename(self.roots[0]) or self.roots[0]
        if len(self.roots) == 2:
            return f"{os.path.basename(self.roots[0])} e {os.path.basename(self.roots[1])}"
        return f"{len(self.roots)} pastas"

    def enabled(self) -> list[Action]:
        return [a for a in self.actions if a.enabled]


ProgressFn = Callable[[str, int, int, str, float | None], None]


class PlanCancelled(Exception):
    pass


def default_mode(scan_or_root: ScanResult | str) -> str:
    xdg = user_dirs()
    if isinstance(scan_or_root, ScanResult):
        if scan_or_root.whole_computer or len(scan_or_root.roots) > 1:
            return MODE_PERSONAL
        root = scan_or_root.root
    else:
        root = scan_or_root
    if is_home(root) or root in (str(xdg["DOWNLOAD"]), str(xdg["DESKTOP"])):
        return MODE_PERSONAL
    return MODE_INSIDE


def _personal_bases() -> dict[str, str]:
    xdg = user_dirs()
    return {
        "documents": str(xdg["DOCUMENTS"]),
        "pictures": str(xdg["PICTURES"]),
        "videos": str(xdg["VIDEOS"]),
        "music": str(xdg["MUSIC"]),
        "archives": str(xdg["DOWNLOAD"] / "Ficheiros comprimidos"),
        "installers": str(xdg["DOWNLOAD"] / "Instaladores"),
        "code": str(xdg["DOCUMENTS"] / "Código"),
        "other": str(xdg["DOCUMENTS"] / "Outros ficheiros"),
    }


def compute_bases_for_root(root: str, scan: ScanResult, mode: str) -> dict[str, str]:
    xdg = user_dirs()
    external_mount = is_external_mount(root)
    if (mode == MODE_PERSONAL or is_home(root)) and not (scan.whole_computer and external_mount):
        return _personal_bases()
    bases = {k: str(Path(root) / v) for k, v in INSIDE_NAMES.items()}
    xdg_map = {"documents": "DOCUMENTS", "pictures": "PICTURES", "videos": "VIDEOS", "music": "MUSIC"}
    for key, xkey in xdg_map.items():
        if os.path.realpath(root) == os.path.realpath(xdg[xkey]):
            bases[key] = root
            if key == "documents":
                bases["other"] = str(Path(root) / "Outros")
            return bases
    if len(scan.roots) == 1:
        counts = Counter({KIND_BASE.get(k): c for k, (c, _) in scan.by_kind.items() if k in KIND_BASE})
        total = sum(counts.values())
        if total >= 5:
            key, n = counts.most_common(1)[0]
            if key and n / total >= 0.9:
                bases[key] = root
    return bases


def compute_bases(scan: ScanResult, mode: str) -> dict[str, str]:
    if len(scan.roots) > 1 or scan.whole_computer or mode == MODE_PERSONAL or is_home(scan.root):
        return _personal_bases() if mode == MODE_PERSONAL or is_home(scan.root) else compute_bases_for_root(scan.roots[0], scan, mode)
    return compute_bases_for_root(scan.root, scan, mode)


class Planner:
    def __init__(self, scan: ScanResult, settings: Settings, mode: str, db: Database | None = None,
                 progress: ProgressFn | None = None, cancel: threading.Event | None = None,
                 skip_ai: threading.Event | None = None):
        self.scan = scan
        self.settings = settings
        self.mode = MODE_PERSONAL if (len(scan.roots) == 1 and is_home(scan.root)) else mode
        self.db = db
        self.progress = progress or (lambda *a: None)
        self.cancel = cancel or threading.Event()
        self.skip_ai = skip_ai or threading.Event()
        self.notes: list[str] = []

    def _check(self) -> None:
        if self.cancel.is_set():
            raise PlanCancelled()

    def _root_for(self, path: str) -> str:
        for r in self.scan.roots:
            if is_within(path, r):
                return r
        return self.scan.roots[0]

    # ------------------------------------------------------------------ estrutura
    def _traverse(self, bases_by_root: dict[str, dict[str, str]]):
        scan = self.scan
        xdg = user_dirs()
        inboxes = {str(xdg["DOWNLOAD"]), str(xdg["DESKTOP"])}
        base_set: set[str] = set()
        for bmap in bases_by_root.values():
            base_set.update(bmap.values())
        ancestors: set[str] = set()
        for r in scan.roots:
            for b in base_set:
                p = os.path.dirname(b)
                while is_within(p, r) and p != r:
                    ancestors.add(p)
                    p = os.path.dirname(p)

        individual: dict[str, str] = {}   # pasta -> estado
        units: list[FolderInfo] = []
        respected: list[tuple[str, str]] = []
        flatten: list[str] = []
        empty_generic: list[str] = []

        queue: list[tuple[str, str]] = []
        for r in reversed(scan.roots):
            inside = all(is_within(b, r) for b in bases_by_root[r].values())
            if is_home(r):
                r_state = "home"
            elif r in base_set and r not in inboxes:
                r_state = "base"
            elif r in inboxes or not inside:
                # Transferências, Secretária ou pastas a esvaziar para as pastas pessoais:
                # as subpastas com nome próprio também são arrumadas (inteiras).
                r_state = "inbox"
            else:
                # Arrumar dentro de uma pasta: as subpastas com nome próprio são a organização
                # da pessoa e ficam onde estão (não se cria «Trabalho/Documentos/Trabalho/…»).
                r_state = "keep"
            queue.append((r, r_state))

        while queue:
            path, state = queue.pop()
            info = scan.folders.get(path)
            if info is None or info.protected:
                continue
            individual[path] = state
            if state.startswith("flatten"):
                flatten.append(path)
            inbox_like = state in ("inbox", "flatten-inbox")
            for child in info.children:
                ci = scan.folders[child]
                if ci.protected:
                    continue
                if child in base_set or child in ancestors:
                    queue.append((child, "inbox" if child in inboxes else "base"))
                    continue
                if child in inboxes:
                    queue.append((child, "inbox"))
                    continue
                if ci.total_files == 0:
                    if ci.generic or inbox_like and self._tree_is_empty(ci):
                        empty_generic.append(child)
                    continue
                if ci.generic:
                    queue.append((child, "flatten-inbox" if inbox_like else "flatten-keep"))
                    continue
                if inbox_like:
                    units.append(ci)
                else:
                    respected.append((child, "Pasta com nome próprio: fica como está."))
        return individual, units, respected, flatten, empty_generic

    def _tree_is_empty(self, ci: FolderInfo) -> bool:
        for dirpath, _dirs, files in os.walk(ci.path):
            if files:
                return False
        return True

    # ------------------------------------------------------------------ IA
    def _ai_client(self) -> LocalAI | None:
        if not self.settings.use_ai:
            return None
        try:
            ai = LocalAI(self.settings.ollama_url, self.settings.model)
            status = ai.check()
        except AIError as e:
            self.notes.append(f"IA local indisponível: {e}")
            return None
        if not status.ok:
            self.notes.append(f"IA local indisponível: {status.error}")
            return None
        return ai

    def _run_ai(self, ai: LocalAI, requests: list[dict]) -> dict[int, dict]:
        """requests: dicts com id, nome, pasta, texto, tipo, cache_key. Um pedido por item."""
        results: dict[int, dict] = {}
        pending = []
        for r in requests:
            cached = self.db.cache_get(r["cache_key"]) if self.db else None
            if cached:
                results[r["id"]] = cached
            else:
                pending.append(r)
        total = len(requests)
        done = total - len(pending)
        started = time.monotonic()
        failures = 0
        for n, r in enumerate(pending):
            self._check()
            if self.skip_ai.is_set():
                self.notes.append("A análise com IA foi interrompida; os restantes documentos "
                                  "foram classificados por palavras-chave.")
                break
            elapsed = time.monotonic() - started
            eta = (elapsed / n) * (len(pending) - n) if n else None
            self.progress("ai", done, total, r["nome"], eta)
            try:
                out = ai.classify_item(r)
                failures = 0
            except AIError as e:
                failures += 1
                done += 1
                if failures >= 3:
                    self.notes.append(f"A IA deixou de responder ({e}). Usaram-se palavras-chave para o resto.")
                    break
                continue
            results[r["id"]] = out
            if self.db:
                self.db.cache_put(r["cache_key"], out)
            done += 1
        self.progress("ai", done, total, "", 0)
        return results

    # ------------------------------------------------------------------ plano
    def build(self) -> Plan:
        scan, st = self.scan, self.settings
        bases_by_root = {r: compute_bases_for_root(r, scan, self.mode) for r in scan.roots}
        primary_bases = compute_bases(scan, self.mode)
        individual, units, respected, flatten, empty_generic = self._traverse(bases_by_root)

        files = [f for f in scan.files if f.parent in individual]
        placements: dict[int, Placement] = {}
        docs: list[int] = []

        # 1) Regras e metadados
        total = len(files)
        for i, f in enumerate(files):
            if i % 50 == 0:
                self._check()
                self.progress("rules", i, total, f.name, None)
            p = classify_simple(f, st)
            if p is None:
                docs.append(i)
            else:
                placements[i] = p

        # 2) Documentos: ler conteúdo e palavras-chave
        texts: dict[int, str] = {}
        keyword: dict[int, tuple[str, str, float, list[str]]] = {}
        for n, i in enumerate(docs):
            self._check()
            f = files[i]
            self.progress("read", n, len(docs), f.name, None)
            text = extract_text(f.path, f.ext) if f.ext in tx.TEXT_EXTRACTABLE else ""
            texts[i] = text
            area, sub, conf, hits = tx.keyword_classify(f.name, text)
            keyword[i] = (area, sub, conf, hits)
            if hits:
                reason = "Contém " + ", ".join(f"«{h}»" for h in hits) + f", por isso parece de {area}" + \
                         (f" › {sub}." if sub else ".")
                source = "palavras-chave"
            else:
                reason = "Sem pistas suficientes no nome ou no conteúdo."
                source = "regras"
            date = ""
            d = plausible(date_from_name(f.name))
            if d:
                date = d.strftime("%Y-%m-%d")
            placements[i] = document_placement(f, st, area, sub, conf, source, reason, date=date)

        # 3) Pastas mantidas inteiras
        unit_info: list[tuple[FolderInfo, str, list[FileItem]]] = []
        unit_files: dict[str, list[FileItem]] = {u.path: [] for u in units}
        if units:
            for f in scan.files:
                for u in units:
                    if is_within(f.path, u.path):
                        unit_files[u.path].append(f)
                        break
        for u in units:
            kinds = Counter({k: c for k, c in u.kinds.items() if k != tx.JUNK})
            dominant = kinds.most_common(1)[0][0] if kinds else tx.OTHER
            unit_info.append((u, dominant, unit_files[u.path]))

        # 4) IA local, um documento de cada vez
        ai = self._ai_client() if (docs or any(d == tx.DOCUMENT for _, d, _ in unit_info)) else None
        ai_count = 0
        self._unit_ai: dict[int, dict | None] = {}
        if ai is not None:
            reqs = []
            for i in docs:
                f = files[i]
                reqs.append({"id": i, "nome": f.name, "pasta": os.path.basename(f.parent),
                             "texto": texts.get(i, ""), "tipo": "documento",
                             "cache_key": f"v{PROMPT_VERSION}|{ai.model}|{f.name}|{f.size}|{int(f.mtime)}"})
            for n, (u, dominant, ufiles) in enumerate(unit_info):
                if dominant != tx.DOCUMENT:
                    continue
                names = sorted(x.name for x in ufiles)[:25]
                digest = hashlib.sha1("\n".join(names).encode("utf-8")).hexdigest()[:16]
                reqs.append({"id": 1_000_000 + n, "nome": u.name, "pasta": os.path.basename(os.path.dirname(u.path)),
                             "texto": "; ".join(names), "tipo": "pasta",
                             "cache_key": f"v{PROMPT_VERSION}|{ai.model}|dir|{u.name}|{len(ufiles)}|{digest}"})
            results = self._run_ai(ai, reqs)
            for i in docs:
                r = results.get(i)
                if not r:
                    continue
                prev = placements[i]
                kw_area, kw_sub, kw_conf, kw_hits = keyword[i]
                if r["area"] == "Outros" and prev.area != "Outros" and prev.confidence >= 0.5:
                    continue  # a IA não soube; as palavras-chave tinham pistas claras
                f = files[i]
                area, sub, source = r["area"], r["subarea"], "IA"
                label = tx.category_label(area, sub)
                what = f"«{r['titulo']}»" if r["titulo"] else "o documento"
                reason = f"A IA local leu {what} e classificou-o em {label}."
                conf = r["confianca"]
                if kw_area == area:
                    conf = max(conf, 0.8)
                elif kw_area != "Outros" and kw_conf >= 0.7:
                    # Pistas fortes no texto contrariam a IA. Nas avaliações, nestes casos quem
                    # acertava eram as palavras-chave; fica o título proposto pela IA.
                    area, sub, source = kw_area, kw_sub, "palavras-chave"
                    pistas = ", ".join(f"«{h}»" for h in kw_hits)
                    reason = (f"O texto contém {pistas}, por isso fica em {tx.category_label(area, sub)} "
                              f"(a IA local tinha sugerido {label}).")
                    conf = min(kw_conf, 0.7)
                elif kw_area != "Outros" and kw_conf >= 0.55:
                    conf = min(conf, 0.5)
                    reason += f" As palavras-chave apontavam para {kw_area}: confirma."
                date = r["data"]
                if not date:
                    d = plausible(date_from_name(f.name))
                    date = d.strftime("%Y-%m-%d") if d else ""
                placements[i] = document_placement(f, st, area, sub, conf, source, reason, r["titulo"], date)
                ai_count += 1
            self._unit_ai = {n: results.get(1_000_000 + n) for n in range(len(unit_info))}

        # 5) Destinos: simplificar a árvore antes de criar as ações
        entries: list[tuple[Placement, str]] = []
        for i, f in enumerate(files):
            p = placements[i]
            if not p.trash:
                entries.append((p, bases_by_root[self._root_for(f.path)][p.base]))
        unit_places: list[Placement] = []
        for n, (u, dominant, ufiles) in enumerate(unit_info):
            p = self._unit_placement(u, dominant, ufiles, self._unit_ai.get(n))
            unit_places.append(p)
            entries.append((p, bases_by_root[self._root_for(u.path)][p.base]))
        simplify_tree(entries)

        # 6) Ações
        actions: list[Action] = []
        taken: set[str] = set()
        next_id = 0

        def add(op, src, dst, kind, size, p: Placement, count=1, enabled=True):
            nonlocal next_id
            actions.append(Action(next_id, op, src, dst, kind, size, p.reason, p.confidence, p.source,
                                  renamed=bool(p.new_name), enabled=enabled, area=p.area,
                                  base_key=p.base, count=count))
            next_id += 1

        for i, f in enumerate(files):
            p = placements[i]
            if p.trash:
                if st.clean_junk:
                    add("trash", f.path, "", tx.JUNK, f.size, p, enabled=p.trash_default)
                continue
            r_bases = bases_by_root[self._root_for(f.path)]
            dst_dir = Path(r_bases[p.base], *p.rel)
            dst = dst_dir / (p.new_name or f.name)
            if str(dst) == f.path:
                continue
            final = unique_path(dst, taken)
            if final != dst:
                p.reason += f" Já existe «{dst.name}» no destino; ficará «{final.name}»."
            taken.add(path_key(final))
            add("move", f.path, str(final), f.kind, f.size, p)

        for (u, dominant, ufiles), p in zip(unit_info, unit_places):
            r_bases = bases_by_root[self._root_for(u.path)]
            dst = Path(r_bases[p.base], *p.rel, u.name)
            if str(dst) == u.path or is_within(dst, u.path):
                continue
            final = unique_path(dst, taken)
            taken.add(path_key(final))
            add("move_dir", u.path, str(final), dominant, u.total_size, p, count=u.total_files)

        for d in empty_generic:
            add("rmdir", d, "", tx.OTHER, 0,
                Placement("", (), reason="Pasta vazia sem nome próprio.", confidence=0.95))

        order = {"move_dir": 0, "move": 1, "trash": 2, "rmdir": 3}
        actions.sort(key=lambda a: (order[a.op], a.dst.lower(), a.src.lower()))
        for n, a in enumerate(actions):
            a.id = n

        model = ai.model if ai is not None else ""
        return Plan(root=scan.root, roots=list(scan.roots), whole_computer=scan.whole_computer,
                    mode=self.mode, bases=primary_bases, actions=actions,
                    respected=respected, cleanup_dirs=flatten, ai_model=model, ai_count=ai_count,
                    notes=self.notes)

    def _unit_placement(self, u: FolderInfo, dominant: str, ufiles: list[FileItem],
                        ai_result: dict | None) -> Placement:
        n = u.total_files
        base = KIND_BASE.get(dominant, "other")
        keep = f"A pasta «{u.name}» tem nome próprio, por isso é mantida inteira ({n} ficheiros)."
        if dominant == tx.IMAGE:
            years: Counter = Counter()
            for f in ufiles[:400]:
                d = plausible(date_from_name(f.name))
                if d is None and f.kind == tx.IMAGE and sum(years.values()) < 8 and f.ext in tx.EXIF_EXT:
                    d = image_info(f.path).get("date")
                d = d or datetime.fromtimestamp(f.mtime)
                years[d.year] += 1
            year = years.most_common(1)[0][0] if years else datetime.now().year
            return Placement("pictures", ("Fotografias", str(year)), year_level=True,
                             reason=f"Álbum de imagens, sobretudo de {year}. {keep}", confidence=0.8)
        if dominant in (tx.DOCUMENT, tx.BOOK):
            if ai_result:
                area = ai_result["area"]
                return Placement("documents", (area,), area=area, source="IA", confidence=ai_result["confianca"],
                                 reason=f"A IA local analisou os nomes dos ficheiros e colocou a pasta em {area}. {keep}")
            area, _sub, conf, hits = tx.keyword_classify(u.name, " ".join(f.name for f in ufiles[:60]))
            why = f"Pistas: {', '.join(hits)}. " if hits else ""
            return Placement("documents", (area,), area=area, confidence=conf,
                             source="palavras-chave" if hits else "regras",
                             reason=f"{why}{keep}")
        label = tx.KIND_INFO.get(dominant, tx.KIND_INFO[tx.OTHER])[0].lower()
        return Placement(base, (), reason=f"Pasta sobretudo com {label}. {keep}", confidence=0.75)


def _has_month_dirs(year_dir: Path) -> bool:
    try:
        return any(e.is_dir() and _MONTH_DIR.match(e.name) for e in os.scandir(year_dir))
    except OSError:
        return False


def _has_year_dirs(parent: Path) -> bool:
    try:
        return any(e.is_dir() and re.fullmatch(r"(19|20)\d{2}", e.name) for e in os.scandir(parent))
    except OSError:
        return False


def simplify_tree(entries: list[tuple[Placement, str]]) -> None:
    """Evita pastas que não fazem sentido: subpastas novas com um ou dois ficheiros e meses
    com meia dúzia de fotografias. entries: (colocação, pasta-base). Altera as colocações."""
    years: dict[tuple, list[Placement]] = defaultdict(list)
    for p, bdir in entries:
        if p.month_level and len(p.rel) >= 2:
            years[(bdir, p.rel[:-1])].append(p)
    for (bdir, year_rel), ps in years.items():
        if len(ps) >= MONTH_SPLIT_MIN or _has_month_dirs(Path(bdir, *year_rel)):
            continue
        for p in ps:
            p.rel = p.rel[:-1]
            p.month_level = False

    # Anos: ou todos os anos de uma pasta têm subpasta, ou nenhum (evita «2025/» com uma captura).
    by_parent: dict[tuple, list[tuple[Placement, int]]] = defaultdict(list)
    for p, bdir in entries:
        idx = len(p.rel) - (2 if p.month_level else 1)
        if p.year_level and idx >= 0 and re.fullmatch(r"(19|20)\d{2}", p.rel[idx]):
            by_parent[(bdir, p.rel[:idx])].append((p, idx))
    for (bdir, parent), items in by_parent.items():
        per_year = Counter(p.rel[idx] for p, idx in items)
        if max(per_year.values()) >= MIN_GROUP or _has_year_dirs(Path(bdir, *parent)):
            continue
        for p, _idx in items:  # nenhum ano chega para ter pasta (e por isso também não há meses)
            p.rel = parent
            p.year_level = False

    changed = True
    while changed:
        changed = False
        counts = Counter((bdir, p.rel) for p, bdir in entries)
        for p, bdir in entries:
            if p.optional_levels <= 0 or not p.rel:
                continue
            if counts[(bdir, p.rel)] >= MIN_GROUP or os.path.isdir(os.path.join(bdir, *p.rel)):
                continue
            parent = p.rel[:-1]
            p.rel = parent
            p.optional_levels -= 1
            if parent:
                p.reason += f" Fica em «{parent[-1]}» porque ainda há poucos ficheiros deste tipo."
            changed = True


def rebase_document(action: Action, plan: Plan, area: str) -> None:
    """Muda a área de um documento escolhida pelo utilizador."""
    base = plan.bases["documents"]
    name = os.path.basename(action.dst)
    if action.op == "move_dir":
        new = Path(base, area, name)
    else:
        rel = Path(action.dst).relative_to(base).parts if is_within(action.dst, base) else ()
        sub = rel[1] if len(rel) >= 3 and rel[0] in tx.AREAS and rel[1] in tx.AREAS.get(area, []) else ""
        new = Path(base, area, sub, name) if sub else Path(base, area, name)
    taken = {path_key(a.dst) for a in plan.actions if a is not action and a.dst}
    action.dst = str(unique_path(new, taken)) if str(new) != action.dst else action.dst
    action.area = area
    action.source = "manual"
    action.confidence = 1.0
    action.reason = f"Escolheste a área {area}."


def retarget(action: Action, plan: Plan, folder: str) -> None:
    """Muda a pasta de destino de um ficheiro ou pasta (incluindo por arrastar e largar)."""
    name = os.path.basename(action.dst or action.src)
    if action.op == "trash":
        action.op = "move"
    taken = {path_key(a.dst) for a in plan.actions if a is not action and a.dst}
    action.dst = str(unique_path(Path(folder) / name, taken))
    action.renamed = (os.path.basename(action.dst) != os.path.basename(action.src))
    action.source = "manual"
    action.confidence = 1.0
    action.reason = f"Movido por ti para «{os.path.basename(folder) or folder}»."


def rename_action_in_plan(action: Action, plan: Plan, new_name: str) -> None:
    """Muda o nome proposto para um ficheiro ou pasta movida."""
    if not action.dst:
        return
    clean = sanitize_name(new_name)
    if action.op == "move":
        _, orig_ext = split_ext(action.src_name)
        _, new_ext = split_ext(clean)
        if orig_ext and not new_ext:
            clean += orig_ext
    parent = Path(os.path.dirname(action.dst))
    candidate = parent / clean
    if str(candidate) == action.dst:
        return
    taken = {path_key(a.dst) for a in plan.actions if a is not action and a.dst}
    action.dst = str(unique_path(candidate, taken))
    action.renamed = (os.path.basename(action.dst) != action.src_name)
    action.source = "manual"
    action.confidence = 1.0
    action.reason = f"Nome alterado por ti para «{os.path.basename(action.dst)}»."


def _rewrite_prefix(plan: Plan, old_dir: str, new_dir: str, reason: str) -> None:
    old_dir = os.path.normpath(old_dir)
    new_dir = os.path.normpath(new_dir)
    if old_dir == new_dir:
        return
    affected = [a for a in plan.actions if a.dst and is_within(a.dst, old_dir)]
    taken = {path_key(a.dst) for a in plan.actions if a.dst and a not in affected}
    for a in affected:
        if os.path.normpath(a.dst) == old_dir:
            cand = Path(new_dir)
        else:
            rel = os.path.relpath(a.dst, old_dir)
            cand = Path(new_dir) / rel
        final = unique_path(cand, taken)
        taken.add(path_key(final))
        a.dst = str(final)
        a.renamed = (os.path.basename(a.dst) != a.src_name)
        a.source = "manual"
        a.confidence = 1.0
        a.reason = reason
    for k, b in list(plan.bases.items()):
        if is_within(b, old_dir):
            rel = os.path.relpath(b, old_dir)
            plan.bases[k] = new_dir if rel == "." else os.path.join(new_dir, rel)


def rename_folder_in_plan(plan: Plan, old_dir: str, new_name: str) -> str:
    """Altera o nome de uma pasta sugerida no plano e atualiza todos os itens lá dentro."""
    clean = sanitize_name(new_name)
    parent = os.path.dirname(os.path.normpath(old_dir))
    new_dir = os.path.join(parent, clean)
    _rewrite_prefix(plan, old_dir, new_dir, f"Pasta renomeada por ti para «{clean}».")
    return new_dir


def move_folder_in_plan(plan: Plan, src_dir: str, target_parent_dir: str) -> str | None:
    """Move uma pasta sugerida inteira para dentro de outra pasta no plano."""
    src_dir = os.path.normpath(src_dir)
    target_parent_dir = os.path.normpath(target_parent_dir)
    if src_dir == target_parent_dir or is_within(target_parent_dir, src_dir):
        return None
    new_dir = os.path.join(target_parent_dir, os.path.basename(src_dir))
    if new_dir == src_dir:
        return None
    _rewrite_prefix(plan, src_dir, new_dir,
                    f"Pasta movida por ti para «{os.path.basename(target_parent_dir) or target_parent_dir}».")
    return new_dir
