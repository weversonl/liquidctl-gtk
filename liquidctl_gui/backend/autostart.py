from __future__ import annotations

import os

from gi.repository import GLib

from ..appinfo import APP_ID, APP_NAME

_AUTOSTART_DIR = os.path.join(GLib.get_user_config_dir(), "autostart")
_AUTOSTART_FILE = os.path.join(_AUTOSTART_DIR, f"{APP_ID}.desktop")

# Autostart .desktop entries are launched by the session/display manager, which does not
# source the user's shell profile - ~/.local/bin may not be on PATH there even though it is
# in an interactive shell. Use the absolute launcher path so autostart works regardless.
_LAUNCHER = os.path.join(GLib.get_home_dir(), ".local", "bin", "liquidctl-gui")

_ENTRY = f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Exec={_LAUNCHER} --hidden
Icon={APP_ID}
Terminal=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
"""


def set_enabled(enabled: bool) -> None:
    if enabled:
        os.makedirs(_AUTOSTART_DIR, exist_ok=True)
        with open(_AUTOSTART_FILE, "w", encoding="utf-8") as fh:
            fh.write(_ENTRY)
    elif os.path.exists(_AUTOSTART_FILE):
        os.remove(_AUTOSTART_FILE)


def is_enabled() -> bool:
    return os.path.exists(_AUTOSTART_FILE)
