"""Watches systemd-logind for suspend/resume so device state gets reapplied after resume.

liquidctl's own HydroPlatinum driver warns that the device needs re-initializing "every time
it is powered on, including when the system resumes from suspending to memory" - without this,
a resumed system silently keeps whatever firmware default the AIO reset to until the app is
reopened by hand.
"""

from __future__ import annotations

from gi.repository import Gio, GLib

_BUS_NAME = "org.freedesktop.login1"
_OBJECT_PATH = "/org/freedesktop/login1"
_INTERFACE = "org.freedesktop.login1.Manager"
_SIGNAL = "PrepareForSleep"


class SleepMonitor:
    def __init__(self, on_resume) -> None:
        self._on_resume = on_resume
        self._bus = None
        self._subscription_id = None
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except GLib.Error:
            return
        self._subscription_id = self._bus.signal_subscribe(
            _BUS_NAME, _INTERFACE, _SIGNAL, _OBJECT_PATH,
            None, Gio.DBusSignalFlags.NONE, self._on_signal,
        )

    def _on_signal(self, _connection, _sender, _path, _interface, _signal, params) -> None:
        (going_to_sleep,) = params.unpack()
        if not going_to_sleep:
            self._on_resume()

    def stop(self) -> None:
        if self._bus is not None and self._subscription_id is not None:
            self._bus.signal_unsubscribe(self._subscription_id)
            self._subscription_id = None
