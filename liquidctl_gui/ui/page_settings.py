from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..backend import autostart  # noqa: E402
from ..i18n import install  # noqa: E402

_ = install()


def _group(title: str) -> tuple[Gtk.Box, Adw.PreferencesGroup]:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    group = Adw.PreferencesGroup(title=title)
    box.append(group)
    return box, group


class SettingsPage(Gtk.Box):
    def __init__(self, window) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=22,
                          margin_top=24, margin_bottom=32, margin_start=28, margin_end=28)
        self.window = window
        config = window.app.config

        appearance_box, appearance_group = _group(_("Appearance"))
        theme_row = Adw.ActionRow(title=_("Theme"))
        self.theme_dropdown = Gtk.DropDown.new_from_strings([_("System"), _("Dark"), _("Light")])
        theme_values = ["system", "dark", "light"]
        current_theme = config.get("theme", "system")
        self.theme_dropdown.set_selected(theme_values.index(current_theme) if current_theme in theme_values else 0)
        self.theme_dropdown.set_valign(Gtk.Align.CENTER)
        self.theme_dropdown.connect(
            "notify::selected",
            lambda dd, _p: window.app.set_theme(theme_values[dd.get_selected()]),
        )
        theme_row.add_suffix(self.theme_dropdown)
        appearance_group.add(theme_row)

        language_row = Adw.ActionRow(
            title=_("Language"), subtitle=_("Requires restarting the app to take effect")
        )
        # The language names themselves aren't translated - "Português (Brasil)" and
        # "English" should read the same regardless of which language the UI is in.
        self.language_dropdown = Gtk.DropDown.new_from_strings(
            [_("Auto (system)"), "Português (Brasil)", "English"]
        )
        language_values = ["auto", "pt_BR", "en_US"]
        current_language = config.get("language", "auto")
        self.language_dropdown.set_selected(
            language_values.index(current_language) if current_language in language_values else 0
        )
        self.language_dropdown.set_valign(Gtk.Align.CENTER)
        self.language_dropdown.connect("notify::selected", self._on_language_changed)
        language_row.add_suffix(self.language_dropdown)
        appearance_group.add(language_row)
        self.append(appearance_box)

        devices_box, devices_group = _group(_("Devices"))
        default_device_row = Adw.ActionRow(title=_("Default device"),
                                            subtitle=_("Which device to select when the app starts"))
        self._device_options: list[str | None] = [None]
        self.default_device_dropdown = Gtk.DropDown.new_from_strings([_("Auto (first detected)")])
        self.default_device_dropdown.set_valign(Gtk.Align.CENTER)
        self.default_device_dropdown.connect("notify::selected", self._on_default_device_changed)
        default_device_row.add_suffix(self.default_device_dropdown)
        devices_group.add(default_device_row)
        self.append(devices_box)

        enable_box, self.device_enable_group = _group(_("Enabled devices"))
        self.device_enable_group.set_description(
            _("Disabled devices are never connected to or controlled by the app.")
        )
        self._device_toggle_rows: dict[str, Adw.SwitchRow] = {}
        self.append(enable_box)

        behavior_box, behavior_group = _group(_("Behavior"))
        autostart_row = Adw.SwitchRow(title=_("Start with the system"), active=config.get("autostart", False))
        autostart_row.connect("notify::active", self._on_autostart_toggled)
        behavior_group.add(autostart_row)
        notif_row = Adw.SwitchRow(title=_("High temperature notifications"), active=config.get("notifications", True))
        notif_row.connect("notify::active", lambda row, _p: config.set("notifications", row.get_active()))
        behavior_group.add(notif_row)
        self.append(behavior_box)

        units_box, units_group = _group(_("Units and monitoring"))
        unit_row = Adw.ActionRow(title=_("Temperature unit"))
        self.unit_dropdown = Gtk.DropDown.new_from_strings(["°C", "°F"])
        self.unit_dropdown.set_selected(0 if config.get("temp_unit", "C") == "C" else 1)
        self.unit_dropdown.set_valign(Gtk.Align.CENTER)
        self.unit_dropdown.connect(
            "notify::selected",
            lambda dd, _p: config.set("temp_unit", "C" if dd.get_selected() == 0 else "F"),
        )
        unit_row.add_suffix(self.unit_dropdown)
        units_group.add(unit_row)

        poll_row = Adw.ActionRow(title=_("Polling interval"))
        self.poll_scale = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL,
            adjustment=Gtk.Adjustment(value=config.get("poll_interval", 2), lower=1, upper=10, step_increment=1),
            hexpand=True, valign=Gtk.Align.CENTER, digits=0, draw_value=True,
        )
        self.poll_scale.set_size_request(220, -1)
        self.poll_scale.connect("value-changed", self._on_poll_changed)
        poll_row.add_suffix(self.poll_scale)
        units_group.add(poll_row)

        validation_row = Adw.ActionRow(
            title=_("Fan duty validation interval"),
            subtitle=_(
                "How often the app double-checks that fan speeds actually match the curve. "
                "Higher values use less CPU/USB traffic but take longer to catch a hardware glitch."
            ),
        )
        validation_row.set_subtitle_lines(3)
        self.validation_scale = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL,
            adjustment=Gtk.Adjustment(
                value=config.get("fan_validation_interval", 60), lower=15, upper=300, step_increment=15
            ),
            hexpand=True, valign=Gtk.Align.CENTER, digits=0, draw_value=True,
        )
        self.validation_scale.set_size_request(220, -1)
        self.validation_scale.connect("value-changed", self._on_validation_interval_changed)
        validation_row.add_suffix(self.validation_scale)
        units_group.add(validation_row)
        self.append(units_box)

        about_box, about_group = _group(_("About"))
        about_row = Adw.ActionRow(
            subtitle=_(
                "This interface controls liquidctl, the open-source cross-platform tool for "
                "liquid coolers, fans and RGB lighting."
            )
        )
        about_row.set_subtitle_lines(3)
        about_group.add(about_row)
        self.append(about_box)

    def on_device_changed(self) -> None:
        pass

    def update_devices(self, devices) -> None:
        default_description = self.window.app.config.get("default_device")
        self._device_options = [None] + [d.description for d in devices]
        labels = [_("Auto (first detected)")] + [d.description for d in devices]

        self.default_device_dropdown.handler_block_by_func(self._on_default_device_changed)
        model = Gtk.StringList.new(labels)
        self.default_device_dropdown.set_model(model)
        selected_index = (
            self._device_options.index(default_description) if default_description in self._device_options else 0
        )
        self.default_device_dropdown.set_selected(selected_index)
        self.default_device_dropdown.handler_unblock_by_func(self._on_default_device_changed)

    def _on_default_device_changed(self, dropdown: Gtk.DropDown, _pspec) -> None:
        index = dropdown.get_selected()
        if 0 <= index < len(self._device_options):
            self.window.app.config.set("default_device", self._device_options[index])

    def update_all_devices(self, infos) -> None:
        for row in self._device_toggle_rows.values():
            self.device_enable_group.remove(row)
        self._device_toggle_rows.clear()

        disabled = set(self.window.app.config.get("disabled_devices", []))
        for info in infos:
            row = Adw.SwitchRow(title=info.description, active=info.description not in disabled)
            row.connect("notify::active", self._on_device_enabled_toggled, info.description)
            self.device_enable_group.add(row)
            self._device_toggle_rows[info.description] = row

    def _on_device_enabled_toggled(self, row: "Adw.SwitchRow", _pspec, description: str) -> None:
        disabled = set(self.window.app.config.get("disabled_devices", []))
        if row.get_active():
            disabled.discard(description)
        else:
            disabled.add(description)
        self.window.app.config.set("disabled_devices", sorted(disabled))
        self.window.app.controller.disabled_devices = disabled
        self.window.refresh_devices()

    def _on_language_changed(self, dropdown: Gtk.DropDown, _pspec) -> None:
        language_values = ["auto", "pt_BR", "en_US"]
        self.window.app.config.set("language", language_values[dropdown.get_selected()])
        self.window.show_toast(_("Restart the app for the new language to take effect."))

    def _on_poll_changed(self, scale: Gtk.Scale) -> None:
        seconds = int(scale.get_value())
        self.window.app.config.set("poll_interval", seconds)
        self.window.app.curve_engine.set_poll_interval(seconds)

    def _on_validation_interval_changed(self, scale: Gtk.Scale) -> None:
        seconds = int(scale.get_value())
        self.window.app.config.set("fan_validation_interval", seconds)
        self.window.app.curve_engine.set_validation_interval(seconds)

    def _on_autostart_toggled(self, row: "Adw.SwitchRow", _pspec) -> None:
        enabled = row.get_active()
        self.window.app.config.set("autostart", enabled)
        autostart.set_enabled(enabled)
