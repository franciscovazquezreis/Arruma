#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Cria o instalador do macOS (.pkg) a partir de dist/Arruma.app (PyInstaller).
# Antes de instalar, o instalador vê a versão de /Applications/Arruma.app: se não houver,
# instala; se for mais antiga, atualiza (retirando a anterior por inteiro); se for a mesma,
# não faz nada; se for mais recente, avisa antes de a substituir.
# Uso: packaging/macos/make-pkg.sh <apple-silicon|intel>
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARCH="${1:-$( [ "$(uname -m)" = arm64 ] && echo apple-silicon || echo intel )}"
VERSION="$(python3 -c "import sys; sys.path.insert(0, '$ROOT'); import arruma; print(arruma.__version__)")"
APP="$ROOT/dist/Arruma.app"
OUT="$ROOT/dist/Arruma-$VERSION-macos-$ARCH.pkg"
HOST="$( [ "$ARCH" = apple-silicon ] && echo arm64 || echo x86_64 )"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

[ -d "$APP" ] || { echo "Falta $APP: corre primeiro o PyInstaller." >&2; exit 1; }
mkdir -p "$STAGE/raiz" "$STAGE/scripts"
ditto "$APP" "$STAGE/raiz/Arruma.app"

# Sem isto, o instalador procura o Arruma noutro sítio do disco e atualiza essa cópia, em vez
# de instalar em /Applications.
pkgbuild --analyze --root "$STAGE/raiz" "$STAGE/componentes.plist" >/dev/null
plutil -replace 0.BundleIsRelocatable -bool NO "$STAGE/componentes.plist"

cat > "$STAGE/scripts/preinstall" <<'EOF'
#!/bin/sh
# Retira a versão anterior por inteiro, para não ficarem ficheiros dela dentro da nova.
rm -rf "${3%/}/Applications/Arruma.app"
exit 0
EOF
chmod 755 "$STAGE/scripts/preinstall"

pkgbuild --root "$STAGE/raiz" --component-plist "$STAGE/componentes.plist" --scripts "$STAGE/scripts" \
    --identifier pt.arruma.Arruma --version "$VERSION" --install-location /Applications \
    "$STAGE/Arruma.pkg" >/dev/null

cat > "$STAGE/distribution.xml" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
  <title>Arruma $VERSION</title>
  <options customize="never" require-scripts="false" hostArchitectures="$HOST"/>
  <domains enable_localSystem="true" enable_anywhere="false" enable_currentUserHome="false"/>
  <installation-check script="verificar_versao()"/>
  <script><![CDATA[
function verificar_versao() {
  var nova = '$VERSION';
  var app = system.files.bundleAtPath('/Applications/Arruma.app');
  if (!app || !app.CFBundleShortVersionString) {
    return true;  // primeira instalação
  }
  var instalada = app.CFBundleShortVersionString;
  var comparacao = system.compareVersions(instalada, nova);
  if (comparacao == 0) {
    my.result.type = 'Fatal';
    my.result.title = 'O Arruma ' + nova + ' já está instalado';
    my.result.message = 'Não há nada a atualizar.';
    return false;
  }
  if (comparacao > 0) {
    my.result.type = 'Warning';
    my.result.title = 'Está instalada uma versão mais recente';
    my.result.message = 'Está instalado o Arruma ' + instalada + ', mais recente do que este instalador (' +
        nova + '). Se continuares, será substituído pela versão mais antiga.';
    return false;
  }
  return true;  // atualização
}
  ]]></script>
  <choices-outline>
    <line choice="arruma"/>
  </choices-outline>
  <choice id="arruma" title="Arruma">
    <pkg-ref id="pt.arruma.Arruma"/>
  </choice>
  <pkg-ref id="pt.arruma.Arruma" version="$VERSION" onConclusion="none">Arruma.pkg</pkg-ref>
</installer-gui-script>
EOF

productbuild --distribution "$STAGE/distribution.xml" --package-path "$STAGE" "$OUT" >/dev/null
echo "$OUT"
