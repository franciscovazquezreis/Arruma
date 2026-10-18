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

from .. import APP_ID, APP_NAME, __version__  # noqa: E402
from ..core import taxonomy as tx  # noqa: E402
from ..core.ai import RECOMMENDED_MODEL, AIError, AIStatus, LocalAI  # noqa: E402
from ..core.db import Database  # noqa: E402
from ..core.duplicates import find_duplicates  # noqa: E402
from ..core.executor import Executor  # noqa: E402
from ..core.fsutil import COMPUTER_TOKEN, check_root_allowed, plural  # noqa: E402
from ..core.planner import Action, PlanCancelled, Planner  # noqa: E402
from ..core.scanner import ScanCancelled, ScanResult, scan  # noqa: E402
from ..core.settings import Settings  # noqa: E402
from ..core.system import IS_LINUX, IS_MAC, TRASH_TO, ollama_install_steps  # noqa: E402
from .page_analysis import AnalysisPage  # noqa: E402
from .page_duplicates import DuplicatesPage  # noqa: E402
from .page_history import HistoryPage  # noqa: E402
from .page_home import HomePage  # noqa: E402
from .page_plan import PlanPage  # noqa: E402
from .page_settings import SettingsPage  # noqa: E402
from .widgets import (MISSING_ICONS, Throttle, Toast, add_classes, button, choose_folders, hbox, icon, label,
                      load_css, message, open_url, run_bg, vbox)

