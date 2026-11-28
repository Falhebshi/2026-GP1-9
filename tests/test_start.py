"""Setup checks of the one-command launcher (backend/start.py). No servers are started."""

import argparse
from datetime import datetime, timedelta, timezone
import io
import socket
import sqlite3

import pytest

from backend.accounts.storage import ROLE_ADMIN, ROLE_ENGINEER, STATUS_INACTIVE, AccountStorage
import backend.start as start
from backend.start import (
    Console,
    SetupCheck,
    StatusPanel,
    active_admin_exists,
    build_services,
    check_setup,
    display_width,
    failure_reason,
    find_sumo,
    offer_fixes,
    port_in_use,
    progress_bar,
    summary_rows,
    report_loaded,
    tidy_line,
)


@pytest.fixture
def setup_paths(tmp_path):
    """A complete setup: private folder, one report, loaded feed, an admin, the website packages."""

    private = tmp_path / "jaadah-private-data"
    report_dir = private / "raw" / "rcrc" / "site_1444"
    report_dir.mkdir(parents=True)
    (report_dir / "report.csv").write_text("x")

    replay_database = private / "processed" / "rcrc_replay" / "rcrc_replay.db"
    replay_database.parent.mkdir(parents=True)
    with sqlite3.connect(replay_database) as connection:
        connection.execute("CREATE TABLE report (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO report (id) VALUES (1)")
    connection.close()

    accounts_database = tmp_path / "accounts.db"
    storage = AccountStorage(accounts_database)
    storage.initialize()
    storage.create_account("Admin", "admin@ksu.edu.sa", "hash", ROLE_ADMIN)

    vite_script = tmp_path / "vite.js"
    vite_script.write_text("")

    return {
        "private_dir": private,
        "report_dir": report_dir,
        "replay_database": replay_database,
        "accounts_database": accounts_database,
        "vite_script": vite_script,
        "ports": (),
        "node": "node",
        "sumo": "sumo",
        "packages": [],
        "environ": {},
        "feed": None,
        "trends_files": [tmp_path / "trends_7d_all.json"],
    }


def test_complete_setup_has_no_problems(setup_paths):
    check = check_setup(with_live=True, **setup_paths)

    assert check.problems == []
    assert check.notes == []
    assert check.report_to_load is None
    assert check.sumo_bin == "sumo"


def test_every_problem_is_reported_at_once(setup_paths, tmp_path):
    setup_paths.update(
        packages=["fastapi"],
        node=None,
        vite_script=tmp_path / "missing.js",
        accounts_database=tmp_path / "no_accounts.db",
    )

    problems = check_setup(with_live=False, **setup_paths).problems

    assert len(problems) == 4
    assert "pip install -r requirements.txt" in problems[0]
    assert "Node.js" in problems[1]
    assert "npm ci" in problems[2]
    assert "create_admin" in problems[3]


def test_missing_private_folder(setup_paths, tmp_path):
    setup_paths["private_dir"] = tmp_path / "nowhere"

    problems = check_setup(with_live=False, **setup_paths).problems

    assert problems == [problem for problem in problems if "private data folder" in problem]
    assert len(problems) == 1


def test_unloaded_report_is_loaded_when_there_is_one(setup_paths, tmp_path):
    setup_paths["replay_database"] = tmp_path / "empty.db"

    check = check_setup(with_live=False, **setup_paths)

    assert check.problems == []
    assert check.report_to_load == setup_paths["report_dir"] / "report.csv"


@pytest.mark.parametrize("reports, expected", [(0, "No RCRC report"), (2, "2 RCRC reports")])
def test_unloaded_report_needs_a_choice(setup_paths, tmp_path, reports, expected):
    setup_paths["replay_database"] = tmp_path / "empty.db"
    for path in setup_paths["report_dir"].glob("*.csv"):
        path.unlink()
    for number in range(reports):
        (setup_paths["report_dir"] / f"report_{number}.csv").write_text("x")

    check = check_setup(with_live=False, **setup_paths)

    assert check.report_to_load is None
    assert len(check.problems) == 1
    assert expected in check.problems[0]


