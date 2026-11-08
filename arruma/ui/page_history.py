# SPDX-License-Identifier: GPL-3.0-or-later
"""Página de histórico: arrumações anteriores, com opção de anular."""

from __future__ import annotations

import os
from datetime import datetime

from gi.repository import Gtk

from ..core import taxonomy as tx
from ..core.executor import Result
from ..core.fsutil import display_path, plural
from ..core.system import TRASH_FROM, TRASH_TO
from .widgets import Placeholder, ProgressPanel, add_classes, button, hbox, icon, label, vbox

UNDONE, UNDONE_PARTLY = 1, 2  # valores de «undone» (ver Database.mark_undone)
REPORT_MAX = 10


def _when(ts: float) -> str:
    d = datetime.fromtimestamp(ts)
    today = datetime.now().date()
    if d.date() == today:
        day = "Hoje"
    elif (today - d.date()).days == 1:
        day = "Ontem"
    else:
        day = f"{d.day} de {tx.MONTHS_PT[d.month - 1]} de {d.year}"
    return f"{day}, {d:%H:%M}"


def changes_summary(ops, undo: bool = False, limit: int = 6) -> list[str]:
    """De que pasta para que pasta foram os itens de uma sessão (ou, ao anular, de onde para onde voltam), do que
    tem mais itens para o que tem menos. «ops»: as operações feitas (estado «ok»)."""
    counts: dict[tuple[str, str], int] = {}
    for o in ops:
        if o["op"] in ("move", "move_dir") and o["dst"]:
            key = (os.path.dirname(o["src"]), os.path.dirname(o["dst"]))
        elif o["op"] == "trash":
            key = (os.path.dirname(o["src"]), "")
        else:
            continue
        counts[key] = counts.get(key, 0) + 1
    lines = []
    for (src, dst), n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]:
        if not dst:
            lines.append(f"• {n} {'sai' if n == 1 else 'saem'} {TRASH_FROM} para {display_path(src)}" if undo
                         else f"• {n} de {display_path(src)} {TRASH_TO}")
        elif undo:
            lines.append(f"• {n} {'volta' if n == 1 else 'voltam'} de {display_path(dst)} para {display_path(src)}")
        else:
            lines.append(f"• {n} de {display_path(src)} para {display_path(dst)}")
    if len(counts) > limit:
        lines.append(f"• e mais {plural(len(counts) - limit, 'pasta', 'pastas')}")
    return lines


def undo_question(s, ops=None) -> tuple[str, str, str]:
    """Título, texto e botão da confirmação antes de anular uma sessão (ou o que falta de uma anulada em parte).
    Com «ops» (as operações por anular), diz também de que pastas para que pastas voltam os itens."""
    where = changes_summary(ops, undo=True, limit=4) if ops else []
    title, text, ok = _undo_question(s)
    return title, text + ("\n\n" + "\n".join(where) if where else ""), ok


def _undo_question(s) -> tuple[str, str, str]:
    keep = "Nada é substituído: se já houver outro com o mesmo nome no sítio original, esse item fica onde está."
    if s["undone"] == UNDONE_PARTLY:
        n = s["n_left"]
        return ("Anular o resto?",
                f"{s['title']}. Ainda {'falta' if n == 1 else 'faltam'} {plural(n, 'item', 'itens')} por voltar ao "
                f"sítio onde {'estava' if n == 1 else 'estavam'}. {keep}", "Anular o resto")
    # As alterações contam também as pastas vazias removidas; os itens são o que o progresso vai contar.
    n = s["n_items"]
    back = (f"{plural(n, 'item volta', 'itens voltam')} ao sítio onde {'estava' if n == 1 else 'estavam'}" if n
            else "Cada item volta ao sítio onde estava")
    return (f"Anular {plural(s['n_ok'], 'alteração', 'alterações')}?",
            f"{s['title']}. {back}, incluindo o que foi {TRASH_TO}. {keep}", "Anular")


def undo_report(res: Result) -> str:
    """Aviso de uma anulação com falhas: o que não voltou ao sítio e porquê."""
    n = len(res.errors)
    lines = [f"{plural(res.ok, 'item voltou', 'itens voltaram')} ao sítio. "
             f"{plural(n, 'item não voltou', 'itens não voltaram')} ao sítio onde {'estava' if n == 1 else 'estavam'}:"]
    lines += [f"• {display_path(path)}: {err}" for path, err in res.errors[:REPORT_MAX]]
    if n > REPORT_MAX:
        lines.append(f"… e mais {n - REPORT_MAX}.")
    lines.append("Resolve o que está indicado e carrega em «Anular o resto», no Histórico, para tentar outra vez.")
    return "\n".join(lines)


