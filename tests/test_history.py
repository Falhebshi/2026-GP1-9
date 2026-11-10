"""The measurement store of the historical analysis: saving and loading one day."""

import gzip
import json
from datetime import date, datetime, timedelta

import pytest

from backend.analytics.history import (
    FORMAT_VERSION,
    HistoryError,
    day_file,
    load_day,
    save_day,
    stored_days,
    whole_day_of,
)
from backend.analytics.service import DEFAULT_MAPPING_PATH, RunMeasurements, calculate_kpis
from jaadah.kpi_inputs.cycle_queues import CycleQueues
from jaadah.kpi_inputs.vehicle_passages import VehiclePassages
from jaadah.mapping.loader import load_network_mappings
from jaadah.models.outputs import (
    ApproachCycleQueueRecord,
    CycleQueueRecord,
    IncompletePassage,
    UninsertedVehicle,
    VehicleDelayRecord,
)
from jaadah.models.scenario import SimulationRun
from jaadah.models.traffic import SimulationDemand
from jaadah.sumo_demand.planner import RunWindow


DAY = date(2026, 10, 22)
RUN_ID = "RUN_HISTORY_20261022_S42"


def at(clock: str, day: date = DAY) -> datetime:
    """A Riyadh time on the test day, e.g. at('08:00:10')."""

    return datetime.fromisoformat(f"{day.isoformat()}T{clock}+03:00")


def whole_day_window(day: date = DAY) -> RunWindow:
    start = at("00:00:00", day)
    return RunWindow(
        epoch=start - timedelta(minutes=15),
        analysis_start=start,
        analysis_end=start + timedelta(days=1),
        run_end=start + timedelta(days=1, minutes=15),
    )


def measurements(window: RunWindow | None = None) -> RunMeasurements:
    """One record of every kind, for North left at 08:00 (hand-entered)."""

    run = SimulationRun(
        run_id=RUN_ID,
        scenario_id="SCN_HISTORY_20261022",
        random_seed=42,
        network_version="jaadah_network_v2",
        sumo_version="1.27.1",
        step_length_s=0.4,
        mapping_version=load_network_mappings(DEFAULT_MAPPING_PATH).mapping_version,
        started_at=at("00:00:00") - timedelta(days=1),
        demand_sha256="a" * 64,
        route_file_sha256="b" * 64,
        status="completed",
    )
    passage = VehicleDelayRecord(
        run_id=RUN_ID, vehicle_id="MOV_N_E__20261022T0800__001", movement_id="MOV_N_E",
        zone_entry_time=at("08:00:10"), stop_line_time=at("08:01:00"), zone_exit_time=at("08:01:20"),
        zone_distance_m=565.0, free_flow_travel_time_s=40.0, halted_time_s=25.0,
    )
    incomplete = IncompletePassage(
        run_id=RUN_ID, vehicle_id="MOV_N_E__20261022T2359__001", movement_id="MOV_N_E",
        zone_entry_time=at("23:59:00"), last_seen_time=at("00:15:00", DAY + timedelta(days=1)),
    )
    uninserted = UninsertedVehicle(
        run_id=RUN_ID, vehicle_id="MOV_N_E__20261022T0615__040", movement_id="MOV_N_E",
        planned_stop_line_time=at("06:20:00"),
    )
    lane_queue = CycleQueueRecord(
        run_id=RUN_ID, lane_id="LANE_N_1", cycle_start=at("08:00:00"), cycle_end=at("08:02:00"),
        max_queue_length_m=22.5, max_queue_vehicles=3,
    )
    approach_queue = ApproachCycleQueueRecord(
        run_id=RUN_ID, approach_id="APP_N", cycle_start=at("08:00:00"), cycle_end=at("08:02:00"),
        max_queue_length_m=500.0, max_queue_vehicles=67, reaches_zone_end=True,
    )
    demand = SimulationDemand(
        demand_id="DEM_MOV_N_E_20261022T0800", movement_id="MOV_N_E",
        interval_start=at("08:00:00"), interval_end=at("08:15:00"),
        vehicle_count=128, source="synthetic", source_observation_ids=["OBS_4", "OBS_5", "OBS_6"],
    )

    return RunMeasurements(
        run=run,
        window=window or whole_day_window(),
        passages=VehiclePassages(records=[passage], incomplete=[incomplete], uninserted=[uninserted]),
        queues=CycleQueues(lanes=[lane_queue], approaches=[approach_queue]),
        demands=[demand],
    )


