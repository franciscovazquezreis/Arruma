"""Página do plano: rever, ajustar e aplicar as mudanças propostas."""

from __future__ import annotations

import os

from gi.repository import Gdk, GLib, Gtk, Pango

from ..core import taxonomy as tx
from ..core.executor import Result
from ..core.fsutil import HOME, display_path, human_size, is_within, plural
from ..core.planner import (Action, Plan, move_folder_in_plan, rebase_document,
                            rename_action_in_plan, rename_folder_in_plan, retarget)
from .widgets import (Placeholder, ProgressPanel, add_classes, button, card, choose_folder, confirm,
                      esc, format_eta, hbox, icon, kind_icon, label, open_path, prompt_text,
                      show_in_folder, vbox)

COL_ACTIVE, COL_INCONS, COL_ICON, COL_MARKUP, COL_ID, COL_KEY, COL_BADGE = range(7)
TRASH_NODE = "Para o Lixo"
EMPTY_NODE = "Pastas vazias a remover"

FILTERS = [
    ("all", "Todas as alterações"),
    ("documents", "Documentos"),
    ("pictures", "Imagens"),
    ("videos", "Vídeos"),
    ("music", "Música e áudio"),
    ("other", "Outros tipos"),
    ("folders", "Pastas inteiras"),
    ("cleanup", "Limpeza"),
    ("renamed", "Com nome novo"),
    ("ai", "Classificados pela IA"),
    ("review", "A rever (pouca certeza)"),
]

SOURCE_LABEL = {
    "IA": ("IA", "#9141ac"),
    "palavras-chave": ("palavras-chave", "#1c71d8"),
    "metadados": ("metadados", "#26a269"),
    "regras": ("regras", "#77767b"),
    "manual": ("escolha tua", "#c64600"),
}

PHASES = {
    "rules": "A classificar os ficheiros",
    "read": "A ler o conteúdo dos documentos",
    "ai": "A IA local está a ler os documentos",
}


