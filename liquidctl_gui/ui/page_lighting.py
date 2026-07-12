from __future__ import annotations

import colorsys
import math
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from ..i18n import install  # noqa: E402

_ = install()

# liquidctl's HydroPlatinum driver only implements ('led', 'off') and ('led', 'fixed') -
# there is no on-device animation. Breathing/pulse/spectrum are driven from here instead,
# by repeatedly pushing a computed 'fixed' color, matching the driver's own guidance
# ("animations still require successive calls to this API").
MODES = ["off", "static", "breathing", "pulse", "spectrum", "rainbow", "comet", "wave", "police", "reactive"]
MODE_LABELS = {
    "off": _("Off"),
    "static": _("Static"),
    "breathing": _("Breathing"),
    "pulse": _("Pulse"),
    "spectrum": _("Spectrum"),
    "rainbow": _("Rainbow"),
    "comet": _("Comet"),
    "wave": _("Wave"),
    "police": _("Police Lights"),
    "reactive": _("Reactive"),
}
ANIMATED_MODES = {"breathing", "pulse", "spectrum", "rainbow", "comet", "wave", "police", "reactive"}
DRIVER_MODE = {"off": "off", "static": "fixed"}  # animated modes resolve to "fixed" per tick

# These address each LED individually via 'super-fixed' - only devices that expose more
# than one individually-addressable LED (DeviceInfo.led_count) can use them, e.g. the
# HydroPlatinum family's pump-head ring (16 LEDs on the H150i Elite). 'reactive' pushes a
# single color to all LEDs instead, so it isn't gated the same way - it needs a liquid
# temperature sensor (has_pump) instead.
PER_LED_MODES = {"rainbow", "comet", "wave", "police"}
PER_LED_MIN_LEDS = 2

# Colors don't come from the picker for these - rainbow is a full hue sweep and reactive's
# color is derived from temperature, so a static swatch there would be misleading. Every
# other mode (including police, whose second color is auto-derived from the picked one)
# does use the picker.
NO_COLOR_PICKER_MODES = {"rainbow", "reactive"}
DIRECTIONAL_MODES = {"rainbow", "comet", "wave"}

DIRECTIONS = ["clockwise", "counterclockwise"]
DIRECTION_LABELS = {
    "clockwise": _("Clockwise"),
    "counterclockwise": _("Counterclockwise"),
}

# comet: number of lit LEDs behind the head, fading out along the trail.
COMET_TRAIL_LEDS = 5
# reactive: liquid temperature range the color gradient is stretched across, as a
# cold -> mid -> hot sequence (green -> yellow -> red).
REACTIVE_TEMP_MIN = 20.0
REACTIVE_TEMP_MAX = 60.0
REACTIVE_COLD_RGB = (0x2e, 0xc2, 0x7a)
REACTIVE_MID_RGB = (0xe5, 0xa5, 0x0a)
REACTIVE_HOT_RGB = (0xe0, 0x1b, 0x24)
REACTIVE_POLL_SECONDS = 1.5

SWATCHES = ["#3584e4", "#33d17a", "#e5a50a", "#e01b24", "#9141ac", "#62a0ea", "#f66151", "#ffffff"]
ANIMATION_TICK_MS = 100


