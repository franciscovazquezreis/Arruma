# SPDX-License-Identifier: GPL-3.0-or-later
"""Página de duplicados: ficheiros com conteúdo exatamente igual."""

from __future__ import annotations

import os
from datetime import datetime

from gi.repository import Gtk, Pango

from ..core.duplicates import DupGroup, short_names
from ..core.fsutil import display_path, human_count, human_size, plural
from ..core.system import TRASH_IN, TRASH_TO
from .widgets import (Placeholder, ProgressPanel, add_classes, button, confirm, esc, hbox, kind_icon, label,
                      markup_column, open_path, resolve_icon, show_in_folder, vbox)

COL_ACTIVE, COL_ICON, COL_MARKUP, COL_SIZE, COL_PATH, COL_IS_FILE, COL_GROUP = range(7)

# Escolhas de cada conjunto de pastas (além de «keep:<pasta>», ficam as cópias dessa pasta)
CHOOSE, KEEP_ALL, BY_HAND = "", "all", "hand"


def _disks(folders) -> set[int]:
    out = set()
    for p in folders:
        try:
            out.add(os.stat(p).st_dev)
        except OSError:
            pass
    return out


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " e " + items[-1]


class FolderSet:
    """Grupos de cópias espalhadas pelas mesmas pastas: a escolha costuma ser a mesma para todos."""

    def __init__(self, folders: tuple[str, ...]):
        self.folders = folders
        self.groups: list[int] = []
        self.wasted = 0
        self.combo: Gtk.ComboBoxText | None = None
        self.handler = 0


