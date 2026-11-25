from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from traffic_source.rcrc_replay.clock import released_until, replay_now
from traffic_source.rcrc_replay.config import RIYADH, ReplayConfig
from traffic_source.rcrc_replay.load import main as load_main
from traffic_source.rcrc_replay.load import missing_runs
from traffic_source.rcrc_replay.report import RCRC_COLUMNS, read_rcrc_report
from traffic_source.rcrc_replay.server import create_app
from traffic_source.rcrc_replay.storage import RcrcReplayStorage


# Artificial reports in the layout of the RCRC "Intersection historical
# data report" export. The values are invented; the private report is
# never used in tests.
TITLE = (
    '"Intersection historical data report for : 1444  (GP3- 1444 A - Test road)\n'
    'From Jul 13, 2026 00:00 to Jul 14, 2026 00:00 ; Aggregation Interval: 15  (minutes)",,,,'
)
HEADER = ",".join(RCRC_COLUMNS)
DETECTORS = ("144409: P2-NB-L1-L-STB-RP2", "144410: P2-NB-L2-L-STB-RP2")
DAY = datetime(2026, 7, 13, tzinfo=RIYADH)
STEP = timedelta(minutes=15)


def stamp(moment: datetime) -> str:
    return moment.strftime("%b %d, %Y %H:%M:%S")


def row(detector: str, moment: datetime, volume="10", occ_s="30", occ_pct="3") -> str:
    return f'{detector},"{stamp(moment)}",{volume},{occ_s},{occ_pct}'


def write_report(tmp_path, rows, title=TITLE, header=HEADER, name="report.csv"):
    path = tmp_path / name
    path.write_text("\n".join([title, header, *rows]) + "\n", encoding="utf-8")
    return path


def day_report(tmp_path, skip=(), name="report.csv"):
    """
    One day of rows for two detectors, interval ends 00:15 to 24:00,
    in RCRC's layout (one block per detector, header repeated). Interval
    ends in `skip` are left out for both detectors.
    """

    rows = []
    for index, detector in enumerate(DETECTORS):
        if index:
            rows.append(HEADER)
        for step in range(1, 97):
            moment = DAY + step * STEP
            if moment not in skip:
                rows.append(row(detector, moment, volume=str(step)))
    return write_report(tmp_path, rows, name=name)


# ============================================================
# REPORT FILE
# ============================================================

def test_report_gives_site_rows_and_fingerprint(tmp_path):
    report = read_rcrc_report(day_report(tmp_path))

    assert report.site_id == "1444"
    assert len(report.rows) == 192
    assert report.repeated_header_count == 1
    assert len(report.sha256) == 64
    assert report.rows[0].values == {
        "Detector ID : Description": "144409: P2-NB-L1-L-STB-RP2",
        "Time Stamp": "Jul 13, 2026 00:15:00",
        "Volume (Vehicles)": "1",
        "Occupancy (Seconds)": "30",
        "Occupancy (Percent)": "3",
    }
    assert report.rows[0].interval_end == DAY + STEP


def test_rows_are_kept_as_written(tmp_path):
    report = read_rcrc_report(write_report(tmp_path, [row(DETECTORS[0], DAY + STEP, volume="x")]))

    assert report.rows[0].values["Volume (Vehicles)"] == "x"


def test_unreadable_time_stamp_is_kept_but_has_no_interval(tmp_path):
    path = write_report(tmp_path, [f'{DETECTORS[0]},"13/07/2026 00:15",10,30,3'])

    report = read_rcrc_report(path)

    assert report.rows[0].interval_end is None
    assert report.undated_rows == report.rows


@pytest.mark.parametrize(
    "title,header,rows,message",
    [
        ('"Some other export",,,,', HEADER, [], "does not name a site ID"),
        (TITLE.replace("Interval: 15", "Interval: 5"), HEADER, [], "only 15-minute"),
        (TITLE.replace(" ; Aggregation Interval: 15  (minutes)", ""), HEADER, [], "aggregation interval"),
        (TITLE, "Detector ID : Description,Time Stamp", [], "expected column header"),
        (TITLE, HEADER, [row(DETECTORS[0], DAY + STEP) + ",7"], "more values"),
    ],
)
def test_unusable_report_is_refused(tmp_path, title, header, rows, message):
    with pytest.raises(ValueError, match=message):
        read_rcrc_report(write_report(tmp_path, rows, title=title, header=header))


