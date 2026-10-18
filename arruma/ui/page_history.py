# SPDX-License-Identifier: GPL-3.0-or-later
"""Página de histórico: arrumações anteriores, com opção de anular."""

from __future__ import annotations

from datetime import datetime

from gi.repository import Gtk

from ..core import taxonomy as tx
from ..core.fsutil import display_path, plural
from ..core.system import TRASH_FROM
from .widgets import Placeholder, add_classes, button, hbox, icon, label, vbox


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
        self.connect("map", lambda *_: self.refresh())

    def refresh(self) -> None:
        sessions = self.win.db.sessions()
        for c in self.list.get_children():
            self.list.remove(c)
        if not sessions:
            self.set_visible_child_name("empty")
            return
        for s in sessions:
            row = Gtk.ListBoxRow()
            row.set_activatable(False)
            box = hbox(14, "history-row")
            box.pack_start(icon("edit-undo-symbolic" if s["undone"] else "emblem-ok-symbolic", 22,
                                "insight-icon", "" if s["undone"] else "ok"), False, False, 0)
            col = vbox(2)
            col.pack_start(label(s["title"], "section-title", ellipsize=True), False, False, 0)
            sub = f"{_when(s['created'])} · {plural(s['n_ok'], 'alteração', 'alterações')}"
            if s["n_err"]:
                sub += f" · {plural(s['n_err'], 'erro', 'erros')}"
            sub += f" · {display_path(s['root'])}"
            col.pack_start(label(sub, "small", "dim", ellipsize=True), False, False, 0)
            box.pack_start(col, True, True, 0)
            if s["undone"]:
                box.pack_end(label("Anulada", "pill", "off"), False, False, 0)
            else:
                b = button("Anular", "edit-undo-symbolic", on_click=lambda sid=s["id"]: self.win.undo_session(sid))
                b.set_valign(Gtk.Align.CENTER)
                box.pack_end(b, False, False, 0)
            row.add(box)
            self.list.add(row)
        self.list.show_all()
        self.set_visible_child_name("content")
