# SPDX-License-Identifier: GPL-3.0-or-later
"""Página de duplicados: ficheiros com conteúdo exatamente igual."""

from __future__ import annotations

import os
from datetime import datetime

from gi.repository import Gtk, Pango

from ..core.duplicates import DupGroup
from ..core.fsutil import display_path, human_size, plural
from ..core.system import TRASH_IN, TRASH_TO
from .widgets import (Placeholder, ProgressPanel, button, confirm, esc, hbox, kind_icon, label,
                      open_path, resolve_icon, show_in_folder, vbox)

COL_ACTIVE, COL_ICON, COL_MARKUP, COL_SIZE, COL_PATH, COL_IS_FILE = range(6)


class DuplicatesPage(Gtk.Stack):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.groups: list[DupGroup] = []
        self.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        self.add_named(Placeholder("edit-copy-symbolic", "Procura ficheiros repetidos",
                                   "Analisa primeiro uma pasta no Início.",
                                   ("Ir para o Início", lambda: win.navigate("home"))), "empty")
        self.intro = Placeholder("edit-copy-symbolic", "Ficheiros repetidos",
                                 "O Arruma compara o conteúdo dos ficheiros (não só o nome) para encontrar cópias "
                                 f"exatas. Tu escolhes o que vai {TRASH_TO}.",
                                 ("Procurar duplicados", win.find_duplicates))
        self.add_named(self.intro, "intro")
        self.progress = ProgressPanel(on_cancel=win.cancel_task)
        self.add_named(self.progress, "progress")
        self.none = Placeholder("emblem-ok-symbolic", "Não há duplicados", "Não foram encontradas cópias exatas. 🎉")
        self.add_named(self.none, "none")
        self.add_named(self._build_content(), "content")
        self.set_visible_child_name("empty")

    def _build_content(self) -> Gtk.Widget:
        root = vbox(0)
        bar = vbox(3, "toolbar-area")
        bar.pack_start(label("Ficheiros repetidos", "page-title"), False, False, 0)
        self.summary = label("", "dim", markup=True, wrap=True)
        bar.pack_start(self.summary, False, False, 0)
        root.pack_start(bar, False, False, 0)

        self.store = Gtk.TreeStore(bool, str, str, str, str, bool)
        self.tv = Gtk.TreeView(model=self.store)
        self.tv.set_headers_visible(False)
        self.tv.set_enable_search(False)
        col = Gtk.TreeViewColumn()
        toggle = Gtk.CellRendererToggle()
        toggle.connect("toggled", self._on_toggled)
        col.pack_start(toggle, False)
        col.add_attribute(toggle, "active", COL_ACTIVE)
        col.add_attribute(toggle, "visible", COL_IS_FILE)
        pix = Gtk.CellRendererPixbuf()
        pix.set_property("stock-size", Gtk.IconSize.LARGE_TOOLBAR)
        pix.set_padding(4, 2)
        col.pack_start(pix, False)
        col.add_attribute(pix, "icon-name", COL_ICON)
        txt = Gtk.CellRendererText()
        txt.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)
        col.pack_start(txt, True)
        col.add_attribute(txt, "markup", COL_MARKUP)
        col.set_expand(True)
        self.tv.append_column(col)
        scol = Gtk.TreeViewColumn()
        st = Gtk.CellRendererText()
        st.set_property("xalign", 1.0)
        st.set_padding(14, 0)
        scol.pack_start(st, False)
        scol.add_attribute(st, "markup", COL_SIZE)
        self.tv.append_column(scol)
        self.tv.connect("row-activated", self._on_activated)
        sw = Gtk.ScrolledWindow()
        sw.add(self.tv)
        root.pack_start(sw, True, True, 0)

        actions = hbox(10, "action-bar")
        self.sel_label = label("", markup=True)
        actions.pack_start(self.sel_label, False, False, 0)
        actions.pack_start(button("Mostrar na pasta", "folder-open-symbolic", "flat", on_click=self._show_selected),
                           False, False, 0)
        actions.pack_start(button("Procurar de novo", "view-refresh-symbolic", "flat", on_click=self.win.find_duplicates),
                           False, False, 0)
        self.trash_btn = button(f"Enviar {TRASH_TO}", "user-trash-symbolic", "destructive-action", "big-button",
                                on_click=self._on_trash)
        actions.pack_end(self.trash_btn, False, False, 0)
        root.pack_start(actions, False, False, 0)
        return root

    # ------------------------------------------------------------------
    def ready(self) -> None:
        self.set_visible_child_name("intro")

    def reset(self) -> None:
        self.groups = []
        self.set_visible_child_name("empty")

    def show_progress(self) -> None:
        self.progress.start("A comparar ficheiros", "Os ficheiros com o mesmo tamanho são comparados pelo conteúdo.")
        self.set_visible_child_name("progress")

    def update_progress(self, done: int, total: int, name: str) -> None:
        self.progress.update(name, done / total if total else None, f"{done} de {total} candidatos")

    def show_groups(self, groups: list[DupGroup]) -> None:
        self.progress.stop()
        self.groups = groups
        if not groups:
            self.set_visible_child_name("none")
            return
        self.store.clear()
        for g in groups:
            first = os.path.basename(g.files[0].path)
            parent = self.store.append(None, [False, kind_icon(g.files[0].kind),
                                              f"<b>{esc(first)}</b>\n<span size='small' alpha='62%'>"
                                              f"{len(g.files)} cópias iguais</span>",
                                              f"<span alpha='62%'>{human_size(g.size)} cada</span>", "", False])
            for f in g.files:
                keep = f.path == g.keep
                date = datetime.fromtimestamp(f.mtime).strftime("%d/%m/%Y")
                tag = "  <span size='small' foreground='#26a269' weight='bold'>manter</span>" if keep else ""
                self.store.append(parent, [not keep, resolve_icon("text-x-generic"),
                                           f"{esc(f.name)}{tag}\n<span size='small' alpha='62%'>"
                                           f"{esc(display_path(os.path.dirname(f.path)))} · {date}</span>",
                                           "", f.path, True])
        self.tv.expand_all()
        wasted = sum(g.wasted for g in groups)
        self.summary.set_markup(f"{plural(len(groups), 'grupo', 'grupos')} de ficheiros iguais. Podes libertar até "
                                f"<b>{human_size(wasted)}</b>. Sugerimos manter a cópia com melhor nome e local; "
                                "as outras ficam marcadas.")
        self._update_label()
        self.set_visible_child_name("content")

    def _iter_files(self):
        it = self.store.get_iter_first()
        while it is not None:
            child = self.store.iter_children(it)
            siblings = []
            while child is not None:
                siblings.append(child)
                child = self.store.iter_next(child)
            yield it, siblings
            it = self.store.iter_next(it)

    def _selected_paths(self) -> list[str]:
        out = []
        for _, children in self._iter_files():
            for c in children:
                if self.store.get_value(c, COL_ACTIVE):
                    out.append(self.store.get_value(c, COL_PATH))
        return out

    def _update_label(self) -> None:
        sizes = {f.path: f.size for g in self.groups for f in g.files}
        sel = self._selected_paths()
        self.sel_label.set_markup(f"<b>{len(sel)}</b> selecionados · {human_size(sum(sizes.get(p, 0) for p in sel))}")
        self.trash_btn.set_sensitive(bool(sel))

    def _on_toggled(self, _r, path: str) -> None:
        it = self.store.get_iter(path)
        new = not self.store.get_value(it, COL_ACTIVE)
        if new:
            # Nunca deixar um grupo sem nenhuma cópia
            parent = self.store.iter_parent(it)
            child = self.store.iter_children(parent)
            remaining = 0
            while child is not None:
                if child != it and not self.store.get_value(child, COL_ACTIVE):
                    remaining += 1
                child = self.store.iter_next(child)
            if remaining == 0:
                self.win.toast.show("Tem de ficar pelo menos uma cópia de cada ficheiro.")
                return
        self.store.set_value(it, COL_ACTIVE, new)
        self._update_label()

    def _on_activated(self, tv, path, _c) -> None:
        p = self.store.get_value(self.store.get_iter(path), COL_PATH)
        if p:
            open_path(p)

    def _show_selected(self) -> None:
        model, it = self.tv.get_selection().get_selected()
        if it is not None and model.get_value(it, COL_PATH):
            show_in_folder(model.get_value(it, COL_PATH))

    def _on_trash(self) -> None:
        sel = self._selected_paths()
        if sel and confirm(self.win, f"Enviar {len(sel)} cópias {TRASH_TO}?",
                           f"Ficam {TRASH_IN} do sistema, de onde as podes recuperar. Também podes anular no Histórico.",
                           f"Enviar {TRASH_TO}", destructive=True):
            self.win.trash_duplicates(sel)
