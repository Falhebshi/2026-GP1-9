"""The day runner of the historical analysis, with the simulation and FCD reading replaced."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from backend.analytics.history import load_day, save_day, stored_days
from simulation.scripts.run_baseline import BaselineNotStarted
from simulation.scripts.run_history import (
    day_end,
    days_between,
    history_run_id,
    last_released_day,
    main,
    released_until,
    run_history,
)
from test_history import measurements, whole_day_window


DAY_1, DAY_2, DAY_3 = date(2026, 10, 27), date(2026, 10, 28), date(2026, 10, 29)
RIYADH = timezone(timedelta(hours=3))


def riyadh(text):
    return datetime.fromisoformat(text).replace(tzinfo=RIYADH)


class FakeClient:
    """Stands in for a traffic source: only the end of its latest released interval."""

    def __init__(self, latest=riyadh("2026-12-31T00:00")):
        self.latest = latest

    def fetch_latest_available_timestamp(self):
        return self.latest


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
        self.options = []

    def __call__(self, analysis_start, analysis_end, *, client, output_dir, run_id, seed, **options):
        day = analysis_start.date()
        self.days.append(day)
        self.options.append(options)
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


# A real time whose demo clock (13 weeks earlier) is after the test days
LATE_ENOUGH = riyadh("2027-02-01T12:00")


def runner(tmp_path, simulation, **options):
    """The hand-made days of test_history have synthetic demand, so synthetic is the default here."""

    return run_history(
        options.pop("days", [DAY_1, DAY_2]), client=options.pop("client", FakeClient()),
        source=options.pop("source", "synthetic"),
        history_dir=tmp_path / "history", output_root=tmp_path / "runs",
        run=simulation, collect=fake_collect, report=options.pop("report", lambda line: None),
        now=options.pop("now", lambda: LATE_ENOUGH), **options,
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


def test_each_day_gets_its_source_and_a_35_day_history_without_the_live_loop_s_long_gaps(tmp_path):
    """
    RCRC: 35 days of history for estimating missing counts, and the gap
    limit of every run other than the live loop (no fallback_gap_intervals).
    """

    simulation = FakeSimulation()

    runner(tmp_path, simulation, days=[DAY_1], source="rcrc")

    assert simulation.options == [{"source": "rcrc", "history_days": 35}]


# ============================================================
# RELEASED DAYS AND ONE SOURCE
# ============================================================

def test_a_day_needs_its_data_to_00_15_the_next_day():
    assert day_end(DAY_1) == riyadh("2026-10-28T00:15")


@pytest.mark.parametrize("latest, last_day", [
    ("2026-08-27T08:15", date(2026, 8, 26)),   # 26 Aug ends 27 Aug 00:15: released
    ("2026-08-27T00:15", date(2026, 8, 26)),   # exactly at its end
    ("2026-08-27T00:00", date(2026, 8, 25)),   # 26 Aug's clearance not released yet
])
def test_the_last_released_day_is_the_day_before_the_demo_s_today(latest, last_day):
    assert last_released_day(riyadh(latest)) == last_day


def test_a_day_the_source_has_not_released_is_not_run_and_is_not_a_failure(tmp_path):
    """The source has released up to 28 Oct 08:15: 27 Oct is complete, 28 Oct is the demo's today."""

    simulation = FakeSimulation()

    outcomes = runner(tmp_path, simulation, days=[DAY_1, DAY_2], client=FakeClient(riyadh("2026-10-28T08:15")))

    assert [(o.day, o.status) for o in outcomes] == [(DAY_1, "stored"), (DAY_2, "not released")]
    assert simulation.days == [DAY_1]


def test_rcrc_releases_are_capped_at_the_demo_clock():
    """
    A replay server started for calibration (offset 0) has released the
    whole report, to 13 Oct. Real time Thu 26 Nov 19:30 minus 13 weeks
    is Thu 27 Aug 19:30: nothing after it is used, and the log says why.
    """

    lines = []
    latest = released_until(FakeClient(riyadh("2026-10-13T00:00")), "rcrc", riyadh("2026-11-26T19:30"), lines.append)

    assert latest == riyadh("2026-08-27T19:30")
    assert "after the demo clock" in lines[0]
    assert last_released_day(latest) == date(2026, 8, 26)


def test_a_source_behind_the_demo_clock_and_a_synthetic_source_are_not_capped():
    behind = riyadh("2026-08-20T10:00")
    assert released_until(FakeClient(behind), "rcrc", riyadh("2026-11-26T19:30"), print) == behind
    assert released_until(FakeClient(riyadh("2026-10-13T00:00")), "synthetic", riyadh("2026-11-26T19:30"), print) \
        == riyadh("2026-10-13T00:00")


def test_the_demo_s_today_is_not_run_even_when_the_server_released_it(tmp_path):
    """Server at offset 0 (released to 13 Oct), demo clock 27 Aug 19:30: 26 Aug is stored, 27 Aug is not run."""

    simulation = FakeSimulation()
    days = [date(2026, 8, 26), date(2026, 8, 27)]

    outcomes = runner(tmp_path, simulation, days=days, source="rcrc",
                      client=FakeClient(riyadh("2026-10-13T00:00")), now=lambda: riyadh("2026-11-26T19:30"))

    assert [(o.day, o.status) for o in outcomes] == [(days[0], "stored"), (days[1], "not released")]
    assert simulation.days == [days[0]]


def test_the_nightly_command_runs_up_to_the_day_before_the_demo_s_today(tmp_path):
    """main() without --last-day, as the nightly task runs it: 25 and 26 Aug are stored, nothing later."""

    simulation = FakeSimulation()

    code = main(
        ["--first-day", "2026-08-25", "--history-dir", str(tmp_path / "history")],
        client=FakeClient(riyadh("2026-10-13T00:00")), now=lambda: riyadh("2026-11-26T19:30"),
        run=simulation, collect=fake_collect, output_root=tmp_path / "runs", report=lambda line: None,
    )

    assert code == 0
    assert simulation.days == [date(2026, 8, 25), date(2026, 8, 26)]
    assert stored_days(tmp_path / "history") == [date(2026, 8, 25), date(2026, 8, 26)]


def test_days_of_the_same_source_pass_the_check(tmp_path):
    save_day(measurements(whole_day_window(DAY_1)), tmp_path / "history")   # synthetic demand

    outcomes = runner(tmp_path, FakeSimulation(), days=[DAY_2], source="synthetic")

    assert outcomes[0].status == "stored"


def test_days_of_another_source_stop_the_runner_before_anything_runs(tmp_path):
    save_day(measurements(whole_day_window(DAY_1)), tmp_path / "history")   # synthetic demand
    simulation = FakeSimulation()

    with pytest.raises(ValueError, match="holds days from the synthetic source"):
        runner(tmp_path, simulation, days=[DAY_2], source="rcrc")

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
