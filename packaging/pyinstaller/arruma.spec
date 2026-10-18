# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Especificação do PyInstaller para as versões de Windows e macOS.

Uso, na raiz do projeto:  pyinstaller packaging/pyinstaller/arruma.spec --noconfirm
Resultado: dist/Arruma/ (Windows) ou dist/Arruma.app (macOS), com Python, GTK e o tema
Adwaita incluídos.
"""

import os
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
    excludes=["tkinter"],
    noarchive=False,
)
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