# ============================================================
# SAVING AND LOADING
# ============================================================

def test_a_saved_day_loads_back_exactly(tmp_path):
    original = measurements()

    path = save_day(original, tmp_path)

    assert path == tmp_path / "2026-10-22.json.gz"
    assert load_day(DAY, tmp_path) == original


def test_a_reloaded_day_gives_the_same_kpis(tmp_path):
    """
    The point of the store: KPIs from the stored day equal the KPIs from
    the measurements it was saved from, for all 96 intervals.
    """

    original = measurements()
    save_day(original, tmp_path)

    assert calculate_kpis(load_day(DAY, tmp_path)) == calculate_kpis(original)


def test_the_file_is_compressed_json_with_its_format_version(tmp_path):
    path = save_day(measurements(), tmp_path)

    with gzip.open(path, "rt", encoding="utf-8") as file:
        payload = json.load(file)

    assert payload["format_version"] == FORMAT_VERSION
    assert payload["run"]["run_id"] == RUN_ID
    assert len(payload["vehicle_records"]) == 1
    # Computed demand fields are left out, otherwise reloading fails
    assert "is_allocated" not in payload["demands"][0]


def test_no_partial_file_is_left_behind(tmp_path):
    save_day(measurements(), tmp_path)

    assert [p.name for p in tmp_path.iterdir()] == ["2026-10-22.json.gz"]


def test_a_stored_day_is_not_overwritten(tmp_path):
    save_day(measurements(), tmp_path)

    with pytest.raises(FileExistsError, match="2026-10-22 is already stored"):
        save_day(measurements(), tmp_path)


def test_stored_days_are_listed_oldest_first_and_other_files_ignored(tmp_path):
    save_day(measurements(whole_day_window(date(2026, 10, 23))), tmp_path)
    save_day(measurements(whole_day_window(date(2026, 10, 21))), tmp_path)
    (tmp_path / "notes.txt").write_text("not a day", encoding="utf-8")
    (tmp_path / "2026-10-24.json.gz.partial").write_bytes(b"")

    assert stored_days(tmp_path) == [date(2026, 10, 21), date(2026, 10, 23)]
    assert stored_days(tmp_path / "missing") == []


# ============================================================
# REFUSED
# ============================================================

def test_a_run_that_is_not_one_whole_day_is_refused(tmp_path):
    one_hour = RunWindow(
        epoch=at("07:45:00"), analysis_start=at("08:00:00"),
        analysis_end=at("09:00:00"), run_end=at("09:15:00"),
    )

    with pytest.raises(HistoryError, match="is not one whole day"):
        save_day(measurements(one_hour), tmp_path)


def test_a_day_not_in_riyadh_time_is_refused():
    utc_midnight = datetime(2026, 10, 22, tzinfo=datetime.fromisoformat("2026-10-22T00:00+00:00").tzinfo)
    window = RunWindow(
        epoch=utc_midnight - timedelta(minutes=15), analysis_start=utc_midnight,
        analysis_end=utc_midnight + timedelta(days=1),
        run_end=utc_midnight + timedelta(days=1, minutes=15),
    )

    with pytest.raises(HistoryError, match="not in Riyadh time"):
        whole_day_of(window)


def test_a_missing_day_is_reported(tmp_path):
    with pytest.raises(HistoryError, match="2026-10-22 is not stored"):
        load_day(DAY, tmp_path)


def test_a_file_of_another_format_version_is_refused(tmp_path):
    path = save_day(measurements(), tmp_path)
    with gzip.open(path, "rt", encoding="utf-8") as file:
        payload = json.load(file)
    payload["format_version"] = FORMAT_VERSION + 1
    with gzip.open(path, "wt", encoding="utf-8") as file:
        json.dump(payload, file)

    with pytest.raises(HistoryError, match="has format version 2"):
        load_day(DAY, tmp_path)


def test_a_file_holding_another_day_is_refused(tmp_path):
    save_day(measurements(), tmp_path)
    day_file(DAY, tmp_path).rename(day_file(date(2026, 10, 23), tmp_path))

    with pytest.raises(HistoryError, match="holds 2026-10-22, not 2026-10-23"):
        load_day(date(2026, 10, 23), tmp_path)
