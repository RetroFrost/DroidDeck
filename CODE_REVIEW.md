# DroidDeck GTK 0.2.0 Code Review

Review scope: Python/GTK architecture, asynchronous process execution, ADB targeting, Fastboot/Heimdall safety, file handling, configuration, shutdown behavior, desktop installation, Python packaging, and regression tests.

## High-severity findings fixed

1. **Raw Fastboot safety bypass** — Option-prefixed write commands could evade the previous first-token assumptions. The classifier now scans the full argument vector and treats flash, erase, format, update, logical-partition writes, `flash:raw`, `flashall`, OEM commands, and non-query `flashing` commands conservatively.
2. **Unselected Fastboot target** — Fastboot actions could be formed without a selected serial. Every Fastboot operation now requires an explicitly detected target and uses `fastboot -s SERIAL`.
3. **Raw write operations bypassing Dry Run/Expert mode** — Raw Fastboot and Heimdall writes now pass through the same classification, Expert-mode, Dry-Run, exclusive-operation, preview, and confirmation layers as structured actions.
4. **Guessed Samsung partitions** — The UI previously offered assumed partition names. The model now starts empty and is populated only from a successful PIT scan of the current device.
5. **Stale PIT data across devices/sessions** — PIT mappings are invalidated on detection, reset, failure, completed rebooting operations, and other state transitions.
6. **Concurrent flashing** — Fastboot and Heimdall operations now use exclusive runner keys, preventing overlapping writes.
7. **Installed launcher failure** — The installed command is a symlink; the old launcher looked for `src/` beside the symlink and failed with `No module named droiddeck_gtk`. The launcher now resolves symlink chains before locating the application root.

## Medium-severity findings fixed

- Raw argument parsing now uses `shlex.split()` and command previews use `shlex.join()`; quoted paths are preserved and no host shell is invoked.
- Heimdall raw commands now respect open `--no-reboot` sessions, require `--resume` when tracked, and close/reset tracked state correctly.
- ADB device-switch races are guarded; stale callbacks cannot overwrite the newly selected device.
- Pairing codes use a password row, are cleared after launch, and are redacted from the visible command log.
- Screenshot and screen-record pulls no longer delete the only recoverable device-side copy after a failed transfer.
- Fixed file-dialog callback signature, retained dialog lifetimes, ignored normal cancellation, and rejected non-local chooser results cleanly.
- Example strings are no longer inserted as live `Adw.EntryRow` values.
- Logcat output is batched and bounded; stopping a stream no longer waits on the GTK thread.
- scrcpy is launched as a detached helper and no longer prevents closing DroidDeck for its entire lifetime.
- Late worker callbacks are discarded after shutdown.
- Configuration booleans are strictly parsed, writes are atomic, permissions are `0600`, and failed saves roll the UI back.
- Output names use microseconds and sanitized components to avoid collisions and path traversal.
- Host/port, package, partition, filesystem, device-list, property, and PIT parsing are stricter.
- Output directory and firmware mapping resolution handle filesystem errors and symlink loops.
- The Python console entry point now reports missing/old GTK dependencies cleanly instead of producing a traceback.
- Desktop-file generation no longer breaks on install prefixes containing spaces, ampersands, dollar signs, or other replacement metacharacters.

## GTK / GNOME review

The original prototype used GTK widgets but did not follow modern GNOME application structure. Version 0.2.0 now uses:

- `Adw.ApplicationWindow`
- `Adw.NavigationSplitView`
- `Adw.NavigationPage`
- `Adw.ToolbarView` and `Adw.HeaderBar`
- `Adw.ViewStack` and `Adw.ViewSwitcherSidebar`
- `Adw.Breakpoint` for adaptive behavior
- `Adw.PreferencesGroup`, `Adw.ActionRow`, `Adw.EntryRow`, and `Adw.SwitchRow`
- `Adw.AlertDialog` and `Adw.ToastOverlay`
- `Gtk.FileDialog`

Custom CSS is limited to semantic status/output styling; Libadwaita controls window chrome, spacing, cards, light/dark appearance, and standard interactions.

## Automated verification

- 30 pytest regression tests
- Python compilation passed
- Ruff lint passed
- Ruff formatting check passed
- Bash syntax checks passed
- No `shell=True`, `os.system`, `eval`, `exec`, deprecated `Gtk.MessageDialog`, old `Gtk.Dialog`, or `Gtk.StackSidebar` patterns found
- Wheel build and isolated wheel install passed
- Wheel console `--version` passed without GI installed
- Missing-GI console startup returned a clear dependency error
- Source launcher `--version` passed without GI installed
- User install, desktop entry, symlinked launch, and uninstall passed with a prefix containing spaces, `&`, and `$`
- AppStream XML and desktop template parsing passed

## Remaining validation boundaries

The review cannot prove the absence of every future or hardware-specific bug. Two important test boundaries remain:

1. The build environment did not have GTK 4, Libadwaita, or PyGObject installed, so a real window could not be instantiated there. GTK API use was checked against current official documentation, imports were exercised with test stubs, and all non-GUI paths were tested.
2. No physical Android, Fastboot, or Samsung Download Mode device was attached. No real flashing success is claimed. Read-only detection/PIT operations and Dry Run should be tested first on the target machine and device.
