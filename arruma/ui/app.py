# SPDX-License-Identifier: GPL-3.0-or-later
"""Janela principal e aplicação GTK."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from .. import APP_ID, APP_NAME, AUTHOR, COPYRIGHT, REPO_URL, __version__  # noqa: E402
from ..core import taxonomy as tx  # noqa: E402
from ..core.ai import RECOMMENDED_MODEL, AIError, AIStatus, LocalAI  # noqa: E402
from ..core.db import Database  # noqa: E402
from ..core.duplicates import find_duplicates  # noqa: E402
from ..core.executor import Executor  # noqa: E402
from ..core.fsutil import COMPUTER_TOKEN, check_root_allowed, is_within, plural  # noqa: E402
from ..core.planner import Action, PlanCancelled, Planner  # noqa: E402
from ..core.scanner import ScanCancelled, ScanResult, check_root_protected, scan  # noqa: E402
from ..core.settings import Settings  # noqa: E402
from ..core.system import (IS_LINUX, IS_MAC, TRASH_TO, license_file, ollama_install_steps,  # noqa: E402
                           third_party_notices)
from .page_analysis import AnalysisPage  # noqa: E402
from .page_duplicates import DuplicatesPage  # noqa: E402
from .page_history import UNDONE, HistoryPage, undo_question, undo_report  # noqa: E402
from .page_home import HomePage  # noqa: E402
from .page_plan import PlanPage  # noqa: E402
from .page_settings import SettingsPage  # noqa: E402
from .widgets import (MISSING_ICONS, Throttle, Toast, add_classes, button, choose_folders, confirm, hbox, icon,
                      label, load_css, logo, logo_pixbuf, message, open_path, open_url, run_bg, vbox)

ICON_PNG = Path(__file__).with_name("arruma.png")
RESPONSE_NOTICES = 1
# Tarefas que mudam ficheiros e não se interrompem a meio: o que estão a fazer e o que fica se parares.
BUSY = {
    "apply": ("a arrumar", "O que já foi arrumado fica no Histórico, onde o podes anular."),
    "undo": ("a anular", "O que faltar fica no Histórico, onde podes anular o resto."),
    "trash": (f"a enviar cópias {TRASH_TO}", "O que já foi enviado fica no Histórico, onde o podes anular."),
}

NAV_ITEMS = [
    ("home", "user-home-symbolic", "Início"),
    ("analysis", "dialog-information-symbolic", "Análise"),
    ("plan", "view-list-symbolic", "Plano"),
    ("duplicates", "edit-copy-symbolic", "Duplicados"),
    ("history", "document-open-recent-symbolic", "Histórico"),
    ("settings", "preferences-system-symbolic", "Definições"),
]


class ArrumaWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application):
        super().__init__(application=app, title=APP_NAME)
        self.set_default_size(1180, 760)
        self.set_position(Gtk.WindowPosition.CENTER)

        self.settings = Settings.load()
        self.db = Database()
        self.executor = Executor(self.db)
        self.scan_result: ScanResult | None = None
        self.ai_status: AIStatus | None = None
        self._cancel: threading.Event | None = None
        self._task: str | None = None  # o que o «_cancel» cancela: scan, plan, duplicates ou uma de BUSY
        self._busy: str | None = None  # a mudar ficheiros (chave de BUSY)
        self._closing = False  # pediste para fechar a meio: fecha quando a tarefa parar
        self._scan_target: str | list[str] = []
        self._skip_ai: threading.Event | None = None

        # Barra superior (HeaderBar)
        hb = Gtk.HeaderBar(show_close_button=True, title=APP_NAME,
                           subtitle="Organizador de ficheiros local")
        open_btn = button("Escolher pastas…", "folder-open-symbolic",
                          on_click=self._choose_folder_header,
                          tooltip=f"Analisar uma ou mais pastas ({'Cmd' if IS_MAC else 'Ctrl'}+O)")
        hb.pack_start(open_btn)
        about_btn = button(icon_name="help-about-symbolic", on_click=self.show_about, tooltip="Acerca do Arruma")
        about_btn.set_relief(Gtk.ReliefStyle.NONE)
        about_btn.set_valign(Gtk.Align.CENTER)
        hb.pack_end(about_btn)
        self.ai_header_pill = label("IA local", "pill", "info")
        self.ai_header_pill.set_valign(Gtk.Align.CENTER)
        hb.pack_end(self.ai_header_pill)
        self.set_titlebar(hb)
        self.header = hb

        # Corpo: barra lateral + páginas + toast
        overlay = Gtk.Overlay()
        main_box = hbox(0)
        main_box.pack_start(self._build_sidebar(), False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.home_page = HomePage(self)
        self.analysis_page = AnalysisPage(self)
        self.plan_page = PlanPage(self)
        self.duplicates_page = DuplicatesPage(self)
        self.history_page = HistoryPage(self)
        self.settings_page = SettingsPage(self)

        self.pages = {
            "home": self.home_page,
            "analysis": self.analysis_page,
            "plan": self.plan_page,
            "duplicates": self.duplicates_page,
            "history": self.history_page,
            "settings": self.settings_page,
        }
        for name, widget in self.pages.items():
            self.stack.add_named(widget, name)

        main_box.pack_start(self.stack, True, True, 0)
        overlay.add(main_box)
        self.toast = Toast()
        overlay.add_overlay(self.toast)
        self.add(overlay)

        self._setup_shortcuts()
        self.connect("delete-event", self._on_delete)
        self.show_all()
        self.navigate("home")
        self.refresh_ai()

    # ------------------------------------------------------------------ navegação
    def _build_sidebar(self) -> Gtk.Widget:
        side = vbox(6, "sidebar")
        side.set_size_request(215, -1)

        brand = hbox(10, margin_top=18, margin_bottom=10, margin_start=18, margin_end=14)
        brand.pack_start(logo(32), False, False, 0)
        col = vbox(0)
        col.pack_start(label("Arruma", "brand"), False, False, 0)
        col.pack_start(label("100\u00a0% local · sem internet", "brand-sub"), False, False, 0)
        brand.pack_start(col, False, False, 0)
        side.pack_start(brand, False, False, 0)

        self.nav_list = Gtk.ListBox()
        self.nav_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.nav_rows: dict[str, Gtk.ListBoxRow] = {}
        self.nav_badges: dict[str, Gtk.Label] = {}
        for key, ico, text in NAV_ITEMS:
            row = Gtk.ListBoxRow()
            row.name_key = key
            b = hbox(10)
            b.pack_start(icon(ico, 18), False, False, 0)
            b.pack_start(label(text), True, True, 0)
            badge = label("", "small", "dim")
            b.pack_end(badge, False, False, 0)
            row.add(b)
            self.nav_list.add(row)
            self.nav_rows[key] = row
            self.nav_badges[key] = badge
        self.nav_list.connect("row-selected", self._on_nav_selected)
        side.pack_start(self.nav_list, True, True, 0)

        foot = hbox(8, margin_top=8, margin_bottom=14, margin_start=16, margin_end=16)
        foot.pack_start(icon("security-high-symbolic", 15, "dim"), False, False, 0)
        foot.pack_start(label("Os teus ficheiros nunca saem deste computador.", "small", "dim",
                              wrap=True, max_width=22), True, True, 0)
        side.pack_end(foot, False, False, 0)
        return side

    def _on_nav_selected(self, _lb, row) -> None:
        if row is not None and self.stack.get_visible_child_name() != row.name_key:
            self.stack.set_visible_child_name(row.name_key)

    def navigate(self, key: str) -> None:
        row = self.nav_rows.get(key)
        if row:
            self.nav_list.select_row(row)
            self.stack.set_visible_child_name(key)

    def _setup_shortcuts(self) -> None:
        accel = Gtk.AccelGroup()
        self.add_accel_group(accel)
        # <Primary> é Ctrl no Linux e no Windows e Cmd no macOS.
        key, mod = Gtk.accelerator_parse("<Primary>o")
        accel.connect(key, mod, Gtk.AccelFlags.VISIBLE, lambda *_: (self._choose_folder_header(), True)[1])
        key, mod = Gtk.accelerator_parse("<Primary>q")
        accel.connect(key, mod, Gtk.AccelFlags.VISIBLE, lambda *_: (self.close(), True)[1])

    def _choose_folder_header(self) -> None:
        start = self.scan_result.root if self.scan_result else None
        paths = choose_folders(self, "Escolhe uma ou mais pastas a arrumar", start)
        if paths:
            self.start_scan(paths)

    # ------------------------------------------------------------------ acerca
    def build_about(self) -> Gtk.AboutDialog:
        """Direitos de autor, ausência de garantia e licença (a GPL pede que a interface os mostre)."""
        dialog = Gtk.AboutDialog(transient_for=self, modal=True)
        dialog.set_program_name(APP_NAME)
        dialog.set_version(__version__)
        dialog.set_comments("Organizador de ficheiros local e sem internet.\n"
                            "Software livre, distribuído sem qualquer garantia, nos termos da GNU General "
                            "Public License, versão 3 ou (à tua escolha) qualquer versão posterior.")
        dialog.set_copyright(COPYRIGHT)
        dialog.set_authors([AUTHOR])
        dialog.set_website(REPO_URL)
        dialog.set_website_label("Código-fonte no GitHub")
        text = license_file()
        if text:
            dialog.set_license(text.read_text(encoding="utf-8", errors="replace"))
        else:
            dialog.set_license_type(Gtk.License.GPL_3_0)
        pixbuf = logo_pixbuf(96)
        if pixbuf is not None:
            dialog.set_logo(pixbuf)
        notices = third_party_notices()
        if notices:
            dialog.add_button("Licenças de terceiros", RESPONSE_NOTICES)

        def on_response(d, response):
            if response == RESPONSE_NOTICES and notices:
                open_path(str(notices))
            else:
                d.destroy()
        dialog.connect("response", on_response)
        return dialog

    def show_about(self) -> None:
        self.build_about().show_all()

    # ------------------------------------------------------------------ IA local
    def refresh_ai(self) -> None:
        url, model = self.settings.ollama_url, self.settings.model

        def work():
            try:
                return LocalAI(url, model).check()
            except AIError as e:
                return AIStatus(ok=False, error=str(e))

        def done(status: AIStatus):
            self.ai_status = status
            self.home_page.update_ai(status, self.settings.use_ai)
            self.settings_page.update_ai(status)
            ctx = self.ai_header_pill.get_style_context()
            for c in ("ok", "off", "info"):
                ctx.remove_class(c)
            if self.settings.use_ai and status.ok:
                ctx.add_class("ok")
                self.ai_header_pill.set_text(f"IA local: {status.model}")
                self.ai_header_pill.set_tooltip_text("A IA local está pronta e corre neste computador.")
            elif not self.settings.use_ai:
                ctx.add_class("off")
                self.ai_header_pill.set_text("IA desligada")
                self.ai_header_pill.set_tooltip_text("A usar regras e palavras-chave.")
            else:
                ctx.add_class("off")
                self.ai_header_pill.set_text("Modo regras")
                self.ai_header_pill.set_tooltip_text(status.error)

        run_bg(work, done)

    def show_ai_help(self) -> None:
        dlg = Gtk.Dialog(title="Como ativar a IA local (Ollama)", transient_for=self, modal=True)
        dlg.add_button("Verificar agora", Gtk.ResponseType.APPLY)
        dlg.add_button("Fechar", Gtk.ResponseType.CLOSE)
        dlg.set_default_size(560, -1)
        box = dlg.get_content_area()
        add_classes(box, "card")
        inner = vbox(10, margin_top=12, margin_bottom=12, margin_start=16, margin_end=16)
        inner.pack_start(label("Inteligência artificial 100\u00a0% local", "section-title"), False, False, 0)
        inner.pack_start(label(
            "Para ler documentos e sugerir nomes em português sem usar a internet, o Arruma liga-se ao "
            "Ollama a correr no teu computador. Depois de instalado, funciona sem internet.",
            wrap=True, max_width=68), False, False, 0)
        steps, cmds = ollama_install_steps(RECOMMENDED_MODEL)
        inner.pack_start(label(steps, wrap=True, max_width=68), False, False, 0)
        cmd_box = hbox(8)
        entry = label(cmds, "mono", selectable=True)
        cmd_box.pack_start(entry, True, True, 0)
        copy_btn = button("Copiar comandos", "edit-copy-symbolic",
                          on_click=lambda: Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(cmds, -1))
        cmd_box.pack_end(copy_btn, False, False, 0)
        inner.pack_start(cmd_box, False, False, 4)
        if not IS_LINUX:
            page = button("Abrir a página de transferência do Ollama", "web-browser-symbolic",
                          on_click=lambda: open_url("https://ollama.com/download"))
            page.set_halign(Gtk.Align.START)
            inner.pack_start(page, False, False, 0)

        inner.pack_start(label(
            "Depois de concluído, carrega em «Verificar agora». Mesmo sem o Ollama, o Arruma continua a "
            "funcionar com regras, metadados (datas das fotografias, etiquetas de música) e palavras-chave.",
            "small", "dim", wrap=True, max_width=68), False, False, 0)
        box.add(inner)
        dlg.show_all()
        while dlg.run() == Gtk.ResponseType.APPLY:
            self.refresh_ai()
        dlg.destroy()

    # ------------------------------------------------------------------ tarefas
    def cancel_task(self, *kinds: str) -> None:
        """Cancela a tarefa em curso. Com «kinds», só se for de um destes tipos: o «Cancelar» de uma vista
        nunca para o que está a decorrer noutra (por exemplo, uma arrumação)."""
        if self._cancel and (not kinds or self._task in kinds):
            self._cancel.set()

    def skip_ai(self) -> None:
        if self._skip_ai:
            self._skip_ai.set()

    def _new_task(self, kind: str) -> threading.Event:
        """Cancela o que estava a decorrer e devolve o sinal de cancelar da nova tarefa."""
        self.cancel_task()
        self._cancel, self._task = threading.Event(), kind
        return self._cancel

    def _task_over(self, cancel: threading.Event) -> bool:
        """No fim de uma tarefa. Falso se outra tomou entretanto o lugar dela: a resposta já não interessa e
        não pode mexer na janela nem no sinal de cancelar da nova."""
        if self._cancel is not cancel:
            return False
        self._cancel = self._task = None
        return True

    def _refuse_if_busy(self) -> bool:
        """A mudar ficheiros não se começa outra tarefa: o sinal de cancelar é o mesmo e interrompia a que está
        a meio. Avisa, sem bloquear a janela."""
        if not self._busy:
            return False
        self.toast.show(f"O Arruma ainda está {BUSY[self._busy][0]}. Espera que termine.")
        return True

    def _start_busy(self, kind: str) -> threading.Event:
        """Começa a mudar ficheiros. Um plano ou uma procura de duplicados a meio é cancelado (ficaria
        desatualizado) e a vista dele deixa de mostrar o progresso."""
        was = self._task
        cancel = self._new_task(kind)
        self._busy = kind
        if was == "plan":
            self.plan_page.progress.stop()
            self.plan_page.reset()
        elif was == "duplicates":
            self.duplicates_page.progress.stop()
            self.duplicates_page.ready()
        return cancel

    def _end_busy(self, cancel: threading.Event) -> bool:
        """Fim de uma tarefa que muda ficheiros. Verdadeiro se a janela vai fechar (pediste para fechar a meio)."""
        self._busy = None
        self._task_over(cancel)
        if self._closing:
            self.close()
            return True
        return False

    def _on_delete(self, *_args) -> bool:
        """Fechar a meio de uma arrumação (ou de uma anulação) pergunta primeiro. Para fechar, o Arruma para
        depois do item em curso e só então fecha: nenhum ficheiro fica a meio de ser movido."""
        if not self._busy:
            return False
        if not self._closing:
            what, after = BUSY[self._busy]
            if confirm(self, f"O Arruma ainda está {what}",
                       f"Se fechares agora, para depois do item em curso e fecha. {after}",
                       "Parar e fechar", destructive=True, cancel_label="Não fechar"):
                if not self._busy:  # terminou enquanto perguntava
                    return False
                self._closing = True
                self.cancel_task()
                self.toast.show("A parar depois do item em curso…")
        return True

    def start_scan(self, paths: str | list[str], refresh: bool = False) -> None:
        """«refresh»: depois de arrumar ou de anular, volta a analisar as mesmas pastas em segundo plano, sem
        mudar de vista nem mexer no plano (o ecrã «Está arrumado!» continua à vista)."""
        raw_list = [str(paths)] if isinstance(paths, (str, Path)) else [str(p) for p in paths if p]
        if not raw_list:
            return
        for p in raw_list if not refresh else []:  # ao repetir, as pastas já foram verificadas
            err = check_root_allowed(p) or check_root_protected(p, self.settings.excluded)
            if err:
                message(self, "Não é possível escolher esta pasta", err, Gtk.MessageType.WARNING)
                return
        if self._refuse_if_busy():
            return
        if COMPUTER_TOKEN in raw_list or "/" in raw_list:
            title = "Todo o computador"
            scan_arg: str | list[str] = COMPUTER_TOKEN
        elif len(raw_list) == 1:
            title = os.path.basename(raw_list[0]) or raw_list[0]
            scan_arg = raw_list[0]
        else:
            names = [os.path.basename(p) or p for p in raw_list]
            title = f"{len(raw_list)} pastas ({', '.join(names[:3])}{'…' if len(names) > 3 else ''})"
            scan_arg = raw_list

        cancel = self._new_task("scan")
        self._scan_target = scan_arg
        self.header.set_subtitle(title)
        self.analysis_page.show_progress(title)
        if not refresh:
            self.plan_page.reset()
        self.duplicates_page.reset()
        self.nav_badges["plan"].set_text("")
        self.nav_badges["duplicates"].set_text("")
        if not refresh:
            self.navigate("analysis")

        prog = Throttle(self.analysis_page.update_progress)
        st = self.settings.copy()

        def work():
            return scan(scan_arg, include_hidden=st.include_hidden, excluded=st.excluded,
                        progress=prog, cancel=cancel)

        def done(res: ScanResult):
            if not self._task_over(cancel):
                return
            self.scan_result = res
            self.header.set_subtitle(res.title)
            self.nav_badges["analysis"].set_text(str(len(res.files)))
            self.analysis_page.show_result(res)
            self.duplicates_page.ready()
            self.home_page.refresh_folders()

        def fail(e: Exception):
            if not self._task_over(cancel):
                return
            self.analysis_page.progress.stop()
            if refresh:
                # A análise anterior já não corresponde ao que está no disco: não volta a aparecer.
                self.scan_result = None
                self.nav_badges["analysis"].set_text("")
                self.analysis_page.set_visible_child_name("empty")
                if not isinstance(e, ScanCancelled):
                    message(self, "Erro ao analisar a pasta", str(e), Gtk.MessageType.ERROR)
            elif isinstance(e, ScanCancelled):
                self.navigate("home")
            else:
                message(self, "Erro ao analisar a pasta", str(e), Gtk.MessageType.ERROR)
                self.navigate("home")

        run_bg(work, done, fail)

    def _refresh_analysis(self) -> None:
        """Depois de mudar ficheiros, volta a analisar as mesmas pastas em segundo plano (como depois de anular):
        a Análise e os Duplicados mostram onde as coisas estão agora e um plano novo parte do que está no disco."""
        sr = self.scan_result
        if sr:
            self.start_scan(COMPUTER_TOKEN if sr.whole_computer else list(sr.roots), refresh=True)

    def build_plan(self, mode: str) -> None:
        if not self.scan_result or self._refuse_if_busy():
            return
        cancel = self._new_task("plan")
        skip = threading.Event()
        self._skip_ai = skip
        self.plan_page.show_progress()
        self.navigate("plan")

        prog = Throttle(self.plan_page.update_progress)
        scan_res = self.scan_result
        st = self.settings.copy()

        def work():
            return Planner(scan_res, st, mode, db=self.db, progress=prog, cancel=cancel, skip_ai=skip).build()

        def done(plan):
            if not self._task_over(cancel):
                return
            self.nav_badges["plan"].set_text(str(len(plan.actions)) if plan.actions else "")
            self.plan_page.show_plan(plan)

        def fail(e: Exception):
            if not self._task_over(cancel):
                return
            self.plan_page.progress.stop()
            if isinstance(e, PlanCancelled):
                self.navigate("analysis")
            else:
                message(self, "Erro ao criar o plano", str(e), Gtk.MessageType.ERROR)
                self.navigate("analysis")

        run_bg(work, done, fail)

    def apply_plan(self, actions: list[Action]) -> None:
        plan = self.plan_page.plan
        if not plan or self._refuse_if_busy():
            return
        cancel = self._start_busy("apply")
        self.plan_page.show_applying(len(actions))
        prog = Throttle(self.plan_page.update_applying)
        title = f"Arrumação de «{plan.title}»"
        protect = set(plan.roots) | set(plan.bases.values()) | {p for p, _ in plan.respected}
        rm_empty = self.settings.remove_empty_dirs

        def work():
            return self.executor.apply(actions, plan.root, title, cleanup_dirs=plan.cleanup_dirs,
                                       protect=protect, remove_empty=rm_empty, progress=prog, cancel=cancel,
                                       roots=plan.roots)

        def done(res):
            if self._end_busy(cancel):
                return
            self.nav_badges["plan"].set_text("")
            self.plan_page.show_done(res, plan)
            self.history_page.refresh()
            self.home_page.refresh_folders()
            self.toast.show(f"{plural(res.ok, 'alteração aplicada', 'alterações aplicadas')}.",
                            "Anular", lambda: self.undo_session(res.session_id))
            self._refresh_analysis()

        def fail(e: Exception):
            # Não se sabe até onde chegou: o plano deixa de valer e a análise volta a fazer-se.
            if self._end_busy(cancel):
                return
            self.plan_page.progress.stop()
            self.plan_page.reset()
            self.nav_badges["plan"].set_text("")
            self.history_page.refresh()
            self._refresh_analysis()
            self.navigate("analysis")
            message(self, "Erro ao arrumar", f"{e}\n\nO que chegou a ser feito aparece no Histórico, onde o podes "
                    "anular.", Gtk.MessageType.ERROR)

        run_bg(work, done, fail)

    def find_duplicates(self) -> None:
        if not self.scan_result or self._refuse_if_busy():
            return
        cancel = self._new_task("duplicates")
        self.duplicates_page.show_progress()
        self.navigate("duplicates")
        prog = Throttle(self.duplicates_page.update_progress)
        files = list(self.scan_result.files)

        def work():
            return find_duplicates(files, progress=prog, cancel=cancel)

        def done(groups):
            if not self._task_over(cancel):
                return
            self.nav_badges["duplicates"].set_text(str(len(groups)) if groups else "")
            self.duplicates_page.show_groups(groups)

        def fail(e: Exception):
            if not self._task_over(cancel):
                return
            self.duplicates_page.progress.stop()
            if isinstance(e, InterruptedError):
                self.duplicates_page.ready()
            else:
                message(self, "Erro ao procurar duplicados", str(e), Gtk.MessageType.ERROR)

        run_bg(work, done, fail)

    def trash_duplicates(self, paths: list[str]) -> None:
        if not self.scan_result or self._refuse_if_busy():
            return
        root = self.scan_result.root
        actions = [Action(i, "trash", p, "", tx.OTHER, 0, "Cópia duplicada", 1.0, "manual")
                   for i, p in enumerate(paths)]
        title = f"Remoção de duplicados em «{self.scan_result.title}»"
        cancel = self._start_busy("trash")

        def work():
            return self.executor.apply(actions, root, title, remove_empty=False, cancel=cancel)

        def done(res):
            if self._end_busy(cancel):
                return
            removed = set(paths) - {p for p, _ in res.errors}
            self.scan_result.files = [f for f in self.scan_result.files if f.path not in removed]
            self.history_page.refresh()
            self.find_duplicates()
            self.toast.show(f"{plural(res.ok, 'cópia enviada', 'cópias enviadas')} {TRASH_TO}.",
                            "Anular", lambda: self.undo_session(res.session_id))

        def fail(e: Exception):
            if self._end_busy(cancel):
                return
            self.history_page.refresh()
            message(self, f"Erro ao enviar as cópias {TRASH_TO}", str(e), Gtk.MessageType.ERROR)

        run_bg(work, done, fail)

    def undo_session(self, session_id: int) -> None:
        if self._refuse_if_busy():
            return
        s = self.db.session(session_id)
        if s is None:
            return
        if s["undone"] == UNDONE:
            self.toast.show(f"{s['title']}: já foi anulada.")
            return
        title, text, ok_label = undo_question(s)
        if not confirm(self, title, text, ok_label):
            return
        rescan = self._task == "scan"  # uma análise a meio é interrompida e volta a fazer-se no fim
        cancel = self._start_busy("undo")
        self.history_page.show_progress(s["title"])
        self.navigate("history")
        prog = Throttle(self.history_page.update_progress)

        def work():
            res = self.executor.undo(session_id, progress=prog, cancel=cancel)
            return res, [p for o in self.db.ops(session_id) for p in (o["src"], o["dst"]) if p]

        def done(out):
            res, paths = out
            self.history_page.stop_progress()
            if self._end_busy(cancel):
                return
            self.home_page.refresh_folders()
            self._refresh_after_undo(paths, rescan)
            if res.errors:
                message(self, "Anulação incompleta", undo_report(res), Gtk.MessageType.WARNING)
            elif res.cancelled:
                self.toast.show("Anulação parada a meio. Para continuar, carrega em «Anular o resto».")
            else:
                self.toast.show("Alterações anuladas. Tudo voltou ao local original.")

        def fail(e: Exception):
            self.history_page.stop_progress()
            if self._end_busy(cancel):
                return
            self._refresh_after_undo(None, rescan)
            message(self, "Erro ao anular", f"{e}\n\nO que ficou por anular continua no Histórico.",
                    Gtk.MessageType.ERROR)

        run_bg(work, done, fail)

    def _refresh_after_undo(self, paths: list[str] | None, rescan: bool) -> None:
        """Volta a analisar as pastas da análise atual só se a anulação mexeu nelas (sem «paths», por precaução,
        sempre); uma anulação de outras pastas deixa a análise e o plano como estão. Uma análise interrompida
        para anular faz-se de novo."""
        sr = self.scan_result
        if rescan:
            self.plan_page.reset()
            self.start_scan(self._scan_target, refresh=True)
        elif sr and (paths is None or sr.whole_computer or any(is_within(p, r) for p in paths for r in sr.roots)):
            self.plan_page.reset()  # o plano (ou o «Está arrumado!») partia do que foi desfeito
            self._refresh_analysis()


def icone_do_tema_abre() -> bool:
    """Verdadeiro se o ícone do Arruma no tema do sistema abre mesmo. O has_icon() fia-se na cache
    do tema, que pode indicar um ficheiro já apagado; com esse, a janela ficaria sem ícone."""
    info = Gtk.IconTheme.get_default().lookup_icon(APP_ID, 64, 0)
    if info is None:
        return False
    try:
        return info.load_icon() is not None
    except GLib.Error:
        return False


class ArrumaApp(Gtk.Application):
    def __init__(self, self_test: str | None = None):
        flags = Gio.ApplicationFlags.HANDLES_COMMAND_LINE
        if not IS_LINUX or self_test is not None:
            # Fora do Linux não há barramento D-Bus de sessão: cada arranque abre a sua janela.
            flags |= Gio.ApplicationFlags.NON_UNIQUE
        super().__init__(application_id=APP_ID, flags=flags)
        self.win: ArrumaWindow | None = None
        self._initial_folders: list[str] = []
        self.self_test = self_test
        self.self_test_status = 1

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        GLib.set_application_name(APP_NAME)
        load_css()
        if ICON_PNG.exists():
            try:
                Gtk.Window.set_default_icon_from_file(str(ICON_PNG))
            except GLib.Error:
                pass
        if IS_LINUX and icone_do_tema_abre():
            Gtk.Window.set_default_icon_name(APP_ID)

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        args = command_line.get_arguments()[1:]
        folders = [str(Path(a).resolve()) for a in args if os.path.isdir(a)]
        if folders:
            self._initial_folders = folders
        self.activate()
        return 0

    def do_activate(self) -> None:
        if not self.win:
            self.win = ArrumaWindow(self)
        self.win.present()
        if self.self_test is not None:
            GLib.timeout_add(800, self._run_self_test)
            return
        if self._initial_folders:
            folders, self._initial_folders = self._initial_folders, []
            self.win.start_scan(folders)

    # ------------------------------------------------------------------ autoteste
    def _run_self_test(self) -> bool:
        """Verifica que a aplicação empacotada funciona: análise, plano e páginas da interface."""
        import tempfile
        import traceback

        from ..core.planner import MODE_INSIDE
        lines = [f"Arruma {__version__}", f"Python {sys.version.split()[0]} em {sys.platform}",
                 f"GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}"]
        ok = True
        try:
            tmp = Path(tempfile.mkdtemp(prefix="arruma-autoteste-"))
            root = tmp / "Bagunça"
            root.mkdir()
            (root / "fatura_123.txt").write_text("FATURA n.º 1 Total a pagar 10,00 EUR NIF 500", encoding="utf-8")
            (root / "IMG_20240812_101010.jpg").write_bytes(b"\xff\xd8\xff\xe0 teste")
            (root / "Nova pasta").mkdir()
            (root / "Nova pasta" / "notas.txt").write_text("Apontamentos da aula de Matemática", encoding="utf-8")
            result = scan(str(root))
            settings = Settings(use_ai=False)
            plan = Planner(result, settings, MODE_INSIDE, db=Database(tmp / "autoteste.db")).build()
            lines.append(f"Análise: {len(result.files)} ficheiros; plano: {len(plan.actions)} alterações")
            if len(plan.actions) < 3:
                ok = False
                lines.append("ERRO: plano incompleto")
            self.win.scan_result = result
            self.win.analysis_page.show_result(result)
            self.win.plan_page.show_plan(plan)
            self.win.navigate("plan")
            self.win.duplicates_page.ready()
            self.win.history_page.refresh()
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            from ..core.extract import extract_text, has_ocr, ocr_languages
            from ..core.system import find_tool
            for tool in ("pdftotext", "pdftoppm", "tesseract", "ollama"):
                lines.append(f"{tool}: {find_tool(tool) or 'não encontrado'}")
            lines.append(f"OCR: {'sim (' + (', '.join(ocr_languages()) or '?') + ')' if has_ocr() else 'não'}")
            # Ler PDF é essencial para classificar documentos: pdftotext ou, em alternativa, pypdf.
            pdf = tmp / "teste.pdf"
            pdf.write_bytes(_minimal_pdf("Fatura de teste do Arruma"))
            text = extract_text(str(pdf), "pdf")
            pdf_ok = "Fatura de teste do Arruma" in text
            lines.append(f"Leitura de PDF: {'OK' if pdf_ok else 'FALHOU'} ({text[:40]!r})")
            if not pdf_ok:
                ok = False
            lines.append("Ícones em falta: " + (", ".join(sorted(MISSING_ICONS)) or "nenhum"))
            # O logótipo da barra lateral e da janela «Acerca» vem dos ficheiros do próprio Arruma.
            logo_ok = logo_pixbuf(64) is not None
            lines.append(f"Logótipo: {'OK' if logo_ok else 'EM FALTA'}")
            ok = ok and logo_ok
            if IS_LINUX and Path(__file__).resolve().is_relative_to("/usr"):
                # Instalado pelo .deb: o menu e a barra de tarefas procuram o ícone no tema do sistema.
                no_tema = icone_do_tema_abre()
                lines.append(f"Ícone no tema do sistema: {'OK' if no_tema else 'EM FALTA'}")
                ok = ok and no_tema
            about = self.win.build_about()
            about.destroy()
            notices = third_party_notices()
            if getattr(sys, "frozen", False):
                import json
                index = notices / "componentes.json" if notices else None
                count = len(json.loads(index.read_text(encoding="utf-8"))["componentes"]) if index and \
                    index.is_file() and (notices / "LEIA-ME.txt").is_file() else 0
                lines.append(f"Licenças de terceiros: {count} componentes" if count else
                             "Licenças de terceiros: EM FALTA")
                if not count or not license_file():
                    ok = False
            lines.append(f"Licença: {license_file() or 'EM FALTA'}")
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:  # noqa: BLE001
            ok = False
            lines.append(traceback.format_exc())
        lines.append("RESULTADO: " + ("OK" if ok else "FALHOU"))
        report = "\n".join(lines) + "\n"
        if self.self_test:
            Path(self.self_test).write_text(report, encoding="utf-8")
        else:
            print(report, end="")
        self.self_test_status = 0 if ok else 1
        self.quit()
        return False


def _minimal_pdf(text: str) -> bytes:
    """PDF de uma página com uma linha de texto, para o autoteste."""
    stream = f"BT /F1 12 Tf 50 750 Td ({text}) Tj ET".encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> "
            b"/Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    if "--version" in argv[1:]:
        print(f"{APP_NAME} {__version__}")
        return 0
    self_test = None
    for arg in argv[1:]:
        if arg == "--self-test" or arg.startswith("--self-test="):
            self_test = arg.partition("=")[2]
    argv = [a for a in argv if not a.startswith("--self-test")]
    GLib.set_prgname("arruma")  # nome da janela, para o menu e a barra de tarefas a associarem ao Arruma
    app = ArrumaApp(self_test=self_test)
    status = app.run(argv)
    return app.self_test_status if self_test is not None else status
