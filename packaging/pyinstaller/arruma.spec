# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Especificação do PyInstaller para as versões de Windows e macOS.

Uso, na raiz do projeto:  pyinstaller packaging/pyinstaller/arruma.spec --noconfirm
Resultado: dist/Arruma/ (Windows) ou dist/Arruma.app (macOS), com Python, GTK e o tema
Adwaita incluídos.
"""

import os
import platform
import shutil
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[1]  # noqa: F821  (SPECPATH é definido pelo PyInstaller)
sys.path.insert(0, str(ROOT))
import arruma  # noqa: E402

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"
ICON = str(ROOT / "packaging" / "icons" / ("arruma.icns" if IS_MAC else "arruma.ico"))

datas = [
    (str(ROOT / "arruma" / "ui" / "style.css"), "arruma/ui"),
    (str(ROOT / "arruma" / "ui" / "arruma.svg"), "arruma/ui"),
    (str(ROOT / "arruma" / "ui" / "arruma.png"), "arruma/ui"),
]

if IS_WIN:
    # A consola do MSYS2 define XDG_DATA_DIRS com as pastas do próprio MSYS2 (/usr/share), e a
    # GTK recolheria de lá ícones que nada têm a ver com o Arruma (por exemplo, os do mintty).
    os.environ.pop("XDG_DATA_DIRS", None)

binaries = []
if IS_WIN:
    # Poppler do MSYS2 para ler PDF e fazer OCR. Ficam ao lado das DLL de que precisam.
    for tool in ("pdftotext", "pdftoppm"):
        path = shutil.which(tool)
        if path:
            binaries.append((path, "."))

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "pyinstaller" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "arruma.ui.app",
        "gi.repository.Gtk", "gi.repository.Gdk", "gi.repository.GdkPixbuf", "gi.repository.Gio",
        "gi.repository.GLib", "gi.repository.Pango", "gi.repository.PangoCairo",
        "cairo", "PIL.Image", "mutagen", "pypdf",
    ],
    hooksconfig={
        "gi": {
            "icons": ["Adwaita", "hicolor"],
            "themes": ["Adwaita"],
            "languages": ["pt", "pt_PT"],
            "module-versions": {"Gtk": "3.0", "Gdk": "3.0"},
        },
    },
    # Sem AVIF: o Arruma não precisa dele e o módulo traria seis bibliotecas (uma delas em Rust).
    excludes=["tkinter", "PIL._avif", "PIL.AvifImagePlugin"],
    noarchive=False,
)
# Licenças de terceiros: lista dos componentes que o PyInstaller recolheu, com os textos das
# licenças e as receitas de construção. Fica pronta antes do COLLECT e do BUNDLE, para que a
# assinatura do .app no macOS cubra também estes ficheiros.
sys.path.insert(0, str(ROOT / "packaging" / "licencas"))
import terceiros  # noqa: E402

# Versão publicada (etiqueta vX.Y.Z) ou de teste (commit), para o aviso indicar o código-fonte certo.
REF, SHA = os.environ.get("GITHUB_REF", ""), os.environ.get("GITHUB_SHA", "")
PUBLICADA = REF == f"refs/tags/v{arruma.__version__}"
if PUBLICADA:
    REFERENCIA = f"etiqueta v{arruma.__version__}"
elif SHA:
    REFERENCIA = f"commit {SHA[:12]}, versão de teste"
else:
    REFERENCIA = "versão construída localmente, sem etiqueta"
licencas = terceiros.gerar(a, Path(workpath) / "licencas", ROOT, Path(workpath),  # noqa: F821
                           arruma.__version__, REFERENCIA, PUBLICADA)
print(f"Licenças de terceiros: {len(licencas.componentes)} componentes")
for comp in sorted(licencas.componentes.values(), key=lambda c: c.nome.casefold()):
    print(f"  {comp.nome} {comp.versao} | {comp.licenca} | {comp.ficheiros} ficheiros | "
          f"{len(comp.textos)} textos | {len(comp.fontes)} fontes")
for caminho, tipo in licencas.desconhecidos:
    print(f"  SEM ORIGEM ({tipo}): {caminho}")
sem_origem = [c for c, t in licencas.desconhecidos if t in ("BINARY", "EXTENSION")]
if sem_origem:
    raise SystemExit(f"{len(sem_origem)} bibliotecas sem origem conhecida: não é possível indicar a licença.")
a.datas += licencas.entradas
# Índice para o fontes.py juntar o código-fonte destes componentes em cada versão publicada.
PLATAFORMA = "windows" if IS_WIN else f"macos-{'apple-silicon' if platform.machine() == 'arm64' else 'intel'}"
Path(DISTPATH).mkdir(parents=True, exist_ok=True)  # noqa: F821
shutil.copyfile(Path(workpath) / "licencas" / "componentes.json",  # noqa: F821
                Path(DISTPATH) / f"componentes-{PLATAFORMA}.json")  # noqa: F821

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Arruma",
    console=False,
    icon=ICON,
    upx=False,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Arruma")  # noqa: F821

if IS_WIN:
    # À vista, ao lado do Arruma.exe (no Windows nada é assinado, por isso pode juntar-se depois).
    shutil.copyfile(ROOT / "LICENSE", Path(DISTPATH) / "Arruma" / "LICENSE.txt")  # noqa: F821

if IS_MAC:
    app = BUNDLE(  # noqa: F821
        coll,
        name="Arruma.app",
        icon=ICON,
        bundle_identifier="pt.arruma.Arruma",
        version=arruma.__version__,
        info_plist={
            "CFBundleName": "Arruma",
            "CFBundleDisplayName": "Arruma",
            "CFBundleShortVersionString": arruma.__version__,
            "CFBundleVersion": arruma.__version__,
            "CFBundleDevelopmentRegion": "pt_PT",
            "LSApplicationCategoryType": "public.app-category.productivity",
            "LSMinimumSystemVersion": os.environ.get("ARRUMA_MACOS_MIN", "11.0"),
            "NSHighResolutionCapable": True,
            "NSDesktopFolderUsageDescription":
                "O Arruma lê e arruma os ficheiros da Secretária apenas quando escolheres essa pasta.",
            "NSDocumentsFolderUsageDescription":
                "O Arruma lê e arruma os teus documentos apenas quando escolheres essa pasta.",
            "NSDownloadsFolderUsageDescription":
                "O Arruma lê e arruma as Descargas apenas quando escolheres essa pasta.",
            "NSRemovableVolumesUsageDescription":
                "O Arruma lê e arruma os discos externos que escolheres.",
            "NSNetworkVolumesUsageDescription":
                "O Arruma lê e arruma as pastas de rede que escolheres.",
        },
    )
