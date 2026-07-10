"""JSON persistence for curves, profiles and preferences.

GSettings would need a compiled+installed schema, which doesn't fit a simple
local venv install, so plain JSON under XDG_CONFIG_HOME is used instead.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy

from gi.repository import GLib

_CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "liquidctl-gui")
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "config.json")

PRESET_CURVES = {
    "silent": [(20, 20), (35, 30), (45, 40), (55, 55), (70, 65)],
    "balanced": [(20, 35), (35, 50), (45, 65), (55, 80), (70, 95)],
    "performance": [(20, 55), (35, 70), (45, 85), (55, 95), (70, 100)],
}

DEFAULTS = {
    "theme": "system",
    "temp_unit": "C",
    "poll_interval": 2,
    "autostart": False,
    "notifications": True,
    "default_device": None,  # device description to select on startup; None = first device found
    "window_width": 1080,
    "window_height": 680,
    "window_maximized": False,
    "sidebar_width": 280,
    "pump_mode": "balanced",
    "active_profile_id": "balanced",
    "device_curves": {},   # {device_description: {channel: [[temp, duty], ...]}}
    "device_presets": {},  # {device_description: {channel: preset_id}}
    "profiles": [
        {"id": "silent", "name": "Silent", "desc": "Prioritizes quiet operation, slightly higher temperatures",
         "pump_curve": PRESET_CURVES["silent"], "fan_curve": PRESET_CURVES["silent"]},
        {"id": "balanced", "name": "Balanced", "desc": "Good balance between noise and cooling",
         "pump_curve": PRESET_CURVES["balanced"], "fan_curve": PRESET_CURVES["balanced"]},
        {"id": "performance", "name": "Performance", "desc": "Maximum cooling, more noise",
         "pump_curve": PRESET_CURVES["performance"], "fan_curve": PRESET_CURVES["performance"]},
    ],
    "lighting": {"mode": "spectrum", "color": "#3584e4", "speed": 50, "brightness": 80},
}


class ConfigStore:
    def __init__(self) -> None:
        self._data = deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            with open(_CONFIG_FILE, encoding="utf-8") as fh:
                on_disk = json.load(fh)
            self._data.update(on_disk)
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, OSError):
            pass

    def save(self) -> None:
        os.makedirs(_CONFIG_DIR, exist_ok=True)
        tmp_path = _CONFIG_FILE + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2)
        os.replace(tmp_path, _CONFIG_FILE)

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set_many(self, updates: dict) -> None:
        self._data.update(updates)
        self.save()

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self.save()

    def get_profile(self, profile_id: str) -> dict | None:
        for profile in self._data["profiles"]:
            if profile["id"] == profile_id:
                return profile
        return None

    def upsert_profile(self, profile: dict) -> None:
        profiles = self._data["profiles"]
        for i, existing in enumerate(profiles):
            if existing["id"] == profile["id"]:
                profiles[i] = profile
                self.save()
                return
        profiles.append(profile)
        self.save()

    def delete_profile(self, profile_id: str) -> None:
        self._data["profiles"] = [p for p in self._data["profiles"] if p["id"] != profile_id]
        if self._data.get("active_profile_id") == profile_id:
            self._data["active_profile_id"] = "balanced"
        self.save()

    def get_device_curve(self, device_description: str, channel: str) -> list | None:
        return self._data.get("device_curves", {}).get(device_description, {}).get(channel)

    def get_device_preset(self, device_description: str, channel: str) -> str | None:
        return self._data.get("device_presets", {}).get(device_description, {}).get(channel)

    def set_device_curve(self, device_description: str, channel: str,
                          curve: list[tuple[float, float]], preset: str) -> None:
        self._data.setdefault("device_curves", {}).setdefault(device_description, {})[channel] = curve
        self._data.setdefault("device_presets", {}).setdefault(device_description, {})[channel] = preset
        self.save()
