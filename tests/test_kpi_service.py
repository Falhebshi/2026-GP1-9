"""The KPIs of one baseline run: reading the run folder, the checks, and a real run end to end."""

import json
import shutil
from datetime import timedelta

import pytest

from backend.analytics.service import (
    DEFAULT_MAPPING_PATH,
    calculate_run_kpis,
    load_run,
    write_kpis,
)
from jaadah.mapping.loader import load_network_mappings
from jaadah.models.kpis import KpiLevel, KpiName, KpiStatus
from simulation.scripts.run_baseline import run_baseline
from test_baseline_run import ANALYSIS_START, source  # noqa: F401  (source is a fixture)


SUMMARY = {
    "run_window": {
        "start": "2026-10-18T07:45:00+03:00",
        "analysis_start": "2026-10-18T08:00:00+03:00",
        "analysis_end": "2026-10-18T08:15:00+03:00",
        "end": "2026-10-18T08:30:00+03:00",
        "duration_s": 2700,
    },
    "simulation_run": {
        "run_id": "RUN_TEST",
        "scenario_id": "SCN_TEST",
        "random_seed": 42,
        "network_version": "jaadah_network_v2",
        "sumo_version": "1.27.1",
        "step_length_s": 0.4,
        "mapping_version": load_network_mappings(DEFAULT_MAPPING_PATH).mapping_version,
        "demand_sha256": "a" * 64,
        "route_file_sha256": "b" * 64,
        "started_at": "2026-10-28T10:00:00+03:00",
        "status": "completed",
    },
}


def run_folder(tmp_path, **run_changes):
    summary = json.loads(json.dumps(SUMMARY))
    summary["simulation_run"].update(run_changes)
    (tmp_path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return tmp_path


# ============================================================
# READING THE RUN FOLDER AND CHECKS
# ============================================================

def test_run_folder_gives_the_run_its_window_and_its_files(tmp_path):
    files = load_run(run_folder(tmp_path))

    assert files.run.run_id == "RUN_TEST"
    assert files.window.duration_s == 2700
    assert files.window.analysis_start.isoformat() == "2026-10-18T08:00:00+03:00"
    assert files.fcd_path == tmp_path / "run" / "raw" / "fcd.xml"
    assert files.manifest_path == tmp_path / "demand" / "demand_manifest.json"


def test_failed_run_has_no_kpis(tmp_path):
    files = load_run(run_folder(tmp_path, status="failed"))

    with pytest.raises(ValueError, match="run RUN_TEST is failed; only a completed run has KPIs"):
        calculate_run_kpis(files)


def test_run_with_another_mapping_version_is_refused(tmp_path):
    files = load_run(run_folder(tmp_path, mapping_version="0.0-old"))

    with pytest.raises(ValueError, match="used mapping 0.0-old"):
        calculate_run_kpis(files)


# ============================================================
# A REAL BASELINE RUN END TO END
# ============================================================

@pytest.mark.skipif(shutil.which("sumo") is None, reason="SUMO is not installed")
def test_baseline_run_gives_every_kpi_for_every_element(source, tmp_path):  # noqa: F811
    """
    Synthetic source -> run_baseline -> SUMO -> measurement records ->
    KPI engine -> kpis.json, for a 30-minute analysis (07:45-08:45): two
    15-minute intervals and the whole period.
    """

    analysis_end = ANALYSIS_START + timedelta(minutes=30)
    middle = ANALYSIS_START + timedelta(minutes=15)
    client = source(stored_through=analysis_end + timedelta(minutes=15))
    run_dir = tmp_path / "baseline"
    run_baseline(ANALYSIS_START, analysis_end, client=client, output_dir=run_dir, run_id="RUN_TEST")

    files = load_run(run_dir)
    results = calculate_run_kpis(files)

    # All nine KPIs, for the 9 movements, 4 approaches and the intersection
    assert {r.kpi for r in results} == set(KpiName)
    elements = {(r.level, getattr(r, f"{r.level.value}_id")) for r in results}
    assert len({e for e in elements if e[0] == KpiLevel.MOVEMENT}) == 9
    assert len({e for e in elements if e[0] == KpiLevel.APPROACH}) == 4
    assert {e for e in elements if e[0] == KpiLevel.INTERSECTION} == {(KpiLevel.INTERSECTION, "INT_001")}

    # Every KPI per 15-minute interval; queues also over the whole period
    def kpis_of(start, end):
        return {r.kpi for r in results if (r.interval_start, r.interval_end) == (start, end)}

    assert kpis_of(ANALYSIS_START, middle) == set(KpiName)
    assert kpis_of(middle, analysis_end) == set(KpiName)
    assert kpis_of(ANALYSIS_START, analysis_end) == {KpiName.QUEUE_LENGTH, KpiName.QUEUE_STORAGE_RATIO}
    assert {(r.interval_start, r.interval_end) for r in results} == {
        (ANALYSIS_START, middle), (middle, analysis_end), (ANALYSIS_START, analysis_end),
    }

    # Every result belongs to the run, and is either a value or a status
    # with its reason
    assert all(r.scenario_id == files.run.scenario_id for r in results)
    assert all(r.run_ids in ([], ["RUN_TEST"]) for r in results)
    assert all(r.reason for r in results if r.status != KpiStatus.OK)
    assert any(r.status == KpiStatus.OK for r in results)

    # The file names the run and holds no SUMO identifiers
    path = write_kpis(results, tmp_path / "kpis.json", files.run)
    text = path.read_text(encoding="utf-8")
    saved = json.loads(text)
    assert saved["run_id"] == "RUN_TEST"
    assert len(saved["results"]) == len(results)
    assert "#" not in text and "cluster" not in text
