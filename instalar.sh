#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Instala (ou atualiza) o Arruma para o utilizador atual no Linux Mint, sem precisar de sudo.
# Alternativa com sudo: o pacote arruma_<versão>_all.deb (ver README).
# Com --remover, retira esta instalação (o histórico e as definições ficam).
# Se já houver uma cópia instalada, só atualiza quando esta for mais recente.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$HOME/.local/share/arruma-app"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
PNG_ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
NEMO_ACTION_DIR="$HOME/.local/share/nemo/actions"

if [ "${1:-}" = "--remover" ]; then
    rm -rf "$APP_DIR"
    rm -f "$BIN_DIR/arruma" "$DESKTOP_DIR/pt.arruma.Arruma.desktop" "$NEMO_ACTION_DIR/arruma.nemo_action" \
          "$ICON_DIR/pt.arruma.Arruma.svg" "$PNG_ICON_DIR/pt.arruma.Arruma.png"
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
    gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
    echo "✓ Arruma removido da pasta pessoal."
    echo "  O histórico e as definições ficam em ~/.local/share/arruma e ~/.config/arruma."
    exit 0
fi

versao_de() { sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$1/arruma/__init__.py"; }
# -1, 0 ou 1, conforme a primeira versão é anterior, igual ou posterior à segunda.
compara() { python3 -c 'import sys; a, b = (tuple(int(p) for p in v.split(".")) for v in sys.argv[1:]); print((a > b) - (a < b))' "$1" "$2"; }

NOVA="$(versao_de "$SRC_DIR")"
if command -v dpkg-query >/dev/null 2>&1 && dpkg-query -W -f='${Status}' arruma 2>/dev/null | grep -q "install ok installed"; then
    echo "O pacote arruma $(dpkg-query -W -f='${Version}' arruma) já está instalado no sistema."
    echo "Uma cópia na pasta pessoal teria prioridade sobre ele. Para atualizar, instala o .deb mais recente."
    exit 1
fi
if [ -f "$APP_DIR/arruma/__init__.py" ]; then
    ATUAL="$(versao_de "$APP_DIR")"
    case "$(compara "$ATUAL" "$NOVA")" in
        0)  echo "O Arruma $NOVA já está instalado. Não há nada a atualizar."
            exit 0 ;;
        1)  printf "Está instalado o Arruma %s, mais recente do que esta cópia (%s). Substituir? [s/N] " "$ATUAL" "$NOVA"
            read -r resposta || resposta=""
            case "$resposta" in s|S|sim|Sim) ;; *) echo "Nada foi alterado."; exit 0 ;; esac ;;
        *)  echo "A atualizar o Arruma de $ATUAL para $NOVA (o histórico e as definições ficam)." ;;
    esac
fi

mkdir -p "$APP_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR" "$PNG_ICON_DIR" "$NEMO_ACTION_DIR"

rm -rf "$APP_DIR/arruma"
cp -r "$SRC_DIR/arruma" "$APP_DIR/arruma"

cat > "$BIN_DIR/arruma" <<EOF
#!/usr/bin/env bash
if [ -d "$SRC_DIR/arruma" ]; then
    export PYTHONPATH="$SRC_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
else
    export PYTHONPATH="$APP_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
fi
exec python3 -m arruma "\$@"
EOF
chmod +x "$BIN_DIR/arruma"

cp "$SRC_DIR/arruma/ui/arruma.svg" "$ICON_DIR/pt.arruma.Arruma.svg"
cp "$SRC_DIR/arruma/ui/arruma.png" "$PNG_ICON_DIR/pt.arruma.Arruma.png"

cat > "$DESKTOP_DIR/pt.arruma.Arruma.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Arruma
GenericName=Organizador de ficheiros
Comment=Organiza pastas e ficheiros localmente, sem internet
Exec=$BIN_DIR/arruma %F
Icon=pt.arruma.Arruma
Terminal=false
Categories=Utility;FileTools;
Keywords=organizar;arrumar;ficheiros;pastas;duplicados;
StartupNotify=true
StartupWMClass=arruma
EOF

cat > "$NEMO_ACTION_DIR/arruma.nemo_action" <<EOF
[Nemo Action]
Active=true
Name=Arrumar com o Arruma
Comment=Analisa e propõe uma organização para as pastas selecionadas
Exec=$BIN_DIR/arruma %F
Icon-Name=pt.arruma.Arruma
Selection=notnone
Extensions=dir;
Quote=double
EOF

update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true

echo "✓ Arruma instalado com sucesso!"
echo "  • Menu de aplicações do Linux Mint → Acessórios → Arruma"
echo "  • Gestor de ficheiros (Nemo): clique direito numa pasta → «Arrumar com o Arruma»"
echo "  • Terminal: $BIN_DIR/arruma"
