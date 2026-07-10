from __future__ import annotations

import ipaddress
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from gi.repository import GLib


@dataclass(slots=True)
class Result:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    started: float
    ended: float
    dry_run: bool = False

    @property
    def output(self) -> str:
        if self.stdout and self.stderr:
            return f"{self.stdout.rstrip()}\n\n[stderr]\n{self.stderr.rstrip()}\n"
        return self.stdout or self.stderr

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(slots=True)
class AdbDevice:
    serial: str
    state: str
    model: str = ""
    product: str = ""
    device: str = ""

    @property
    def label(self) -> str:
        name = self.model.replace("_", " ") if self.model else self.serial
        return f"{name} — {self.serial} ({self.state})"


@dataclass(slots=True)
class FastbootDevice:
    serial: str
    state: str = "fastboot"

    @property
    def label(self) -> str:
        return f"{self.serial} ({self.state})"


class Config:
    """Small, strictly parsed JSON configuration with atomic writes."""

    def __init__(self) -> None:
        xdg_config = os.environ.get("XDG_CONFIG_HOME", "").strip()
        config_root = (
            Path(xdg_config).expanduser() if xdg_config else Path.home() / ".config"
        )
        self.dir = config_root / "droiddeck-gtk"
        self.path = self.dir / "config.json"
        self.output_dir = Path.home() / "DroidDeck"
        self.dry_run = False
        self.expert = False
        self.adb_serial = ""
        self.last_error = ""
        self.load()

    @staticmethod
    def _bool(data: dict[str, object], key: str, default: bool) -> bool:
        value = data.get(key, default)
        return value if isinstance(value, bool) else default

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError) as exc:
            self.last_error = f"Could not read configuration: {exc}"
            return
        if not isinstance(data, dict):
            self.last_error = "Configuration root must be a JSON object."
            return

        output_dir = data.get("output_dir")
        if isinstance(output_dir, str) and output_dir.strip():
            candidate = Path(output_dir).expanduser()
            if not candidate.is_absolute():
                candidate = Path.home() / candidate
            self.output_dir = candidate
        self.dry_run = self._bool(data, "dry_run", False)
        self.expert = self._bool(data, "expert", False)
        serial = data.get("adb_serial", "")
        self.adb_serial = serial if isinstance(serial, str) else ""

    def save(self) -> bool:
        payload = (
            json.dumps(
                {
                    "output_dir": str(self.output_dir),
                    "dry_run": self.dry_run,
                    "expert": self.expert,
                    "adb_serial": self.adb_serial,
                },
                indent=2,
            )
            + "\n"
        )
        tmp_path: Path | None = None
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix="config-", suffix=".json.tmp", dir=self.dir
            )
            tmp_path = Path(tmp_name)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp_path, 0o600)
            tmp_path.replace(self.path)
        except OSError as exc:
            if tmp_path:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            self.last_error = f"Could not save configuration: {exc}"
            return False
        self.last_error = ""
        return True


