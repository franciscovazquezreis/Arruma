#!/usr/bin/env bash
# Cria a imagem de disco do macOS a partir de dist/Arruma.app (PyInstaller).
# Uso: packaging/macos/make-dmg.sh <apple-silicon|intel>
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARCH="${1:-$( [ "$(uname -m)" = arm64 ] && echo apple-silicon || echo intel )}"
VERSION="$(python3 -c "import sys; sys.path.insert(0, '$ROOT'); import arruma; print(arruma.__version__)")"
APP="$ROOT/dist/Arruma.app"
OUT="$ROOT/dist/Arruma-$VERSION-macos-$ARCH.dmg"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

[ -d "$APP" ] || { echo "Falta $APP: corre primeiro o PyInstaller." >&2; exit 1; }
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Aplicações"
hdiutil create -volname "Arruma $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$OUT" >/dev/null
echo "$OUT"
