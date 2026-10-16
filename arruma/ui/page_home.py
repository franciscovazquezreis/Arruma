"""Página inicial: escolher uma ou mais pastas (ou todo o computador) e ver o estado da IA local."""

from __future__ import annotations

import os

from gi.repository import Gdk, Gtk

from ..core.ai import RECOMMENDED_MODEL, AIStatus
from ..core.fsutil import COMPUTER_TOKEN, HOME, display_path, expand_computer_roots, plural, user_dirs
from ..core.system import DISPLAY_NAMES, is_hidden_entry
from .widgets import add_classes, button, card, choose_folders, hbox, icon, label, vbox


def _count_items(path: str) -> int | None:
    try:
        with os.scandir(path) as it:
            return sum(1 for e in it if not is_hidden_entry(e))
    except OSError:
        return None


class HomePage(Gtk.ScrolledWindow):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.selected_paths: list[str] = []
        self.custom_paths: list[str] = []
        self._card_widgets: dict[str, tuple[Gtk.Button, Gtk.Widget]] = {}

        outer = vbox(22, margin_top=36, margin_bottom=36, margin_start=36, margin_end=36)
        outer.set_halign(Gtk.Align.CENTER)
        outer.set_size_request(860, -1)

        head = vbox(6)
        head.pack_start(label("O que queres arrumar?", "hero-title"), False, False, 0)
        head.pack_start(label(
            "Seleciona uma pasta, várias pastas ao mesmo tempo ou todo o computador. "
            "O Arruma analisa tudo, propõe uma organização clara e só altera alguma coisa depois de aprovares.",
            "subtitle", wrap=True, max_width=92), False, False, 0)
        outer.pack_start(head, False, False, 0)

        self.flow = Gtk.FlowBox()
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_homogeneous(True)
        self.flow.set_min_children_per_line(2)
        self.flow.set_max_children_per_line(4)
        self.flow.set_column_spacing(14)
        self.flow.set_row_spacing(14)
        outer.pack_start(self.flow, False, False, 0)

        # Barra de seleção e arranque da análise
        sel_bar = card("accent", spacing=12, horizontal=True)
        sel_col = vbox(2)
        self.sel_title = label("", "section-title")
        self.sel_sub = label("", "small", "dim", wrap=True, max_width=64)
        sel_col.pack_start(self.sel_title, False, False, 0)
        sel_col.pack_start(self.sel_sub, False, False, 0)
        sel_bar.pack_start(sel_col, True, True, 0)

        self.clear_btn = button("Limpar seleção", None, "flat", on_click=self._clear_selection)
        self.clear_btn.set_valign(Gtk.Align.CENTER)
        sel_bar.pack_start(self.clear_btn, False, False, 0)

        self.start_btn = button("Analisar seleção", "emblem-ok-symbolic", "suggested-action", "big-button",
                                on_click=self._start_selected)
        self.start_btn.set_valign(Gtk.Align.CENTER)
        sel_bar.pack_start(self.start_btn, False, False, 0)
        outer.pack_start(sel_bar, False, False, 0)

        self.refresh_folders()

        # Estado da IA local
        self.ai_card = card(spacing=16, horizontal=True)
        self.ai_icon = icon("applications-science-symbolic", 30, "insight-icon")
        self.ai_icon.set_valign(Gtk.Align.CENTER)
        col = vbox(4)
        top = hbox(10)
        top.pack_start(label("Inteligência artificial local", "section-title"), False, False, 0)
        self.ai_pill = label("a verificar…", "pill", "info")
        top.pack_start(self.ai_pill, False, False, 0)
        col.pack_start(top, False, False, 0)
        self.ai_text = label("", "dim", wrap=True, max_width=80)
        col.pack_start(self.ai_text, False, False, 0)
        self.ai_btn = button("Como ativar", None)
        self._btn_target = self.win.show_ai_help
        self.ai_btn.connect("clicked", lambda *_: self._btn_target())
        self.ai_btn.set_valign(Gtk.Align.CENTER)
        refresh = button("", "view-refresh-symbolic", on_click=self.win.refresh_ai,
                         tooltip="Verificar novamente")
        refresh.set_valign(Gtk.Align.CENTER)
        self.ai_card.pack_start(self.ai_icon, False, False, 0)
        self.ai_card.pack_start(col, True, True, 0)
        self.ai_card.pack_start(self.ai_btn, False, False, 0)
        self.ai_card.pack_start(refresh, False, False, 0)
        outer.pack_start(self.ai_card, False, False, 0)

        # Garantias
        promises = hbox(28, margin_top=4)
        for ico, title, text in (
            ("network-offline-symbolic", "Sem internet", "Nenhum ficheiro sai do computador."),
            ("view-dual-symbolic", "Revês tudo antes", "Nada muda sem a tua aprovação."),
            ("edit-undo-symbolic", "Sempre reversível", "Podes anular qualquer arrumação."),
        ):
            b = hbox(10)
            i = icon(ico, 20, "insight-icon")
            i.set_valign(Gtk.Align.START)
            b.pack_start(i, False, False, 0)
            c = vbox(1)
            c.pack_start(label(title, "section-title"), False, False, 0)
            c.pack_start(label(text, "small", "dim", wrap=True), False, False, 0)
            b.pack_start(c, True, True, 0)
            promises.pack_start(b, True, True, 0)
        outer.pack_start(promises, False, False, 0)

        self.add(outer)

    def refresh_folders(self) -> None:
        for child in self.flow.get_children():
            self.flow.remove(child)
        self._card_widgets.clear()
        xdg = user_dirs()
        entries = [
            ("folder-download", "DOWNLOAD", str(xdg["DOWNLOAD"])),
            ("user-desktop", "DESKTOP", str(xdg["DESKTOP"])),
            ("folder-documents", "DOCUMENTS", str(xdg["DOCUMENTS"])),
            ("folder-pictures", "PICTURES", str(xdg["PICTURES"])),
            ("folder-videos", "VIDEOS", str(xdg["VIDEOS"])),
            ("folder-music", "MUSIC", str(xdg["MUSIC"])),
            ("user-home", "HOME", str(HOME)),
        ]
        known_paths = {p for _, _, p in entries}
        for ico, key, path in entries:
            if os.path.isdir(path):
                n = _count_items(path)
                sub = plural(n, "item", "itens") if n is not None else display_path(path)
                # No Windows e no macOS as pastas chamam-se Documents, Downloads… no disco.
                title = "Pasta pessoal" if key == "HOME" else DISPLAY_NAMES.get(key, os.path.basename(path))
                self.flow.add(self._selectable_card(ico, title, sub, path))

        # Todo o computador
        comp_roots = expand_computer_roots()
        comp_sub = "Pasta pessoal e discos" if len(comp_roots) > 1 else "Todas as pastas do utilizador"
        self.flow.add(self._selectable_card("computer-symbolic", "Todo o computador", comp_sub, COMPUTER_TOKEN))

        # Pastas adicionais escolhidas pelo utilizador
        for path in list(self.custom_paths):
            if path not in known_paths and os.path.isdir(path):
                n = _count_items(path)
                sub = plural(n, "item", "itens") if n is not None else display_path(path)
                self.flow.add(self._selectable_card("folder", os.path.basename(path) or path, sub, path))

        self.flow.add(self._action_card("folder-open", "Outras pastas…", "Escolher uma ou várias",
                                        self._choose_other))
        self.flow.show_all()
        self._sync_selection_ui()

    def _selectable_card(self, ico: str, title: str, sub: str, key: str) -> Gtk.Widget:
        btn = Gtk.Button()
        add_classes(btn, "folder-card")
        overlay = Gtk.Overlay()
        box = vbox(6)
        box.pack_start(icon(ico, 48), False, False, 0)
        box.pack_start(label(title, "name", xalign=0.5, ellipsize=True), False, False, 0)
        box.pack_start(label(sub, "small", "dim", xalign=0.5, ellipsize=True), False, False, 0)
        overlay.add(box)

        check = icon("emblem-ok-symbolic", 18, "check-badge")
        check.set_halign(Gtk.Align.END)
        check.set_valign(Gtk.Align.START)
        check.set_no_show_all(True)
        overlay.add_overlay(check)

        btn.add(overlay)
        btn.connect("clicked", lambda *_: self._toggle_path(key))
        btn.connect("button-press-event", self._on_card_button_press, key)
        btn.set_tooltip_text(f"Clica para selecionar «{title}» (duplo clique para analisar já)")
        self._card_widgets[key] = (btn, check)
        return btn

    def _action_card(self, ico: str, title: str, sub: str, cb) -> Gtk.Widget:
        btn = Gtk.Button()
        add_classes(btn, "folder-card")
        box = vbox(6)
        box.pack_start(icon(ico, 48), False, False, 0)
        box.pack_start(label(title, "name", xalign=0.5, ellipsize=True), False, False, 0)
        box.pack_start(label(sub, "small", "dim", xalign=0.5, ellipsize=True), False, False, 0)
        btn.add(box)
        btn.connect("clicked", lambda *_: cb())
        btn.set_tooltip_text(title)
        return btn

    def _on_card_button_press(self, _widget, event: Gdk.EventButton, key: str) -> bool:
        if event.type == Gdk.EventType._2BUTTON_PRESS and event.button == 1:
            self.selected_paths = [key]
            self._sync_selection_ui()
            self.win.start_scan([key])
            return True
        return False

    def _toggle_path(self, key: str) -> None:
        if key == COMPUTER_TOKEN:
            if COMPUTER_TOKEN in self.selected_paths:
                self.selected_paths.remove(COMPUTER_TOKEN)
            else:
                self.selected_paths = [COMPUTER_TOKEN]
        else:
            if COMPUTER_TOKEN in self.selected_paths:
                self.selected_paths.remove(COMPUTER_TOKEN)
            if key in self.selected_paths:
                self.selected_paths.remove(key)
            else:
                self.selected_paths.append(key)
        self._sync_selection_ui()

    def _clear_selection(self) -> None:
        self.selected_paths.clear()
        self._sync_selection_ui()

    def _sync_selection_ui(self) -> None:
        for key, (btn, check) in self._card_widgets.items():
            active = key in self.selected_paths
            ctx = btn.get_style_context()
            if active:
                ctx.add_class("selected")
            else:
                ctx.remove_class("selected")
            check.set_visible(active)

        n = len(self.selected_paths)
        self.clear_btn.set_visible(n > 0)
        self.start_btn.set_sensitive(n > 0)
        if n == 0:
            self.sel_title.set_text("Nenhuma pasta selecionada")
            self.sel_sub.set_text("Clica num ou em vários cartões acima para escolheres o que queres arrumar "
                                  "(ou faz duplo clique num cartão para começar logo).")
            self.start_btn.set_label("Analisar seleção")
        elif self.selected_paths == [COMPUTER_TOKEN]:
            roots = expand_computer_roots()
            self.sel_title.set_text("Todo o computador selecionado")
            self.sel_sub.set_text("Inclui: " + ", ".join(display_path(r) for r in roots) +
                                  " (as pastas internas do sistema operativo ficam protegidas).")
            self.start_btn.set_label("Analisar todo o computador")
        elif n == 1:
            p = self.selected_paths[0]
            name = os.path.basename(p) or p
            self.sel_title.set_text(f"1 pasta selecionada: {name}")
            self.sel_sub.set_text(f"{display_path(p)}. Podes clicar noutras pastas para juntar mais à seleção.")
            self.start_btn.set_label(f"Analisar «{name}»")
        else:
            names = ", ".join(os.path.basename(p) or p for p in self.selected_paths[:4])
            if n > 4:
                names += f" (+{n - 4})"
            self.sel_title.set_text(f"{n} pastas selecionadas")
            self.sel_sub.set_text(names)
            self.start_btn.set_label(f"Analisar {n} pastas")

    def _start_selected(self) -> None:
        if self.selected_paths:
            self.win.start_scan(list(self.selected_paths))

    def _choose_other(self) -> None:
        paths = choose_folders(self.win, "Escolhe uma ou mais pastas a arrumar", str(HOME))
        if not paths:
            return
        if COMPUTER_TOKEN in self.selected_paths:
            self.selected_paths.remove(COMPUTER_TOKEN)
        for p in paths:
            if p not in self.custom_paths:
                self.custom_paths.append(p)
            if p not in self.selected_paths:
                self.selected_paths.append(p)
        self.refresh_folders()

    def update_ai(self, status: AIStatus | None, enabled: bool) -> None:
        ctx = self.ai_pill.get_style_context()
        for c in ("ok", "off", "info"):
            ctx.remove_class(c)
        if not enabled:
            ctx.add_class("off")
            self.ai_pill.set_text("desligada")
            self.ai_text.set_text("A IA local está desligada nas Definições. A organização usa regras e "
                                  "palavras-chave.")
            self.ai_btn.set_label("Definições")
            self._set_btn(lambda: self.win.navigate("settings"))
        elif status is None:
            ctx.add_class("info")
            self.ai_pill.set_text("a verificar…")
            self.ai_text.set_text("")
        elif status.ok:
            ctx.add_class("ok")
            self.ai_pill.set_text("ativa")
            self.ai_text.set_text(f"Modelo «{status.model}» pronto, a correr neste computador. Vai ler os "
                                  "documentos para os classificar e dar-lhes nomes claros.")
            self.ai_btn.set_label("Definições")
            self._set_btn(lambda: self.win.navigate("settings"))
        else:
            ctx.add_class("off")
            self.ai_pill.set_text("não encontrada")
            self.ai_text.set_text(f"{status.error} Podes usar o Arruma na mesma (com regras e palavras-chave) "
                                  f"ou ativar a IA instalando o Ollama e o modelo {RECOMMENDED_MODEL}.")
            self.ai_btn.set_label("Como ativar")
            self._set_btn(self.win.show_ai_help)

    def _set_btn(self, cb) -> None:
        self._btn_target = cb
