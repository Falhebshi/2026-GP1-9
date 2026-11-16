"""The day runner of the historical analysis, with the simulation and FCD reading replaced."""

import json
from datetime import date

import pytest

from backend.analytics.history import load_day, save_day, stored_days
from simulation.scripts.run_baseline import BaselineNotStarted
from simulation.scripts.run_history import days_between, history_run_id, run_history
from test_history import measurements, whole_day_window


DAY_1, DAY_2, DAY_3 = date(2026, 10, 27), date(2026, 10, 28), date(2026, 10, 29)


def write_run_folder(run_dir, day, status="completed"):
    """A run folder as run_baseline leaves it: summary.json and the raw files."""

    window = whole_day_window(day)
    run = measurements(window).run.model_dump(mode="json")
    run["status"] = status
    summary = {
        "run_window": {
            "start": window.epoch.isoformat(),
            "analysis_start": window.analysis_start.isoformat(),
            "analysis_end": window.analysis_end.isoformat(),
            "end": window.run_end.isoformat(),
            "duration_s": window.duration_s,
        },
        "simulation_run": run,
    }
    raw = run_dir / "run" / "raw"
    raw.mkdir(parents=True)
    (raw / "fcd.xml").write_text("<fcd-export/>", encoding="utf-8")
    (raw / "tripinfo.xml").write_text("<tripinfos/>", encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")


class FakeSimulation:
    """Stands in for run_baseline: writes a run folder and remembers the days it ran."""

    def __init__(self, status="completed", fail_on=None):
        self.status = status
        self.fail_on = fail_on or set()
        self.days = []

    def __call__(self, analysis_start, analysis_end, *, client, output_dir, run_id, seed):
        day = analysis_start.date()
        self.days.append(day)
        if day in self.fail_on:
            raise BaselineNotStarted(["the source has no data for this day"])
        assert (analysis_end - analysis_start).days == 1
        assert analysis_start.utcoffset().total_seconds() == 3 * 3600
        assert run_id == history_run_id(day, seed)
        write_run_folder(output_dir, day, status=self.status)
        return {"status": self.status}


def fake_collect(files):
    """Stands in for collect_measurements: the hand-made records of test_history, for the run's day."""

    return measurements(files.window)


def runner(tmp_path, simulation, **options):
    return run_history(
        options.pop("days", [DAY_1, DAY_2]), client=None,
        history_dir=tmp_path / "history", output_root=tmp_path / "runs",
        run=simulation, collect=fake_collect, report=lambda line: None, **options,
    )


# ============================================================
# STORING DAYS
# ============================================================

def test_each_day_is_simulated_stored_and_its_raw_files_deleted(tmp_path):
    simulation = FakeSimulation()

    outcomes = runner(tmp_path, simulation)

    assert [(o.day, o.status) for o in outcomes] == [(DAY_1, "stored"), (DAY_2, "stored")]
    assert simulation.days == [DAY_1, DAY_2]
    assert stored_days(tmp_path / "history") == [DAY_1, DAY_2]
    assert load_day(DAY_1, tmp_path / "history") == measurements(whole_day_window(DAY_1))

    run_dir = tmp_path / "runs" / "RUN_HISTORY_20261027_S42"
    assert not (run_dir / "run" / "raw" / "fcd.xml").exists()
    assert not (run_dir / "run" / "raw" / "tripinfo.xml").exists()
    assert (run_dir / "summary.json").exists()


def test_raw_files_are_kept_when_asked(tmp_path):
    runner(tmp_path, FakeSimulation(), days=[DAY_1], keep_raw=True)

    assert (tmp_path / "runs" / "RUN_HISTORY_20261027_S42" / "run" / "raw" / "fcd.xml").exists()


def test_a_stored_day_is_skipped_so_a_batch_can_be_restarted(tmp_path):
    save_day(measurements(whole_day_window(DAY_1)), tmp_path / "history")
    simulation = FakeSimulation()

    outcomes = runner(tmp_path, simulation)

    assert [(o.day, o.status) for o in outcomes] == [(DAY_1, "skipped"), (DAY_2, "stored")]
    assert simulation.days == [DAY_2]


def test_a_finished_run_whose_day_was_not_stored_is_reused_not_simulated_again(tmp_path):
    write_run_folder(tmp_path / "runs" / "RUN_HISTORY_20261027_S42", DAY_1)
    simulation = FakeSimulation()

    outcomes = runner(tmp_path, simulation, days=[DAY_1])

    assert outcomes[0].status == "stored"
    assert outcomes[0].detail.startswith("existing run reused")
    assert simulation.days == []


# ============================================================
# FAILED DAYS
# ============================================================

def test_a_day_that_cannot_start_fails_and_the_batch_continues(tmp_path):
    simulation = FakeSimulation(fail_on={DAY_2})

    outcomes = runner(tmp_path, simulation, days=[DAY_1, DAY_2, DAY_3])

    assert [(o.day, o.status) for o in outcomes] == [
        (DAY_1, "stored"), (DAY_2, "failed"), (DAY_3, "stored"),
    ]
    assert "the source has no data for this day" in outcomes[1].detail
    assert stored_days(tmp_path / "history") == [DAY_1, DAY_3]


def test_a_simulation_that_does_not_complete_fails_and_nothing_is_stored(tmp_path):
    outcomes = runner(tmp_path, FakeSimulation(status="failed"), days=[DAY_1])

    assert outcomes[0].status == "failed"
    assert "did not complete (status failed)" in outcomes[0].detail
    assert stored_days(tmp_path / "history") == []


def test_an_unfinished_run_folder_fails_the_day_and_says_what_to_do(tmp_path):
    write_run_folder(tmp_path / "runs" / "RUN_HISTORY_20261027_S42", DAY_1, status="failed")

    outcomes = runner(tmp_path, FakeSimulation(), days=[DAY_1])

    assert outcomes[0].status == "failed"
    assert "delete that folder to simulate the day again" in outcomes[0].detail


# ============================================================
# DAYS AND NAMES
# ============================================================

def test_days_between_includes_both_ends():
    assert days_between(DAY_1, DAY_3) == [DAY_1, DAY_2, DAY_3]
    assert days_between(DAY_1, DAY_1) == [DAY_1]


def test_days_in_the_wrong_order_are_refused():
    with pytest.raises(ValueError, match="last day 2026-10-27 is before first day 2026-10-29"):
        days_between(DAY_3, DAY_1)


def test_history_run_id():
    assert history_run_id(date(2026, 10, 22), 42) == "RUN_HISTORY_20261022_S42"
