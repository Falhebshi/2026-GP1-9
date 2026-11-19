from xml.etree import ElementTree as ET

import pytest

from jaadah.calibration.vehicle_type import (
    VehicleSettingsError,
    parse_vehicle_settings,
    route_file_with_settings,
)

ROUTES = """<?xml version='1.0' encoding='utf-8'?>
<routes>
    <vType id="car" vClass="passenger" accel="2.6" decel="4.5" sigma="0.5" length="5.0" minGap="2.5" speedDev="0.1" />
    <route id="MOV_X" edges="a b" />
    <vehicle id="v1" type="car" route="MOV_X" depart="10.00" />
</routes>
"""


def test_settings_are_parsed():
    assert parse_vehicle_settings(["tau=1.2", " sigma = 0.4"]) == {"tau": 1.2, "sigma": 0.4}
    assert parse_vehicle_settings([]) == {}


@pytest.mark.parametrize(
    ("items", "message"),
    [
        (["length=6"], "cannot be tuned"),
        (["tau"], "name=value"),
        (["tau=fast"], "must be a number"),
        (["tau=-1"], "0 or more"),
        (["tau=nan"], "finite"),
        (["sigma=1.5"], "between 0 and 1"),
        (["tau=1", "tau=2"], "twice"),
    ],
)
def test_invalid_settings_are_refused(items, message):
    with pytest.raises(VehicleSettingsError, match=message):
        parse_vehicle_settings(items)


def test_copy_changes_only_the_vehicle_type(tmp_path):
    source = tmp_path / "demand_routes.rou.xml"
    source.write_text(ROUTES, encoding="utf-8")
    original = source.read_bytes()

    copy = route_file_with_settings(source, tmp_path / "run" / "routes.rou.xml", {"tau": 1.2, "minGap": 2.0})

    assert source.read_bytes() == original
    root = ET.parse(copy).getroot()
    vehicle_type = root.find("vType")
    assert vehicle_type.get("tau") == "1.2"
    assert vehicle_type.get("minGap") == "2"
    assert vehicle_type.get("length") == "5.0"
    assert [item.get("id") for item in root.findall("vehicle")] == ["v1"]


def test_route_file_must_have_one_vehicle_type(tmp_path):
    source = tmp_path / "routes.rou.xml"
    source.write_text("<routes><route id='r' edges='a'/></routes>", encoding="utf-8")
    with pytest.raises(VehicleSettingsError, match="0 vehicle types"):
        route_file_with_settings(source, tmp_path / "copy.rou.xml", {"tau": 1.0})
