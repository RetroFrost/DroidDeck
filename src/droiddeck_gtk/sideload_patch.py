from __future__ import annotations

from pathlib import Path

from gi.repository import Adw, Gtk

from .pages_adb import AdbPagesMixin
from .widgets import ActionButton, Section, button_row, choose_file, entry_group, typed_confirm


def _build_adb_tools_page(self) -> Gtk.Widget:
    box = self.page_box()

    reboot = Section("Reboot", "Reboot the selected ADB device into another mode.")
    for label, target in [
        ("Android", ""),
        ("Recovery", "recovery"),
        ("Bootloader", "bootloader"),
        ("fastbootd", "fastboot"),
        ("Samsung Download Mode", "download"),
    ]:
        button = ActionButton(
            label, "system-reboot-symbolic", destructive=bool(target)
        )
        button.connect("clicked", lambda _b, t=target: self.confirm_adb_reboot(t))
        reboot.append(button)
    box.append(reboot)

    sideload = Section(
        "ADB sideload",
        "Install a signed OTA or ROM ZIP while the selected device is in recovery sideload mode.",
    )
    warning = Gtk.Label(
        label=(
            "The package is sent directly with adb sideload. Verify that it is intended "
            "for your exact device before continuing."
        ),
        xalign=0,
        wrap=True,
    )
    warning.add_css_class("dim-label")
    sideload.append(warning)
    choose_sideload = ActionButton(
        "Choose ZIP and sideload", "document-send-symbolic", suggested=True
    )
    choose_sideload.connect("clicked", lambda _b: self.choose_adb_sideload())
    sideload.append(button_row(choose_sideload))
    box.append(sideload)

    wireless = Section(
        "Wireless ADB", "Pair or connect to Android's wireless debugging service."
    )
    group, self.pair_address = entry_group("Pairing address", "192.168.1.10:37123")
    wireless.append(group)
    self.pair_code = Adw.PasswordEntryRow(title="Pairing code", text="")
    self.pair_code.set_input_purpose(Gtk.InputPurpose.DIGITS)
    wireless.append(self.pair_code)
    pair = ActionButton("Pair", suggested=True)
    pair.connect("clicked", lambda _b: self.adb_pair())
    wireless.append(button_row(pair))
    group, self.connect_address = entry_group(
        "Connect address", "192.168.1.10:5555"
    )
    wireless.append(group)
    connect = ActionButton("Connect")
    connect.connect("clicked", lambda _b: self.adb_connect())
    disconnect = ActionButton("Disconnect all")
    disconnect.connect("clicked", lambda _b: self.run_tool(["adb", "disconnect"]))
    tcp = ActionButton("Enable TCP/IP 5555")
    tcp.connect(
        "clicked",
        lambda _b: self.run_adb(
            "tcpip", "5555", destructive=True, exclusive="adb-tcpip"
        ),
    )
    wireless.append(button_row(connect, disconnect, tcp))
    box.append(wireless)

    shell = Section(
        "ADB shell", "Open an interactive terminal or run one Android shell command."
    )
    group, self.shell_command = entry_group(
        "Command", "getprop ro.build.display.id"
    )
    shell.append(group)
    run = ActionButton(
        "Run command", "media-playback-start-symbolic", suggested=True
    )
    run.connect("clicked", lambda _b: self.run_shell_command())
    terminal = ActionButton(
        "Open interactive terminal", "utilities-terminal-symbolic"
    )
    terminal.connect("clicked", lambda _b: self.open_adb_shell())
    shell.append(button_row(run, terminal))
    box.append(shell)
    return self.scroll_page(box)


def _choose_adb_sideload(self) -> None:
    choose_file(
        self,
        "Select sideload ZIP",
        self.confirm_adb_sideload,
        patterns=["*.zip"],
    )


def _confirm_adb_sideload(self, path: Path) -> None:
    typed_confirm(
        self,
        "Sideload update package",
        (
            "The selected device must already be in recovery sideload mode. "
            "DroidDeck cannot verify that this package belongs to your device.\n\n"
            f"Package: {path}"
        ),
        f"SIDELOAD {path.name}",
        lambda: self.run_adb(
            "sideload",
            str(path),
            destructive=True,
            exclusive="adb-sideload",
        ),
    )


def install() -> None:
    AdbPagesMixin.build_adb_tools_page = _build_adb_tools_page
    AdbPagesMixin.choose_adb_sideload = _choose_adb_sideload
    AdbPagesMixin.confirm_adb_sideload = _confirm_adb_sideload
