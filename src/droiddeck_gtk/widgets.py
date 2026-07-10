from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk


class Section(Adw.PreferencesGroup):
    """Native Libadwaita group with an append-compatible API."""

    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__(title=title, description=subtitle)

    def append(self, child: Gtk.Widget) -> None:
        self.add(child)


class ActionButton(Gtk.Button):
    def __init__(
        self,
        label: str,
        icon: str | None = None,
        *,
        suggested: bool = False,
        destructive: bool = False,
    ) -> None:
        super().__init__()
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        content.set_halign(Gtk.Align.CENTER)
        if icon:
            content.append(Gtk.Image.new_from_icon_name(icon))
        text = Gtk.Label(label=label)
        text.set_wrap(True)
        content.append(text)
        self.set_child(content)
        self.set_tooltip_text(label)
        if suggested:
            self.add_css_class("suggested-action")
        if destructive:
            self.add_css_class("destructive-action")


def button_row(*widgets: Gtk.Widget) -> Gtk.FlowBox:
    """A wrapping action row that remains usable in narrow windows."""

    row = Gtk.FlowBox(
        selection_mode=Gtk.SelectionMode.NONE,
        column_spacing=8,
        row_spacing=8,
        min_children_per_line=1,
        max_children_per_line=4,
    )
    row.set_halign(Gtk.Align.START)
    row.set_homogeneous(False)
    row.set_margin_top(4)
    row.set_margin_bottom(4)
    for widget in widgets:
        row.insert(widget, -1)
    return row


def entry_group(
    label: str, placeholder: str = "", value: str = ""
) -> tuple[Adw.EntryRow, Adw.EntryRow]:
    entry = Adw.EntryRow(title=label)
    if placeholder:
        entry.set_tooltip_text(f"Example: {placeholder}")
    if value:
        entry.set_text(value)
    return entry, entry


def _dialog_store(parent: Gtk.Window, attribute: str) -> list[object]:
    dialogs = getattr(parent, attribute, None)
    if dialogs is None:
        dialogs = []
        setattr(parent, attribute, dialogs)
    return dialogs


def _short_body(body: str, limit: int = 24000) -> str:
    if len(body) <= limit:
        return body
    half = limit // 2
    return (
        body[:half]
        + "\n\n… middle truncated; see Command Output for complete command output. …\n\n"
        + body[-half:]
    )


def show_message(
    parent: Gtk.Window, title: str, body: str, *, error: bool = False
) -> None:
    dialog = Adw.AlertDialog(heading=title, body=_short_body(body))
    dialog.add_response("ok", "OK")
    dialog.set_default_response("ok")
    dialog.set_close_response("ok")
    if error:
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
    dialogs = _dialog_store(parent, "_alert_dialogs")
    dialogs.append(dialog)

    def response(dlg: Adw.AlertDialog, _response: str) -> None:
        if dlg in dialogs:
            dialogs.remove(dlg)

    dialog.connect("response", response)
    dialog.present(parent)


def confirm(
    parent: Gtk.Window,
    title: str,
    body: str,
    accept: Callable[[], None],
    *,
    destructive: bool = False,
    accept_label: str = "Continue",
) -> None:
    dialog = Adw.AlertDialog(heading=title, body=_short_body(body))
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("accept", accept_label)
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")
    dialog.set_response_appearance(
        "accept",
        Adw.ResponseAppearance.DESTRUCTIVE
        if destructive
        else Adw.ResponseAppearance.SUGGESTED,
    )
    dialogs = _dialog_store(parent, "_alert_dialogs")
    dialogs.append(dialog)

    def response(dlg: Adw.AlertDialog, response_id: str) -> None:
        if dlg in dialogs:
            dialogs.remove(dlg)
        if response_id == "accept":
            accept()

    dialog.connect("response", response)
    dialog.present(parent)


