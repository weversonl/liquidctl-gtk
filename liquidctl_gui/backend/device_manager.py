from __future__ import annotations

from dataclasses import dataclass, field

import liquidctl


@dataclass
class DeviceInfo:
    key: str
    description: str
    driver_class_name: str
    has_pump: bool
    has_pump_control: bool
    pump_mode_only: bool
    has_fan: bool
    has_lighting: bool
    channel_names: list[str] = field(default_factory=list)


_PUMP_DRIVERS = {"HydroPlatinum", "Hydro", "Kraken2", "KrakenX3", "Modern690Lc", "Coolit"}
_FAN_DRIVERS = _PUMP_DRIVERS | {"CommanderPro", "SmartDevice", "SmartDeviceV2", "Corsair"}
_LIGHTING_DRIVERS = {
    "AuraLed",
    "HydroPlatinum",
    "SmartDeviceV2",
    "SmartDevice",
    "CommanderPro",
    "Kraken2",
    "KrakenX3",
}
# HydroPlatinum reports a liquid-temp/pump sensor but only accepts 3 fixed pump
# modes at initialize() time - set_fixed_speed()/set_speed_profile() reject a
# "pump" channel outright, confirmed against real hardware (ValueError: unknown
# channel, should be one of: 'fan', 'fan1', 'fan2', 'fan3').
PUMP_MODE_ONLY_DRIVERS = {"HydroPlatinum"}
PUMP_MODES = ("quiet", "balanced", "extreme")


def _classify(driver) -> tuple[bool, bool, bool, bool, bool]:
    name = type(driver).__name__
    has_pump = any(name.startswith(p) or name == p for p in _PUMP_DRIVERS)
    pump_mode_only = has_pump and name in PUMP_MODE_ONLY_DRIVERS
    has_pump_control = has_pump and not pump_mode_only
    has_fan = any(name.startswith(p) or name == p for p in _FAN_DRIVERS)
    has_lighting = any(name.startswith(p) or name == p for p in _LIGHTING_DRIVERS)
    return has_pump, has_pump_control, pump_mode_only, has_fan, has_lighting


def discover_devices() -> list[tuple[DeviceInfo, object]]:
    results = []
    for driver in liquidctl.find_liquidctl_devices():
        has_pump, has_pump_control, pump_mode_only, has_fan, has_lighting = _classify(driver)
        key = f"{type(driver).__module__}.{type(driver).__name__}:{getattr(driver, 'address', driver.description)}"
        info = DeviceInfo(
            key=key,
            description=driver.description,
            driver_class_name=type(driver).__name__,
            has_pump=has_pump,
            has_pump_control=has_pump_control,
            pump_mode_only=pump_mode_only,
            has_fan=has_fan,
            has_lighting=has_lighting,
        )
        results.append((info, driver))
    return results
