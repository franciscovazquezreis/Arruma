#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Cria o pacote arruma_<versão>_all.deb (Linux Mint, Ubuntu, Debian).
# Uso: packaging/linux/build-deb.sh [pasta de saída]   (por omissão: dist/)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${1:-$ROOT/dist}"
VERSION="$(python3 -c "import sys; sys.path.insert(0, '$ROOT'); import arruma; print(arruma.__version__)")"
STAGE="$(mktemp -d)"
PKG="$STAGE/arruma_${VERSION}_all"
trap 'rm -rf "$STAGE"' EXIT

install -d "$PKG/DEBIAN" "$PKG/usr/bin" "$PKG/usr/lib/arruma" "$PKG/usr/share/applications" \
    "$PKG/usr/share/icons/hicolor/scalable/apps" "$PKG/usr/share/icons/hicolor/256x256/apps" \
    "$PKG/usr/share/nemo/actions" "$PKG/usr/share/doc/arruma"

cp -r "$ROOT/arruma" "$PKG/usr/lib/arruma/"
find "$PKG/usr/lib/arruma" -name '__pycache__' -prune -exec rm -rf {} +

# Não usa «python3 -m arruma», que abriria primeiro um Arruma que estivesse na pasta atual.
cat > "$PKG/usr/bin/arruma" <<'EOF'
#!/bin/sh
exec python3 -c 'import runpy, sys; sys.path[0] = sys.argv.pop(1); runpy.run_module("arruma", run_name="__main__", alter_sys=True)' /usr/lib/arruma "$@"
EOF
chmod 755 "$PKG/usr/bin/arruma"

# Retira as cópias antigas do instalar.sh, que esconderiam este pacote, e o código compilado pelo
# Python, que o dpkg não conhece (ver cada script).
install -m 755 "$ROOT/packaging/linux/postinst" "$PKG/DEBIAN/postinst"
install -m 755 "$ROOT/packaging/linux/preinst" "$PKG/DEBIAN/preinst"
install -m 755 "$ROOT/packaging/linux/prerm" "$PKG/DEBIAN/prerm"
install -m 644 "$ROOT/packaging/linux/pt.arruma.Arruma.desktop" "$PKG/usr/share/applications/"
install -m 644 "$ROOT/packaging/linux/arruma.nemo_action" "$PKG/usr/share/nemo/actions/"
install -m 644 "$ROOT/arruma/ui/arruma.svg" "$PKG/usr/share/icons/hicolor/scalable/apps/pt.arruma.Arruma.svg"
install -m 644 "$ROOT/arruma/ui/arruma.png" "$PKG/usr/share/icons/hicolor/256x256/apps/pt.arruma.Arruma.png"
install -m 644 "$ROOT/README.md" "$PKG/usr/share/doc/arruma/README.md"
# Formato legível por máquina do Debian (DEP-5). O pacote só contém o código do Arruma;
# as dependências vêm do apt, cada uma com a sua licença.
cat > "$PKG/usr/share/doc/arruma/copyright" <<EOF
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: Arruma
Source: https://github.com/franciscovazquezreis/Arruma

Files: *
Copyright: 2026 Francisco Reis
License: GPL-3.0+
 This program is free software: you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation, either version 3 of the License, or
 (at your option) any later version.
 .
 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.
 .
 On Debian systems, the complete text of the GNU General Public License
 version 3 can be found in "/usr/share/common-licenses/GPL-3".
EOF

SIZE="$(du -sk "$PKG/usr" | cut -f1)"
cat > "$PKG/DEBIAN/control" <<EOF
Package: arruma
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Installed-Size: $SIZE
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, gir1.2-gtk-3.0, poppler-utils
Recommends: python3-pil, python3-mutagen, librsvg2-common, tesseract-ocr, tesseract-ocr-por
Suggests: tesseract-ocr-spa, tesseract-ocr-fra, tesseract-ocr-deu, tesseract-ocr-ita
Maintainer: Francisco Reis <franciscovazquezreis@users.noreply.github.com>
Homepage: https://github.com/franciscovazquezreis/Arruma
Description: Organizador de ficheiros local e sem internet
 Analisa pastas, propõe uma organização clara (documentos por área,
 fotografias por data, música por artista) e só altera alguma coisa
 depois de aprovada. Tudo pode ser anulado. Opcionalmente usa uma IA
 local (Ollama) para ler documentos, sem enviar nada para a internet.
EOF

mkdir -p "$OUT"
dpkg-deb --root-owner-group --build "$PKG" "$OUT/arruma_${VERSION}_all.deb" >/dev/null
echo "$OUT/arruma_${VERSION}_all.deb"
