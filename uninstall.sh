#!/usr/bin/env bash
set -euo pipefail
PREFIX=${PREFIX:-"$HOME/.local"}
rm -rf "$PREFIX/share/droiddeck-gtk"
rm -f "$PREFIX/bin/droiddeck-gtk"
rm -f "$PREFIX/share/applications/io.github.droiddeck.DroidDeck.desktop"
rm -f "$PREFIX/share/icons/hicolor/scalable/apps/io.github.droiddeck.DroidDeck.svg"
rm -f "$PREFIX/share/metainfo/io.github.droiddeck.DroidDeck.metainfo.xml"
update-desktop-database "$PREFIX/share/applications" >/dev/null 2>&1 || true
gtk-update-icon-cache "$PREFIX/share/icons/hicolor" >/dev/null 2>&1 || true
printf 'Removed DroidDeck GTK from %s\n' "$PREFIX"
