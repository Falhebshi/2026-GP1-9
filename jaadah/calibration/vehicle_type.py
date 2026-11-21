"""
Driver settings for calibration runs.

The demand writer puts one vehicle type ("car") in every route file,
and the demand checks require it unchanged. A calibration run therefore
never edits the generated route file: it writes a copy, next to the
run, with the tuned attributes set on that vehicle type. Everything
else in the copy (routes, vehicles, departure times) is unchanged.
"""

import math
from pathlib import Path
from xml.etree import ElementTree as ET

from .parameters import POSITIVE_VEHICLE_ATTRIBUTES, TUNABLE_VEHICLE_ATTRIBUTES


class VehicleSettingsError(ValueError):
    """A driver setting is unknown or out of range."""


def parse_vehicle_settings(items: list[str]) -> dict[str, float]:
    """
    Turn ["tau=1.2", "sigma=0.4"] into {"tau": 1.2, "sigma": 0.4}.

    Only attributes in TUNABLE_VEHICLE_ATTRIBUTES are accepted. Values
    must be finite and not negative; the attributes in
    POSITIVE_VEHICLE_ATTRIBUTES (tau, accel, decel, speedFactor) must be
    above 0, because SUMO cannot run with them at 0; sigma is at most 1.
    """

    settings = {}
    for item in items:
        name, separator, value = item.partition("=")
        name = name.strip()
        if not separator or not name:
            raise VehicleSettingsError(f"expected name=value, got {item!r}")
        if name not in TUNABLE_VEHICLE_ATTRIBUTES:
            raise VehicleSettingsError(
                f"{name} cannot be tuned; allowed: {', '.join(TUNABLE_VEHICLE_ATTRIBUTES)}"
            )
        if name in settings:
            raise VehicleSettingsError(f"{name} is given twice")
        try:
            number = float(value)
        except ValueError:
            raise VehicleSettingsError(f"{name} must be a number, got {value!r}") from None
        if not math.isfinite(number) or number < 0:
            raise VehicleSettingsError(f"{name} must be a finite number, 0 or more")
        if name in POSITIVE_VEHICLE_ATTRIBUTES and number == 0:
            raise VehicleSettingsError(f"{name} must be above 0")
        if name == "sigma" and number > 1:
            raise VehicleSettingsError("sigma must be between 0 and 1")
        settings[name] = number
    return settings


def route_file_with_settings(
    route_path: str | Path,
    output_path: str | Path,
    settings: dict[str, float],
) -> Path:
    """Copy the route file, setting the given attributes on its single vehicle type."""

    tree = ET.parse(route_path)
    vehicle_types = tree.getroot().findall("vType")
    if len(vehicle_types) != 1:
        raise VehicleSettingsError(
            f"route file has {len(vehicle_types)} vehicle types, expected 1"
        )
    for name, value in settings.items():
        vehicle_types[0].set(name, f"{value:g}")

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path
