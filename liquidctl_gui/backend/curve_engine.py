"""Keeps fan/pump curves applied over time.

Some liquidctl drivers accept `set_speed_profile()` and apply the temperature->duty
curve on-device from then on (no host-side polling needed). Drivers that don't
support this raise `NotImplementedError`/`ValueError` on that call - for those,
this module falls back to software polling: read the sensor, interpolate the duty
from the curve, and push a fixed duty on every tick.
"""

from __future__ import annotations

from dataclasses import dataclass

from gi.repository import GLib

from .controller import DeviceController

DEFAULT_POLL_SECONDS = 2

# HydroPlatinum's 3-fan variant writes fan3 via a second HID report sent right
# before the main one; this occasionally races on the firmware side (not just at
# startup) and leaves fan3 at a stale/wrong duty. Rather than trust a fixed
# delay, periodically re-read status and resend if the fans disagree by more
# than this many percentage points - confirmed by direct liquidctl reproduction
# that a resend reliably corrects it. The interval is user-configurable (see
# Settings): this only needs to catch a rare firmware hiccup, not track
# temperature in real time (the device already does that on its own for a
# native profile), so a slower interval trades a bit of reaction time for
# less USB traffic/CPU.
_FAN_DUTY_TOLERANCE = 5
DEFAULT_VALIDATION_SECONDS = 60

# Right after applying a curve is exactly when the race is most likely (see above),
# so re-check quickly at first - then, once the fans agree (or we've retried enough
# times without success), settle into the slower, user-configurable interval instead
# of hammering the device forever at startup speed.
_STARTUP_VALIDATION_SECONDS = 2
_STARTUP_VALIDATION_MAX_ATTEMPTS = 10


def interpolate_duty(curve: list[tuple[float, float]], temp: float) -> int:
    points = sorted(curve, key=lambda p: p[0])
    if not points:
        return 0
    if temp <= points[0][0]:
        return round(points[0][1])
    if temp >= points[-1][0]:
        return round(points[-1][1])
    for (t0, d0), (t1, d1) in zip(points, points[1:]):
        if t0 <= temp <= t1:
            if t1 == t0:
                return round(d1)
            ratio = (temp - t0) / (t1 - t0)
            return round(d0 + ratio * (d1 - d0))
    return round(points[-1][1])


@dataclass
class _ChannelJob:
    device_key: str
    channel: str
    curve: list[tuple[float, float]]
    temp_sensor_key: str
    software_fallback: bool = False
    timeout_id: int | None = None
    validation_timeout_id: int | None = None
    startup_checks_left: int = 0


class CurveEngine:
    """Applies one curve per (device, channel) and keeps software-fallback ones ticking."""

    def __init__(
        self,
        controller: DeviceController,
        poll_seconds: int = DEFAULT_POLL_SECONDS,
        validation_seconds: int = DEFAULT_VALIDATION_SECONDS,
    ) -> None:
        self._controller = controller
        self._poll_seconds = poll_seconds
        self._validation_seconds = validation_seconds
        self._jobs: dict[tuple[str, str], _ChannelJob] = {}

    def set_poll_interval(self, seconds: int) -> None:
        self._poll_seconds = max(1, seconds)
        for job in list(self._jobs.values()):
            if job.software_fallback and job.timeout_id is not None:
                GLib.source_remove(job.timeout_id)
                job.timeout_id = GLib.timeout_add_seconds(self._poll_seconds, self._tick, job)

    def set_validation_interval(self, seconds: int) -> None:
        self._validation_seconds = max(5, seconds)
        for job in list(self._jobs.values()):
            # Don't interrupt an in-progress startup fast-check phase - it'll pick up
            # the new steady interval once it settles.
            if job.validation_timeout_id is not None and job.startup_checks_left == 0:
                GLib.source_remove(job.validation_timeout_id)
                job.validation_timeout_id = GLib.timeout_add_seconds(
                    self._validation_seconds, self._validate_fan_duty, job
                )

    def apply_curve(self, device_key: str, channel: str, curve: list[tuple[float, float]], temp_sensor_key: str) -> None:
        key = (device_key, channel)
        job = self._jobs.get(key)
        if job is None:
            job = _ChannelJob(device_key, channel, curve, temp_sensor_key)
            self._jobs[key] = job
        else:
            job.curve = curve

        def on_error(exc: Exception) -> None:
            job.software_fallback = True
            self._start_software_loop(job)

        def on_done(_result) -> None:
            if job.software_fallback and job.timeout_id is not None:
                GLib.source_remove(job.timeout_id)
                job.timeout_id = None
                job.software_fallback = False
            if channel == "fan" and job.validation_timeout_id is None:
                job.startup_checks_left = _STARTUP_VALIDATION_MAX_ATTEMPTS
                job.validation_timeout_id = GLib.timeout_add_seconds(
                    _STARTUP_VALIDATION_SECONDS, self._validate_fan_duty, job
                )

        self._controller.set_speed_profile(device_key, channel, sorted(curve), on_done=on_done, on_error=on_error)

    def _validate_fan_duty(self, job: _ChannelJob) -> bool:
        if (job.device_key, job.channel) not in self._jobs:
            job.validation_timeout_id = None
            return GLib.SOURCE_REMOVE

        def on_status(status) -> None:
            duties = [value for key, value, _unit in status if "fan" in key.lower() and "duty" in key.lower()]
            mismatched = len(duties) >= 2 and max(duties) - min(duties) > _FAN_DUTY_TOLERANCE

            if mismatched:
                self._controller.set_speed_profile(job.device_key, job.channel, sorted(job.curve))

            if job.startup_checks_left > 0:
                if mismatched:
                    job.startup_checks_left -= 1
                    next_seconds = _STARTUP_VALIDATION_SECONDS
                else:
                    # Fans agree - startup settled, switch to the slow steady cadence.
                    job.startup_checks_left = 0
                    next_seconds = self._validation_seconds
            else:
                next_seconds = self._validation_seconds

            job.validation_timeout_id = GLib.timeout_add_seconds(next_seconds, self._validate_fan_duty, job)

        self._controller.get_status(job.device_key, on_status)
        return GLib.SOURCE_REMOVE

    def stop_channel(self, device_key: str, channel: str) -> None:
        job = self._jobs.pop((device_key, channel), None)
        if job and job.timeout_id is not None:
            GLib.source_remove(job.timeout_id)
        if job and job.validation_timeout_id is not None:
            GLib.source_remove(job.validation_timeout_id)

    def stop_all(self) -> None:
        for job in self._jobs.values():
            if job.timeout_id is not None:
                GLib.source_remove(job.timeout_id)
            if job.validation_timeout_id is not None:
                GLib.source_remove(job.validation_timeout_id)
        self._jobs.clear()

    def _start_software_loop(self, job: _ChannelJob) -> None:
        if job.timeout_id is not None:
            return
        job.timeout_id = GLib.timeout_add_seconds(self._poll_seconds, self._tick, job)

    def _tick(self, job: _ChannelJob) -> bool:
        if (job.device_key, job.channel) not in self._jobs:
            return GLib.SOURCE_REMOVE

        def on_status(status) -> None:
            temp = None
            for key, value, _unit in status:
                if job.temp_sensor_key.lower() in key.lower():
                    temp = value
                    break
            if temp is None:
                return
            duty = interpolate_duty(job.curve, temp)
            self._controller.set_fixed_speed(job.device_key, job.channel, duty)

        self._controller.get_status(job.device_key, on_status)
        return GLib.SOURCE_CONTINUE
