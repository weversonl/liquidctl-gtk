# LiquidctlGTK

A native GTK4 / libadwaita desktop app for [liquidctl](https://github.com/liquidctl/liquidctl) —
monitor liquid temperature, pump and fan speeds, edit fan curves, and control RGB lighting from a
proper GNOME app instead of the command line.

> **Hardware compatibility notice.** This app was built and tested against one specific device: a
> **Corsair iCUE H150i Elite RGB White (Hydro Platinum)** AIO, alongside an ASUS Aura LED
> Controller. liquidctl supports many more devices, and the driver-family detection in this app
> is a best-effort guess for those — it has **not** been verified against them. If you own a
> different pump/fan hub, it's worth trying, but expect rough edges (a curve tab that doesn't
> apply, a sensor that doesn't show up) until someone tests and fixes it for that specific device.

## Features

- **Dashboard** — live liquid temperature, pump and fan RPM/duty for the selected device.
- **Curves** — a draggable temperature × duty graph per channel (add/remove points, presets, or
  freehand). Falls back automatically to host-side polling for devices whose driver doesn't
  support hardware speed profiles.
- **Pump mode** — for devices without continuous pump duty control (like the Hydro Platinum
  family), a simple quiet/balanced/extreme switch instead of a curve that wouldn't apply.
- **Lighting** — off/static/breathing/pulse/spectrum, a quick color palette plus a native
  GNOME color picker, brightness and animation speed. Animated modes are driven host-side when
  the hardware itself has no on-device animation support.
- **Profiles** — save/apply/delete named bundles of fan+pump curves.
- **Tray** — closing the window keeps the app running in the background (curves need a live
  process to keep re-applying, since liquidctl itself has no daemon) until you quit from the
  tray menu.
- **Locale-aware** — Portuguese (`pt_BR`) if that's your system locale, English everywhere else.
- Remembers window size, sidebar width, theme and default device between launches.

## Stack

- **Python 3.10+**
- **GTK4** + **libadwaita** via **PyGObject**
- **[liquidctl](https://pypi.org/project/liquidctl/)** — used as a library, not shelled out to
- **AyatanaAppIndicator3** for the tray icon (runs in a small GTK3 helper subprocess, since GTK3
  and GTK4 can't share a process and the tray menu API requires a GTK3 `Gtk.Menu`)
- **gettext** for translations
- No external UI/charting libraries — the curve editor is a `Gtk.DrawingArea` drawn with Cairo

## Install

```bash
git clone <this-repo>
cd liquidctl-gui
./install.sh
```

This creates an isolated virtualenv under `~/.local/share/liquidctl-gui`, installs a
`liquidctl-gui` launcher to `~/.local/bin`, and registers the app + icon with GNOME (so it shows
up in the app grid). Remove everything later with `./install.sh --uninstall` (your saved
curves/settings in `~/.config/liquidctl-gui` are left alone).

**Dependencies** the installer expects to already be on your system (installed via your distro's
package manager): GTK4, libadwaita, PyGObject, `liquidctl`'s udev rules (installing the
`liquidctl` package on most distros, e.g. Arch, sets these up for you — otherwise see
[liquidctl's udev docs](https://github.com/liquidctl/liquidctl/blob/main/docs/udev/)), the
`AyatanaAppIndicator3` introspection bindings, and `gettext`.

## Development

```bash
python -m venv .venv --system-site-packages
source .venv/bin/activate
pip install -e .
python -m liquidctl_gui
```

See `docs/ARCHITECTURE.md` for the module map, threading model, and where each feature lives.

## License

GPL-3.0-or-later, matching liquidctl's own license.
