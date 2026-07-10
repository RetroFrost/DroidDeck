from __future__ import annotations

import importlib


def test_all_application_modules_import() -> None:
    for name in (
        "droiddeck_gtk.backend",
        "droiddeck_gtk.widgets",
        "droiddeck_gtk.pages_adb",
        "droiddeck_gtk.pages_flash",
        "droiddeck_gtk.pages_settings",
        "droiddeck_gtk.app",
    ):
        importlib.import_module(name)