def test_missing_sumo_only_skips_the_live_loop(setup_paths):
    setup_paths["sumo"] = None

    check = check_setup(with_live=True, **setup_paths)

    assert check.problems == []
    assert "live update loop" in check.notes[0]
    assert all(
        service.label != "live" for group in build_services("python", "node", check.sumo_bin) for service in group
    )


def test_busy_port_is_a_problem(setup_paths):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        setup_paths["ports"] = (port,)

        problems = check_setup(with_live=False, **setup_paths).problems

    assert port_in_use(port) is False
    assert len(problems) == 1
    assert f"Port {port} is already in use" in problems[0]


def test_report_loaded_reads_the_report_row(tmp_path):
    database = tmp_path / "replay.db"
    assert report_loaded(database) is False

    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE report (id INTEGER PRIMARY KEY)")
    connection.close()
    assert report_loaded(database) is False


def test_only_an_active_admin_counts(tmp_path):
    database = tmp_path / "accounts.db"
    storage = AccountStorage(database)
    storage.initialize()
    storage.create_account("Engineer", "eng@ksu.edu.sa", "hash", ROLE_ENGINEER)
    assert active_admin_exists(database) is False

    admin = storage.create_account("Admin", "admin@ksu.edu.sa", "hash", ROLE_ADMIN)
    assert active_admin_exists(database) is True

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE accounts SET status = ? WHERE id = ?", (STATUS_INACTIVE, admin.id))
    connection.close()
    assert active_admin_exists(database) is False


def test_sumo_from_sumo_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "sumo").write_text("")

    assert find_sumo({"SUMO_HOME": str(tmp_path)}) == str(tmp_path / "bin" / "sumo")
    assert find_sumo({}) is None


def test_services_start_feed_first_and_live_loop_last():
    groups = build_services("python", "node", "sumo")

    assert [service.label for service in groups[0]] == ["rcrc"]
    assert {service.label for service in groups[1]} == {"network", "accounts", "website"}
    assert [service.label for service in groups[2]] == ["live"]
    assert groups[2][0].required is False


def test_failure_reason_is_the_last_exception_line():
    lines = [
        "Traceback (most recent call last):",
        '  File "server.py", line 165, in lifespan',
        "ValueError: network_speeds.db was built from other inputs. Delete it and start again.",
        "",
        "ERROR:    Application startup failed. Exiting.",
    ]

    assert failure_reason(lines) == lines[2]
    assert failure_reason(["INFO:     Started server process [1]"]) is None


def test_tidy_line_hides_request_logs_and_blank_lines():
    request = 'INFO:     127.0.0.1:64062 - "GET /speeds?time=x HTTP/1.1" 200 OK'
    assert tidy_line(request) == (None, None)
    assert tidy_line(request, verbose=True)[0].endswith("200 OK")
    assert tidy_line("   ") == (None, None)
    assert tidy_line("INFO:     Application startup complete.") == ("Application startup complete.", None)
    assert tidy_line("ERROR:    Application startup failed. Exiting.") == ("Application startup failed. Exiting.", "31")
    assert tidy_line("  VITE v8.3.3  ready in 721 ms") == ("  VITE v8.3.3  ready in 721 ms", None)


def test_progress_bar():
    assert progress_bar(0, 4, 8, "#", ".") == "........"
    assert progress_bar(2, 4, 8, "#", ".") == "####...."
    assert progress_bar(4, 4, 8, "#", ".") == "########"


def test_summary_puts_the_website_first():
    services = [service for group in build_services("python", "node", "sumo") for service in group]
    rows = summary_rows(services)

    assert rows[0] == ("Website", "http://localhost:5173")
    assert ("Live update loop", "running") in rows


