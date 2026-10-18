# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes das diferenças entre sistemas (Linux, Windows, macOS). Correm nos três no CI.

A ida ao Lixo e o regresso só correm com ARRUMA_TESTAR_LIXO=1, porque mexem no Lixo real."""

import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arruma.core import system  # noqa: E402
from arruma.core.fsutil import (check_root_allowed, is_within, path_key, sanitize_name,  # noqa: E402
                                unique_path)
from arruma.core.scanner import scan  # noqa: E402
from arruma.core.trash import find_in_recycle_bin, parse_recycle_index  # noqa: E402


def recycle_index(path: str, deleted: int, version: int = 2) -> bytes:
    """Ficheiro $I da Reciclagem do Windows, como o Windows 10/11 o escreve."""
    raw = (path + "\0").encode("utf-16-le")
    head = version.to_bytes(8, "little") + (123).to_bytes(8, "little") + deleted.to_bytes(8, "little")
    if version == 1:
        return head + raw.ljust(520, b"\0")
    return head + (len(raw) // 2).to_bytes(4, "little") + raw


class SystemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arruma-teste-")).resolve()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_user_dirs(self):
        dirs = system.user_dirs()
        for key in ("DESKTOP", "DOWNLOAD", "DOCUMENTS", "MUSIC", "PICTURES", "VIDEOS"):
            self.assertIsInstance(dirs[key], Path)
            self.assertTrue(dirs[key].is_absolute(), dirs[key])
        if system.IS_WINDOWS or system.IS_MAC:
            self.assertTrue(dirs["DOCUMENTS"].is_dir(), dirs["DOCUMENTS"])

    def test_config_dir_is_writable(self):
        path = system.config_dir()
        self.assertTrue(path.is_dir())
        self.assertTrue(os.access(path, os.W_OK))

    def test_reserved_and_bad_names(self):
        self.assertEqual(sanitize_name("CON"), "_CON")
        self.assertEqual(sanitize_name("nul.txt"), "_nul.txt")
        self.assertEqual(sanitize_name("Fatura: EDP / março?"), "Fatura EDP março")
        self.assertEqual(sanitize_name("Console"), "Console")

    def test_paths_and_case(self):
        base = str(self.tmp / "Documentos")
        self.assertTrue(is_within(os.path.join(base, "Finanças", "x.pdf"), base))
        self.assertFalse(is_within(base + "2", base))
        if system.IS_WINDOWS or system.IS_MAC:
            self.assertEqual(path_key(base + "/Faturas"), path_key(base + "/FATURAS"))
        taken = {path_key(self.tmp / "Faturas" / "a.pdf")}
        cand = unique_path(self.tmp / ("faturas" if system.IS_LINUX else "Faturas") / "a.pdf", taken)
        if system.IS_LINUX:
            self.assertEqual(cand.name, "a.pdf")  # no Linux «faturas» e «Faturas» são pastas diferentes
        else:
            self.assertEqual(cand.name, "a (2).pdf")

    def test_temp_folders_can_be_organized(self):
        self.assertIsNone(check_root_allowed(self.tmp))

    def test_system_folders_are_refused(self):
        for path in system.system_paths()[:3]:
            if os.path.isdir(path):
                self.assertIsNotNone(check_root_allowed(path), path)

    def test_hidden_files_are_skipped(self):
        (self.tmp / ".oculto").write_text("x")
        visible = self.tmp / "visivel.txt"
        visible.write_text("x")
        marked = self.tmp / "marcado.txt"
        marked.write_text("x")
        hidden_by_attribute = False
        if system.IS_WINDOWS:
            import ctypes
            hidden_by_attribute = bool(ctypes.windll.kernel32.SetFileAttributesW(str(marked), 2))
        elif system.IS_MAC:
            os.chflags(marked, stat.UF_HIDDEN)
            hidden_by_attribute = True
        names = {f.name for f in scan(str(self.tmp)).files}
        self.assertIn("visivel.txt", names)
        self.assertNotIn(".oculto", names)
        if hidden_by_attribute:
            self.assertNotIn("marcado.txt", names)

    def test_package_folders_are_not_opened(self):
        app = self.tmp / "Programa.app" / "Contents"
        app.mkdir(parents=True)
        (app / "Info.plist").write_text("x")
        result = scan(str(self.tmp))
        self.assertFalse(any("Programa.app" in f.path for f in result.files))
        self.assertIn(str(self.tmp / "Programa.app"), [p for p, _ in result.protected])

    def test_find_tool_does_not_crash(self):
        for name in ("pdftotext", "tesseract", "ollama", "programa-que-nao-existe"):
            found = system.find_tool(name)
            self.assertTrue(found is None or os.path.isfile(found), found)

    def test_bundled_tools_come_first(self):
        """Na versão empacotada usa-se o pdftotext que vem com o Arruma, mesmo havendo outro no PATH."""
        tool = self.tmp / ("pdftotext.exe" if system.IS_WINDOWS else "pdftotext")
        tool.write_bytes(b"")
        tool.chmod(0o755)
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "_MEIPASS", str(self.tmp), create=True):
            self.assertEqual(system.find_tool("pdftotext"), str(tool))

    def test_recycle_bin_index(self):
        for version in (1, 2):
            path, deleted = parse_recycle_index(recycle_index(r"C:\Users\Ana\Desktop\fatura.pdf", 42, version))
            self.assertEqual(path, r"C:\Users\Ana\Desktop\fatura.pdf")
            self.assertEqual(deleted, 42)
        self.assertEqual(parse_recycle_index(b"lixo"), (None, 0))

    def test_recycle_bin_lookup_picks_latest(self):
        sid = self.tmp / "$Recycle.Bin" / "S-1-5-21-1"
        sid.mkdir(parents=True)
        orig = os.path.join(str(self.tmp), "Ana", "fatura.pdf")
        for name, when in (("ABC123.pdf", 10), ("XYZ789.pdf", 20)):
            (sid / f"$I{name}").write_bytes(recycle_index(orig, when))
            (sid / f"$R{name}").write_bytes(b"pdf")
        found = find_in_recycle_bin(orig, self.tmp / "$Recycle.Bin")
        self.assertIsNotNone(found)
        self.assertEqual(found[1].name, "$RXYZ789.pdf")
        self.assertIsNone(find_in_recycle_bin(orig + "x", self.tmp / "$Recycle.Bin"))


@unittest.skipUnless(os.environ.get("ARRUMA_TESTAR_LIXO") == "1", "só com ARRUMA_TESTAR_LIXO=1")
class TrashRoundTripTests(unittest.TestCase):
    """Envia um ficheiro para o Lixo verdadeiro e anula, como o Arruma faz no Histórico."""

    def test_trash_and_restore(self):
        from arruma.core.trash import restore, send_to_trash
        folder = Path(tempfile.mkdtemp(prefix="arruma-lixo-", dir=os.environ.get("ARRUMA_PASTA_LIXO") or None)).resolve()
        try:
            target = folder / "temporario.tmp"
            target.write_text("conteúdo de teste", encoding="utf-8")
            where = send_to_trash(str(target))
            self.assertFalse(target.exists())
            restore(str(target), where)
            self.assertEqual(target.read_text(encoding="utf-8"), "conteúdo de teste")
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
