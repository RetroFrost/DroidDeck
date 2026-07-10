# Validation — DroidDeck GTK 0.2.0

## Automated checks completed

```text
pytest                         30 passed
ruff check                     passed
ruff format --check            passed
python compileall              passed
bash -n                        passed
wheel build                    passed
isolated wheel install         passed
source --version               passed
installed-symlink --version    passed
missing-GI error path          passed
AppStream XML parse            passed
desktop template parse         passed
```

## Regression coverage

- ADB, Fastboot, property, and PIT parsers
- package, partition, filesystem, and host/port validators
- Fastboot dangerous/state-changing classification, including option-prefixed and vendor raw commands
- Heimdall dangerous-command classification
- strict configuration parsing, atomic writes, private permissions, and temporary-file cleanup
- shell-safe command quoting/splitting round trips
- Dry Run prevents actual execution
- command execution does not invoke a host shell
- exclusive operation keys block overlap
- streamed output is delivered completely
- output paths are sanitized and unique
- detached helpers are not counted as active in-app work
- queued callbacks are dropped after runner shutdown
- modern Libadwaita structure is present
- deprecated GTK dialog/sidebar patterns are absent
- raw flashing paths use quote-aware parsing and safety classification
- Heimdall does not guess partitions
- Fastboot commands target a selected serial
- pairing codes are redacted
- file-dialog callbacks accept GIO user data
- examples are not inserted as executable entry values
- raw Heimdall commands respect tracked resume state
- duplicate method definitions are rejected

## Installation validation

A complete install/launch/uninstall cycle was run using this prefix:

```text
/tmp/Droid Deck & Test $x
```

This verified:

- source copy
- launcher installation
- launcher symlink resolution
- icon and AppStream installation
- desktop-entry generation and Exec quoting
- `droiddeck-gtk --version` through the installed symlink
- cleanup by `uninstall.sh`

## Packaging validation

A wheel was built without dependency downloads and installed into an isolated virtual environment. The console entry point returned `0.2.0` without importing GTK, and a normal launch without GI returned a concise dependency message rather than a traceback.

## Static safety search

No occurrences were found in application source for:

- `shell=True`
- `os.system`
- `eval`
- `exec`
- `Gtk.MessageDialog`
- `Gtk.Dialog`
- `Gtk.StackSidebar`

## Environment limitations

The build container did not include GTK 4, Libadwaita, or PyGObject and could not install them, so a real window startup was not performed there. The application requires GTK 4.10+ and Libadwaita 1.5+; API usage was reviewed against official documentation.

No physical ADB, Fastboot, or Samsung Download Mode hardware was attached. Real device flashing was intentionally not claimed as tested.
