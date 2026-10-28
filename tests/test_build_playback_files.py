import json
import sys
from datetime import datetime

import pytest

from backend.outputs.intersections import (
    REPO_ROOT,
)


SCRIPTS_DIR = REPO_ROOT / "simulation" / "scene_3d"

sys.path.insert(0, str(SCRIPTS_DIR))

from build_playback import (  # noqa: E402
    find_run_files,
    read_run_window,
)


def touch(
    path,
) -> None:
    """Create an empty file and its folders."""

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        "",
        encoding="utf-8",
    )


def test_files_of_a_baseline_run_folder(
    tmp_path,
) -> None:
    for name in (
        "demand/demand_manifest.json",
        "demand/demand_demand.json",
        "demand/demand_routes.rou.xml",
        "run/raw/fcd.xml",
        "run/raw/tls_states.xml",
    ):
        touch(
            path=tmp_path / name,
        )

    files = find_run_files(
        run_dir=tmp_path,
    )

    assert files == {
        "fcd": tmp_path / "run" / "raw" / "fcd.xml",
        "tls_states": tmp_path / "run" / "raw" / "tls_states.xml",
        "manifest": tmp_path / "demand" / "demand_manifest.json",
        "demand": tmp_path / "demand" / "demand_demand.json",
    }


def test_files_of_a_flat_run_folder(
    tmp_path,
) -> None:
    for name in (
        "test_manifest.json",
        "test_demand.json",
        "fcd.xml",
        "tls_states.xml",
    ):
        touch(
            path=tmp_path / name,
        )

    files = find_run_files(
        run_dir=tmp_path,
    )

    assert files["fcd"] == tmp_path / "fcd.xml"
    assert files["manifest"] == tmp_path / "test_manifest.json"


def test_a_missing_demand_file_is_reported(
    tmp_path,
) -> None:
    touch(
        path=tmp_path / "demand" / "demand_manifest.json",
    )
    touch(
        path=tmp_path / "run" / "raw" / "fcd.xml",
    )

    with pytest.raises(
        FileNotFoundError,
        match="demand.json",
    ):
        find_run_files(
            run_dir=tmp_path,
        )


def test_run_window_from_summary(
    tmp_path,
) -> None:
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "run_id": "RUN_BASELINE_20261027T0800-0900_S42",
                "run_window": {
                    "start": "2026-10-27T07:45:00+03:00",
                    "analysis_start": "2026-10-27T08:00:00+03:00",
                    "analysis_end": "2026-10-27T09:00:00+03:00",
                    "end": "2026-10-27T09:15:00+03:00",
                    "duration_s": 5400,
                },
            }
        ),
        encoding="utf-8",
    )

    run = read_run_window(
        summary_path=summary_path,
    )

    assert run == {
        "run_id": "RUN_BASELINE_20261027T0800-0900_S42",
        "run_start": datetime.fromisoformat("2026-10-27T07:45:00+03:00"),
        "duration_s": 5400,
        "warm_up_s": 900,
        "clearance_s": 900,
    }
