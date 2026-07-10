from __future__ import annotations

from pathlib import Path
from typing import Callable

from gi.repository import Adw, Gtk

from .backend import Result
from .widgets import (
    ActionButton,
    Section,
    button_row,
    choose_file,
    choose_folder,
    confirm,
    entry_group,
    show_message,
    typed_confirm,
)


class AdbPagesMixin:
    # ---------- Overview ----------
    def build_overview_page(self) -> Gtk.Widget:
        box = self.page_box()
        hero = Section(
            "Device overview", "Live information from the selected Android device."
        )
        self.overview_status = Gtk.Label(
            label="Looking for devices…", xalign=0, wrap=True
        )
        self.overview_status.add_css_class("title-2")
        hero.append(self.overview_status)
        refresh = ActionButton(
            "Refresh overview", "view-refresh-symbolic", suggested=True
        )
        refresh.connect("clicked", lambda _b: self.refresh_overview())
        hero.append(button_row(refresh))
        box.append(hero)

        details = Section(
            "Device details",
            "Properties reported by Android for the currently selected device.",
        )
        self.metrics: dict[str, Adw.ActionRow] = {}
        for name in [
            "Model",
            "Android",
            "Battery",
            "Security patch",
            "ABI",
            "Boot state",
        ]:
            row = Adw.ActionRow(title=name, subtitle="—")
            row.set_use_markup(False)
            row.add_css_class("property")
            row.set_subtitle_selectable(True)
            details.append(row)
            self.metrics[name] = row
        box.append(details)

        quick = Section("Quick actions")
        screenshot = ActionButton("Screenshot", "camera-photo-symbolic")
        screenshot.connect("clicked", lambda _b: self.take_screenshot())
        shell = ActionButton("Open shell", "utilities-terminal-symbolic")
        shell.connect("clicked", lambda _b: self.open_adb_shell())
        recovery = ActionButton("Reboot recovery", "system-reboot-symbolic")
        recovery.connect("clicked", lambda _b: self.confirm_adb_reboot("recovery"))
        report = ActionButton("Bug report", "document-save-symbolic")
        report.connect("clicked", lambda _b: self.generate_bugreport())
        quick.append(button_row(screenshot, shell, recovery, report))
        box.append(quick)
        return self.scroll_page(box)

    def refresh_overview(self) -> None:
        if not self.adb_required():
            return
        serial = self.backend.adb_serial

        def still_selected() -> bool:
            return serial == self.backend.adb_serial

        def props_done(result: Result) -> None:
            if not still_selected() or not result.ok:
                return
            props = self.backend.parse_props(result.stdout)
            self.metrics["Model"].set_subtitle(props.get("ro.product.model", "Unknown"))
            self.metrics["Android"].set_subtitle(
                props.get("ro.build.version.release", "Unknown")
            )
            self.metrics["Security patch"].set_subtitle(
                props.get("ro.build.version.security_patch", "Unknown")
            )
            self.metrics["ABI"].set_subtitle(props.get("ro.product.cpu.abi", "Unknown"))
            verified = props.get("ro.boot.verifiedbootstate", "unknown")
            locked = props.get("ro.boot.flash.locked", "?")
            self.metrics["Boot state"].set_subtitle(f"{verified}; locked={locked}")

        def battery_done(result: Result) -> None:
            if not still_selected() or not result.ok:
                return
            level, temp = "?", "?"
            for line in result.stdout.splitlines():
                key, separator, value = line.partition(":")
                if not separator:
                    continue
                if key.strip() == "level":
                    level = value.strip()
                elif key.strip() == "temperature":
                    raw = value.strip()
                    try:
                        temp = f"{int(raw) / 10:.1f}°C"
                    except ValueError:
                        temp = raw
            self.metrics["Battery"].set_subtitle(f"{level}% · {temp}")

        self.run_adb("shell", "getprop", done=props_done, serial=serial)
        self.run_adb("shell", "dumpsys", "battery", done=battery_done, serial=serial)

    def build_apps_page(self) -> Gtk.Widget:
        box = self.page_box()
        head = Section(
            "Application manager",
            "Install APKs and manage packages on the selected device.",
        )
        self.package_search = Gtk.SearchEntry()
        self.package_search.set_placeholder_text("Filter package IDs")
        self.package_search.set_hexpand(True)
        self.package_search.connect(
            "search-changed", lambda _e: self.apply_package_filter()
        )
        head.append(self.package_search)
        refresh = ActionButton("Refresh", "view-refresh-symbolic")
        refresh.connect("clicked", lambda _b: self.load_packages())
        install = ActionButton("Install APK", "list-add-symbolic", suggested=True)
        install.connect("clicked", lambda _b: self.install_apk())
        split = ActionButton("Install split APKs")
        split.connect("clicked", lambda _b: self.install_split_apks())
        head.append(button_row(refresh, install, split))
        box.append(head)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, wide_handle=True)
        paned.set_vexpand(True)
        paned.set_size_request(-1, 440)
        self.package_store = Gtk.StringList.new([])
        self.package_selection = Gtk.SingleSelection(model=self.package_store)
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self.package_item_setup)
        factory.connect("bind", self.package_item_bind)
        package_list = Gtk.ListView(model=self.package_selection, factory=factory)
        package_scroll = Gtk.ScrolledWindow()
        package_scroll.set_min_content_width(370)
        package_scroll.set_child(package_list)
        paned.set_start_child(package_scroll)

        action_box = Section("Selected package")
        self.selected_package_label = Gtk.Label(
            label="No package selected", xalign=0, wrap=True, selectable=True
        )
        self.selected_package_label.add_css_class("title-4")
        action_box.append(self.selected_package_label)
        self.package_selection.connect(
            "notify::selected", lambda _s, _p: self.update_selected_package()
        )
        flow = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            column_spacing=8,
            row_spacing=8,
            max_children_per_line=2,
        )
        actions = [
            ("Package info", self.package_info, False),
            ("Force stop", lambda: self.package_shell_action("force-stop"), False),
            ("Launch", self.launch_package, False),
            ("Clear data", self.clear_package_data, True),
            ("Uninstall", self.uninstall_package, True),
            ("Extract APK", self.extract_package, False),
        ]
        for label, callback, destructive in actions:
            button = ActionButton(label, destructive=destructive)
            button.connect("clicked", lambda _b, cb=callback: cb())
            flow.insert(button, -1)
        action_box.append(flow)
        paned.set_end_child(action_box)
        paned.set_position(650)
        package_breakpoint = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse("max-width: 850sp")
        )
        package_breakpoint.add_setter(paned, "orientation", Gtk.Orientation.VERTICAL)
        package_breakpoint.add_setter(paned, "position", 285)
        self.add_breakpoint(package_breakpoint)
        box.append(paned)
        return self.scroll_page(box)

    @staticmethod
    def package_item_setup(
        _factory: Gtk.SignalListItemFactory, item: Gtk.ListItem
    ) -> None:
        label = Gtk.Label(xalign=0, selectable=True)
        label.set_margin_top(7)
        label.set_margin_bottom(7)
        label.set_margin_start(10)
        label.set_margin_end(10)
        item.set_child(label)

    @staticmethod
    def package_item_bind(
        _factory: Gtk.SignalListItemFactory, item: Gtk.ListItem
    ) -> None:
        item.get_child().set_text(item.get_item().get_string())

    def load_packages(self) -> None:
        if not self.adb_required():
            return
        serial = self.backend.adb_serial

        def done(result: Result) -> None:
            if serial != self.backend.adb_serial:
                return
            if not result.ok:
                show_message(
                    self,
                    "Could not list packages",
                    result.output or "The package manager returned no output.",
                    error=True,
                )
                return
            packages: set[str] = set()
            for line in result.stdout.splitlines():
                if not line.startswith("package:"):
                    continue
                package = line.removeprefix("package:").strip()
                if self.backend.valid_package(package):
                    packages.add(package)
            self._all_packages = sorted(packages)
            self.apply_package_filter()
            self.toast(f"Loaded {len(packages)} packages")

        self.run_adb(
            "shell",
            "pm",
            "list",
            "packages",
            done=done,
            serial=serial,
            exclusive="package-list",
        )

    def apply_package_filter(self) -> None:
        query = self.package_search.get_text().strip().lower()
        packages = [p for p in getattr(self, "_all_packages", []) if query in p.lower()]
        self.package_store.splice(0, self.package_store.get_n_items(), packages)

    def selected_package(self) -> str:
        item = self.package_selection.get_selected_item()
        return item.get_string() if item else ""

    def update_selected_package(self) -> None:
        self.selected_package_label.set_text(
            self.selected_package() or "No package selected"
        )

    def install_apk(self) -> None:
        choose_file(
            self,
            "Select APK",
            lambda path: self.run_adb(
                "install", "-r", str(path), destructive=True, exclusive="apk-install"
            ),
            patterns=["*.apk"],
        )

    def install_split_apks(self) -> None:
        def selected(folder: Path) -> None:
            apks = sorted(path for path in folder.glob("*.apk") if path.is_file())
            if not apks:
                show_message(
                    self,
                    "No APKs found",
                    "The selected folder contains no .apk files.",
                    error=True,
                )
                return
            self.run_adb(
                "install-multiple",
                "-r",
                *(str(path) for path in apks),
                destructive=True,
                exclusive="apk-install",
            )

        choose_folder(self, "Select folder containing split APKs", selected)

    def package_info(self) -> None:
        package = self.selected_package()
        if package:
            self.run_adb("shell", "dumpsys", "package", package)

    def package_shell_action(self, action: str) -> None:
        package = self.selected_package()
        if package:
            self.run_adb("shell", "am", action, package)

    def launch_package(self) -> None:
        package = self.selected_package()
        if package:
            self.run_adb(
                "shell",
                "monkey",
                "-p",
                package,
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            )

    def clear_package_data(self) -> None:
        package = self.selected_package()
        if package:
            typed_confirm(
                self,
                "Clear application data",
                f"This permanently removes local app data for {package}.",
                f"CLEAR {package}",
                lambda: self.run_adb(
                    "shell",
                    "pm",
                    "clear",
                    package,
                    destructive=True,
                    exclusive="package-write",
                ),
            )

    def uninstall_package(self) -> None:
        package = self.selected_package()
        if package:
            typed_confirm(
                self,
                "Uninstall application",
                f"Remove {package} from the selected device?",
                f"UNINSTALL {package}",
                lambda: self.run_adb(
                    "uninstall",
                    package,
                    destructive=True,
                    exclusive="package-write",
                ),
            )

    def extract_package(self) -> None:
        package = self.selected_package()
        if not package or not self.adb_required():
            return
        serial = self.backend.adb_serial

        def paths_done(result: Result) -> None:
            if serial != self.backend.adb_serial:
                return
            paths = [
                line.removeprefix("package:").strip()
                for line in result.stdout.splitlines()
                if line.startswith("package:")
            ]
            if not result.ok or not paths:
                show_message(
                    self,
                    "APK path not found",
                    result.output or "No APK path was returned.",
                    error=True,
                )
                return
            try:
                folder = self.backend.output_path("apks", package, "")
                folder.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                show_message(self, "Could not create APK folder", str(exc), error=True)
                return
            for remote in paths:
                self.run_adb(
                    "pull",
                    remote,
                    str(folder / Path(remote).name),
                    serial=serial,
                )
            self.toast(f"Extracting {len(paths)} APK file(s)")

        self.run_adb("shell", "pm", "path", package, done=paths_done, serial=serial)

    def build_files_page(self) -> Gtk.Widget:
        box = self.page_box()
        push = Section(
            "Push to Android", "Copy a local file or folder to the selected device."
        )
        group, self.push_remote = entry_group(
            "Remote destination", "/sdcard/Download/", "/sdcard/Download/"
        )
        push.append(group)
        file_button = ActionButton(
            "Choose file and push", "document-send-symbolic", suggested=True
        )
        file_button.connect(
            "clicked",
            lambda _b: choose_file(
                self,
                "Choose file to push",
                lambda p: self.push_local_path(p),
            ),
        )
        folder_button = ActionButton("Choose folder and push")
        folder_button.connect(
            "clicked",
            lambda _b: choose_folder(
                self,
                "Choose folder to push",
                lambda p: self.push_local_path(p),
            ),
        )
        push.append(button_row(file_button, folder_button))
        box.append(push)

        pull = Section(
            "Pull from Android", "Copy a remote path into DroidDeck's output directory."
        )
        group, self.pull_remote = entry_group(
            "Remote path", "/sdcard/Download/example.zip"
        )
        pull.append(group)
        self.pull_destination = Gtk.Label(
            label=f"Destination: {self.config.output_dir / 'downloads'}",
            xalign=0,
            selectable=True,
        )
        self.pull_destination.add_css_class("dim-label")
        pull.append(self.pull_destination)
        button = ActionButton("Pull path", "document-save-symbolic", suggested=True)
        button.connect("clicked", lambda _b: self.pull_remote_path())
        pull.append(button_row(button))
        box.append(pull)

        common = Section("Common Android locations")
        for path in [
            "/sdcard/Download",
            "/sdcard/DCIM",
            "/sdcard/Pictures",
            "/sdcard/Android",
        ]:
            button = ActionButton(path)
            button.connect(
                "clicked", lambda _b, p=path: self.run_adb("shell", "ls", "-lah", p)
            )
            common.append(button)
        box.append(common)
        return self.scroll_page(box)

    def push_local_path(self, path: Path) -> None:
        remote = self.push_remote.get_text().strip()
        if not remote:
            show_message(
                self,
                "Remote destination required",
                "Enter a destination path on Android.",
                error=True,
            )
            return
        self.run_adb(
            "push",
            str(path),
            remote,
            destructive=True,
            exclusive="adb-push",
        )

    def pull_remote_path(self) -> None:
        remote = self.pull_remote.get_text().strip()
        if not remote:
            show_message(
                self, "Remote path required", "Enter a path on Android.", error=True
            )
            return
        try:
            destination = self.config.output_dir / "downloads"
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            show_message(self, "Could not create download folder", str(exc), error=True)
            return
        self.run_adb("pull", remote, str(destination))

    def build_logcat_page(self) -> Gtk.Widget:
        box = self.page_box()
        section = Section(
            "Live Logcat", "Stream Android logs without freezing the interface."
        )
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.log_level = Gtk.DropDown.new_from_strings(
            ["All", "Verbose", "Debug", "Info", "Warning", "Error", "Fatal", "Crashes"]
        )
        row.append(self.log_level)
        self.log_filter = Gtk.Entry()
        self.log_filter.set_placeholder_text("Optional text filter")
        self.log_filter.set_hexpand(True)
        row.append(self.log_filter)
        start = ActionButton("Start", "media-playback-start-symbolic", suggested=True)
        start.connect("clicked", lambda _b: self.start_logcat())
        stop = ActionButton("Stop", "media-playback-stop-symbolic")
        stop.connect("clicked", lambda _b: self.stop_logcat())
        clear = ActionButton("Clear")
        clear.connect("clicked", lambda _b: self.logcat_buffer.set_text(""))
        save = ActionButton("Save")
        save.connect("clicked", lambda _b: self.save_logcat())
        for button in (start, stop, clear, save):
            row.append(button)
        section.append(row)
        box.append(section)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_min_content_height(420)
        self.logcat_view = Gtk.TextView(
            buffer=self.logcat_buffer,
            editable=False,
            monospace=True,
            wrap_mode=Gtk.WrapMode.NONE,
        )
        scroll.set_child(self.logcat_view)
        box.append(scroll)
        return self.scroll_page(box)

    def start_logcat(self) -> None:
        if not self.adb_required():
            return
        if self.logcat_running:
            show_message(
                self, "Logcat is already running", "Stop the stream first.", error=True
            )
            return
        serial = self.backend.adb_serial
        selected = self.log_level.get_selected()
        levels = {1: "V", 2: "D", 3: "I", 4: "W", 5: "E", 6: "F"}
        args = self.backend.adb("logcat", serial=serial)
        if selected == 7:
            args += ["AndroidRuntime:E", "*:S"]
        elif selected in levels:
            args += [f"*:{levels[selected]}"]
        query = self.log_filter.get_text().strip().lower()

        def line(text: str) -> bool:
            if serial != self.backend.adb_serial:
                return False
            visible = text
            if query:
                visible = "".join(
                    part
                    for part in text.splitlines(keepends=True)
                    if query in part.lower()
                )
            if visible:
                self.logcat_buffer.insert(self.logcat_buffer.get_end_iter(), visible)
                if self.logcat_buffer.get_char_count() > 750_000:
                    start = self.logcat_buffer.get_start_iter()
                    trim_to = self.logcat_buffer.get_iter_at_offset(150_000)
                    self.logcat_buffer.delete(start, trim_to)
            return False

        if self.runner.stream(args, line, lambda _rc: self._logcat_stopped()):
            self.logcat_running = True
            self.toast("Logcat started")
        else:
            show_message(
                self,
                "Stream already running",
                "Stop the current streaming command first.",
                error=True,
            )

    def _logcat_stopped(self) -> bool:
        self.logcat_running = False
        return False

    def stop_logcat(self) -> None:
        self.runner.stop_stream()
        self.logcat_running = False

    def save_logcat(self) -> None:
        text = self.logcat_buffer.get_text(
            self.logcat_buffer.get_start_iter(), self.logcat_buffer.get_end_iter(), True
        )
        try:
            path = self.backend.output_path("logs", "logcat", ".txt")
            path.write_text(text, encoding="utf-8")
        except OSError as exc:
            show_message(self, "Could not save Logcat", str(exc), error=True)
            return
        show_message(self, "Logcat saved", str(path))

    def build_screen_page(self) -> Gtk.Widget:
        box = self.page_box()
        capture = Section("Capture", "Take a screenshot or record the Android display.")
        screenshot = ActionButton(
            "Take screenshot", "camera-photo-symbolic", suggested=True
        )
        screenshot.connect("clicked", lambda _b: self.take_screenshot())
        record = ActionButton("Record 30 seconds", "media-record-symbolic")
        record.connect("clicked", lambda _b: self.record_screen(30))
        capture.append(button_row(screenshot, record))
        box.append(capture)

        mirror = Section(
            "scrcpy", "Mirror and control Android using scrcpy when installed."
        )
        normal = ActionButton("Open scrcpy", "video-display-symbolic", suggested=True)
        normal.connect("clicked", lambda _b: self.launch_scrcpy([]))
        view = ActionButton("View only")
        view.connect("clicked", lambda _b: self.launch_scrcpy(["--no-control"]))
        off = ActionButton("Turn device screen off")
        off.connect("clicked", lambda _b: self.launch_scrcpy(["--turn-screen-off"]))
        mirror.append(button_row(normal, view, off))
        box.append(mirror)
        return self.scroll_page(box)

    def take_screenshot(self) -> None:
        if not self.adb_required():
            return
        serial = self.backend.adb_serial
        try:
            local = self.backend.output_path("screenshots", "screenshot", ".png")
        except OSError as exc:
            show_message(self, "Could not create screenshot path", str(exc), error=True)
            return
        remote = f"/sdcard/.droiddeck-{local.stem}.png"

        def pulled(result: Result) -> None:
            if result.ok and local.is_file():
                self.run_adb("shell", "rm", "-f", remote, serial=serial)
                show_message(self, "Screenshot saved", str(local))
            else:
                show_message(
                    self,
                    "Screenshot pull failed",
                    "The copy remains on the device so it can be recovered manually.\n\n"
                    + (result.output or remote),
                    error=True,
                )

        def captured(result: Result) -> None:
            if not result.ok:
                show_message(self, "Screenshot failed", result.output, error=True)
                return
            self.run_adb(
                "pull",
                remote,
                str(local),
                done=pulled,
                serial=serial,
                exclusive="screenshot",
            )

        self.run_adb(
            "shell",
            "screencap",
            "-p",
            remote,
            done=captured,
            serial=serial,
            exclusive="screenshot",
        )

    def record_screen(self, seconds: int) -> None:
        if not self.adb_required():
            return
        serial = self.backend.adb_serial
        try:
            local = self.backend.output_path("recordings", "screen", ".mp4")
        except OSError as exc:
            show_message(self, "Could not create recording path", str(exc), error=True)
            return
        remote = f"/sdcard/.droiddeck-{local.stem}.mp4"

        def pulled(result: Result) -> None:
            if result.ok and local.is_file():
                self.run_adb("shell", "rm", "-f", remote, serial=serial)
                show_message(self, "Screen recording saved", str(local))
            else:
                show_message(
                    self,
                    "Recording pull failed",
                    "The recording remains on the device so it can be recovered manually.\n\n"
                    + (result.output or remote),
                    error=True,
                )

        def recorded(result: Result) -> None:
            if not result.ok:
                show_message(self, "Screen recording failed", result.output, error=True)
                return
            self.run_adb(
                "pull",
                remote,
                str(local),
                done=pulled,
                serial=serial,
                exclusive="screen-recording",
            )

        self.run_adb(
            "shell",
            "screenrecord",
            "--time-limit",
            str(seconds),
            remote,
            done=recorded,
            serial=serial,
            exclusive="screen-recording",
        )

    def launch_scrcpy(self, extra: list[str]) -> None:
        if self.adb_required() and self.tool_required("scrcpy"):
            if not self.runner.spawn_detached(
                ["scrcpy", "--serial", self.backend.adb_serial, *extra]
            ):
                show_message(
                    self,
                    "Could not launch scrcpy",
                    "Review Command Output for details.",
                    error=True,
                )

    # ---------- ADB tools ----------
    def build_adb_tools_page(self) -> Gtk.Widget:
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

        wireless = Section(
            "Wireless ADB", "Pair or connect to Android's wireless debugging service."
        )
        group, self.pair_address = entry_group("Pairing address", "192.168.1.10:37123")
        wireless.append(group)
        self.pair_code = Adw.PasswordEntryRow(
            title="Pairing code",
            text="",
        )
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
            "ADB shell",
            "Open an interactive terminal or run one Android shell command.",
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

    def run_shell_command(self) -> None:
        command = self.shell_command.get_text().strip()
        if not command:
            return
        confirm(
            self,
            "Run raw ADB shell command?",
            "DroidDeck does not inspect arbitrary Android shell commands for destructive behavior, so dry-run cannot protect this action.\n\n"
            f"adb shell {command}",
            lambda: self.run_adb("shell", command, exclusive="adb-shell"),
            destructive=False,
        )

    def confirm_adb_reboot(self, target: str) -> None:
        label = target or "Android"
        confirm(
            self,
            f"Reboot to {label}?",
            "The selected device will reboot immediately.",
            lambda: self.run_adb(
                "reboot",
                *([target] if target else []),
                destructive=True,
                exclusive="adb-reboot",
            ),
            destructive=True,
        )

    def adb_pair(self) -> None:
        address = self.pair_address.get_text().strip()
        code = self.pair_code.get_text().strip()
        if not self.backend.validate_host_port(address):
            show_message(
                self,
                "Invalid pairing address",
                "Enter host:port, for example 192.168.1.10:37123.",
                error=True,
            )
            return
        if len(code) != 6 or not code.isdigit():
            show_message(
                self,
                "Invalid pairing code",
                "Enter the six-digit Android pairing code.",
                error=True,
            )
            return
        if self.run_tool(
            ["adb", "pair", address, code],
            display_args=["adb", "pair", address, "••••••"],
            exclusive="adb-pair",
        ):
            self.pair_code.set_text("")

    def adb_connect(self) -> None:
        address = self.connect_address.get_text().strip()
        if not self.backend.validate_host_port(address):
            show_message(
                self,
                "Invalid connection address",
                "Enter host:port, for example 192.168.1.10:5555.",
                error=True,
            )
            return
        self.run_tool(["adb", "connect", address], exclusive="adb-connect")

    def open_adb_shell(self) -> None:
        if self.adb_required():
            self.launch_terminal(["adb", "-s", self.backend.adb_serial, "shell"])

    # ---------- Diagnostics ----------
    def build_diagnostics_page(self) -> Gtk.Widget:
        box = self.page_box()
        report = Section(
            "Diagnostic reports",
            "Collect device state for development, bug reports, and ROM troubleshooting.",
        )
        folder = ActionButton(
            "Generate diagnostic folder", "folder-new-symbolic", suggested=True
        )
        folder.connect("clicked", lambda _b: self.generate_diagnostic_folder())
        bugreport = ActionButton("Generate full adb bugreport")
        bugreport.connect("clicked", lambda _b: self.generate_bugreport())
        report.append(button_row(folder, bugreport))
        box.append(report)

        doctor = Section(
            "Dependency doctor",
            "Optional features activate automatically when their tools are installed.",
        )
        self.dependency_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        doctor.append(self.dependency_list)
        refresh = ActionButton("Refresh dependency status", "view-refresh-symbolic")
        refresh.connect("clicked", lambda _b: self.refresh_dependencies())
        doctor.append(refresh)
        box.append(doctor)

        performance = Section("Performance snapshots")
        cpu = ActionButton("CPU / processes")
        cpu.connect("clicked", lambda _b: self.run_adb("shell", "top", "-b", "-n", "1"))
        memory = ActionButton("Memory")
        memory.connect(
            "clicked", lambda _b: self.run_adb("shell", "cat", "/proc/meminfo")
        )
        graphics = ActionButton("Graphics")
        graphics.connect(
            "clicked", lambda _b: self.run_adb("shell", "dumpsys", "gfxinfo")
        )
        battery = ActionButton("Battery stats")
        battery.connect(
            "clicked", lambda _b: self.run_adb("shell", "dumpsys", "batterystats")
        )
        performance.append(button_row(cpu, memory, graphics, battery))
        box.append(performance)
        return self.scroll_page(box)

    def refresh_dependencies(self) -> None:
        if not hasattr(self, "dependency_list"):
            return
        while self.dependency_list.get_first_child():
            self.dependency_list.remove(self.dependency_list.get_first_child())
        for name, available, description in self.backend.dependencies():
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            status = Gtk.Label(label="✓" if available else "✗")
            status.add_css_class("status-ok" if available else "status-bad")
            row.append(status)
            label = Gtk.Label(label=f"{name} — {description}", xalign=0)
            label.set_hexpand(True)
            row.append(label)
            self.dependency_list.append(row)

    def generate_diagnostic_folder(self) -> None:
        if not self.adb_required():
            return
        serial = self.backend.adb_serial
        try:
            folder = self.backend.output_path("reports", "diagnostic", "")
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            show_message(self, "Could not create report folder", str(exc), error=True)
            return
        jobs = [
            ("properties.txt", self.backend.adb("shell", "getprop", serial=serial)),
            (
                "packages.txt",
                self.backend.adb(
                    "shell", "pm", "list", "packages", "-f", serial=serial
                ),
            ),
            (
                "battery.txt",
                self.backend.adb("shell", "dumpsys", "battery", serial=serial),
            ),
            (
                "memory.txt",
                self.backend.adb("shell", "cat", "/proc/meminfo", serial=serial),
            ),
            ("storage.txt", self.backend.adb("shell", "df", "-h", serial=serial)),
            ("kernel.txt", self.backend.adb("shell", "uname", "-a", serial=serial)),
            ("logcat.txt", self.backend.adb("logcat", "-d", serial=serial)),
        ]
        pending = {name for name, _args in jobs}
        failures: list[str] = []

        def finish_if_complete() -> None:
            if pending:
                return
            if failures:
                show_message(
                    self,
                    "Diagnostic folder completed with errors",
                    f"Saved to {folder}\n\n" + "\n".join(failures),
                    error=True,
                )
            else:
                show_message(self, "Diagnostic folder complete", str(folder))

        def callback(name: str) -> Callable[[Result], None]:
            def done(result: Result) -> None:
                try:
                    (folder / name).write_text(result.output, encoding="utf-8")
                except OSError as exc:
                    failures.append(f"{name}: {exc}")
                if not result.ok:
                    failures.append(f"{name}: command exited {result.returncode}")
                pending.discard(name)
                finish_if_complete()

            return done

        for name, args in jobs:
            if not self.runner.run(args, callback(name)):
                failures.append(f"{name}: could not start command")
                pending.discard(name)
        finish_if_complete()

    def generate_bugreport(self) -> None:
        if not self.adb_required():
            return
        serial = self.backend.adb_serial
        try:
            path = self.backend.output_path("bugreports", "bugreport", ".zip")
        except OSError as exc:
            show_message(self, "Could not create bug-report path", str(exc), error=True)
            return

        def done(result: Result) -> None:
            success = result.ok and path.is_file()
            show_message(
                self,
                "Bug report complete" if success else "Bug report failed",
                str(path)
                if success
                else (result.output or "No report file was created."),
                error=not success,
            )

        self.run_adb(
            "bugreport", str(path), done=done, serial=serial, exclusive="bugreport"
        )
