from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from ..backend.config_store import PRESET_CURVES  # noqa: E402
from ..backend.device_manager import PUMP_MODES  # noqa: E402
from ..i18n import install  # noqa: E402

_ = install()

TMIN, TMAX = 20, 100
DMIN, DMAX = 0, 100
PAD_L, PAD_R, PAD_T, PAD_B = 44, 20, 16, 34
POINT_RADIUS = 7
HIT_RADIUS = 16
MIN_POINTS = 2
MAX_POINTS = 7  # liquidctl speed profiles accept at most 7 (temperature, duty) pairs

PRESET_LABELS = {
    "silent": _("Silent"),
    "balanced": _("Balanced"),
    "performance": _("Performance"),
    "custom": _("Custom"),
}

CHANNEL_LABELS = {"pump": _("Pump"), "fan": _("Fan")}
CHANNEL_TEMP_SENSOR = {"pump": "liquid temperature", "fan": "liquid temperature"}

PUMP_MODE_LABELS = {
    "quiet": _("Quiet"),
    "balanced": _("Balanced"),
    "extreme": _("Extreme"),
}


class CurveGraph(Gtk.DrawingArea):
    """Editable temperature -> duty curve, drawn and dragged directly on a Cairo surface."""

    def __init__(self, on_point_moved) -> None:
        super().__init__(hexpand=True, vexpand=False, content_width=280, content_height=300)
        self.set_draw_func(self._draw)
        self.points: list[tuple[float, float]] = list(PRESET_CURVES["balanced"])
        self._on_point_moved = on_point_moved
        self._drag_index: int | None = None

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)
        self._drag_start_point: tuple[float, float] | None = None

        primary_click = Gtk.GestureClick(button=1)
        primary_click.connect("pressed", self._on_primary_click)
        self.add_controller(primary_click)

        secondary_click = Gtk.GestureClick(button=3)
        secondary_click.connect("pressed", self._on_secondary_click)
        self.add_controller(secondary_click)

    def set_points(self, points: list[tuple[float, float]]) -> None:
        self.points = sorted(points)
        self.queue_draw()

    def _graph_size(self) -> tuple[float, float]:
        return self.get_width() or 640, self.get_height() or 300

    def _temp_to_x(self, temp: float) -> float:
        w, _h = self._graph_size()
        return PAD_L + (temp - TMIN) / (TMAX - TMIN) * (w - PAD_L - PAD_R)

    def _duty_to_y(self, duty: float) -> float:
        _w, h = self._graph_size()
        return (h - PAD_B) - (duty - DMIN) / (DMAX - DMIN) * (h - PAD_T - PAD_B)

    def _x_to_temp(self, x: float) -> float:
        w, _h = self._graph_size()
        return TMIN + (x - PAD_L) / (w - PAD_L - PAD_R) * (TMAX - TMIN)

    def _y_to_duty(self, y: float) -> float:
        _w, h = self._graph_size()
        return DMIN + ((h - PAD_B) - y) / (h - PAD_T - PAD_B) * (DMAX - DMIN)

    def _nearest_point_index(self, x: float, y: float) -> int | None:
        best_index = None
        best_dist = HIT_RADIUS
        for i, (temp, duty) in enumerate(self.points):
            dx = self._temp_to_x(temp) - x
            dy = self._duty_to_y(duty) - y
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best_index = i
        return best_index

    def _on_drag_begin(self, gesture: Gtk.GestureDrag, start_x: float, start_y: float) -> None:
        self._drag_index = self._nearest_point_index(start_x, start_y)
        self._drag_start_point = self.points[self._drag_index] if self._drag_index is not None else None

    def _on_drag_update(self, gesture: Gtk.GestureDrag, offset_x: float, offset_y: float) -> None:
        if self._drag_index is None or self._drag_start_point is None:
            return
        ok, start_x, start_y = gesture.get_start_point()
        x = start_x + offset_x
        y = start_y + offset_y
        duty = max(DMIN, min(DMAX, self._y_to_duty(y)))
        i = self._drag_index
        temp = self.points[i][0]
        if 0 < i < len(self.points) - 1:
            min_t = self.points[i - 1][0] + 2
            max_t = self.points[i + 1][0] - 2
            temp = max(min_t, min(max_t, self._x_to_temp(x)))
        self.points[i] = (round(temp), round(duty))
        self.queue_draw()

    def _on_drag_end(self, gesture: Gtk.GestureDrag, offset_x: float, offset_y: float) -> None:
        if self._drag_index is not None:
            self._on_point_moved(list(self.points))
        self._drag_index = None
        self._drag_start_point = None

    def _on_primary_click(self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float) -> None:
        if n_press != 2:
            return
        if self._nearest_point_index(x, y) is not None:
            return
        if len(self.points) >= MAX_POINTS:
            return
        temp = round(max(TMIN, min(TMAX, self._x_to_temp(x))))
        duty = round(max(DMIN, min(DMAX, self._y_to_duty(y))))
        if any(abs(t - temp) < 2 for t, _d in self.points):
            return
        self.points = sorted(self.points + [(temp, duty)])
        self.queue_draw()
        self._on_point_moved(list(self.points))

    def _on_secondary_click(self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float) -> None:
        if len(self.points) <= MIN_POINTS:
            return
        index = self._nearest_point_index(x, y)
        if index is None:
            return
        del self.points[index]
        self.queue_draw()
        self._on_point_moved(list(self.points))

    def _draw(self, area, cr, width, height) -> None:
        fg = self.get_color()
        accent = Gdk.RGBA()
        accent.parse("#3584e4")

        cr.select_font_face("sans-serif", 0, 0)
        cr.set_font_size(11)

        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.15)
        cr.set_line_width(1)
        for i in range(5):
            duty = DMIN + (DMAX - DMIN) * i / 4
            y = self._duty_to_y(duty)
            cr.move_to(PAD_L, y)
            cr.line_to(width - PAD_R, y)
            cr.stroke()

        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.65)
        for i in range(5):
            duty = DMIN + (DMAX - DMIN) * i / 4
            y = self._duty_to_y(duty)
            label = f"{int(duty)}%"
            extents = cr.text_extents(label)
            cr.move_to(PAD_L - 8 - extents.width, y + extents.height / 2)
            cr.show_text(label)

        for temp in range(TMIN, TMAX + 1, 10):
            x = self._temp_to_x(temp)
            label = f"{temp}°C"
            extents = cr.text_extents(label)
            cr.move_to(x - extents.width / 2, height - PAD_B + 18)
            cr.show_text(label)

        # Below the first point and above the last, the applied duty is held flat -
        # draw that held range too so the line always reaches both graph edges.
        first_temp, first_duty = self.points[0]
        last_temp, last_duty = self.points[-1]

        cr.set_source_rgba(accent.red, accent.green, accent.blue, 0.35)
        cr.set_line_width(2.5)
        cr.set_dash([4, 4], 0)
        cr.move_to(self._temp_to_x(TMIN), self._duty_to_y(first_duty))
        cr.line_to(self._temp_to_x(first_temp), self._duty_to_y(first_duty))
        cr.move_to(self._temp_to_x(last_temp), self._duty_to_y(last_duty))
        cr.line_to(self._temp_to_x(TMAX), self._duty_to_y(last_duty))
        cr.stroke()
        cr.set_dash([], 0)

        cr.set_source_rgba(accent.red, accent.green, accent.blue, 1.0)
        cr.set_line_width(2.5)
        for i, (temp, duty) in enumerate(self.points):
            x, y = self._temp_to_x(temp), self._duty_to_y(duty)
            if i == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()

        for temp, duty in self.points:
            x, y = self._temp_to_x(temp), self._duty_to_y(duty)
            cr.arc(x, y, POINT_RADIUS, 0, 2 * 3.14159265)
            cr.set_source_rgb(1, 1, 1)
            cr.fill_preserve()
            cr.set_source_rgba(accent.red, accent.green, accent.blue, 1.0)
            cr.set_line_width(2.2)
            cr.stroke()


