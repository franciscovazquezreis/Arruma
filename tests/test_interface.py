# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes da interface GTK. Saltam sem o PyGObject (gi) e, os que criam janelas, sem ecrã
(no Linux sem ambiente gráfico: xvfb-run -a python3 -m unittest discover -s tests)."""

import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gtk
except (ImportError, ValueError):
    Gtk = None

HAS_DISPLAY = Gtk is not None and Gtk.init_check()[0]

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
    return types.SimpleNamespace(cancel_task=lambda: None, skip_ai=lambda: None, navigate=lambda key: None,
                                 scan_result=scan_result, toast=mock.Mock(), apply_plan=lambda actions: None)


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
            self.assertEqual(message.call_args.args[1], "Não é possível escolher esta pasta")
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


if __name__ == "__main__":
    unittest.main()
