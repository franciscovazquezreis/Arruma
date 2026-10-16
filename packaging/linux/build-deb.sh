#!/usr/bin/env bash
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

cat > "$PKG/usr/bin/arruma" <<'EOF'
#!/bin/sh
export PYTHONPATH="/usr/lib/arruma${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m arruma "$@"
EOF
chmod 755 "$PKG/usr/bin/arruma"

install -m 644 "$ROOT/packaging/linux/pt.arruma.Arruma.desktop" "$PKG/usr/share/applications/"
install -m 644 "$ROOT/packaging/linux/arruma.nemo_action" "$PKG/usr/share/nemo/actions/"
install -m 644 "$ROOT/arruma/ui/arruma.svg" "$PKG/usr/share/icons/hicolor/scalable/apps/pt.arruma.Arruma.svg"
install -m 644 "$ROOT/arruma/ui/arruma.png" "$PKG/usr/share/icons/hicolor/256x256/apps/pt.arruma.Arruma.png"
install -m 644 "$ROOT/README.md" "$PKG/usr/share/doc/arruma/README.md"
cat > "$PKG/usr/share/doc/arruma/copyright" <<EOF
Arruma $VERSION
Código-fonte: https://github.com/franciscovazquezreis/Arruma
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
Maintainer: Arruma <franciscovazquezreis@users.noreply.github.com>
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
