"""
Build the test KPI results the frontend shows until the KPI engine
writes them for the baseline run.

Usage (from the repository root):
    python simulation/scene_3d/build_test_kpis.py

The values are made up: the sample values the pages used before, a
little higher or lower in each 15-minute interval so the page can be
seen to follow the time. They are not calculated from the test run.
Every result is a KpiResult, so the file has the same shape and follows
the same rules as the KPI engine's results. The file is marked
"is_test": true, so the page says that the values are test data. It is
written next to the test run's run.json and is replaced by the real file
once the baseline run's KPIs are calculated.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parents[1]

sys.path.insert(0, str(REPO_ROOT))

from backend.analytics.kpi.parameters import (  # noqa: E402
    level_of_service,
)
from jaadah.mapping.loader import (  # noqa: E402
    load_network_mappings,
)
from jaadah.models.kpis import (  # noqa: E402
    InputOrigin,
    KpiLevel,
    KpiMethod,
    KpiName,
    KpiResult,
    KpiStatus,
    KpiUnit,
    UNCONTROLLED_TAG_BY_METHOD,
)
from jaadah.models.mappings import (  # noqa: E402
    NetworkMappingConfig,
)
from jaadah.models.network import (  # noqa: E402
    MovementControl,
)


MAPPING_PATH = (
    REPO_ROOT
    / "data"
    / "processed"
    / "road_network"
    / "network_mappings.json"
)

RUN_DIR = (
    REPO_ROOT
    / "frontend"
    / "public"
    / "data"
    / "INT_001"
    / "baseline"
)

# The scenario of the test run (build_test_run.py)
SCENARIO_ID = "SCN_SCENE_3D_TEST"

# How each KPI is calculated and reported, as in the KPI engine
METHOD_OF_KPI = {
    KpiName.CONTROL_DELAY: KpiMethod.SIMULATION,
    KpiName.LEVEL_OF_SERVICE: KpiMethod.SIMULATION,
    KpiName.VOLUME_TO_CAPACITY_RATIO: KpiMethod.HCM,
    KpiName.CAPACITY: KpiMethod.HCM,
    KpiName.SATURATION_FLOW_RATE: KpiMethod.HCM,
    KpiName.QUEUE_LENGTH: KpiMethod.SIMULATION,
    KpiName.QUEUE_DURATION: KpiMethod.SIMULATION,
    KpiName.QUEUE_STORAGE_RATIO: KpiMethod.SIMULATION,
    KpiName.THROUGHPUT: KpiMethod.SIMULATION,
}

UNIT_OF_KPI = {
    KpiName.CONTROL_DELAY: KpiUnit.SECONDS_PER_VEHICLE,
    KpiName.LEVEL_OF_SERVICE: KpiUnit.GRADE,
    KpiName.VOLUME_TO_CAPACITY_RATIO: KpiUnit.RATIO,
    KpiName.CAPACITY: KpiUnit.VEHICLES_PER_HOUR,
    KpiName.SATURATION_FLOW_RATE: KpiUnit.VEHICLES_PER_HOUR,
    KpiName.QUEUE_LENGTH: KpiUnit.METRES,
    KpiName.QUEUE_DURATION: KpiUnit.SECONDS,
    KpiName.QUEUE_STORAGE_RATIO: KpiUnit.RATIO,
    KpiName.THROUGHPUT: KpiUnit.VEHICLES_PER_HOUR,
}

# Where the inputs come from. HCM results use the demand and assumed
# geometry and timing, without a run.
ORIGINS_OF_METHOD = {
    KpiMethod.SIMULATION: [InputOrigin.SIMULATED],
    KpiMethod.HCM: [InputOrigin.MODELLED_ASSUMPTION],
}

# The KPIs reported per element, as in docs/kpi_engine.md section 11.1:
# capacity is not reported for the intersection, and saturation flow
# only per lane group and movement.
KPIS_OF_LEVEL = {
    KpiLevel.INTERSECTION: [
        KpiName.CONTROL_DELAY,
        KpiName.LEVEL_OF_SERVICE,
        KpiName.VOLUME_TO_CAPACITY_RATIO,
        KpiName.QUEUE_LENGTH,
        KpiName.QUEUE_DURATION,
        KpiName.QUEUE_STORAGE_RATIO,
        KpiName.THROUGHPUT,
    ],
    KpiLevel.APPROACH: [
        KpiName.CONTROL_DELAY,
        KpiName.LEVEL_OF_SERVICE,
        KpiName.VOLUME_TO_CAPACITY_RATIO,
        KpiName.CAPACITY,
        KpiName.QUEUE_LENGTH,
        KpiName.QUEUE_DURATION,
        KpiName.QUEUE_STORAGE_RATIO,
        KpiName.THROUGHPUT,
    ],
    KpiLevel.MOVEMENT: [
        KpiName.CONTROL_DELAY,
        KpiName.LEVEL_OF_SERVICE,
        KpiName.VOLUME_TO_CAPACITY_RATIO,
        KpiName.CAPACITY,
        KpiName.SATURATION_FLOW_RATE,
        KpiName.QUEUE_LENGTH,
        KpiName.QUEUE_DURATION,
        KpiName.QUEUE_STORAGE_RATIO,
        KpiName.THROUGHPUT,
    ],
}

# The signal measures, which do not apply to an uncontrolled slip
SIGNAL_KPIS = {
    KpiName.LEVEL_OF_SERVICE,
    KpiName.VOLUME_TO_CAPACITY_RATIO,
    KpiName.CAPACITY,
    KpiName.SATURATION_FLOW_RATE,
}

SLIP_REASON = (
    "Uncontrolled right turn on a slip lane, signal measures do not apply."
)

# KPIs measured per lane: a movement on a shared lane shows the lane's
# value (data_models.md section 6.7)
LANE_KPIS = {
    KpiName.QUEUE_LENGTH,
    KpiName.QUEUE_STORAGE_RATIO,
}

# KPIs that do not change within the hour
FIXED_KPIS = {
    KpiName.CAPACITY,
    KpiName.SATURATION_FLOW_RATE,
}

# Digits kept for each KPI, as on the page
RATIO_KPIS = {
    KpiName.VOLUME_TO_CAPACITY_RATIO,
    KpiName.QUEUE_STORAGE_RATIO,
}

# Each analysis interval's values are the sample values times this
# factor: a little lower at 08:00, highest at 08:30
INTERVAL_FACTORS = [0.85, 1.0, 1.1, 0.95]

# The sample values the pages used before (made up)
INTERSECTION_VALUES = {
    KpiName.CONTROL_DELAY: 46,
    KpiName.VOLUME_TO_CAPACITY_RATIO: 0.91,
    KpiName.QUEUE_LENGTH: 128,
    KpiName.QUEUE_DURATION: 37,
    KpiName.QUEUE_STORAGE_RATIO: 1.12,
    KpiName.THROUGHPUT: 1842,
}

APPROACH_VALUES = {
    "APP_E": {
        KpiName.CONTROL_DELAY: 52,
        KpiName.VOLUME_TO_CAPACITY_RATIO: 0.94,
        KpiName.CAPACITY: 1710,
        KpiName.QUEUE_LENGTH: 142,
        KpiName.QUEUE_DURATION: 38,
        KpiName.QUEUE_STORAGE_RATIO: 0.81,
        KpiName.THROUGHPUT: 1540,
    },
    "APP_W": {
        KpiName.CONTROL_DELAY: 41,
        KpiName.VOLUME_TO_CAPACITY_RATIO: 0.83,
        KpiName.CAPACITY: 1420,
        KpiName.QUEUE_LENGTH: 109,
        KpiName.QUEUE_DURATION: 29,
        KpiName.QUEUE_STORAGE_RATIO: 0.66,
        KpiName.THROUGHPUT: 1290,
    },
    "APP_S": {
        KpiName.CONTROL_DELAY: 33,
        KpiName.VOLUME_TO_CAPACITY_RATIO: 0.71,
        KpiName.CAPACITY: 1020,
        KpiName.QUEUE_LENGTH: 74,
        KpiName.QUEUE_DURATION: 22,
        KpiName.QUEUE_STORAGE_RATIO: 0.52,
        KpiName.THROUGHPUT: 720,
    },
    "APP_N": {
        KpiName.CONTROL_DELAY: 58,
        KpiName.VOLUME_TO_CAPACITY_RATIO: 1.04,
        KpiName.CAPACITY: 760,
        KpiName.QUEUE_LENGTH: 168,
        KpiName.QUEUE_DURATION: 61,
        KpiName.QUEUE_STORAGE_RATIO: 1.12,
        KpiName.THROUGHPUT: 790,
    },
}

# A slip has values only for the KPIs that are not signal measures
MOVEMENT_VALUES = {
    "MOV_E_W": {
        KpiName.CONTROL_DELAY: 44,
        KpiName.VOLUME_TO_CAPACITY_RATIO: 0.88,
        KpiName.CAPACITY: 1180,
        KpiName.SATURATION_FLOW_RATE: 1820,
        KpiName.QUEUE_LENGTH: 142,
        KpiName.QUEUE_DURATION: 31,
        KpiName.QUEUE_STORAGE_RATIO: 0.81,
        KpiName.THROUGHPUT: 1040,
    },
    "MOV_E_S": {
        KpiName.CONTROL_DELAY: 71,
        KpiName.VOLUME_TO_CAPACITY_RATIO: 0.94,
        KpiName.CAPACITY: 530,
        KpiName.SATURATION_FLOW_RATE: 1760,
        KpiName.QUEUE_LENGTH: 142,
        KpiName.QUEUE_DURATION: 52,
        KpiName.QUEUE_STORAGE_RATIO: 0.81,
        KpiName.THROUGHPUT: 500,
    },
    "MOV_W_E": {
        KpiName.CONTROL_DELAY: 36,
        KpiName.VOLUME_TO_CAPACITY_RATIO: 0.79,
        KpiName.CAPACITY: 960,
        KpiName.SATURATION_FLOW_RATE: 1800,
        KpiName.QUEUE_LENGTH: 109,
        KpiName.QUEUE_DURATION: 26,
        KpiName.QUEUE_STORAGE_RATIO: 0.66,
        KpiName.THROUGHPUT: 760,
    },
    "MOV_W_N": {
        KpiName.CONTROL_DELAY: 53,
        KpiName.VOLUME_TO_CAPACITY_RATIO: 0.83,
        KpiName.CAPACITY: 460,
        KpiName.SATURATION_FLOW_RATE: 1750,
        KpiName.QUEUE_LENGTH: 109,
        KpiName.QUEUE_DURATION: 35,
        KpiName.QUEUE_STORAGE_RATIO: 0.66,
        KpiName.THROUGHPUT: 380,
    },
    "MOV_W_S_SLIP": {
        KpiName.CONTROL_DELAY: 7,
        KpiName.QUEUE_LENGTH: 15,
        KpiName.QUEUE_DURATION: 4,
        KpiName.QUEUE_STORAGE_RATIO: 0.25,
        KpiName.THROUGHPUT: 150,
    },
    "MOV_S_W": {
        KpiName.CONTROL_DELAY: 33,
        KpiName.VOLUME_TO_CAPACITY_RATIO: 0.71,
        KpiName.CAPACITY: 1020,
        KpiName.SATURATION_FLOW_RATE: 1790,
        KpiName.QUEUE_LENGTH: 74,
        KpiName.QUEUE_DURATION: 22,
        KpiName.QUEUE_STORAGE_RATIO: 0.52,
        KpiName.THROUGHPUT: 640,
    },
    "MOV_S_E_BYPASS": {
        KpiName.CONTROL_DELAY: 6,
        KpiName.QUEUE_LENGTH: 12,
        KpiName.QUEUE_DURATION: 3,
        KpiName.QUEUE_STORAGE_RATIO: 0.2,
        KpiName.THROUGHPUT: 80,
    },
    "MOV_N_E": {
        KpiName.CONTROL_DELAY: 64,
        KpiName.VOLUME_TO_CAPACITY_RATIO: 1.04,
        KpiName.CAPACITY: 760,
        KpiName.SATURATION_FLOW_RATE: 1740,
        KpiName.QUEUE_LENGTH: 168,
        KpiName.QUEUE_DURATION: 61,
        KpiName.QUEUE_STORAGE_RATIO: 1.12,
        KpiName.THROUGHPUT: 700,
    },
    "MOV_N_W_SLIP": {
        KpiName.CONTROL_DELAY: 8,
        KpiName.QUEUE_LENGTH: 18,
        KpiName.QUEUE_DURATION: 5,
        KpiName.QUEUE_STORAGE_RATIO: 0.3,
        KpiName.THROUGHPUT: 90,
    },
}


def analysis_intervals(
    run: dict,
) -> list[tuple[datetime, datetime]]:
    """Return the run's 15-minute analysis intervals as Riyadh times."""

    run_start = datetime.fromisoformat(run["run_start"])
    intervals = []

    for start_s in range(
        run["analysis_start_s"],
        run["analysis_end_s"],
        run["interval_s"],
    ):
        start = run_start + timedelta(seconds=start_s)
        end = start + timedelta(seconds=run["interval_s"])
        intervals.append((start, end))

    return intervals