def typed_confirm(
    parent: Gtk.Window,
    title: str,
    body: str,
    phrase: str,
    accept: Callable[[], None],
) -> None:
    dialog = Adw.AlertDialog(heading=title, body=_short_body(body))
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("accept", "Continue")
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")
    dialog.set_response_appearance("accept", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_response_enabled("accept", False)

    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    instruction = Gtk.Label(label=f"Type exactly: {phrase}", xalign=0, wrap=True)
    instruction.add_css_class("heading")
    content.append(instruction)
    entry = Gtk.Entry(placeholder_text=phrase)
    entry.set_activates_default(False)
    content.append(entry)
    dialog.set_extra_child(content)

    def changed(field: Gtk.Entry) -> None:
        dialog.set_response_enabled("accept", field.get_text() == phrase)

    entry.connect("changed", changed)
    dialogs = _dialog_store(parent, "_alert_dialogs")
    dialogs.append(dialog)

    def response(dlg: Adw.AlertDialog, response_id: str) -> None:
        if dlg in dialogs:
            dialogs.remove(dlg)
        if response_id == "accept" and entry.get_text() == phrase:
            accept()

    dialog.connect("response", response)
    dialog.present(parent)

    def focus_entry() -> bool:
        entry.grab_focus()
        return False

    GLib.idle_add(focus_entry)


def _store_file_dialog(parent: Gtk.Window, dialog: Gtk.FileDialog) -> list[object]:
    dialogs = _dialog_store(parent, "_file_dialogs")
    dialogs.append(dialog)
    return dialogs


def _make_filters(patterns: list[str] | None) -> Gio.ListStore | None:
    if not patterns:
        return None
    filters = Gio.ListStore.new(Gtk.FileFilter)
    supported = Gtk.FileFilter()
    supported.set_name("Supported files")
    for pattern in patterns:
        supported.add_pattern(pattern)
    filters.append(supported)
    all_files = Gtk.FileFilter()
    all_files.set_name("All files")
    all_files.add_pattern("*")
    filters.append(all_files)
    return filters


def _is_cancelled(error: GLib.Error) -> bool:
    try:
        return error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED)
    except (AttributeError, TypeError):
        text = str(error).lower()
        return "cancel" in text or "dismiss" in text


def choose_file(
    parent: Gtk.Window,
    title: str,
    selected: Callable[[Path], None],
    *,
    patterns: list[str] | None = None,
) -> None:
    dialog = Gtk.FileDialog(title=title, modal=True)
    filters = _make_filters(patterns)
    if filters is not None:
        dialog.set_filters(filters)
        first_filter = filters.get_item(0)
        if first_filter is not None:
            dialog.set_default_filter(first_filter)
    dialogs = _store_file_dialog(parent, dialog)

    def response(
        source: Gtk.FileDialog, result: Gio.AsyncResult, _user_data: object = None
    ) -> None:
        try:
            file = source.open_finish(result)
            path = file.get_path() if file else None
            if path:
                selected(Path(path))
            else:
                show_message(
                    parent,
                    "Local file required",
                    "DroidDeck currently supports local filesystem paths only.",
                    error=True,
                )
        except GLib.Error as exc:
            if not _is_cancelled(exc):
                show_message(
                    parent, "Could not open file chooser", str(exc), error=True
                )
        finally:
            if source in dialogs:
                dialogs.remove(source)

    dialog.open(parent, None, response)


def choose_folder(
    parent: Gtk.Window, title: str, selected: Callable[[Path], None]
) -> None:
    dialog = Gtk.FileDialog(title=title, modal=True)
    dialogs = _store_file_dialog(parent, dialog)

    def response(
        source: Gtk.FileDialog, result: Gio.AsyncResult, _user_data: object = None
    ) -> None:
        try:
            file = source.select_folder_finish(result)
            path = file.get_path() if file else None
            if path:
                selected(Path(path))
            else:
                show_message(
                    parent,
                    "Local folder required",
                    "DroidDeck currently supports local filesystem folders only.",
                    error=True,
                )
        except GLib.Error as exc:
            if not _is_cancelled(exc):
                show_message(
                    parent, "Could not open folder chooser", str(exc), error=True
                )
        finally:
            if source in dialogs:
                dialogs.remove(source)

    dialog.select_folder(parent, None, response)


def install_css() -> None:
    """Only app-specific semantic styling; Libadwaita owns the chrome."""

    provider = Gtk.CssProvider()
    provider.load_from_data(
        """
        .device-hero { padding: 8px 0; }
        .metric-value { font-size: 1.18em; font-weight: 700; }
        .status-ok { color: @success_color; font-weight: 700; }
        .status-bad { color: @error_color; font-weight: 700; }
        .status-warning { color: @warning_color; font-weight: 700; }
        .command-output { padding: 9px; }
        .output-toolbar { padding: 6px 12px; }
        .monospace { font-family: monospace; }
        """
    )
    display = Gdk.Display.get_default()
    if display:
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