def test_missing_runs_per_detector(tmp_path):
    gap = {DAY + 5 * STEP, DAY + 6 * STEP}

    runs = missing_runs(read_rcrc_report(day_report(tmp_path, skip=gap)))

    assert runs[DETECTORS[0]] == [(DAY + 5 * STEP, 2)]


# ============================================================
# CLOCK
# ============================================================

OFFSET_WEEKS = 18
# The real time at which the replay shows 10:00 on the report's day.
ANCHOR = (DAY + 40 * STEP + timedelta(weeks=OFFSET_WEEKS)).astimezone(timezone.utc)
CONFIG = ReplayConfig(offset_weeks=OFFSET_WEEKS)


@pytest.mark.parametrize(
    "elapsed,expected",
    [
        (timedelta(0), DAY + 40 * STEP),
        (timedelta(minutes=14, seconds=59), DAY + 40 * STEP),
        (timedelta(minutes=15), DAY + 41 * STEP),
        (timedelta(hours=1, minutes=7), DAY + 44 * STEP),
        (-timedelta(hours=1), DAY + 36 * STEP),
    ],
)
def test_clock_releases_whole_intervals_as_time_passes(elapsed, expected):
    assert released_until(ANCHOR + elapsed, CONFIG, data_end=DAY + 96 * STEP) == expected


def test_replay_keeps_the_real_time_of_day_and_weekday():
    real = datetime(2026, 12, 1, 10, 0, tzinfo=RIYADH)  # Tuesday 10:00

    shown = replay_now(real, ReplayConfig())

    assert shown == datetime(2026, 9, 1, 10, 0, tzinfo=RIYADH)
    assert shown.weekday() == real.weekday()


def test_default_replay_shows_mid_august_on_16_november():
    shown = replay_now(datetime(2026, 11, 16, 1, 45, tzinfo=RIYADH), ReplayConfig())

    assert shown == datetime(2026, 8, 17, 1, 45, tzinfo=RIYADH)


def test_clock_stops_at_the_end_of_the_data():
    assert released_until(ANCHOR + timedelta(days=30), CONFIG, DAY + 96 * STEP) == DAY + 96 * STEP


@pytest.mark.parametrize("weeks", [-1, 1.5, True])
def test_invalid_replay_config(weeks):
    with pytest.raises(ValueError, match="offset_weeks"):
        ReplayConfig(offset_weeks=weeks)


# ============================================================
# STORAGE AND API
# ============================================================

class FakeNow:
    def __init__(self, moment: datetime):
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


@pytest.fixture
def replay(tmp_path):
    """A replay source holding one day, released through 10:00."""

    storage = RcrcReplayStorage(tmp_path / "replay.db")
    storage.initialize()
    storage.load_report(read_rcrc_report(day_report(tmp_path, skip={DAY + 20 * STEP})))
    now = FakeNow(ANCHOR)

    with TestClient(create_app(storage=storage, config=CONFIG, now=now)) as api:
        yield api, now, storage


def get_observations(api, start, end):
    return api.get("/observations", params={"start": start.isoformat(), "end": end.isoformat()})


def test_health_reports_how_far_the_feed_has_reached(replay):
    api, now, _ = replay

    assert api.get("/health").json() == {
        "status": "ok",
        "source": "rcrc",
        "site_id": "1444",
        "latest_available_timestamp": (DAY + 40 * STEP).isoformat(),
        "replay_time": (DAY + 40 * STEP).isoformat(),
        "data_start": DAY.isoformat(),
        "data_end": (DAY + 96 * STEP).isoformat(),
    }

    now.moment = ANCHOR + timedelta(minutes=30)

    assert api.get("/health").json()["latest_available_timestamp"] == (DAY + 42 * STEP).isoformat()