def interval_values(
    values: dict[KpiName, float],
    factor: float,
) -> dict[KpiName, float]:
    """Return the sample values of one interval, rounded as on the page."""

    scaled = {}

    for kpi, value in values.items():
        if kpi not in FIXED_KPIS:
            value = value * factor

        if kpi in RATIO_KPIS:
            scaled[kpi] = round(value, 2)
        else:
            scaled[kpi] = round(value)

    return scaled


def shared_lanes(
    config: NetworkMappingConfig,
) -> dict[str, str]:
    """Return the shared lane of each movement that uses one."""

    lane_of_movement = {}

    for lane in config.approach_lanes:
        if len(lane.served_movement_ids) < 2:
            continue

        for movement_id in lane.served_movement_ids:
            lane_of_movement[movement_id] = lane.lane_id

    return lane_of_movement


def element_results(
    level: KpiLevel,
    element_id: str,
    values: dict[KpiName, float],
    interval: tuple[datetime, datetime],
    run_id: str,
    is_slip: bool = False,
    has_slips: bool = False,
    shared_lane_id: str | None = None,
) -> list[KpiResult]:
    """Return the KPI results of one element for one interval."""

    results = []

    for kpi in KPIS_OF_LEVEL[level]:
        method = METHOD_OF_KPI[kpi]
        fields = {
            "kpi": kpi,
            "level": level,
            f"{level.value}_id": element_id,
            "interval_start": interval[0],
            "interval_end": interval[1],
            "unit": UNIT_OF_KPI[kpi],
            "method": method,
            "scenario_id": SCENARIO_ID,
            "run_ids": (
                [run_id]
                if method == KpiMethod.SIMULATION
                else []
            ),
        }

        if is_slip and kpi in SIGNAL_KPIS:
            results.append(
                KpiResult(
                    **fields,
                    status=KpiStatus.NOT_APPLICABLE,
                    reason=SLIP_REASON,
                )
            )
            continue

        if kpi == KpiName.LEVEL_OF_SERVICE:
            grade = level_of_service(
                control_delay_s=values[KpiName.CONTROL_DELAY],
                volume_to_capacity=(
                    values[KpiName.VOLUME_TO_CAPACITY_RATIO]
                    if level == KpiLevel.MOVEMENT
                    else None
                ),
            )
            fields["los_grade"] = grade
        else:
            fields["value"] = values[kpi]

        if has_slips:
            fields["uncontrolled_movements"] = (
                UNCONTROLLED_TAG_BY_METHOD[method]
            )

        if shared_lane_id is not None and kpi in LANE_KPIS:
            fields["measured_on_lane_id"] = shared_lane_id

        results.append(
            KpiResult(
                **fields,
                status=KpiStatus.OK,
                input_origins=ORIGINS_OF_METHOD[method],
            )
        )

    return results