class LightingPage(Gtk.Box):
    def __init__(self, window) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                          margin_top=24, margin_bottom=32, margin_start=28, margin_end=28)
        self.window = window
        cfg = window.app.config.get("lighting", {})
        self._mode = cfg.get("mode", "static")
        self._color = cfg.get("color", "#3584e4")
        self._color2 = cfg.get("color2", "#e01b24")
        self._speed = cfg.get("speed", 50)
        self._brightness = cfg.get("brightness", 80)
        self._direction = cfg.get("direction", "clockwise")
        self._anim_timeout_id: int | None = None
        self._anim_start_time = 0.0
        self._reactive_temp: float | None = None
        self._reactive_last_poll = 0.0

        self.unsupported_label = Gtk.Label(
            label=_("This device has no RGB lighting."), wrap=True,
            css_classes=["dim-label"], margin_top=40,
        )
        self.append(self.unsupported_label)

        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.append(self.content_box)

        mode_header = Gtk.Label(label=_("Mode"), halign=Gtk.Align.START, css_classes=["heading"])
        self.content_box.append(mode_header)
        self.mode_box = Adw.WrapBox(child_spacing=8, line_spacing=8)
        self._mode_buttons: dict[str, Gtk.ToggleButton] = {}
        first = None
        for mode in MODES:
            btn = Gtk.ToggleButton(label=MODE_LABELS[mode], css_classes=["pill"])
            if first is None:
                first = btn
            else:
                btn.set_group(first)
            btn.set_active(mode == self._mode)
            btn.connect("toggled", lambda b, m=mode: b.get_active() and self._set_mode(m))
            self._mode_buttons[mode] = btn
            self.mode_box.append(btn)
        self.content_box.append(self.mode_box)
        self._update_mode_highlight()

        self.direction_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        direction_header = Gtk.Label(label=_("Direction"), halign=Gtk.Align.START, css_classes=["heading"])
        self.direction_section.append(direction_header)
        self.direction_box = Adw.WrapBox(child_spacing=8, line_spacing=8)
        self._direction_buttons: dict[str, Gtk.ToggleButton] = {}
        first_direction = None
        for direction in DIRECTIONS:
            btn = Gtk.ToggleButton(label=DIRECTION_LABELS[direction], css_classes=["pill"])
            if first_direction is None:
                first_direction = btn
            else:
                btn.set_group(first_direction)
            btn.set_active(direction == self._direction)
            btn.connect("toggled", lambda b, d=direction: b.get_active() and self._set_direction(d))
            self._direction_buttons[direction] = btn
            self.direction_box.append(btn)
        self.direction_section.append(self.direction_box)
        self.content_box.append(self.direction_section)
        self._update_direction_highlight()

        self.color_section, self._refresh_color_selection = self._build_color_section(
            _("Color"), lambda: self._color, self._set_color
        )
        self.content_box.append(self.color_section)

        # Police is a two-color strobe - both colors are user-chosen, not one picked and
        # one auto-derived, so it gets its own picker instead of reusing self._color twice.
        self.color2_section, self._refresh_color2_selection = self._build_color_section(
            _("Second color"), lambda: self._color2, self._set_color2
        )
        self.content_box.append(self.color2_section)

        self.speed_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        speed_header_box = Gtk.Box(spacing=8)
        speed_header_box.append(Gtk.Label(label=_("Speed"), hexpand=True, halign=Gtk.Align.START))
        self.speed_value_label = Gtk.Label(label=f"{self._speed}%")
        speed_header_box.append(self.speed_value_label)
        self.speed_section.append(speed_header_box)
        self.speed_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=Gtk.Adjustment(
            value=self._speed, lower=0, upper=100, step_increment=1))
        self.speed_scale.connect("value-changed", self._on_speed_changed)
        self.speed_section.append(self.speed_scale)
        self.content_box.append(self.speed_section)

        self.brightness_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        brightness_header_box = Gtk.Box(spacing=8)
        brightness_header_box.append(Gtk.Label(label=_("Brightness"), hexpand=True, halign=Gtk.Align.START))
        self.brightness_value_label = Gtk.Label(label=f"{self._brightness}%")
        brightness_header_box.append(self.brightness_value_label)
        self.brightness_section.append(brightness_header_box)
        self.brightness_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=Gtk.Adjustment(
            value=self._brightness, lower=0, upper=100, step_increment=1))
        self.brightness_scale.connect("value-changed", self._on_brightness_changed)
        self.brightness_section.append(self.brightness_scale)
        self.content_box.append(self.brightness_section)

        self._update_mode_sections()

    def on_device_changed(self) -> None:
        device = self.window.active_device
        has_hardware = device is not None and device.has_lighting
        supported = has_hardware and device.lighting_effects_supported

        if not has_hardware:
            self.unsupported_label.set_label(_("This device has no RGB lighting."))
        elif not supported:
            self.unsupported_label.set_label(
                _("This device has RGB lighting, but its protocol isn't supported by this app yet.")
            )
        self.unsupported_label.set_visible(not supported)
        self.content_box.set_visible(supported)

        per_led_supported = device is not None and device.led_count >= PER_LED_MIN_LEDS
        for mode in PER_LED_MODES:
            self._mode_buttons[mode].set_visible(per_led_supported)

        reactive_supported = device is not None and device.has_pump
        self._mode_buttons["reactive"].set_visible(reactive_supported)

        mode_now_unsupported = (
            (self._mode in PER_LED_MODES and not per_led_supported)
            or (self._mode == "reactive" and not reactive_supported)
        )
        if mode_now_unsupported:
            self._mode_buttons["static"].set_active(True)  # triggers _set_mode via "toggled"

        if supported:
            self._start_or_push()
        else:
            self._stop_animation()

    def reapply(self) -> None:
        self._start_or_push()

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        self._update_mode_sections()
        self._persist()
        self._start_or_push()
        self._update_mode_highlight()

    def _set_direction(self, direction: str) -> None:
        self._direction = direction
        self._persist()
        self._update_direction_highlight()

    def _update_direction_highlight(self) -> None:
        for direction, button in self._direction_buttons.items():
            if direction == self._direction:
                button.add_css_class("suggested-action")
            else:
                button.remove_css_class("suggested-action")

    def _update_mode_sections(self) -> None:
        is_off = self._mode == "off"
        self.color_section.set_visible(not is_off and self._mode not in NO_COLOR_PICKER_MODES)
        self.color2_section.set_visible(self._mode == "police")
        self.brightness_section.set_visible(not is_off)
        self.speed_section.set_visible(not is_off and self._mode in ANIMATED_MODES)
        self.direction_section.set_visible(self._mode in DIRECTIONAL_MODES)

    def _update_mode_highlight(self) -> None:
        for mode, button in self._mode_buttons.items():
            if mode == self._mode:
                button.add_css_class("suggested-action")
            else:
                button.remove_css_class("suggested-action")

    def _build_color_section(self, title: str, get_color, on_color_chosen):
        """Builds a heading + preset swatches + custom-color-picker row. Used twice:
        once for the primary color (most modes), once for police's second color."""
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        section.append(Gtk.Label(label=title, halign=Gtk.Align.START, css_classes=["heading"]))

        box = Adw.WrapBox(child_spacing=10, line_spacing=10)
        swatch_buttons: dict[str, Gtk.Button] = {}
        dialog = Gtk.ColorDialog(with_alpha=False)
        picker_button = Gtk.Button(
            css_classes=["circular", "color-swatch", "color-picker-swatch"],
            tooltip_text=_("Custom color"), valign=Gtk.Align.CENTER,
        )
        picker_button.set_size_request(30, 30)

        def refresh_selection() -> None:
            current = get_color()
            for hex_color, button in swatch_buttons.items():
                if hex_color == current:
                    button.add_css_class("selected")
                else:
                    button.remove_css_class("selected")
            if current in swatch_buttons:
                picker_button.remove_css_class("selected")
            else:
                picker_button.add_css_class("selected")

        def select(hex_color: str) -> None:
            on_color_chosen(hex_color)
            refresh_selection()

        for hex_color in SWATCHES:
            btn = Gtk.Button(css_classes=["circular", "color-swatch"])
            btn.set_size_request(30, 30)
            provider = Gtk.CssProvider()
            provider.load_from_string(f"button {{ background: {hex_color}; border-radius: 999px; }}")
            btn.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            btn.connect("clicked", lambda _b, c=hex_color: select(c))
            swatch_buttons[hex_color] = btn
            box.append(btn)

        def on_dialog_done(dlg: Gtk.ColorDialog, result, _user_data=None) -> None:
            try:
                rgba = dlg.choose_rgba_finish(result)
            except GLib.Error:
                return
            select("#{:02x}{:02x}{:02x}".format(
                round(rgba.red * 255), round(rgba.green * 255), round(rgba.blue * 255)
            ))

        def on_pick_clicked(_button: Gtk.Button) -> None:
            initial = Gdk.RGBA()
            initial.parse(get_color())
            dialog.choose_rgba(self.get_root(), initial, None, on_dialog_done)

        picker_button.connect("clicked", on_pick_clicked)

        picker_icon = Gtk.Image.new_from_icon_name("list-add-symbolic")
        picker_icon.set_can_target(False)
        picker_icon.set_halign(Gtk.Align.CENTER)
        picker_icon.set_valign(Gtk.Align.CENTER)
        picker_icon.add_css_class("color-picker-icon")
        picker_overlay = Gtk.Overlay(child=picker_button)
        picker_overlay.add_overlay(picker_icon)
        box.append(picker_overlay)

        section.append(box)
        refresh_selection()
        return section, refresh_selection

    def _set_color(self, hex_color: str) -> None:
        self._color = hex_color
        self._persist()
        if self._mode not in ANIMATED_MODES:
            self._start_or_push()
        self._refresh_color_selection()

    def _set_color2(self, hex_color: str) -> None:
        self._color2 = hex_color
        self._persist()
        self._refresh_color2_selection()

    def _on_speed_changed(self, scale: Gtk.Scale) -> None:
        self._speed = int(scale.get_value())
        self.speed_value_label.set_label(f"{self._speed}%")
        self._persist()

    def _on_brightness_changed(self, scale: Gtk.Scale) -> None:
        self._brightness = int(scale.get_value())
        self.brightness_value_label.set_label(f"{self._brightness}%")
        self._persist()
        if self._mode not in ANIMATED_MODES:
            self._start_or_push()

    def _persist(self) -> None:
        self.window.app.config.set("lighting", {
            "mode": self._mode, "color": self._color, "color2": self._color2,
            "speed": self._speed, "brightness": self._brightness, "direction": self._direction,
        })

    # -- device push / animation loop ------------------------------------------------

    def _start_or_push(self) -> None:
        self._stop_animation()
        if self._mode in ANIMATED_MODES:
            self._anim_start_time = time.monotonic()
            self._anim_timeout_id = GLib.timeout_add(ANIMATION_TICK_MS, self._on_animation_tick)
            self._on_animation_tick()
        else:
            self._push_color(self._current_static_rgb())

    def _stop_animation(self) -> None:
        if self._anim_timeout_id is not None:
            GLib.source_remove(self._anim_timeout_id)
            self._anim_timeout_id = None

    def _on_animation_tick(self) -> bool:
        device = self.window.active_device
        if device is None or not device.has_lighting or self._mode not in ANIMATED_MODES:
            self._anim_timeout_id = None
            return GLib.SOURCE_REMOVE

        elapsed = time.monotonic() - self._anim_start_time
        period = 4.5 - (self._speed / 100) * 4.0  # 4.5s at speed=0 down to ~0.5s at speed=100
        phase = (elapsed % period) / period

        if self._mode in PER_LED_MODES:
            self._push_per_led(device, phase)
            return GLib.SOURCE_CONTINUE

        if self._mode == "reactive":
            self._push_reactive(device)
            return GLib.SOURCE_CONTINUE

        base_r, base_g, base_b = self._hex_to_rgb(self._color)
        brightness = self._brightness / 100

        if self._mode == "spectrum":
            hue = phase
            r, g, b = colorsys.hsv_to_rgb(hue, 1.0, brightness)
            rgb = (round(r * 255), round(g * 255), round(b * 255))
        elif self._mode == "pulse":
            envelope = max(0.0, math.sin(2 * math.pi * phase)) ** 3
            rgb = tuple(round(c * envelope * brightness) for c in (base_r, base_g, base_b))
        else:  # breathing
            envelope = (math.sin(2 * math.pi * phase) + 1) / 2
            rgb = tuple(round(c * envelope * brightness) for c in (base_r, base_g, base_b))

        self._push_color(rgb)
        return GLib.SOURCE_CONTINUE

    def _current_static_rgb(self) -> tuple[int, int, int]:
        r, g, b = self._hex_to_rgb(self._color)
        brightness = self._brightness / 100
        return (round(r * brightness), round(g * brightness), round(b * brightness))

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
        rgba = Gdk.RGBA()
        rgba.parse(hex_color)
        return (round(rgba.red * 255), round(rgba.green * 255), round(rgba.blue * 255))

    def _push_color(self, rgb: tuple[int, int, int]) -> None:
        device = self.window.active_device
        if device is None or not device.has_lighting:
            return
        driver_mode = "off" if self._mode == "off" else "fixed"
        colors = [] if driver_mode == "off" else [rgb]
        self.window.app.controller.set_color(device.key, "led", driver_mode, colors)

    def _push_per_led(self, device, phase: float) -> None:
        if device.led_count < PER_LED_MIN_LEDS:
            return
        n = device.led_count
        brightness = self._brightness / 100
        turn = -phase if self._direction == "clockwise" else phase

        if self._mode == "rainbow":
            colors = self._rainbow_colors(n, turn, brightness)
        elif self._mode == "comet":
            colors = self._comet_colors(n, turn, brightness)
        elif self._mode == "wave":
            colors = self._wave_colors(n, phase, brightness)
        else:  # police
            colors = self._police_colors(n, phase, brightness)

        self.window.app.controller.set_color(device.key, "led", "super-fixed", colors)

    @staticmethod
    def _rainbow_colors(n: int, turn: float, brightness: float) -> list[tuple[int, int, int]]:
        colors = []
        for led_index in range(n):
            hue = (led_index / n + turn) % 1.0
            r, g, b = colorsys.hsv_to_rgb(hue, 1.0, brightness)
            colors.append((round(r * 255), round(g * 255), round(b * 255)))
        return colors

    def _comet_colors(self, n: int, turn: float, brightness: float) -> list[tuple[int, int, int]]:
        base_rgb = self._hex_to_rgb(self._color)
        head = turn * n
        colors = []
        for led_index in range(n):
            distance = (head - led_index) % n
            factor = (1 - distance / COMET_TRAIL_LEDS) * brightness if distance < COMET_TRAIL_LEDS else 0.0
            colors.append(tuple(round(c * factor) for c in base_rgb))
        return colors

    def _wave_colors(self, n: int, phase: float, brightness: float) -> list[tuple[int, int, int]]:
        base_rgb = self._hex_to_rgb(self._color)
        sign = -1 if self._direction == "clockwise" else 1
        colors = []
        for led_index in range(n):
            led_phase = (phase + sign * led_index / n) % 1.0
            envelope = (math.sin(2 * math.pi * led_phase) + 1) / 2
            colors.append(tuple(round(c * envelope * brightness) for c in base_rgb))
        return colors

    def _police_colors(self, n: int, phase: float, brightness: float) -> list[tuple[int, int, int]]:
        color_a = self._hex_to_rgb(self._color)
        color_b = self._hex_to_rgb(self._color2)
        half = n // 2
        swapped = phase >= 0.5
        colors = []
        for led_index in range(n):
            first_half = led_index < half
            color = color_a if (first_half != swapped) else color_b
            colors.append(tuple(round(c * brightness) for c in color))
        return colors

    def _push_reactive(self, device) -> None:
        now = time.monotonic()
        if now - self._reactive_last_poll >= REACTIVE_POLL_SECONDS:
            self._reactive_last_poll = now
            self.window.app.controller.get_status(device.key, self._on_reactive_status)

        if self._reactive_temp is None:
            return  # nothing to show yet - wait for the first status read

        ratio = (self._reactive_temp - REACTIVE_TEMP_MIN) / (REACTIVE_TEMP_MAX - REACTIVE_TEMP_MIN)
        ratio = max(0.0, min(1.0, ratio))
        if ratio <= 0.5:
            low, high, local_ratio = REACTIVE_COLD_RGB, REACTIVE_MID_RGB, ratio / 0.5
        else:
            low, high, local_ratio = REACTIVE_MID_RGB, REACTIVE_HOT_RGB, (ratio - 0.5) / 0.5
        brightness = self._brightness / 100
        rgb = tuple(round((low[i] + local_ratio * (high[i] - low[i])) * brightness) for i in range(3))
        self._push_color(rgb)

    def _on_reactive_status(self, status) -> None:
        for key, value, _unit in status:
            if "liquid temperature" in key.lower():
                self._reactive_temp = value
                break
