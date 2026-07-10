from __future__ import annotations

import sys
from types import ModuleType


class _DummyWidget:
    pass


def _module(name: str) -> ModuleType:
    module = ModuleType(name)
    return module


if "gi" not in sys.modules:
    gi_module = _module("gi")
    repository = _module("gi.repository")
    glib = _module("GLib")
    glib.idle_add = lambda callback, *args: callback(*args)

    adw = _module("Adw")
    adw.PreferencesGroup = _DummyWidget
    adw.ApplicationWindow = _DummyWidget
    adw.Application = _DummyWidget

    gtk = _module("Gtk")
    gtk.Button = _DummyWidget

    gio = _module("Gio")
    gdk = _module("Gdk")

    repository.GLib = glib
    repository.Adw = adw
    repository.Gtk = gtk
    repository.Gio = gio
    repository.Gdk = gdk
    gi_module.repository = repository
    gi_module.require_version = lambda *_args: None

    sys.modules.update(
        {
            "gi": gi_module,
            "gi.repository": repository,
            "gi.repository.GLib": glib,
            "gi.repository.Adw": adw,
            "gi.repository.Gtk": gtk,
            "gi.repository.Gio": gio,
            "gi.repository.Gdk": gdk,
        }
    )
