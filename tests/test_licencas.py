# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes do inventário de licenças de terceiros (packaging/licencas/terceiros.py).

Usam instalações simuladas do MSYS2 e do Homebrew, por isso correm em qualquer sistema."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "packaging" / "licencas"))

import terceiros  # noqa: E402


def escrever(caminho: Path, texto: str = "x") -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto, encoding="utf-8")
    return caminho


def pacote_msys2(raiz: Path, nome: str, versao: str, licencas: list[str], ficheiros: list[str],
                 base: str | None = None, url: str = "https://exemplo.org") -> None:
    pasta = raiz / "var" / "lib" / "pacman" / "local" / f"{nome}-{versao}"
    desc = [f"%NAME%\n{nome}\n", f"%VERSION%\n{versao}\n", f"%URL%\n{url}\n", "%LICENSE%\n" + "\n".join(licencas) + "\n"]
    if base:
        desc.append(f"%BASE%\n{base}\n")
    escrever(pasta / "desc", "\n".join(desc))
    escrever(pasta / "files", "%FILES%\n" + "\n".join(["ucrt64/", "ucrt64/bin/"] + ficheiros) + "\n")
    for f in ficheiros:
        escrever(raiz / f, f"conteúdo de {f}")


class LicenseFieldTests(unittest.TestCase):
    def test_msys2_license_values(self):
        self.assertEqual(terceiros.licenca_msys2(["spdx:LGPL-2.1-or-later"]), "LGPL-2.1-or-later")
        self.assertEqual(terceiros.licenca_msys2(["spdx:MIT", "spdx:Apache-2.0"]), "MIT OR Apache-2.0")
        self.assertEqual(terceiros.licenca_msys2(["spdx:GPL-2.0-or-later OR FTL"]), "GPL-2.0-or-later OR FTL")
        self.assertEqual(terceiros.licenca_msys2(["spdx:MIT,"]), "MIT")
        self.assertEqual(terceiros.licenca_msys2(["spdx:LGPL-2.1-or-later", "documentation:spdx:GPL-3.0"]),
                         "LGPL-2.1-or-later")
        self.assertEqual(terceiros.licenca_msys2(["custom"]), "custom")

    def test_standard_texts(self):
        self.assertEqual(terceiros._textos_padrao("LGPL-3.0-or-later OR CC-BY-SA-3.0"), ["LGPL-3.0.txt", "GPL-3.0.txt"])
        self.assertIn("LGPL-2.1.txt", terceiros._textos_padrao("LGPL-2.1-only OR MPL-1.1"))
        self.assertEqual(terceiros._textos_padrao("MIT"), [])
        self.assertIn("LGPL-2.0.txt", terceiros._textos_padrao("LGPL-2.0-only"))
        self.assertNotIn("LGPL-2.1.txt", terceiros._textos_padrao("LGPL-2.0-or-later"))
        for nome in ("GPL-2.0.txt", "LGPL-2.0.txt", "LGPL-2.1.txt", "LGPL-3.0.txt", "MPL-2.0.txt", "Apache-2.0.txt"):
            self.assertTrue((terceiros.TEXTOS_PADRAO / nome).is_file(), nome)


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arruma-licencas-")).resolve()
        self.projeto = self.tmp / "projeto"
        shutil.copyfile(RAIZ / "LICENSE", escrever(self.projeto / "LICENSE"))
        self.trabalho = self.projeto / "build" / "arruma"
        self.trabalho.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_collected_files_skip_links_and_missing(self):
        real = escrever(self.tmp / "a.dll")
        lista = [("a.dll", str(real), "BINARY"), ("b", "x/y", "SYMLINK"), ("ns", "-", "PYMODULE"),
                 ("c", str(self.tmp / "nao-existe.dll"), "BINARY"), ("a2.dll", str(real), "BINARY")]
        self.assertEqual(terceiros.ficheiros_recolhidos(lista), [(str(real), "BINARY")])

    def test_msys2_inventory_and_notices(self):
        msys = self.tmp / "msys64"
        pacote_msys2(msys, "mingw-w64-ucrt-x86_64-gtk3", "3.24.52-1", ["spdx:LGPL-2.1-or-later"],
                     ["ucrt64/bin/libgtk-3-0.dll", "ucrt64/share/licenses/gtk3/COPYING"], base="mingw-w64-gtk3")
        pacote_msys2(msys, "mingw-w64-ucrt-x86_64-poppler", "26.08.0-1", ["spdx:GPL-2.0-or-later"],
                     ["ucrt64/bin/pdftotext.exe"], base="mingw-w64-poppler")
        pacote_msys2(msys, "mingw-w64-ucrt-x86_64-gdk-pixbuf2", "2.44.8-1", ["spdx:LGPL-2.1-or-later"],
                     ["ucrt64/bin/libgdk_pixbuf-2.0-0.dll"], base="mingw-w64-gdk-pixbuf2")
        r = terceiros.Msys2(str(msys))
        dll = str(msys / "ucrt64" / "bin" / "libgtk-3-0.dll")
        self.assertEqual(r.pacote_de(dll), "mingw-w64-ucrt-x86_64-gtk3")
        if os.name == "nt":  # no Windows, maiúsculas e minúsculas são o mesmo ficheiro
            self.assertEqual(r.pacote_de(dll.upper()), "mingw-w64-ucrt-x86_64-gtk3")

        cache = escrever(self.trabalho / "loaders.cache")
        proprio = escrever(self.projeto / "arruma" / "core" / "x.py")
        estranho = escrever(self.tmp / "outro" / "misterio.dll")
        analise = SimpleNamespace(
            binaries=[("libgtk-3-0.dll", dll, "BINARY"),
                      ("pdftotext.exe", str(msys / "ucrt64" / "bin" / "pdftotext.exe"), "BINARY"),
                      ("misterio.dll", str(estranho), "BINARY")],
            datas=[("lib/gdk-pixbuf/loaders.cache", str(cache), "DATA")],
            pure=[("arruma.core.x", str(proprio), "PYMODULE")],
            scripts=[])
        inv = terceiros.Inventario([r], self.projeto, self.trabalho)
        for caminho, tipo in terceiros.ficheiros_recolhidos(analise.binaries, analise.datas, analise.pure):
            inv.atribuir(caminho, tipo)
        self.assertEqual(inv.desconhecidos, [(str(estranho), "BINARY")])
        comps = inv.componentes()
        gtk = comps["msys2:mingw-w64-ucrt-x86_64-gtk3"]
        self.assertEqual(gtk.licenca, "LGPL-2.0-or-later")  # corrigida pelo COPYING do projeto
        self.assertEqual(gtk.fontes[0]["url"],
                         "https://repo.msys2.org/mingw/sources/mingw-w64-gtk3-3.24.52-1.src.tar.zst")
        self.assertEqual(comps["msys2:mingw-w64-ucrt-x86_64-poppler"].licenca,
                         "(GPL-2.0-only OR GPL-3.0-only) AND GPL-2.0-or-later")
        self.assertEqual(comps["msys2:mingw-w64-ucrt-x86_64-gdk-pixbuf2"].ficheiros, 1)  # o loaders.cache

        destino = self.trabalho / "licencas"
        entradas = terceiros.escrever(comps, destino, "0.2.0", "windows", self.projeto)
        destinos = [e[0] for e in entradas]
        self.assertIn("licencas/LEIA-ME.txt", destinos)
        self.assertIn("licencas/Arruma/LICENSE", destinos)
        self.assertIn("licencas/gtk3/COPYING", destinos)
        self.assertIn("licencas/textos-padrao/GPL-3.0.txt", destinos)  # Poppler
        self.assertIn("licencas/textos-padrao/GPL-2.0.txt", destinos)
        self.assertEqual(len({d.casefold() for d in destinos}), len(destinos))
        self.assertTrue(all(e[2] == "DATA" and Path(e[1]).is_file() for e in entradas))
        leia = (destino / "LEIA-ME.txt").read_text(encoding="utf-8")
        self.assertIn("gtk3 3.24.52-1", leia)
        self.assertIn("três anos", leia)
        self.assertNotIn("—", leia)
        dados = json.loads((destino / "componentes.json").read_text(encoding="utf-8"))
        self.assertEqual(dados["sistema"], "windows")
        self.assertEqual(len(dados["componentes"]), 3)

    def test_homebrew_kegs_and_generated_typelibs(self):
        prefixo = self.tmp / "brew"
        cellar = prefixo / "Cellar"
        keg = cellar / "gtk+3" / "3.24.52_1"
        dylib = escrever(keg / "lib" / "libgtk-3.0.dylib")
        escrever(keg / "COPYING", "GNU LIBRARY GENERAL PUBLIC LICENSE")
        escrever(keg / "README.md")
        escrever(keg / ".brew" / "gtk+3.rb", "class Gtk3 < Formula\nend\n")
        escrever(keg / "sbom.spdx.json", json.dumps({"packages": [
            {"SPDXID": "SPDXRef-Archive-gtk+3-src",
             "downloadLocation": "https://download.gnome.org/sources/gtk/3.24/gtk-3.24.52.tar.xz"},
            {"SPDXID": "SPDXRef-Patch-gtk+3-0", "downloadLocation": "https://example.org/fix.patch"},
            {"SPDXID": "SPDXRef-Package-SPDXRef-glib-2.90", "downloadLocation": "https://ignorar.org/x"}]}))
        gir = escrever(keg / "share" / "gir-1.0" / "Gtk-3.0.gir")
        ligacao = prefixo / "share" / "gir-1.0" / "Gtk-3.0.gir"
        ligacao.parent.mkdir(parents=True)
        try:
            ligacao.symlink_to(gir)
        except (OSError, NotImplementedError):
            self.skipTest("este sistema não permite ligações simbólicas")
        typelib = escrever(self.trabalho / "Gtk-3.0.typelib")

        r = terceiros.Homebrew(str(prefixo), str(cellar))
        self.assertEqual(r.pacote_de(str(dylib)), "gtk+3/3.24.52_1")
        self.assertEqual(r.pacote_de(str(typelib)), "gtk+3/3.24.52_1")
        self.assertEqual(r.pacote_por_nome("gtk+3"), "gtk+3/3.24.52_1")
        r.carregar_info = lambda nomes: r.info.update({"gtk+3": {
            "license": "LGPL-2.0-or-later", "homepage": "https://gtk.org/", "tap_git_head": "abc123",
            "ruby_source_path": "Formula/g/gtk+3.rb", "patches": [{"file": "Patches/gtk/x.diff"}]}})
        inv = terceiros.Inventario([r], self.projeto, self.trabalho)
        inv.atribuir(str(dylib), "BINARY")
        inv.atribuir(str(typelib), "DATA")
        self.assertEqual(inv.desconhecidos, [])
        comp = inv.componentes()["homebrew:gtk+3/3.24.52_1"]
        self.assertEqual(comp.ficheiros, 2)
        urls = [f["url"] for f in comp.fontes]
        self.assertEqual(urls[:2], ["https://download.gnome.org/sources/gtk/3.24/gtk-3.24.52.tar.xz",
                                    "https://example.org/fix.patch"])
        self.assertIn("https://raw.githubusercontent.com/Homebrew/homebrew-core/abc123/Formula/g/gtk+3.rb", urls)
        self.assertIn("https://raw.githubusercontent.com/Homebrew/homebrew-core/abc123/Patches/gtk/x.diff", urls)
        self.assertNotIn("https://ignorar.org/x", urls)
        nomes = sorted(Path(t).name for t in comp.textos)
        self.assertEqual(nomes, ["COPYING", "gtk+3.rb"])

    @unittest.skipUnless(__import__("importlib").util.find_spec("mutagen"), "precisa do mutagen")
    def test_pip_distribution(self):
        import mutagen
        r = terceiros.Pip()
        chave = r.pacote_de(mutagen.__file__)
        if chave is None:
            self.skipTest("o mutagen deste sistema não traz a lista de ficheiros (RECORD)")
        comp = r.componente(chave)
        self.assertIn("GPL", comp.licenca)
        self.assertEqual(comp.fontes[0]["tipo"], "pypi")

    def test_pip_finds_dist_info_next_to_the_real_file(self):
        tmp = Path(tempfile.mkdtemp(prefix="arruma-site-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        site = tmp / "Cellar" / "pydantic" / "2.13.5" / "lib" / "python3.14" / "site-packages"
        modulo = escrever(site / "typing_extensions.py", "# módulo")
        info = site / "typing_extensions-4.15.0.dist-info"
        escrever(info / "METADATA", "Metadata-Version: 2.4\nName: typing_extensions\nVersion: 4.15.0\n"
                                    "License-Expression: PSF-2.0\nLicense-File: LICENSE\n")
        escrever(info / "licenses" / "LICENSE", "A. HISTORY OF THE SOFTWARE")
        escrever(info / "RECORD", "typing_extensions.py,,\ntyping_extensions-4.15.0.dist-info/METADATA,,\n"
                                  "typing_extensions-4.15.0.dist-info/licenses/LICENSE,,\n")
        r = terceiros.Pip()
        chave = r.pacote_de(str(modulo))
        self.assertEqual(chave, "typing_extensions/4.15.0")
        comp = r.componente(chave)
        self.assertEqual(comp.licenca, "PSF-2.0")
        self.assertEqual([Path(t).name for t in comp.textos], ["LICENSE"])


class ChoiceAndNoticeTests(unittest.TestCase):
    def test_license_choice_is_gpl3_compatible(self):
        casos = {
            "(GPL-2.0-only OR GPL-3.0-only) AND GPL-2.0-or-later": "GPL-3.0-only AND GPL-2.0-or-later",
            "LGPL-2.1-only OR MPL-1.1": "LGPL-2.1-only",
            "(BSD-3-Clause OR GPL-2.0-only) AND BSD-2-Clause AND MIT": "BSD-3-Clause AND BSD-2-Clause AND MIT",
            "LGPL-3.0-or-later OR CC-BY-SA-3.0": "LGPL-3.0-or-later",
            "FTL OR GPL-2.0-or-later": "FTL",
            "GPL-2.0-or-later WITH Bootloader-exception AND Apache-2.0":
                "GPL-2.0-or-later WITH Bootloader-exception AND Apache-2.0",
        }
        for licenca, esperada in casos.items():
            self.assertEqual(terceiros.escolher_licenca(licenca), esperada, licenca)
        for comp, licenca in terceiros.LICENCAS_CORRIGIDAS.items():
            self.assertNotRegex(terceiros.escolher_licenca(licenca), r"(?<!L)GPL-2\.0-only", comp)

    def test_test_build_and_release_notices(self):
        tmp = Path(tempfile.mkdtemp(prefix="arruma-aviso-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        projeto = tmp / "projeto"
        shutil.copyfile(RAIZ / "LICENSE", escrever(projeto / "LICENSE"))
        comp = terceiros.Componente(chave="msys2:x", nome="cairo", versao="1.18.6-2",
                                    licenca="LGPL-2.1-only OR MPL-1.1", origem="msys2")
        terceiros.escrever({"msys2:x": comp}, tmp / "a", "0.2.0", "windows", projeto,
                           "commit 2feff1e49b17, versão de teste", False)
        teste = (tmp / "a" / "LEIA-ME.txt").read_text(encoding="utf-8")
        self.assertIn("versão de teste", teste)
        self.assertIn("Distribuído nos termos de: LGPL-2.1-only", teste)
        terceiros.escrever({"msys2:x": comp}, tmp / "b", "0.2.0", "macos", projeto, "etiqueta v0.2.0", True)
        publicada = (tmp / "b" / "LEIA-ME.txt").read_text(encoding="utf-8")
        self.assertIn("Esta versão está publicada", publicada)
        self.assertIn("reescreve os caminhos das bibliotecas", publicada)
        self.assertEqual(json.loads((tmp / "b" / "componentes.json").read_text(encoding="utf-8"))["publicada"], True)

    def test_compiled_schemas_credit_every_package(self):
        tmp = Path(tempfile.mkdtemp(prefix="arruma-esquemas-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        prefixo, cellar = tmp / "brew", tmp / "brew" / "Cellar"
        escrever(cellar / "glib" / "2.88.3" / "lib" / "libglib-2.0.dylib")
        fontes = {"org.gtk.Settings.FileChooser.gschema.xml": "gtk+3/3.24.52",
                  "org.gnome.desktop.a11y.gschema.xml": "gsettings-desktop-schemas/50.1"}
        trabalho = tmp / "build"
        compilado = escrever(trabalho / "_pyi_gschema_compilation" / "gschemas.compiled")
        for nome, keg in fontes.items():
            original = escrever(cellar / keg / "share" / "glib-2.0" / "schemas" / nome)
            ligacao = prefixo / "share" / "glib-2.0" / "schemas" / nome
            ligacao.parent.mkdir(parents=True, exist_ok=True)
            try:
                ligacao.symlink_to(original)
            except (OSError, NotImplementedError):
                self.skipTest("este sistema não permite ligações simbólicas")
            escrever(compilado.parent / nome)
        r = terceiros.Homebrew(str(prefixo), str(cellar))
        inv = terceiros.Inventario([r], tmp / "projeto", trabalho)
        inv.atribuir(str(compilado), "DATA")
        self.assertEqual(inv.desconhecidos, [])
        contados = {chave for (_i, chave) in inv.contagem}
        self.assertEqual(contados, {"glib/2.88.3", "gtk+3/3.24.52", "gsettings-desktop-schemas/50.1"})


class SourceDownloadTests(unittest.TestCase):
    def test_download_writes_checkable_sums(self):
        import hashlib
        import tarfile
        import fontes
        tmp = Path(tempfile.mkdtemp(prefix="arruma-fontes-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        origem = escrever(tmp / "origem" / "exemplo-1.0.tar.gz", "conteúdo")
        url = origem.as_uri()
        lista = {"windows": [("exemplo 1.0", url), ("falta 1", (tmp / "nao-existe.tar").as_uri())]}
        from unittest import mock
        with mock.patch.object(fontes.time, "sleep"):
            falhas = fontes.descarregar(lista, tmp / "saida", "0.2.0")
        self.assertEqual(falhas, 1)
        somas = (tmp / "saida" / "fontes-windows" / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
        linhas = [l for l in somas if l and not l.startswith("#")]
        self.assertEqual(linhas, [f"{hashlib.sha256(origem.read_bytes()).hexdigest()}  exemplo-1.0.tar.gz"])
        self.assertIn(f"# exemplo 1.0; {url}", somas)
        with tarfile.open(tmp / "saida" / "Arruma-0.2.0-codigo-fonte-terceiros-windows.tar") as tar:
            self.assertIn("Arruma-0.2.0-codigo-fonte-terceiros-windows/exemplo-1.0.tar.gz", tar.getnames())
        self.assertFalse(list((tmp / "saida").rglob("*.part")))


if __name__ == "__main__":
    unittest.main()
