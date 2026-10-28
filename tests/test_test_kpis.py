import json
import sys

import pytest

from backend.outputs.intersections import (
    REPO_ROOT,
)
from jaadah.mapping.loader import (
    load_network_mappings,
)
from jaadah.models.kpis import (
    KpiResult,
)


SCRIPTS_DIR = REPO_ROOT / "simulation" / "scene_3d"

sys.path.insert(0, str(SCRIPTS_DIR))

from build_test_kpis import (  # noqa: E402
    MAPPING_PATH,
    RUN_DIR,
    build_test_kpis,
)


# Computed fields of KpiResult: in the dashboard dump, not passed in
COMPUTED_FIELDS = {
    "replication_count",
    "value_computation",
    "is_shared_value",
}

INTERSECTION_KPIS = {
    "level_of_service",
    "control_delay",
    "queue_length",
    "queue_duration",
    "queue_storage_ratio",
    "throughput",
    "volume_to_capacity_ratio",
}

SIGNAL_KPIS = {
    "level_of_service",
    "volume_to_capacity_ratio",
    "capacity",
    "saturation_flow_rate",
}


def load_run() -> dict:
    """Load the test run the KPIs belong to."""

    with (RUN_DIR / "run.json").open(
        encoding="utf-8",
    ) as file:
        return json.load(file)


# Once the baseline run's real files replace the test run, the checks
# that read the test run from the folder no longer apply.
needs_test_run = pytest.mark.skipif(
    not load_run().get("is_test", False),
    reason="the frontend folder holds a real run, not the test run",
)


def study_kpis() -> dict:
    """Build the test KPI results of the test run."""

    return build_test_kpis(
        run=load_run(),
        config=load_network_mappings(
            file_path=MAPPING_PATH,
        ),
    )


def interval_starts(
    results: list[dict],
) -> set[str]:
    """Return the interval starts the results cover."""

    return {
        result["interval_start"]
        for result in results
    }


def test_every_result_is_a_valid_kpi_result() -> None:
    for result in study_kpis()["results"]:
        stored = {
            name: value
            for name, value in result.items()
            if name not in COMPUTED_FIELDS
        }

        KpiResult.model_validate(stored)


@needs_test_run
def test_results_cover_every_analysis_interval() -> None:
    results = study_kpis()["results"]

    assert interval_starts(results) == {
        "2026-10-20T08:00:00+03:00",
        "2026-10-20T08:15:00+03:00",
        "2026-10-20T08:30:00+03:00",
        "2026-10-20T08:45:00+03:00",
    }


def test_intersection_has_its_seven_kpis_in_every_interval() -> None:
    results = study_kpis()["results"]

    for start in interval_starts(results):
        kpis = {
            result["kpi"]
            for result in results
            if result["level"] == "intersection"
            and result["interval_start"] == start
        }

        assert kpis == INTERSECTION_KPIS


def test_every_approach_and_movement_has_results() -> None:
    config = load_network_mappings(
        file_path=MAPPING_PATH,
    )
    results = study_kpis()["results"]

    approaches = {
        result["approach_id"]
        for result in results
        if result["level"] == "approach"
    }
    movements = {
        result["movement_id"]
        for result in results
        if result["level"] == "movement"
    }

    assert approaches == {
        approach.approach_id
        for approach in config.approach_mappings
    }
    assert movements == {
        attributes.movement_id
        for attributes in config.movement_attributes
    }


def test_signal_measures_do_not_apply_to_slips() -> None:
    results = study_kpis()["results"]
    slip_results = [
        result
        for result in results
        if result["movement_id"] in {
            "MOV_S_E_BYPASS",
            "MOV_W_S_SLIP",
            "MOV_N_W_SLIP",
        }
        and result["kpi"] in SIGNAL_KPIS
    ]

    assert slip_results
    for result in slip_results:
        assert result["status"] == "not_applicable"
        assert result["reason"]


def test_shared_lane_movements_show_the_lane_queue() -> None:
    results = study_kpis()["results"]
    shared = {
        (result["movement_id"], result["measured_on_lane_id"])
        for result in results
        if result["is_shared_value"]
    }

    assert shared == {
        ("MOV_E_S", "LANE_E_2"),
        ("MOV_E_W", "LANE_E_2"),
        ("MOV_W_N", "LANE_W_2"),
        ("MOV_W_E", "LANE_W_2"),
    }


@needs_test_run
def test_test_files_say_they_are_test_data() -> None:
    assert study_kpis()["is_test"] is True
    assert load_run()["is_test"] is True


@needs_test_run
def test_frontend_copy_is_up_to_date() -> None:
    with (RUN_DIR / "kpis.json").open(
        encoding="utf-8",
    ) as file:
        frontend_copy = json.load(file)

    assert frontend_copy == study_kpis()
