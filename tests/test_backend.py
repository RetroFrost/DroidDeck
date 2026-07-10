from __future__ import annotations

import json
import stat
import sys
import threading
import time
from pathlib import Path

from droiddeck_gtk.backend import Backend, Config, Result, Runner


def wait(event: threading.Event, seconds: float = 3.0) -> None:
    assert event.wait(seconds), "asynchronous callback did not finish"


def test_adb_devices() -> None:
    text = (
        "List of devices attached\n"
        "R58M123\tdevice product:beyond2lte model:SM_G975F "
        "device:beyond2 transport_id:1\n"
        "emulator-5554\toffline\n"
    )
    devices = Backend.parse_adb_devices(text)
    assert len(devices) == 2
    assert devices[0].serial == "R58M123"
    assert devices[0].model == "SM_G975F"
    assert devices[1].state == "offline"


def test_adb_devices_accept_space_aligned_output_and_ignore_noise() -> None:
    text = (
        "* daemon started successfully *\n"
        "List of devices attached\n"
        "RQ8M608LY0A        device usb:2-1.3 product:aosp_beyond2lte "
        "model:SM_G975F device:beyond2lte transport_id:1\n"
        "????????????       no permissions (user in plugdev group)\n"
        "error: unrelated adb noise\n"
    )
    devices = Backend.parse_adb_devices(text)
    assert [(device.serial, device.state) for device in devices] == [
        ("RQ8M608LY0A", "device"),
        ("????????????", "no permissions"),
    ]
    assert devices[0].model == "SM_G975F"
    assert devices[0].product == "aosp_beyond2lte"
    assert devices[0].device == "beyond2lte"


def test_fastboot_devices_deduplicate_and_ignore_noise() -> None:
    devices = Backend.parse_fastboot_devices(
        "ABC123\tfastboot\nABC123 fastboot\nerror: waiting for device\nXYZ bootloader\n"
    )
    assert [(item.serial, item.state) for item in devices] == [
        ("ABC123", "fastboot"),
        ("XYZ", "bootloader"),
    ]


def test_props() -> None:
    props = Backend.parse_props(
        "[ro.product.model]: [Galaxy S10+]\n[ro.build.version.release]: [15]\n"
    )
    assert props["ro.product.model"] == "Galaxy S10+"


def test_pit_is_unique_sorted_and_strict() -> None:
    assert Backend.parse_pit(
        "Partition Name: BOOT\n"
        "Partition Name: RECOVERY\n"
        "Partition Name: BOOT\n"
        "Partition Name: ../../oops\n"
    ) == ["BOOT", "RECOVERY"]


def test_validation_helpers() -> None:
    assert Backend.valid_partition("RECOVERY")
    assert Backend.valid_partition("super_a")
    assert not Backend.valid_partition("../boot")
    assert not Backend.valid_partition("")
    assert Backend.valid_filesystem("ext4")
    assert not Backend.valid_filesystem("ext4;rm")
    assert Backend.valid_package("com.example.app")
    assert not Backend.valid_package("not-a-package")


def test_host_port_validation() -> None:
    assert Backend.validate_host_port("192.168.1.2:5555")
    assert Backend.validate_host_port("adb-host.local:37123")
    assert Backend.validate_host_port("[2001:db8::1]:5555")
    assert Backend.validate_host_port("[fe80::1%wlan0]:5555")
    assert Backend.validate_host_port("adb-ABC._adb-tls-connect._tcp:5555")
    assert not Backend.validate_host_port("192.168.1.2")
    assert not Backend.validate_host_port("host:0")
    assert not Backend.validate_host_port("host:65536")
    assert not Backend.validate_host_port("host:abc")
    assert not Backend.validate_host_port("bad host:5555")
    assert not Backend.validate_host_port("bad/host:5555")
    assert not Backend.validate_host_port("[not-ipv6]:5555")


def test_fastboot_classification() -> None:
    for args in (
        ["flash", "boot", "boot.img"],
        ["erase", "userdata"],
        ["format:ext4", "userdata"],
        ["flashing", "unlock"],
        ["oem", "unlock"],
        ["-w"],
        ["--slot", "all", "flash", "boot", "boot.img"],
        ["flash:raw", "boot", "kernel", "ramdisk"],
        ["flashall"],
        ["oem", "vendor-defined-write"],
        ["flashing", "vendor-defined-write"],
    ):
        assert Backend.fastboot_is_dangerous(args), args
    assert not Backend.fastboot_is_dangerous(["getvar", "all"])
    assert Backend.fastboot_is_state_changing(["reboot"])
    assert Backend.fastboot_is_state_changing(["boot", "recovery.img"])
    assert Backend.fastboot_is_state_changing(["set_active", "a"])
    assert Backend.fastboot_is_state_changing(["--set-active=a", "getvar", "all"])
    assert Backend.fastboot_is_state_changing(["set_active:b"])
    assert not Backend.fastboot_is_state_changing(["devices"])


