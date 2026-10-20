# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes da interface GTK. Saltam sem o PyGObject (gi) e, os que criam janelas, sem ecrã
(no Linux sem ambiente gráfico: xvfb-run -a python3 -m unittest discover -s tests)."""

import itertools
import os
import shutil
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gtk
except (ImportError, ValueError):
    Gtk = None

HAS_DISPLAY = Gtk is not None and Gtk.init_check()[0]
_APP_IDS = itertools.count(1)

from arruma.core import taxonomy as tx  # noqa: E402
from arruma.core.planner import MODE_INSIDE, Action, Planner  # noqa: E402
from arruma.core.scanner import scan  # noqa: E402
from arruma.core.settings import Settings  # noqa: E402


def write(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def fake_window(scan_result=None):
    """O mínimo da janela principal de que a página do plano precisa."""
    return types.SimpleNamespace(cancel_task=lambda *kinds: None, skip_ai=lambda: None, navigate=lambda key: None,
                                 scan_result=scan_result, toast=mock.Mock(), apply_plan=lambda actions: None,
                                 find_duplicates=lambda: None)


def pump(cond, timeout: float = 10.0) -> bool:
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.01)
    return bool(cond())


def has_color(cell: "Gtk.CellRendererText") -> bool:
    """Se o texto da célula (depois de cell_set_cell_data) tem alguma cor própria."""
    from gi.repository import Pango
    attrs = cell.get_property("attributes")
    return attrs is not None and any(a.klass.type == Pango.AttrType.FOREGROUND for a in attrs.get_attributes())


@unittest.skipIf(Gtk is None, "sem o PyGObject (gi)")
class ApplySummaryTests(unittest.TestCase):
    """Confirmação de «Aplicar alterações»: o que vai para o Lixo não são só ficheiros temporários."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arruma-teste-")).resolve()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_folders_and_chosen_files_going_to_the_trash(self):
        from arruma.core.system import TRASH_TO
        from arruma.ui.page_plan import apply_summary
        album = self.tmp / "Férias Algarve"
        album.mkdir()
        actions = [
            Action(0, "move", str(self.tmp / "a.pdf"), str(self.tmp / "Documentos" / "a.pdf"), tx.DOCUMENT, 1, "",
                   0.9, "regras"),
            Action(1, "trash", str(self.tmp / "Thumbs.db"), "", tx.JUNK, 1, "", 0.95, "regras"),
            # Arrastados por ti para «Para o Lixo»: um ficheiro e uma pasta inteira com 12 ficheiros.
            Action(2, "trash", str(self.tmp / "b.pdf"), "", tx.DOCUMENT, 1, "", 1.0, "manual"),
            Action(3, "trash", str(album), "", tx.IMAGE, 1, "", 1.0, "manual", count=12),
            Action(4, "rmdir", str(self.tmp / "Nova pasta"), "", tx.OTHER, 0, "", 0.95, "regras"),
        ]
        self.assertEqual(apply_summary(actions), [
            "1 item vai ser movido para as novas pastas.",
            f"1 ficheiro temporário vai {TRASH_TO}.",
            f"1 ficheiro que escolheste vai {TRASH_TO}.",
            f"1 pasta inteira vai {TRASH_TO}, com tudo o que tem dentro (12 ficheiros).",
            "1 pasta vazia vai ser removida.",
            "Nada é apagado definitivamente e podes anular tudo no Histórico.",
        ])
        only_junk = apply_summary([actions[1]])
        self.assertEqual(only_junk[0], f"1 ficheiro temporário vai {TRASH_TO}.")
        self.assertFalse(any("pasta" in line or "escolheste" in line for line in only_junk))


