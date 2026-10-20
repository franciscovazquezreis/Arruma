# SPDX-License-Identifier: GPL-3.0-or-later
"""Aplicar e anular: o histórico fica certo mesmo a meio, nada interrompe uma arrumação, a análise acompanha
o que mudou e anular pergunta, mostra o progresso e diz porque falhou. Os testes da janela precisam do
PyGObject e de ecrã (no Linux sem ambiente gráfico: xvfb-run -a python3 -m unittest discover -s tests)."""

import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
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

from arruma.core import executor as executor_mod  # noqa: E402
from arruma.core import taxonomy as tx  # noqa: E402
from arruma.core.db import Database  # noqa: E402
from arruma.core.executor import Executor, Result  # noqa: E402
from arruma.core.planner import Action  # noqa: E402
from arruma.core.settings import Settings  # noqa: E402

# O histórico como as versões anteriores o criavam (sem «finished»).
OLD_SCHEMA = """
CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL, root TEXT NOT NULL,
    title TEXT NOT NULL, n_ok INTEGER DEFAULT 0, n_err INTEGER DEFAULT 0, undone INTEGER DEFAULT 0);
CREATE TABLE ops (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL REFERENCES sessions(id),
    seq INTEGER NOT NULL, op TEXT NOT NULL, src TEXT NOT NULL, dst TEXT, status TEXT NOT NULL, error TEXT,
    ts REAL NOT NULL);
CREATE INDEX ops_session ON ops(session_id);
CREATE TABLE ai_cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, created REAL NOT NULL);
"""


