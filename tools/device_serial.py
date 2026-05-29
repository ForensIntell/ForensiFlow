"""Helpers for resolving a ForensiFlow Android device serial."""

from __future__ import annotations

import os
import subprocess
from typing import List


PLACEHOLDER_SERIALS = {"YOUR_SERIAL", "<serial>", "serial", "DEVICE_SERIAL"}


def resolve_device_serial(value: str = "", *, required: bool = False) -> str:
    serial = (value or "").strip()
    if not serial:
        serial = (
            os.getenv("FF_SERIAL")
            or os.getenv("FORENSIFLOW_DEVICE_SERIAL")
            or os.getenv("ANDROID_SERIAL")
            or ""
        ).strip()
    if serial in PLACEHOLDER_SERIALS:
        raise SystemExit(f"invalid placeholder device serial: {serial!r}\n\n{adb_devices_text()}")
    if serial:
        return serial

    devices = adb_device_serials()
    if len(devices) == 1:
        return devices[0]
    if required:
        hint = "No device serial was provided."
        if len(devices) > 1:
            hint = "Multiple devices are connected; choose one serial."
        raise SystemExit(
            f"{hint}\n"
            "Set it with: export FF_SERIAL=<serial>\n"
            "Or pass: --device-serial <serial>\n\n"
            f"{adb_devices_text()}"
        )
    return ""


def adb_device_serials() -> List[str]:
    try:
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=8)
    except Exception:
        return []
    serials: List[str] = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def adb_devices_text() -> str:
    try:
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=8)
    except Exception as exc:
        return f"failed to run adb devices: {exc}"
    return result.stdout.strip()
