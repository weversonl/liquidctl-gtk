from __future__ import annotations

import re

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk, Pango  # noqa: E402

from ..backend import system_sensors  # noqa: E402
from ..i18n import install  # noqa: E402

_ = install()

_FAN_KEY_RE = re.compile(r"fan\s*(\d+)", re.IGNORECASE)


def _card(title: str) -> tuple[Gtk.Box, Gtk.Label, Gtk.Label]:
    """A libadwaita 'card' box with real internal padding (not just outer margin)."""
    card = Gtk.Box(css_classes=["card"], hexpand=True)
    card.set_size_request(140, -1)

    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True,
                       margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
    header = Gtk.Label(label=title, halign=Gtk.Align.START, wrap=True,
                        css_classes=["dim-label", "caption-heading"])
    value = Gtk.Label(label="—", halign=Gtk.Align.START, css_classes=["title-1"])
    sub = Gtk.Label(label="", halign=Gtk.Align.START, css_classes=["dim-label", "caption"])
    content.append(header)
    content.append(value)
    content.append(sub)
    card.append(content)
    return card, value, sub


class DashboardPage(Gtk.Box):
    def __init__(self, window) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                          margin_top=24, margin_bottom=32, margin_start=28, margin_end=28)
        self.window = window
        self._timeout_id: int | None = None

        self.header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        self.device_name_label = Gtk.Label(label="", halign=Gtk.Align.START, css_classes=["title-2"])
        self.device_type_label = Gtk.Label(label="", halign=Gtk.Align.START, css_classes=["dim-label"])
        title_box.append(self.device_name_label)
        title_box.append(self.device_type_label)
        self.header_box.append(title_box)
        self.status_pill = Gtk.Label(label=_("Connected"), valign=Gtk.Align.CENTER,
                                      css_classes=["status-badge", "success"])
        self.header_box.append(self.status_pill)
        self.append(self.header_box)

        self.sensor_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14, homogeneous=True)
        self.liquid_temp_card, self.liquid_temp_value, self.liquid_temp_sub = _card(_("Liquid temperature"))
        self.pump_card, self.pump_value, self.pump_sub = _card(_("Pump"))
        self.fan_card, self.fan_value, self.fan_sub = _card(_("Fan"))
        self.append(self.sensor_row)

        self.empty_label = Gtk.Label(
            label=_("No liquidctl devices were detected. Check USB connections and udev permissions."),
            wrap=True, css_classes=["dim-label"], margin_top=40,
        )
        self.append(self.empty_label)
        self.empty_label.set_visible(False)

        # Deliberately NOT appended into this page: it lives in the window's
        # Adw.ToolbarView bottom bar instead (see window.py), which stays pinned to
        # the window edge outside the scrollable content - unlike a child of this
        # page, it can never be pushed off-screen or require scrolling to reach.
        self.system_box = Adw.WrapBox(child_spacing=16, line_spacing=2,
                                       halign=Gtk.Align.END, margin_top=6, margin_bottom=6,
                                       margin_start=12, margin_end=12)
        self.cpu_label = Gtk.Label(halign=Gtk.Align.END, css_classes=["dim-label", "caption"],
                                    ellipsize=Pango.EllipsizeMode.END, max_width_chars=40)
        self.system_box.append(self.cpu_label)

        self._cpu_name = system_sensors.get_cpu_name()
        self._fan_detail_labels: list[Gtk.Label] = []
        self._update_cpu()
        GLib.timeout_add_seconds(2, self._update_cpu)

    def on_device_changed(self) -> None:
        if self._timeout_id is not None:
            GLib.source_remove(self._timeout_id)
            self._timeout_id = None

        device = self.window.active_device
        for child in list(self.sensor_row):
            self.sensor_row.remove(child)

        if device is None:
            self.header_box.set_visible(False)
            self.empty_label.set_visible(True)
            return

        self.header_box.set_visible(True)
        self.empty_label.set_visible(False)
        self.device_name_label.set_label(device.description)
        self.device_type_label.set_label(device.driver_class_name)

        if device.has_pump:
            self.sensor_row.append(self.liquid_temp_card)
            self.sensor_row.append(self.pump_card)
        if device.has_fan:
            self.sensor_row.append(self.fan_card)

        self._poll()
        poll_interval = self.window.app.config.get("poll_interval", 2)
        self._timeout_id = GLib.timeout_add_seconds(max(1, poll_interval), self._on_tick)

    def _on_tick(self) -> bool:
        if self.window.active_device is None:
            self._timeout_id = None
            return GLib.SOURCE_REMOVE
        self._poll()
        return GLib.SOURCE_CONTINUE

    def _poll(self) -> None:
        device = self.window.active_device
        if device is None:
            return
        self.window.app.controller.get_status(device.key, self._on_status)

    def _on_status(self, status) -> None:
        unit = self.window.app.config.get("temp_unit", "C")
        fans: dict[int, dict[str, float]] = {}

        for key, value, raw_unit in status:
            lower_key = key.lower()
            match = _FAN_KEY_RE.search(lower_key)
            if "liquid temperature" in lower_key:
                self.liquid_temp_value.set_label(self._format_temp(value, unit))
            elif lower_key.startswith("pump speed"):
                self.pump_value.set_label(_("{rpm} RPM").format(rpm=int(value)))
            elif lower_key.startswith("pump duty"):
                self.pump_sub.set_label(_("{duty}% power").format(duty=int(value)))
            elif match and "speed" in lower_key:
                fans.setdefault(int(match.group(1)), {})["rpm"] = value
            elif match and "duty" in lower_key:
                fans.setdefault(int(match.group(1)), {})["duty"] = value

        if fans:
            rpms = [f["rpm"] for f in fans.values() if "rpm" in f]
            duties = [f["duty"] for f in fans.values() if "duty" in f]
            if rpms:
                self.fan_value.set_label(_("{rpm} RPM").format(rpm=round(sum(rpms) / len(rpms))))
            if duties:
                self.fan_sub.set_label(_("{duty}% power").format(duty=round(sum(duties) / len(duties))))

        self._update_fan_details(fans)

    def _update_fan_details(self, fans: dict[int, dict[str, float]]) -> None:
        for label in self._fan_detail_labels:
            self.system_box.remove(label)
        self._fan_detail_labels.clear()

        for index in sorted(fans):
            values = fans[index]
            if "rpm" not in values or "duty" not in values:
                continue
            text = _("Fan {n}: {rpm} RPM / {duty}%").format(
                n=index, rpm=round(values["rpm"]), duty=round(values["duty"])
            )
            label = Gtk.Label(label=text, halign=Gtk.Align.END, css_classes=["dim-label", "caption"])
            self.system_box.append(label)
            self._fan_detail_labels.append(label)

    def _update_cpu(self) -> bool:
        temp = system_sensors.get_cpu_temp()
        if temp is None:
            self.cpu_label.set_visible(False)
        else:
            unit = self.window.app.config.get("temp_unit", "C")
            self.cpu_label.set_visible(True)
            self.cpu_label.set_label(f"{self._cpu_name}: {self._format_temp(temp, unit)}")
        return GLib.SOURCE_CONTINUE

    @staticmethod
    def _format_temp(celsius: float, unit: str) -> str:
        if unit == "F":
            return f"{celsius * 9 / 5 + 32:.1f}°F"
        return f"{celsius:.1f}°C"
