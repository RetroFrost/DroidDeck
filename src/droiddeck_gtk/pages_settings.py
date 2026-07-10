from __future__ import annotations

from pathlib import Path

from gi.repository import Adw, Gio, GLib, Gtk

from . import __version__
from .widgets import ActionButton, Section, button_row, choose_folder, show_message


class SettingsPagesMixin:
    def build_settings_page(self) -> Gtk.Widget:
        box = self.page_box()

        safety = Section(
            "Safety",
            "DroidDeck keeps dangerous flashing tools behind explicit controls.",
        )
        self.dry_run_switch = Adw.SwitchRow(
            title="Dry run protected write actions",
            subtitle="Preview commands DroidDeck marks as write, flash, erase, format, install, or reboot operations.",
            active=self.config.dry_run,
        )
        self.dry_run_switch.connect(
            "notify::active", lambda row, _pspec: self.set_dry_run(row.get_active())
        )
        safety.append(self.dry_run_switch)

        self.expert_switch = Adw.SwitchRow(
            title="Expert mode",
            subtitle="Unlock Fastboot and Heimdall write operations. Typed confirmations still apply.",
            active=self.config.expert,
        )
        self.expert_switch.connect(
            "notify::active", lambda row, _pspec: self.set_expert(row.get_active())
        )
        safety.append(self.expert_switch)
        box.append(safety)

        output = Section(
            "Output directory",
            "Screenshots, logs, reports, PIT files, recordings, and extracted APKs are saved here.",
        )
        self.output_dir_row = Adw.ActionRow(
            title="Current location", subtitle=str(self.config.output_dir)
        )
        self.output_dir_row.set_use_markup(False)
        self.output_dir_row.set_subtitle_selectable(True)
        output.append(self.output_dir_row)
        choose = ActionButton("Choose folder", "folder-open-symbolic", suggested=True)
        choose.connect(
            "clicked",
            lambda _button: choose_folder(
                self, "Choose DroidDeck output directory", self.set_output_dir
            ),
        )
        open_button = ActionButton("Open folder", "folder-symbolic")
        open_button.connect("clicked", lambda _button: self.open_output_dir())
        output.append(button_row(choose, open_button))
        box.append(output)

        about = Section("About")
        version = Adw.ActionRow(
            title="DroidDeck",
            subtitle=f"Version {__version__} · GTK 4 + Libadwaita Android toolbox",
        )
        about.append(version)
        box.append(about)
        return self.scroll_page(box)

    def _save_settings(self) -> bool:
        if self.config.save():
            return True
        show_message(
            self, "Could not save settings", self.config.last_error, error=True
        )
        return False

    def set_dry_run(self, active: bool) -> None:
        if self.config.dry_run == active:
            return
        previous = self.config.dry_run
        self.config.dry_run = active
        if not self._save_settings():
            self.config.dry_run = previous
            if self.dry_run_switch.get_active() != previous:
                self.dry_run_switch.set_active(previous)
            if self.header_dry_run.get_active() != previous:
                self.header_dry_run.set_active(previous)
            return
        if self.header_dry_run.get_active() != active:
            self.header_dry_run.set_active(active)
        self.toast("Dry run enabled" if active else "Dry run disabled")

    def set_expert(self, active: bool) -> None:
        if self.config.expert == active:
            return
        previous = self.config.expert
        self.config.expert = active
        if not self._save_settings():
            self.config.expert = previous
            if self.expert_switch.get_active() != previous:
                self.expert_switch.set_active(previous)
            return
        self.toast("Expert mode enabled" if active else "Expert mode disabled")

    def set_output_dir(self, path: Path) -> None:
        try:
            path = path.expanduser().resolve()
            path.mkdir(parents=True, exist_ok=True)
        except (OSError, RuntimeError) as exc:
            show_message(self, "Could not use output directory", str(exc), error=True)
            return
        previous = self.config.output_dir
        self.config.output_dir = path
        if not self._save_settings():
            self.config.output_dir = previous
            return
        self.output_dir_row.set_subtitle(str(path))
        if hasattr(self, "pull_destination"):
            self.pull_destination.set_text(f"Destination: {path / 'downloads'}")
        self.toast("Output directory updated")

    def open_output_dir(self) -> None:
        try:
            self.config.output_dir.mkdir(parents=True, exist_ok=True)
            Gio.AppInfo.launch_default_for_uri(self.config.output_dir.as_uri(), None)
        except (OSError, GLib.Error) as exc:
            show_message(self, "Could not open output directory", str(exc), error=True)
