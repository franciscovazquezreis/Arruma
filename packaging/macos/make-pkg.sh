#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Cria o instalador do macOS (.pkg) a partir de dist/Arruma.app (PyInstaller).
# Antes de instalar, o instalador vê a versão de /Applications/Arruma.app: se não houver,
# instala; se for mais antiga, atualiza (retirando a anterior por inteiro); se for a mesma,
# não faz nada; se for mais recente, avisa antes de a substituir e, numa instalação pela linha
# de comandos (sem ninguém para responder), deixa-a como está. Se o Arruma estiver aberto, pede
# para o fechar primeiro.
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
# A versão mínima do macOS com que o Arruma foi construído (ver arruma.spec).
MIN="$(/usr/libexec/PlistBuddy -c 'Print LSMinimumSystemVersion' "$APP/Contents/Info.plist" 2>/dev/null || true)"
mkdir -p "$STAGE/raiz" "$STAGE/scripts"
ditto "$APP" "$STAGE/raiz/Arruma.app"

pkgbuild --analyze --root "$STAGE/raiz" "$STAGE/componentes.plist" >/dev/null
# Sem isto, o instalador procura o Arruma noutro sítio do disco e atualiza essa cópia, em vez
# de instalar em /Applications.
plutil -replace 0.BundleIsRelocatable -bool NO "$STAGE/componentes.plist"
# A comparação de versões é feita pelo verificar_versao() abaixo. Com a verificação do próprio
# instalador, ele recusava-se em silêncio a pôr uma versão mais antiga por cima de uma mais
# recente, depois de o preinstall já ter retirado a instalada.
plutil -replace 0.BundleIsVersionChecked -bool NO "$STAGE/componentes.plist"

cat > "$STAGE/scripts/preinstall" <<EOF
#!/bin/sh
APP="\${3%/}/Applications/Arruma.app"
NOVA='$VERSION'

# Na janela do instalador, o macOS pede antes para fechar o Arruma (must-close, abaixo); pela
# linha de comandos não pede, e substituir a aplicação aberta estragava o trabalho em curso.
if pgrep -f "\$APP/Contents/MacOS/Arruma" >/dev/null 2>&1; then
    echo "O Arruma está aberto. Fecha-o e volta a correr o instalador." >&2
    exit 1
fi

# Pela linha de comandos, o aviso do verificar_versao() não para a instalação e ninguém pode
# responder: uma versão mais recente fica como está.
if [ -n "\${COMMAND_LINE_INSTALL:-}" ] && [ -f "\$APP/Contents/Info.plist" ]; then
    INSTALADA="\$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "\$APP/Contents/Info.plist" 2>/dev/null || true)"
    MAIS_RECENTE="\$(printf '%s\\n%s\\n' "\$INSTALADA" "\$NOVA" | sort -t. -k1,1n -k2,2n -k3,3n | tail -n 1)"
    if [ -n "\$INSTALADA" ] && [ "\$INSTALADA" != "\$NOVA" ] && [ "\$MAIS_RECENTE" = "\$INSTALADA" ]; then
        echo "Está instalado o Arruma \$INSTALADA, mais recente do que a versão deste instalador (\$NOVA); fica como está." >&2
        echo "Para o substituir, põe primeiro o Arruma no Lixo." >&2
        exit 1
    fi
fi

# Retira a versão anterior por inteiro, para não ficarem ficheiros dela dentro da nova.
rm -rf "\$APP"
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
  <!-- O instalador Intel declara também arm64 para correr sem o Rosetta num Mac com processador
       Apple, e assim recusar logo, em vez de pedir primeiro para instalar o Rosetta. -->
  <options customize="never" require-scripts="false" hostArchitectures="$( [ "$HOST" = arm64 ] && echo arm64 || echo x86_64,arm64 )"/>
  <domains enable_localSystem="true" enable_anywhere="false" enable_currentUserHome="false"/>
$( [ -n "$MIN" ] && printf '  <allowed-os-versions><os-version min="%s"/></allowed-os-versions>\n' "$MIN" )
  <installation-check script="verificar_versao()"/>
  <script><![CDATA[
function mac_com_processador_apple() {
  try {
    return system.sysctl('hw.optional.arm64') == 1;  // também sob o Rosetta
  } catch (e) {
    return false;
  }
}

function verificar_versao() {
  var nova = '$VERSION';
  if ('$HOST' == 'x86_64' && mac_com_processador_apple()) {
    my.result.type = 'Fatal';
    my.result.title = 'Este instalador é para Macs com processador Intel';
    my.result.message = 'Este Mac tem um processador Apple (M1, M2, M3…). Descarrega o instalador «apple-silicon».';
    return false;
  }
  var app = system.files.bundleAtPath('/Applications/Arruma.app');
  if (!app || !app.CFBundleShortVersionString) {
    return true;  // primeira instalação
  }
  var instalada = app.CFBundleShortVersionString;
  var comparacao = system.compareVersions(instalada, nova);
  if (comparacao == 0) {
    my.result.type = 'Fatal';
    my.result.title = 'O Arruma ' + nova + ' já está instalado';
    my.result.message = 'Não há nada a atualizar. Para o reinstalar, põe primeiro o Arruma no Lixo.';
    return false;
  }
  if (comparacao > 0) {
    my.result.type = 'Warning';
    my.result.title = 'Está instalada uma versão mais recente';
    my.result.message = 'Está instalado o Arruma ' + instalada + ', mais recente do que a versão deste instalador (' +
        nova + '). Se continuares nesta janela, será substituído pela versão mais antiga. Pela linha de ' +
        'comandos fica como está; para o substituir, põe primeiro o Arruma no Lixo.';
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
  <pkg-ref id="pt.arruma.Arruma">
    <must-close>
      <app id="pt.arruma.Arruma"/>
    </must-close>
  </pkg-ref>
</installer-gui-script>
EOF

productbuild --distribution "$STAGE/distribution.xml" --package-path "$STAGE" "$OUT" >/dev/null
echo "$OUT"