def test_website_is_checked_on_ipv4_and_ipv6():
    website = next(s for g in build_services("python", "node", None) for s in g if s.label == "website")

    assert website.health_urls == ("http://127.0.0.1:5173/", "http://[::1]:5173/")


def test_website_runs_in_the_frontend_folder():
    """Vite serves the folder it starts in: from the repository root it finds no index.html and no config."""

    website = next(s for g in build_services("python", "node", None) for s in g if s.label == "website")

    assert website.cwd.name == "frontend"
    assert (website.cwd / "index.html").is_file()
    assert (website.cwd / "vite.config.js").is_file()


def test_display_width_counts_block_characters_as_two():
    assert display_width("3/5 ready") == 9
    assert display_width("██") == 4


def test_status_line_names_every_service_still_starting(monkeypatch):
    monkeypatch.setattr(start.shutil, "get_terminal_size", lambda fallback: start.os.terminal_size((120, 30)))
    services = [service for group in build_services("python", "node", None) for service in group]
    panel = StatusPanel(Console(colour=False), services)
    for label in ("rcrc", "network", "accounts", "website"):
        panel.state[label] = ("starting", start.time.monotonic())
    panel.state["rcrc"] = ("ready", start.time.monotonic())

    line = panel._status_line()

    assert "1/4 ready" in line
    assert "waiting for Network map server, Accounts server, Website" in line


def test_status_line_shortens_the_list_on_a_narrow_terminal(monkeypatch):
    monkeypatch.setattr(start.shutil, "get_terminal_size", lambda fallback: start.os.terminal_size((80, 30)))
    services = [service for group in build_services("python", "node", None) for service in group]
    panel = StatusPanel(Console(colour=False), services)
    for label in ("network", "accounts", "website"):
        panel.state[label] = ("starting", start.time.monotonic())

    line = panel._status_line()
    assert "waiting for Network map server +2 more" in line or "3 starting" in line
    assert start.display_width(line) <= 79


def test_refused_administrator_can_be_tried_again(monkeypatch):
    console = Console(colour=False)
    answers = iter([True, True])          # create it now? yes; try again? yes
    typed = iter(["Noura", "bad-email", "", "Noura", "noura.admin@ksu.edu.sa", ""])
    results = iter([1, 0])                # first attempt refused, second created
    commands = []
    monkeypatch.setattr(console, "ask", lambda question, default=True: next(answers))
    monkeypatch.setattr(console, "prompt", lambda question: next(typed))
    monkeypatch.setattr(
        start.subprocess, "run",
        lambda command, cwd: commands.append(command) or start.subprocess.CompletedProcess(command, next(results)),
    )

    assert offer_fixes(console, SetupCheck(fixable={"admin"}), "python") is True
    assert len(commands) == 2
    assert commands[1][-2:] == ["--email", "noura.admin@ksu.edu.sa"]


def test_server_errors_stay_visible_without_verbose():
    error = 'INFO:     127.0.0.1:5 - "POST /auth/login HTTP/1.1" 500 Internal Server Error'

    text, colour = tidy_line(error)

    assert text.endswith("500 Internal Server Error")
    assert colour == "31"


def test_declined_fix_prints_the_problems_once(monkeypatch):
    stream = io.StringIO()
    console = Console(colour=False, stream=stream)
    monkeypatch.setattr(start, "check_setup", lambda with_live: SetupCheck(problems=["No admin"], fixable={"admin"}))
    monkeypatch.setattr(start, "offer_fixes", lambda console, check, python: False)

    assert start.prepare(console, argparse.Namespace(no_live=True), "python") is None
    assert stream.getvalue().count("No admin") == 1


def test_ctrl_c_during_setup_cancels_cleanly(monkeypatch, capsys):
    def interrupted(console, args, python):
        raise KeyboardInterrupt

    monkeypatch.setattr(start, "prepare", interrupted)

    assert start.main(["--no-browser"]) == 130
    assert "Cancelled; nothing was started." in capsys.readouterr().out


