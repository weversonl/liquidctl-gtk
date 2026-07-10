"""Serializes all liquidctl I/O on a single background worker thread.

liquidctl talks to USB/HID devices with blocking calls; none of that may run on the
GTK main thread. A single worker thread also avoids two callers hitting the same
device handle concurrently.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Callable

from gi.repository import GLib

from .device_manager import DeviceInfo, PUMP_MODE_ONLY_DRIVERS, discover_devices


@dataclass
class _Job:
    fn: Callable[[], object]
    on_done: Callable[[object], None] | None
    on_error: Callable[[Exception], None] | None


class DeviceController:
    """Owns the worker thread and the set of connected liquidctl drivers."""

    def __init__(self) -> None:
        self._queue: queue.Queue[_Job | None] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="liquidctl-io", daemon=True)
        self._devices: dict[str, object] = {}
        self._infos: dict[str, DeviceInfo] = {}
        self._connected: set[str] = set()
        self.pump_mode = "balanced"
        self._thread.start()

    def refresh_devices(self, on_done: Callable[[list[DeviceInfo]], None], force_reinitialize: bool = False) -> None:
        def work():
            pairs = discover_devices()
            self._devices = {info.key: driver for info, driver in pairs}
            self._infos = {info.key: info for info, driver in pairs}
            if force_reinitialize:
                # e.g. after a suspend/resume: the device may have reset its onboard state even
                # though its USB address (and thus our "already connected" bookkeeping) is unchanged.
                self._connected.clear()
            for key, driver in self._devices.items():
                if key not in self._connected:
                    driver.connect()
                    if type(driver).__name__ in PUMP_MODE_ONLY_DRIVERS:
                        driver.initialize(pump_mode=self.pump_mode)
                    else:
                        driver.initialize()
                    self._connected.add(key)
            return list(self._infos.values())

        self._submit(work, on_done)

    def set_pump_mode(self, device_key: str, mode: str, on_done=None) -> None:
        def work():
            self._devices[device_key].initialize(pump_mode=mode)
            return None

        self._submit(work, on_done)

    def get_status(self, device_key: str, on_done: Callable[[list[tuple[str, object, str]]], None]) -> None:
        def work():
            driver = self._devices[device_key]
            return driver.get_status()

        self._submit(work, on_done)

    def set_fixed_speed(self, device_key: str, channel: str, duty: int, on_done=None) -> None:
        def work():
            self._devices[device_key].set_fixed_speed(channel, duty)
            return None

        self._submit(work, on_done)

    def set_speed_profile(self, device_key: str, channel: str, profile: list[tuple[float, float]], on_done=None, on_error=None) -> None:
        def work():
            self._devices[device_key].set_speed_profile(channel, profile)
            return None

        self._submit(work, on_done, on_error)

    def set_color(self, device_key: str, channel: str, mode: str, colors: list[tuple[int, int, int]],
                  on_done=None, on_error=None, **kwargs) -> None:
        def work():
            self._devices[device_key].set_color(channel, mode, colors, **kwargs)
            return None

        self._submit(work, on_done, on_error)

    def shutdown(self) -> None:
        self._queue.put(None)

    def _submit(self, fn, on_done, on_error=None) -> None:
        self._queue.put(_Job(fn, on_done, on_error))

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                for driver in self._devices.values():
                    try:
                        driver.disconnect()
                    except Exception:
                        pass
                return
            try:
                result = job.fn()
            except Exception as exc:  # noqa: BLE001 - surfaced to the caller via callback
                if job.on_error is not None:
                    GLib.idle_add(job.on_error, exc)
                continue
            if job.on_done is not None:
                GLib.idle_add(job.on_done, result)
