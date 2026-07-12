from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..appinfo import APP_ID, APP_NAME  # noqa: E402
from ..backend.device_manager import DeviceInfo  # noqa: E402
from ..i18n import install  # noqa: E402
from .page_curves import CurvesPage  # noqa: E402
from .page_dashboard import DashboardPage  # noqa: E402
from .page_lighting import LightingPage  # noqa: E402
from .page_profiles import ProfilesPage  # noqa: E402
from .page_settings import SettingsPage  # noqa: E402
from .sidebar import Sidebar  # noqa: E402
from .style import install as install_style  # noqa: E402

_ = install()

PAGE_TITLES = {
    "dashboard": _("Dashboard"),
    "curves": _("Curves"),
    "lighting": _("Lighting"),
    "profiles": _("Profiles"),
    "settings": _("Settings"),
}


class LiquidctlGuiWindow(Adw.ApplicationWindow):
    def __init__(self, application) -> None:
        super().__init__(application=application, title=APP_NAME)
        self.app = application
        self.set_icon_name(APP_ID)
        install_style()

        self.devices: list[DeviceInfo] = []
        self.active_device_key: str | None = None

        self.set_default_size(
            application.config.get("window_width", 1080),
            application.config.get("window_height", 680),
        )
        if application.config.get("window_maximized", False):
            self.maximize()

        self._geometry_save_id: int | None = None
        self.connect("notify::default-width", self._schedule_geometry_save)
        self.connect("notify::default-height", self._schedule_geometry_save)
        self.connect("notify::maximized", self._schedule_geometry_save)

        self.view_stack = Gtk.Stack(vexpand=True, hexpand=True)
        self.dashboard_page = DashboardPage(self)
        self.curves_page = CurvesPage(self)
        self.lighting_page = LightingPage(self)
        self.profiles_page = ProfilesPage(self)
        self.settings_page = SettingsPage(self)

        self.view_stack.add_named(self.dashboard_page, "dashboard")
        self.view_stack.add_named(self.curves_page, "curves")
        self.view_stack.add_named(self.lighting_page, "lighting")
        self.view_stack.add_named(self.profiles_page, "profiles")
        self.view_stack.add_named(self.settings_page, "settings")

        clamp = Adw.Clamp(maximum_size=1400, tightening_threshold=900, child=self.view_stack)

        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(clamp)

        self.title_label = Gtk.Label(label=PAGE_TITLES["dashboard"], css_classes=["title"])
        header = Adw.HeaderBar()
        header.set_title_widget(self.title_label)

        content_toolbar = Adw.ToolbarView()
        content_toolbar.add_top_bar(header)
        content_toolbar.set_content(scroller)
        content_toolbar.set_bottom_bar_style(Adw.ToolbarStyle.FLAT)
        content_toolbar.add_bottom_bar(self.dashboard_page.system_box)

        self.sidebar = Sidebar(self)
        # A minimum this low let the paned handle be dragged until the sidebar
        # became a sliver of a pixel wide - invisible and impossible to grab back.
        self.sidebar.set_size_request(180, -1)
        content_toolbar.set_size_request(320, -1)

        self.split_view = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, wide_handle=False)
        self.split_view.set_start_child(self.sidebar)
        self.split_view.set_end_child(content_toolbar)
        self.split_view.set_resize_start_child(False)
        # False enforces the sidebar's size_request as a hard floor - with True, the
        # handle could still be dragged past it down to (and hiding) zero width.
        self.split_view.set_shrink_start_child(False)
        self.split_view.set_resize_end_child(True)
        self.split_view.set_shrink_end_child(False)
        # max() guards against a sidebar_width saved from before the fix above,
        # which could still be as small as 1px.
        self.split_view.set_position(max(180, application.config.get("sidebar_width", 280)))
        self.split_view.connect("notify::position", self._schedule_geometry_save)
        self.set_content(self.split_view)

        self.navigate("dashboard")
        self.refresh_devices()

    def navigate(self, page_name: str) -> None:
        self.view_stack.set_visible_child_name(page_name)
        self.title_label.set_label(PAGE_TITLES.get(page_name, ""))
        self.sidebar.set_active_nav(page_name)
        self.dashboard_page.system_box.set_visible(page_name == "dashboard")

    def refresh_devices(self) -> None:
        self.app.controller.refresh_devices(self._on_devices_loaded)

    def _on_devices_loaded(self, devices: list[DeviceInfo]) -> None:
        self.devices = devices
        if devices and self.active_device_key not in {d.key for d in devices}:
            default_description = self.app.config.get("default_device")
            preferred = next((d for d in devices if d.description == default_description), None)
            self.active_device_key = (preferred or devices[0]).key
        self.sidebar.update_devices(devices, self.active_device_key)
        self.settings_page.update_devices(devices)
        self.app.controller.list_all_devices(self.settings_page.update_all_devices)
        self.on_active_device_changed()

    def select_device(self, device_key: str) -> None:
        if device_key == self.active_device_key:
            return
        self.active_device_key = device_key
        self.sidebar.update_devices(self.devices, self.active_device_key)
        self.on_active_device_changed()

    @property
    def active_device(self) -> DeviceInfo | None:
        for device in self.devices:
            if device.key == self.active_device_key:
                return device
        return None

    def on_active_device_changed(self) -> None:
        self.dashboard_page.on_device_changed()
        self.curves_page.on_device_changed()
        self.lighting_page.on_device_changed()

    def _schedule_geometry_save(self, *_args) -> None:
        if self._geometry_save_id is not None:
            GLib.source_remove(self._geometry_save_id)
        self._geometry_save_id = GLib.timeout_add(400, self._save_geometry)

    def _save_geometry(self) -> bool:
        self._geometry_save_id = None
        maximized = self.is_maximized()
        updates = {"window_maximized": maximized, "sidebar_width": self.split_view.get_position()}
        if not maximized:
            updates["window_width"] = self.get_width()
            updates["window_height"] = self.get_height()
        self.app.config.set_many(updates)
        return GLib.SOURCE_REMOVE