def test_live_loop_requests_are_hidden_too():
    request = '2026-11-28 15:11:44,201 INFO HTTP Request: GET http://127.0.0.1:8002/health "HTTP/1.1 200 OK"'
    failed = '2026-11-28 15:11:44,201 INFO HTTP Request: GET http://127.0.0.1:8002/observations "HTTP/1.1 503 Service Unavailable"'

    assert tidy_line(request) == (None, None)
    assert tidy_line(request, verbose=True)[0] == request
    assert tidy_line(failed)[1] == "31"
    assert tidy_line("2026-11-28 15:15:06,760 INFO new chain RUN_LIVE_20260829T0245_R1445_S42")[0] is not None


def test_calibration_offset_is_left_out(setup_paths, monkeypatch):
    setup_paths["environ"] = {"JAADAH_REPLAY_OFFSET_WEEKS": "0"}

    check = check_setup(with_live=False, **setup_paths)

    assert check.problems == []
    assert "JAADAH_REPLAY_OFFSET_WEEKS=0 is set" in check.notes[0]

    captured = {}
    monkeypatch.setenv("JAADAH_REPLAY_OFFSET_WEEKS", "0")
    monkeypatch.setattr(start.subprocess, "Popen", lambda command, **kwargs: captured.update(kwargs) or _Done())
    monkeypatch.setattr(start.threading, "Thread", lambda **kwargs: _Done())
    start.Launcher(Console(colour=False, stream=io.StringIO())).start(
        build_services("python", "node", None)[0][0]
    )
    assert "JAADAH_REPLAY_OFFSET_WEEKS" not in captured["env"]


class _Done:
    stdout = ()

    def start(self):
        pass


def _feed(weeks_behind: int) -> dict:
    replay = datetime.now(timezone.utc) - timedelta(weeks=weeks_behind)
    return {"status": "ok", "source": "rcrc", "replay_time": replay.isoformat()}


def test_running_feed_on_its_port_is_reused(setup_paths, monkeypatch):
    monkeypatch.setattr(start, "port_in_use", lambda port: True)
    setup_paths.update(ports=(start.RCRC_PORT,), feed=_feed(13))

    check = check_setup(with_live=False, **setup_paths)

    assert check.problems == []
    assert check.reuse_feed is True
    assert len(check.notes) == 1
    assert "leaves it running" in check.notes[0]


def test_reused_feed_on_another_clock_is_named(setup_paths, monkeypatch):
    monkeypatch.setattr(start, "port_in_use", lambda port: True)
    setup_paths.update(ports=(start.RCRC_PORT,), feed=_feed(0))

    notes = check_setup(with_live=False, **setup_paths).notes

    assert "runs 0 weeks behind real time, not 13" in notes[1]


def test_something_else_on_the_feed_port_is_a_problem(setup_paths, monkeypatch):
    monkeypatch.setattr(start, "port_in_use", lambda port: True)
    setup_paths.update(ports=(start.RCRC_PORT,), feed=None)

    check = check_setup(with_live=False, **setup_paths)

    assert check.reuse_feed is False
    assert "Port 8002 is already in use" in check.problems[0]


def test_reused_feed_is_not_started_and_shows_in_the_summary():
    groups = build_services("python", "node", None, reuse_feed=True)
    services = [service for group in groups for service in group]

    assert "rcrc" not in {service.label for service in services}
    assert summary_rows(services, reuse_feed=True)[:2] == [
        ("Website", "http://localhost:5173"),
        ("RCRC traffic feed", "http://127.0.0.1:8002 (already running)"),
    ]


def test_missing_trends_history_is_a_note(setup_paths):
    setup_paths["trends_files"] = []

    check = check_setup(with_live=False, **setup_paths)

    assert check.problems == []
    assert "No traffic history has been built yet" in check.notes[0]
