from __future__ import annotations

from pathlib import Path

from gi.repository import Adw, Gtk

from .backend import Result
from .widgets import (
    ActionButton,
    Section,
    button_row,
    choose_file,
    entry_group,
    show_message,
    typed_confirm,
)


class FlashPagesMixin:
    # ---------- Fastboot ----------
    def build_fastboot_page(self) -> Gtk.Widget:
        box = self.page_box()

        device = Section(
            "Fastboot device",
            "Fastboot is a separate USB mode. Detect and explicitly select the target before any operation.",
        )
        self.fastboot_status = Gtk.Label(label="Not checked", xalign=0, wrap=True)
        device.append(self.fastboot_status)
        self.fastboot_model = Gtk.StringList.new(["No Fastboot device selected"])
        self.fastboot_dropdown = Gtk.DropDown(model=self.fastboot_model)
        self.fastboot_dropdown.set_hexpand(True)
        self.fastboot_dropdown.connect(
            "notify::selected", self.on_fastboot_device_selected
        )
        device.append(self.fastboot_dropdown)
        detect = ActionButton("Detect devices", "view-refresh-symbolic", suggested=True)
        detect.connect("clicked", lambda _button: self.fastboot_detect())
        variables = ActionButton("Get all variables")
        variables.connect(
            "clicked", lambda _button: self.fastboot_run(["getvar", "all"])
        )
        slot = ActionButton("Show current slot")
        slot.connect(
            "clicked", lambda _button: self.fastboot_run(["getvar", "current-slot"])
        )
        device.append(button_row(detect, variables, slot))
        box.append(device)

        controls = Section(
            "Boot and slot controls",
            "These commands change device state. Dry run previews them without execution.",
        )
        actions = [
            ("Reboot Android", ["reboot"]),
            ("Reboot bootloader", ["reboot-bootloader"]),
            ("Enter fastbootd", ["reboot", "fastboot"]),
            ("Request recovery", ["reboot", "recovery"]),
        ]
        buttons: list[Gtk.Widget] = []
        for label, args in actions:
            button = ActionButton(label)
            button.connect(
                "clicked",
                lambda _button, command=args: self.fastboot_run(
                    command, state_changing=True
                ),
            )
            buttons.append(button)
        controls.append(button_row(*buttons))

        slot_a = ActionButton("Set slot A")
        slot_a.connect("clicked", lambda _button: self.fastboot_set_slot("a"))
        slot_b = ActionButton("Set slot B")
        slot_b.connect("clicked", lambda _button: self.fastboot_set_slot("b"))
        boot_image = ActionButton("Temporarily boot image", suggested=True)
        boot_image.connect("clicked", lambda _button: self.fastboot_choose_boot_image())
        controls.append(button_row(slot_a, slot_b, boot_image))
        box.append(controls)

        danger = Section(
            "Fastboot danger zone",
            "Expert mode and typed confirmation are required. A wrong partition, image, or lock state can make the device unbootable.",
        )
        row, self.fastboot_partition = entry_group("Partition", "boot", "boot")
        danger.append(row)
        row, self.fastboot_format_type = entry_group(
            "Format filesystem", "ext4", "ext4"
        )
        danger.append(row)
        flash = ActionButton("Flash image", destructive=True)
        flash.connect("clicked", lambda _button: self.fastboot_flash())
        erase = ActionButton("Erase partition", destructive=True)
        erase.connect("clicked", lambda _button: self.fastboot_erase())
        format_button = ActionButton("Format partition", destructive=True)
        format_button.connect("clicked", lambda _button: self.fastboot_format())
        danger.append(button_row(flash, erase, format_button))

        lock_buttons = []
        for label, operation in [
            ("Unlock bootloader", "unlock"),
            ("Lock bootloader", "lock"),
            ("Unlock critical", "unlock_critical"),
            ("Lock critical", "lock_critical"),
        ]:
            button = ActionButton(label, destructive=True)
            button.connect(
                "clicked",
                lambda _button, selected=operation: self.fastboot_lock_change(selected),
            )
            lock_buttons.append(button)
        danger.append(button_row(*lock_buttons))
        box.append(danger)

        raw = Section(
            "Raw Fastboot arguments",
            "Shell-style quoting is supported, but no host shell is invoked. Dangerous commands still require Expert mode, dry-run handling, and typed confirmation.",
        )
        row, self.fastboot_raw = entry_group("Arguments", "getvar product")
        raw.append(row)
        raw_button = ActionButton("Run raw arguments")
        raw_button.connect("clicked", lambda _button: self.fastboot_raw_run())
        raw.append(raw_button)
        box.append(raw)
        return self.scroll_page(box)

    def fastboot_detect(self) -> None:
        def done(result: Result) -> None:
            devices = self.backend.parse_fastboot_devices(result.stdout)
            self.fastboot_devices = devices
            labels = [device.label for device in devices] or [
                "No Fastboot device found"
            ]
            self.fastboot_model.splice(0, self.fastboot_model.get_n_items(), labels)
            self.fastboot_dropdown.set_selected(0)
            self.fastboot_serial = devices[0].serial if devices else ""
            self.fastboot_status.set_text(
                f"Selected: {self.fastboot_serial}"
                if self.fastboot_serial
                else "No Fastboot device found"
            )

        self.run_tool(
            ["fastboot", "devices"],
            done,
            exclusive="fastboot",
            timeout=15,
        )

    def on_fastboot_device_selected(
        self, dropdown: Gtk.DropDown, _pspec: object
    ) -> None:
        devices = getattr(self, "fastboot_devices", [])
        index = dropdown.get_selected()
        if index >= len(devices):
            return
        self.fastboot_serial = devices[index].serial
        self.fastboot_status.set_text(f"Selected: {self.fastboot_serial}")

    def fastboot_command(self, args: list[str]) -> list[str]:
        return ["fastboot", "-s", self.fastboot_serial, *args]

    def fastboot_run(
        self,
        args: list[str],
        *,
        state_changing: bool | None = None,
        done=None,
    ) -> bool:
        if not self.fastboot_required():
            return False
        dangerous = self.backend.fastboot_is_dangerous(args)
        changes_state = (
            self.backend.fastboot_is_state_changing(args)
            if state_changing is None
            else state_changing
        )
        if dangerous and not self.expert_required("dangerous Fastboot commands"):
            return False
        return self.run_tool(
            self.fastboot_command(args),
            done,
            destructive=changes_state,
            exclusive="fastboot",
        )

    def fastboot_set_slot(self, slot: str) -> None:
        if not self.fastboot_required():
            return
        command = self.fastboot_command(["set_active", slot])
        typed_confirm(
            self,
            "Change active slot",
            f"Set the active A/B slot to {slot.upper()}?\n\nCommand:\n{self.runner.quote(command)}",
            f"SLOT {slot.upper()}",
            lambda: self.fastboot_run(["set_active", slot], state_changing=True),
        )

    def fastboot_choose_boot_image(self) -> None:
        if not self.fastboot_required():
            return

        def selected(path: Path) -> None:
            command = self.fastboot_command(["boot", str(path)])
            typed_confirm(
                self,
                "Temporarily boot image",
                f"Attempt to boot this image without intentionally flashing it:\n\n{path}\n\nCommand:\n{self.runner.quote(command)}",
                "BOOT IMAGE",
                lambda: self.fastboot_run(["boot", str(path)], state_changing=True),
            )

        choose_file(self, "Select image to boot", selected, patterns=["*.img"])

    def _validated_fastboot_partition(self) -> str:
        partition = self.fastboot_partition.get_text().strip()
        if not self.backend.valid_partition(partition):
            show_message(
                self,
                "Invalid partition",
                "Enter a partition token beginning with a letter or number and containing only letters, numbers, dot, underscore, plus, or hyphen.",
                error=True,
            )
            return ""
        return partition

    def fastboot_flash(self) -> None:
        if (
            not self.expert_required("Fastboot flashing")
            or not self.fastboot_required()
        ):
            return
        partition = self._validated_fastboot_partition()
        if not partition:
            return

        def selected(path: Path) -> None:
            command = self.fastboot_command(["flash", partition, str(path)])
            typed_confirm(
                self,
                "Flash Fastboot partition",
                f"Write this image to {partition}:\n\n{path}\n\nVerify compatibility with the exact device.\n\nCommand:\n{self.runner.quote(command)}",
                f"FLASH {partition}",
                lambda: self.fastboot_run(["flash", partition, str(path)]),
            )

        choose_file(
            self,
            f"Select image for {partition}",
            selected,
            patterns=["*.img", "*.bin"],
        )

    def fastboot_erase(self) -> None:
        if not self.expert_required("Fastboot erase") or not self.fastboot_required():
            return
        partition = self._validated_fastboot_partition()
        if not partition:
            return
        command = self.fastboot_command(["erase", partition])
        typed_confirm(
            self,
            "Erase partition",
            f"Permanently erase Fastboot partition {partition}.\n\nCommand:\n{self.runner.quote(command)}",
            f"ERASE {partition}",
            lambda: self.fastboot_run(["erase", partition]),
        )

    def fastboot_format(self) -> None:
        if not self.expert_required("Fastboot format") or not self.fastboot_required():
            return
        partition = self._validated_fastboot_partition()
        filesystem = self.fastboot_format_type.get_text().strip()
        if not partition:
            return
        if not self.backend.valid_filesystem(filesystem):
            show_message(
                self,
                "Invalid filesystem",
                "Enter a simple filesystem token such as ext4 or f2fs.",
                error=True,
            )
            return
        args = [f"format:{filesystem}", partition]
        command = self.fastboot_command(args)
        typed_confirm(
            self,
            "Format partition",
            f"Format {partition} as {filesystem}. This destroys data in that partition.\n\nCommand:\n{self.runner.quote(command)}",
            f"FORMAT {partition}",
            lambda: self.fastboot_run(args),
        )

    def fastboot_lock_change(self, operation: str) -> None:
        if (
            not self.expert_required("bootloader state changes")
            or not self.fastboot_required()
        ):
            return
        mapping = {
            "unlock": (["flashing", "unlock"], "UNLOCK"),
            "lock": (["flashing", "lock"], "LOCK"),
            "unlock_critical": (["flashing", "unlock_critical"], "UNLOCK CRITICAL"),
            "lock_critical": (["flashing", "lock_critical"], "LOCK CRITICAL"),
        }
        args, phrase = mapping[operation]
        command = self.fastboot_command(args)
        typed_confirm(
            self,
            phrase.title(),
            "Changing bootloader lock state may wipe user data. Locking while incompatible software is installed can make the device unbootable."
            f"\n\nCommand:\n{self.runner.quote(command)}",
            phrase,
            lambda: self.fastboot_run(args),
        )

    def fastboot_raw_run(self) -> None:
        raw = self.fastboot_raw.get_text().strip()
        if not raw:
            return
        try:
            args = self.runner.split_args(raw)
        except ValueError as exc:
            show_message(self, "Invalid arguments", str(exc), error=True)
            return
        if not args:
            return
        dangerous = self.backend.fastboot_is_dangerous(args)
        state_changing = self.backend.fastboot_is_state_changing(args)
        if dangerous and not self.expert_required("raw dangerous Fastboot commands"):
            return
        if not self.fastboot_required():
            return
        command = self.fastboot_command(args)
        if dangerous:
            typed_confirm(
                self,
                "Run dangerous raw Fastboot command",
                f"Review the exact command carefully:\n\n{self.runner.quote(command)}",
                "RUN FASTBOOT",
                lambda: self.fastboot_run(args),
            )
            return
        self.fastboot_run(args, state_changing=state_changing)

    # ---------- Heimdall ----------
    def build_heimdall_page(self) -> Gtk.Widget:
        box = self.page_box()

        connection = Section(
            "Samsung Download Mode",
            "Heimdall communicates with Samsung devices in Download Mode. Only one Heimdall operation can run at a time.",
        )
        self.heimdall_status = Gtk.Label(
            label="Not checked", xalign=0, wrap=True, selectable=True
        )
        connection.append(self.heimdall_status)
        detect = ActionButton("Detect device", "view-refresh-symbolic", suggested=True)
        detect.connect("clicked", lambda _button: self.heimdall_detect())
        version = ActionButton("Version")
        version.connect(
            "clicked",
            lambda _button: self.run_tool(
                ["heimdall", "version"], exclusive="heimdall"
            ),
        )
        help_button = ActionButton("Command help")
        help_button.connect(
            "clicked",
            lambda _button: self.run_tool(["heimdall", "help"], exclusive="heimdall"),
        )
        connection.append(button_row(detect, version, help_button))
        box.append(connection)

        pit = Section(
            "PIT tools",
            "Scan the exact device partition table before flashing. DroidDeck will not assume RECOVERY, BOOT, or any other partition name.",
        )
        self.heimdall_partition_model = Gtk.StringList.new([])
        self.heimdall_partition = Gtk.DropDown(model=self.heimdall_partition_model)
        self.heimdall_partition.set_hexpand(True)
        self.heimdall_partition.set_tooltip_text("Run Print PIT to populate partitions")
        pit.append(self.heimdall_partition)
        print_button = ActionButton(
            "Print PIT", "document-open-symbolic", suggested=True
        )
        print_button.connect("clicked", lambda _button: self.heimdall_print_pit())
        download_button = ActionButton("Download raw PIT")
        download_button.connect("clicked", lambda _button: self.heimdall_download_pit())
        reset_button = ActionButton("Reset resume tracking")
        reset_button.connect("clicked", lambda _button: self.heimdall_reset_resume())
        pit.append(button_row(print_button, download_button, reset_button))
        box.append(pit)

        single = Section(
            "Single-partition flash",
            "Select a partition discovered from the current device PIT and one compatible image or binary.",
        )
        self.heimdall_file: Path | None = None
        self.heimdall_file_label = Gtk.Label(
            label="No image selected", xalign=0, wrap=True, selectable=True
        )
        single.append(self.heimdall_file_label)
        choose = ActionButton("Choose image or file", "document-open-symbolic")
        choose.connect(
            "clicked",
            lambda _button: choose_file(
                self, "Select file to flash", self.set_heimdall_file
            ),
        )
        single.append(choose)
        self.heimdall_no_reboot = Adw.SwitchRow(
            title="Keep Heimdall session open",
            subtitle="Pass --no-reboot and automatically use --resume for the next operation.",
        )
        self.heimdall_verbose = Adw.SwitchRow(
            title="Verbose Heimdall output",
            subtitle="Include additional protocol details in Command Output.",
        )
        single.append(self.heimdall_no_reboot)
        single.append(self.heimdall_verbose)
        flash = ActionButton("Flash selected partition", destructive=True)
        flash.connect("clicked", lambda _button: self.heimdall_flash_single())
        single.append(flash)
        box.append(single)

        multiple = Section(
            "Multi-partition firmware set",
            "Enter one mapping per line as PARTITION=/path/file. Partitions must exist in the scanned PIT and may appear only once.",
        )
        self.heimdall_multi_buffer = Gtk.TextBuffer()
        multi_view = Gtk.TextView(
            buffer=self.heimdall_multi_buffer,
            monospace=True,
            wrap_mode=Gtk.WrapMode.NONE,
        )
        multi_view.set_size_request(-1, 150)
        multi_scroll = Gtk.ScrolledWindow()
        multi_scroll.set_child(multi_view)
        multiple.append(multi_scroll)
        multi_flash = ActionButton("Flash firmware set", destructive=True)
        multi_flash.connect("clicked", lambda _button: self.heimdall_flash_multiple())
        multiple.append(multi_flash)
        box.append(multiple)

        repartition = Section(
            "Repartition and flash",
            "EXTREME RISK: changes the partition layout and wipes data. Use only the exact model and storage-variant PIT.",
        )
        self.heimdall_pit_file: Path | None = None
        self.heimdall_pit_label = Gtk.Label(
            label="No PIT selected", xalign=0, wrap=True, selectable=True
        )
        repartition.append(self.heimdall_pit_label)
        choose_pit = ActionButton("Choose PIT file")
        choose_pit.connect(
            "clicked",
            lambda _button: choose_file(
                self,
                "Select PIT file",
                self.set_heimdall_pit_file,
                patterns=["*.pit"],
            ),
        )
        repartition_button = ActionButton(
            "Repartition and flash firmware set", destructive=True
        )
        repartition_button.connect(
            "clicked", lambda _button: self.heimdall_repartition()
        )
        repartition.append(button_row(choose_pit, repartition_button))
        box.append(repartition)

        raw = Section(
            "Raw Heimdall arguments",
            "Shell-style quoting is supported and no host shell is used. Flash and repartition commands still require Expert mode, dry-run handling, and typed confirmation.",
        )
        row, self.heimdall_raw = entry_group("Arguments", "print-pit --verbose")
        raw.append(row)
        raw_button = ActionButton("Run raw arguments")
        raw_button.connect("clicked", lambda _button: self.heimdall_raw_run())
        raw.append(raw_button)
        box.append(raw)
        return self.scroll_page(box)

    def clear_heimdall_pit(self) -> None:
        self.backend.heimdall_partitions.clear()
        self.heimdall_partition_model.splice(
            0, self.heimdall_partition_model.get_n_items(), []
        )

    def heimdall_detect(self) -> None:
        if self.backend.heimdall_resume:
            show_message(
                self,
                "Heimdall session is still open",
                "The previous command used --no-reboot. Continue with a --resume operation, or reset resume tracking after reconnecting/rebooting the device.",
                error=True,
            )
            return
        self.clear_heimdall_pit()

        def done(result: Result) -> None:
            self.heimdall_status.set_text(
                "Download Mode device detected"
                if result.ok
                else "No compatible Download Mode device detected"
            )

        self.run_tool(
            ["heimdall", "detect"],
            done,
            exclusive="heimdall",
            timeout=20,
        )

    def heimdall_session_args(self) -> list[str]:
        args: list[str] = []
        if self.backend.heimdall_resume:
            args.append("--resume")
        if self.heimdall_no_reboot.get_active():
            args.append("--no-reboot")
        if self.heimdall_verbose.get_active():
            args.append("--verbose")
        return args

    def heimdall_print_pit(self) -> None:
        self.clear_heimdall_pit()
        try:
            path = self.backend.output_path("pit", "print-pit", ".txt")
        except OSError as exc:
            show_message(self, "Could not create PIT output path", str(exc), error=True)
            return
        args = ["heimdall", "print-pit"]
        if self.backend.heimdall_resume:
            args.append("--resume")
        args.append("--no-reboot")

        def done(result: Result) -> None:
            if not result.ok:
                self.heimdall_status.set_text("PIT scan failed")
                return
            if not result.dry_run:
                self.backend.heimdall_resume = True
            parts = self.backend.parse_pit(result.output)
            if not parts:
                self.heimdall_status.set_text(
                    "PIT output contained no usable partitions"
                )
                show_message(
                    self,
                    "No partitions parsed",
                    "Heimdall completed, but DroidDeck could not parse partition names. Review Command Output before flashing.",
                    error=True,
                )
                return
            try:
                path.write_text(result.output, encoding="utf-8")
            except OSError as exc:
                show_message(self, "Could not save PIT output", str(exc), error=True)
                return
            self.backend.heimdall_partitions = set(parts)
            self.heimdall_partition_model.splice(
                0, self.heimdall_partition_model.get_n_items(), parts
            )
            self.heimdall_partition.set_selected(0)
            self.heimdall_status.set_text(
                f"Loaded {len(parts)} PIT partitions; saved to {path}. Next Heimdall command uses --resume."
            )
            self.toast(f"Loaded {len(parts)} PIT partitions")

        self.run_tool(args, done, exclusive="heimdall")

    def heimdall_download_pit(self) -> None:
        try:
            path = self.backend.output_path("pit", "device", ".pit")
        except OSError as exc:
            show_message(self, "Could not create PIT output path", str(exc), error=True)
            return
        args = ["heimdall", "download-pit", "--output", str(path)]
        if self.backend.heimdall_resume:
            args.append("--resume")
        args.append("--no-reboot")

        def done(result: Result) -> None:
            if result.ok and not result.dry_run:
                self.backend.heimdall_resume = True
            if result.ok and path.is_file():
                self.heimdall_status.set_text(
                    f"PIT downloaded to {path}; next command uses --resume."
                )
                self.toast("PIT downloaded")
            elif result.ok:
                show_message(
                    self,
                    "PIT file missing",
                    "Heimdall reported success but the requested PIT file was not created.",
                    error=True,
                )

        self.run_tool(args, done, exclusive="heimdall")

    def heimdall_reset_resume(self) -> None:
        self.backend.heimdall_resume = False
        self.clear_heimdall_pit()
        self.heimdall_status.set_text(
            "Local --resume tracking reset. Reconnect or reboot the device if the Heimdall session is still open."
        )

    def set_heimdall_file(self, path: Path) -> None:
        if not path.is_file():
            show_message(self, "File not found", str(path), error=True)
            return
        self.heimdall_file = path
        self.heimdall_file_label.set_text(str(path))

    def set_heimdall_pit_file(self, path: Path) -> None:
        if not path.is_file():
            show_message(self, "PIT file not found", str(path), error=True)
            return
        self.heimdall_pit_file = path
        self.heimdall_pit_label.set_text(str(path))

    def selected_heimdall_partition(self) -> str:
        item = self.heimdall_partition.get_selected_item()
        partition = item.get_string() if item else ""
        if partition and partition in self.backend.heimdall_partitions:
            return partition
        return ""

    def update_heimdall_session(self, result: Result, *, no_reboot: bool) -> None:
        if result.dry_run:
            self.heimdall_status.set_text(
                "Dry run preview complete; Heimdall session state was not changed."
            )
            return
        if result.ok:
            self.backend.heimdall_resume = no_reboot
            if not no_reboot:
                self.clear_heimdall_pit()
            self.heimdall_status.set_text(
                "Operation complete; --resume required for the next Heimdall command."
                if no_reboot
                else "Operation complete. Re-scan PIT before another flash."
            )
            self.toast("Heimdall operation complete")
        else:
            self.backend.heimdall_resume = False
            self.clear_heimdall_pit()
            self.heimdall_status.set_text(
                "Heimdall operation failed. Reconnect the device and re-scan PIT before retrying."
            )

    def _heimdall_done_callback(self, no_reboot: bool):
        return lambda result: self.update_heimdall_session(result, no_reboot=no_reboot)

    def _require_scanned_pit(self) -> bool:
        if self.backend.heimdall_partitions:
            return True
        show_message(
            self,
            "Scan the device PIT first",
            "Run Print PIT successfully before selecting or mapping partitions. DroidDeck does not guess Samsung partition names.",
            error=True,
        )
        return False

    def heimdall_flash_single(self) -> None:
        if (
            not self.expert_required("Heimdall flashing")
            or not self._require_scanned_pit()
            or not self.heimdall_file
        ):
            return
        partition = self.selected_heimdall_partition()
        if not partition:
            show_message(
                self,
                "No PIT partition selected",
                "Select a scanned partition.",
                error=True,
            )
            return
        no_reboot = self.heimdall_no_reboot.get_active()
        args = [
            "heimdall",
            "flash",
            *self.heimdall_session_args(),
            f"--{partition}",
            str(self.heimdall_file),
        ]
        typed_confirm(
            self,
            "Flash Samsung partition",
            f"Write {self.heimdall_file} to PIT partition {partition}. Verify the exact model and file compatibility. Do not disconnect USB.\n\nCommand:\n{self.runner.quote(args)}",
            f"FLASH {partition}",
            lambda: self.run_tool(
                args,
                self._heimdall_done_callback(no_reboot),
                destructive=True,
                exclusive="heimdall",
            ),
        )

    def parse_heimdall_pairs(self) -> tuple[list[str], str] | None:
        if not self._require_scanned_pit():
            return None
        text = self.heimdall_multi_buffer.get_text(
            self.heimdall_multi_buffer.get_start_iter(),
            self.heimdall_multi_buffer.get_end_iter(),
            True,
        )
        args: list[str] = []
        summary: list[str] = []
        seen: set[str] = set()
        for line_number, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                show_message(
                    self,
                    "Invalid firmware mapping",
                    f"Line {line_number} must be PARTITION=/path/file",
                    error=True,
                )
                return None
            partition, filename = (item.strip() for item in line.split("=", 1))
            if not self.backend.valid_partition(partition):
                show_message(
                    self,
                    "Invalid partition",
                    f"Line {line_number}: {partition}",
                    error=True,
                )
                return None
            if partition not in self.backend.heimdall_partitions:
                show_message(
                    self,
                    "Partition not found in scanned PIT",
                    f"Line {line_number}: {partition}",
                    error=True,
                )
                return None
            if partition in seen:
                show_message(
                    self,
                    "Duplicate partition",
                    f"{partition} appears more than once.",
                    error=True,
                )
                return None
            seen.add(partition)
            try:
                path = Path(filename).expanduser().resolve()
            except (OSError, RuntimeError) as exc:
                show_message(
                    self,
                    "Invalid firmware path",
                    f"Line {line_number}: {exc}",
                    error=True,
                )
                return None
            if not path.is_file():
                show_message(
                    self, "File not found", f"Line {line_number}: {path}", error=True
                )
                return None
            args += [f"--{partition}", str(path)]
            summary.append(f"{partition} ← {path}")
        if not args:
            show_message(
                self,
                "No firmware mappings",
                "Add at least one PARTITION=/path/file line.",
                error=True,
            )
            return None
        return args, "\n".join(summary)

    def heimdall_flash_multiple(self) -> None:
        if not self.expert_required("multi-partition Heimdall flashing"):
            return
        parsed = self.parse_heimdall_pairs()
        if not parsed:
            return
        pairs, summary = parsed
        no_reboot = self.heimdall_no_reboot.get_active()
        args = ["heimdall", "flash", *self.heimdall_session_args(), *pairs]
        typed_confirm(
            self,
            "Flash Samsung firmware set",
            f"The following PIT partitions will be written:\n\n{summary}\n\nA wrong mapping can brick the device.\n\nCommand:\n{self.runner.quote(args)}",
            "FLASH MULTIPLE",
            lambda: self.run_tool(
                args,
                self._heimdall_done_callback(no_reboot),
                destructive=True,
                exclusive="heimdall",
            ),
        )

    def heimdall_repartition(self) -> None:
        if (
            not self.expert_required("Heimdall repartitioning")
            or not self.heimdall_pit_file
        ):
            return
        parsed = self.parse_heimdall_pairs()
        if not parsed:
            return
        pairs, summary = parsed
        no_reboot = self.heimdall_no_reboot.get_active()
        args = [
            "heimdall",
            "flash",
            "--repartition",
            "--pit",
            str(self.heimdall_pit_file),
            *self.heimdall_session_args(),
            *pairs,
        ]
        typed_confirm(
            self,
            "EXTREME DANGER: repartition",
            f"PIT: {self.heimdall_pit_file}\n\n{summary}\n\nRepartitioning changes the partition layout and wipes data. A wrong PIT can hard-brick the device.\n\nCommand:\n{self.runner.quote(args)}",
            "REPARTITION",
            lambda: self.run_tool(
                args,
                self._heimdall_done_callback(no_reboot),
                destructive=True,
                exclusive="heimdall",
            ),
        )

    def heimdall_raw_run(self) -> None:
        raw = self.heimdall_raw.get_text().strip()
        if not raw:
            return
        try:
            args = self.runner.split_args(raw)
        except ValueError as exc:
            show_message(self, "Invalid arguments", str(exc), error=True)
            return
        if not args:
            return
        dangerous = self.backend.heimdall_is_dangerous(args)
        if dangerous and not self.expert_required("raw Heimdall flashing"):
            return
        if self.backend.heimdall_resume and "--resume" not in args:
            show_message(
                self,
                "--resume is required",
                "DroidDeck is tracking an open Heimdall session. Add --resume to the raw arguments, or reset resume tracking after reconnecting or rebooting the device.",
                error=True,
            )
            return
        command = ["heimdall", *args]
        leaves_session_open = "--no-reboot" in args
        touches_session = (
            leaves_session_open
            or "--resume" in args
            or any(token in {"flash", "print-pit", "download-pit"} for token in args)
        )

        def done(result: Result) -> None:
            if result.dry_run or not touches_session:
                return
            if result.ok:
                self.backend.heimdall_resume = leaves_session_open
                if leaves_session_open:
                    self.heimdall_status.set_text(
                        "Raw Heimdall command left the session open; the next command must use --resume."
                    )
                else:
                    self.clear_heimdall_pit()
                    self.heimdall_status.set_text(
                        "Raw Heimdall session completed. Re-scan PIT before flashing again."
                    )
            else:
                self.backend.heimdall_resume = False
                self.clear_heimdall_pit()
                self.heimdall_status.set_text(
                    "Raw Heimdall operation failed. Reconnect the device and re-scan PIT before retrying."
                )

        if dangerous:
            typed_confirm(
                self,
                "Run dangerous raw Heimdall command",
                f"Review the exact command carefully. Raw mode cannot verify partition mappings for you.\n\n{self.runner.quote(command)}",
                "RUN HEIMDALL",
                lambda: self.run_tool(
                    command,
                    done,
                    destructive=True,
                    exclusive="heimdall",
                ),
            )
            return
        self.run_tool(command, done, exclusive="heimdall")
