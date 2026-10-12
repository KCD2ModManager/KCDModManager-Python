#!/bin/sh
# Optional: add KCD Mod Manager (tarball build) to the application menu of the current user.
# Run from the extracted folder:  ./install-desktop-entry.sh   (undo: ./install-desktop-entry.sh --remove)
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"

if [ "${1:-}" = "--remove" ]; then
    rm -f "$APPS/kcd-mod-manager.desktop" "$ICONS/kcd-mod-manager.png"
    echo "Removed desktop entry."
    exit 0
fi

mkdir -p "$APPS" "$ICONS"
cp "$HERE/kcd-mod-manager.png" "$ICONS/kcd-mod-manager.png"
sed "s|^Exec=.*|Exec=\"$HERE/KCDModManager\"|" "$HERE/kcd-mod-manager.desktop" > "$APPS/kcd-mod-manager.desktop"
chmod +x "$APPS/kcd-mod-manager.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" || true
echo "Installed desktop entry to $APPS"
