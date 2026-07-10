from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk, Pango  # noqa: E402

import liquidctl  # noqa: E402

from ..i18n import install  # noqa: E402

_ = install()

NAV_ITEMS = [
    ("dashboard", "view-grid-symbolic", None),
    ("curves", "media-playlist-consecutive-symbolic", None),
    ("lighting", "weather-clear-night-symbolic", None),
    ("profiles", "document-properties-symbolic", None),
    ("settings", "emblem-system-symbolic", None),
]


def _ellipsized_label_factory() -> Gtk.SignalListItemFactory:
    factory = Gtk.SignalListItemFactory()

    def setup(_factory, list_item: Gtk.ListItem) -> None:
        list_item.set_child(Gtk.Label(halign=Gtk.Align.START, hexpand=True, ellipsize=Pango.EllipsizeMode.END))

    def bind(_factory, list_item: Gtk.ListItem) -> None:
        list_item.get_child().set_label(list_item.get_item().get_string())

    factory.connect("setup", setup)
    factory.connect("bind", bind)
    return factory


class Sidebar(Gtk.Box):
    def __init__(self, window) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, overflow=Gtk.Overflow.HIDDEN)
        self.window = window
        self.add_css_class("sidebar-pane")

        self._device_dropdown = Gtk.DropDown(margin_start=10, margin_end=10, margin_top=10, margin_bottom=6)
        self._device_model = Gtk.StringList()
        self._device_dropdown.set_model(self._device_model)
        self._device_dropdown.set_factory(_ellipsized_label_factory())
        self._device_dropdown.connect("notify::selected", self._on_device_selected)
        self.append(self._device_dropdown)

        self._nav_rows: dict[str, Gtk.ListBoxRow] = {}
        nav_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE,
                                margin_start=10, margin_end=10, css_classes=["navigation-sidebar"])
        nav_list.connect("row-selected", self._on_nav_selected)

        labels = {
            "dashboard": _("Dashboard"),
            "curves": _("Curves"),
            "lighting": _("Lighting"),
            "profiles": _("Profiles"),
            "settings": _("Settings"),
        }
        for page_name, icon_name, _unused in NAV_ITEMS:
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12,
                               margin_top=8, margin_bottom=8, margin_start=10, margin_end=10)
            row_box.append(Gtk.Image.new_from_icon_name(icon_name))
            row_box.append(Gtk.Label(label=labels[page_name], halign=Gtk.Align.START,
                                      hexpand=True, ellipsize=Pango.EllipsizeMode.END))
            list_row = Gtk.ListBoxRow(child=row_box)
            list_row.page_name = page_name  # type: ignore[attr-defined]
            nav_list.append(list_row)
            self._nav_rows[page_name] = list_row

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(nav_list)
        self.append(scroller)

        version = getattr(liquidctl, "__version__", "?")
        status_label = Gtk.Label(
            label=_("liquidctl {version} · driver connected").format(version=version),
            halign=Gtk.Align.START,
            hexpand=True,
            ellipsize=Pango.EllipsizeMode.END,
            margin_start=14,
            margin_end=14,
            margin_top=6,
            margin_bottom=10,
            css_classes=["dim-label", "caption"],
        )
        self.append(status_label)

    def update_devices(self, devices, active_key: str | None) -> None:
        self._device_model.splice(0, self._device_model.get_n_items(), [d.description for d in devices])
        for index, device in enumerate(devices):
            if device.key == active_key:
                self._device_dropdown.set_selected(index)
                break
        self._devices = devices

    def set_active_nav(self, page_name: str) -> None:
        row = self._nav_rows.get(page_name)
        if row is not None:
            row.get_parent().select_row(row)

    def _on_device_selected(self, dropdown, _pspec) -> None:
        index = dropdown.get_selected()
        devices = getattr(self, "_devices", [])
        if 0 <= index < len(devices):
            self.window.select_device(devices[index].key)

    def _on_nav_selected(self, _listbox, row) -> None:
        if row is not None:
            self.window.navigate(row.page_name)
