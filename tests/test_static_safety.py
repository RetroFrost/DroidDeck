from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "droiddeck_gtk"


def source(name: str) -> str:
    return (SRC / name).read_text(encoding="utf-8")


def test_python_files_parse() -> None:
    for path in SRC.glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_no_host_shell_or_eval_escape_hatches() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in SRC.glob("*.py"))
    forbidden = (
        "shell=True",
        "shell = True",
        "os.system(",
        "eval(",
        "exec(",
    )
    for token in forbidden:
        assert token not in combined


def test_no_deprecated_dialog_shell() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in SRC.glob("*.py"))
    for token in ("Gtk.MessageDialog", "Gtk.Dialog(", "Gtk.StackSidebar"):
        assert token not in combined
    assert "Adw.NavigationSplitView" in source("app.py")
    assert "Adw.AlertDialog" in source("widgets.py")
    assert "Gtk.FileDialog" in source("widgets.py")


def test_raw_flashing_uses_quote_aware_parsing_and_safety_classification() -> None:
    text = source("pages_flash.py")
    assert text.count("self.runner.split_args(raw)") >= 2
    assert "self.backend.fastboot_is_dangerous(args)" in text
    assert "self.backend.fastboot_is_state_changing(args)" in text
    assert "self.backend.heimdall_is_dangerous(args)" in text


def test_heimdall_does_not_guess_device_partitions() -> None:
    text = source("pages_flash.py")
    assert "self.heimdall_partition_model = Gtk.StringList.new([])" in text
    assert "parse_pit(result.output)" in text
    assert "not in self.backend.heimdall_partitions" in text


def test_fastboot_commands_always_target_selected_serial() -> None:
    text = source("pages_flash.py")
    assert 'return ["fastboot", "-s", self.fastboot_serial, *args]' in text
    assert "if not self.fastboot_required():" in text


def test_pairing_code_is_redacted_from_command_log() -> None:
    text = source("pages_adb.py")
    assert 'display_args=["adb", "pair", address, "••••••"]' in text
    assert "Adw.PasswordEntryRow" in text


def test_launcher_checks_modern_gtk_and_libadwaita() -> None:
    launcher = source("launcher.py")
    assert "(Gtk.get_major_version(), Gtk.get_minor_version()) < (4, 10)" in launcher
    for symbol in ("AlertDialog", "AboutDialog", "NavigationSplitView", "Breakpoint"):
        assert symbol in launcher
    shell_launcher = (ROOT / "droiddeck-gtk").read_text(encoding="utf-8")
    assert 'exec "$PYTHON_BIN" -m droiddeck_gtk "$@"' in shell_launcher
    assert 'while [[ -L "$SOURCE" ]]' in shell_launcher
    assert "sys.version_info < (3, 10)" in launcher


def test_no_duplicate_method_definitions() -> None:
    for path in SRC.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            names: set[str] = set()
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    assert child.name not in names, (
                        f"duplicate {node.name}.{child.name} in {path.name}"
                    )
                    names.add(child.name)


def test_file_dialog_callbacks_accept_gio_user_data() -> None:
    text = source("widgets.py")
    assert text.count("_user_data: object = None") == 2


def test_entry_examples_are_not_inserted_as_commands() -> None:
    text = source("widgets.py")
    assert "entry.set_text(value or placeholder)" not in text
    assert "if value:" in text
    assert "entry.set_text(value)" in text


def test_raw_heimdall_respects_open_session_tracking() -> None:
    text = source("pages_flash.py")
    assert 'self.backend.heimdall_resume and "--resume" not in args' in text
    assert "self.backend.heimdall_resume = leaves_session_open" in text
