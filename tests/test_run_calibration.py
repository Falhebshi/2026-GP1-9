from datetime import date, datetime, timedelta, timezone

import pytest

from simulation.scripts.run_calibration import default_label, mean_occupancy, parse_args, parse_days

RIYADH = timezone(timedelta(hours=3))
END = datetime(2026, 9, 1, 8, 15, tzinfo=RIYADH)


def test_parse_days_range_and_single_day():
    assert parse_days("2026-08-30..2026-09-01") == [date(2026, 8, 30), date(2026, 8, 31), date(2026, 9, 1)]
    assert parse_days("2026-09-01") == [date(2026, 9, 1)]


def test_settings_and_defaults_from_the_command_line():
    args = parse_args(["--days", "2026-09-01", "--set", "tau=1.2", "--seeds", "42", "43"])
    assert args.settings == {"tau": 1.2}
    assert args.seeds == [42, 43]
    assert args.jobs == 1


def test_bad_settings_stop_before_any_run():
    with pytest.raises(SystemExit):
        parse_args(["--days", "2026-09-01", "--set", "length=6"])


def test_mean_occupancy_needs_all_four_intervals():
    values = {("D1", END - step * timedelta(minutes=15)): 10.0 + step for step in range(4)}
    assert mean_occupancy(values, "D1", END) == pytest.approx(11.5)
    del values[("D1", END)]
    assert mean_occupancy(values, "D1", END) is None


def test_default_label_names_the_settings():
    assert default_label({}).endswith("_defaults")
    assert default_label({"tau": 1.2, "sigma": 0.4}).endswith("_sigma0.4_tau1.2")


# ============================================================
# CAPACITY AND REPORTING
# ============================================================

import json
from pathlib import Path

from jaadah.calibration.geh import HourlyComparison
from simulation.scripts.run_calibration import (
    GroupCapacity,
    describe_share,
    hour_capacities,
    hour_movement_demand,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NETWORK = PROJECT_ROOT / "data/processed/road_network/jaadah_study_area.net.xml"
MAPPING = PROJECT_ROOT / "data/processed/road_network/network_mappings.json"


def test_within_capacity_needs_both_values():
    assert GroupCapacity("G", 300, 340.0).within_capacity is True
    assert GroupCapacity("G", 340, 340.0).within_capacity is True
    assert GroupCapacity("G", 650, 340.0).within_capacity is False
    assert GroupCapacity("G", None, 340.0).within_capacity is None
    assert GroupCapacity("G", 300, None).within_capacity is None


def test_describe_share_marks_small_sets_indicative():
    small = [HourlyComparison("D1", END, 600, 610)] * 10
    assert describe_share(small) == "100.0% of 10 (indicative: fewer than 100)"
    assert describe_share(small * 10) == "100.0% of 100"
    assert describe_share([]) == "none"


def test_hour_movement_demand_sums_only_the_test_hour(tmp_path):
    folder = tmp_path / "20260901T0715_S42"
    folder.mkdir()
    def record(movement, start, end, count):
        return {
            "demand_id": f"DEM_X_{movement}_{start}", "interval_start": start, "interval_end": end,
            "movement_id": movement, "vehicle_count": count, "source": "rcrc",
            "source_observation_ids": ["OBS_RCRC_9999_1_X"], "allocated_observation_ids": [], "imputed_detectors": [],
        }
    records = [
        record("MOV_A", "2026-09-01T07:00:00+03:00", "2026-09-01T07:15:00+03:00", 99),   # warm-up
        record("MOV_A", "2026-09-01T07:15:00+03:00", "2026-09-01T07:30:00+03:00", 10),
        record("MOV_A", "2026-09-01T08:00:00+03:00", "2026-09-01T08:15:00+03:00", 20),
        record("MOV_A", "2026-09-01T08:15:00+03:00", "2026-09-01T08:30:00+03:00", 99),   # clearance
        record("MOV_B", "2026-09-01T07:30:00+03:00", "2026-09-01T07:45:00+03:00", 5),
    ]
    (folder / "20260901T0715_S42_demand.json").write_text(json.dumps(records), encoding="utf-8")
    start = datetime(2026, 9, 1, 7, 15, tzinfo=RIYADH)
    assert hour_movement_demand(folder, start, start + timedelta(hours=1)) == {"MOV_A": 30, "MOV_B": 5}


def test_hour_capacities_uses_the_kpi_engine_lane_groups():
    from backend.analytics.kpi.lane_groups import derive_lane_groups
    from jaadah.calibration.detectors import calibration_detectors
    from jaadah.kpi_inputs.network_inputs import build_network_inputs
    from jaadah.kpi_inputs.signal_program import build_signal_program
    from jaadah.mapping.loader import load_network_mappings

    mapping = load_network_mappings(MAPPING, network_path=NETWORK)
    network = build_network_inputs(mapping)
    program = build_signal_program(mapping, NETWORK, scenario_id="SCN_T", signal_program_id="SP_T")
    groups = derive_lane_groups(network.lanes, list(network.movement_attributes.values()))
    detectors = calibration_detectors(mapping, source="rcrc", site_id="1444")
    detector_of_lane = {d.lane_id: d.detector_id for d in detectors}

    # Invented demand: 300 veh/h for every analysed movement; every detector counted 150.
    demand = {m: 300 for m in network.movement_attributes}
    observed = {d.detector_id: 150 for d in detectors}
    capacities = hour_capacities(
        groups, {lane.lane_id: lane for lane in network.lanes},
        {m: network.movements[m] for m in network.movement_attributes},
        network.movement_attributes, program, demand, observed, detector_of_lane,
    )

    assert set(capacities) == set(observed)
    for detector in detectors:
        result = capacities[detector.detector_id]
        group = next(g for g in groups if g.lane_group_id == result.lane_group_id)
        assert detector.lane_id in group.lane_ids
        assert result.observed_veh_h == 150 * len(group.lane_ids)
        assert result.capacity_veh_h is not None and result.capacity_veh_h > 0

    # A lane group with a missing count has no observed volume.
    observed.pop(detectors[0].detector_id)
    capacities = hour_capacities(
        groups, {lane.lane_id: lane for lane in network.lanes},
        {m: network.movements[m] for m in network.movement_attributes},
        network.movement_attributes, program, demand, observed, detector_of_lane,
    )
    assert capacities[detectors[0].detector_id].within_capacity is None
