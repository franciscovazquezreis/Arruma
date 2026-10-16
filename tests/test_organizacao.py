"""Testes das regras de organização e da IA (com um Ollama falso). Sem interface gráfica."""

import json
import os
import shutil
import socketserver
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arruma.core import taxonomy as tx  # noqa: E402
from arruma.core.ai import clean_date, clean_title, validate_result  # noqa: E402
from arruma.core.classifier import Placement, real_tag  # noqa: E402
from arruma.core.db import Database  # noqa: E402
from arruma.core.planner import MODE_INSIDE, MODE_PERSONAL, Planner, simplify_tree  # noqa: E402
from arruma.core.scanner import scan  # noqa: E402
from arruma.core.settings import Settings  # noqa: E402


def write(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def make_docx(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f"<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
                                        "</w:body></w:document>")


class TaxonomyTests(unittest.TestCase):
    def test_labels_are_unique_and_parse_back(self):
        self.assertEqual(len(tx.CATEGORY_LABELS), len(set(tx.CATEGORY_LABELS)))
        for label in tx.CATEGORY_LABELS:
            area, sub = tx.parse_category(label)
            self.assertEqual(tx.category_label(area, sub), label)

    def test_no_ambiguous_subareas(self):
        seen = {}
        for area, subs in tx.AREAS.items():
            for sub in subs:
                self.assertNotIn(sub, seen, f"«{sub}» repete-se em {area} e {seen.get(sub)}")
                seen[sub] = area

    def test_keywords_point_to_existing_categories(self):
        for area, sub, strong, _weak in tx._KEYWORDS:
            self.assertIn(area, tx.AREAS)
            if sub:
                self.assertIn(sub, tx.AREAS[area])
            self.assertTrue(strong)

    def test_parse_is_tolerant_but_closed(self):
        self.assertEqual(tx.parse_category("financas > faturas e recibos"), ("Finanças", "Faturas e Recibos"))
        self.assertEqual(tx.parse_category("Saúde/Receitas médicas"), ("Saúde", "Receitas médicas"))
        self.assertEqual(tx.parse_category("Casa › Manutenção Eletrodomésticos"), ("Casa", ""))
        self.assertEqual(tx.parse_category("Coisas importantes"), ("Outros", ""))


class KeywordTests(unittest.TestCase):
    def area(self, name, text):
        return tx.keyword_classify(name, text)[0]

    def test_traps(self):
        self.assertEqual(self.area("ata.pdf", "ATA N.º 27 Assembleia de Condóminos, ordem de trabalhos: "
                                              "contas do condomínio e quotas"), "Casa")
        self.assertEqual(self.area("Manual_Formando_UFCD_0349.pdf", "MANUAL DO FORMANDO UFCD 0349 "
                                                                    "Módulo 1"), "Educação")
        self.assertEqual(self.area("receita.docx", "Ingredientes: bacalhau, ovos. Modo de preparação: "
                                                   "aloure a cebola"), "Lazer")
        self.assertEqual(self.area("cc.pdf", "CARTÃO DE CIDADÃO Nacionalidade PRT N.º de utente de saúde "
                                             "123"), "Pessoal")
        self.assertEqual(self.area("livro.pdf", "ISBN 978-972 Todos os direitos reservados. Capítulo 1"),
                         "Livros e Leituras")

    def test_single_generic_word_does_not_decide(self):
        for text in ("Segue em anexo o envio pedido.", "Fica a consulta marcada.", "Ver o manual."):
            self.assertEqual(self.area("nota.txt", text), "Outros", text)


class ValidationTests(unittest.TestCase):
    TEXT = "LusoEnergia, S.A. FATURA N.º FT 2025/184532 Data de emissão: 12-03-2025 Energia ativa"

    def test_title_must_be_grounded(self):
        self.assertEqual(clean_title("Fatura LusoEnergia eletricidade", self.TEXT, "scan_001.pdf"),
                         "Fatura LusoEnergia eletricidade")
        # Empresa que não aparece no documento: título recusado (nada de nomes inventados).
        self.assertEqual(clean_title("Fatura EDP eletricidade", self.TEXT, "scan_001.pdf"), "")
        self.assertEqual(clean_title("Fatura Águas do Planalto", self.TEXT, "scan_001.pdf"), "")

    def test_title_cleanup(self):
        self.assertEqual(clean_title("Documento"), "")
        self.assertEqual(clean_title("Documento digitalizado"), "")
        self.assertEqual(clean_title("Fatura EDP março.pdf"), "Fatura EDP março")
        self.assertEqual(clean_title("Fatura 2025-03-12 EDP"), "Fatura EDP")
        self.assertEqual(clean_title("CONTRATO DE ARRENDAMENTO HABITACIONAL"), "Contrato de Arrendamento Habitacional")
        self.assertEqual(clean_title("ATA Assembleia de Condóminos"), "Ata Assembleia de Condóminos")

    def test_date_must_be_grounded(self):
        self.assertEqual(clean_date("2025-03-12", self.TEXT), "2025-03-12")
        # Só o mês está escrito: o dia não se inventa.
        self.assertEqual(clean_date("2025-01-31", "Recibo de vencimento de janeiro de 2025"), "2025-01")
        self.assertEqual(clean_date("2025-02-20", "Lourinhã, 20 de fevereiro de 2025"), "2025-02-20")
        self.assertEqual(clean_date("2023-03-12", self.TEXT), "")
        self.assertEqual(clean_date("2025-02-30"), "")
        self.assertEqual(clean_date("12/03/2025"), "")

    def test_validate_never_leaves_taxonomy(self):
        r = validate_result({"categoria": "Educação › Trabalho", "titulo": "Curriculum Vitae",
                             "data": "", "confianca": 2})
        self.assertEqual((r["area"], r["subarea"]), ("Educação", ""))
        self.assertEqual(r["confianca"], 1.0)

    def test_placeholder_tags(self):
        self.assertEqual(real_tag("Unknown Artist", artist=True), "")
        self.assertEqual(real_tag("Track 02"), "")
        self.assertEqual(real_tag("Various Artists", artist=True), "Vários artistas")
        self.assertEqual(real_tag("Madredeus", artist=True), "Madredeus")


class SimplifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arruma-teste-")).resolve()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def doc(self, area, sub):
        return Placement("documents", (area, sub), optional_levels=1)

    def test_small_subareas_collapse(self):
        base = str(self.tmp)
        few = [self.doc("Finanças", "Banco") for _ in range(2)]
        many = [self.doc("Finanças", "Faturas e Recibos") for _ in range(3)]
        simplify_tree([(p, base) for p in few + many])
        self.assertTrue(all(p.rel == ("Finanças",) for p in few))
        self.assertTrue(all(p.rel == ("Finanças", "Faturas e Recibos") for p in many))

    def test_existing_subarea_is_reused(self):
        (self.tmp / "Finanças" / "Banco").mkdir(parents=True)
        p = self.doc("Finanças", "Banco")
        simplify_tree([(p, str(self.tmp))])
        self.assertEqual(p.rel, ("Finanças", "Banco"))

    def test_photo_months_and_years(self):
        def photo(year, month):
            return Placement("pictures", ("Fotografias", year, f"{year}-{month} Mês"), month_level=True,
                             year_level=True)
        base = str(self.tmp)
        lots = [photo("2024", "08") for _ in range(45)]
        few = [photo("2023", "12") for _ in range(2)]
        simplify_tree([(p, base) for p in lots + few])
        self.assertEqual(lots[0].rel, ("Fotografias", "2024", "2024-08 Mês"))
        self.assertEqual(few[0].rel, ("Fotografias", "2023"))  # anos coerentes: há outro ano grande
        lonely = [photo("2022", "01")]
        simplify_tree([(p, base) for p in lonely])
        self.assertEqual(lonely[0].rel, ("Fotografias",))


class FakeOllama:
    """Servidor que imita o Ollama e se porta como um modelo fraco."""

    def __init__(self, answers: dict[str, dict]):
        self.answers = answers
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, payload):
                data = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/api/version":
                    self._send({"version": "0.99-teste"})
                else:
                    self._send({"models": [{"name": "qwen2.5:3b"}]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                question = body["messages"][-1]["content"]
                name = question.splitlines()[0].split(": ", 1)[1]
                answer = outer.answers.get(name, {"titulo": "", "categoria": "Outros", "data": "", "confianca": 0.2})
                self._send({"message": {"role": "assistant", "content": json.dumps(answer)}})

        class Server(ThreadingHTTPServer):
            def server_bind(self):  # sem socket.getfqdn(): no macOS a consulta de DNS demora 30 s
                socketserver.TCPServer.server_bind(self)
                self.server_name, self.server_port = self.server_address[:2]

        self.server = Server(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


class AIPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arruma-teste-")).resolve()
        self.root = self.tmp / "Bagunça"
        write(self.root / "scan_001.txt", "LusoEnergia FATURA N.º 1 Data de emissão: 12-03-2025 Total a pagar 59,77")
        write(self.root / "doc2025.txt", "RECIBO DE VENCIMENTO Janeiro de 2025 Vencimento base 1.250,00")
        make_docx(self.root / "CV.docx", "Curriculum Vitae Ana Ribeiro Experiência profissional")
        write(self.root / "garantia.txt", "Certificado de garantia do computador portátil Nexus 15")
        self.fake = FakeOllama({
            "scan_001.txt": {"titulo": "Fatura LusoEnergia eletricidade", "categoria": "Finanças › Faturas e Recibos",
                             "data": "2025-03-12", "confianca": 0.9},
            # Respostas típicas de um modelo fraco sem esquema: categoria inventada e empresa inventada.
            "doc2025.txt": {"titulo": "Fatura Construções Oeste", "categoria": "Casa › Obras e Manutenção",
                            "data": "2025-01-31", "confianca": 0.7},
            "CV.docx": {"titulo": "Curriculum vitae Ana Ribeiro", "categoria": "Educação › Trabalho",
                        "data": "", "confianca": 0.6},
            "garantia.txt": {"titulo": "Garantia portátil Nexus", "categoria": "Veículos › Manutenção",
                             "data": "", "confianca": 0.4},
        })
        self.settings = Settings(use_ai=True, ollama_url=self.fake.url, model="qwen2.5:3b")
        self.db = Database(self.tmp / "teste.db")

    def tearDown(self):
        self.fake.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self):
        return Planner(scan(self.root), self.settings, MODE_INSIDE, db=self.db).build()

    def test_one_document_per_request_with_closed_schema(self):
        plan = self.build()
        self.assertEqual(plan.ai_count, 4)
        self.assertEqual(len(self.fake.requests), 4)
        for body in self.fake.requests:
            self.assertEqual(body["format"]["properties"]["categoria"]["enum"], tx.CATEGORY_LABELS)
            self.assertEqual(body["messages"][-1]["content"].count("Ficheiro:"), 1)
        # Segunda vez: tudo vem da cache.
        self.build()
        self.assertEqual(len(self.fake.requests), 4)

    def test_weak_model_cannot_create_odd_folders(self):
        plan = self.build()
        by_name = {os.path.basename(a.src): a for a in plan.actions}
        for a in plan.actions:
            parts = Path(a.dst).relative_to(self.root).parts
            if parts[0] == "Documentos" and len(parts) > 3:
                self.assertIn(parts[2], tx.AREAS[parts[1]], a.dst)
        self.assertTrue(by_name["scan_001.txt"].dst.endswith("2025-03-12 Fatura LusoEnergia eletricidade.txt"))
        # Título com empresa que não está no texto: o nome não muda.
        self.assertEqual(os.path.basename(by_name["doc2025.txt"].dst), "doc2025.txt")
        # A IA contraria pistas fortes no texto («recibo de vencimento»): prevalecem as palavras-chave.
        self.assertIn("/Documentos/Finanças/", by_name["doc2025.txt"].dst)
        self.assertEqual(by_name["doc2025.txt"].source, "palavras-chave")
        # A IA contraria pistas fracas: fica onde a IA disse, mas marcado para rever.
        self.assertEqual(Path(by_name["garantia.txt"].dst).parent, self.root / "Documentos" / "Veículos")
        # Modelo inventou a subpasta «Educação › Trabalho»; o CV tem pistas fortes de Pessoal.
        self.assertEqual(Path(by_name["CV.docx"].dst).parent, self.root / "Documentos" / "Pessoal")
        self.assertLess(by_name["garantia.txt"].confidence, 0.55)


class StructureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arruma-teste-")).resolve()
        self.root = self.tmp / "Trabalho"
        write(self.root / "Clientes" / "Cliente A" / "proposta.txt", "Proposta comercial para o Cliente A")
        write(self.root / "Faturação" / "fatura_1.txt", "FATURA n.º 1 Total a pagar 100 EUR")
        write(self.root / "solto.txt", "FATURA n.º 7 Total a pagar 30 EUR")
        self.settings = Settings(use_ai=False)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_inside_mode_keeps_named_subfolders(self):
        plan = Planner(scan(self.root), self.settings, MODE_INSIDE).build()
        moved = {os.path.relpath(a.src, self.root).replace(os.sep, "/") for a in plan.actions}
        self.assertEqual(moved, {"solto.txt"})
        kept = {os.path.basename(p) for p, _ in plan.respected}
        self.assertEqual(kept, {"Clientes", "Faturação"})

    def test_personal_mode_moves_whole_folders(self):
        home = self.tmp / "casa"
        dirs = {k: home / v for k, v in {"DESKTOP": "Secretária", "DOWNLOAD": "Transferências",
                                          "DOCUMENTS": "Documentos", "MUSIC": "Música", "PICTURES": "Imagens",
                                          "VIDEOS": "Vídeos", "TEMPLATES": "Modelos",
                                          "PUBLICSHARE": "Público"}.items()}
        with mock.patch("arruma.core.planner.user_dirs", return_value=dirs):
            plan = Planner(scan(self.root), self.settings, MODE_PERSONAL).build()
        units = {os.path.basename(a.src): a for a in plan.actions if a.op == "move_dir"}
        self.assertEqual(set(units), {"Clientes", "Faturação"})
        self.assertTrue(units["Faturação"].dst.startswith(str(home / "Documentos")))


if __name__ == "__main__":
    unittest.main()