@unittest.skipIf(Gtk is None, "sem o PyGObject (gi)")
class StartScanTests(unittest.TestCase):
    """Escolher diretamente uma pasta protegida recusa-a, como as pastas do sistema."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arruma-teste-")).resolve()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_protected_folders_are_refused(self):
        from arruma.ui import app
        write(self.tmp / "Dropbox" / "fatura.txt")
        write(self.tmp / "Arquivo" / "velho.txt")
        write(self.tmp / "Normal" / "Dropbox" / "partilhado.txt")  # esta pode-se escolher
        win = types.SimpleNamespace(settings=Settings(excluded=[str(self.tmp / "Arquivo")]))
        for folder, why in (("Dropbox", "pasta sincronizada (Dropbox)"), ("Arquivo", "Pastas a ignorar sempre")):
            with mock.patch.object(app, "message") as message:
                app.ArrumaWindow.start_scan(win, [str(self.tmp / "Normal"), str(self.tmp / folder)])
            message.assert_called_once()
            self.assertEqual(message.call_args.args[1], f"Não é possível escolher «{folder}»")  # diz qual das duas
            self.assertIn(why, message.call_args.args[2])


@unittest.skipUnless(HAS_DISPLAY, "sem o PyGObject (gi) ou sem ecrã")
class PlanPageFolderTests(unittest.TestCase):
    """Na árvore do plano, só as pastas novas mudam de nome ou de local: numa que já existe, só os itens
    do plano iam para uma pasta nova e a pasta real ficava como estava."""

    def setUp(self):
        from arruma.ui import page_plan
        self.page_plan = page_plan
        self.tmp = Path(tempfile.mkdtemp(prefix="arruma-teste-")).resolve()
        self.root = self.tmp / "Bagunça"
        write(self.root / "fatura_1.txt", "FATURA n.º 1 Total a pagar 10 EUR NIF 500")
        write(self.root / "Documentos" / "Finanças" / "antiga.txt", "FATURA antiga")
        write(self.root / "Screenshot from 2025-01-02 10-00-00.png")
        result = scan(self.root)
        self.plan = Planner(result, Settings(use_ai=False), MODE_INSIDE).build()
        self.win = fake_window(result)
        self.page = page_plan.PlanPage(self.win)
        self.page.show_plan(self.plan)
        self.existing = str(self.root / "Documentos" / "Finanças")
        self.new = str(self.root / "Imagens" / "Capturas de ecrã")
        self.assertTrue(os.path.isdir(self.existing))
        self.assertFalse(os.path.isdir(self.new))

    def tearDown(self):
        self.page.destroy()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def find_row(self, folder: str):
        tv, store = self.page.trees["after"]
        key = "\x1f".join(self.page._parts(folder))

        def walk(it):
            while it is not None:
                if store.get_value(it, self.page_plan.COL_ID) == -1 and \
                        store.get_value(it, self.page_plan.COL_KEY) == key:
                    return it
                found = walk(store.iter_children(it))
                if found is not None:
                    return found
                it = store.iter_next(it)
            return None
        it = walk(store.get_iter_first())
        self.assertIsNotNone(it, folder)
        return tv, store, it

    def detail_widgets(self, kind):
        found = []

        def walk(w):
            if isinstance(w, kind):
                found.append(w)
            if isinstance(w, Gtk.Container):
                for c in w.get_children():
                    walk(c)
        walk(self.page.detail_scroll)
        return found

    def test_context_menu(self):
        for folder, labels, sensitive in (
                (self.existing, ["Já existe: só as pastas novas mudam de nome ou de local"], False),
                (self.new, ["Mudar nome da pasta… (F2)", "Mover pasta para outro local…"], True)):
            menu = Gtk.Menu()
            self.page._add_folder_items(menu, folder, os.path.basename(folder))
            self.assertEqual([m.get_label() for m in menu.get_children()], labels)
            self.assertTrue(all(m.get_sensitive() == sensitive for m in menu.get_children()))
            menu.destroy()

    def test_f2_and_dragging(self):
        _tv, store, it = self.find_row(self.existing)
        with mock.patch.object(self.page_plan, "prompt_text", return_value="Despesas") as prompt:
            self.page._prompt_rename_iter(store, it)
            prompt.assert_not_called()
            self.assertIn("já existe", self.win.toast.show.call_args.args[0])
            # Também pelo painel de detalhes ou por arrastar: nada muda.
            self.page._apply_folder_rename(self.existing, "Despesas")
            self.page._choose_folder_dest(self.existing)
            self.assertTrue(any(os.path.dirname(a.dst) == self.existing for a in self.plan.actions))
            _tv, store, it = self.find_row(self.new)
            self.page._prompt_rename_iter(store, it)
            prompt.assert_called_once()
        renamed = os.path.join(os.path.dirname(self.new), "Despesas")
        self.assertTrue(any(os.path.dirname(a.dst) == renamed for a in self.plan.actions))

    def test_merge_asks_first(self):
        # Uma pasta nova com o nome e o local de uma que já existe junta-se a ela e depois já não se separa.
        shot = next(a for a in self.plan.actions if os.path.dirname(a.dst) == self.new)
        (self.root / "Imagens" / "Ecrã").mkdir(parents=True)
        (self.root / "Documentos" / "Capturas de ecrã").mkdir()
        with mock.patch.object(self.page_plan, "confirm", return_value=False) as confirm, \
                mock.patch.object(self.page_plan, "choose_folder", return_value=str(self.root / "Documentos")):
            self.page._apply_folder_rename(self.new, "Ecrã")  # F2
            self.page._choose_folder_dest(self.new)  # «Mover pasta para outro local…»
            self.page._merge_dropped_folder(self.new, str(self.root / "Documentos"))  # largada na árvore
            self.assertEqual([c.args[1] for c in confirm.call_args_list],
                             ["Juntar à pasta «Ecrã»?"] + ["Juntar à pasta «Capturas de ecrã»?"] * 2)
            self.assertEqual(os.path.dirname(shot.dst), self.new)  # «Cancelar»: nada muda
            self.page._apply_folder_rename(self.new, "Ecrãs")  # um nome livre não pergunta
            self.assertEqual(confirm.call_count, 3)
        renamed = os.path.join(os.path.dirname(self.new), "Ecrãs")
        self.assertEqual(os.path.dirname(shot.dst), renamed)
        with mock.patch.object(self.page_plan, "confirm", return_value=True):
            self.page._apply_folder_rename(renamed, "Ecrã")
        self.assertEqual(os.path.dirname(shot.dst), str(self.root / "Imagens" / "Ecrã"))

    def test_hint_is_short_and_the_tooltip_says_it_all(self):
        def walk(w):
            found = [w]
            if isinstance(w, Gtk.Container):
                for c in w.get_children():
                    found += walk(c)
            return found
        hint, = [w for w in walk(self.page) if isinstance(w, Gtk.Label) and w.get_text().startswith("💡")]
        self.assertLessEqual(len(hint.get_text()), 62)  # cabe ao lado de «Depois/Antes» com a janela normal
        self.assertIn("As pastas novas também mudam de nome (F2) e de local.", hint.get_tooltip_text())

    def test_tree_without_a_common_folder(self):
        # Pastas em discos diferentes (no Windows, C: e D:) não têm pasta comum: a árvore começa em cada disco
        # e cada pasta da árvore continua a corresponder ao caminho certo.
        other = self.tmp / "Outro disco"
        write(other / "fatura_2.txt", "FATURA n.º 2 Total a pagar 20 EUR NIF 500")
        plan = Planner(scan([self.root, other]), Settings(use_ai=False), MODE_INSIDE).build()
        with mock.patch.object(self.page_plan, "common_root", return_value=None), \
                mock.patch.object(self.page_plan, "HOME", self.tmp / "casa"):
            self.page.show_plan(plan)
            self.assertEqual(self.page.anchor, "")
            for folder in (self.existing, str(other / "Documentos" / "Finanças")):
                _tv, store, it = self.find_row(folder)
                key = store.get_value(it, self.page_plan.COL_KEY).split("\x1f")
                self.assertEqual(os.path.join(self.page.anchor, *key), folder)
            self.assertFalse(self.page._is_new_folder(self.existing))

    def test_detail_panel(self):
        tv, _store, it = self.find_row(self.existing)
        tv.get_selection().select_iter(it)
        self.assertEqual(self.detail_widgets(Gtk.Entry), [])
        texts = [w.get_text() for w in self.detail_widgets(Gtk.Label)]
        self.assertIn(self.page_plan.EXISTING_FOLDER_NOTE, texts)
        self.assertNotIn("Mover pasta para outro local…", [b.get_label() for b in self.detail_widgets(Gtk.Button)])
        tv, _store, it = self.find_row(self.new)
        tv.get_selection().select_iter(it)
        self.assertEqual(len(self.detail_widgets(Gtk.Entry)), 1)
        self.assertIn("Esta pasta ainda não existe e será criada.", [w.get_text() for w in self.detail_widgets(Gtk.Label)])

    def test_trash_node_says_what_goes_there(self):
        from arruma.core.system import TRASH_TO
        trash = self.page_plan.TRASH_NODE
        shot = next(a for a in self.plan.actions if a.kind == tx.IMAGE)
        shot.op, shot.dst, shot.source = "trash", "", "manual"  # como ao arrastar para «Para o Lixo»
        self.page._show_folder_detail([trash], False, 1)
        texts = [w.get_text() for w in self.detail_widgets(Gtk.Label)]
        self.assertIn(f"O que arrastaste para aqui. Vai tudo {TRASH_TO} do sistema, de onde o podes recuperar.", texts)
        self.assertFalse(any("temporários" in t for t in texts))

    def test_kept_button_only_with_kept_folders(self):
        # O «Mantidas (n)» não aparece sem pastas mantidas, mesmo depois de a janela mostrar tudo.
        self.page.show_all()
        self.page.show_plan(self.plan)
        self.assertTrue(self.page.kept_btn.get_visible())
        texts = [w.get_text() for w in self.page.kept_btn.get_child().get_children() if isinstance(w, Gtk.Label)]
        self.assertIn(f"Mantidas ({len(self.plan.respected)})", texts)
        loose = self.tmp / "Soltos"
        write(loose / "fatura_9.txt", "FATURA n.º 9 Total a pagar 10 EUR NIF 500")
        result = scan(loose)
        plan = Planner(result, Settings(use_ai=False), MODE_INSIDE).build()
        self.assertEqual((plan.respected, result.protected), ([], []))
        self.win.scan_result = result
        self.page.show_plan(plan)
        self.assertFalse(self.page.kept_btn.get_visible())

    def test_tags_readable_on_the_selected_row(self):
        # Na linha selecionada (fundo da cor de destaque), «palavras-chave» e «• nova» ficam com a cor do texto.
        tv, store, it = self.find_row(self.new)
        while store.get_value(it, self.page_plan.COL_ID) == -1:
            it = store.iter_children(it)
        self.assertTrue(store.get_value(it, self.page_plan.COL_BADGE))
        folder = store.iter_parent(it)
        self.assertIn("• nova", store.get_value(folder, self.page_plan.COL_MARKUP))
        badge = tv.get_column(1).get_cells()[0]
        name = tv.get_column(0).get_cells()[2]
        for row, column, cell in ((it, 1, badge), (folder, 0, name)):
            tv.get_selection().unselect_all()
            tv.get_column(column).cell_set_cell_data(store, row, False, False)
            self.assertTrue(has_color(cell))
            tv.get_selection().select_iter(row)
            tv.get_column(column).cell_set_cell_data(store, row, False, False)
            self.assertFalse(has_color(cell))


@unittest.skipIf(Gtk is None, "sem o PyGObject (gi)")
class SelectedRowColorTests(unittest.TestCase):
    def test_colors_are_removed(self):
        from arruma.ui.widgets import without_colors
        tag = "<span size='small' foreground='#1c71d8' weight='bold'>palavras-chave</span> ⚠️"
        self.assertEqual(without_colors(tag), "<span size='small' weight='bold'>palavras-chave</span> ⚠️")
        self.assertEqual(without_colors("<b>Faturas</b>\n<span size='small' alpha='60%'>4 itens</span>"),
                         "<b>Faturas</b>\n<span size='small' alpha='60%'>4 itens</span>")


@unittest.skipUnless(HAS_DISPLAY, "sem o PyGObject (gi) ou sem ecrã")
class DuplicatesPageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arruma-teste-")).resolve()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_group_title_is_the_copy_that_stays(self):
        from arruma.core.duplicates import find_duplicates
        from arruma.ui.page_duplicates import COL_MARKUP, DuplicatesPage
        for name in ("foto (1).jpg", "foto.jpg"):
            (self.tmp / name).write_bytes(b"\xff\xd8\xff\xe0 igual" * 50)
        groups = find_duplicates(scan(self.tmp).files)
        page = DuplicatesPage(fake_window())
        self.addCleanup(page.destroy)
        page.show_groups(groups)
        title = page.store.get_value(page.store.get_iter_first(), COL_MARKUP)
        self.assertTrue(title.startswith("<b>foto.jpg</b>"), title)


@unittest.skipUnless(HAS_DISPLAY and Gdk.Display.get_default().__gtype__.name == "GdkX11Display",
                     "precisa de desenhar a janela fora do ecrã como no X11")
class ToastTests(unittest.TestCase):
    def test_no_grey_box_around_the_toast(self):
        # A sombra do aviso cabia mal no Gtk.Revealer, que a cortava: via-se um retângulo cinzento à volta.
        from arruma.ui.widgets import CSS_PATH, Toast
        provider = Gtk.CssProvider()
        provider.load_from_path(str(CSS_PATH))
        screen = Gdk.Screen.get_default()
        Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.addCleanup(Gtk.StyleContext.remove_provider_for_screen, screen, provider)
        win = Gtk.OffscreenWindow()
        self.addCleanup(win.destroy)
        overlay = Gtk.Overlay()
        background = Gtk.Box()
        background.set_size_request(700, 240)
        overlay.add(background)
        toast = Toast()
        toast.set_transition_duration(0)
        overlay.add_overlay(toast)
        win.add(overlay)
        win.show_all()
        toast.show("3 cópias enviadas para o Lixo.", "Anular", lambda: None)
        self.assertTrue(pump(lambda: toast.get_child_revealed() and toast.get_allocated_height() > 1))
        pump(lambda: False, 0.2)
        pixbuf = win.get_pixbuf()
        scale = pixbuf.get_width() / win.get_allocated_width()  # 2 em ecrãs HiDPI
        x, y = toast.translate_coordinates(win, 0, 0)
        w, h = toast.get_allocated_width(), toast.get_allocated_height()

        def pixel(px, py):
            data = pixbuf.get_pixels()
            i = int(py * scale) * pixbuf.get_rowstride() + int(px * scale) * pixbuf.get_n_channels()
            return data[i:i + 3]

        def diff(px, py):
            return max(abs(a - b) for a, b in zip(pixel(px, py), far))
        far = pixel(2, 2)
        self.assertGreater(diff(x + w // 2, y + h // 2), 100)  # o aviso está lá (escuro)
        # Nas bordas do Gtk.Revealer, a sombra já desapareceu: não há nenhum corte à vista.
        for px, py in ((x, y), (x + w // 2, y), (x + w - 1, y), (x, y + h // 2), (x + w - 1, y + h // 2),
                       (x, y + h - 1), (x + w // 2, y + h - 1), (x + w - 1, y + h - 1)):
            self.assertLessEqual(diff(px, py), 2, (px - x, py - y))

    @unittest.skipUnless(HAS_DISPLAY and Gdk.Display.get_default().__gtype__.name == "GdkX11Display",
                         "precisa de mudar a posição do rato (X11)")
    def test_only_the_toast_catches_clicks(self):
        # A margem à volta do aviso (o espaço da sombra) não pode tapar o que está por baixo: um item largado
        # ou um clique logo ao lado do aviso tem de chegar à árvore do plano.
        from arruma.ui.widgets import CSS_PATH, Toast
        provider = Gtk.CssProvider()
        provider.load_from_path(str(CSS_PATH))
        screen = Gdk.Screen.get_default()
        Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.addCleanup(Gtk.StyleContext.remove_provider_for_screen, screen, provider)
        win = Gtk.Window()
        self.addCleanup(win.destroy)
        overlay = Gtk.Overlay()
        under = Gtk.EventBox()
        under.set_size_request(700, 300)
        overlay.add(under)
        toast = Toast()
        toast.set_transition_duration(0)
        overlay.add_overlay(toast)
        overlay.set_overlay_pass_through(toast, True)  # como na janela do Arruma
        win.add(overlay)
        win.show_all()
        toast.show("«fatura.pdf» movido para «Documentos».")
        self.assertTrue(pump(lambda: toast.get_child_revealed() and toast.get_allocated_height() > 1))
        pump(lambda: False, 0.2)
        pill = toast.get_child()
        ctx = pill.get_style_context()
        m = ctx.get_margin(ctx.get_state())
        self.assertGreater(min(m.top, m.left), 10)  # há mesmo uma margem à volta
        x, y = pill.translate_coordinates(win, m.left, m.top)
        w = pill.get_allocated_width() - m.left - m.right
        h = pill.get_allocated_height() - m.top - m.bottom
        ox, oy = win.get_window().get_origin()[1:]
        pointer = Gdk.Display.get_default().get_default_seat().get_pointer()

        def window_at(px, py):
            pointer.warp(screen, ox + px, oy + py)
            pump(lambda: False, 0.05)
            return pointer.get_window_at_position()[0]
        self.assertEqual(window_at(x + w // 2, y - m.top // 2), under.get_window())  # por cima do aviso
        self.assertEqual(window_at(x - m.left // 2, y + h // 2), under.get_window())  # ao lado
        self.assertEqual(window_at(x + w // 2, y + h + m.bottom // 2), under.get_window())  # por baixo
        inside = window_at(x + w // 2, y + h // 2)
        while inside is not None and inside != toast.get_window():
            inside = inside.get_parent()
        self.assertEqual(inside, toast.get_window())  # o próprio aviso (e o botão de o fechar) continua a responder


@unittest.skipUnless(HAS_DISPLAY, "sem o PyGObject (gi) ou sem ecrã")
class WindowStateTests(unittest.TestCase):
    """A janela verdadeira, com a IA desligada nas Definições e um Ollama (fingido) parado."""

    def setUp(self):
        from arruma.core.ai import AIError, LocalAI
        from arruma.core.db import Database
        from arruma.ui import app
        self.tmp = Path(tempfile.mkdtemp(prefix="arruma-teste-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.stopped = AIError("Não foi possível contactar o Ollama. Está instalado e a correr?")
        self.request = mock.Mock(side_effect=self.stopped)
        self.autostart = mock.Mock(return_value=False)
        for p in (mock.patch.object(app, "Database", lambda: Database(self.tmp / "historico.db")),
                  mock.patch.object(app.Settings, "load", classmethod(lambda cls: Settings(use_ai=False))),
                  mock.patch.object(Settings, "save", lambda self: None),
                  mock.patch.object(LocalAI, "_request", self.request),
                  mock.patch.object(LocalAI, "_try_autostart", self.autostart)):
            p.start()
            self.addCleanup(p.stop)
        # Cada aplicação com um nome próprio: sem nome, no Windows (com D-Bus) a segunda colide com a primeira.
        self.application = Gtk.Application(application_id=f"pt.arruma.TesteInterface{next(_APP_IDS)}")
        self.application.register(None)
        self.win = app.ArrumaWindow(self.application)
        self.addCleanup(lambda: (self.win.destroy(), pump(lambda: False, 0.05)))
        self.assertTrue(pump(lambda: self.win.ai_status is not None))

    def pills(self):
        return self.win.home_page.ai_pill.get_text(), self.win.ai_header_pill.get_text()

    def test_clear_selection_only_with_something_selected(self):
        home = self.win.home_page
        self.assertEqual(home.selected_paths, [])
        self.assertFalse(home.clear_btn.get_visible())
        btn, _check = next(iter(home._card_widgets.values()))
        btn.clicked()
        self.assertTrue(home.clear_btn.get_visible())
        home.clear_btn.clicked()
        self.assertFalse(home.clear_btn.get_visible())

    def test_ai_switch_updates_the_top_bar_and_only_then_starts_ollama(self):
        self.assertTrue(self.request.called)  # vê o estado do Ollama...
        self.autostart.assert_not_called()  # ...mas, com a IA desligada, não o arranca
        self.assertEqual(self.pills(), ("desligada", "IA desligada"))
        self.win.settings_page.use_ai.set_active(True)
        self.assertEqual(self.pills(), ("a verificar…", "IA local"))
        self.assertTrue(pump(lambda: self.win.ai_status is not None))
        self.autostart.assert_called_once()
        self.assertEqual(self.pills(), ("não encontrada", "Modo regras"))
        self.win.settings_page.use_ai.set_active(False)
        self.assertEqual(self.pills(), ("desligada", "IA desligada"))
        self.win.refresh_ai()  # «Testar» com a IA desligada também não arranca o Ollama
        self.assertTrue(pump(lambda: self.win.ai_status is not None))
        self.autostart.assert_called_once()

    def test_ollama_running_without_a_model(self):
        self.win.settings.use_ai = True
        self.request.side_effect = lambda path, *a, **k: {"version": "0.12.3"} if path == "/api/version" \
            else {"models": []}
        self.win.refresh_ai()
        self.assertTrue(pump(lambda: self.win.ai_status is not None))
        self.assertEqual(self.pills(), ("sem modelo", "Modo regras"))
        self.assertIn("O Ollama está a correr", self.win.home_page.ai_text.get_text())
        self.request.side_effect = self.stopped
        self.win.refresh_ai()
        self.assertTrue(pump(lambda: self.win.ai_status is not None))
        self.assertEqual(self.pills(), ("não encontrada", "Modo regras"))

    def test_how_to_enable_shows_only_what_is_missing(self):
        from arruma.core.ai import RECOMMENDED_MODEL, AIStatus

        def texts(dlg):
            def walk(w):
                found = [w.get_text()] if isinstance(w, Gtk.Label) else []
                if isinstance(w, Gtk.Container):
                    for c in w.get_children():
                        found += walk(c)
                return found
            return " ".join(walk(dlg.get_content_area()))
        home = self.win.home_page
        with mock.patch.object(self.win, "show_ai_help") as show:
            home.update_ai(AIStatus(ok=False, running=True), True)  # o Ollama a correr, sem modelo
            home.ai_btn.clicked()
            show.assert_called_once_with(model_only=True)
            home.update_ai(AIStatus(ok=False, error="Não foi possível contactar o Ollama."), True)
            home.ai_btn.clicked()
            self.assertEqual(show.call_args_list[-1], mock.call())
        only_model = self.win.build_ai_help(model_only=True)
        self.addCleanup(only_model.destroy)
        self.assertIn(f"ollama pull {RECOMMENDED_MODEL}", texts(only_model))
        self.assertIn("já está a correr", texts(only_model))
        self.assertNotIn("install.sh", texts(only_model))
        self.assertNotIn("Descarrega e instala o Ollama", texts(only_model))
        install = self.win.build_ai_help()
        self.addCleanup(install.destroy)
        self.assertIn(f"ollama pull {RECOMMENDED_MODEL}", texts(install))

    def test_session_waits_while_files_are_changing(self):
        # Sair ou desligar o computador a meio de uma arrumação: o Arruma pede à sessão que espere.
        flags = Gtk.ApplicationInhibitFlags.LOGOUT | Gtk.ApplicationInhibitFlags.SUSPEND
        self.assertIs(self.win.get_application(), self.application)
        with mock.patch.object(self.application, "inhibit", return_value=7) as inhibit, \
                mock.patch.object(self.application, "uninhibit") as uninhibit:
            cancel = self.win._start_busy("apply")
            inhibit.assert_called_once_with(self.win, flags, "O Arruma está a arrumar.")
            uninhibit.assert_not_called()
            self.win._end_busy(cancel)
            uninhibit.assert_called_once_with(7)
        # Sem gestor de sessão (como aqui, no Xvfb), o pedido não faz nada.
        cancel = self.win._start_busy("undo")
        self.win._end_busy(cancel)
        self.assertEqual((self.win._inhibit, self.win._busy, self.win._task), (0, None, None))

    def test_toast_margin_lets_clicks_through(self):
        overlay = self.win.toast.get_parent()
        self.assertTrue(overlay.get_overlay_pass_through(self.win.toast))  # ver ToastTests

    def test_a_new_task_frees_the_view_of_the_one_it_cancels(self):
        # Um plano a meio e, entretanto, «Procurar duplicados» (ou ao contrário): a vista da tarefa cancelada
        # não pode ficar presa no ecrã de progresso, com um «Cancelar» que já não faz nada.
        from arruma.core.planner import PlanCancelled
        from arruma.ui import app
        write(self.tmp / "Bagunça" / "fatura_1.txt", "FATURA n.º 1 Total a pagar 10 EUR NIF 500")
        self.win.scan_result = scan(self.tmp / "Bagunça")

        class StuckPlanner:
            def __init__(self, *args, cancel, **kwargs):
                self.cancel = cancel

            def build(self):
                self.cancel.wait(10)
                raise PlanCancelled()

        def stuck_duplicates(files, progress=None, cancel=None):
            cancel.wait(10)
            raise InterruptedError()
        plan_page, dup_page = self.win.plan_page, self.win.duplicates_page
        with mock.patch.object(app, "Planner", StuckPlanner), mock.patch.object(app, "find_duplicates",
                                                                                stuck_duplicates):
            self.win.build_plan("inside")
            self.assertEqual(plan_page.get_visible_child_name(), "progress")
            self.win.find_duplicates()
            self.assertEqual(plan_page.get_visible_child_name(), "empty")
            self.assertFalse(plan_page.progress.spinner.get_property("active"))
            self.assertEqual(dup_page.get_visible_child_name(), "progress")
            self.win.build_plan("inside")
            self.assertEqual(dup_page.get_visible_child_name(), "intro")
            self.assertFalse(dup_page.progress.spinner.get_property("active"))
            self.assertEqual(plan_page.get_visible_child_name(), "progress")
            pump(lambda: False, 0.3)  # as tarefas canceladas terminam e já não mexem na janela
            self.assertEqual((plan_page.get_visible_child_name(), dup_page.get_visible_child_name()),
                             ("progress", "intro"))
            self.win.cancel_task("plan")
            self.assertTrue(pump(lambda: self.win._task is None))


if __name__ == "__main__":
    unittest.main()
