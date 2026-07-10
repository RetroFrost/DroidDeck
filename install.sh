#!/usr/bin/env bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PREFIX=${PREFIX:-"$HOME/.local"}
APP_DIR="$PREFIX/share/droiddeck-gtk"
BIN_DIR="$PREFIX/bin"
DESKTOP_DIR="$PREFIX/share/applications"
ICON_DIR="$PREFIX/share/icons/hicolor/scalable/apps"
METAINFO_DIR="$PREFIX/share/metainfo"
PYTHON_BIN=${DROIDDECK_PYTHON:-/usr/bin/python3}
if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN=$(command -v python3 || true)
fi
if [[ -z "$PYTHON_BIN" ]]; then
    printf '%s\n' 'DroidDeck needs Python 3.10 or newer.' >&2
    exit 1
fi
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
    printf '%s\n' 'DroidDeck needs Python 3.10 or newer.' >&2
    exit 1
fi

mkdir -p "$APP_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR" "$METAINFO_DIR"
rm -rf "$APP_DIR/src"
cp -a "$ROOT/src" "$APP_DIR/src"
install -m 0755 "$ROOT/droiddeck-gtk" "$APP_DIR/droiddeck-gtk"
ln -sfn "$APP_DIR/droiddeck-gtk" "$BIN_DIR/droiddeck-gtk"
install -m 0644 \
    "$ROOT/data/io.github.droiddeck.DroidDeck.svg" \
    "$ICON_DIR/io.github.droiddeck.DroidDeck.svg"
install -m 0644 \
    "$ROOT/data/io.github.droiddeck.DroidDeck.metainfo.xml" \
    "$METAINFO_DIR/io.github.droiddeck.DroidDeck.metainfo.xml"

"$PYTHON_BIN" - \
    "$ROOT/data/io.github.droiddeck.DroidDeck.desktop.in" \
    "$DESKTOP_DIR/io.github.droiddeck.DroidDeck.desktop" \
    "$BIN_DIR/droiddeck-gtk" <<'PY'
from pathlib import Path
import sys

template, destination, executable = map(Path, sys.argv[1:])
# Desktop Entry Exec quoting is not shell quoting. Escape the characters that
# are special inside a double-quoted Exec argument.
escaped = str(executable).replace("\\", "\\\\")
for character in ('"', '`', '$'):
    escaped = escaped.replace(character, "\\" + character)
text = template.read_text(encoding="utf-8").replace(
    "Exec=@EXEC@", f'Exec="{escaped}"'
)
destination.write_text(text, encoding="utf-8")
PY

update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
gtk-update-icon-cache "$PREFIX/share/icons/hicolor" >/dev/null 2>&1 || true
printf 'Installed DroidDeck GTK to %s\n' "$PREFIX"
printf 'Run: %s/droiddeck-gtk\n' "$BIN_DIR"