def write(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def move(i: int, src: Path, dst: Path) -> Action:
    return Action(i, "move", str(src), str(dst), tx.DOCUMENT, 1, "", 1.0, "regras")


class Interrupted(BaseException):
    """O Arruma fechado a meio: a arrumação para sem chegar ao fim."""


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arruma-teste-")).resolve()
        self.root = self.tmp / "Bagunça"
        self.files = [write(self.root / f"fatura_{i}.txt", f"fatura {i}") for i in range(4)]
        self.db = Database(self.tmp / "historico.db")
        self.ex = Executor(self.db)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def actions(self, folder="Documentos/Finanças"):
        return [move(i, f, self.root / folder / f.name) for i, f in enumerate(self.files)]

    def test_interrupted_apply_is_in_history_and_can_be_undone(self):
        seen = []

        def progress(n, total, path):
            if path:
                seen.append(dict(self.db.sessions()[0]) if self.db.sessions() else None)
            if n == 2:
                raise Interrupted()
        with self.assertRaises(Interrupted):
            self.ex.apply(self.actions(), str(self.root), "Arrumação de «Bagunça»", progress=progress)
        # As contagens ficam gravadas a cada ficheiro, não só no fim.
        self.assertEqual([s and s["n_ok"] for s in seen], [None, 1, 2])
        self.assertIsNone(self.ex.running)
        sessions = self.db.sessions()
        self.assertEqual(len(sessions), 1)
        s = sessions[0]
        self.assertEqual((s["n_ok"], s["n_err"], s["finished"], s["undone"]), (2, 0, 0, 0))
        self.assertEqual(sorted(os.listdir(self.root / "Documentos" / "Finanças")), ["fatura_0.txt", "fatura_1.txt"])
        res = self.ex.undo(s["id"])
        self.assertEqual(res.errors, [])
        self.assertTrue(all(f.exists() for f in self.files))
        self.assertFalse((self.root / "Documentos").exists())
        self.assertEqual(self.db.session(s["id"])["undone"], 1)

    def test_finished_and_running_sessions(self):
        during = []
        res = self.ex.apply(self.actions(), str(self.root), "teste",
                            progress=lambda n, total, path: during.append(self.ex.running))
        self.assertEqual(set(during), {res.session_id})
        self.assertIsNone(self.ex.running)
        s = self.db.session(res.session_id)
        self.assertEqual((s["n_ok"], s["finished"], s["n_left"]), (4, 1, 4))

    def test_old_history_is_migrated(self):
        path = self.tmp / "antigo.db"
        conn = sqlite3.connect(path)
        conn.executescript(OLD_SCHEMA)
        ops = "INSERT INTO ops(session_id, seq, op, src, dst, status, error, ts) VALUES (?,?,?,?,?,?,?,0)"
        # 1: terminada; 2: interrompida a meio (ficou com 0 alterações e escondida); 3: só erros.
        conn.execute("INSERT INTO sessions(created, root, title, n_ok, n_err) VALUES (1, '/r', 'terminada', 1, 0)")
        conn.execute(ops, (1, 0, "move", "/r/a", "/r/D/a", "ok", None))
        conn.execute("INSERT INTO sessions(created, root, title) VALUES (2, '/r', 'interrompida')")
        conn.execute(ops, (2, 0, "mkdir", "/r/D", None, "ok", None))
        conn.execute(ops, (2, 1, "move", "/r/b", "/r/D/b", "ok", None))
        conn.execute(ops, (2, 2, "move", "/r/c", "/r/D/c", "erro", "Sem permissão"))
        conn.execute(ops, (2, 3, "trash", "/r/Thumbs.db", None, "ok", None))
        conn.execute("INSERT INTO sessions(created, root, title, n_ok, n_err) VALUES (3, '/r', 'só erros', 0, 1)")
        conn.execute(ops, (3, 0, "move", "/r/d", "/r/D/d", "erro", "Sem permissão"))
        conn.commit()
        conn.close()
        db = Database(path)
        rows = {s["title"]: s for s in db.sessions()}
        self.assertEqual(set(rows), {"terminada", "interrompida"})
        self.assertEqual((rows["terminada"]["finished"], rows["terminada"]["n_ok"]), (1, 1))
        self.assertEqual((rows["interrompida"]["finished"], rows["interrompida"]["n_ok"],
                          rows["interrompida"]["n_err"]), (0, 2, 1))
        Database(path)  # abrir outra vez não volta a migrar
        self.assertEqual(len(Database(path).sessions()), 2)
        # Um histórico novo já nasce com a coluna; as sessões novas começam por terminar.
        fresh = Database(self.tmp / "novo.db")
        sid = fresh.new_session("/r", "nova")
        self.assertEqual(fresh.session(sid)["finished"], 0)
        fresh.finish_session(sid, 0, 0)
        self.assertEqual(fresh.session(sid)["finished"], 1)

    def test_undo_with_a_failure_is_partial_and_can_be_retried(self):
        res = self.ex.apply(self.actions("Documentos"), str(self.root), "teste")
        blocker = write(self.files[1], "outro ficheiro com o mesmo nome")
        undo = self.ex.undo(res.session_id)
        self.assertEqual(undo.errors, [(str(self.files[1]), "Já existe um item com o mesmo nome no local original.")])
        s = self.db.session(res.session_id)
        self.assertEqual((s["undone"], s["n_left"]), (2, 1))
        self.assertTrue((self.root / "Documentos" / "fatura_1.txt").exists())
        self.assertEqual(blocker.read_text(encoding="utf-8"), "outro ficheiro com o mesmo nome")  # nada substituído
        blocker.unlink()
        again = self.ex.undo(res.session_id)
        self.assertEqual(again.errors, [])
        self.assertEqual(again.ok, 2)  # o ficheiro que faltava e a pasta criada, que agora ficou vazia
        self.assertEqual(self.db.session(res.session_id)["undone"], 1)
        self.assertTrue(all(f.exists() for f in self.files))
        self.assertFalse((self.root / "Documentos").exists())

    def test_undo_can_stop_and_continue(self):
        res = self.ex.apply(self.actions(), str(self.root), "teste")
        cancel = threading.Event()

        def progress(n, total, path):
            if n == 2:
                cancel.set()
        first = self.ex.undo(res.session_id, progress=progress, cancel=cancel)
        self.assertTrue(first.cancelled)
        self.assertEqual(first.ok, 2)
        s = self.db.session(res.session_id)
        self.assertEqual((s["undone"], s["n_left"]), (2, 2))
        rest = self.ex.undo(res.session_id)
        self.assertEqual((rest.ok, rest.errors, rest.cancelled), (2 + 2, [], False))  # 2 ficheiros e 2 pastas
        self.assertTrue(all(f.exists() for f in self.files))
        self.assertEqual(self.db.session(res.session_id)["undone"], 1)

    def test_undo_reasons(self):
        res = self.ex.apply(self.actions(), str(self.root), "teste")
        done = self.root / "Documentos" / "Finanças"
        # Um voltou à mão para o sítio: já está anulado. Outro desapareceu: diz porquê.
        os.rename(done / "fatura_0.txt", self.files[0])
        (done / "fatura_2.txt").unlink()
        undo = self.ex.undo(res.session_id)
        self.assertEqual(undo.errors, [(str(self.files[2]), "O ficheiro já não está onde foi colocado.")])
        self.assertEqual(self.db.session(res.session_id)["n_left"], 1)

    def test_nothing_undone_keeps_the_session_as_it_was(self):
        res = self.ex.apply(self.actions()[:1], str(self.root), "teste")
        write(self.files[0], "outro")
        self.assertEqual(len(self.ex.undo(res.session_id).errors), 1)
        self.assertEqual(self.db.session(res.session_id)["undone"], 0)


@unittest.skipIf(Gtk is None, "sem o PyGObject (gi)")
class UndoTextTests(unittest.TestCase):
    def test_question(self):
        from arruma.core.system import TRASH_TO
        from arruma.ui.page_history import undo_question
        s = {"title": "Arrumação de «Bagunça»", "undone": 0, "n_ok": 12, "n_left": 12}
        title, text, ok = undo_question(s)
        self.assertEqual((title, ok), ("Anular 12 alterações?", "Anular"))
        self.assertTrue(text.startswith(f"Arrumação de «Bagunça». Cada item volta ao sítio onde estava, incluindo o "
                                        f"que foi {TRASH_TO}."))
        title, text, ok = undo_question({**s, "undone": 2, "n_left": 1})
        self.assertEqual((title, ok), ("Anular o resto?", "Anular o resto"))
        self.assertIn("Ainda falta 1 item por voltar ao sítio onde estava.", text)
        self.assertIn("Ainda faltam 3 itens por voltar ao sítio onde estavam.",
                      undo_question({**s, "undone": 2, "n_left": 3})[1])

    def test_report_gives_the_real_reasons(self):
        from arruma.ui.page_history import REPORT_MAX, undo_report
        res = Result(1, ok=3, errors=[("/r/a.pdf", "Já existe um item com o mesmo nome no local original."),
                                      ("/r/b.pdf", "O ficheiro já não está no Lixo.")])
        text = undo_report(res)
        self.assertIn("3 operações revertidas. 2 itens não voltaram ao sítio onde estavam:", text)
        self.assertIn("• /r/a.pdf: Já existe um item com o mesmo nome no local original.", text)
        self.assertIn("• /r/b.pdf: O ficheiro já não está no Lixo.", text)
        self.assertIn("«Anular o resto»", text)
        self.assertNotIn("manualmente", text)
        many = Result(1, errors=[(f"/r/{i}", "erro") for i in range(REPORT_MAX + 5)])
        self.assertIn("… e mais 5.", undo_report(many))


def pump(cond, timeout: float = 20.0) -> bool:
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.01)
    return bool(cond())


