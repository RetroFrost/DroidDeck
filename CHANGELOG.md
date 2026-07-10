# Changelog

## 0.3.0 — 2026-07-10

### Urgent ADB detection fix

- Fixed ADB device detection for `adb devices -l` implementations that align
  columns with spaces instead of a literal tab.
- Added coverage for space-aligned devices, `no permissions` devices, and ADB
  daemon/error noise.

## 0.2.0 — 2026-07-09

### Modern GTK / GNOME interface

- Replaced the fixed sidebar shell with `Adw.NavigationSplitView`, navigation pages, toolbar views, native header bars, and adaptive breakpoints.
- Replaced deprecated `Gtk.Dialog` / `Gtk.MessageDialog` patterns with `Adw.AlertDialog`.
- Replaced the old chooser path with `Gtk.FileDialog` and corrected the GIO async callback signature and object lifetime handling.
- Reworked settings and device information into native Libadwaita preference, action, entry, and switch rows.
- Added native toasts, a responsive application page, wrapping action toolbars, and a collapsible command-output panel.
- Removed custom fake-window chrome and left visual styling to Libadwaita apart from a few semantic classes.

### Safety fixes

- Fastboot commands now always require and target an explicitly detected serial.
- Raw Fastboot commands can no longer bypass Expert mode or Dry Run by placing options before `flash`/write verbs.
- Added conservative handling for `flash:raw`, `flashall`, vendor `oem` commands, and unknown `flashing` subcommands.
- Replaced whitespace splitting with quote-aware `shlex.split()` for raw Fastboot and Heimdall arguments.
- Removed guessed Heimdall `RECOVERY`/`BOOT` partitions; flashing requires a successful PIT scan from the current device.
- Cleared stale PIT mappings across reconnects, completed sessions, failures, and uncertain state.
- Fixed Heimdall `--no-reboot` / `--resume` tracking for structured and raw commands.
- Blocked concurrent Fastboot and Heimdall operations.
- Added exact command previews and typed confirmations to dangerous operations.
- Marked APK install, push, TCP/IP changes, reboots, package deletion, and other protected writes for Dry Run.
- Redacted wireless-pairing codes from command logs and changed the code field to a password row.

### Reliability fixes

- Fixed installed-launcher symlink resolution; user installs now find the packaged Python source correctly.
- Consolidated GTK dependency checks into a graceful Python entry point shared by source, installed, and wheel launches.
- Made `--version` work without GTK/PyGObject installed.
- Fixed accidental execution of example text from `Adw.EntryRow` fields.
- Fixed GTK file-dialog callback arity, cancellation handling, non-local file handling, and lifetime retention.
- Fixed screenshot and screen-record cleanup so failed pulls leave the device-side copy intact.
- Added unique microsecond output names to prevent collisions.
- Stopped Logcat when switching devices and guarded stale async device callbacks.
- Batched Logcat delivery and bounded Logcat/command buffers to prevent unbounded GTK main-loop and memory growth.
- Moved stream termination off the GTK thread.
- Detached scrcpy from in-app operation tracking.
- Dropped late callbacks after window shutdown.
- Added strict parser filtering for package lists and device data.
- Added strict host/port validation, including IPv4, bracketed IPv6, scoped IPv6, hostnames, and ADB mDNS names.
- Made configuration writes atomic and private (`0600`) and rolled back settings when saves fail.
- Added error handling for output directories, diagnostics, symlink loops, invalid paths, and worker startup failures.
- Fixed desktop-file generation for prefixes containing spaces and special characters.

### Packaging and tests

- Added AppStream metadata and improved desktop integration.
- Added a wheel-safe console launcher with clear dependency instructions.
- Added a regression suite covering parsers, validation, dry-run behavior, no-shell execution, exclusive operation locks, stream delivery, shutdown callback handling, modern GTK architecture, flashing gates, and packaging safety.

## 0.1.0 — 2026-07-09

- First GTK 4 prototype with ADB, package, file, Logcat, screen, diagnostics, Fastboot, and Heimdall pages.
