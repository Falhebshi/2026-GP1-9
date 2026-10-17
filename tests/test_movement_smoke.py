"""Unit tests for the TraCI movement smoke-test script; SUMO is not required."""

import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "simulation/scripts/tests"))
from run_movement_smoke import require_mapping, run_one, write_vehicle_route


def test_route_generation(tmp_path):
    route = tmp_path / "vehicle.rou.xml"
    write_vehicle_route({"movement_id": "MOV_E_W", "sumo_route_edge_ids": ["A", "B", "C"]}, route)
    vehicle = ET.parse(route).getroot().find("vehicle")
    assert vehicle.get("id") == "MOV_E_W"
    assert vehicle.find("route").get("edges") == "A B C"


def test_mapping_hash(tmp_path):
    net = tmp_path / "network.net.xml"
    net.write_bytes(b"<net />")
    data = {
        "network": {"sha256": hashlib.sha256(net.read_bytes()).hexdigest()},
        "movement_mappings": [
            {"movement_id": f"MOV_{i}", "sumo_route_edge_ids": ["A", "B"]}
            for i in range(18)
        ],
    }
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps(data), encoding="utf-8")
    assert len(require_mapping(mapping, net)) == 18
    net.write_bytes(b"<net changed='yes' />")
    with pytest.raises(ValueError, match="SHA-256"):
        require_mapping(mapping, net)


@pytest.mark.parametrize("mode,expected", [
    ("arrived", True),
    ("teleported", False),
    ("stalled", False),
])
def test_traci_run(monkeypatch, tmp_path, mode, expected):
    class FakeSimulation:
        steps = 0
        def getMinExpectedNumber(self):
            return 1 if self.steps < 1 else 0
        def getTime(self):
            return float(self.steps)
        def getDepartedIDList(self):
            return ["MOV_E_W"]
        def getArrivedIDList(self):
            return ["MOV_E_W"] if mode == "arrived" else []
        def getStartingTeleportIDList(self):
            return ["MOV_E_W"] if mode == "teleported" else []
        def getEndingTeleportIDList(self):
            return []

    simulation = FakeSimulation()
    calls = []
    def step():
        simulation.steps += 1
    fake = SimpleNamespace(
        start=lambda cmd: calls.append("start"),
        simulationStep=step,
        simulation=simulation,
        close=lambda: calls.append("close"),
    )
    monkeypatch.setitem(sys.modules, "traci", fake)
    net = tmp_path / "network.net.xml"
    net.write_text("<net/>")
    result = run_one("sumo", net, {"movement_id": "MOV_E_W", "sumo_route_edge_ids": ["A"]}, tmp_path/"outputs", 5)
    assert result["passed"] is expected
    assert calls == ["start", "close"]


def test_traci_closes_on_error(monkeypatch, tmp_path):
    calls = []
    def crash():
        raise RuntimeError("connection dropped")
    fake = SimpleNamespace(
        start=lambda cmd: calls.append("start"),
        simulation=SimpleNamespace(getMinExpectedNumber=lambda: 1),
        simulationStep=crash,
        close=lambda: calls.append("close"),
    )
    monkeypatch.setitem(sys.modules, "traci", fake)
    net = tmp_path / "network.net.xml"
    net.write_text("<net/>")
    result = run_one("sumo", net, {"movement_id": "MOV_E_W", "sumo_route_edge_ids": ["A"]}, tmp_path/"outputs", 5)
    assert not result["passed"]
    assert "connection dropped" in result["error"]
    assert calls == ["start", "close"]
