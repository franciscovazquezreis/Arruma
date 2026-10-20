# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes do núcleo (sem interface). Executar: python3 -m unittest discover -s tests"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arruma.core import taxonomy as tx  # noqa: E402
from arruma.core.db import Database  # noqa: E402
from arruma.core.duplicates import find_duplicates  # noqa: E402
from arruma.core.executor import Executor  # noqa: E402
from arruma.core.fsutil import is_generic_dir_name, is_unclear_name, sanitize_name  # noqa: E402
from arruma.core.planner import MODE_INSIDE, Planner  # noqa: E402
from arruma.core.scanner import scan  # noqa: E402
from arruma.core.settings import Settings  # noqa: E402


def write(path: Path, content: str | bytes = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)
    return path


def make_docx(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml",
                   f'<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')


def make_jpg(path: Path) -> None:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), (200, 100, 50)).save(path, "JPEG")


class NameTests(unittest.TestCase):
    def test_unclear(self):
        for n in ["scan_003", "Documento (1)", "8f3a2c9d1e", "IMG_1234", "DOC00123", "untitled",
                  "fatura_123", "20240812_101010"]:
            self.assertTrue(is_unclear_name(n), n)
        for n in ["Contrato arrendamento Lisboa", "CV Francisco 2025", "Relatório anual"]:
            self.assertFalse(is_unclear_name(n), n)

    def test_generic_dirs(self):
        for n in ["Nova pasta", "New Folder (2)", "untitled folder", "temp", "Diversos"]:
            self.assertTrue(is_generic_dir_name(n), n)
        for n in ["Férias Algarve", "2023", "Casamento Ana", "IRS"]:
            self.assertFalse(is_generic_dir_name(n), n)

    def test_sanitize(self):
        self.assertEqual(sanitize_name('Fatura: EDP / março?'), "Fatura EDP março")

    def test_keywords(self):
        area, sub, conf, _ = tx.keyword_classify("doc.pdf", "FATURA nº 123 NIF 500 Total a pagar 30€")
        self.assertEqual((area, sub), ("Finanças", "Faturas e Recibos"))
        area, *_ = tx.keyword_classify("x.pdf", "Resultado de análises clínicas, hemograma")
        self.assertEqual(area, "Saúde")


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arruma-teste-")).resolve()
        self.root = self.tmp / "Bagunça"
        r = self.root
        write(r / "fatura_123.txt", "FATURA nº 2025/123 NIF 501 Total a pagar 42,10 EUR")
        write(r / "fatura_123 (1).txt", "FATURA nº 2025/123 NIF 501 Total a pagar 42,10 EUR")
        make_docx(r / "Documento (1).docx", "Resultado de análises clínicas: hemograma completo")
        make_jpg(r / "IMG_20240812_101010.jpg")
        write(r / "Screenshot from 2025-01-02 10-00-00.png", b"\x89PNG fake")
        write(r / "musica.mp3", b"ID3 fake")
        write(r / "programa.deb", b"!<arch>")
        write(r / "fotos.zip", b"PK fake")
        write(r / "Thumbs.db", b"junk")
        write(r / "Nova pasta" / "contrato.txt", "Contrato de arrendamento entre senhorio e inquilino")
        make_jpg(r / "Férias Algarve" / "praia1.jpg")
        make_jpg(r / "Férias Algarve" / "praia2.jpg")
        write(r / "meuprojeto" / "main.py", "print('olá')")
        (r / "meuprojeto" / ".git").mkdir(parents=True)
        (r / "Nova pasta (2)").mkdir()
        self.settings = Settings(use_ai=False, clean_junk=True)
        self.db = Database(self.tmp / "teste.db")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def snapshot(self):
        out = set()
        for dp, dirs, files in os.walk(self.root):
            for f in files:
                out.add(os.path.relpath(os.path.join(dp, f), self.root).replace(os.sep, "/"))
        return out

    def build(self):
        result = scan(self.root)
        return result, Planner(result, self.settings, MODE_INSIDE, db=self.db).build()

    def test_scan_protects_projects(self):
        result = scan(self.root)
        reasons = dict(result.protected)
        self.assertEqual(reasons.get(str(self.root / "meuprojeto")), "projeto de programação")

    def test_plan(self):
        _, plan = self.build()
        by_src = {os.path.relpath(a.src, self.root).replace(os.sep, "/"): a for a in plan.actions}
        rel = lambda a: os.path.relpath(a.dst, self.root).replace(os.sep, "/")  # noqa: E731

        # Poucos ficheiros: não se criam subpastas de subárea, ano ou mês só para um ou dois.
        self.assertEqual(rel(by_src["fatura_123.txt"]), "Documentos/Finanças/fatura_123.txt")
        self.assertTrue(rel(by_src["Documento (1).docx"]).startswith("Documentos/Saúde/"))
        self.assertEqual(rel(by_src["IMG_20240812_101010.jpg"]), "Imagens/Fotografias/IMG_20240812_101010.jpg")
        self.assertEqual(rel(by_src["Screenshot from 2025-01-02 10-00-00.png"]),
                         "Imagens/Capturas de ecrã/Screenshot from 2025-01-02 10-00-00.png")
        self.assertTrue(rel(by_src["programa.deb"]).startswith("Instaladores/"))
        self.assertTrue(rel(by_src["fotos.zip"]).startswith("Ficheiros comprimidos/"))
        self.assertTrue(rel(by_src["Nova pasta/contrato.txt"]).startswith("Documentos/Casa/"))
        self.assertEqual(by_src["Thumbs.db"].op, "trash")
        # Subpasta com nome próprio dentro da pasta escolhida: fica onde está.
        self.assertNotIn("Férias Algarve", by_src)
        self.assertIn(str(self.root / "Férias Algarve"), [p for p, _ in plan.respected])
        self.assertEqual(by_src["Nova pasta (2)"].op, "rmdir")
        self.assertFalse(any("meuprojeto" in s for s in by_src))
        # destinos nunca colidem
        dsts = [a.dst for a in plan.actions if a.dst]
        self.assertEqual(len(dsts), len(set(dsts)))

    def test_apply_and_undo(self):
        before = self.snapshot()
        _, plan = self.build()
        actions = [a for a in plan.enabled() if a.op != "trash"]  # o Lixo pode não existir em /tmp
        ex = Executor(self.db)
        res = ex.apply(actions, plan.root, "teste", cleanup_dirs=plan.cleanup_dirs,
                       protect=set(plan.bases.values()))
        self.assertEqual(res.errors, [])
        after = self.snapshot()
        self.assertIn("Instaladores/programa.deb", after)
        self.assertFalse((self.root / "Nova pasta").exists())
        # Correr de novo não deve propor mais mudanças (idempotente)
        _, plan2 = self.build()
        moves2 = [a for a in plan2.actions if a.op in ("move", "move_dir")]
        self.assertEqual(moves2, [], [(a.src, a.dst) for a in moves2])
        # Anular repõe tudo
        undo = ex.undo(res.session_id)
        self.assertEqual(undo.errors, [])
        self.assertEqual(self.snapshot(), before)
        self.assertTrue((self.root / "Nova pasta (2)").is_dir())
        self.assertFalse((self.root / "Documentos").exists())

    def test_duplicates(self):
        result = scan(self.root)
        groups = find_duplicates(result.files)
        group = next(g for g in groups if any(f.name == "fatura_123.txt" for f in g.files))
        self.assertEqual(sorted(f.name for f in group.files), ["fatura_123 (1).txt", "fatura_123.txt"])
        self.assertEqual(os.path.basename(group.keep), "fatura_123.txt")
        # O título do grupo nos Duplicados é o da cópia que fica, não o da primeira por ordem alfabética.
        self.assertEqual(group.files[0].name, "fatura_123 (1).txt")
        self.assertEqual(group.keep_file.name, "fatura_123.txt")

    def test_duplicates_compare_the_whole_content(self):
        from arruma.core.duplicates import CHUNK
        from arruma.core.scanner import FileItem
        comum = bytes(range(256)) * (CHUNK // 256)
        casos = {  # tamanhos à volta dos limites de leitura parcial
            "pequeno": (comum[:1000] + b"A", comum[:1000] + b"B"),
            "medio": (comum + b"A" * 36000, comum + b"B" * 36000),  # iguais nos primeiros 64 KB
            "grande": (comum + b"A" * CHUNK * 2 + comum, comum + b"B" * CHUNK * 2 + comum),  # início e fim iguais
        }
        for nome, (a, b) in casos.items():
            itens = []
            for sufixo, dados in (("a", a), ("b", b), ("c", a)):
                p = self.root / f"{nome}-{sufixo}.bin"
                p.write_bytes(dados)
                itens.append(FileItem(str(p), p.name, "bin", len(dados), p.stat().st_mtime, tx.OTHER, str(self.root)))
            grupos = find_duplicates(itens)
            self.assertEqual([sorted(f.name for f in g.files) for g in grupos],
                             [[f"{nome}-a.bin", f"{nome}-c.bin"]], nome)

    def test_ai_security_and_validation(self):
        from arruma.core.ai import AIError, LocalAI, validate_result
        with self.assertRaises(AIError):
            LocalAI("http://example.com:11434")
        ai = LocalAI("http://127.0.0.1:11434")
        self.assertEqual(ai.base, "http://127.0.0.1:11434")
        r = validate_result({"area": "financAs", "subarea": "faturas e recibos",
                             "titulo": "Fatura EDP março.pdf", "data": "2025-03-10", "confianca": 0.92})
        self.assertEqual(r["area"], "Finanças")
        self.assertEqual(r["subarea"], "Faturas e Recibos")
        self.assertEqual(r["titulo"], "Fatura EDP março")
        self.assertEqual(r["data"], "2025-03-10")

    def test_ai_check_starts_ollama_only_when_asked(self):
        from arruma.core.ai import AIError, LocalAI
        ai = LocalAI("http://127.0.0.1:11434")
        stopped = AIError("Não foi possível contactar o Ollama. Está instalado e a correr?")
        with mock.patch.object(LocalAI, "_request", side_effect=stopped), \
                mock.patch.object(LocalAI, "_try_autostart", return_value=False) as autostart:
            status = ai.check(autostart=False)  # com a IA desligada: só se vê o estado
            autostart.assert_not_called()
            self.assertEqual((status.ok, status.running, status.error), (False, False, str(stopped)))
            ai.check()
            autostart.assert_called_once()

    def test_ai_status_tells_ollama_without_a_model_apart(self):
        from arruma.core.ai import LocalAI

        def ollama(models):
            return lambda path, *a, **k: {"version": "0.12.3"} if path == "/api/version" else {"models": models}
        ai = LocalAI("http://127.0.0.1:11434")
        with mock.patch.object(LocalAI, "_request", side_effect=ollama([{"name": "nomic-embed-text:latest"}])):
            status = ai.check()
        self.assertEqual((status.ok, status.running, status.version), (False, True, "0.12.3"))
        self.assertIn("ainda não tem nenhum modelo", status.error)
        with mock.patch.object(LocalAI, "_request", side_effect=ollama([{"name": "qwen2.5:3b"}])):
            status = ai.check()
        self.assertEqual((status.ok, status.running, status.model), (True, True, "qwen2.5:3b"))

    def test_multi_folder_and_whole_computer(self):
        from arruma.core.fsutil import COMPUTER_TOKEN, check_root_allowed, normalize_roots
        roots, whole = normalize_roots(COMPUTER_TOKEN)
        self.assertTrue(whole)
        self.assertGreaterEqual(len(roots), 1)
        self.assertIsNone(check_root_allowed(COMPUTER_TOKEN))

        dir_b = self.tmp / "SegundaPasta"
        write(dir_b / "recibo_agua.txt", "FATURA de água NIF 502 Total a pagar 18,50 EUR")
        res = scan([self.root, dir_b])
        self.assertEqual(len(res.roots), 2)
        plan = Planner(res, self.settings, MODE_INSIDE, db=self.db).build()
        self.assertTrue(any(a.src.endswith("recibo_agua.txt") and a.dst.startswith(str(dir_b)) for a in plan.actions))

    def test_rename_and_move_in_plan(self):
        from arruma.core.planner import move_folder_in_plan, rename_action_in_plan, rename_folder_in_plan, retarget
        _, plan = self.build()
        by_src = {os.path.relpath(a.src, self.root).replace(os.sep, "/"): a for a in plan.actions}
        fat = by_src["fatura_123.txt"]
        old_dir = os.path.dirname(fat.dst)
        # 1. Renomear pasta sugerida
        new_dir = rename_folder_in_plan(plan, old_dir, "Despesas Mensais")
        self.assertEqual(new_dir, os.path.join(os.path.dirname(old_dir), "Despesas Mensais"))
        self.assertEqual(os.path.dirname(fat.dst), new_dir)
        # 2. Mover pasta sugerida para dentro de outra pasta
        target_parent = str(self.root / "Documentos" / "Casa")
        moved_dir = move_folder_in_plan(plan, new_dir, target_parent)
        self.assertEqual(moved_dir, os.path.join(target_parent, "Despesas Mensais"))
        self.assertEqual(os.path.dirname(fat.dst), moved_dir)
        # 3. Alterar o nome proposto de um ficheiro
        rename_action_in_plan(fat, plan, "Fatura Luz Janeiro")
        self.assertEqual(fat.dst_name, "Fatura Luz Janeiro.txt")
        self.assertTrue(fat.renamed)
        # 4. Arrastar um ficheiro para outra pasta (retarget)
        custom_folder = str(self.root / "Documentos" / "Arquivo 2025")
        retarget(fat, plan, custom_folder)
        self.assertEqual(os.path.dirname(fat.dst), custom_folder)

    def test_existing_folders_keep_name_and_place_in_plan(self):
        # Mudar o nome de uma pasta que já existe só mandaria os itens do plano para uma pasta nova;
        # a pasta real e o que já lá estava ficavam. Por isso não muda nada.
        from arruma.core.planner import move_folder_in_plan, rename_folder_in_plan
        write(self.root / "Documentos" / "Finanças" / "antiga.txt", "FATURA antiga NIF 501")
        _, plan = self.build()
        fat = next(a for a in plan.actions if a.src_name == "fatura_123.txt")
        fin = str(self.root / "Documentos" / "Finanças")
        self.assertEqual(os.path.dirname(fat.dst), fin)
        self.assertEqual(rename_folder_in_plan(plan, fin, "Despesas"), fin)
        self.assertIsNone(move_folder_in_plan(plan, fin, str(self.root / "Arquivo")))
        self.assertEqual(os.path.dirname(fat.dst), fin)
        self.assertEqual(fat.source, "palavras-chave")
        # As pastas novas continuam a poder mudar de nome.
        img = next(a for a in plan.actions if a.src_name == "IMG_20240812_101010.jpg")
        fotos = os.path.dirname(img.dst)
        self.assertFalse(os.path.isdir(fotos))
        self.assertEqual(rename_folder_in_plan(plan, fotos, "Fotos"), os.path.join(os.path.dirname(fotos), "Fotos"))
        self.assertEqual(os.path.basename(os.path.dirname(img.dst)), "Fotos")

    def test_empty_folders_follow_the_setting(self):
        # Desligada, nem as pastas que já estavam vazias são propostas.
        self.settings.remove_empty_dirs = False
        _, plan = self.build()
        self.assertEqual([a.src for a in plan.actions if a.op == "rmdir"], [])
        # Ligada, só pastas genéricas sem nada lá dentro (nem pastas com nome próprio, nem ocultos),
        # e nunca uma pasta que vai receber ficheiros do plano.
        self.settings.remove_empty_dirs = True
        (self.root / "Nova pasta (3)" / "Férias").mkdir(parents=True)
        write(self.root / "temp" / ".configuracao", "x")
        (self.root / "Documentos" / "Outros").mkdir(parents=True)
        write(self.root / "coisa solta.txt", "Umas linhas sem pistas nenhumas.")
        _, plan = self.build()
        rm = {os.path.relpath(a.src, self.root).replace(os.sep, "/") for a in plan.actions if a.op == "rmdir"}
        self.assertEqual(rm, {"Nova pasta (2)"})
        notas = next(a for a in plan.actions if a.src_name == "coisa solta.txt")
        self.assertEqual(Path(notas.dst).parent, self.root / "Documentos" / "Outros")
        self.assertTrue(all(a.reason == "Pasta vazia sem nome próprio." for a in plan.actions if a.op == "rmdir"))

    def test_protected_folders_cannot_be_chosen_directly(self):
        from arruma.core.fsutil import COMPUTER_TOKEN
        from arruma.core.scanner import check_root_protected
        write(self.tmp / "Dropbox" / "fatura.txt", "FATURA n.º 9")
        write(self.tmp / "Calibre" / "metadata.db", "x")
        write(self.tmp / "Arquivo" / "2020" / "velho.txt", "x")
        excluded = [str(self.tmp / "Arquivo")]
        for rel, why in (("Dropbox", "pasta sincronizada (Dropbox)"), ("Bagunça/meuprojeto", "projeto de programação"),
                         ("Calibre", "biblioteca do Calibre")):
            msg = check_root_protected(self.tmp / rel, excluded)
            self.assertIsNotNone(msg, rel)
            self.assertIn(why, msg)
        self.assertIn("«Pastas a ignorar sempre»", check_root_protected(self.tmp / "Arquivo", excluded))
        self.assertIn("dentro de «Arquivo»", check_root_protected(self.tmp / "Arquivo" / "2020", excluded))
        # Uma pasta normal com pastas protegidas lá dentro escolhe-se na mesma: essas são só ignoradas.
        write(self.root / "Dropbox" / "partilhado.txt", "x")
        self.assertIsNone(check_root_protected(self.root, excluded))
        self.assertIsNone(check_root_protected(self.tmp, excluded))
        self.assertIsNone(check_root_protected(COMPUTER_TOKEN, excluded))
        protected = dict(scan(self.root, excluded=excluded).protected)
        self.assertEqual(protected.get(str(self.root / "Dropbox")), "pasta sincronizada (Dropbox)")

    def test_whole_computer_skips_excluded_disks(self):
        # «Todo o computador» inclui os discos montados: um que esteja em «Pastas a ignorar sempre» fica de fora.
        from arruma.core.fsutil import COMPUTER_TOKEN
        from arruma.core.planner import MODE_PERSONAL
        home = self.tmp / "casa"
        disk = self.tmp / "media" / "Backup"
        write(home / "fatura_1.txt", "FATURA n.º 1 Total a pagar 10 EUR NIF 500")
        write(disk / "relatorio.pdf", "x")
        make_jpg(disk / "foto.jpg")
        write(disk / "Sub" / "nota.txt", "x")
        with mock.patch("arruma.core.fsutil.computer_roots", return_value=[str(home), str(disk)]):
            res = scan(COMPUTER_TOKEN, excluded=[str(disk)])
        self.assertTrue(res.whole_computer)
        self.assertEqual([f.name for f in res.files], ["fatura_1.txt"])
        self.assertIn((str(disk), "excluída nas definições"), res.protected)
        for mode in (MODE_INSIDE, MODE_PERSONAL):
            plan = Planner(res, self.settings, mode, db=self.db).build()
            self.assertFalse([a.src for a in plan.actions if str(disk) in a.src], mode)

    def test_merging_a_new_folder_into_an_existing_one(self):
        # Uma pasta nova com o nome e o local de uma que já existe junta-se a ela; depois já não se separa.
        # (A interface pergunta antes: ver PlanPageFolderTests.test_merge_asks_first.)
        from arruma.core.planner import move_folder_in_plan, rename_folder_in_plan
        write(self.root / "Documentos" / "Finanças" / "antiga.txt", "FATURA antiga NIF 501")
        _, plan = self.build()
        img = next(a for a in plan.actions if a.src_name == "IMG_20240812_101010.jpg")
        fotos = os.path.dirname(img.dst)
        fin = str(self.root / "Documentos" / "Finanças")
        moved = move_folder_in_plan(plan, fotos, str(self.root / "Documentos"))
        self.assertEqual(rename_folder_in_plan(plan, moved, "Finanças"), fin)
        self.assertEqual(os.path.dirname(img.dst), fin)
        self.assertEqual(rename_folder_in_plan(plan, fin, os.path.basename(fotos)), fin)  # já não se separa

    def test_personal_folders_are_never_projects(self):
        # O VS Code guarda as extensões em ~/.vscode e as Transferências têm muitas vezes ficheiros soltos
        # como «Makefile»: nem por isso deixam de se poder arrumar. «Público» continua protegida.
        from arruma.core.scanner import check_root_protected
        home = self.tmp / "casa"
        write(home / ".vscode" / "extensions" / "extensions.json", "[]")
        write(home / "Transferências" / "Makefile", "all:")
        write(home / "Transferências" / "package.json", "{}")
        write(home / "Público" / "partilha.txt", "x")
        dirs = {k: home / v for k, v in {"DESKTOP": "Secretária", "DOWNLOAD": "Transferências",
                                          "DOCUMENTS": "Documentos", "MUSIC": "Música", "PICTURES": "Imagens",
                                          "VIDEOS": "Vídeos", "TEMPLATES": "Modelos",
                                          "PUBLICSHARE": "Público"}.items()}
        with mock.patch("arruma.core.scanner.HOME", home), \
                mock.patch("arruma.core.scanner.user_dirs", return_value=dirs):
            self.assertIsNone(check_root_protected(home))
            self.assertIsNone(check_root_protected(home / "Transferências"))
            self.assertIn("pasta pública partilhada", check_root_protected(home / "Público") or "")
            write(self.tmp / "Coisas" / "Makefile", "all:")  # fora das pastas pessoais é um projeto
            self.assertIn("projeto de programação", check_root_protected(self.tmp / "Coisas") or "")
            pen = write(self.tmp / "PEN" / "Makefile", "all:").parent  # uma pen USB escolhida diretamente
            with mock.patch("os.path.ismount", side_effect=lambda q: os.path.normpath(q) == str(pen)):
                self.assertIsNone(check_root_protected(pen))



def _tsv(words: list[tuple[str, float]]) -> str:
    """Saída TSV do Tesseract com estas palavras (texto e confiança)."""
    rows = ["level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
            "1\t1\t0\t0\t0\t0\t0\t0\t100\t100\t-1\t"]
    rows += [f"5\t1\t1\t1\t1\t{i}\t0\t0\t10\t10\t{conf}\t{word}" for i, (word, conf) in enumerate(words, 1)]
    return "\n".join(rows) + "\n"


class OcrLanguageTests(unittest.TestCase):
    """O OCR lê em português e só lê noutro idioma quando o texto mostra que é desse idioma."""

    PT = "Contrato de arrendamento entre o senhorio e a arrendatária, com renda paga ao dia 8 pela conta do banco"
    ES = "Contrato de arrendamiento entre el señor y la señora, con los pagos del mes y las cuentas del banco"

    def setUp(self):
        from arruma.core import extract
        self.extract = extract
        self.calls: list[list[str]] = []

    def run_ocr(self, installed: list[str], readings: dict[str, str]) -> str:
        def fake_run(cmd, timeout):
            self.calls.append(cmd)
            if cmd[1:] == ["--list-langs"]:
                return "List of available languages in \"/x\" (%d):\n" % len(installed) + "\n".join(installed) + "\n"
            return readings.get(cmd[cmd.index("-l") + 1], "")
        with mock.patch.object(self.extract, "find_tool", return_value="tesseract"), \
                mock.patch.object(self.extract, "run_quiet", side_effect=fake_run):
            return self.extract._ocr_image("tesseract", "p.png", 2000)

    def reads(self) -> list[str]:
        return [c[c.index("-l") + 1] for c in self.calls if "-l" in c]

    def test_tsv_text_and_confidence(self):
        text, confidence = self.extract._tsv_reading(_tsv([("Contrato", 96.0), ("de", 90.0)]))
        self.assertEqual(text, "Contrato de")
        self.assertAlmostEqual(confidence, 93.0)
        self.assertEqual(self.extract._tsv_reading(""), ("", 0.0))

    def test_portuguese_text_is_read_once_even_with_low_confidence(self):
        # Numa fotocópia, outro idioma pode ter mais confiança por décimas: não conta.
        words = [(w, 85.0) for w in self.PT.split()]
        text = self.run_ocr(["deu", "eng", "fra", "ita", "osd", "por", "spa"],
                            {"por+eng": _tsv(words), "fra+eng": _tsv([(w, 86.0) for w in self.PT.split()])})
        self.assertEqual(text, self.PT)
        self.assertEqual(self.reads(), ["por+eng"])

    def test_spanish_text_is_read_again_in_spanish(self):
        read_as_portuguese = self.ES.replace("señor", "senor").replace("señora", "senora")
        text = self.run_ocr(["eng", "osd", "por", "spa", "fra"], {
            "por+eng": _tsv([(w, 89.0) for w in read_as_portuguese.split()]),
            "spa+eng": _tsv([(w, 96.0) for w in self.ES.split()]),
        })
        self.assertEqual(text, self.ES)
        self.assertEqual(self.reads(), ["por+eng", "spa+eng"])

    def test_foreign_reading_is_kept_only_if_surer(self):
        text = self.run_ocr(["eng", "por", "spa"], {
            "por+eng": _tsv([(w, 90.0) for w in self.ES.split()]),
            "spa+eng": _tsv([(w, 80.0) for w in self.ES.replace("señor", "sefior").split()]),
        })
        self.assertEqual(text, self.ES)  # a leitura em português
        self.assertEqual(self.reads(), ["por+eng", "spa+eng"])

    def test_portuguese_receipt_with_italian_dishes_is_read_once(self):
        recibo = ("FATURA SIMPLIFICADA Trattoria Da Marco Rua das Flores Lisboa Spaghetti alla carbonara "
                  "Gnocchi di patate al pesto Tiramisù della casa Água das Pedras IVA incluído "
                  "Obrigado pela preferência")
        self.run_ocr(["eng", "ita", "por"], {"por+eng": _tsv([(w, 93.0) for w in recibo.split()]),
                                              "ita+eng": _tsv([(w, 94.0) for w in recibo.split()])})
        self.assertEqual(self.reads(), ["por+eng"])

    def test_language_not_installed_is_not_tried(self):
        self.run_ocr(["eng", "por", "fra"], {"por+eng": _tsv([(w, 89.0) for w in self.ES.split()])})
        self.assertEqual(self.reads(), ["por+eng"])

    def test_language_detection(self):
        guess = self.extract._foreign_language
        self.assertIsNone(guess(self.PT, ["spa", "fra", "deu", "ita"]))
        self.assertEqual(guess(self.ES, ["spa", "fra", "deu", "ita"]), "spa")
        self.assertEqual(guess("Die Miete ist bis zum dritten Werktag auf das Konto des Vermieters mit der Kaution", ["spa", "deu"]), "deu")
        self.assertEqual(guess("Le loyer est fixé à 720 euros, payable avant le cinq de chaque mois par virement sur le compte", ["fra", "ita"]), "fra")
        self.assertEqual(guess("Il canone mensile è stabilito in 690 euro, da pagare entro il giorno cinque di ogni mese per bonifico della banca", ["ita", "spa"]), "ita")
        self.assertIsNone(guess("1234 56,78 € 2025-03-01", ["spa"]))

    def test_only_english_installed(self):
        text = self.run_ocr(["eng", "osd"], {"eng": _tsv([("Invoice", 92.0)])})
        self.assertEqual(text, "Invoice")

    def test_unknown_languages_fall_back_to_portuguese_and_english(self):
        text = self.run_ocr([], {"por+eng": "Fatura de teste"})
        self.assertEqual(text, "Fatura de teste")

    @unittest.skipUnless(shutil.which("tesseract"), "sem o Tesseract")
    def test_real_tesseract_reads_spanish_accents(self):
        from arruma.core import extract
        if not {"por", "spa"} <= set(extract._tesseract_languages(shutil.which("tesseract"))):
            self.skipTest("sem os idiomas português e espanhol no Tesseract")
        try:
            from PIL import Image, ImageDraw, ImageFont
            font = ImageFont.truetype("DejaVuSerif.ttf", 30)
        except (ImportError, OSError):
            self.skipTest("sem o Pillow ou a letra DejaVu")
        lines = ["En Logroño, a 12 de mayo de 2025, el señor", "Íñigo Muñoz Peña y la señora Begoña Núñez",
                 "acuerdan el alquiler del piso de la calle Mayor."]
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "es.png"
            img = Image.new("L", (1240, 380), 255)
            for i, line in enumerate(lines):
                ImageDraw.Draw(img).text((60, 60 + i * 90), line, font=font, fill=0)
            img.save(image)
            text = extract._ocr_image(shutil.which("tesseract"), str(image), 2000)
        for word in ("Logroño", "señor", "Muñoz", "Begoña"):
            self.assertIn(word, text)

if __name__ == "__main__":
    unittest.main()
