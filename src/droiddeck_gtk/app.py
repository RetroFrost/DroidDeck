from __future__ import annotations

# ruff: noqa: E402

import subprocess
import sys
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk

from . import __version__
from .backend import AdbDevice, Backend, Config, Result, Runner
from .pages_adb import AdbPagesMixin
from .pages_flash import FlashPagesMixin
from .pages_settings import SettingsPagesMixin
from .widgets import install_css, show_message


class DroidDeckWindow(
    AdbPagesMixin, FlashPagesMixin, SettingsPagesMixin, Adw.ApplicationWindow
):
    """Main adaptive Libadwaita window."""

    PAGE_DEFINITIONS = (
        ("overview", "Overview", "computer-symbolic"),
        ("apps", "Applications", "application-x-executable-symbolic"),
        ("files", "Files", "folder-symbolic"),
        ("logcat", "Logcat", "text-x-generic-symbolic"),
        ("screen", "Screen", "video-display-symbolic"),
        ("adb", "ADB Tools", "utilities-terminal-symbolic"),
        ("diagnostics", "Diagnostics", "emblem-system-symbolic"),
        ("fastboot", "Fastboot", "system-run-symbolic"),
        ("heimdall", "Heimdall", "drive-harddisk-symbolic"),
        ("settings", "Settings", "preferences-system-symbolic"),
    )

    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="DroidDeck")
        self.set_default_size(1180, 780)
        self.set_size_request(540, 480)

        self.config = Config()
        self.output_buffer = Gtk.TextBuffer()
        self.runner = Runner(self.config, self.append_output)
        self.backend = Backend(self.config, self.runner)
        self.adb_devices: list[AdbDevice] = []
        self.fastboot_serial = ""
        self.logcat_buffer = Gtk.TextBuffer()
        self.logcat_running = False
        self._closing = False
        self._updating_device_dropdown = False

        self._build_ui()
        self.refresh_adb_devices()
        self.refresh_dependencies()
        if self.config.last_error:
            show_message(
                self, "Configuration warning", self.config.last_error, error=True
            )

    def _build_ui(self) -> None:
        self.toast_overlay = Adw.ToastOverlay()
        self.split_view = Adw.NavigationSplitView()
        self.toast_overlay.set_child(self.split_view)
        self.set_content(self.toast_overlay)

        self.stack = Adw.ViewStack()
        self.stack.set_vexpand(True)
        self.stack.connect("notify::visible-child-name", self._on_page_changed)

        builders: dict[str, Callable[[], Gtk.Widget]] = {
            "overview": self.build_overview_page,
            "apps": self.build_apps_page,
            "files": self.build_files_page,
            "logcat": self.build_logcat_page,
            "screen": self.build_screen_page,
            "adb": self.build_adb_tools_page,
            "diagnostics": self.build_diagnostics_page,
            "fastboot": self.build_fastboot_page,
            "heimdall": self.build_heimdall_page,
            "settings": self.build_settings_page,
        }
        for name, title, icon_name in self.PAGE_DEFINITIONS:
            page = self.stack.add_titled(builders[name](), name, title)
            page.set_icon_name(icon_name)

        sidebar_toolbar = Adw.ToolbarView()
        sidebar_header = Adw.HeaderBar()
        sidebar_header.set_show_end_title_buttons(False)
        sidebar_title = Adw.WindowTitle(title="DroidDeck", subtitle="Android toolbox")
        sidebar_header.set_title_widget(sidebar_title)
        sidebar_toolbar.add_top_bar(sidebar_header)
        switcher = Adw.ViewSwitcherSidebar()
        switcher.set_stack(self.stack)
        sidebar_toolbar.set_content(switcher)
        sidebar_page = Adw.NavigationPage.new(sidebar_toolbar, "DroidDeck")
        self.split_view.set_sidebar(sidebar_page)

        content_toolbar = Adw.ToolbarView()
        content_header = Adw.HeaderBar()
        self.page_title = Adw.WindowTitle(title="Overview", subtitle="No ADB device")
        content_header.set_title_widget(self.page_title)

        self.device_model = Gtk.StringList.new(["No ADB device selected"])
        self.device_dropdown = Gtk.DropDown(model=self.device_model)
        self.device_dropdown.set_tooltip_text("Selected ADB device")
        self.device_dropdown.set_size_request(250, -1)
        self.device_dropdown.connect("notify::selected", self.on_device_selected)
        content_header.pack_start(self.device_dropdown)

        refresh = Gtk.Button(
            icon_name="view-refresh-symbolic", tooltip_text="Refresh ADB devices"
        )
        refresh.connect("clicked", lambda _button: self.refresh_adb_devices())
        content_header.pack_start(refresh)

        self.header_dry_run = Gtk.ToggleButton(
            icon_name="changes-prevent-symbolic",
            tooltip_text="Dry run: preview protected write commands",
        )
        self.header_dry_run.set_active(self.config.dry_run)
        self.header_dry_run.connect("toggled", self.on_header_dry_run)
        content_header.pack_end(self.header_dry_run)

        self.output_toggle = Gtk.ToggleButton(
            icon_name="utilities-terminal-symbolic", tooltip_text="Show command output"
        )
        self.output_toggle.set_active(True)
        self.output_toggle.connect(
            "toggled",
            lambda button: self.output_revealer.set_reveal_child(button.get_active()),
        )
        content_header.pack_end(self.output_toggle)

        menu = Gio.Menu()
        menu.append("About DroidDeck", "app.about")
        menu.append("Quit", "app.quit")
        content_header.pack_end(
            Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        )
        content_toolbar.add_top_bar(content_header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.set_vexpand(True)
        self.stack.set_vexpand(True)
        content.append(self.stack)
        self.output_revealer = Gtk.Revealer(
            reveal_child=True,
            transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
            transition_duration=180,
        )
        self.output_revealer.set_child(self._build_output_panel())
        content.append(self.output_revealer)
        content_toolbar.set_content(content)

        self.content_page = Adw.NavigationPage.new(content_toolbar, "Overview")
        self.split_view.set_content(self.content_page)

        condition = Adw.BreakpointCondition.parse("max-width: 720sp")
        breakpoint = Adw.Breakpoint.new(condition)
        breakpoint.add_setter(self.split_view, "collapsed", True)
        self.add_breakpoint(breakpoint)

    def _build_output_panel(self) -> Gtk.Widget:
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        panel.add_css_class("view")
        panel.add_css_class("card")

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.add_css_class("output-toolbar")
        title = Gtk.Label(label="Command output", xalign=0)
        title.add_css_class("heading")
        title.set_hexpand(True)
        toolbar.append(title)
        clear = Gtk.Button(label="Clear")
        clear.connect("clicked", lambda _button: self.output_buffer.set_text(""))
        toolbar.append(clear)
        panel.append(toolbar)

        output_scroll = Gtk.ScrolledWindow()
        output_scroll.set_size_request(-1, 190)
        self.output_view = Gtk.TextView(
            buffer=self.output_buffer,
            editable=False,
            monospace=True,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
            cursor_visible=False,
        )
        self.output_view.add_css_class("command-output")
        output_scroll.set_child(self.output_view)
        self.output_end_mark = self.output_buffer.create_mark(
            "droiddeck-output-end", self.output_buffer.get_end_iter(), False
        )
        panel.append(output_scroll)
        return panel

    def _on_page_changed(self, _stack: Adw.ViewStack, _pspec: object) -> None:
        name = self.stack.get_visible_child_name() or "overview"
        title = next(
            (
                page_title
                for page_name, page_title, _icon in self.PAGE_DEFINITIONS
                if page_name == name
            ),
            "DroidDeck",
        )
        self.page_title.set_title(title)
        self.content_page.set_title(title)
        if self.split_view.get_collapsed():
            self.split_view.set_show_content(True)

    def page_box(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.set_margin_top(24)
        box.set_margin_bottom(32)
        box.set_margin_start(24)
        box.set_margin_end(24)
        return box

    @staticmethod
    def scroll_page(content: Gtk.Widget) -> Gtk.ScrolledWindow:
        clamp = Adw.Clamp(maximum_size=1100, tightening_threshold=760)
        clamp.set_child(content)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(clamp)
        return scroll

    def toast(self, text: str, *, timeout: int = 3) -> None:
        toast = Adw.Toast.new(text)
        toast.set_timeout(timeout)
        self.toast_overlay.add_toast(toast)

    def append_output(self, text: str) -> bool:
        if self._closing:
            return False
        self.output_buffer.insert(self.output_buffer.get_end_iter(), text)
        if self.output_buffer.get_char_count() > 1_000_000:
            start = self.output_buffer.get_start_iter()
            trim_to = self.output_buffer.get_iter_at_offset(200_000)
            self.output_buffer.delete(start, trim_to)
        self.output_buffer.move_mark(
            self.output_end_mark, self.output_buffer.get_end_iter()
        )
        self.output_view.scroll_to_mark(self.output_end_mark, 0.0, True, 0.0, 1.0)
        return False

    def tool_required(self, name: str) -> bool:
        if self.runner.exists(name):
            return True
        show_message(
            self,
            f"{name} is not installed",
            f"Install {name}, then try again.",
            error=True,
        )
        return False

    def adb_required(self) -> bool:
        if not self.tool_required("adb"):
            return False
        if not self.backend.adb_serial:
            show_message(
                self,
                "No ADB device selected",
                "Connect and authorize a device, then choose it in the header.",
                error=True,
            )
            return False
        return True

    def fastboot_required(self) -> bool:
        if not self.tool_required("fastboot"):
            return False
        if not self.fastboot_serial:
            show_message(
                self,
                "No Fastboot device selected",
                "Detect Fastboot devices before running a command.",
                error=True,
            )
            return False
        return True

    def expert_required(self, feature: str) -> bool:
        if self.config.expert:
            return True
        show_message(
            self,
            "Expert mode required",
            f"Enable Expert mode in Settings before using {feature}.",
            error=True,
        )
        return False

    def run_adb(
        self,
        *args: str,
        done: Callable[[Result], None] | None = None,
        destructive: bool = False,
        exclusive: str | None = None,
        serial: str | None = None,
        display_args: list[str] | None = None,
        timeout: float | None = None,
    ) -> bool:
        if not self.tool_required("adb"):
            return False
        target = serial if serial is not None else self.backend.adb_serial
        if not target:
            show_message(
                self,
                "No ADB device selected",
                "Connect and authorize a device, then choose it in the header.",
                error=True,
            )
            return False
        started = self.runner.run(
            self.backend.adb(*args, serial=target),
            done,
            destructive=destructive,
            exclusive=exclusive,
            display_args=display_args,
            timeout=timeout,
        )
        if not started and exclusive:
            show_message(
                self,
                "Operation already running",
                f"Wait for the current {exclusive} operation to finish.",
                error=True,
            )
        return started

    def run_tool(
        self,
        args: list[str],
        done: Callable[[Result], None] | None = None,
        destructive: bool = False,
        exclusive: str | None = None,
        display_args: list[str] | None = None,
        timeout: float | None = None,
    ) -> bool:
        if not args or not self.tool_required(args[0]):
            return False
        started = self.runner.run(
            args,
            done,
            destructive=destructive,
            exclusive=exclusive,
            display_args=display_args,
            timeout=timeout,
        )
        if not started and exclusive:
            show_message(
                self,
                "Operation already running",
                f"Wait for the current {exclusive} operation to finish.",
                error=True,
            )
        return started

    def refresh_adb_devices(self) -> None:
        if not self.runner.exists("adb"):
            self._replace_device_list([], "ADB not installed")
            return

        previous_serial = self.backend.adb_serial

        def done(result: Result) -> None:
            if not result.ok:
                self._replace_device_list([], "Unable to list ADB devices")
                return
            devices = self.backend.parse_adb_devices(result.stdout)
            self.adb_devices = devices
            labels = [device.label for device in devices] or ["No ADB devices found"]
            self._updating_device_dropdown = True
            self.device_model.splice(0, self.device_model.get_n_items(), labels)

            authorized = [
                (index, device)
                for index, device in enumerate(devices)
                if device.state == "device"
            ]
            if not authorized:
                if self.logcat_running:
                    self.stop_logcat()
                self.backend.clear_adb()
                self.device_dropdown.set_selected(0)
                self._updating_device_dropdown = False
                status = (
                    "No ADB devices found"
                    if not devices
                    else "No authorized ADB device"
                )
                self._set_device_status(status)
                return

            selected_index = next(
                (
                    index
                    for index, device in authorized
                    if device.serial == previous_serial
                ),
                authorized[0][0],
            )
            self.device_dropdown.set_selected(selected_index)
            self._updating_device_dropdown = False
            selected = devices[selected_index]
            if (
                self.logcat_running
                and previous_serial
                and selected.serial != previous_serial
            ):
                self.stop_logcat()
            if not self.backend.choose_adb(selected.serial):
                self.toast("Selected device, but could not save it")
            self._set_device_status(f"Connected: {selected.label}")
            self.refresh_overview()

        self.runner.run(
            ["adb", "devices", "-l"],
            done,
            exclusive="adb-device-scan",
            timeout=15,
        )

    def _replace_device_list(self, devices: list[AdbDevice], message: str) -> None:
        if self.logcat_running:
            self.stop_logcat()
        self.adb_devices = devices
        self.backend.clear_adb()
        self._updating_device_dropdown = True
        self.device_model.splice(0, self.device_model.get_n_items(), [message])
        self.device_dropdown.set_selected(0)
        self._updating_device_dropdown = False
        self._set_device_status(message)

    def _set_device_status(self, message: str) -> None:
        if hasattr(self, "overview_status"):
            self.overview_status.set_text(message)
        self.page_title.set_subtitle(message)

    def on_device_selected(self, dropdown: Gtk.DropDown, _pspec: object) -> None:
        if self._updating_device_dropdown:
            return
        index = dropdown.get_selected()
        if index >= len(self.adb_devices):
            return
        device = self.adb_devices[index]
        if (
            self.logcat_running
            and self.backend.adb_serial
            and device.serial != self.backend.adb_serial
        ):
            self.stop_logcat()
        if device.state != "device":
            self.backend.clear_adb()
            self._set_device_status(f"Device is {device.state}")
            show_message(
                self,
                "Device unavailable",
                f"{device.serial} is {device.state}.",
                error=True,
            )
            return
        if not self.backend.choose_adb(device.serial):
            self.toast("Device selected, but the setting could not be saved")
        self._set_device_status(f"Connected: {device.label}")
        self.refresh_overview()

    def on_header_dry_run(self, button: Gtk.ToggleButton) -> None:
        active = button.get_active()
        if self.config.dry_run == active:
            return
        previous = self.config.dry_run
        self.config.dry_run = active
        if not self.config.save():
            self.config.dry_run = previous
            if button.get_active() != previous:
                button.set_active(previous)
            if (
                hasattr(self, "dry_run_switch")
                and self.dry_run_switch.get_active() != previous
            ):
                self.dry_run_switch.set_active(previous)
            show_message(
                self, "Could not save settings", self.config.last_error, error=True
            )
            return
        if (
            hasattr(self, "dry_run_switch")
            and self.dry_run_switch.get_active() != active
        ):
            self.dry_run_switch.set_active(active)
        self.toast("Dry run enabled" if active else "Dry run disabled")

    def launch_terminal(self, args: list[str]) -> None:
        candidates = [
            ["kgx", "--", *args],
            ["gnome-terminal", "--", *args],
            ["x-terminal-emulator", "-e", *args],
        ]
        for command in candidates:
            if self.runner.exists(command[0]):
                try:
                    subprocess.Popen(
                        command,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    return
                except OSError:
                    continue
        show_message(
            self,
            "No terminal found",
            "Install GNOME Console or GNOME Terminal.",
            error=True,
        )

    def close_request(self) -> bool:
        if self.runner.has_active:
            show_message(
                self,
                "Operation still running",
                "Stop Logcat or wait for the active command to finish before closing DroidDeck.",
                error=True,
            )
            return True
        self._closing = True
        self.runner.close()
        return False


class DroidDeckApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id="io.github.droiddeck.DroidDeck",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", self._request_quit)
        self.add_action(quit_action)
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self.show_about)
        self.add_action(about_action)
        self.set_accels_for_action("app.quit", ["<primary>q"])

    def do_activate(self) -> None:
        window = self.props.active_window
        if not window:
            install_css()
            window = DroidDeckWindow(self)
            window.connect("close-request", lambda current: current.close_request())
        window.present()

    def _request_quit(self, _action: Gio.SimpleAction, _parameter: object) -> None:
        window = self.props.active_window
        if window:
            window.close()
        else:
            self.quit()

    def show_about(self, _action: Gio.SimpleAction, _parameter: object) -> None:
        window = self.props.active_window
        if not window:
            return
        dialog = Adw.AboutDialog()
        dialog.set_application_name("DroidDeck")
        dialog.set_application_icon("io.github.droiddeck.DroidDeck")
        dialog.set_version(__version__)
        dialog.set_developer_name("FrostStraw and contributors")
        dialog.set_comments(
            "A native GTK 4 and Libadwaita toolbox for Android development, ADB, Fastboot, and Heimdall."
        )
        dialog.set_license_type(Gtk.License.MIT_X11)
        dialog.present(window)


def main() -> int:
    if "--version" in sys.argv[1:]:
        print(__version__)
        return 0
    return DroidDeckApplication().run(sys.argv)