@unittest.skipUnless(HAS_DISPLAY, "sem o PyGObject (gi) ou sem ecrã")
class WindowTests(unittest.TestCase):
    """A janela verdadeira, com um histórico e definições só do teste."""

    def setUp(self):
        from arruma.ui import app
        self.app = app
        self.tmp = Path(tempfile.mkdtemp(prefix="arruma-teste-")).resolve()
        self.root = self.tmp / "Bagunça"
        for i in range(5):
            write(self.root / f"fatura_{i}.txt", f"FATURA n.º {i} Total a pagar 10 EUR NIF 500")
        write(self.root / "Screenshot from 2025-01-02 10-00-00.png")
        self.messages = []
        self.answers = []  # respostas às confirmações, por ordem (por defeito, sim)
        self.questions = []
        patches = [
            mock.patch.object(app, "Database", lambda: Database(self.tmp / "historico.db")),
            mock.patch.object(app.Settings, "load", classmethod(lambda cls: Settings(use_ai=False))),
            mock.patch.object(app.ArrumaWindow, "refresh_ai", lambda self: None),
            mock.patch.object(app, "message", lambda _w, title, text, *_a: self.messages.append((title, text))),
            mock.patch.object(app, "confirm", self.confirm),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.application = Gtk.Application()
        self.application.register(None)
        self.win = app.ArrumaWindow(self.application)
        self.closed = False
        self.win.connect("destroy", lambda *_: setattr(self, "closed", True))
        self.win.start_scan(str(self.root))
        self.assertTrue(pump(lambda: self.win.scan_result is not None))

    def tearDown(self):
        pump(lambda: self.win._busy is None and self.win._task is None, 10)
        if not self.closed:
            self.win.destroy()
        pump(lambda: False, 0.05)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def confirm(self, _win, title, text, ok_label, *args, **kwargs):
        self.questions.append((title, text, ok_label, kwargs.get("cancel_label", "Cancelar")))
        return self.answers.pop(0) if self.answers else True

    def build_plan(self):
        self.win.build_plan("inside")
        self.assertTrue(pump(lambda: self.win.plan_page.get_visible_child_name() == "content"))
        return self.win.plan_page.plan

    def slow_moves(self, seconds=0.1):
        real = executor_mod.safe_move

        def slow(src, dst):
            time.sleep(seconds)
            real(src, dst)
        p = mock.patch.object(executor_mod, "safe_move", slow)
        p.start()
        self.addCleanup(p.stop)

    def moved(self):
        return [p.name for p in self.root.iterdir() if p.is_file()]

    def test_nothing_interrupts_the_apply(self):
        plan = self.build_plan()
        self.slow_moves()
        self.win.apply_plan(plan.enabled())
        cancel = self.win._cancel
        session = self.win.executor.apply([], str(self.root), "outra")  # uma sessão qualquer para anular
        for attempt in (lambda: self.win.start_scan(str(self.root)), self.win.find_duplicates,
                        lambda: self.win.build_plan("inside"), lambda: self.win.undo_session(session.session_id),
                        lambda: self.win.trash_duplicates([str(self.root / "fatura_4.txt")])):
            attempt()
            self.assertFalse(cancel.is_set())
            self.assertEqual(self.win.toast.text.get_text(), "O Arruma ainda está a arrumar. Espera que termine.")
        # O «Cancelar» das outras vistas também não para a arrumação.
        self.win.cancel_task("scan")
        self.win.cancel_task("duplicates")
        self.assertFalse(cancel.is_set())
        self.assertEqual(self.win.plan_page.get_visible_child_name(), "progress")
        self.assertTrue(pump(lambda: self.win.plan_page.get_visible_child_name() == "done"))
        self.assertEqual(self.moved(), [])
        self.assertEqual(self.questions, [])

    def test_closing_while_applying(self):
        plan = self.build_plan()
        self.slow_moves(0.2)
        self.win.apply_plan(plan.enabled())
        cancel = self.win._cancel
        self.assertTrue(pump(lambda: len(self.moved()) < 6, 5))
        self.answers = [False]  # «Não fechar»
        self.assertTrue(self.win._on_delete())
        self.assertEqual(self.questions[-1][0], "O Arruma ainda está a arrumar")
        self.assertEqual(self.questions[-1][2:], ("Parar e fechar", "Não fechar"))
        self.assertFalse(cancel.is_set())
        self.assertFalse(self.closed)
        self.win.navigate("history")  # a sessão em curso aparece «a decorrer», sem «Anular»
        self.assertTrue(pump(lambda: self.win.history_page.get_visible_child_name() == "content", 2))
        labels = [w.get_text() for w in self.walk(self.win.history_page.list, Gtk.Label)]
        self.assertIn("A decorrer", labels)
        self.answers = [True]  # «Parar e fechar»
        self.assertTrue(self.win._on_delete())
        self.assertTrue(cancel.is_set())
        self.assertFalse(self.closed)  # espera pelo item em curso
        self.assertTrue(pump(lambda: self.closed, 10))
        sessions = Database(self.tmp / "historico.db").sessions()
        self.assertEqual(len(sessions), 1)
        self.assertGreater(sessions[0]["n_ok"], 0)
        self.assertGreater(len(self.moved()), 0)  # parou a meio

    def test_analysis_is_refreshed_after_apply(self):
        plan = self.build_plan()
        old = self.win.scan_result
        self.win.apply_plan(plan.enabled())
        self.assertTrue(pump(lambda: self.win.scan_result is not old and self.win._task is None))
        self.assertTrue(all(os.path.exists(f.path) for f in self.win.scan_result.files))
        self.assertEqual(self.win.stack.get_visible_child_name(), "plan")  # o «Está arrumado!» fica à vista
        self.assertEqual(self.win.plan_page.get_visible_child_name(), "done")
        self.assertEqual(self.win.analysis_page.get_visible_child_name(), "content")
        self.assertEqual(self.win.duplicates_page.get_visible_child_name(), "intro")
        self.win.build_plan("inside")
        self.assertTrue(pump(lambda: self.win.plan_page.get_visible_child_name() in ("content", "done")))
        self.assertFalse(any(not os.path.lexists(a.src) for a in self.win.plan_page.plan.actions))

    def test_undo_asks_shows_progress_and_reports(self):
        plan = self.build_plan()
        self.win.apply_plan(plan.enabled())
        self.assertTrue(pump(lambda: self.win._busy is None and self.win._task is None))
        sid = Database(self.tmp / "historico.db").sessions()[0]["id"]
        self.answers = [False]
        self.win.undo_session(sid)
        self.assertEqual(self.questions[-1][0], f"Anular {len(plan.actions)} alterações?")
        self.assertEqual(self.moved(), [])  # não anulou
        blocker = write(self.root / "fatura_0.txt", "outro ficheiro")
        self.slow_moves(0.05)
        scans = []
        real_scan = self.win.start_scan
        with mock.patch.object(self.win, "start_scan", lambda paths, **kw: (scans.append((paths, kw)),
                                                                             real_scan(paths, **kw))):
            self.win.undo_session(sid)
            self.assertEqual(self.win.stack.get_visible_child_name(), "history")
            self.assertEqual(self.win.history_page.get_visible_child_name(), "progress")
            self.assertEqual(self.win.history_page.progress.title.get_text(), "A anular…")
            self.assertTrue(pump(lambda: self.messages))
        title, text = self.messages[-1]
        self.assertEqual(title, "Anulação incompleta")
        self.assertIn("fatura_0.txt: Já existe um item com o mesmo nome no local original.", text)
        self.assertNotIn("manualmente", text)
        self.assertEqual(scans, [([str(self.root)], {"refresh": True})])  # a análise atual, que foi mexida
        self.assertEqual(self.win.stack.get_visible_child_name(), "history")
        self.assertEqual(self.win.plan_page.get_visible_child_name(), "empty")
        self.assertEqual(Database(self.tmp / "historico.db").session(sid)["undone"], 2)
        labels = [w.get_text() for w in self.walk(self.win.history_page.list, Gtk.Label)]
        buttons = [b.get_label() for b in self.walk(self.win.history_page.list, Gtk.Button)]
        self.assertIn("Anulada em parte", labels)
        self.assertIn("Anular o resto", buttons)
        blocker.unlink()
        self.win.undo_session(sid)
        self.assertEqual(self.questions[-1][0], "Anular o resto?")
        self.assertTrue(pump(lambda: self.win.toast.text.get_text().startswith("Alterações anuladas")))
        self.assertEqual(sorted(self.moved()), sorted(os.path.basename(a.src) for a in plan.actions))
        self.assertEqual(Database(self.tmp / "historico.db").session(sid)["undone"], 1)
        self.win.undo_session(sid)  # já anulada: não pergunta outra vez
        self.assertEqual(self.questions[-1][0], "Anular o resto?")
        self.assertIn("já foi anulada", self.win.toast.text.get_text())

    def test_undo_of_other_folders_keeps_the_analysis(self):
        other = self.tmp / "Outra"
        src = write(other / "fatura.txt")
        res = self.win.executor.apply([move(0, src, other / "Documentos" / "fatura.txt")], str(other), "Outra")
        before = self.win.scan_result
        self.win.navigate("history")
        self.win.undo_session(res.session_id)
        self.assertTrue(pump(lambda: self.win._busy is None))
        pump(lambda: False, 0.3)
        self.assertIs(self.win.scan_result, before)
        self.assertIsNone(self.win._task)  # não voltou a analisar
        self.assertEqual(self.win.stack.get_visible_child_name(), "history")
        self.assertTrue(src.exists())

    def test_apply_error_recovers(self):
        plan = self.build_plan()
        with mock.patch.object(self.win.executor, "apply", side_effect=sqlite3.OperationalError("disk I/O error")):
            self.win.apply_plan(plan.enabled())
            self.assertTrue(pump(lambda: self.messages))
        self.assertEqual(self.messages[-1][0], "Erro ao arrumar")
        self.assertIn("disk I/O error", self.messages[-1][1])
        self.assertNotEqual(self.win.plan_page.get_visible_child_name(), "progress")
        self.assertIsNone(self.win._busy)
        self.assertEqual(self.win.stack.get_visible_child_name(), "analysis")
        self.assertTrue(pump(lambda: self.win._task is None))
        self.win.find_duplicates()  # a janela não ficou presa
        self.assertEqual(self.win._task, "duplicates")

    def walk(self, widget, kind):
        found = [widget] if isinstance(widget, kind) else []
        if isinstance(widget, Gtk.Container):
            for c in widget.get_children():
                found += self.walk(c, kind)
        return found


if __name__ == "__main__":
    unittest.main()
