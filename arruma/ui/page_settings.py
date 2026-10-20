# SPDX-License-Identifier: GPL-3.0-or-later
"""Página de definições: IA local, preferências de organização e pastas excluídas."""

from __future__ import annotations

from gi.repository import Gtk

from ..core.ai import RECOMMENDED_MODEL, AIStatus
from ..core.extract import has_ocr, ocr_languages
from ..core.fsutil import HOME, display_path
from ..core.system import TRASH_TO, ocr_install_hint
from .widgets import add_classes, button, choose_folder, hbox, label, pref_group, pref_row, vbox


class SettingsPage(Gtk.ScrolledWindow):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._updating = False

        outer = vbox(22, margin_top=28, margin_bottom=36, margin_start=32, margin_end=32)
        outer.set_halign(Gtk.Align.CENTER)
        outer.set_size_request(760, -1)
        outer.pack_start(label("Definições", "page-title"), False, False, 0)

        # ------------------------------------------------------------------ IA
        outer.pack_start(label("Inteligência artificial local (Ollama)", "section-title"), False, False, 0)
        self.use_ai = Gtk.Switch(active=win.settings.use_ai)
        self.use_ai.connect("notify::active", self._save)

        self.model_combo = Gtk.ComboBoxText()
        self.model_combo.connect("changed", self._save)

        url_box = hbox(6)
        self.url_entry = Gtk.Entry(text=win.settings.ollama_url, width_chars=24)
        self.url_entry.connect("activate", self._save)
        self.url_entry.connect("focus-out-event", lambda *_: (self._save(), False)[1])
        url_box.pack_start(self.url_entry, False, False, 0)
        url_box.pack_start(button("Testar", None, on_click=win.refresh_ai), False, False, 0)

        self.ai_status_lbl = label("a verificar…", "small", "dim", wrap=True)
        status_box = hbox(8)
        status_box.pack_start(self.ai_status_lbl, False, False, 0)
        status_box.pack_start(button("Como instalar", None, "flat", on_click=win.show_ai_help), False, False, 0)

        outer.pack_start(pref_group([
            pref_row("Usar IA local para classificar documentos",
                     f"Lê o texto dos documentos no teu computador para escolher a área e propor nomes claros. "
                     f"Modelo recomendado: {RECOMMENDED_MODEL}.",
                     self.use_ai),
            pref_row("Modelo", "«Automático» escolhe o melhor modelo que tiveres instalado.", self.model_combo),
            pref_row("Endereço do Ollama", "Apenas endereços deste computador (127.0.0.1 / localhost).", url_box),
            pref_row("Estado", "", status_box),
        ]), False, False, 0)

        # ------------------------------------------------------------------ Organização
        outer.pack_start(label("Organização", "section-title"), False, False, 0)
        self.photos_month = Gtk.Switch(active=win.settings.photos_by_month)
        self.rename_unclear = Gtk.Switch(active=win.settings.rename_unclear)
        self.clean_junk = Gtk.Switch(active=win.settings.clean_junk)
        self.remove_empty = Gtk.Switch(active=win.settings.remove_empty_dirs)
        self.include_hidden = Gtk.Switch(active=win.settings.include_hidden)
        for sw in (self.photos_month, self.rename_unclear, self.clean_junk, self.remove_empty, self.include_hidden):
            sw.connect("notify::active", self._save)

        names = {"por": "português", "spa": "espanhol", "fra": "francês", "deu": "alemão", "ita": "italiano",
                 "eng": "inglês"}
        languages = ", ".join(names[lang] for lang in ocr_languages())
        ocr_pill = label((f"instalado: {languages}" if languages else "instalado") if has_ocr()
                         else f"não instalado ({ocr_install_hint()})", "pill", "ok" if has_ocr() else "off")

        outer.pack_start(pref_group([
            pref_row("Agrupar fotografias por ano e mês",
                     "Ex.: Imagens/Fotografias/2024/2024-08 Agosto, quando há muitas fotografias desse ano. "
                     "Se desligares, agrupa apenas por ano.",
                     self.photos_month),
            pref_row("Sugerir nomes claros para ficheiros com nomes vagos",
                     "Só propõe mudar nomes como «scan_003.pdf» ou «Documento (1).pdf». "
                     "Nomes que já fazem sentido nunca são alterados.",
                     self.rename_unclear),
            pref_row(f"Propor envio de ficheiros temporários {TRASH_TO}",
                     "Ficheiros como Thumbs.db, .DS_Store ou transferências incompletas antigas.",
                     self.clean_junk),
            pref_row("Remover pastas genéricas que fiquem vazias",
                     "Pastas como «Nova pasta» que já estavam vazias ou que ficam vazias depois de os seus "
                     "ficheiros serem arrumados. As pastas com nome próprio nunca são removidas.",
                     self.remove_empty),
            pref_row("Incluir ficheiros e pastas ocultos (começados por ponto)",
                     "Desligado por defeito para não mexer em configurações.",
                     self.include_hidden),
            pref_row("Leitura de digitalizações (OCR)",
                     "Permite ler PDF digitalizados sem texto selecionável, em português e, se instalares esses "
                     "idiomas no Tesseract, em espanhol, francês, alemão ou italiano.",
                     ocr_pill),
        ]), False, False, 0)

        # ------------------------------------------------------------------ Pastas excluídas
        head = hbox(10)
        head.pack_start(label("Pastas a ignorar sempre", "section-title"), True, True, 0)
        head.pack_end(button("Adicionar pasta…", "list-add-symbolic", on_click=self._add_excluded), False, False, 0)
        outer.pack_start(head, False, False, 0)
        outer.pack_start(label("Projetos de programação, bibliotecas do Calibre/digiKam/Steam e pastas "
                               "sincronizadas (Dropbox, Nextcloud…) já são protegidos automaticamente.",
                               "small", "dim", wrap=True), False, False, 0)
        self.excl_list = Gtk.ListBox()
        self.excl_list.set_selection_mode(Gtk.SelectionMode.NONE)
        add_classes(self.excl_list, "pref-group")
        outer.pack_start(self.excl_list, False, False, 0)
        self._rebuild_excluded()

        self.add(outer)

    def update_ai(self, status: AIStatus | None) -> None:
        self._updating = True
        cur = self.win.settings.model
        self.model_combo.remove_all()
        self.model_combo.append("", "Automático (recomendado)")
        models = list(status.models) if status else []
        if cur and cur not in models:
            models.append(cur)
        for m in models:
            self.model_combo.append(m, m)
        self.model_combo.set_active_id(cur if cur in models else "")
        if status is None:
            self.ai_status_lbl.set_text("a verificar…")
        elif status.ok:
            self.ai_status_lbl.set_text(f"Ligado ao Ollama {status.version} · modelo ativo: {status.model}")
        else:
            self.ai_status_lbl.set_text(status.error)
        self._updating = False

    def _save(self, *_):
        if self._updating:
            return
        s = self.win.settings
        was_on = s.use_ai
        s.use_ai = self.use_ai.get_active()
        s.model = self.model_combo.get_active_id() or ""
        s.ollama_url = self.url_entry.get_text().strip() or "http://127.0.0.1:11434"
        s.photos_by_month = self.photos_month.get_active()
        s.rename_unclear = self.rename_unclear.get_active()
        s.clean_junk = self.clean_junk.get_active()
        s.remove_empty_dirs = self.remove_empty.get_active()
        s.include_hidden = self.include_hidden.get_active()
        s.save()
        if s.use_ai and not was_on:
            self.win.refresh_ai()  # acabaste de ligar a IA: verifica o Ollama (e arranca-o, se estiver parado)
        else:
            self.win.show_ai_state()

    def _rebuild_excluded(self) -> None:
        for c in self.excl_list.get_children():
            self.excl_list.remove(c)
        if not self.win.settings.excluded:
            self.excl_list.add(pref_row("Nenhuma pasta extra adicionada", "", None))
        for path in self.win.settings.excluded:
            rm = button("", "user-trash-symbolic", "flat", on_click=lambda p=path: self._remove_excluded(p),
                        tooltip="Deixar de ignorar")
            self.excl_list.add(pref_row(display_path(path), path, rm))
        self.excl_list.show_all()

    def _add_excluded(self) -> None:
        path = choose_folder(self.win, "Escolhe uma pasta a ignorar sempre", str(HOME))
        if path and path not in self.win.settings.excluded:
            self.win.settings.excluded.append(path)
            self.win.settings.save()
            self._rebuild_excluded()

    def _remove_excluded(self, path: str) -> None:
        if path in self.win.settings.excluded:
            self.win.settings.excluded.remove(path)
            self.win.settings.save()
            self._rebuild_excluded()
