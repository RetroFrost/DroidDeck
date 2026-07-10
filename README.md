# DroidDeck GTK 0.3.0

DroidDeck is a native GTK 4 and Libadwaita desktop toolbox for Android development, debugging, device management, Fastboot, and protected Samsung Heimdall operations.

Version 0.3.0 fixes ADB device discovery when `adb devices -l` aligns its
columns with spaces rather than a literal tab.

## Requirements

- Python 3.10 or newer
- GTK 4.10 or newer
- Libadwaita 1.5 or newer
- PyGObject (`python3-gi` on Ubuntu/Debian)

# Installing (ez method:)

```bash
sudo apt install droiddeck
```

Run it with:

```bash
droiddeck-gtk
```

Ubuntu/Debian dependencies:

```bash
sudo apt update
sudo apt install \
  python3 \
  python3-gi \
  gir1.2-gtk-4.0 \
  gir1.2-adw-1 \
  adb \
  fastboot \
  heimdall-flash
```

Optional tools:

```bash
sudo apt install scrcpy zip
```

`apkanalyzer` comes from the Android SDK Command-line Tools. Perfetto tooling is optional.

## Run without installing

```bash
chmod +x droiddeck-gtk
./droiddeck-gtk
```

No venv or pip installation is required. The launcher uses the system Python so it can access the distribution-provided GTK bindings.

Check the version without loading GTK:

```bash
droiddeck-gtk --version
```

## Install into GNOME

```bash
./install.sh
```

Then open **DroidDeck** from the GNOME app grid or run:

```bash
droiddeck-gtk
```

Uninstall:

```bash
./uninstall.sh
```

## Interface

The desktop shell uses native Libadwaita components:

- adaptive `Adw.NavigationSplitView` navigation
- GNOME header bars and toolbar views
- `Adw.PreferencesGroup`, action rows, entry rows, and switch rows
- native alert dialogs and toasts
- GTK file dialogs
- responsive page breakpoints
- collapsible, bounded command output
- system light/dark appearance through Libadwaita

## Features

### ADB

- Multi-device selector and live device overview
- Model, Android version, battery/temperature, security patch, ABI, Verified Boot, and lock state
- APK and split-APK installation
- Package search, package information, force-stop, launch, clear data, uninstall, and APK extraction
- File/folder push and remote-path pull
- Live Logcat with severity and text filtering, stop, clear, save, bounded buffering, and batched UI updates
- Screenshots, screen recording, and scrcpy launch modes
- Wireless ADB pair, connect, disconnect, and TCP/IP mode
- Android/recovery/bootloader/fastbootd/Samsung Download Mode reboots
- Interactive ADB shell and confirmed one-shot shell commands
- Diagnostic report folder and full `adb bugreport`
- CPU, memory, graphics, and battery snapshots

### Fastboot

- Explicit Fastboot device detection and selection
- Every command targets the selected serial with `fastboot -s`
- `getvar all`, current slot, reboot targets, A/B slot switching, and temporary image boot
- Expert-gated partition flash, erase, format, bootloader lock/unlock, and critical lock/unlock
- Dry-run protection and exact typed confirmations
- Quote-aware raw arguments without a host shell
- Conservative detection of vendor/OEM and option-prefixed write commands

### Samsung / Heimdall

- Download Mode detection, version, and command help
- Print PIT and download raw PIT
- Partition selector populated only from the current device PIT; DroidDeck does not guess partition names
- Tracked `--no-reboot` / `--resume` session state
- Expert-gated single-partition flashing
- Multi-partition firmware sets using `PARTITION=/absolute/path/file` mappings
- Protected repartition and firmware flashing
- Quote-aware raw arguments without a host shell
- Exact typed confirmations for destructive operations
- PIT mappings are cleared after failures, reconnects, completed sessions, and state uncertainty

### Safety and reliability

- Commands are always argument arrays; no `shell=True`, `os.system`, `eval`, or `exec`
- Persistent exact command/output panel with exit codes
- Dry-run mode for protected state-changing operations
- Expert-mode gate for dangerous Fastboot and Heimdall operations
- Pairing codes are hidden in the UI and redacted from command logs
- Concurrent flashing operations are blocked
- Long-running commands execute off the GTK main thread
- Late worker callbacks are dropped during shutdown
- Logcat shutdown no longer blocks the GTK thread
- Failed screenshot/recording pulls preserve the device-side copy
- Strict package, partition, filesystem, host/port, and PIT parsing
- Atomic configuration writes with mode `0600`
- Graceful dependency errors instead of PyGObject tracebacks

## Output files

Generated files are stored under:

```text
~/DroidDeck/
```

Change the location in Settings.

## Development checks

```bash
PYTHONPATH=src pytest -q
ruff check src tests
ruff format --check src tests
python3 -m compileall -q src tests
bash -n droiddeck-gtk install.sh uninstall.sh
```

## Important warning

DroidDeck cannot verify that a firmware image, recovery, boot image, or PIT belongs to your exact device model and storage variant. Keep backups, use device-specific documentation, start with Dry Run, and test read-only detection/PIT operations first.

The release environment did not have a physical Android/Samsung device attached, so real ADB/Fastboot/Heimdall flashing is not claimed as tested. The build environment also lacked GTK/PyGObject, so the actual window could not be launched there; API usage was reviewed against current official GTK/Libadwaita/PyGObject documentation and the non-GUI paths were tested automatically.