def test_heimdall_classification() -> None:
    assert Backend.heimdall_is_dangerous(["flash", "--BOOT", "boot.img"])
    assert Backend.heimdall_is_dangerous(["--verbose", "flash", "--BOOT", "boot.img"])
    assert Backend.heimdall_is_dangerous(["anything", "--repartition"])
    assert Backend.heimdall_is_dangerous(["anything", "--pit=device.pit"])
    assert not Backend.heimdall_is_dangerous(["print-pit", "--no-reboot"])


def test_config_loads_only_real_booleans_and_saves_atomically(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config_dir = tmp_path / "config" / "droiddeck-gtk"
    config_dir.mkdir(parents=True)
    path = config_dir / "config.json"
    path.write_text(
        json.dumps(
            {
                "output_dir": "relative-output",
                "dry_run": "false",
                "expert": 1,
                "adb_serial": 123,
            }
        ),
        encoding="utf-8",
    )
    config = Config()
    assert config.dry_run is False
    assert config.expert is False
    assert config.adb_serial == ""
    assert config.output_dir.is_absolute()

    config.dry_run = True
    config.expert = True
    config.adb_serial = "SERIAL"
    assert config.save()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["dry_run"] is True
    assert saved["expert"] is True
    assert saved["adb_serial"] == "SERIAL"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(config_dir.glob("*.tmp"))


def test_runner_quote_and_split_round_trip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config = Config()
    runner = Runner(config, lambda _text: None)
    args = ["flash", "RECOVERY", "/tmp/a file.img", "literal'quote"]
    assert runner.split_args(runner.quote(args)) == args


def test_runner_dry_run_does_not_execute(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config = Config()
    config.dry_run = True
    output: list[str] = []
    runner = Runner(config, output.append)
    event = threading.Event()
    results: list[Result] = []

    assert runner.run(
        ["definitely-not-a-real-command", "flash"],
        lambda result: (results.append(result), event.set()),
        destructive=True,
        exclusive="flash",
    )
    wait(event)
    assert results[0].ok
    assert results[0].dry_run
    assert "not executed" in results[0].stdout
    assert not runner.has_active
    assert not runner.has_destructive


def test_runner_executes_without_a_host_shell(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config = Config()
    output: list[str] = []
    runner = Runner(config, output.append)
    event = threading.Event()
    results: list[Result] = []
    payload = "$(printf injected); literal"

    assert runner.run(
        [sys.executable, "-c", "import sys; print(sys.argv[1])", payload],
        lambda result: (results.append(result), event.set()),
    )
    wait(event)
    assert results[0].ok
    assert results[0].stdout.strip() == payload


def test_runner_exclusive_key_blocks_overlap(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config = Config()
    runner = Runner(config, lambda _text: None)
    event = threading.Event()
    assert runner.run(
        [sys.executable, "-c", "import time; time.sleep(0.15)"],
        lambda _result: event.set(),
        exclusive="same-operation",
    )
    assert not runner.run(
        [sys.executable, "-c", "print('should not run')"],
        exclusive="same-operation",
    )
    wait(event)
    assert runner.run(
        [sys.executable, "-c", "print('now allowed')"],
        exclusive="same-operation",
    )
    deadline = time.monotonic() + 3
    while runner.has_active and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not runner.has_active


def test_runner_stream_delivers_complete_output(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config = Config()
    runner = Runner(config, lambda _text: None)
    chunks: list[str] = []
    event = threading.Event()
    assert runner.stream(
        [sys.executable, "-c", "print('one'); print('two')"],
        chunks.append,
        lambda returncode: event.set() if returncode == 0 else None,
    )
    wait(event)
    assert "one\ntwo\n" == "".join(chunks)


def test_output_paths_are_sanitized_and_unique(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config = Config()
    config.output_dir = tmp_path / "output"
    runner = Runner(config, lambda _text: None)
    backend = Backend(config, runner)
    first = backend.output_path("../reports", "bad/name", ".txt")
    second = backend.output_path("../reports", "bad/name", ".txt")
    assert first.parent == config.output_dir / "reports"
    assert first.name.startswith("bad-name-")
    assert first != second


def test_runner_detached_process_is_not_tracked(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config = Config()
    runner = Runner(config, lambda _text: None)
    marker = tmp_path / "detached.txt"
    assert runner.spawn_detached(
        [
            sys.executable,
            "-c",
            "import pathlib,sys,time; time.sleep(0.05); pathlib.Path(sys.argv[1]).write_text('ok')",
            str(marker),
        ]
    )
    assert not runner.has_active
    deadline = time.monotonic() + 3
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.read_text() == "ok"


def test_closed_runner_drops_queued_callbacks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config = Config()
    runner = Runner(config, lambda _text: None)
    queued: list[tuple[object, tuple[object, ...]]] = []

    from droiddeck_gtk import backend as backend_module

    monkeypatch.setattr(
        backend_module.GLib,
        "idle_add",
        lambda callback, *args: queued.append((callback, args)),
    )
    called: list[str] = []
    runner._schedule(lambda: called.append("late"))
    runner.close()
    for callback, args in queued:
        callback(*args)
    assert called == []
