"""Standalone GTK3 process for the tray icon.

AyatanaAppIndicator3's set_menu() only accepts a Gtk3 GtkMenu, and PyGObject can
load only one major version of the "Gtk" namespace per process - so the tray
indicator + its menu run here, in a separate process from the GTK4 main window,
talking back over stdout with one command per line ("show" / "quit").
"""

from __future__ import annotations

import gettext
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")

from gi.repository import AyatanaAppIndicator3, Gtk  # noqa: E402

from .appinfo import APP_ID, APP_NAME  # noqa: E402
from .i18n import DOMAIN, _LOCALE_DIR, _detect_language  # noqa: E402

ICON_NAME = APP_ID
FALLBACK_ICON_NAME = "utilities-system-monitor-symbolic"


def _send(command: str) -> None:
    sys.stdout.write(command + "\n")
    sys.stdout.flush()


def main() -> None:
    translation = gettext.translation(
        DOMAIN, localedir=_LOCALE_DIR, languages=[_detect_language()], fallback=True
    )
    _ = translation.gettext

    icon_theme = Gtk.IconTheme.get_default()
    icon_name = ICON_NAME if icon_theme.has_icon(ICON_NAME) else FALLBACK_ICON_NAME

    indicator = AyatanaAppIndicator3.Indicator.new(
        APP_ID, icon_name, AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS
    )
    indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
    indicator.set_title(APP_NAME)

    menu = Gtk.Menu()

    show_item = Gtk.MenuItem(label=_("Show window"))
    show_item.connect("activate", lambda *_a: _send("show"))
    menu.append(show_item)

    menu.append(Gtk.SeparatorMenuItem())

    quit_item = Gtk.MenuItem(label=_("Quit"))
    quit_item.connect("activate", lambda *_a: (_send("quit"), Gtk.main_quit()))
    menu.append(quit_item)

    menu.show_all()
    indicator.set_menu(menu)

    Gtk.main()


if __name__ == "__main__":
    main()
