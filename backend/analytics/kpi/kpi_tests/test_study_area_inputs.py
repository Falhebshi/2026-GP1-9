"""
The engine on the study area's real network inputs and signal program,
as prepared by jaadah/kpi_inputs, with a uniform test demand.
"""

from pathlib import Path

import pytest

from backend.analytics.kpi.capacity import calculate_capacity
from backend.analytics.kpi.lane_groups import derive_lane_groups
from jaadah.kpi_inputs.network_inputs import build_network_inputs
from jaadah.kpi_inputs.signal_program import build_signal_program
from jaadah.mapping.loader import load_network_mappings
from jaadah.models.kpis import KpiStatus
from jaadah.models.network import MovementControl

PROJECT_ROOT = Path(__file__).resolve().parents[4]
NETWORK_DIR = PROJECT_ROOT / "data/processed/road_network"


@pytest.fixture(scope="module")
def study_area():
    config = load_network_mappings(NETWORK_DIR / "network_mappings.json")
    inputs = build_network_inputs(config)
    program = build_signal_program(
        config, NETWORK_DIR / "jaadah_study_area.net.xml",
        scenario_id="SCN_BASE", signal_program_id="SP_BASE",
    )
    groups = derive_lane_groups(inputs.lanes, list(inputs.movement_attributes.values()))
    return inputs, program, groups


def test_study_area_lane_groups(study_area):
    """The slips are uncontrolled and form no lane group."""
    _, _, groups = study_area

    assert {g.lane_group_id: g.lane_ids for g in groups} == {
        "APP_E_L": ("LANE_E_1",),
        "APP_E_LT": ("LANE_E_2",),
        "APP_E_T": ("LANE_E_3", "LANE_E_4"),
        "APP_N_L": ("LANE_N_1", "LANE_N_2", "LANE_N_3"),
        "APP_S_L": ("LANE_S_1", "LANE_S_2"),
        "APP_W_L": ("LANE_W_1",),
        "APP_W_LT": ("LANE_W_2",),
        "APP_W_T": ("LANE_W_3",),
    }


def test_capacity_runs_on_the_study_area_inputs(study_area):
    """Every lane group is calculated, with the greens of the network's plan."""
    inputs, program, groups = study_area
    demand = {
        movement_id: 400.0
        for movement_id, attributes in inputs.movement_attributes.items()
        if attributes.control == MovementControl.SIGNALIZED
    }

    results = calculate_capacity(
        groups, {lane.lane_id: lane for lane in inputs.lanes},
        inputs.movements, inputs.movement_attributes, program, demand,
    )

    assert all(r.status == KpiStatus.OK for r in results.lane_groups.values())
    assert {g: r.green_s for g, r in results.lane_groups.items()} == {
        "APP_E_L": 40, "APP_E_LT": 40, "APP_E_T": 40,
        "APP_S_L": 15, "APP_W_L": 30, "APP_W_LT": 30, "APP_W_T": 30, "APP_N_L": 15,
    }
    assert results.critical_status == KpiStatus.OK