ICON_PNG = Path(__file__).with_name("arruma.png")

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
        self._skip_ai: threading.Event | None = None

        # Barra superior (HeaderBar)
        hb = Gtk.HeaderBar(show_close_button=True, title=APP_NAME,
                           subtitle="Organizador de ficheiros local")
        open_btn = button("Escolher pastas…", "folder-open-symbolic",
                          on_click=self._choose_folder_header,
                          tooltip=f"Analisar uma ou mais pastas ({'Cmd' if IS_MAC else 'Ctrl'}+O)")
        hb.pack_start(open_btn)
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
        self.show_all()
        self.navigate("home")
        self.refresh_ai()

    # ------------------------------------------------------------------ navegação
    def _build_sidebar(self) -> Gtk.Widget:
        side = vbox(6, "sidebar")
        side.set_size_request(215, -1)

        brand = hbox(10, margin_top=18, margin_bottom=10, margin_start=18, margin_end=14)
        brand.pack_start(icon("folder", 32), False, False, 0)
        col = vbox(0)
        col.pack_start(label("Arruma", "brand"), False, False, 0)
        col.pack_start(label("100% local · sem internet", "brand-sub"), False, False, 0)
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
        inner.pack_start(label("Inteligência artificial 100% local", "section-title"), False, False, 0)
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
            "funcionar usando regras, metadados (datas das fotografias, etiquetas de música) e palavras-chave.",
            "small", "dim", wrap=True, max_width=68), False, False, 0)
        box.add(inner)
        dlg.show_all()
        while dlg.run() == Gtk.ResponseType.APPLY:
            self.refresh_ai()
        dlg.destroy()

    # ------------------------------------------------------------------ tarefas
    def cancel_task(self) -> None:
        if self._cancel:
            self._cancel.set()

    def skip_ai(self) -> None:
        if self._skip_ai:
            self._skip_ai.set()

    def start_scan(self, paths: str | list[str]) -> None:
        raw_list = [str(paths)] if isinstance(paths, (str, Path)) else [str(p) for p in paths if p]
        if not raw_list:
            return
        for p in raw_list:
            err = check_root_allowed(p)
            if err:
                message(self, "Não é possível escolher esta pasta", err, Gtk.MessageType.WARNING)
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

        self.cancel_task()
        cancel = threading.Event()
        self._cancel = cancel
        self.header.set_subtitle(title)
        self.analysis_page.show_progress(title)
        self.plan_page.reset()
        self.duplicates_page.reset()
        self.nav_badges["plan"].set_text("")
        self.nav_badges["duplicates"].set_text("")
        self.navigate("analysis")

        prog = Throttle(self.analysis_page.update_progress)
        st = self.settings.copy()

        def work():
            return scan(scan_arg, include_hidden=st.include_hidden, excluded=st.excluded,
                        progress=prog, cancel=cancel)

        def done(res: ScanResult):
            self._cancel = None
            self.scan_result = res
            self.header.set_subtitle(res.title)
            self.nav_badges["analysis"].set_text(str(len(res.files)))
            self.analysis_page.show_result(res)
            self.duplicates_page.ready()
            self.home_page.refresh_folders()

        def fail(e: Exception):
            self._cancel = None
            self.analysis_page.progress.stop()
            if isinstance(e, ScanCancelled):
                self.navigate("home")
            else:
                message(self, "Erro ao analisar a pasta", str(e), Gtk.MessageType.ERROR)
                self.navigate("home")

        run_bg(work, done, fail)

    def build_plan(self, mode: str) -> None:
        if not self.scan_result:
            return
        self.cancel_task()
        cancel, skip = threading.Event(), threading.Event()
        self._cancel, self._skip_ai = cancel, skip
        self.plan_page.show_progress()
        self.navigate("plan")

        prog = Throttle(self.plan_page.update_progress)
        scan_res = self.scan_result
        st = self.settings.copy()

        def work():
            return Planner(scan_res, st, mode, db=self.db, progress=prog, cancel=cancel, skip_ai=skip).build()

        def done(plan):
            self._cancel = None
            self.nav_badges["plan"].set_text(str(len(plan.actions)) if plan.actions else "")
            self.plan_page.show_plan(plan)

        def fail(e: Exception):
            self._cancel = None
            self.plan_page.progress.stop()
            if isinstance(e, PlanCancelled):
                self.navigate("analysis")
            else:
                message(self, "Erro ao criar o plano", str(e), Gtk.MessageType.ERROR)
                self.navigate("analysis")

        run_bg(work, done, fail)

    def apply_plan(self, actions: list[Action]) -> None:
        plan = self.plan_page.plan
        if not plan:
            return
        cancel = threading.Event()
        self._cancel = cancel
        self.plan_page.show_applying(len(actions))
        prog = Throttle(self.plan_page.update_applying)
        title = f"Arrumação de «{plan.title}»"
        protect = set(plan.roots) | set(plan.bases.values()) | {p for p, _ in plan.respected}
        rm_empty = self.settings.remove_empty_dirs

        def work():
            return self.executor.apply(actions, plan.root, title, cleanup_dirs=plan.cleanup_dirs,
                                       protect=protect, remove_empty=rm_empty, progress=prog, cancel=cancel)

        def done(res):
            self._cancel = None
            self.nav_badges["plan"].set_text("")
            self.plan_page.show_done(res, plan)
            self.history_page.refresh()
            self.home_page.refresh_folders()
            self.toast.show(f"{plural(res.ok, 'alteração aplicada', 'alterações aplicadas')}.",
                            "Anular", lambda: self.undo_session(res.session_id))

        run_bg(work, done, lambda e: message(self, "Erro ao arrumar", str(e), Gtk.MessageType.ERROR))

    def find_duplicates(self) -> None:
        if not self.scan_result:
            return
        self.cancel_task()
        cancel = threading.Event()
        self._cancel = cancel
        self.duplicates_page.show_progress()
        self.navigate("duplicates")
        prog = Throttle(self.duplicates_page.update_progress)
        files = list(self.scan_result.files)

        def work():
            return find_duplicates(files, progress=prog, cancel=cancel)

        def done(groups):
            self._cancel = None
            self.nav_badges["duplicates"].set_text(str(len(groups)) if groups else "")
            self.duplicates_page.show_groups(groups)

        def fail(e: Exception):
            self._cancel = None
            self.duplicates_page.progress.stop()
            if isinstance(e, InterruptedError):
                self.duplicates_page.ready()
            else:
                message(self, "Erro ao procurar duplicados", str(e), Gtk.MessageType.ERROR)

        run_bg(work, done, fail)

    def trash_duplicates(self, paths: list[str]) -> None:
        if not self.scan_result:
            return
        root = self.scan_result.root
        actions = [Action(i, "trash", p, "", tx.OTHER, 0, "Cópia duplicada", 1.0, "manual")
                   for i, p in enumerate(paths)]
        title = f"Remoção de duplicados em «{self.scan_result.title}»"

        def work():
            return self.executor.apply(actions, root, title, remove_empty=False)

        def done(res):
            removed = set(paths) - {p for p, _ in res.errors}
            self.scan_result.files = [f for f in self.scan_result.files if f.path not in removed]
            self.history_page.refresh()
            self.find_duplicates()
            self.toast.show(f"{plural(res.ok, 'cópia enviada', 'cópias enviadas')} {TRASH_TO}.",
                            "Anular", lambda: self.undo_session(res.session_id))

        run_bg(work, done)

    def undo_session(self, session_id: int) -> None:
        def work():
            return self.executor.undo(session_id)

        def done(res):
            self.history_page.refresh()
            self.home_page.refresh_folders()
            if res.errors:
                message(self, "Anulação concluída com avisos",
                        f"{plural(res.ok, 'operação revertida', 'operações revertidas')}. "
                        f"{plural(len(res.errors), 'item já tinha sido movido', 'itens já tinham sido movidos')} "
                        "manualmente.", Gtk.MessageType.WARNING)
            else:
                self.toast.show("Alterações anuladas. Tudo voltou ao local original.")
            if self.scan_result:
                target = COMPUTER_TOKEN if self.scan_result.whole_computer else list(self.scan_result.roots)
                self.start_scan(target)

        run_bg(work, done)


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
        if IS_LINUX and Gtk.IconTheme.get_default().has_icon(APP_ID):
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
            from ..core.extract import extract_text, has_ocr
            from ..core.system import find_tool
            for tool in ("pdftotext", "pdftoppm", "tesseract", "ollama"):
                lines.append(f"{tool}: {find_tool(tool) or 'não encontrado'}")
            lines.append(f"OCR: {'sim' if has_ocr() else 'não'}")
            # Ler PDF é essencial para classificar documentos: pdftotext ou, em alternativa, pypdf.
            pdf = tmp / "teste.pdf"
            pdf.write_bytes(_minimal_pdf("Fatura de teste do Arruma"))
            text = extract_text(str(pdf), "pdf")
            pdf_ok = "Fatura de teste do Arruma" in text
            lines.append(f"Leitura de PDF: {'OK' if pdf_ok else 'FALHOU'} ({text[:40]!r})")
            if not pdf_ok:
                ok = False
            lines.append("Ícones em falta: " + (", ".join(sorted(MISSING_ICONS)) or "nenhum"))
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