def test_observations_are_served_as_rcrc_wrote_them(replay):
    api, _, _ = replay

    body = get_observations(api, DAY, DAY + STEP).json()

    assert body["source"] == "rcrc"
    assert body["site_id"] == "1444"
    assert body["observations"] == [
        {
            "Detector ID : Description": DETECTORS[0],
            "Time Stamp": "Jul 13, 2026 00:15:00",
            "Volume (Vehicles)": "1",
            "Occupancy (Seconds)": "30",
            "Occupancy (Percent)": "3",
        },
        {
            "Detector ID : Description": DETECTORS[1],
            "Time Stamp": "Jul 13, 2026 00:15:00",
            "Volume (Vehicles)": "1",
            "Occupancy (Seconds)": "30",
            "Occupancy (Percent)": "3",
        },
    ]


def test_future_rows_are_not_released(replay):
    api, now, _ = replay

    body = get_observations(api, DAY + 39 * STEP, DAY + 45 * STEP).json()

    assert {o["Time Stamp"] for o in body["observations"]} == {stamp(DAY + 40 * STEP)}
    assert body["latest_available_timestamp"] == (DAY + 40 * STEP).isoformat()

    now.moment = ANCHOR + timedelta(minutes=45)
    body = get_observations(api, DAY + 39 * STEP, DAY + 45 * STEP).json()

    assert len(body["observations"]) == 4 * 2


def test_released_missing_interval_returns_no_rows(replay):
    api, _, _ = replay

    body = get_observations(api, DAY + 19 * STEP, DAY + 20 * STEP).json()

    assert body["observations"] == []


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-07-13T00:00:00", "2026-07-13T01:00:00+03:00"),
        ("2026-07-13T00:07:00+03:00", "2026-07-13T01:00:00+03:00"),
        ("2026-07-13T01:00:00+03:00", "2026-07-13T01:00:00+03:00"),
    ],
)
def test_bad_requests_are_refused(replay, start, end):
    api, _, _ = replay

    assert api.get("/observations", params={"start": start, "end": end}).status_code == 400


def test_detectors(replay):
    api, _, _ = replay

    assert api.get("/detectors").json() == {
        "site_id": "1444",
        "count": 2,
        "detectors": list(DETECTORS),
    }


def test_source_without_a_report(tmp_path):
    storage = RcrcReplayStorage(tmp_path / "empty.db")

    with TestClient(create_app(storage=storage, now=FakeNow(ANCHOR))) as api:
        assert api.get("/health").json()["status"] == "no_report"
        assert api.get("/health").json()["latest_available_timestamp"] is None
        response = get_observations(api, DAY, DAY + STEP)
        assert response.status_code == 503


def test_restarting_the_service_changes_nothing(replay):
    """The clock only depends on the real time, so a restart cannot shift it."""

    _, _, storage = replay

    with TestClient(create_app(storage=storage, config=CONFIG, now=FakeNow(ANCHOR))) as api:
        assert api.get("/health").json()["latest_available_timestamp"] == (
            DAY + 40 * STEP
        ).isoformat()


def test_loading_the_same_report_again_changes_nothing(replay, tmp_path):
    _, _, storage = replay

    assert storage.load_report(read_rcrc_report(day_report(tmp_path, skip={DAY + 20 * STEP}))) is False


def test_loading_another_report_replaces_it(replay, tmp_path):
    _, _, storage = replay

    assert storage.load_report(read_rcrc_report(day_report(tmp_path, name="other.csv"))) is True
    assert storage.get_report_info()["row_count"] == 192


def test_load_command(tmp_path, capsys):
    path = day_report(tmp_path, skip={DAY + 5 * STEP})

    assert load_main([str(path), "--database", str(tmp_path / "cli.db")]) == 0

    output = capsys.readouterr().out
    assert "Loaded: site 1444" in output
    assert "Rows: 190" in output
    assert "weeks behind the real clock" in output
    assert DETECTORS[0] in output
