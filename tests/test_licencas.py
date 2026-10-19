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
        self.assertIn("/issues", leia)
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
        # Como no Homebrew: sem RECORD, só METADATA e as licenças.
        outro = escrever(site / "cryptography" / "hazmat" / "_oid.py", "# módulo")
        escrever(site / "cryptography-50.0.1.dist-info" / "METADATA",
                 "Metadata-Version: 2.4\nName: cryptography\nVersion: 50.0.1\nLicense-Expression: Apache-2.0 OR BSD-3-Clause\n")
        r = terceiros.Pip()
        self.assertEqual(r.pacote_de(str(outro)), "cryptography/50.0.1")
        self.assertIsNone(r.pacote_de(str(escrever(site / "gi" / "__init__.py"))))  # fica para o Homebrew
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

    def test_license_choice_follows_spdx_precedence(self):
        casos = {
            # AND liga mais do que OR: «A AND B OR C» é «(A AND B) OR C».
            "GPL-2.0-only AND MIT OR Apache-2.0": "Apache-2.0",
            "MIT OR GPL-2.0-only AND BSD-3-Clause": "MIT",
            # Identificadores antigos: GPL-2.0 é -only; «+» é «ou posterior».
            "GPL-2.0 OR MIT": "MIT",
            "GPL-2.0+ OR MPL-1.1": "GPL-2.0+",
            "CC-BY-SA-3.0 OR LGPL-3.0-or-later": "LGPL-3.0-or-later",
            "OpenSSL OR MIT": "MIT",
            "MIT OR MPL-2.0 OR LGPL-2.1-or-later OR GPL-2.0-or-later": "MIT",
            "GPL-2.0-only": "GPL-2.0-only",  # sem escolha fica como está
            "Artistic-1.0-Perl OR GPL-1.0-or-later": "GPL-1.0-or-later",
            "CC-BY-SA-3.0-DE OR MIT": "MIT",
            "CDDL-1.0+ OR BSD-2-Clause": "BSD-2-Clause",
            "MPL-1.1+ OR CDDL-1.0": "MPL-1.1+",  # a MPL-2.0 já é compatível
        }
        for licenca, esperada in casos.items():
            self.assertEqual(terceiros.escolher_licenca(licenca), esperada, licenca)
        with self.assertRaises(ValueError):
            terceiros.escolher_licenca("GPL-2.0-only OR MPL-1.1")

    def test_incompatible_licenses_are_reported(self):
        def comp(nome, licenca):
            return terceiros.Componente(chave=nome, nome=nome, versao="1", licenca=licenca, origem="msys2")
        componentes = {c.chave: c for c in (
            comp("zstd", "(BSD-3-Clause OR GPL-2.0-only) AND BSD-2-Clause AND MIT"),
            comp("hicolor-icon-theme", "GPL-2.0-only"),  # só dados: agregado
            comp("biblioteca", "MIT AND GPL-2.0-only"),
            comp("outra", "MPL-1.1"),
            comp("sem-licenca", "não indicada"),
            comp("texto-livre", "GNU General Public License v2 (GPLv2)"),
            comp("propria", "LicenseRef-Proprietaria"),
            comp("minusculas", "gpl-2.0-only"),
        )}
        self.assertEqual(terceiros.incompativeis(componentes),
                         ["biblioteca 1 (MIT AND GPL-2.0-only)", "minusculas 1 (gpl-2.0-only)",
                          "outra 1 (MPL-1.1)", "propria 1 (LicenseRef-Proprietaria)",
                          "sem-licenca 1 (não indicada)", "texto-livre 1 (GNU General Public License v2 (GPLv2))"])
        agregado = {"h": comp("hicolor-icon-theme", "GPL-2.0-only OR MPL-1.1")}
        self.assertEqual(terceiros.incompativeis(agregado), [])
        with self.assertRaisesRegex(ValueError, "^outra 1:"):
            terceiros.escolha_do_componente(comp("outra", "GPL-2.0-only OR MPL-1.1"))

    def test_freetype_credit_year_comes_from_its_header(self):
        tmp = Path(tempfile.mkdtemp(prefix="arruma-freetype-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        texto = escrever(tmp / "ucrt64" / "share" / "licenses" / "freetype" / "FTL.TXT", "Copyright 1996-2002, 2006")
        escrever(tmp / "ucrt64" / "include" / "freetype2" / "freetype" / "freetype.h",
                 " * Copyright (C) 1996-2025 by\n")
        comp = terceiros.Componente(chave="f", nome="freetype", versao="2.15.0-1",
                                    licenca="FTL OR GPL-2.0-or-later", origem="msys2", textos=[str(texto)])
        self.assertEqual(terceiros._ano_freetype(comp), 2025)

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
        self.assertIn("não é acompanhada do código-fonte dos componentes", teste)
        self.assertIn("Distribuído nos termos de: LGPL-2.1-only", teste)
        self.assertNotIn("três anos", teste)
        execucao = "https://github.com/franciscovazquezreis/Arruma/actions/runs/1"
        terceiros.escrever({"msys2:x": comp}, tmp / "c", "0.2.0", "windows", projeto,
                           "commit 2feff1e49b17, versão de teste", False, execucao)
        com_fontes = " ".join((tmp / "c" / "LEIA-ME.txt").read_text(encoding="utf-8").split())
        self.assertIn("Esta é uma versão de teste, que não foi publicada em Releases", com_fontes)
        self.assertIn(f"no artefacto «{terceiros.ARTEFACTO_FONTES}»: {execucao}", com_fontes)
        terceiros.escrever({"msys2:x": comp}, tmp / "b", "0.2.0", "macos", projeto, "etiqueta v0.2.0", True)
        publicada = (tmp / "b" / "LEIA-ME.txt").read_text(encoding="utf-8")
        self.assertIn("Esta versão está publicada", publicada)
        self.assertIn("Arruma-0.2.0-codigo-fonte-terceiros-macos.tar", publicada)
        self.assertIn("pelo Homebrew (https://brew.sh) e pelo PyPI", " ".join(publicada.split()))
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
        pasta = "Arruma-0.2.0-codigo-fonte-terceiros-windows"
        with tarfile.open(tmp / "saida" / f"{pasta}.tar") as tar:
            self.assertIn(f"{pasta}/exemplo-1.0.tar.gz", tar.getnames())
            somas = tar.extractfile(f"{pasta}/SHA256SUMS.txt").read().decode("utf-8").splitlines()
        linhas = [l for l in somas if l and not l.startswith("#")]
        self.assertEqual(linhas, [f"{hashlib.sha256(origem.read_bytes()).hexdigest()}  exemplo-1.0.tar.gz"])
        self.assertIn(f"# exemplo 1.0; {url}", somas)
        self.assertEqual([p.name for p in (tmp / "saida").iterdir()], [f"{pasta}.tar"])  # só fica o .tar



def vendor_de_teste(raiz: Path) -> Path:
    """Pasta vendor/ como a do «cargo vendor --versioned-dirs», com três crates."""
    apache = "Apache License\nVersion 2.0, January 2004\n"
    escrever(raiz / "vendor" / "foo-1.0.0" / "Cargo.toml",
             '[package]\nname = "foo"\nversion = "1.0.0"\nlicense = "MIT OR Apache-2.0"\n\n[dependencies]\nx = "1"\n')
    escrever(raiz / "vendor" / "foo-1.0.0" / "LICENSE-MIT", "Copyright (c) 2024 Foo\nPermission is hereby granted")
    escrever(raiz / "vendor" / "foo-1.0.0" / "LICENSE-APACHE", apache)
    escrever(raiz / "vendor" / "foo-1.0.0" / "src" / "lib.rs", "// código")
    escrever(raiz / "vendor" / "foo-1.0.0" / "src" / "tabelas" / "LICENSE-UNICODE", "UNICODE LICENSE")
    escrever(raiz / "vendor" / "foo-1.0.0" / "tests" / "LICENSE", "texto de um teste")  # ignorado
    escrever(raiz / "vendor" / "bar-2.0.0" / "Cargo.toml",
             '[package]\nname = "bar"\nversion = "2.0.0"\nlicense = "MIT/Apache-2.0"\nlicense-file = "LICENSE-APACHE"\n')
    escrever(raiz / "vendor" / "bar-2.0.0" / "LICENSE-APACHE", apache)  # igual ao do foo
    escrever(raiz / "vendor" / "baz-0.1.0" / "Cargo.toml",
             '[package]\nname = "baz"\nversion = "0.1.0"\nauthors = ["Ana Exemplo"]\nlicense = "MIT"\n')  # sem texto
    return raiz


class RustCrateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="arruma-crates-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_crate_texts_are_copied_once_and_listed(self):
        import fontes
        raiz = vendor_de_teste(self.tmp / "projeto")
        destino = self.tmp / "crates"
        info = fontes.copiar_textos_crates(raiz, destino, "librsvg 2.62.3")
        self.assertEqual((info["n"], info["gerado"], info["sem_texto"]), (3, False, ["MIT"]))
        self.assertEqual(info["licencas"], ["MIT", "MIT OR Apache-2.0", "MIT/Apache-2.0"])
        textos = sorted(p.name for p in (destino / "textos").iterdir())
        self.assertEqual(len(textos), 3)  # o texto da Apache-2.0 aparece uma só vez; o dos testes não entra
        lista = (destino / "CRATES.txt").read_text(encoding="utf-8")
        self.assertIn("foo 1.0.0: MIT OR Apache-2.0", lista)
        self.assertRegex(lista, r"textos/\w+-LICENSE-UNICODE \(src/tabelas\)")
        self.assertEqual(lista.count("-LICENSE-APACHE"), 2)  # uma vez no foo e uma no bar, sem repetir no bar
        self.assertIn("baz 0.1.0: MIT (autores: Ana Exemplo)\n  o pacote não traz o texto; ver ../../textos-padrao",
                      lista)
        self.assertNotIn("não traz Cargo.lock", lista)
        self.assertEqual([p.name for p in destino.iterdir() if p.is_file()], ["CRATES.txt"])
        fontes.copiar_textos_crates(raiz, self.tmp / "gerado", "libimagequant 4.4.1", gerado=True)
        self.assertIn("não traz Cargo.lock", (self.tmp / "gerado" / "CRATES.txt").read_text(encoding="utf-8"))

    def test_license_file_through_a_symlinked_path_is_listed_once(self):
        import fontes
        real = vendor_de_teste(self.tmp / "real")
        ligacao = self.tmp / "ligacao"
        try:
            ligacao.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("este sistema não permite ligações simbólicas")
        fontes.copiar_textos_crates(ligacao, self.tmp / "crates", "x 1")
        linha_bar = [l for l in (self.tmp / "crates" / "CRATES.txt").read_text(encoding="utf-8").splitlines()
                     if l.startswith("  ") and "LICENSE-APACHE" in l]
        self.assertTrue(all(l.count("LICENSE-APACHE") == 1 for l in linha_bar), linha_bar)

    def test_crate_licenses_are_checked(self):
        self.assertEqual(terceiros.problemas_crates(
            ["MIT/Apache-2.0", "Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT", "Unicode-3.0", "Zlib"], ["MIT"]), [])
        problemas = terceiros.problemas_crates(["GPL-2.0-only", "texto livre"], ["ISC"])
        self.assertEqual(len(problemas), 3, problemas)
        self.assertIn("sem texto no pacote nem texto-padrão: ISC", problemas)

    def test_cargo_update_lines_from_msys2_recipes(self):
        import fontes
        receita = ("prepare() {\n  cargo update -p foo --precise 1.2.3\n  ${MINGW_PREFIX}/bin/cargo update -p bar\n"
                   "  cargo update\n  cargo fetch --locked\n  cargo update -p \"$x\"  # variável\n}\n")
        capturados = [c.strip() for c in fontes._CARGO_UPDATE.findall(receita)]
        self.assertEqual(capturados, ["-p foo --precise 1.2.3", "-p bar", "", '-p "$x"'])

    def test_vendoring_with_and_without_cargo_lock(self):
        import tarfile
        import fontes
        from unittest import mock
        registo = self.tmp / "cargo.log"
        falso = escrever(self.tmp / "bin" / "cargo", f"""#!/bin/sh
echo "$@" >> "{registo}"
if [ "$1" = generate-lockfile ]; then echo "# gerado" > Cargo.lock; fi
if [ "$1" = vendor ]; then mkdir -p vendor/x-1.0.0 && printf '[package]\\nname = "x"\\nversion = "1.0.0"\\nlicense = "MIT"\\n' > vendor/x-1.0.0/Cargo.toml; fi
""")
        falso.chmod(0o755)

        def arquivo(nome, com_lock):
            src = self.tmp / "src" / nome
            escrever(src / "Cargo.toml", '[package]\nname = "p"\nversion = "1.0.0"\n')
            if com_lock:
                escrever(src / "Cargo.lock", "# lock")
            destino = self.tmp / f"{nome}.tar.gz"
            with tarfile.open(destino, "w:gz") as tar:
                tar.add(src, arcname=nome)
            return destino

        with mock.patch.dict(os.environ, {"PATH": f"{falso.parent}{os.pathsep}{os.environ['PATH']}"}):
            if sys.platform == "win32":
                self.skipTest("o cargo falso é um script de shell")
            raiz, gerado = fontes._vendorizar("p 1.0.0", [arquivo("com-lock", True)], self.tmp / "t1")
            self.assertFalse(gerado)
            raiz, gerado = fontes._vendorizar("p 1.0.0", [arquivo("sem-lock", False)], self.tmp / "t2")
            self.assertTrue(gerado)
            self.assertTrue((raiz / "vendor" / "x-1.0.0" / "Cargo.toml").is_file())
        chamadas = registo.read_text(encoding="utf-8").splitlines()
        self.assertEqual(chamadas, ["vendor --locked --versioned-dirs vendor", "generate-lockfile",
                                    "vendor --locked --versioned-dirs vendor"])

    def test_cargo_toml_without_tomllib(self):
        import fontes
        from unittest import mock
        texto = '[package]\nname = "foo"\nversion = "1.0.0"\nlicense = "MIT OR Apache-2.0"\n\n[lib]\nname = "x"\n'
        with mock.patch.dict(sys.modules, {"tomllib": None}):  # como no Python 3.10
            pacote = fontes._pacote_cargo(texto)
        self.assertEqual((pacote["name"], pacote["version"], pacote["license"]), ("foo", "1.0.0", "MIT OR Apache-2.0"))

    def test_extract_without_system_tar(self):
        import tarfile
        import fontes
        origem = escrever(self.tmp / "src" / "pacote-1.0" / "Cargo.lock", "# lock")
        arquivo = self.tmp / "pacote-1.0.tar.gz"
        with tarfile.open(arquivo, "w:gz") as tar:
            tar.add(origem.parent, arcname="pacote-1.0")
        fontes._extrair(arquivo, self.tmp / "aberto")
        self.assertTrue((self.tmp / "aberto" / "pacote-1.0" / "Cargo.lock").is_file())

    def test_standard_texts_for_crates_without_their_own(self):
        self.assertEqual(terceiros._textos_padrao_crates(["MIT", "Apache-2.0 OR MIT", "MPL-2.0", "MIT-0"]),
                         ["MIT.txt", "Apache-2.0.txt", "MPL-2.0.txt"])
        self.assertEqual(terceiros._textos_padrao_crates(["BSD-2-Clause"]), ["BSD-2-Clause.txt"])
        self.assertEqual(terceiros._textos_padrao_crates(["BSD-2-Clause-Patent"]), [])
        for nome in ("MIT.txt", "BSD-2-Clause.txt"):
            self.assertTrue((terceiros.TEXTOS_PADRAO / nome).is_file(), nome)

    def test_notice_ships_crate_texts(self):
        import fontes
        crates = self.tmp / "trabalho" / "librsvg"
        info = fontes.copiar_textos_crates(vendor_de_teste(self.tmp / "projeto"), crates, "librsvg 2.62.3")
        projeto = self.tmp / "arruma"
        shutil.copyfile(RAIZ / "LICENSE", escrever(projeto / "LICENSE"))
        comp = terceiros.Componente(chave="h:librsvg", nome="librsvg", versao="2.62.3", licenca="LGPL-2.1-or-later",
                                    origem="homebrew", cargo=True, crates=str(crates), n_crates=info["n"],
                                    crates_sem_texto=info["sem_texto"])
        liq = terceiros.Componente(chave="h:liq", nome="libimagequant", versao="4.4.1", licenca="GPL-3.0-or-later",
                                   origem="homebrew", cargo=True, crates=str(crates), n_crates=3, crates_lock_gerado=True)
        entradas = terceiros.escrever({"h:librsvg": comp, "h:liq": liq}, self.tmp / "licencas", "0.2.0", "macos",
                                      projeto, "etiqueta v0.2.0", True)
        leia = " ".join((self.tmp / "licencas" / "LEIA-ME.txt").read_text(encoding="utf-8").split())
        self.assertIn("Bibliotecas Rust: librsvg/crates/CRATES.txt (3 crates do Cargo.lock", leia)
        self.assertIn("listadas no Cargo.lock do código-fonte do librsvg", leia)
        self.assertIn("listadas num Cargo.lock gerado na construção do Arruma (o código-fonte do libimagequant", leia)
        self.assertIn("está em librsvg/crates", leia)
        self.assertIn("librsvg-2.62.3-crates.tar.gz", leia)
        self.assertTrue((self.tmp / "licencas" / "textos-padrao" / "MIT.txt").is_file())
        destinos = {d for d, _src, _tipo in entradas}
        self.assertIn("licencas/librsvg/crates/CRATES.txt", destinos)
        self.assertFalse([d for d in destinos if d.endswith(".json") and "/crates/" in d])

    def test_crates_are_collected_once_per_version_and_failures_stop_ci(self):
        import fontes
        from unittest import mock
        def comp(chave, nome):
            return terceiros.Componente(chave=chave, nome=nome, versao="50.0.1", licenca="Apache-2.0",
                                        origem="pypi", cargo=True, fontes=[{"tipo": "url", "url": "https://x/y.tar.gz"}])
        componentes = {"pypi:c": comp("pypi:c", "cryptography"), "homebrew:c": comp("homebrew:c", "cryptography")}
        chamadas = []
        def falso(rotulo, urls, destino):
            chamadas.append(rotulo)
            destino.mkdir(parents=True)
            return {"n": 7, "gerado": False, "sem_texto": ["MIT"], "licencas": ["MIT", "Apache-2.0"]}
        with mock.patch.object(fontes, "textos_crates", falso):
            terceiros.juntar_textos_crates(componentes, self.tmp / "crates")
        self.assertEqual(chamadas, ["cryptography 50.0.1"])
        self.assertEqual({c.n_crates for c in componentes.values()}, {7})
        self.assertEqual({tuple(c.crates_sem_texto) for c in componentes.values()}, {("MIT",)})

        def avaria(rotulo, urls, destino):
            raise ValueError("arquivo estragado")  # qualquer erro, não só os de rede
        outro = {"pypi:c": comp("pypi:c", "cryptography")}
        with mock.patch.object(fontes, "textos_crates", avaria), \
                mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            with self.assertRaises(SystemExit):
                terceiros.juntar_textos_crates(outro, self.tmp / "crates2")
        with mock.patch.object(fontes, "textos_crates", avaria), \
                mock.patch.dict(os.environ, {"GITHUB_ACTIONS": ""}):
            terceiros.juntar_textos_crates(outro, self.tmp / "crates3")
        self.assertEqual(outro["pypi:c"].crates, "")

        def incompativel(rotulo, urls, destino):
            destino.mkdir(parents=True)
            return {"n": 1, "gerado": False, "sem_texto": [], "licencas": ["GPL-2.0-only"]}
        with mock.patch.object(fontes, "textos_crates", incompativel), \
                mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            with self.assertRaises(SystemExit):
                terceiros.juntar_textos_crates({"pypi:c": comp("pypi:c", "cryptography")}, self.tmp / "crates4")


if __name__ == "__main__":
    unittest.main()
