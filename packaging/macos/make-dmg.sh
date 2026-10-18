#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
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
# Nos servidores macOS do GitHub, o hdiutil falha por vezes com «Resource busy» porque o
# sistema ainda está a examinar a imagem temporária; basta tentar outra vez.
for attempt in 1 2 3 4 5; do
  if hdiutil create -volname "Arruma $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$OUT" >/dev/null; then
    echo "$OUT"
    exit 0
  fi
  echo "O hdiutil falhou (tentativa $attempt de 5)." >&2
  sleep $((attempt * 5))
done
exit 1
