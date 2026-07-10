from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .appinfo import APP_ID  # noqa: E402
from .backend.config_store import ConfigStore  # noqa: E402
from .backend.controller import DeviceController  # noqa: E402
from .backend.curve_engine import CurveEngine  # noqa: E402
from .backend.sleep_monitor import SleepMonitor  # noqa: E402
from .i18n import install  # noqa: E402

_ = install()


class LiquidctlGuiApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        Gtk.Window.set_default_icon_name(APP_ID)
        self.config = ConfigStore()
        self.controller = DeviceController()
        self.controller.pump_mode = self.config.get("pump_mode", "balanced")
        self.curve_engine = CurveEngine(self.controller, poll_seconds=self.config.get("poll_interval", 2))
        self.window: Adw.ApplicationWindow | None = None
        self.tray = None
        self._quitting = False
        self.sleep_monitor = SleepMonitor(self._on_system_resume)

        self._apply_theme(self.config.get("theme", "system"))

    def do_activate(self) -> None:  # noqa: N802 - GObject virtual method name
        # do_activate only runs in the primary instance (locally, or via D-Bus Activate
        # relayed from a second launch) - a secondary/remote invocation's own process never
        # reaches this method, so hold() here can't keep a duplicate process alive forever
        # the way it would if called unconditionally from __init__.
        from .ui.window import LiquidctlGuiWindow

        if self.window is None:
            self.hold()
            self.window = LiquidctlGuiWindow(application=self)
            self.window.connect("close-request", self._on_close_request)

            try:
                from .tray import AppTray

                self.tray = AppTray(self)
            except Exception:
                self.tray = None

        if "--hidden" not in sys.argv:
            self.window.present()

    def _on_close_request(self, *_args) -> bool:
        if self._quitting or self.tray is None:
            return False
        self.window.set_visible(False)
        return True

    def _on_system_resume(self) -> None:
        def on_devices_refreshed(devices) -> None:
            if self.window is None:
                return
            self.window.devices = devices
            self.window.on_active_device_changed()
            self.window.lighting_page.reapply()

        self.controller.refresh_devices(on_devices_refreshed, force_reinitialize=True)

    def quit_for_real(self) -> None:
        self._quitting = True
        self.sleep_monitor.stop()
        self.curve_engine.stop_all()
        if self.window is not None:
            self.window.lighting_page._stop_animation()
        self.controller.shutdown()
        if self.tray is not None:
            self.tray.shutdown()
        self.quit()

    def _apply_theme(self, theme: str) -> None:
        style_manager = Adw.StyleManager.get_default()
        if theme == "dark":
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        elif theme == "light":
            style_manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        else:
            style_manager.set_color_scheme(Adw.ColorScheme.DEFAULT)

    def set_theme(self, theme: str) -> None:
        self.config.set("theme", theme)
        self._apply_theme(theme)
