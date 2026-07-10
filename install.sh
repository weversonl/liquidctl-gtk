#!/usr/bin/env bash
# Installs LiquidctlGTK for the current user: a venv under ~/.local/share,
# a launcher on PATH, the .desktop entry and the app icon.
# Run with --uninstall to remove everything this script created.
set -euo pipefail

APP_ID="io.github.weversonl.LiquidctlGTK"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/share/liquidctl-gui"
VENV_DIR="$INSTALL_DIR/venv"
BIN_DIR="$HOME/.local/bin"
LAUNCHER="$BIN_DIR/liquidctl-gui"
APPLICATIONS_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
DESKTOP_FILE="$APPLICATIONS_DIR/$APP_ID.desktop"
ICON_FILE="$ICON_DIR/$APP_ID.svg"
AUTOSTART_FILE="$HOME/.config/autostart/$APP_ID.desktop"

if [[ "${1:-}" == "--uninstall" ]]; then
    echo "==> Removing LiquidctlGTK"
    rm -rf "$INSTALL_DIR"
    rm -f "$LAUNCHER" "$DESKTOP_FILE" "$ICON_FILE" "$AUTOSTART_FILE"
    command -v update-desktop-database >/dev/null && update-desktop-database "$APPLICATIONS_DIR" 2>/dev/null || true
    command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
    echo "Done. Your config/curves at ~/.config/liquidctl-gui were left untouched."
    exit 0
fi

echo "==> Checking dependencies"
missing=()
python3 -c "import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1')" 2>/dev/null \
    || missing+=("PyGObject + GTK4 + libadwaita")
python3 -c "import liquidctl" 2>/dev/null \
    || missing+=("python-liquidctl")
python3 -c "import gi; gi.require_version('AyatanaAppIndicator3', '0.1')" 2>/dev/null \
    || missing+=("AyatanaAppIndicator3 introspection bindings (tray icon)")
command -v msgfmt >/dev/null 2>&1 \
    || missing+=("gettext (msgfmt)")

if [[ ${#missing[@]} -gt 0 ]]; then
    echo "Missing dependencies - install these with your distro's package manager first:"
    printf '  - %s\n' "${missing[@]}"
    exit 1
fi

echo "==> Creating virtualenv at $VENV_DIR"
mkdir -p "$INSTALL_DIR"
python3 -m venv --system-site-packages "$VENV_DIR"

echo "==> Installing LiquidctlGTK"
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -e "$REPO_DIR" -q

echo "==> Compiling translations"
mkdir -p "$REPO_DIR/po/locale/pt_BR/LC_MESSAGES"
msgfmt "$REPO_DIR/po/pt_BR.po" -o "$REPO_DIR/po/locale/pt_BR/LC_MESSAGES/liquidctl-gui.mo"

echo "==> Installing launcher to $LAUNCHER"
mkdir -p "$BIN_DIR"
cat >"$LAUNCHER" <<EOF
#!/usr/bin/env bash
exec "$VENV_DIR/bin/liquidctl-gui" "\$@"
EOF
chmod +x "$LAUNCHER"

echo "==> Installing desktop entry and icon"
mkdir -p "$APPLICATIONS_DIR" "$ICON_DIR"
sed "s|^Exec=.*|Exec=$LAUNCHER|" "$REPO_DIR/data/$APP_ID.desktop" >"$DESKTOP_FILE"
cp "$REPO_DIR/data/$APP_ID.svg" "$ICON_FILE"

command -v update-desktop-database >/dev/null && update-desktop-database "$APPLICATIONS_DIR" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo
    echo "NOTE: $BIN_DIR is not on your PATH. Add this to your shell profile:"
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

echo
echo "==> Done. Launch LiquidctlGTK from the GNOME app grid, or run: liquidctl-gui"
echo "    To remove it later: $0 --uninstall"