class CurvesPage(Gtk.Box):
    def __init__(self, window) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                          margin_top=24, margin_bottom=32, margin_start=28, margin_end=28)
        self.window = window
        self.channel = "pump"
        self._available_channels: list[str] = []
        self._curves: dict[tuple[str, str], list[tuple[float, float]]] = {}
        self._presets: dict[tuple[str, str], str] = {}

        top_row = Adw.WrapBox(child_spacing=12, line_spacing=8)

        self.channel_dropdown = Gtk.DropDown(valign=Gtk.Align.CENTER)
        self._channel_model = Gtk.StringList()
        self.channel_dropdown.set_model(self._channel_model)
        self.channel_dropdown.connect("notify::selected", self._on_channel_selected)
        top_row.append(self.channel_dropdown)

        self.preset_box = Adw.WrapBox(child_spacing=6, line_spacing=6)
        self._preset_buttons: dict[str, Gtk.Button] = {}
        for preset_id in ("custom", "silent", "balanced", "performance"):
            button = Gtk.Button(label=PRESET_LABELS[preset_id], css_classes=["pill"])
            if preset_id != "custom":
                button.connect("clicked", lambda _b, p=preset_id: self._apply_preset(p))
            else:
                button.set_can_target(False)  # reflects state only, not clickable
            self._preset_buttons[preset_id] = button
            self.preset_box.append(button)
        top_row.append(self.preset_box)
        self.append(top_row)

        self.unsupported_label = Gtk.Label(
            label=_("This device has no control for this channel."),
            wrap=True, css_classes=["dim-label"], margin_top=40,
        )
        self.append(self.unsupported_label)

        pump_mode_hint = Gtk.Label(
            label=_("This pump only supports fixed modes, not a temperature curve."),
            halign=Gtk.Align.START, wrap=True, margin_top=8, margin_bottom=4,
            css_classes=["dim-label", "caption"],
        )
        self.append(pump_mode_hint)
        self.pump_mode_hint = pump_mode_hint

        self.pump_mode_box = Adw.WrapBox(child_spacing=8, line_spacing=8)
        self._pump_mode_buttons: dict[str, Gtk.Button] = {}
        for mode in PUMP_MODES:
            button = Gtk.Button(label=PUMP_MODE_LABELS[mode], css_classes=["pill"])
            button.connect("clicked", lambda _b, m=mode: self._set_pump_mode(m))
            self._pump_mode_buttons[mode] = button
            self.pump_mode_box.append(button)
        self.append(self.pump_mode_box)

        self.graph = CurveGraph(self._on_points_moved)
        self.graph_frame = Gtk.Frame(child=self.graph, margin_top=6)
        self.append(self.graph_frame)

        self.bottom_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, margin_top=10)
        hint = Gtk.Label(
            label=_(
                "Drag points to adjust the curve, double-click to add a point, "
                "right-click a point to remove it."
            ),
            halign=Gtk.Align.START, hexpand=True, wrap=True, css_classes=["dim-label", "caption"],
        )
        reset_button = Gtk.Button(label=_("Restore default"))
        reset_button.connect("clicked", lambda _b: self._apply_preset("balanced"))
        self.bottom_row.append(hint)
        self.bottom_row.append(reset_button)
        self.append(self.bottom_row)

    def on_device_changed(self) -> None:
        self._refresh()
        self._reapply_all_channels()

    def _load_curve_state(self, device, channel: str) -> tuple[tuple[str, str], list[tuple[float, float]]]:
        key = (device.key, channel)
        curve = self._curves.get(key)
        if curve is None:
            saved_curve = self.window.app.config.get_device_curve(device.description, channel)
            saved_preset = self.window.app.config.get_device_preset(device.description, channel)
            if saved_curve:
                curve = [tuple(point) for point in saved_curve]
                self._presets[key] = saved_preset or "custom"
            else:
                curve = list(PRESET_CURVES["balanced"])
                self._presets[key] = "balanced"
            self._curves[key] = curve
        return key, curve

    def _reapply_all_channels(self) -> None:
        # The graph/_refresh() only ever pushes the channel currently on screen. Pump-mode-only
        # devices default to showing "pump" first, so without this, a channel like "fan" would
        # never get its curve (re-)applied to hardware just from opening the app - it would sit
        # at whatever duty driver.initialize() reset it to until the user manually visited that
        # tab. Call this whenever a device becomes active so every controllable channel is pushed.
        device = self.window.active_device
        if device is None:
            return
        channels = []
        if device.has_pump_control:
            channels.append("pump")
        if device.has_fan:
            channels.append("fan")
        for channel in channels:
            key, curve = self._load_curve_state(device, channel)
            self._apply_to_device(key, curve)

    def _set_channel(self, channel: str) -> None:
        self.channel = channel
        self._refresh()

    def _on_channel_selected(self, dropdown: Gtk.DropDown, _pspec) -> None:
        index = dropdown.get_selected()
        if 0 <= index < len(self._available_channels):
            self._set_channel(self._available_channels[index])

    def _key(self) -> tuple[str, str] | None:
        device = self.window.active_device
        if device is None:
            return None
        return device.key, self.channel

    def _refresh(self) -> None:
        device = self.window.active_device
        available = []
        if device is not None:
            if device.has_pump_control or device.pump_mode_only:
                available.append("pump")
            if device.has_fan:
                available.append("fan")

        self.channel_dropdown.set_visible(bool(available))
        if available:
            if self.channel not in available:
                self.channel = available[0]
            if available != self._available_channels:
                self._available_channels = available
                self.channel_dropdown.handler_block_by_func(self._on_channel_selected)
                self._channel_model.splice(
                    0, self._channel_model.get_n_items(), [CHANNEL_LABELS[c] for c in available]
                )
                self.channel_dropdown.handler_unblock_by_func(self._on_channel_selected)
            self.channel_dropdown.handler_block_by_func(self._on_channel_selected)
            self.channel_dropdown.set_selected(available.index(self.channel))
            self.channel_dropdown.handler_unblock_by_func(self._on_channel_selected)

        pump_mode_only = device is not None and self.channel == "pump" and device.pump_mode_only
        supported = device is not None and self.channel in available and not pump_mode_only

        self.unsupported_label.set_visible(device is None or self.channel not in available)
        self.pump_mode_hint.set_visible(pump_mode_only)
        self.pump_mode_box.set_visible(pump_mode_only)
        self.graph_frame.set_visible(supported)
        self.preset_box.set_visible(supported)
        self.bottom_row.set_visible(supported)

        if pump_mode_only:
            self._update_pump_mode_highlight()
            return
        if not supported:
            return

        key, curve = self._load_curve_state(device, self.channel)
        self.graph.set_points(curve)
        self._apply_to_device(key, curve)
        self._update_preset_highlight()

    def _apply_preset(self, preset_id: str) -> None:
        key = self._key()
        if key is None:
            return
        curve = list(PRESET_CURVES[preset_id])
        self._curves[key] = curve
        self._presets[key] = preset_id
        self.graph.set_points(curve)
        self._apply_to_device(key, curve)
        self._update_preset_highlight()
        self._clear_active_profile()
        self._persist_curve(key, curve, preset_id)

    def _on_points_moved(self, points: list[tuple[float, float]]) -> None:
        key = self._key()
        if key is None:
            return
        self._curves[key] = points
        self._presets[key] = "custom"
        self._apply_to_device(key, points)
        self._update_preset_highlight()
        self._persist_curve(key, points, "custom")
        self._clear_active_profile()

    def _clear_active_profile(self) -> None:
        if self.window.app.config.get("active_profile_id") is not None:
            self.window.app.config.set("active_profile_id", None)
        self.window.profiles_page.refresh()

    def set_curve_for_channel(self, channel: str, curve: list[tuple[float, float]], preset: str) -> None:
        device = self.window.active_device
        if device is None:
            return
        if channel == "pump" and not device.has_pump_control:
            return  # e.g. pump_mode_only devices have no duty curve to set
        if channel == "fan" and not device.has_fan:
            return
        key = (device.key, channel)
        curve = list(curve)
        self._curves[key] = curve
        self._presets[key] = preset
        self._persist_curve(key, curve, preset)
        if channel == self.channel:
            self.graph.set_points(curve)
            self._update_preset_highlight()
        self._apply_to_device(key, curve)

    def _persist_curve(self, key: tuple[str, str], curve: list[tuple[float, float]], preset: str) -> None:
        device = self.window.active_device
        if device is None:
            return
        _device_key, channel = key
        self.window.app.config.set_device_curve(device.description, channel, curve, preset)

    def _update_preset_highlight(self) -> None:
        key = self._key()
        active = self._presets.get(key, "balanced") if key else "balanced"
        for preset_id, button in self._preset_buttons.items():
            if preset_id == active:
                button.add_css_class("suggested-action")
            else:
                button.remove_css_class("suggested-action")

    def _apply_to_device(self, key: tuple[str, str], curve: list[tuple[float, float]]) -> None:
        device_key, channel = key
        sensor = CHANNEL_TEMP_SENSOR[channel]
        self.window.app.curve_engine.apply_curve(device_key, channel, curve, sensor)

    def _set_pump_mode(self, mode: str) -> None:
        device = self.window.active_device
        if device is None:
            return
        self.window.app.config.set("pump_mode", mode)
        self.window.app.controller.pump_mode = mode

        def on_done(_result) -> None:
            self.window.lighting_page.reapply()

        self.window.app.controller.set_pump_mode(device.key, mode, on_done=on_done)
        self._update_pump_mode_highlight()
        self._clear_active_profile()

    def _update_pump_mode_highlight(self) -> None:
        current = self.window.app.config.get("pump_mode", "balanced")
        for mode, button in self._pump_mode_buttons.items():
            if mode == current:
                button.add_css_class("suggested-action")
            else:
                button.remove_css_class("suggested-action")