def build_test_kpis(
    run: dict,
    config: NetworkMappingConfig,
) -> dict:
    """Return the test KPI results of every analysis interval of a run."""

    approach_of_movement = {
        movement.movement_id: movement.approach_id
        for movement in config.movement_mappings
    }
    slips = {
        attributes.movement_id
        for attributes in config.movement_attributes
        if attributes.control == MovementControl.UNCONTROLLED
    }
    approaches_with_slips = {
        approach_of_movement[movement_id]
        for movement_id in slips
    }
    lane_of_movement = shared_lanes(
        config=config,
    )
    intersection_id = config.intersection_mapping.intersection_id
    results = []

    for interval, factor in zip(
        analysis_intervals(
            run=run,
        ),
        INTERVAL_FACTORS,
        strict=True,
    ):
        results += element_results(
            level=KpiLevel.INTERSECTION,
            element_id=intersection_id,
            values=interval_values(
                values=INTERSECTION_VALUES,
                factor=factor,
            ),
            interval=interval,
            run_id=run["run_id"],
            has_slips=bool(slips),
        )

        for approach_id, values in APPROACH_VALUES.items():
            results += element_results(
                level=KpiLevel.APPROACH,
                element_id=approach_id,
                values=interval_values(
                    values=values,
                    factor=factor,
                ),
                interval=interval,
                run_id=run["run_id"],
                has_slips=approach_id in approaches_with_slips,
            )

        for movement_id, values in MOVEMENT_VALUES.items():
            results += element_results(
                level=KpiLevel.MOVEMENT,
                element_id=movement_id,
                values=interval_values(
                    values=values,
                    factor=factor,
                ),
                interval=interval,
                run_id=run["run_id"],
                is_slip=movement_id in slips,
                shared_lane_id=lane_of_movement.get(movement_id),
            )

    return {
        "run_id": run["run_id"],
        "is_test": True,
        "scenario_id": SCENARIO_ID,
        "intersection_id": intersection_id,
        "results": [
            result.model_dump(
                mode="json",
            )
            for result in results
        ],
    }


def main() -> None:
    with (RUN_DIR / "run.json").open(
        encoding="utf-8",
    ) as file:
        run = json.load(file)

    kpis = build_test_kpis(
        run=run,
        config=load_network_mappings(
            file_path=MAPPING_PATH,
        ),
    )

    with (RUN_DIR / "kpis.json").open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            kpis,
            file,
            separators=(",", ":"),
        )

    print(
        f"{len(kpis['results'])} results for {kpis['run_id']} "
        f"in {(RUN_DIR / 'kpis.json').relative_to(REPO_ROOT)}"
    )


if __name__ == "__main__":
    main()
