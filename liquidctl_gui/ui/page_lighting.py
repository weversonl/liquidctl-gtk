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
MODES = ["off", "static", "breathing", "pulse", "spectrum"]
MODE_LABELS = {
    "off": _("Off"),
    "static": _("Static"),
    "breathing": _("Breathing"),
    "pulse": _("Pulse"),
    "spectrum": _("Spectrum"),
}
ANIMATED_MODES = {"breathing", "pulse", "spectrum"}
DRIVER_MODE = {"off": "off", "static": "fixed"}  # animated modes resolve to "fixed" per tick

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
        self._speed = cfg.get("speed", 50)
        self._brightness = cfg.get("brightness", 80)
        self._anim_timeout_id: int | None = None
        self._anim_start_time = 0.0

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

        self.color_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        color_header = Gtk.Label(label=_("Color"), halign=Gtk.Align.START, css_classes=["heading"])
        self.color_section.append(color_header)

        self.color_box = Adw.WrapBox(child_spacing=10, line_spacing=10)
        self._color_buttons: dict[str, Gtk.Button] = {}
        for hex_color in SWATCHES:
            btn = Gtk.Button(css_classes=["circular", "color-swatch"])
            btn.set_size_request(30, 30)
            provider = Gtk.CssProvider()
            provider.load_from_string(f"button {{ background: {hex_color}; border-radius: 999px; }}")
            btn.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            btn.connect("clicked", lambda _b, c=hex_color: self._set_color(c))
            self._color_buttons[hex_color] = btn
            self.color_box.append(btn)

        self.color_dialog = Gtk.ColorDialog(with_alpha=False)
        self.picker_button = Gtk.Button(
            css_classes=["circular", "color-swatch", "color-picker-swatch"],
            tooltip_text=_("Custom color"), valign=Gtk.Align.CENTER,
        )
        self.picker_button.set_size_request(30, 30)
        self.picker_button.connect("clicked", self._on_pick_custom_color)

        picker_icon = Gtk.Image.new_from_icon_name("list-add-symbolic")
        picker_icon.set_can_target(False)
        picker_icon.set_halign(Gtk.Align.CENTER)
        picker_icon.set_valign(Gtk.Align.CENTER)
        picker_icon.add_css_class("color-picker-icon")

        picker_overlay = Gtk.Overlay(child=self.picker_button)
        picker_overlay.add_overlay(picker_icon)
        self.color_box.append(picker_overlay)

        self.color_section.append(self.color_box)
        self.content_box.append(self.color_section)
        self._update_color_selection()

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
        supported = device is not None and device.has_lighting
        self.unsupported_label.set_visible(not supported)
        self.content_box.set_visible(supported)
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

    def _update_mode_sections(self) -> None:
        is_off = self._mode == "off"
        self.color_section.set_visible(not is_off)
        self.brightness_section.set_visible(not is_off)
        self.speed_section.set_visible(not is_off and self._mode in ANIMATED_MODES)

    def _update_mode_highlight(self) -> None:
        for mode, button in self._mode_buttons.items():
            if mode == self._mode:
                button.add_css_class("suggested-action")
            else:
                button.remove_css_class("suggested-action")

    def _set_color(self, hex_color: str) -> None:
        self._color = hex_color
        self._persist()
        if self._mode not in ANIMATED_MODES:
            self._start_or_push()
        self._update_color_selection()

    def _on_pick_custom_color(self, _button: Gtk.Button) -> None:
        initial = Gdk.RGBA()
        initial.parse(self._color)
        self.color_dialog.choose_rgba(self.get_root(), initial, None, self._on_color_dialog_done)

    def _on_color_dialog_done(self, dialog: Gtk.ColorDialog, result, _user_data=None) -> None:
        try:
            rgba = dialog.choose_rgba_finish(result)
        except GLib.Error:
            return
        hex_color = "#{:02x}{:02x}{:02x}".format(
            round(rgba.red * 255), round(rgba.green * 255), round(rgba.blue * 255)
        )
        self._set_color(hex_color)

    def _update_color_selection(self) -> None:
        for hex_color, button in self._color_buttons.items():
            if hex_color == self._color:
                button.add_css_class("selected")
            else:
                button.remove_css_class("selected")

        if self._color in self._color_buttons:
            self.picker_button.remove_css_class("selected")
        else:
            self.picker_button.add_css_class("selected")

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
            "mode": self._mode, "color": self._color,
            "speed": self._speed, "brightness": self._brightness,
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
