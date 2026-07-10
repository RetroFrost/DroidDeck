from __future__ import annotations

import sys

from . import __version__


def _dependency_error(message: str) -> int:
    print(
        f"DroidDeck could not start: {message}\n\n"
        "Install the required GTK bindings on Ubuntu/Debian with:\n"
        "  sudo apt update\n"
        "  sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    if "--version" in sys.argv[1:]:
        print(__version__)
        return 0
    if sys.version_info < (3, 10):
        return _dependency_error("Python 3.10 or newer is required")
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk
    except (ImportError, ValueError) as exc:
        return _dependency_error(str(exc))

    if (Gtk.get_major_version(), Gtk.get_minor_version()) < (4, 10):
        return _dependency_error("GTK 4.10 or newer is required")
    for required in (
        "AlertDialog",
        "AboutDialog",
        "NavigationSplitView",
        "Breakpoint",
    ):
        if not hasattr(Adw, required):
            return _dependency_error(
                f"Libadwaita 1.5 or newer is required (missing {required})"
            )

    from .app import main as app_main

    return app_main()
