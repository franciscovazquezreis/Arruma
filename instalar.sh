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
    # Sem o gtk-update-icon-cache, a cache antiga continuaria a indicar os ícones apagados; mudar
    # a data da pasta faz o GTK deixar de confiar nela.
    touch -c "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
    gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
    echo "✓ Arruma removido da pasta pessoal."
    echo "  O histórico e as definições ficam em ~/.local/share/arruma e ~/.config/arruma."
    exit 0
fi

versao_de() { sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$1/arruma/__init__.py" 2>/dev/null || true; }
# Escreve -1, 0 ou 1, conforme a primeira versão (X.Y.Z) é anterior, igual ou posterior à
# segunda; não escreve nada se alguma delas não tiver esse formato.
compara() {
    local formato='^[0-9]+(\.[0-9]+)*$' a b i
    [[ $1 =~ $formato && $2 =~ $formato ]] || return 0
    IFS=. read -ra a <<<"$1"
    IFS=. read -ra b <<<"$2"
    for ((i = 0; i < ${#a[@]} || i < ${#b[@]}; i++)); do
        if ((10#${a[i]:-0} < 10#${b[i]:-0})); then echo -1; return 0; fi
        if ((10#${a[i]:-0} > 10#${b[i]:-0})); then echo 1; return 0; fi
    done
    echo 0
}
pergunta() {
    printf "%s Substituir? [s/N] " "$1"
    read -r resposta || resposta=""
    case "$resposta" in s|S|sim|Sim) ;; *) echo "Nada foi alterado."; exit 0 ;; esac
}

NOVA="$(versao_de "$SRC_DIR")"
# Com o pacote no sistema (instalado ou a meio de uma instalação), uma cópia na pasta pessoal
# escondê-lo-ia no menu, no Nemo e no terminal.
ESTADO_PACOTE="$(dpkg-query -W -f='${db:Status-Status}' arruma 2>/dev/null || true)"
case "$ESTADO_PACOTE" in
    ""|not-installed|config-files) ;;
    *)  PACOTE="$(dpkg-query -W -f='${Version}' arruma 2>/dev/null || true)"
        COPIA="$(versao_de "$APP_DIR")"
        echo "O pacote arruma $PACOTE já está instalado no sistema."
        if [ -n "$COPIA" ] && [ "$(compara "$COPIA" "$PACOTE")" = 1 ]; then
            echo "A cópia na pasta pessoal ($COPIA) é mais recente do que o pacote e é essa que se abre."
            echo "Para a continuar a atualizar com o instalar.sh, remove primeiro o pacote: sudo apt remove arruma"
        else
            echo "Uma cópia na pasta pessoal teria prioridade sobre ele. Para atualizar, instala o .deb mais recente."
            if [ -e "$APP_DIR" ] || [ -e "$BIN_DIR/arruma" ]; then
                echo "Ainda há uma cópia antiga na pasta pessoal; retira-a com ./instalar.sh --remover."
            fi
        fi
        exit 1 ;;
esac
if [ -f "$APP_DIR/arruma/__init__.py" ]; then
    ATUAL="$(versao_de "$APP_DIR")"
    case "$(compara "$ATUAL" "$NOVA")" in
        0)  echo "O Arruma $NOVA já está instalado. Não há nada a atualizar."
            exit 0 ;;
        1)  pergunta "Está instalado o Arruma $ATUAL, mais recente do que a versão desta cópia ($NOVA)." ;;
        -1) echo "A atualizar o Arruma de $ATUAL para $NOVA (o histórico e as definições ficam)." ;;
        *)  pergunta "Está instalado o Arruma ${ATUAL:-de versão desconhecida}, que não se consegue comparar com esta cópia ($NOVA)." ;;
    esac
fi

mkdir -p "$APP_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR" "$PNG_ICON_DIR" "$NEMO_ACTION_DIR"

rm -rf "$APP_DIR/arruma"
cp -r "$SRC_DIR/arruma" "$APP_DIR/arruma"

# O lançador abre sempre a cópia instalada, e não a pasta do código: assim abre-se a versão que
# foi escolhida acima, mesmo que o código mude depois.
cat > "$BIN_DIR/arruma" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$APP_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
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