class PlanPage(Gtk.Stack):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.plan: Plan | None = None
        self.filter_id = "all"
        self.anchor = str(HOME)
        self.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        self.add_named(Placeholder("view-list-symbolic", "Ainda não há plano",
                                   "Analisa uma pasta e carrega em «Criar plano de organização».",
                                   ("Ir para o Início", lambda: win.navigate("home"))), "empty")
        self.progress = ProgressPanel(on_cancel=win.cancel_task,
                                      secondary=("Continuar sem IA", win.skip_ai))
        self.add_named(self.progress, "progress")
        self.add_named(self._build_content(), "content")
        self.done_box = vbox(0)
        self.add_named(self.done_box, "done")
        self.set_visible_child_name("empty")

    # ================================================================== construção
    def _build_content(self) -> Gtk.Widget:
        root = vbox(0)

        bar = hbox(12, "toolbar-area")
        titles = vbox(3)
        titles.pack_start(label("Plano de organização", "page-title"), False, False, 0)
        self.summary = label("", "dim", markup=True, wrap=True)
        titles.pack_start(self.summary, False, False, 0)
        bar.pack_start(titles, True, True, 0)

        self.kept_btn = Gtk.MenuButton()
        self.kept_btn.set_valign(Gtk.Align.CENTER)
        self.kept_btn.set_tooltip_text("Pastas que ficam exatamente como estão")
        self.kept_pop = Gtk.Popover()
        self.kept_btn.set_popover(self.kept_pop)
        bar.pack_start(self.kept_btn, False, False, 0)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Procurar ficheiro ou pasta…")
        self.search.set_valign(Gtk.Align.CENTER)
        self.search.connect("search-changed", lambda *_: self._repopulate())
        bar.pack_start(self.search, False, False, 0)

        self.filter_combo = Gtk.ComboBoxText()
        for fid, text in FILTERS:
            self.filter_combo.append(fid, text)
        self.filter_combo.set_active_id("all")
        self.filter_combo.set_valign(Gtk.Align.CENTER)
        self.filter_combo.connect("changed", self._on_filter)
        bar.pack_start(self.filter_combo, False, False, 0)
        root.pack_start(bar, False, False, 0)

        self.notes_box = vbox(6, margin_start=22, margin_end=22, margin_bottom=8)
        root.pack_start(self.notes_box, False, False, 0)

        # Vistas Depois / Antes
        self.views = Gtk.Stack()
        self.views.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.trees: dict[str, tuple[Gtk.TreeView, Gtk.TreeStore]] = {}
        for name, title in (("after", "Depois (nova organização)"), ("before", "Antes (onde estão agora)")):
            tv, store = self._make_tree(enable_dnd=(name == "after"))
            sw = Gtk.ScrolledWindow()
            sw.add(tv)
            self.views.add_titled(sw, name, title)
            self.trees[name] = (tv, store)
        self.views.connect("notify::visible-child-name", lambda *_: self._repopulate())

        sw_row = hbox(10, margin_start=22, margin_end=22, margin_bottom=8)
        switcher = Gtk.StackSwitcher()
        switcher.set_stack(self.views)
        sw_row.pack_start(switcher, False, False, 0)
        hint = label("💡 Podes arrastar ficheiros e pastas na árvore ou clicar numa pasta para mudar o nome (F2).",
                     "small", "dim", ellipsize=True)
        hint.set_valign(Gtk.Align.CENTER)
        sw_row.pack_start(hint, True, True, 6)
        sw_row.pack_end(button("", "list-remove-symbolic", "flat", on_click=lambda: self._expand(False),
                               tooltip="Fechar todas as pastas"), False, False, 0)
        sw_row.pack_end(button("", "list-add-symbolic", "flat", on_click=lambda: self._expand(True),
                               tooltip="Abrir todas as pastas"), False, False, 0)
        root.pack_start(sw_row, False, False, 0)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.NONE)
        frame.add(self.views)
        add_classes(frame, "plan-tree")
        paned.pack1(frame, True, False)
        self.detail_scroll = Gtk.ScrolledWindow()
        self.detail_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.detail_scroll.set_size_request(370, -1)
        add_classes(self.detail_scroll, "detail-panel")
        paned.pack2(self.detail_scroll, False, False)
        root.pack_start(paned, True, True, 0)

        actions = hbox(10, "action-bar")
        self.sel_label = label("", markup=True)
        actions.pack_start(self.sel_label, False, False, 0)
        actions.pack_start(button("Selecionar tudo", None, "flat", on_click=lambda: self._select_all(True)), False, False, 0)
        actions.pack_start(button("Desmarcar tudo", None, "flat", on_click=lambda: self._select_all(False)), False, False, 0)
        self.apply_btn = button("Aplicar alterações", "emblem-ok-symbolic", "suggested-action", "big-button",
                                on_click=self._on_apply)
        actions.pack_end(self.apply_btn, False, False, 0)
        root.pack_start(actions, False, False, 0)
        return root

    def _make_tree(self, enable_dnd: bool = False) -> tuple[Gtk.TreeView, Gtk.TreeStore]:
        store = Gtk.TreeStore(bool, bool, str, str, int, str, str)
        tv = Gtk.TreeView(model=store)
        tv.set_headers_visible(False)
        tv.set_enable_search(False)
        tv.set_activate_on_single_click(False)

        col = Gtk.TreeViewColumn()
        toggle = Gtk.CellRendererToggle()
        toggle.connect("toggled", self._on_toggled, store)
        col.pack_start(toggle, False)
        col.add_attribute(toggle, "active", COL_ACTIVE)
        col.add_attribute(toggle, "inconsistent", COL_INCONS)
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
        tv.append_column(col)

        bcol = Gtk.TreeViewColumn()
        badge = Gtk.CellRendererText()
        badge.set_property("xalign", 1.0)
        badge.set_padding(12, 0)
        bcol.pack_start(badge, False)
        bcol.add_attribute(badge, "markup", COL_BADGE)
        tv.append_column(bcol)

        tv.get_selection().connect("changed", self._on_selection, store)
        tv.connect("row-activated", self._on_row_activated)
        tv.connect("button-press-event", self._on_tree_button_press)
        tv.connect("key-press-event", self._on_tree_key_press)

        if enable_dnd:
            dnd_target = Gtk.TargetEntry.new("ARRUMA_PLAN_ROW", Gtk.TargetFlags.SAME_WIDGET, 0)
            tv.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK, [dnd_target], Gdk.DragAction.MOVE)
            tv.enable_model_drag_dest([dnd_target], Gdk.DragAction.MOVE)
            tv.connect("drag-data-get", self._on_drag_data_get)
            tv.connect("drag-data-received", self._on_drag_data_received)
        return tv, store

    # ================================================================== progresso
    def show_progress(self) -> None:
        self.progress.start("A preparar o plano", "Ainda nada é alterado: isto é só a proposta.")
        self.set_visible_child_name("progress")

    def update_progress(self, phase: str, done: int, total: int, detail: str, eta) -> None:
        frac = done / total if total else None
        counter = f"{done} de {total}" if total else ""
        if phase == "ai":
            counter += f" · {format_eta(eta)}" if eta != 0 else ""
            if self.progress.secondary_btn:
                self.progress.secondary_btn.set_visible(True)
            self.progress.hint.set_text("A IA corre no teu processador, por isso pode demorar. Os resultados "
                                        "ficam guardados: da próxima vez é muito mais rápido.")
            self.progress.hint.set_visible(True)
        self.progress.update(detail, frac, counter, PHASES.get(phase))

    def show_applying(self, total: int) -> None:
        self.progress.start("A arrumar…", "Não feches o Arruma até terminar.")
        self.set_visible_child_name("progress")

    def update_applying(self, done: int, total: int, current: str) -> None:
        self.progress.update(display_path(current), done / total if total else None, f"{done} de {total}")

    # ================================================================== plano
    def _compute_anchor(self, plan: Plan) -> str:
        dirs = list(plan.roots) + list(plan.bases.values())
        for a in plan.actions:
            if a.src:
                dirs.append(os.path.dirname(a.src))
            if a.dst:
                dirs.append(os.path.dirname(a.dst))
        if dirs and all(is_within(d, HOME) for d in dirs):
            return str(HOME)
        if len(plan.roots) == 1 and all(is_within(d, plan.root) for d in dirs):
            return os.path.dirname(plan.root)
        try:
            common = os.path.commonpath(dirs) if dirs else str(HOME)
            return common or "/"
        except ValueError:
            return "/"

    def show_plan(self, plan: Plan) -> None:
        self.progress.stop()
        self.plan = plan
        self.anchor = self._compute_anchor(plan)
        self.search.set_text("")
        self.filter_combo.set_active_id("all")

        for c in self.notes_box.get_children():
            self.notes_box.remove(c)
        for note in plan.notes:
            n = card("warn", spacing=10, horizontal=True)
            n.pack_start(icon("dialog-information-symbolic", 16), False, False, 0)
            n.pack_start(label(note, wrap=True), True, True, 0)
            self.notes_box.pack_start(n, False, False, 0)
        self.notes_box.show_all()

        self._build_kept_popover(plan)
        self._update_top_summary()
        if not plan.actions:
            self._show_nothing_to_do()
            return
        self.views.set_visible_child_name("after")
        self._repopulate()
        self._show_detail(None)
        self.set_visible_child_name("content")

    def _show_nothing_to_do(self) -> None:
        for c in self.done_box.get_children():
            self.done_box.remove(c)
        self.done_box.pack_start(Placeholder("emblem-ok-symbolic", "Já está tudo arrumado!",
                                             "Não há nada a mudar nesta seleção. 🎉",
                                             ("Escolher outra pasta", lambda: self.win.navigate("home"))),
                                 True, True, 0)
        self.done_box.show_all()
        self.set_visible_child_name("done")

    def _build_kept_popover(self, plan: Plan) -> None:
        kept = list(plan.respected) + [(p, f"Protegida: {why}.") for p, why in self.win.scan_result.protected] \
            if self.win.scan_result else list(plan.respected)
        self.kept_btn.set_visible(bool(kept))
        box = hbox(6)
        box.pack_start(icon("security-high-symbolic", 16), False, False, 0)
        box.pack_start(Gtk.Label(label=f"Mantidas ({len(kept)})"), False, False, 0)
        if self.kept_btn.get_child():
            self.kept_btn.remove(self.kept_btn.get_child())
        self.kept_btn.add(box)
        self.kept_btn.show_all()
        pop = vbox(8, margin_top=14, margin_bottom=14, margin_start=14, margin_end=14)
        pop.pack_start(label("Pastas que ficam como estão", "section-title"), False, False, 0)
        pop.pack_start(label("Têm nome próprio, são projetos ou pertencem a outros programas.", "small", "dim",
                             wrap=True, max_width=50), False, False, 0)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_max_content_height(360)
        sw.set_propagate_natural_height(True)
        lst = vbox(6)
        for path, why in kept[:300]:
            r = vbox(0)
            r.pack_start(label(display_path(path), ellipsize=True, max_width=50), False, False, 0)
            r.pack_start(label(why, "small", "dim", wrap=True, max_width=50), False, False, 0)
            lst.pack_start(r, False, False, 0)
        sw.add(lst)
        pop.pack_start(sw, True, True, 0)
        if self.kept_pop.get_child():
            self.kept_pop.remove(self.kept_pop.get_child())
        self.kept_pop.add(pop)
        pop.show_all()

    def _update_top_summary(self) -> None:
        plan = self.plan
        if not plan:
            return
        acts = plan.actions
        parts = []
        groups = [
            ("📄", "documento", "documentos", lambda a: a.op == "move" and a.kind in (tx.DOCUMENT, tx.BOOK)),
            ("🖼️", "imagem", "imagens", lambda a: a.op == "move" and a.kind == tx.IMAGE),
            ("🎬", "vídeo", "vídeos", lambda a: a.op == "move" and a.kind == tx.VIDEO),
            ("🎵", "áudio", "áudios", lambda a: a.op == "move" and a.kind == tx.AUDIO),
            ("📦", "outro ficheiro", "outros ficheiros", lambda a: a.op == "move" and a.kind in
             (tx.ARCHIVE, tx.INSTALLER, tx.CODE, tx.OTHER)),
            ("📁", "pasta inteira", "pastas inteiras", lambda a: a.op == "move_dir"),
            ("🗑️", "item para limpar", "itens para limpar", lambda a: a.op in ("trash", "rmdir")),
        ]
        for emoji, s, p, pred in groups:
            n = sum(1 for a in acts if pred(a))
            if n:
                parts.append(f"{emoji} {plural(n, s, p)}")
        renamed = sum(1 for a in acts if a.renamed)
        if renamed:
            parts.append(f"✏️ {plural(renamed, 'nome novo', 'nomes novos')}")
        txt = "  ·  ".join(parts)
        if plan.ai_model:
            txt += f"\n<span size='small'>A IA local ({esc(plan.ai_model)}) leu {plan.ai_count} documentos.</span>"
        self.summary.set_markup(txt)
        self._update_selection_label()

    def _update_selection_label(self) -> None:
        if not self.plan:
            return
        en = self.plan.enabled()
        size = sum(a.size for a in en if a.op != "rmdir")
        self.sel_label.set_markup(f"<b>{len(en)}</b> de {len(self.plan.actions)} alterações selecionadas"
                                  f"  <span alpha='60%'>· {human_size(size)}</span>")
        self.apply_btn.set_sensitive(bool(en))

    # ================================================================== árvore
    def _visible_actions(self) -> list[Action]:
        q = self.search.get_text().strip().lower()
        f = self.filter_id
        out = []
        for a in self.plan.actions:
            if f == "documents" and not (a.op == "move" and a.kind in (tx.DOCUMENT, tx.BOOK)):
                continue
            if f == "pictures" and not (a.op == "move" and a.kind == tx.IMAGE):
                continue
            if f == "videos" and not (a.op == "move" and a.kind == tx.VIDEO):
                continue
            if f == "music" and not (a.op == "move" and a.kind == tx.AUDIO):
                continue
            if f == "other" and not (a.op == "move" and a.kind in (tx.ARCHIVE, tx.INSTALLER, tx.CODE, tx.OTHER)):
                continue
            if f == "folders" and a.op != "move_dir":
                continue
            if f == "cleanup" and a.op not in ("trash", "rmdir"):
                continue
            if f == "renamed" and not a.renamed:
                continue
            if f == "ai" and a.source != "IA":
                continue
            if f == "review" and not (a.confidence < 0.55 and a.op in ("move", "move_dir")):
                continue
            if q and q not in a.src.lower() and q not in a.dst.lower():
                continue
            out.append(a)
        return out

    def _parts(self, directory: str) -> list[str]:
        rel = os.path.relpath(directory, self.anchor)
        return [] if rel == "." else [p for p in rel.split(os.sep) if p]

    def _repopulate(self, select_id: int | None = None, select_folder: str | None = None) -> None:
        if not self.plan:
            return
        self.anchor = self._compute_anchor(self.plan)
        which = self.views.get_visible_child_name() or "after"
        tv, store = self.trees[which]
        tv.set_model(None)
        store.clear()
        nodes: dict[tuple, Gtk.TreeIter] = {}
        stats: dict[tuple, list] = {}

        def ensure(parts: list[str]):
            key = tuple(parts)
            if not key:
                return None
            if key in nodes:
                return nodes[key]
            parent = ensure(parts[:-1])
            special = key[0] in (TRASH_NODE, EMPTY_NODE)
            exists = special or os.path.isdir(os.path.join(self.anchor, *parts))
            ico = "user-trash" if key == (TRASH_NODE,) else ("folder" if exists else "folder-new")
            it = store.append(parent, [True, False, ico, "", -1, "\x1f".join(key), ""])
            nodes[key] = it
            stats[key] = [0, 0, exists]
            return it

        visible = self._visible_actions()
        for a in visible:
            if which == "after":
                if a.op == "trash":
                    parts = [TRASH_NODE]
                elif a.op == "rmdir":
                    parts = [EMPTY_NODE]
                else:
                    parts = self._parts(os.path.dirname(a.dst))
            else:
                parts = self._parts(os.path.dirname(a.src))
            parent = ensure(parts)
            store.append(parent, [a.enabled, False, self._icon(a), self._leaf_markup(a, which), a.id, "",
                                  self._badge(a)])
            for i in range(1, len(parts) + 1):
                s = stats[tuple(parts[:i])]
                s[0] += 1
                s[1] += a.size
        for key, it in nodes.items():
            n, size, exists = stats[key]
            extra = "" if exists else "  <span size='small' foreground='#1c71d8'>• nova</span>"
            size_txt = f" · {human_size(size)}" if size else ""
            store.set_value(it, COL_MARKUP, f"<b>{esc(key[-1])}</b>{extra}\n"
                                            f"<span size='small' alpha='60%'>{plural(n, 'item', 'itens')}{size_txt}</span>")
        self._refresh_states(store)
        tv.set_model(store)
        if len(visible) < 1500 or self.search.get_text():
            tv.expand_all()
        else:
            it = store.get_iter_first()
            while it:
                tv.expand_row(store.get_path(it), False)
                it = store.iter_next(it)
        if select_id is not None:
            self._select_action(tv, store, select_id)
        elif select_folder is not None:
            self._select_folder(tv, store, select_folder)
        self._update_top_summary()

    def _icon(self, a: Action) -> str:
        if a.op == "move_dir":
            return "folder"
        if a.op == "rmdir":
            return "folder"
        return kind_icon(a.kind)

    def _leaf_markup(self, a: Action, which: str) -> str:
        small = "<span size='small' alpha='62%'>{}</span>"
        if which == "after":
            if a.op == "trash":
                return f"{esc(a.src_name)}\n" + small.format(f"de {esc(display_path(os.path.dirname(a.src)))}")
            if a.op == "rmdir":
                return f"{esc(a.src_name)}\n" + small.format(esc(display_path(a.src)))
            name = esc(a.dst_name)
            if a.renamed:
                name += "  <span size='small' foreground='#1c71d8'>✏️ nome novo</span>"
                sub = f"era «{esc(a.src_name)}» em {esc(display_path(os.path.dirname(a.src)))}"
            else:
                sub = f"de {esc(display_path(os.path.dirname(a.src)))}"
            if a.op == "move_dir":
                sub = f"pasta inteira ({a.count} ficheiros) · " + sub
            return f"{name}\n" + small.format(sub)
        if a.op == "trash":
            target = "→ Lixo (recuperável)"
        elif a.op == "rmdir":
            target = "→ remover (está vazia)"
        else:
            target = f"→ {esc(display_path(a.dst))}"
        return f"{esc(a.src_name)}\n" + small.format(target)

    def _badge(self, a: Action) -> str:
        text, color = SOURCE_LABEL.get(a.source, (a.source, "#77767b"))
        warn = " ⚠️" if a.confidence < 0.55 and a.op in ("move", "move_dir") else ""
        return f"<span size='small' foreground='{color}' weight='bold'>{esc(text)}</span>{warn}"

    def _refresh_states(self, store: Gtk.TreeStore, it=None) -> tuple[bool, bool]:
        child = store.iter_children(it)
        all_on, any_on = True, False
        has = False
        while child is not None:
            has = True
            if store.get_value(child, COL_ID) >= 0:
                on = store.get_value(child, COL_ACTIVE)
                c_all, c_any = on, on
            else:
                c_all, c_any = self._refresh_states(store, child)
            all_on = all_on and c_all
            any_on = any_on or c_any
            child = store.iter_next(child)
        if it is not None:
            store.set_value(it, COL_ACTIVE, all_on and has)
            store.set_value(it, COL_INCONS, any_on and not all_on)
        return all_on, any_on

    def _set_subtree(self, store: Gtk.TreeStore, it, value: bool) -> None:
        aid = store.get_value(it, COL_ID)
        if aid >= 0:
            self.plan.actions[aid].enabled = value
        store.set_value(it, COL_ACTIVE, value)
        store.set_value(it, COL_INCONS, False)
        child = store.iter_children(it)
        while child is not None:
            self._set_subtree(store, child, value)
            child = store.iter_next(child)

    def _on_toggled(self, _renderer, path: str, store: Gtk.TreeStore) -> None:
        it = store.get_iter(path)
        new = True if store.get_value(it, COL_INCONS) else not store.get_value(it, COL_ACTIVE)
        self._set_subtree(store, it, new)
        self._refresh_states(store)
        self._update_selection_label()

    def _select_all(self, value: bool) -> None:
        for a in self._visible_actions():
            a.enabled = value
        self._repopulate()

    def _on_filter(self, combo) -> None:
        self.filter_id = combo.get_active_id() or "all"
        self._repopulate()

    def _expand(self, expand: bool) -> None:
        tv, _ = self.trees[self.views.get_visible_child_name() or "after"]
        tv.expand_all() if expand else tv.collapse_all()

    def _select_action(self, tv, store, aid: int) -> None:
        def walk(it):
            while it is not None:
                if store.get_value(it, COL_ID) == aid:
                    path = store.get_path(it)
                    tv.expand_to_path(path)
                    tv.get_selection().select_path(path)
                    tv.scroll_to_cell(path, None, True, 0.4, 0)
                    return True
                if walk(store.iter_children(it)):
                    return True
                it = store.iter_next(it)
            return False
        walk(store.get_iter_first())

    def _select_folder(self, tv, store, folder_path: str) -> None:
        target_key = "\x1f".join(self._parts(folder_path))

        def walk(it):
            while it is not None:
                if store.get_value(it, COL_ID) == -1 and store.get_value(it, COL_KEY) == target_key:
                    path = store.get_path(it)
                    tv.expand_to_path(path)
                    tv.get_selection().select_path(path)
                    tv.scroll_to_cell(path, None, True, 0.4, 0)
                    return True
                if walk(store.iter_children(it)):
                    return True
                it = store.iter_next(it)
            return False
        walk(store.get_iter_first())

    def _on_row_activated(self, tv, path, _col) -> None:
        model = tv.get_model()
        aid = model.get_value(model.get_iter(path), COL_ID)
        if aid >= 0:
            a = self.plan.actions[aid]
            if a.op in ("move", "trash") and os.path.exists(a.src):
                open_path(a.src)
        elif tv.row_expanded(path):
            tv.collapse_row(path)
        else:
            tv.expand_row(path, False)

    # ================================================================== menu de contexto, F2 e arrastar (DnD)
    def _on_tree_key_press(self, tv: Gtk.TreeView, event: Gdk.EventKey) -> bool:
        if (self.views.get_visible_child_name() or "after") != "after":
            return False
        if event.keyval == Gdk.KEY_F2:
            model, it = tv.get_selection().get_selected()
            if it is not None:
                self._prompt_rename_iter(model, it)
                return True
        return False

    def _on_tree_button_press(self, tv: Gtk.TreeView, event: Gdk.EventButton) -> bool:
        if event.button != 3 or (self.views.get_visible_child_name() or "after") != "after":
            return False
        hit = tv.get_path_at_pos(int(event.x), int(event.y))
        if not hit:
            return False
        path, col, _, _ = hit
        tv.get_selection().select_path(path)
        model = tv.get_model()
        it = model.get_iter(path)
        aid = model.get_value(it, COL_ID)
        key_str = model.get_value(it, COL_KEY)

        menu = Gtk.Menu()
        if aid == -1:
            key = key_str.split("\x1f")
            if key[0] not in (TRASH_NODE, EMPTY_NODE):
                folder_path = os.path.join(self.anchor, *key)
                mi_ren = Gtk.MenuItem(label="Mudar nome da pasta… (F2)")
                mi_ren.connect("activate", lambda *_: self._prompt_rename_folder(folder_path, key[-1]))
                menu.append(mi_ren)
                mi_mov = Gtk.MenuItem(label="Mover pasta para outro local…")
                mi_mov.connect("activate", lambda *_: self._choose_folder_dest(folder_path))
                menu.append(mi_mov)
        else:
            a = self.plan.actions[aid]
            if a.op in ("move", "move_dir"):
                mi_ren = Gtk.MenuItem(label="Mudar nome proposto… (F2)")
                mi_ren.connect("activate", lambda *_: self._prompt_rename_action(a))
                menu.append(mi_ren)
                mi_mov = Gtk.MenuItem(label="Escolher outra pasta de destino…")
                mi_mov.connect("activate", lambda *_: self._choose_dest(a))
                menu.append(mi_mov)
            if a.op != "rmdir":
                mi_open = Gtk.MenuItem(label="Mostrar na pasta atual")
                mi_open.connect("activate", lambda *_: show_in_folder(a.src))
                menu.append(mi_open)

        if len(menu.get_children()) > 0:
            menu.show_all()
            menu.popup_at_pointer(event)
            return True
        return False

    def _prompt_rename_iter(self, model: Gtk.TreeModel, it: Gtk.TreeIter) -> None:
        aid = model.get_value(it, COL_ID)
        if aid >= 0:
            a = self.plan.actions[aid]
            if a.op in ("move", "move_dir"):
                self._prompt_rename_action(a)
        else:
            key = model.get_value(it, COL_KEY).split("\x1f")
            if key and key[0] not in (TRASH_NODE, EMPTY_NODE):
                self._prompt_rename_folder(os.path.join(self.anchor, *key), key[-1])

    def _prompt_rename_folder(self, folder_path: str, current_name: str) -> None:
        new_name = prompt_text(
            self.win,
            "Mudar nome da pasta sugerida",
            f"Escolhe o novo nome para a pasta «{current_name}».\n"
            "Todos os ficheiros e subpastas dentro dela serão atualizados automaticamente.",
            initial=current_name,
            ok_label="Guardar nome",
        )
        if new_name:
            self._apply_folder_rename(folder_path, new_name)

    def _apply_folder_rename(self, folder_path: str, new_name: str) -> None:
        if not self.plan:
            return
        new_dir = rename_folder_in_plan(self.plan, folder_path, new_name)
        if new_dir != folder_path:
            self._repopulate(select_folder=new_dir)
            self.win.toast.show(f"Pasta renomeada para «{os.path.basename(new_dir)}».")

    def _choose_folder_dest(self, folder_path: str) -> None:
        if not self.plan:
            return
        target_parent = choose_folder(self.win, "Mover pasta para dentro de…", os.path.dirname(folder_path))
        if target_parent:
            new_dir = move_folder_in_plan(self.plan, folder_path, target_parent)
            if new_dir:
                self._repopulate(select_folder=new_dir)
                self.win.toast.show(f"Pasta movida para «{display_path(new_dir)}».")

    def _prompt_rename_action(self, a: Action) -> None:
        new_name = prompt_text(
            self.win,
            "Mudar nome proposto",
            f"Escolhe o nome com que «{a.src_name}» ficará guardado:",
            initial=a.dst_name,
            ok_label="Guardar nome",
        )
        if new_name:
            self._apply_action_rename(a, new_name)

    def _apply_action_rename(self, a: Action, new_name: str) -> None:
        if not self.plan:
            return
        rename_action_in_plan(a, self.plan, new_name)
        self._repopulate(select_id=a.id)
        self._show_detail(a)

    # ---- Drag and Drop na árvore "Depois"
    def _on_drag_data_get(self, tv: Gtk.TreeView, _context, selection_data: Gtk.SelectionData,
                          _info: int, _time: int) -> None:
        model, it = tv.get_selection().get_selected()
        if it is None:
            return
        aid = model.get_value(it, COL_ID)
        if aid >= 0:
            a = self.plan.actions[aid]
            if a.op == "rmdir":
                return
            payload = f"A:{aid}"
        else:
            key_str = model.get_value(it, COL_KEY)
            if not key_str or key_str.split("\x1f")[0] in (TRASH_NODE, EMPTY_NODE):
                return
            payload = f"F:{key_str}"
        selection_data.set(selection_data.get_target(), 8, payload.encode("utf-8"))

    def _on_drag_data_received(self, tv: Gtk.TreeView, context: Gdk.DragContext, x: int, y: int,
                               selection_data: Gtk.SelectionData, _info: int, time: int) -> None:
        if not self.plan:
            context.finish(False, False, time)
            return
        data = selection_data.get_data()
        if not data:
            context.finish(False, False, time)
            return
        raw = data.decode("utf-8", errors="ignore")
        dest = tv.get_dest_row_at_pos(x, y)
        if dest is None:
            context.finish(False, False, time)
            return
        dest_path, drop_pos = dest
        model = tv.get_model()
        dest_iter = model.get_iter(dest_path)
        dest_aid = model.get_value(dest_iter, COL_ID)
        dest_key_str = model.get_value(dest_iter, COL_KEY)

        # Determinar pasta de destino onde o utilizador largou o item
        target_trash = False
        target_dir: str | None = None
        if dest_aid == -1:
            dest_parts = dest_key_str.split("\x1f")
            if dest_parts[0] == TRASH_NODE:
                target_trash = True
            elif dest_parts[0] == EMPTY_NODE:
                context.finish(False, False, time)
                return
            else:
                target_dir = os.path.join(self.anchor, *dest_parts)
        else:
            dest_act = self.plan.actions[dest_aid]
            if dest_act.op == "trash":
                target_trash = True
            elif dest_act.op == "rmdir":
                context.finish(False, False, time)
                return
            elif dest_act.op == "move_dir" and drop_pos in (
                Gtk.TreeViewDropPosition.INTO_OR_BEFORE,
                Gtk.TreeViewDropPosition.INTO_OR_AFTER,
            ):
                target_dir = dest_act.dst
            else:
                target_dir = os.path.dirname(dest_act.dst)

        if raw.startswith("A:"):
            aid = int(raw[2:])
            a = self.plan.actions[aid]
            if target_trash:
                if a.op == "trash":
                    context.finish(False, False, time)
                    return
                a.op = "trash"
                a.dst = ""
                a.renamed = False
                a.source = "manual"
                a.confidence = 1.0
                a.reason = "Movido manualmente para o Lixo."
                context.finish(True, False, time)
                GLib.idle_add(self._finish_dnd, a.id, None, f"«{a.src_name}» movido para o Lixo.")
                return
            if target_dir:
                if a.op == "move_dir" and (target_dir == a.src or is_within(target_dir, a.src)):
                    context.finish(False, False, time)
                    return
                if a.op in ("move", "move_dir") and os.path.dirname(a.dst) == target_dir:
                    context.finish(False, False, time)
                    return
                retarget(a, self.plan, target_dir)
                context.finish(True, False, time)
                GLib.idle_add(self._finish_dnd, a.id, None,
                              f"«{a.dst_name}» movido para «{display_path(target_dir)}».")
                return

        elif raw.startswith("F:") and target_dir:
            src_parts = raw[2:].split("\x1f")
            src_dir = os.path.join(self.anchor, *src_parts)
            new_dir = move_folder_in_plan(self.plan, src_dir, target_dir)
            if new_dir:
                context.finish(True, False, time)
                GLib.idle_add(self._finish_dnd, None, new_dir,
                              f"Pasta «{src_parts[-1]}» movida para «{display_path(target_dir)}».")
                return

        context.finish(False, False, time)

    def _finish_dnd(self, select_id: int | None, select_folder: str | None, toast_msg: str) -> bool:
        self._repopulate(select_id=select_id, select_folder=select_folder)
        if select_id is not None and self.plan:
            self._show_detail(self.plan.actions[select_id])
        self.win.toast.show(toast_msg)
        return False

    # ================================================================== detalhe
    def _on_selection(self, selection, store) -> None:
        model, it = selection.get_selected()
        if it is None:
            return
        aid = model.get_value(it, COL_ID)
        if aid >= 0:
            self._show_detail(self.plan.actions[aid])
        else:
            key = model.get_value(it, COL_KEY).split("\x1f")
            n = model.iter_n_children(it)
            self._show_folder_detail(key, model.get_value(it, COL_ICON) == "folder-new", n)

    def _set_detail(self, widget: Gtk.Widget) -> None:
        child = self.detail_scroll.get_child()
        if child:
            self.detail_scroll.remove(child)
        self.detail_scroll.add(widget)
        widget.show_all()

    def _field(self, box: Gtk.Box, caption: str, value: str, markup: bool = False) -> None:
        box.pack_start(label(caption, "caps", margin_top=6), False, False, 0)
        box.pack_start(label(value, "detail-value", wrap=True, selectable=True, markup=markup, max_width=40),
                       False, False, 0)

    def _show_folder_detail(self, key: list[str], new: bool, n: int) -> None:
        box = vbox(6, margin_top=24, margin_bottom=24, margin_start=22, margin_end=22)
        box.pack_start(icon("folder-new" if new else "folder", 64), False, False, 0)
        box.pack_start(label(key[-1], "section-title", wrap=True), False, False, 4)
        if key[0] in (TRASH_NODE, EMPTY_NODE):
            txt = ("Ficheiros temporários ou automáticos. Vão para o Lixo do sistema, de onde os podes "
                   "recuperar.") if key[0] == TRASH_NODE else "Pastas vazias sem nome próprio."
            box.pack_start(label(txt, "dim", wrap=True), False, False, 0)
        else:
            path = os.path.join(self.anchor, *key)
            self._field(box, "LOCAL", display_path(path))
            self._field(box, "CONTEÚDO", plural(n, "item direto", "itens diretos"))
            if new:
                box.pack_start(label("Esta pasta ainda não existe e será criada.", "dim", wrap=True,
                                     margin_top=6), False, False, 0)

            if (self.views.get_visible_child_name() or "after") == "after":
                box.pack_start(label("MUDAR NOME DA PASTA", "caps", margin_top=12), False, False, 0)
                ren_row = hbox(6)
                entry = Gtk.Entry()
                entry.set_text(key[-1])
                entry.set_hexpand(True)
                entry.connect("activate", lambda e: self._apply_folder_rename(path, e.get_text()))
                ren_row.pack_start(entry, True, True, 0)
                save_btn = button("Guardar", "emblem-ok-symbolic",
                                  on_click=lambda: self._apply_folder_rename(path, entry.get_text()))
                ren_row.pack_start(save_btn, False, False, 0)
                box.pack_start(ren_row, False, False, 0)

                move_btn = button("Mover pasta para outro local…", "folder-symbolic",
                                  on_click=lambda: self._choose_folder_dest(path))
                move_btn.set_halign(Gtk.Align.START)
                move_btn.set_margin_top(6)
                box.pack_start(move_btn, False, False, 0)

        box.pack_start(label("Dica: podes arrastar ficheiros ou subpastas para outra pasta na árvore à esquerda, "
                             "ou desmarcar a caixa para excluir tudo o que está cá dentro.",
                             "small", "dim", wrap=True, margin_top=14), False, False, 0)
        self._set_detail(box)

    def _show_detail(self, a: Action | None) -> None:
        box = vbox(6, margin_top=24, margin_bottom=24, margin_start=22, margin_end=22)
        if a is None:
            box.set_valign(Gtk.Align.CENTER)
            img = icon("view-dual-symbolic", 48)
            img.set_opacity(0.35)
            box.pack_start(img, False, False, 0)
            box.pack_start(label("Seleciona uma pasta ou ficheiro para veres os detalhes, mudar o nome "
                                 "ou escolher outro destino.", "dim",
                                 xalign=0.5, wrap=True, justify=Gtk.Justification.CENTER), False, False, 8)
            box.pack_start(label("Dica: também podes arrastar ficheiros e pastas diretamente na árvore.",
                                 "small", "dim", xalign=0.5, wrap=True, justify=Gtk.Justification.CENTER),
                           False, False, 0)
            self._set_detail(box)
            return

        box.pack_start(icon(self._icon(a), 64), False, False, 0)
        title = a.dst_name if a.op in ("move", "move_dir") else a.src_name
        box.pack_start(label(title, "section-title", wrap=True, selectable=True, max_width=40), False, False, 4)
        if a.renamed:
            self._field(box, "NOME ATUAL", a.src_name)
        self._field(box, "ESTÁ EM", display_path(os.path.dirname(a.src)))
        if a.op == "trash":
            self._field(box, "VAI PARA", "Lixo do sistema (podes recuperar)")
        elif a.op == "rmdir":
            self._field(box, "VAI SER", "Removida (está vazia)")
        else:
            self._field(box, "VAI PARA", display_path(os.path.dirname(a.dst)))
        self._field(box, "PORQUÊ", a.reason)

        if a.op in ("move", "move_dir"):
            box.pack_start(label("CERTEZA", "caps", margin_top=6), False, False, 0)
            lvl = Gtk.LevelBar()
            lvl.set_min_value(0)
            lvl.set_max_value(1)
            lvl.set_value(a.confidence)
            lvl.set_size_request(-1, 8)
            box.pack_start(lvl, False, False, 2)
            word = "Alta" if a.confidence >= 0.75 else ("Média" if a.confidence >= 0.55 else "Baixa — confirma")
            src, _ = SOURCE_LABEL.get(a.source, (a.source, ""))
            who = f"IA local ({self.plan.ai_model})" if a.source == "IA" and self.plan.ai_model else src
            box.pack_start(label(f"{word} · decidido por {who}", "small", "dim", wrap=True), False, False, 0)

        size = human_size(a.size) + (f" · {a.count} ficheiros" if a.op == "move_dir" else "")
        if a.op != "rmdir":
            self._field(box, "TAMANHO", size)

        if a.op in ("move", "move_dir"):
            box.pack_start(label("MUDAR NOME PROPOSTO", "caps", margin_top=10), False, False, 0)
            ren_row = hbox(6)
            entry = Gtk.Entry()
            entry.set_text(a.dst_name)
            entry.set_hexpand(True)
            entry.connect("activate", lambda e: self._apply_action_rename(a, e.get_text()))
            ren_row.pack_start(entry, True, True, 0)
            save_btn = button("Guardar", "emblem-ok-symbolic",
                              on_click=lambda: self._apply_action_rename(a, entry.get_text()))
            ren_row.pack_start(save_btn, False, False, 0)
            box.pack_start(ren_row, False, False, 0)

        if a.op in ("move", "move_dir") and a.kind in (tx.DOCUMENT, tx.BOOK):
            box.pack_start(label("MUDAR DE ÁREA", "caps", margin_top=10), False, False, 0)
            combo = Gtk.ComboBoxText()
            for area in tx.AREAS:
                combo.append(area, f"{tx.AREA_ICONS.get(area, '')}  {area}")
            if a.area in tx.AREAS:
                combo.set_active_id(a.area)
            combo.connect("changed", self._on_area_changed, a)
            box.pack_start(combo, False, False, 0)

        btns = Gtk.FlowBox()
        btns.set_selection_mode(Gtk.SelectionMode.NONE)
        btns.set_max_children_per_line(3)
        btns.set_margin_top(14)
        if a.op != "rmdir":
            btns.add(button("Abrir", "document-open-symbolic", on_click=lambda: open_path(a.src)))
        btns.add(button("Mostrar", "folder-open-symbolic", on_click=lambda: show_in_folder(a.src)))
        if a.op in ("move", "move_dir"):
            btns.add(button("Outro destino…", "document-edit-symbolic", on_click=lambda: self._choose_dest(a)))
        box.pack_start(btns, False, False, 0)
        self._set_detail(box)

    def _on_area_changed(self, combo, a: Action) -> None:
        area = combo.get_active_id()
        if not area or area == a.area:
            return
        rebase_document(a, self.plan, area)
        self._repopulate(select_id=a.id)
        self._show_detail(a)

    def _choose_dest(self, a: Action) -> None:
        initial = os.path.dirname(a.dst) if a.dst else os.path.dirname(a.src)
        folder = choose_folder(self.win, "Escolhe o destino", initial)
        if folder:
            if a.op == "move_dir" and is_within(folder, a.src):
                return
            retarget(a, self.plan, folder)
            self._repopulate(select_id=a.id)
            self._show_detail(a)

    # ================================================================== aplicar
    def _on_apply(self) -> None:
        en = self.plan.enabled()
        moves = sum(1 for a in en if a.op in ("move", "move_dir"))
        trash = sum(1 for a in en if a.op == "trash")
        parts = []
        if moves:
            parts.append(f"{plural(moves, 'item vai ser movido', 'itens vão ser movidos')} para as novas pastas.")
        if trash:
            parts.append(f"{plural(trash, 'ficheiro temporário vai', 'ficheiros temporários vão')} para o Lixo.")
        parts.append("Nada é apagado definitivamente e podes anular tudo no Histórico.")
        if confirm(self.win, f"Aplicar {len(en)} alterações?", "\n".join(parts), "Aplicar"):
            self.win.apply_plan(en)

    def show_done(self, res: Result, plan: Plan) -> None:
        self.progress.stop()
        for c in self.done_box.get_children():
            self.done_box.remove(c)
        box = vbox(12, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        box.set_size_request(520, -1)
        box.pack_start(icon("emblem-ok-symbolic", 84, "success-icon"), False, False, 0)
        box.pack_start(label("Está arrumado!", "hero-title", xalign=0.5), False, False, 0)
        box.pack_start(label(f"{plural(res.ok, 'alteração aplicada', 'alterações aplicadas')} "
                             f"({human_size(res.bytes_moved)} organizados).", "subtitle", xalign=0.5),
                       False, False, 0)
        if res.errors:
            exp = Gtk.Expander(label=f"{plural(len(res.errors), 'item não pôde', 'itens não puderam')} ser alterados")
            lst = vbox(4, margin_top=6)
            for path, err in res.errors[:100]:
                lst.pack_start(label(f"{display_path(path)} — {err}", "small", "dim", wrap=True, max_width=70),
                               False, False, 0)
            exp.add(lst)
            box.pack_start(exp, False, False, 0)
        row = hbox(10, halign=Gtk.Align.CENTER, margin_top=14)
        target = plan.root if plan.mode == "inside" else plan.bases["documents"]
        row.pack_start(button("Abrir pasta", "folder-open-symbolic", on_click=lambda: open_path(target)), False, False, 0)
        row.pack_start(button("Anular", "edit-undo-symbolic", on_click=lambda: self.win.undo_session(res.session_id)),
                       False, False, 0)
        row.pack_start(button("Arrumar outra pasta", None, "suggested-action",
                              on_click=lambda: self.win.navigate("home")), False, False, 0)
        box.pack_start(row, False, False, 0)
        box.pack_start(label("Dica: volta a analisar daqui a umas semanas; o Arruma respeita o que já está "
                             "arrumado e só trata do que é novo.", "small", "dim", xalign=0.5, wrap=True,
                             justify=Gtk.Justification.CENTER, margin_top=10), False, False, 0)
        self.done_box.pack_start(box, True, True, 0)
        self.done_box.show_all()
        self.set_visible_child_name("done")

    def reset(self) -> None:
        self.plan = None
        self.set_visible_child_name("empty")