class DuplicatesPage(Gtk.Stack):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.groups: list[DupGroup] = []
        self.sets: dict[tuple[str, ...], FolderSet] = {}
        self.names: dict[str, str] = {}
        self.parents: list[Gtk.TreeIter] = []  # a linha de cada grupo (as do Gtk.TreeStore não mudam)
        self.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        self.add_named(Placeholder("edit-copy-symbolic", "Procura ficheiros repetidos",
                                   "Analisa primeiro uma pasta no Início.",
                                   ("Ir para o Início", lambda: win.navigate("home"))), "empty")
        self.intro = Placeholder("edit-copy-symbolic", "Ficheiros repetidos",
                                 "O Arruma compara o conteúdo dos ficheiros (não só o nome) para encontrar cópias "
                                 f"exatas e mostra em que pastas estão. Tu escolhes as que vão {TRASH_TO}.",
                                 ("Procurar duplicados", win.find_duplicates))
        self.add_named(self.intro, "intro")
        self.progress = ProgressPanel(on_cancel=lambda: win.cancel_task("duplicates", "trash"))
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

        # Cópias em pastas diferentes: a escolha é de que pasta ficam, e é o utilizador que a faz.
        self.folders_box = vbox(6)
        self.folders_box.set_margin_top(10)
        self.folders_box.pack_start(label("Cópias em pastas diferentes", "section-title"), False, False, 0)
        self.folders_box.pack_start(label(
            "Aqui o Arruma não escolhe por ti: só tu sabes qual é a pasta boa. Para cada conjunto de pastas, escolhe "
            f"de qual ficam as cópias; as das outras ficam marcadas para ir {TRASH_TO}. Também podes mudar as "
            "marcas uma a uma na lista.", "small", "dim", wrap=True), False, False, 0)
        self.pending = label("", "small", markup=True, wrap=True)
        self.folders_box.pack_start(self.pending, False, False, 0)
        self.folders_list = Gtk.ListBox()
        self.folders_list.set_selection_mode(Gtk.SelectionMode.NONE)
        add_classes(self.folders_list, "pref-group")
        fsw = Gtk.ScrolledWindow()
        fsw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        fsw.set_propagate_natural_height(True)
        fsw.set_max_content_height(250)
        fsw.add(self.folders_list)
        self.folders_box.pack_start(fsw, False, False, 0)
        bar.pack_start(self.folders_box, False, False, 0)
        root.pack_start(bar, False, False, 0)

        self.store = Gtk.TreeStore(bool, str, str, str, str, bool, int)
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
        markup_column(col, txt, COL_MARKUP)
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

    def show_trashing(self) -> None:
        # A lista sai de vista enquanto as cópias vão para o Lixo: mudar as marcas a meio já não contava.
        self.progress.start(f"A enviar cópias {TRASH_TO}",
                            "Cada cópia é comparada outra vez com a que fica antes de sair. Se parares, o que já "
                            "foi enviado fica no Histórico, onde o podes anular.")
        self.set_visible_child_name("progress")

    def update_trashing(self, done: int, total: int, path: str) -> None:
        self.progress.update(os.path.basename(path), done / total if total else None, f"{done} de {total}")

    def show_groups(self, groups: list[DupGroup]) -> None:
        self.progress.stop()
        self.groups = groups
        if not groups:
            self.set_visible_child_name("none")
            return
        self.names = short_names(p for g in groups for p in g.folders)
        self.sets = {}
        for i, g in enumerate(groups):
            s = self.sets.setdefault(g.folders, FolderSet(g.folders))
            s.groups.append(i)
            s.wasted += g.wasted

        self.store.clear()
        self.parents = []
        for i, g in enumerate(groups):
            marked = g.suggested()
            n = len(g.folders)
            where = "na mesma pasta" if n == 1 else ("nas duas pastas" if n == 2 else f"em {n} pastas")
            parent = self.store.append(None, [False, kind_icon(g.files[0].kind),
                                              f"<b>{esc(g.title)}</b>\n<span size='small' alpha='62%'>"
                                              f"{len(g.files)} cópias iguais {where}</span>",
                                              f"<span alpha='62%'>{human_size(g.size)} cada</span>", "", False, i])
            self.parents.append(parent)
            for f in g.files:
                self.store.append(parent, [f.path in marked, resolve_icon("text-x-generic"),
                                           self._file_markup(f, f.path in marked, n > 1), "", f.path, True, i])
        self.tv.expand_all()
        self._build_folder_rows()

        wasted = sum(g.wasted for g in groups)
        self.summary.set_markup(
            f"{plural(len(groups), 'grupo', 'grupos')} de ficheiros com conteúdo exatamente igual, byte a byte "
            f"(o nome não conta). Podes libertar até <b>{human_size(wasted)}</b>.\n"
            f"<b>Uma cópia marcada vai {TRASH_TO}</b>; as desmarcadas ficam, e em cada grupo fica sempre pelo "
            "menos uma. À partida, só vêm marcadas as cópias com «(1)» ou «cópia» no nome que estão na mesma "
            "pasta que outra sem essa marca.")
        self._update_label()
        self.set_visible_child_name("content")

    def _file_markup(self, f, trash: bool, multi: bool) -> str:
        # Num grupo o conteúdo é o mesmo: em destaque vai o que distingue as cópias.
        tag = (f"<span size='small' foreground='#c01c28' weight='bold'>vai {TRASH_TO}</span>" if trash
               else "<span size='small' foreground='#26a269' weight='bold'>fica</span>")
        date = datetime.fromtimestamp(f.mtime).strftime("%d/%m/%Y")
        if multi:  # o que distingue as cópias é a pasta
            first, rest = self.names.get(f.parent, f.parent), f"{f.name} · {date}"
        else:  # todas na mesma pasta: é o nome
            first, rest = f.name, date
        return (f"<b>{esc(first)}</b>   {tag}\n<span size='small' alpha='62%'>{esc(rest)} · em "
                f"{esc(display_path(f.parent))}</span>")

    # --- conjuntos de pastas -------------------------------------------
    def _build_folder_rows(self) -> None:
        for row in self.folders_list.get_children():
            self.folders_list.remove(row)
        multi = sorted((s for s in self.sets.values() if len(s.folders) > 1), key=lambda s: -s.wasted)
        self.folders_box.set_visible(bool(multi))
        self.folders_box.set_no_show_all(not multi)
        if not multi:
            return
        for s in multi:
            n = len(s.groups)
            row = Gtk.ListBoxRow()
            row.set_activatable(False)
            row.set_selectable(False)
            box = hbox(16)
            col = vbox(2)
            col.pack_start(label(_join([f"<b>{esc(self.names[p])}</b>" for p in s.folders]), markup=True,
                                 wrap=True), False, False, 0)
            both = "nas duas pastas" if len(s.folders) == 2 else f"nas {len(s.folders)} pastas"
            col.pack_start(label(f"{plural(n, 'ficheiro repetido', 'ficheiros repetidos')} {both} · "
                                 f"{human_size(s.wasted)} a libertar", "small", "dim", wrap=True), False, False, 0)
            for p in s.folders:
                path = label(f"{self.names[p]}: {display_path(p)}", "small", "dim", ellipsize=True)
                path.set_tooltip_text(display_path(p))
                col.pack_start(path, False, False, 0)
            if len(_disks(s.folders)) > 1:
                col.pack_start(label("<span foreground='#c64600'>Estas pastas estão em discos diferentes: se uma "
                                     "delas for uma cópia de segurança, escolhe «Ficam todas».</span>", "small",
                                     markup=True, wrap=True), False, False, 0)
            box.pack_start(col, True, True, 0)
            combo = Gtk.ComboBoxText()
            combo.append(CHOOSE, "Escolher…")
            for p in s.folders:
                combo.append(f"keep:{p}", f"Ficam as de «{self.names[p]}»")
            combo.append(KEEP_ALL, "Ficam todas")
            combo.append(BY_HAND, "Marcadas à mão")
            combo.set_active_id(CHOOSE)
            combo.set_valign(Gtk.Align.CENTER)
            s.combo = combo
            s.handler = combo.connect("changed", self._on_set_choice, s)
            box.pack_end(combo, False, False, 0)
            row.add(box)
            self.folders_list.add(row)
        self.folders_list.show_all()

    def _group_rows(self, i: int):
        child = self.store.iter_children(self.parents[i])
        while child is not None:
            yield child
            child = self.store.iter_next(child)

    def _set_marks(self, i: int, marked: set[str]) -> None:
        g = self.groups[i]
        by_path = {f.path: f for f in g.files}
        for child in self._group_rows(i):
            path = self.store.get_value(child, COL_PATH)
            self.store.set(child, COL_ACTIVE, path in marked,
                           COL_MARKUP, self._file_markup(by_path[path], path in marked, len(g.folders) > 1))

    def _marks(self, i: int) -> set[str]:
        return {self.store.get_value(c, COL_PATH) for c in self._group_rows(i) if self.store.get_value(c, COL_ACTIVE)}

    def _on_set_choice(self, combo: Gtk.ComboBoxText, s: FolderSet) -> None:
        choice = combo.get_active_id() or CHOOSE
        if choice.startswith("keep:"):
            folder = choice[len("keep:"):]
            for i in s.groups:
                self._set_marks(i, self.groups[i].keeping(folder))
        elif choice == KEEP_ALL:
            for i in s.groups:
                self._set_marks(i, set())
        elif choice == CHOOSE:
            for i in s.groups:
                self._set_marks(i, self.groups[i].suggested())
        self._update_label()

    def _sync_set(self, s: FolderSet) -> None:
        """Depois de mudar uma marca à mão: a escolha do conjunto passa a «Escolha uma a uma», a não ser que as
        marcas continuem a corresponder a uma das escolhas."""
        if s.combo is None:
            return
        marks = [self._marks(i) for i in s.groups]
        choice = BY_HAND
        if all(not m for m in marks):
            choice = KEEP_ALL
        for p in s.folders:
            if all(m == self.groups[i].keeping(p) for i, m in zip(s.groups, marks)):
                choice = f"keep:{p}"
        if s.combo.get_active_id() != choice:
            s.combo.handler_block(s.handler)
            s.combo.set_active_id(choice)
            s.combo.handler_unblock(s.handler)

    # ------------------------------------------------------------------
    def _selected_paths(self) -> list[str]:
        out = []
        it = self.store.get_iter_first()
        while it is not None:
            child = self.store.iter_children(it)
            while child is not None:
                if self.store.get_value(child, COL_ACTIVE):
                    out.append(self.store.get_value(child, COL_PATH))
                child = self.store.iter_next(child)
            it = self.store.iter_next(it)
        return out

    def _update_label(self) -> None:
        sizes = {f.path: f.size for g in self.groups for f in g.files}
        sel = self._selected_paths()
        pending = sum(1 for s in self.sets.values() if s.combo is not None and s.combo.get_active_id() == CHOOSE)
        self.sel_label.set_markup(f"<b>{human_count(len(sel))}</b> {'marcada' if len(sel) == 1 else 'marcadas'} "
                                  f"para ir {TRASH_TO} · {human_size(sum(sizes.get(p, 0) for p in sel))}")
        self.pending.set_markup(
            f"<span foreground='#c64600' weight='bold'>Falta escolher em "
            f"{plural(pending, 'conjunto de pastas', 'conjuntos de pastas')}.</span>" if pending else "")
        self.pending.set_visible(bool(pending))
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
        i = self.store.get_value(it, COL_GROUP)
        marked = self._marks(i) ^ {self.store.get_value(it, COL_PATH)}
        self._set_marks(i, marked)
        self._sync_set(self.sets[self.groups[i].folders])
        self._update_label()

    def _on_activated(self, tv, path, _c) -> None:
        p = self.store.get_value(self.store.get_iter(path), COL_PATH)
        if p:
            open_path(p)

    def _show_selected(self) -> None:
        model, it = self.tv.get_selection().get_selected()
        if it is not None and model.get_value(it, COL_PATH):
            show_in_folder(model.get_value(it, COL_PATH))

    def trash_summary(self, sel: list[str]) -> str:
        """O texto da confirmação: de que pastas saem as cópias e onde ficam as iguais."""
        chosen = set(sel)
        out: dict[str, int] = {}
        stay: dict[str, int] = {}
        for g in self.groups:
            if not chosen.intersection(f.path for f in g.files):
                continue
            for f in g.files:
                target = out if f.path in chosen else stay
                target[f.parent] = target.get(f.parent, 0) + 1

        def lines(counts: dict[str, int], limit: int) -> list[str]:
            items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].casefold()))
            text = [f"• {n} de {display_path(p)}" for p, n in items[:limit]]
            if len(items) > limit:
                text.append(f"• e de mais {plural(len(items) - limit, 'pasta', 'pastas')}")
            return text

        fica, a = ("Fica", "a") if len(sel) == 1 else ("Ficam", "as")
        return ("Saem de:\n" + "\n".join(lines(out, 6)) + "\n\nAs cópias iguais que ficam estão em:\n"
                + "\n".join(lines(stay, 4)) + f"\n\n{fica} {TRASH_IN} do sistema, de onde {a} podes recuperar. "
                "Também podes anular no Histórico.")

    def _on_trash(self) -> None:
        sel = self._selected_paths()
        if not sel or not confirm(self.win, f"Enviar {plural(len(sel), 'cópia', 'cópias')} {TRASH_TO}?",
                                  self.trash_summary(sel), f"Enviar {TRASH_TO}", destructive=True):
            return
        chosen = set(sel)
        keepers: dict[str, list[str]] = {}
        sigs: dict[str, tuple[int, int]] = {}
        for g in self.groups:
            stay = [f.path for f in g.files if f.path not in chosen]
            for f in g.files:
                if f.path in chosen:
                    keepers[f.path] = stay
            sigs.update(g.sigs)
        self.win.trash_duplicates(sel, keepers, sigs)
