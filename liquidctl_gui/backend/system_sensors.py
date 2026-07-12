"""Reads the host CPU's name and temperature straight from sysfs/procfs.

liquidctl only knows about the devices it controls, not the CPU itself, so this
is a separate, tiny reader - plain file I/O, no extra dependency (e.g. psutil)
for something this simple. Cheap enough to call directly from the GTK main
thread on every dashboard tick.
"""

from __future__ import annotations

import os
import re

_HWMON_ROOT = "/sys/class/hwmon"
_KNOWN_CPU_CHIPS = ("k10temp", "zenpower", "coretemp")
_TEMP_INPUT_RE = re.compile(r"temp\d+_input")


def get_cpu_name() -> str:
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("model name"):
                    return " ".join(line.split(":", 1)[1].split())
    except OSError:
        pass
    return "CPU"


def get_cpu_temp() -> float | None:
    try:
        chips = os.listdir(_HWMON_ROOT)
    except OSError:
        return None

    for chip in chips:
        chip_dir = os.path.join(_HWMON_ROOT, chip)
        try:
            with open(os.path.join(chip_dir, "name"), encoding="utf-8") as fh:
                name = fh.read().strip()
        except OSError:
            continue
        if name not in _KNOWN_CPU_CHIPS:
            continue
        temp = _read_first_temp(chip_dir)
        if temp is not None:
            return temp
    return None


def _read_first_temp(chip_dir: str) -> float | None:
    try:
        entries = sorted(os.listdir(chip_dir))
    except OSError:
        return None
    for entry in entries:
        if not _TEMP_INPUT_RE.fullmatch(entry):
            continue
        try:
            with open(os.path.join(chip_dir, entry), encoding="utf-8") as fh:
                return int(fh.read().strip()) / 1000
        except (OSError, ValueError):
            continue
    return None
