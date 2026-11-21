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


# ============================================================
# READING THE OBSERVATIONS ONCE
# ============================================================

from types import SimpleNamespace

import simulation.scripts.run_calibration as run_calibration


def fake_observation(end):
    return SimpleNamespace(interval_end=end, detector_id="D1", vehicle_count=1)


def test_observation_source_slices_like_a_separate_request(monkeypatch):
    ends = [END + step * timedelta(minutes=15) for step in range(8)]
    calls = []

    def fake_ingest(client, start, end):
        calls.append((start, end))
        return SimpleNamespace(observations=[fake_observation(e) for e in ends if start < e <= end], errors=[])

    monkeypatch.setattr(run_calibration, "ingest_rcrc_observations", fake_ingest)
    source = run_calibration.ObservationSource(None, ends[0] - timedelta(minutes=15), ends[-1])

    items, rejected = source.between(ends[1], ends[4])      # (ends[1], ends[4]]
    assert [item.interval_end for item in items] == ends[2:5]
    assert rejected == 0
    assert len(calls) == 1                                   # read once, then sliced


def test_observation_source_falls_back_to_requests_when_rows_are_rejected(monkeypatch):
    calls = []

    def fake_ingest(client, start, end):
        calls.append((start, end))
        return SimpleNamespace(observations=[], errors=["bad row"])

    monkeypatch.setattr(run_calibration, "ingest_rcrc_observations", fake_ingest)
    source = run_calibration.ObservationSource(None, END, END + timedelta(hours=2))

    items, rejected = source.between(END, END + timedelta(hours=1))
    assert (items, rejected) == ([], 1)
    assert len(calls) == 2                                   # the span, then the hour on its own


# ============================================================
# SHARED-LANE SENSITIVITY CHECK
# ============================================================

HASH = "0123456789abcdef" * 4
OFFICIAL = "2.6_net-0123456789ab"


def test_no_shift_means_no_adjustment_and_the_official_folder(tmp_path):
    assert run_calibration.share_adjustments(0.0) is None
    assert run_calibration.demand_folder(tmp_path, "2.6", HASH, 0.0) == tmp_path / OFFICIAL


def test_shift_adjusts_both_shared_lane_left_movements(tmp_path):
    assert run_calibration.share_adjustments(-0.2) == {"MOV_W_N": -0.2, "MOV_E_S": -0.2}
    assert run_calibration.demand_folder(tmp_path, "2.6", HASH, -0.2) == tmp_path / OFFICIAL / "left_share_shift_-0.2"
    assert run_calibration.demand_folder(tmp_path, "2.6", HASH, 0.2) == tmp_path / OFFICIAL / "left_share_shift_+0.2"


# ============================================================
# STORED DEMAND AND LEFT-OUT DAYS
# ============================================================

def test_stored_demand_depends_on_the_network_file(tmp_path):
    network = tmp_path / "a.net.xml"
    network.write_text("<net/>", encoding="utf-8")
    first = run_calibration.file_sha256(network)
    network.write_text("<net version='2'/>", encoding="utf-8")
    second = run_calibration.file_sha256(network)
    assert first != second
    assert (run_calibration.demand_folder(tmp_path, "2.6", first, 0.0)
            != run_calibration.demand_folder(tmp_path, "2.6", second, 0.0))


def test_national_day_week_is_left_out():
    assert run_calibration.excluded_day_reason(date(2026, 9, 19)) is None
    assert run_calibration.excluded_day_reason(date(2026, 9, 20)) == "National Day week"
    assert run_calibration.excluded_day_reason(date(2026, 9, 26)) == "National Day week"
    assert run_calibration.excluded_day_reason(date(2026, 9, 27)) is None


def observation(detector_id, end, count=10):
    return SimpleNamespace(detector_id=detector_id, interval_end=end, vehicle_count=count)


def test_missing_share_counts_test_hour_intervals_without_a_count():
    start = datetime(2026, 9, 1, 7, 15, tzinfo=RIYADH)
    windows = [(start, start + timedelta(hours=1))]
    ends = [start + step * timedelta(minutes=15) for step in range(1, 5)]
    complete = [observation(d, end) for d in ("D1", "D2") for end in ends]
    assert run_calibration.missing_share(complete, windows, ["D1", "D2"]) == 0.0

    one_missing = complete[1:]                       # D1's first interval
    assert run_calibration.missing_share(one_missing, windows, ["D1", "D2"]) == 1 / 8

    zero_count = [observation("D1", ends[0], count=0)] + complete[1:]
    assert run_calibration.missing_share(zero_count, windows, ["D1", "D2"]) == 0.0   # a reported 0 is observed

    outside = [observation(d, end + timedelta(hours=2)) for d in ("D1", "D2") for end in ends]
    assert run_calibration.missing_share(outside, windows, ["D1", "D2"]) == 1.0


def test_left_movements_are_the_shared_lanes_movements():
    from jaadah.calibration.parameters import SHARED_LANE_LEFT_MOVEMENTS
    from jaadah.mapping.loader import load_network_mappings

    mapping = load_network_mappings(MAPPING, network_path=NETWORK)
    shared = [d for d in mapping.detector_mappings
              if d.source == "rcrc" and d.mapping_status == "requires_allocation"]
    for movement_id in SHARED_LANE_LEFT_MOVEMENTS:
        assert sum(movement_id in d.movement_ids for d in shared) == 1


def test_shift_on_the_command_line_and_in_the_label():
    assert parse_args(["--days", "2026-09-01", "--left-share-shift", "-0.2"]).left_share_shift == -0.2
    assert parse_args(["--days", "2026-09-01"]).left_share_shift == 0.0
    with pytest.raises(SystemExit):
        parse_args(["--days", "2026-09-01", "--left-share-shift", "1.5"])
    assert default_label({}, 0.2).endswith("_defaults_left_share+0.2")
    assert default_label({}).endswith("_defaults")