class Runner:
    """Threaded subprocess runner that never invokes a host shell."""

    def __init__(self, config: Config, log: Callable[[str], object]) -> None:
        self.config = config
        self.log = log
        self._stream: subprocess.Popen[str] | None = None
        self._stream_starting = False
        self._stop_requested = False
        self._closed = False
        self._active_keys: set[str] = set()
        self._active_count = 0
        self._destructive_count = 0
        self._lock = threading.RLock()

    @staticmethod
    def exists(command: str) -> bool:
        return shutil.which(command) is not None

    @staticmethod
    def quote(args: Sequence[str]) -> str:
        return shlex.join([str(item) for item in args])

    @staticmethod
    def split_args(text: str) -> list[str]:
        return shlex.split(text, posix=True)

    @staticmethod
    def _text(value: str | bytes | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode(errors="replace")
        return value

    @property
    def has_active(self) -> bool:
        with self._lock:
            return (
                self._active_count > 0
                or self._stream_starting
                or bool(self._stream and self._stream.poll() is None)
            )

    @property
    def has_destructive(self) -> bool:
        with self._lock:
            return self._destructive_count > 0

    def emit(self, text: str) -> None:
        with self._lock:
            if self._closed:
                return
        GLib.idle_add(self.log, text)

    def _schedule(self, callback: Callable[..., object], *args: object) -> None:
        with self._lock:
            if self._closed:
                return

        def invoke() -> bool:
            with self._lock:
                if self._closed:
                    return False
            try:
                callback(*args)
            except Exception as exc:  # UI callback failures must not kill the app.
                self.emit(f"[callback error] {type(exc).__name__}: {exc}\n")
            return False

        GLib.idle_add(invoke)

    def _release_operation(self, exclusive: str | None, destructive: bool) -> None:
        with self._lock:
            self._active_count = max(0, self._active_count - 1)
            if destructive:
                self._destructive_count = max(0, self._destructive_count - 1)
            if exclusive:
                self._active_keys.discard(exclusive)

    def run(
        self,
        args: Sequence[str],
        done: Callable[[Result], object] | None = None,
        *,
        destructive: bool = False,
        timeout: float | None = None,
        exclusive: str | None = None,
        display_args: Sequence[str] | None = None,
    ) -> bool:
        argv = tuple(str(item) for item in args)
        if not argv or not argv[0] or any("\0" in item for item in argv):
            return False

        with self._lock:
            if self._closed:
                return False
            if exclusive and exclusive in self._active_keys:
                return False
            if exclusive:
                self._active_keys.add(exclusive)
            self._active_count += 1
            if destructive:
                self._destructive_count += 1

        shown = tuple(str(item) for item in (display_args or argv))
        self.emit(f"\n$ {self.quote(shown)}\n")

        if destructive and self.config.dry_run:
            now = time.monotonic()
            result = Result(
                argv,
                0,
                "Dry run: state-changing command was not executed.\n",
                "",
                now,
                now,
                dry_run=True,
            )
            self.emit(result.output)
            self.emit("[dry run]\n")
            self._release_operation(exclusive, destructive)
            if done:
                self._schedule(done, result)
            return True

        def worker() -> None:
            started = time.monotonic()
            try:
                cp = subprocess.run(
                    argv,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    check=False,
                    timeout=timeout,
                )
                result = Result(
                    argv,
                    cp.returncode,
                    cp.stdout,
                    cp.stderr,
                    started,
                    time.monotonic(),
                )
            except FileNotFoundError:
                result = Result(
                    argv,
                    127,
                    "",
                    f"Command not found: {argv[0]}\n",
                    started,
                    time.monotonic(),
                )
            except subprocess.TimeoutExpired as exc:
                result = Result(
                    argv,
                    124,
                    self._text(exc.stdout),
                    self._text(exc.stderr) + "\nCommand timed out.\n",
                    started,
                    time.monotonic(),
                )
            except (OSError, ValueError) as exc:
                result = Result(
                    argv,
                    126,
                    "",
                    f"{type(exc).__name__}: {exc}\n",
                    started,
                    time.monotonic(),
                )
            finally:
                self._release_operation(exclusive, destructive)

            self.emit(result.output or f"[exit {result.returncode}; no output]\n")
            self.emit(
                f"[exit {result.returncode}; {result.ended - result.started:.2f}s]\n"
            )
            if done:
                self._schedule(done, result)

        thread = threading.Thread(
            target=worker, daemon=True, name=f"droiddeck-{argv[0]}"
        )
        try:
            thread.start()
        except RuntimeError as exc:
            self._release_operation(exclusive, destructive)
            self.emit(f"Unable to start worker thread: {exc}\n")
            return False
        return True

    def spawn_detached(
        self,
        args: Sequence[str],
        *,
        display_args: Sequence[str] | None = None,
    ) -> bool:
        """Launch a long-lived GUI/terminal helper without tracking it as app work."""

        argv = tuple(str(item) for item in args)
        if not argv or not argv[0] or any("\0" in item for item in argv):
            return False
        with self._lock:
            if self._closed:
                return False
        shown = tuple(str(item) for item in (display_args or argv))
        self.emit(f"\n$ {self.quote(shown)}\n")
        try:
            subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            self.emit(f"Unable to launch {argv[0]}: {exc}\n")
            return False
        return True

    def stream(
        self,
        args: Sequence[str],
        line: Callable[[str], object],
        done: Callable[[int], object] | None = None,
        *,
        display_args: Sequence[str] | None = None,
    ) -> bool:
        argv = tuple(str(item) for item in args)
        if not argv or not argv[0] or any("\0" in item for item in argv):
            return False
        with self._lock:
            if self._closed or self._stream_starting:
                return False
            if self._stream and self._stream.poll() is None:
                return False
            self._stream_starting = True
            self._stop_requested = False
        shown = tuple(str(item) for item in (display_args or argv))
        self.emit(f"\n$ {self.quote(shown)}\n")

        def worker() -> None:
            try:
                proc = subprocess.Popen(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                    bufsize=1,
                    start_new_session=True,
                )
            except (OSError, ValueError) as exc:
                with self._lock:
                    self._stream_starting = False
                self._schedule(line, f"Unable to start: {exc}\n")
                if done:
                    self._schedule(done, 127)
                return

            with self._lock:
                self._stream = proc
                self._stream_starting = False
                stop_now = self._stop_requested or self._closed
            if stop_now:
                self._terminate_process(proc)

            pending: list[str] = []
            pending_lock = threading.Lock()
            flush_scheduled = False

            def flush_lines() -> bool:
                nonlocal flush_scheduled
                with pending_lock:
                    text = "".join(pending)
                    pending.clear()
                    flush_scheduled = False
                with self._lock:
                    closed = self._closed
                if text and not closed:
                    try:
                        line(text)
                    except Exception as exc:
                        self.emit(
                            f"[stream callback error] {type(exc).__name__}: {exc}\n"
                        )
                return False

            def queue_line(text: str) -> None:
                nonlocal flush_scheduled
                should_schedule = False
                with pending_lock:
                    pending.append(text)
                    if not flush_scheduled:
                        flush_scheduled = True
                        should_schedule = True
                if should_schedule:
                    GLib.idle_add(flush_lines)

            if proc.stdout is not None:
                for text in proc.stdout:
                    queue_line(text)
            rc = proc.wait()
            with self._lock:
                if self._stream is proc:
                    self._stream = None
                self._stop_requested = False
            self.emit(f"[stream exit {rc}]\n")
            if done:
                self._schedule(done, rc)

        try:
            threading.Thread(
                target=worker, daemon=True, name=f"droiddeck-stream-{argv[0]}"
            ).start()
        except RuntimeError as exc:
            with self._lock:
                self._stream_starting = False
            self.emit(f"Unable to start stream worker: {exc}\n")
            return False
        return True

    @staticmethod
    def _terminate_process(proc: subprocess.Popen[str]) -> None:
        if proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.terminate()
            except OSError:
                return
        try:
            proc.wait(2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.kill()
                except OSError:
                    pass

    def stop_stream(self) -> None:
        with self._lock:
            self._stop_requested = True
            proc = self._stream
        if proc:
            threading.Thread(
                target=self._terminate_process,
                args=(proc,),
                daemon=True,
                name="droiddeck-stream-stop",
            ).start()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._stop_requested = True
            proc = self._stream
        if proc:
            threading.Thread(
                target=self._terminate_process,
                args=(proc,),
                daemon=True,
                name="droiddeck-stream-close",
            ).start()


class Backend:
    PARTITION_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}\Z")
    FILESYSTEM_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}\Z")
    PACKAGE_TOKEN = re.compile(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+\Z")
    ADB_DEVICE_STATES = {
        "authorizing",
        "bootloader",
        "connecting",
        "device",
        "host",
        "offline",
        "recovery",
        "rescue",
        "sideload",
        "unauthorized",
    }

    def __init__(self, config: Config, runner: Runner) -> None:
        self.config = config
        self.runner = runner
        self.adb_serial = config.adb_serial
        self.heimdall_resume = False
        self.heimdall_partitions: set[str] = set()

    def adb(self, *args: str, serial: str | None = None) -> list[str]:
        target = self.adb_serial if serial is None else serial
        command = ["adb"]
        if target:
            command += ["-s", target]
        return command + list(args)

    def choose_adb(self, serial: str) -> bool:
        self.adb_serial = serial
        self.config.adb_serial = serial
        return self.config.save()

    def clear_adb(self) -> bool:
        return self.choose_adb("")

    def output_path(self, category: str, stem: str, suffix: str) -> Path:
        safe_category = re.sub(r"[^A-Za-z0-9_.-]+", "-", category).strip(".-")
        safe_stem = re.sub(r"[^A-Za-z0-9_.+-]+", "-", stem).strip(".-")
        folder = self.config.output_dir / (safe_category or "output")
        folder.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        return folder / f"{safe_stem or 'file'}-{timestamp}{suffix}"

    @classmethod
    def valid_partition(cls, value: str) -> bool:
        return bool(cls.PARTITION_TOKEN.fullmatch(value))

    @classmethod
    def valid_filesystem(cls, value: str) -> bool:
        return bool(cls.FILESYSTEM_TOKEN.fullmatch(value))

    @classmethod
    def valid_package(cls, value: str) -> bool:
        return bool(cls.PACKAGE_TOKEN.fullmatch(value))

    @staticmethod
    def parse_adb_devices(text: str) -> list[AdbDevice]:
        devices: list[AdbDevice] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("List of devices attached"):
                continue

            tokens = line.split()
            if len(tokens) < 2:
                continue

            serial = tokens[0]
            if tokens[1:3] == ["no", "permissions"]:
                state = "no permissions"
                details = tokens[3:]
            elif tokens[1].lower() in Backend.ADB_DEVICE_STATES:
                state = tokens[1].lower()
                details = tokens[2:]
            else:
                # Ignore daemon messages, errors, and other command noise.
                continue

            fields: dict[str, str] = {}
            for token in details:
                if ":" in token:
                    key, value = token.split(":", 1)
                    fields[key] = value
            devices.append(
                AdbDevice(
                    serial,
                    state,
                    fields.get("model", ""),
                    fields.get("product", ""),
                    fields.get("device", ""),
                )
            )
        return devices

    @staticmethod
    def parse_fastboot_devices(text: str) -> list[FastbootDevice]:
        devices: list[FastbootDevice] = []
        seen: set[str] = set()
        for raw in text.splitlines():
            parts = raw.split()
            if not parts:
                continue
            serial = parts[0]
            state = parts[1] if len(parts) > 1 else "fastboot"
            if serial in seen or state.lower() not in {"fastboot", "bootloader"}:
                continue
            seen.add(serial)
            devices.append(FastbootDevice(serial, state))
        return devices

    @staticmethod
    def parse_props(text: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in text.splitlines():
            match = re.match(r"\[([^]]+)]\s*:\s*\[([^]]*)]", line)
            if match:
                result[match.group(1)] = match.group(2)
        return result

    @classmethod
    def parse_pit(cls, text: str) -> list[str]:
        partitions: list[str] = []
        for line in text.splitlines():
            match = re.match(r"\s*Partition Name:\s*(\S+)\s*$", line, re.I)
            if match and cls.valid_partition(match.group(1)):
                partitions.append(match.group(1))
        return sorted(set(partitions))

    @staticmethod
    def validate_host_port(value: str) -> bool:
        value = value.strip()
        if not value or any(ch.isspace() for ch in value):
            return False
        host = ""
        port_text = ""
        bracketed = value.startswith("[") and "]:" in value
        if bracketed:
            host, port_text = value[1:].rsplit("]:", 1)
        elif ":" in value:
            host, port_text = value.rsplit(":", 1)
        if not host or not port_text.isdigit():
            return False
        port = int(port_text)
        if not 1 <= port <= 65535:
            return False
        if bracketed:
            try:
                ipaddress.IPv6Address(host.split("%", 1)[0])
            except ipaddress.AddressValueError:
                return False
            return True
        try:
            ipaddress.ip_address(host)
            return True
        except ValueError:
            return bool(
                re.fullmatch(
                    r"(?=.{1,253}\Z)[A-Za-z0-9_](?:[A-Za-z0-9_.-]*[A-Za-z0-9_])?",
                    host,
                )
            )

    @staticmethod
    def fastboot_is_dangerous(args: Sequence[str]) -> bool:
        lowered = [item.lower() for item in args]
        if not lowered:
            return False
        dangerous_verbs = {
            "flash",
            "flashall",
            "erase",
            "delete-logical-partition",
            "create-logical-partition",
            "resize-logical-partition",
            "update",
            "wipe-super",
            "snapshot-update",
            "stage",
        }
        if any(
            token in dangerous_verbs
            or token.startswith("flash:")
            or token.startswith("format:")
            for token in lowered
        ):
            return True
        for index, token in enumerate(lowered[:-1]):
            if token == "flashing" and lowered[index + 1] != "get_unlock_ability":
                return True
            # OEM subcommands are vendor-defined and can modify persistent state.
            if token == "oem":
                return True
        return "-w" in lowered or "--wipe-and-use-fbe" in lowered

    @classmethod
    def fastboot_is_state_changing(cls, args: Sequence[str]) -> bool:
        lowered = [item.lower() for item in args]
        if not lowered:
            return False
        if cls.fastboot_is_dangerous(args):
            return True
        state_verbs = {
            "boot",
            "continue",
            "reboot",
            "reboot-bootloader",
            "set_active",
        }
        return any(
            token in state_verbs
            or token.startswith("--set-active")
            or token.startswith("set_active:")
            for token in lowered
        )

    @staticmethod
    def heimdall_is_dangerous(args: Sequence[str]) -> bool:
        lowered = [item.lower() for item in args]
        return bool(lowered) and (
            "flash" in lowered
            or "--repartition" in lowered
            or any(token.startswith("--pit=") for token in lowered)
        )

    def dependencies(self) -> list[tuple[str, bool, str]]:
        tools = [
            ("adb", "Android Debug Bridge"),
            ("fastboot", "Android bootloader utility"),
            ("heimdall", "Samsung Download Mode flasher"),
            ("scrcpy", "Screen mirroring/control"),
            ("apkanalyzer", "APK inspection"),
            ("perfetto", "Performance tracing"),
            ("zip", "Report archiving"),
        ]
        return [
            (name, self.runner.exists(name), description) for name, description in tools
        ]
