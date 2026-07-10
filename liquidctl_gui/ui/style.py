"""Small shared stylesheet for widgets libadwaita's stock CSS classes don't cover
(a Gtk.Label doesn't get a background/padding just from the 'pill' button class).
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, Gtk  # noqa: E402

_CSS = """
.status-badge {
  padding: 4px 12px;
  border-radius: 999px;
  font-weight: 600;
  font-size: 0.85em;
}
.status-badge.success {
  background-color: alpha(@success_color, 0.15);
  color: @success_color;
}
.status-badge.accent {
  background-color: alpha(@accent_color, 0.15);
  color: @accent_color;
}
.color-swatch.selected {
  box-shadow: 0 0 0 2px @window_bg_color, 0 0 0 4px @accent_color;
}
.color-picker-swatch {
  background-image: conic-gradient(red, yellow, lime, cyan, blue, magenta, red);
  border-radius: 999px;
  color: #ffffff;
  padding: 0;
  min-width: 0;
  min-height: 0;
}
.color-picker-swatch image {
  filter: drop-shadow(0 0 1px rgba(0, 0, 0, 0.8));
}
"""

_installed = False


def install() -> None:
    global _installed
    if _installed:
        return
    _installed = True
    provider = Gtk.CssProvider()
    provider.load_from_string(_CSS)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
