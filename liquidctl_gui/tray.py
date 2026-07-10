"""Bridges the GTK4 app to the GTK3 tray-helper subprocess (see _tray_helper.py)."""

from __future__ import annotations

import subprocess
import sys
import threading

from gi.repository import GLib


class AppTray:
    def __init__(self, app) -> None:
        self.app = app
        self._process = subprocess.Popen(
            [sys.executable, "-m", "liquidctl_gui._tray_helper"],
            stdout=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

    def _read_loop(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            command = line.strip()
            if command == "show":
                GLib.idle_add(self._on_show)
            elif command == "quit":
                GLib.idle_add(self._on_quit)

    def _on_show(self) -> bool:
        if self.app.window is not None:
            self.app.window.present()
        return GLib.SOURCE_REMOVE

    def _on_quit(self) -> bool:
        self.app.quit_for_real()
        return GLib.SOURCE_REMOVE

    def shutdown(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
