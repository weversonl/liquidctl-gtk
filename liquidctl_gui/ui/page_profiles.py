from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..i18n import install  # noqa: E402

_ = install()

BUILTIN_PROFILE_INFO = {
    "silent": (_("Silent"), _("Prioritizes quiet operation, slightly higher temperatures")),
    "balanced": (_("Balanced"), _("Good balance between noise and cooling")),
    "performance": (_("Performance"), _("Maximum cooling, more noise")),
}


class ProfilesPage(Gtk.Box):
    def __init__(self, window) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                          margin_top=24, margin_bottom=32, margin_start=28, margin_end=28)
        self.window = window

        self.custom_label = Gtk.Label(
            label=_("Custom configuration in use — none of the profiles below match it."),
            halign=Gtk.Align.START, wrap=True, css_classes=["dim-label", "caption"],
        )
        self.append(self.custom_label)

        self.list_box = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        self.append(self.list_box)

        add_button = Gtk.Button(
            label=_("New profile from current settings"),
            css_classes=["flat"], margin_top=8,
        )
        add_button.connect("clicked", self._on_add_profile)
        self.append(add_button)

        self._rebuild()

    def on_device_changed(self) -> None:
        pass

    def refresh(self) -> None:
        self._rebuild()

    def _rebuild(self) -> None:
        child = self.list_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.list_box.remove(child)
            child = nxt

        active_id = self.window.app.config.get("active_profile_id")
        self.custom_label.set_visible(active_id is None)
        for profile in self.window.app.config.get("profiles", []):
            builtin = BUILTIN_PROFILE_INFO.get(profile["id"])
            title, subtitle = builtin if builtin is not None else (profile["name"], profile.get("desc", ""))
            row = Adw.ActionRow(title=title, subtitle=subtitle)

            if profile["id"] == active_id:
                badge = Gtk.Label(label=_("Active"), valign=Gtk.Align.CENTER,
                                   css_classes=["status-badge", "accent"])
                row.add_suffix(badge)
            else:
                apply_button = Gtk.Button(label=_("Apply"), valign=Gtk.Align.CENTER, css_classes=["flat"])
                apply_button.connect("clicked", lambda _b, p=profile: self._apply_profile(p))
                row.add_suffix(apply_button)

            if builtin is None:
                delete_button = Gtk.Button(
                    icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                    css_classes=["flat"], tooltip_text=_("Delete profile"),
                )
                delete_button.connect("clicked", lambda _b, p=profile: self._confirm_delete_profile(p))
                row.add_suffix(delete_button)

            self.list_box.append(row)

    def _apply_profile(self, profile: dict) -> None:
        self.window.app.config.set("active_profile_id", profile["id"])
        preset_marker = profile["id"] if profile["id"] in BUILTIN_PROFILE_INFO else "custom"
        for channel, curve_key in (("pump", "pump_curve"), ("fan", "fan_curve")):
            curve = profile.get(curve_key)
            if curve and self.window.active_device_key:
                self.window.curves_page.set_curve_for_channel(channel, [tuple(p) for p in curve], preset_marker)
        self._rebuild()

    def _confirm_delete_profile(self, profile: dict) -> None:
        title, _subtitle = BUILTIN_PROFILE_INFO.get(profile["id"], (profile["name"], None))
        dialog = Adw.AlertDialog(
            heading=_("Delete profile?"),
            body=_("“{name}” will be permanently removed.").format(name=title),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("delete", _("Delete"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_response(_dlg, response: str) -> None:
            if response != "delete":
                return
            self.window.app.config.delete_profile(profile["id"])
            self._rebuild()

        dialog.connect("response", on_response)
        dialog.present(self.window)

    def _on_add_profile(self, _button: Gtk.Button) -> None:
        device_key = self.window.active_device_key
        pump_curve = self.window.curves_page._curves.get((device_key, "pump")) if device_key else None
        fan_curve = self.window.curves_page._curves.get((device_key, "fan")) if device_key else None

        dialog = Adw.AlertDialog(
            heading=_("New profile"),
            body=_("Give this profile a name. It will store the current pump/fan curves."),
        )
        entry = Gtk.Entry(placeholder_text=_("Profile name"))
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("create", _("Create"))
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)

        def on_response(_dlg, response: str) -> None:
            if response != "create":
                return
            name = entry.get_text().strip() or _("Untitled profile")
            profile_id = name.lower().replace(" ", "-")
            self.window.app.config.upsert_profile({
                "id": profile_id, "name": name, "desc": _("Custom profile"),
                "pump_curve": pump_curve or [],
                "fan_curve": fan_curve or [],
            })
            self._rebuild()

        dialog.connect("response", on_response)
        dialog.present(self.window)