class HistoryPage(Gtk.Stack):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.add_named(Placeholder("document-open-recent-symbolic", "Ainda não há histórico",
                                   "Cada arrumação fica registada aqui e pode ser anulada."), "empty")
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer = vbox(16, margin_top=28, margin_bottom=28, margin_start=32, margin_end=32)
        outer.pack_start(label("Histórico", "page-title"), False, False, 0)
        outer.pack_start(label("Todas as alterações feitas pelo Arruma. Anular devolve cada ficheiro ao sítio "
                               f"onde estava (e recupera {TRASH_FROM} o que lá foi parar).", "dim", wrap=True),
                         False, False, 0)
        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.NONE)
        add_classes(self.list, "pref-group")
        outer.pack_start(self.list, False, False, 0)
        sw.add(outer)
        self.add_named(sw, "content")
        self.progress = ProgressPanel(on_cancel=lambda: win.cancel_task("undo"))
        self.add_named(self.progress, "progress")
        self.working = False  # a anular: a lista atualiza-se, mas o progresso fica à vista
        self.connect("map", lambda *_: self.refresh())

    def show_progress(self, title: str) -> None:
        self.working = True
        self.progress.start("A anular…", f"{title}: cada item volta ao sítio onde estava.")
        self.set_visible_child_name("progress")

    def update_progress(self, done: int, total: int, current: str) -> None:
        self.progress.update(display_path(current), done / total if total else None, f"{done} de {total}")

    def stop_progress(self) -> None:
        self.working = False
        self.progress.stop()
        self.refresh()

    def _details_button(self, s) -> Gtk.MenuButton:
        """«O que mudou»: de que pastas para que pastas foram os itens desta sessão."""
        btn = Gtk.MenuButton(label="O que mudou")
        add_classes(btn, "flat")
        btn.set_valign(Gtk.Align.CENTER)
        pop = Gtk.Popover()
        box = vbox(6, margin_top=12, margin_bottom=12, margin_start=14, margin_end=14)
        box.pack_start(label(s["title"], "section-title", ellipsize=True, max_width=60), False, False, 0)
        lines = changes_summary([o for o in self.win.db.ops(s["id"]) if o["status"] in ("ok", "anulada")],
                                limit=12)
        box.pack_start(label("\n".join(lines) or "Só pastas vazias removidas.", wrap=True, max_width=70),
                       False, False, 0)
        if s["undone"]:
            box.pack_start(label("Esta arrumação foi anulada: os itens voltaram ao sítio onde estavam."
                                 if s["undone"] == UNDONE else "Parte destes itens já voltou ao sítio onde estava.",
                                 "small", "dim", wrap=True, max_width=70), False, False, 0)
        box.show_all()
        pop.add(box)
        btn.set_popover(pop)
        return btn

    def refresh(self) -> None:
        sessions = self.win.db.sessions()
        running = self.win.executor.running
        for c in self.list.get_children():
            self.list.remove(c)
        if not sessions:
            if not self.working:
                self.set_visible_child_name("empty")
            return
        for s in sessions:
            row = Gtk.ListBoxRow()
            row.set_activatable(False)
            box = hbox(14, "history-row")
            partly = s["undone"] == UNDONE_PARTLY
            ico = ("dialog-warning-symbolic", "warn") if partly else \
                ("edit-undo-symbolic", "") if s["undone"] else ("emblem-ok-symbolic", "ok")
            box.pack_start(icon(ico[0], 22, "insight-icon", ico[1]), False, False, 0)
            col = vbox(2)
            col.pack_start(label(s["title"], "section-title", ellipsize=True), False, False, 0)
            sub = f"{_when(s['created'])} · {plural(s['n_ok'], 'alteração', 'alterações')}"
            if s["n_err"]:
                sub += f" · {plural(s['n_err'], 'erro', 'erros')}"
            if not s["finished"] and s["id"] != running:
                sub += " · interrompida"  # o Arruma fechou antes do fim: o que chegou a fazer pode ser anulado
            if partly:
                sub += f" · {plural(s['n_left'], 'item por anular', 'itens por anular')}"
            sub += f" · {display_path(s['root'])}"
            col.pack_start(label(sub, "small", "dim", ellipsize=True), False, False, 0)
            box.pack_start(col, True, True, 0)
            if s["id"] == running:
                box.pack_end(label("A decorrer", "pill", "info"), False, False, 0)
            elif s["undone"] == UNDONE:
                box.pack_end(label("Anulada", "pill", "off"), False, False, 0)
            else:
                b = button("Anular o resto" if partly else "Anular", "edit-undo-symbolic",
                           on_click=lambda sid=s["id"]: self.win.undo_session(sid))
                b.set_valign(Gtk.Align.CENTER)
                box.pack_end(b, False, False, 0)
                if partly:
                    box.pack_end(label("Anulada em parte", "pill", "off"), False, False, 0)
            if s["id"] != running:
                box.pack_end(self._details_button(s), False, False, 0)  # à esquerda do «Anular»
            row.add(box)
            self.list.add(row)
        self.list.show_all()
        if not self.working:
            self.set_visible_child_name("content")
