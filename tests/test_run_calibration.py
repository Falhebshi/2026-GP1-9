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
