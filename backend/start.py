"""
Start Jaadah with one command: the RCRC traffic feed, the network map
server, the accounts server, the website and the live update loop.

    python -m backend.start
    python -m backend.start --no-live     # without the live update loop

Run it from the repository root with the virtual environment active.
It first checks the one-time setup and says what is missing, offering to
fix what it can (npm ci, the administrator account), and loads the RCRC
report into the feed if that was never done. It then starts each service
once the one it needs answers, showing a live status panel, and when
everything is up prints the addresses and opens the website. After that,
the services' output follows in this terminal, each line labelled with
its service; request logs are hidden unless --verbose. Ctrl+C stops
everything.

If a service fails, the launcher shows its last lines and the error,
stops the others and exits with code 1.

An RCRC traffic feed already running on port 8002 (the nightly history
run starts one and leaves it running) is used as it is and left running
on Ctrl+C, so a history run using it is not cut off. The calibration
setting JAADAH_REPLAY_OFFSET_WEEKS is left out of what the launcher
starts, so the feed always runs on the 13-week demonstration clock. Colours and the redrawing panel
need a terminal; NO_COLOR=1 turns them off.

The live update loop needs SUMO. Without it, the launcher says so and
runs everything else; Current Traffic then shows no live results.

What stays manual: the one-time setup (virtual environment and
pip install, npm ci, create_admin) and the baseline run, which is a
one-off job rather than a service (simulation/scripts/run_baseline.py).
"""

import argparse
import errno
import importlib.util
import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import webbrowser
from collections import deque
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path

from backend.accounts.storage import DEFAULT_DATABASE as ACCOUNTS_DATABASE
from backend.accounts.storage import ROLE_ADMIN, STATUS_ACTIVE
from traffic_source.rcrc_replay.config import (
    OFFSET_WEEKS_VARIABLE,
    PRIVATE_DATA_DIR,
    RCRC_REPLAY_DATABASE_PATH,
    RCRC_REPORT_DIR,
    ReplayConfig,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_ROOT / "frontend"
VITE_SCRIPT = FRONTEND_DIR / "node_modules" / "vite" / "bin" / "vite.js"
# Built per computer by the nightly history run, ignored by git (docs/kpi_engine.md, 17.10)
TRENDS_FILES = "frontend/public/data/*/history/trends_*.json"
# The demonstration clock (13 weeks behind) that Current Traffic is meant to show
DEMO_OFFSET_WEEKS = ReplayConfig().offset_weeks

RCRC_PORT = 8002
NETWORK_PORT = 8001
ACCOUNTS_PORT = 8003
WEBSITE_PORT = 5173
WEBSITE_URL = f"http://localhost:{WEBSITE_PORT}"

# Imported by the servers; a missing one means the requirements are not installed
REQUIRED_PACKAGES = ("fastapi", "uvicorn", "pydantic", "pandas", "shapely", "argon2", "traci")

ADDRESS_IN_USE = {errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", errno.EADDRINUSE)}

POLL_S = 0.5
STOP_WAIT_S = 10.0
LABEL_WIDTH = 8


@dataclass(frozen=True)
class Service:
    """One process the launcher starts and watches."""

    label: str
    name: str
    command: tuple[str, ...]
    # Addresses to try for readiness; the service is ready when any answers
    health_urls: tuple[str, ...]
    ready_timeout_s: float
    port: int | None = None
    # A service that is not required may stop without stopping the rest
    required: bool = True
    # Where it runs: Vite serves the folder it is started in
    cwd: Path = REPO_ROOT


@dataclass
class SetupCheck:
    """What the setup check found: problems stop the start, notes do not."""

    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    report_to_load: Path | None = None
    # Problems the launcher can offer to fix: "npm", "admin"
    fixable: set[str] = field(default_factory=set)
    sumo_bin: str | None = None
    # An RCRC traffic feed already answering on its port (the nightly history
    # run starts one and leaves it running): used as it is, and left running
    reuse_feed: bool = False


def missing_packages(packages: tuple[str, ...] = REQUIRED_PACKAGES) -> list[str]:
    return [name for name in packages if importlib.util.find_spec(name) is None]


def port_in_use(port: int) -> bool:
    """
    True if the port cannot be taken on 127.0.0.1 (where uvicorn
    listens) or ::1 (where Node may listen on Windows). Binding answers
    at once; connecting to a closed port on Windows waits about 2 s.
    """

    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            probe = socket.socket(family, socket.SOCK_STREAM)
        except OSError:
            continue  # no IPv6 on this computer

        try:
            probe.bind((host, port))
        except OSError as error:
            # Other errors (no ::1 address, for one) say nothing about the port
            if error.errno in ADDRESS_IN_USE:
                return True
        finally:
            probe.close()

    return False


def report_loaded(database: Path = RCRC_REPLAY_DATABASE_PATH) -> bool:
    if not database.exists():
        return False

    try:
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
            return connection.execute("SELECT 1 FROM report WHERE id = 1").fetchone() is not None
    except sqlite3.Error:
        return False


def active_admin_exists(database: Path = ACCOUNTS_DATABASE) -> bool:
    if not database.exists():
        return False

    try:
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
            row = connection.execute(
                "SELECT 1 FROM accounts WHERE role = ? AND status = ? LIMIT 1",
                (ROLE_ADMIN, STATUS_ACTIVE),
            ).fetchone()
    except sqlite3.Error:
        return False

    return row is not None


def find_sumo(environ: dict[str, str] | None = None) -> str | None:
    """The sumo executable: on PATH, or in SUMO_HOME/bin."""

    environ = os.environ if environ is None else environ
    on_path = shutil.which("sumo")
    if on_path:
        return on_path

    sumo_home = environ.get("SUMO_HOME")
    if sumo_home:
        for name in ("sumo.exe", "sumo"):
            candidate = Path(sumo_home) / "bin" / name
            if candidate.is_file():
                return str(candidate)

    return None


def running_feed(url: str = f"http://127.0.0.1:{RCRC_PORT}/health") -> dict | None:
    """The /health answer of an RCRC traffic feed already running on its port, or None."""

    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=2) as response:
            health = json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None

    return health if health.get("source") == "rcrc" and health.get("status") == "ok" else None


def feed_offset_weeks(health: dict, now: datetime | None = None) -> int | None:
    """How many weeks behind real time a running feed's replay clock is, from its /health."""

    try:
        replay = datetime.fromisoformat(health["replay_time"])
    except (KeyError, TypeError, ValueError):
        return None

    now = datetime.now(timezone.utc) if now is None else now
    return round((now - replay).total_seconds() / (7 * 24 * 3600))


def check_setup(
    with_live: bool,
    private_dir: Path = PRIVATE_DATA_DIR,
    report_dir: Path = RCRC_REPORT_DIR,
    replay_database: Path = RCRC_REPLAY_DATABASE_PATH,
    accounts_database: Path = ACCOUNTS_DATABASE,
    vite_script: Path = VITE_SCRIPT,
    ports: tuple[int, ...] = (RCRC_PORT, NETWORK_PORT, ACCOUNTS_PORT, WEBSITE_PORT),
    node: str | None = "auto",
    sumo: str | None = "auto",
    packages: list[str] | None = None,
    environ: dict[str, str] | None = None,
    feed: dict | None | str = "auto",
    trends_files: list[Path] | None = None,
) -> SetupCheck:
    """Check everything the services need, and collect every problem at once."""

    check = SetupCheck()
    packages = missing_packages() if packages is None else packages
    node = shutil.which("node") if node == "auto" else node

    if packages:
        check.problems.append(
            f"Python packages are missing ({', '.join(packages)}). Activate the virtual "
            "environment (.\\.venv\\Scripts\\Activate.ps1 on Windows, "
            "source .venv/bin/activate on Mac) and run: python -m pip install -r requirements.txt"
        )

    if node is None:
        check.problems.append("Node.js is not on PATH. Install Node.js 22, then open a new terminal.")

    if not vite_script.is_file():
        check.problems.append("The website's packages are not installed. Run: cd frontend; npm ci")
        if node is not None:
            check.fixable.add("npm")

    if not private_dir.is_dir():
        check.problems.append(
            f"The private data folder is missing: {private_dir}. "
            "It sits next to the repository and holds the RCRC report."
        )
    elif not report_loaded(replay_database):
        reports = sorted(report_dir.glob("*.csv")) if report_dir.is_dir() else []

        if len(reports) == 1:
            check.report_to_load = reports[0]
        elif not reports:
            check.problems.append(f"No RCRC report was found in {report_dir}.")
        else:
            check.problems.append(
                f"{len(reports)} RCRC reports are in {report_dir}. Load the one to use once, "
                "then start again: python -m traffic_source.rcrc_replay.load <report.csv>"
            )

    if not active_admin_exists(accounts_database):
        check.problems.append(
            "There is no administrator account, so nobody can log in. Create one once: "
            'python -m backend.accounts.create_admin --name "Your Name" --email you.admin@ksu.edu.sa'
        )
        check.fixable.add("admin")

    environ = os.environ if environ is None else environ
    offset = environ.get(OFFSET_WEEKS_VARIABLE)
    if offset is not None and offset.strip():
        check.notes.append(
            f"{OFFSET_WEEKS_VARIABLE}={offset.strip()} is set in this terminal (it is for calibration). "
            f"The launcher leaves it out, so the feed uses the {DEMO_OFFSET_WEEKS}-week demonstration clock."
        )

    for port in ports:
        if not port_in_use(port):
            continue

        if port == RCRC_PORT:
            health = running_feed() if feed == "auto" else feed
            if health is not None:
                check.reuse_feed = True
                check.notes.append(
                    f"An RCRC traffic feed is already running on port {RCRC_PORT} (the nightly history "
                    "run starts one, and may be using it). The launcher uses it and leaves it running "
                    "when you stop."
                )
                weeks = feed_offset_weeks(health)
                if weeks is not None and weeks != DEMO_OFFSET_WEEKS:
                    check.notes.append(
                        f"That feed runs {weeks} weeks behind real time, not {DEMO_OFFSET_WEEKS}, so Current "
                        f"Traffic will show {health['replay_time'][:10]}. To fix it, close that feed's window "
                        f"and start again."
                    )
                continue

        check.problems.append(
            f"Port {port} is already in use. Jaadah may already be running in another "
            "terminal; otherwise close the program using it."
        )

    trends_files = sorted(REPO_ROOT.glob(TRENDS_FILES)) if trends_files is None else trends_files
    if not trends_files:
        check.notes.append(
            "No traffic history is built on this computer, so Traffic Patterns & Trends will say "
            '"No traffic history has been built yet". The nightly history run builds it '
            "(docs/kpi_engine.md, section 17.11)."
        )

    if with_live:
        check.sumo_bin = find_sumo() if sumo == "auto" else sumo
        if check.sumo_bin is None:
            check.notes.append(
                "SUMO was not found (not on PATH and no SUMO_HOME), so the live update loop "
                "will not run and Current Traffic will show no live results. "
                "Install SUMO to include it."
            )

    return check


def build_services(python: str, node: str, sumo_bin: str | None, reuse_feed: bool = False) -> list[list[Service]]:
    """
    The services in start order: each group starts once the group
    before it is ready. The network map server reads the RCRC feed while
    it starts, so the feed comes first; the live loop comes last so its
    first SUMO run does not slow the others down. A feed already running
    (reuse_feed) is not started.
    """

    def uvicorn(app: str, port: int) -> tuple[str, ...]:
        return (python, "-m", "uvicorn", app, "--host", "127.0.0.1", "--port", str(port))

    groups = [
        [
            Service(
                "rcrc",
                "RCRC traffic feed",
                uvicorn("traffic_source.rcrc_replay.server:app", RCRC_PORT),
                (f"http://127.0.0.1:{RCRC_PORT}/health",),
                60,
                RCRC_PORT,
            )
        ],
        [
            Service(
                "network",
                "Network map server",
                uvicorn("jaadah.network_congestion.server:app", NETWORK_PORT),
                (f"http://127.0.0.1:{NETWORK_PORT}/health",),
                180,
                NETWORK_PORT,
            ),
            Service(
                "accounts",
                "Accounts server",
                uvicorn("backend.accounts.server:app", ACCOUNTS_PORT),
                (f"http://127.0.0.1:{ACCOUNTS_PORT}/health",),
                60,
                ACCOUNTS_PORT,
            ),
            Service(
                "website",
                "Website",
                # Vite straight from node_modules: through npm.cmd, Ctrl+C on
                # Windows stops at "Terminate batch job (Y/N)?"
                (node, str(VITE_SCRIPT), "--port", str(WEBSITE_PORT), "--strictPort"),
                # Node may listen on IPv4 or IPv6 "localhost" (IPv6 on Windows)
                (f"http://127.0.0.1:{WEBSITE_PORT}/", f"http://[::1]:{WEBSITE_PORT}/"),
                90,
                WEBSITE_PORT,
                cwd=FRONTEND_DIR,
            ),
        ],
    ]

    if reuse_feed:
        groups.pop(0)

    if sumo_bin is not None:
        groups.append(
            [
                Service(
                    "live",
                    "Live update loop",
                    (python, "simulation/scripts/run_live.py", "--source", "rcrc", "--sumo-bin", sumo_bin),
                    (),
                    5,
                    required=False,
                )
            ]
        )

    return groups


# Local checks never go through a proxy (Windows can set one for the whole system)
LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def probe(service: Service) -> str | None:
    """
    None once one of the service's health addresses answers (the feed
    must also have its report); otherwise what the last attempt got,
    for the timeout message.
    """

    detail = "no answer"
    for url in service.health_urls:
        try:
            with LOCAL_OPENER.open(url, timeout=2) as response:
                if service.label != "rcrc":
                    return None
                status = json.loads(response.read()).get("status")
                if status == "ok":
                    return None
                detail = f"answered with status {status!r}"
        except urllib.error.HTTPError as error:
            detail = f"answered {error.code} {error.reason}"
        except (urllib.error.URLError, OSError, ValueError):
            continue

    return detail


# The look --------------------------------------------------------------------

BANNER = (
    "     ██╗ █████╗  █████╗ ██████╗  █████╗ ██╗  ██╗",
    "     ██║██╔══██╗██╔══██╗██╔══██╗██╔══██╗██║  ██║",
    "     ██║███████║███████║██║  ██║███████║███████║",
    "██   ██║██╔══██║██╔══██║██║  ██║██╔══██║██╔══██║",
    "╚█████╔╝██║  ██║██║  ██║██████╔╝██║  ██║██║  ██║",
    " ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝",
)
# One 256-colour shade per banner row, cyan to violet
BANNER_SHADES = ("38;5;51", "38;5;45", "38;5;39", "38;5;33", "38;5;63", "38;5;99")

FANCY = {
    "ok": "✓", "fail": "✗", "note": "!", "ask": "?", "bar": "│",
    "full": "█", "empty": "░", "dot": "·",
    "spinner": "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏",
    "box": "╭╮╰╯─│",
}
PLAIN = {
    "ok": "+", "fail": "x", "note": "!", "ask": "?", "bar": "|",
    "full": "#", "empty": ".", "dot": "-",
    "spinner": "|/-\\",
    "box": "++++-|",
}

LABEL_COLOURS = {"rcrc": "36", "network": "34", "accounts": "35", "website": "32", "live": "33"}

# uvicorn's level prefixes, dropped from the line and shown as a colour instead
UVICORN_LEVELS = (("INFO:", None), ("WARNING:", "33"), ("ERROR:", "31"), ("CRITICAL:", "31"))

# One request: in a server's access log, e.g. '127.0.0.1:5 - "GET /speeds HTTP/1.1" 200 OK',
# or made by the live loop (httpx), e.g. 'HTTP Request: GET http://127.0.0.1:8002/health "HTTP/1.1 200 OK"'
ACCESS_LOG = re.compile(
    r'"(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) \S+ HTTP/[\d.]+" (\d{3})'
    r'|HTTP Request: [A-Z]+ \S+ "HTTP/[\d.]+ (\d{3})'
)

# The last line of a Python traceback, e.g. "ValueError: ... Delete it and start again."
EXCEPTION_LINE = re.compile(r"^[A-Za-z_][\w.]*(?:Error|Exception): ")


def colour_supported(stream, environ: dict[str, str] | None = None) -> bool:
    """Colours only on a real terminal, unless NO_COLOR is set; switched on in older Windows consoles."""

    environ = os.environ if environ is None else environ
    if "NO_COLOR" in environ or not hasattr(stream, "isatty") or not stream.isatty():
        return False

    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                return False
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
        except (AttributeError, OSError):
            return False

    return True


def failure_reason(lines: list[str]) -> str | None:
    """The last exception line a service printed, or None."""

    for line in reversed(lines):
        if EXCEPTION_LINE.match(line.strip()):
            return line.strip()

    return None


def tidy_line(line: str, verbose: bool = False) -> tuple[str | None, str | None]:
    """
    A service's output line as (text, colour), or (None, None) to hide
    it. Blank lines are always hidden. Request logs are hidden unless
    verbose, except server errors (5xx), which are shown in red.
    """

    text = line.rstrip()
    if not text.strip():
        return None, None

    request = ACCESS_LOG.search(text)
    if request and int(request.group(1) or request.group(2)) >= 500:
        return text.removeprefix("INFO:").strip(), "31"
    if request and not verbose:
        return None, None

    for prefix, colour in UVICORN_LEVELS:
        if text.startswith(prefix):
            return text[len(prefix):].strip(), colour

    return text, None


def progress_bar(done: int, total: int, width: int, full: str, empty: str) -> str:
    filled = round(width * done / total) if total else width
    return full * filled + empty * (width - filled)


class Console:
    """Everything the launcher prints. live is True on a colour terminal, where the panel redraws in place."""

    def __init__(self, colour: bool | None = None, stream=None) -> None:
        stream = sys.stdout if stream is None else stream
        self.stream = stream
        self.colour = colour_supported(stream) if colour is None else colour
        self.live = self.colour
        self.lock = threading.Lock()

        try:
            "".join(FANCY.values()).encode(stream.encoding or "ascii")
            "".join(BANNER).encode(stream.encoding or "ascii")
            self.symbols = FANCY
        except (UnicodeEncodeError, LookupError):
            self.symbols = PLAIN

    def paint(self, text: str, code: str | None) -> str:
        return f"\033[{code}m{text}\033[0m" if self.colour and code else text

    def write(self, text: str = "") -> None:
        with self.lock:
            print(text, file=self.stream, flush=True)

    def banner(self) -> None:
        self.write()
        if self.symbols is FANCY:
            for row, shade in zip(BANNER, BANNER_SHADES):
                self.write("  " + self.paint(row, shade))
        else:
            self.write("  J A A D A H")
        dot = self.symbols["dot"]
        self.write("  " + self.paint(f"Traffic digital twin {dot} Riyadh", "2"))
        self.write()

    def heading(self, text: str) -> None:
        self.write()
        self.write("  " + self.paint(text.upper(), "1;38;5;45"))

    def ok(self, text: str) -> None:
        self.write(f"  {self.paint(self.symbols['ok'], '32')} {text}")

    def note(self, text: str) -> None:
        self.write(f"  {self.paint(self.symbols['note'], '33')} {self.paint(text, '33')}")

    def fail(self, text: str, reason: str | None = None) -> None:
        self.write()
        self.write(f"  {self.paint(self.symbols['fail'], '31')} {self.paint(text, '1;31')}")
        if reason:
            self.write(f"    {self.paint('Reason:', '1')} {reason}")

    def service_line(self, label: str, line: str, verbose: bool = False) -> None:
        text, colour = tidy_line(line, verbose)
        if text is None:
            return

        name = self.paint(f"{label:<{LABEL_WIDTH}}", LABEL_COLOURS.get(label))
        self.write(f"  {name} {self.paint(self.symbols['bar'], '2')} {self.paint(text, colour)}")

    def ask(self, question: str, default: bool = True) -> bool:
        """A yes/no question; without a person at the keyboard, the answer is no."""

        if not sys.stdin.isatty():
            return False

        hint = "Y/n" if default else "y/N"
        try:
            answer = input(f"  {self.paint(self.symbols['ask'], '1;36')} {question} {self.paint(hint, '2')} ")
        except EOFError:
            return False

        answer = answer.strip().lower()
        return default if not answer else answer in {"y", "yes"}

    def prompt(self, question: str) -> str:
        return input(f"    {question}: ").strip()

    def box(self, title: str, rows: list[tuple[str, str]], footer: str) -> None:
        """A rounded box: a title, aligned rows of (name, value), and a footer line."""

        top_left, top_right, bottom_left, bottom_right, line, side = self.symbols["box"]
        key_width = max(len(name) for name, _ in rows) + 2
        plain_rows = [f"{name:<{key_width}}{value}" for name, value in rows]
        width = max(len(title), len(footer), *(len(row) for row in plain_rows)) + 4

        def framed(plain: str, painted: str) -> str:
            edge = self.paint(side, "38;5;45")
            return f"  {edge}  {painted}{' ' * (width - 4 - len(plain))}  {edge}"

        edge = lambda text: self.paint(text, "38;5;45")  # noqa: E731
        self.write()
        self.write("  " + edge(top_left + line * width + top_right))
        self.write(framed(title, self.paint(title, "1;32")))
        self.write(framed("", ""))
        for (name, value), plain in zip(rows, plain_rows):
            colour = "1;36" if value.startswith("http://localhost") else "2"
            self.write(framed(plain, f"{name:<{key_width}}" + self.paint(value, colour)))
        self.write(framed("", ""))
        self.write(framed(footer, self.paint(footer, "2")))
        self.write("  " + edge(bottom_left + line * width + bottom_right))
        self.write()


def display_width(text: str) -> int:
    """
    Columns the text takes, counting wide and ambiguous-width characters
    (East Asian widths W, F and A; block characters such as the progress
    bar are A) as two, the most a terminal may give them.
    """

    return sum(2 if unicodedata.east_asian_width(char) in "WFA" else 1 for char in text)


class StatusPanel:
    """
    Startup progress. Each service gets a permanent line once it is
    ready or has failed. Under those lines, one status line (spinner,
    progress bar, the service being waited for) redraws in place, ten
    times a second.

    Only that one line is redrawn, with a carriage return: moving the
    cursor up over several lines does not work in every terminal (in VS
    Code on Windows it left a copy of the panel behind on every frame).
    The status line is kept narrower than the terminal, so it never wraps.
    """

    def __init__(self, console: Console, services: list[Service]) -> None:
        self.console = console
        self.services = {service.label: service for service in services}
        self.state = {service.label: ("waiting", None) for service in services}
        self.lock = threading.Lock()
        self.frame = 0
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def set(self, label: str, status: str) -> None:
        now = time.monotonic()
        with self.lock:
            _, started = self.state[label]
            if status == "starting":
                self.state[label] = (status, now)
                return
            self.state[label] = (status, started)

        took = now - started if started else None
        self._print(self._row(self.services[label], status, took))

    def run(self) -> None:
        if self.console.live:
            self.thread = threading.Thread(target=self._animate, daemon=True)
            self.thread.start()

    def finish(self) -> None:
        """Stop the animation and remove the status line; later calls do nothing."""

        self.stop_event.set()
        if self.thread is not None:
            self.thread.join()
            self.thread = None
            with self.console.lock:
                self.console.stream.write("\r\033[2K")
                self.console.stream.flush()

    def _print(self, line: str) -> None:
        with self.console.lock:
            if self.console.live:
                self.console.stream.write("\r\033[2K")
            self.console.stream.write(line + "\n")
            self.console.stream.flush()

    def _animate(self) -> None:
        while not self.stop_event.wait(0.1):
            self.frame += 1
            line = self._status_line()
            with self.console.lock:
                self.console.stream.write("\r\033[2K" + line)
                self.console.stream.flush()

    def _row(self, service: Service, status: str, took: float | None) -> str:
        paint, symbols = self.console.paint, self.console.symbols
        icon, colour = {
            "ready": (symbols["ok"], "32"),
            "running": (symbols["ok"], "32"),
            "failed": (symbols["fail"], "31"),
            "stopped": (symbols["note"], "33"),
        }[status]
        where = f":{service.port}" if service.port else ""
        timer = f"{took:.1f}s" if took is not None and status == "ready" else ""

        return (
            f"    {paint(icon, colour)} {service.name:<20} {paint(f'{status:<9}', colour)}"
            f"{paint(f'{where:<7}', '2')}{paint(f'{timer:>6}', '2')}"
        )

    def _status_line(self) -> str:
        paint, symbols = self.console.paint, self.console.symbols
        with self.lock:
            states = list(self.state.items())

        done = sum(1 for _, (status, _) in states if status in {"ready", "running"})
        starting = [(started, label) for label, (status, started) in states if status == "starting"]
        spinner = symbols["spinner"][self.frame % len(symbols["spinner"])]
        bar = progress_bar(done, len(states), 20, symbols["full"], symbols["empty"])
        head = f"    {spinner} {bar}  {done}/{len(states)} ready"

        tail = ""
        if starting:
            # Everything still starting, oldest first, with how long the oldest has taken
            order = list(self.services)
            starting.sort(key=lambda item: (item[0], order.index(item[1])))
            oldest = f"{time.monotonic() - starting[0][0]:.0f}s"
            names = [self.services[label].name for _, label in starting]
            dot = symbols["dot"]
            room = (shutil.get_terminal_size((80, 24)).columns or 80) - 1
            # The longest form that fits: every name, the first and a count, or just the count
            forms = [f"  {dot} waiting for {', '.join(names)} {oldest}"]
            if len(names) > 1:
                forms.append(f"  {dot} waiting for {names[0]} +{len(names) - 1} more {oldest}")
            forms.append(f"  {dot} {len(names)} starting {oldest}")
            tail = next((form for form in forms if display_width(head + form) <= room), "")

        return f"    {paint(spinner, '36')} {paint(bar, '38;5;45')}  {done}/{len(states)} ready" + paint(tail, "2")


# Running the services --------------------------------------------------------


class Launcher:
    """Start, watch and stop the services."""

    def __init__(self, console: Console, verbose: bool = False) -> None:
        self.console = console
        self.verbose = verbose
        self.running: list[tuple[Service, subprocess.Popen]] = []
        self.recent: dict[str, deque] = {}
        self.reported_exits: set[str] = set()
        # Output is kept quiet while the status panel is on screen, then streamed
        self.streaming = False
        self.panel: StatusPanel | None = None

    def _relay(self, service: Service, stream) -> None:
        for line in stream:
            self.recent[service.label].append(line.rstrip())
            if self.streaming:
                self.console.service_line(service.label, line, self.verbose)

    def start(self, service: Service) -> subprocess.Popen:
        environment = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        # Calibration's replay offset must not reach the demonstration (see check_setup)
        environment.pop(OFFSET_WEEKS_VARIABLE, None)
        process = subprocess.Popen(
            service.command,
            cwd=service.cwd,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.running.append((service, process))
        self.recent[service.label] = deque(maxlen=200)
        threading.Thread(target=self._relay, args=(service, process.stdout), daemon=True).start()
        if self.panel:
            self.panel.set(service.label, "starting")
        return process

    def reason(self, service: Service) -> str | None:
        # Give the relay thread a moment to pass on the last lines of a stopped process
        time.sleep(0.3)
        return failure_reason(list(self.recent.get(service.label, ())))

    def show_last_lines(self, service: Service, count: int = 12) -> None:
        """The end of a failed service's output, which stayed hidden behind the panel."""

        lines = [line for line in self.recent.get(service.label, ()) if tidy_line(line)[0] is not None]
        if not lines:
            return

        self.console.write()
        self.console.write("  " + self.console.paint(f"Last lines from {service.name}:", "2"))
        for line in lines[-count:]:
            self.console.service_line(service.label, line, verbose=True)

    def wait_ready(self, group: list[tuple[Service, subprocess.Popen]]) -> tuple[Service, str] | None:
        """Wait until every service in the group is ready; return (failed service, message), or None."""

        deadline = {service.label: time.monotonic() + service.ready_timeout_s for service, _ in group}
        waiting = list(group)

        while waiting:
            for service, process in list(waiting):
                code = process.poll()

                if not service.health_urls:
                    # No health address (the live loop): ready if it is still running after its wait
                    if code is not None:
                        waiting.remove((service, process))
                        self.panel.set(service.label, "stopped")
                    elif time.monotonic() >= deadline[service.label]:
                        waiting.remove((service, process))
                        self.panel.set(service.label, "running")
                    continue

                if code is not None:
                    self.panel.set(service.label, "failed")
                    return service, f"{service.name} stopped while starting (exit code {code})."

                detail = probe(service)
                if detail is None:
                    waiting.remove((service, process))
                    self.panel.set(service.label, "ready")
                elif time.monotonic() >= deadline[service.label]:
                    self.panel.set(service.label, "failed")
                    return service, (
                        f"{service.name} was not ready on port {service.port} "
                        f"within {service.ready_timeout_s:.0f} s ({detail})."
                    )

            time.sleep(POLL_S)

        return None

    def report_exit(self, service: Service, code: int) -> None:
        if service.label in self.reported_exits:
            return

        self.reported_exits.add(service.label)
        reason = self.reason(service)
        self.console.note(
            f"{service.name} stopped (exit code {code}); the other services keep running."
            + (f" Reason: {reason}" if reason else "")
        )

    def watch(self) -> tuple[Service, str]:
        """Block until a required service stops; return (that service, what happened)."""

        while True:
            for service, process in self.running:
                code = process.poll()
                if code is None:
                    continue
                if service.required:
                    return service, f"{service.name} stopped unexpectedly (exit code {code})."
                self.report_exit(service, code)

            time.sleep(POLL_S)

    def stop_all(self, interrupted: bool) -> None:
        """
        Stop every service, newest first. After Ctrl+C the terminal has
        already sent the interrupt to every service, so each gets a few
        seconds to stop on its own. A service still running is asked to
        stop (SIGINT on Mac; on Windows it is ended with its child
        processes), and killed if it is still running STOP_WAIT_S later.
        """

        self.streaming = False
        for service, process in reversed(self.running):
            if process.poll() is not None:
                continue

            if interrupted:
                try:
                    process.wait(timeout=5)
                    continue
                except subprocess.TimeoutExpired:
                    pass

            try:
                if os.name == "nt":
                    # With its children: terminate() would leave the live loop's SUMO run going
                    subprocess.run(
                        ("taskkill", "/PID", str(process.pid), "/T", "/F"),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                else:
                    # The live loop's SUMO run stops with it: subprocess.run kills its child
                    # when interrupted
                    process.send_signal(signal.SIGINT)
            except OSError:
                pass

            try:
                process.wait(timeout=STOP_WAIT_S)
            except subprocess.TimeoutExpired:
                self.console.note(f"{service.name} did not stop in time; killing it.")
                process.kill()
                process.wait()

    def fail(self, service: Service, message: str) -> int:
        self.show_last_lines(service)
        self.console.fail(message, self.reason(service))
        self.console.write("    Stopping everything.")
        self.stop_all(interrupted=False)
        return 1


# Setup fixes -----------------------------------------------------------------


def offer_fixes(console: Console, check: SetupCheck, python: str) -> bool:
    """
    Offer to fix what can be fixed from here (website packages, the
    administrator account). True if anything was fixed, so the check
    should run again.
    """

    fixed = False

    if "npm" in check.fixable and console.ask("Install the website's packages now (npm ci)?"):
        npm = shutil.which("npm")
        fixed |= npm is not None and subprocess.run((npm, "ci"), cwd=FRONTEND_DIR).returncode == 0

    if "admin" in check.fixable and console.ask("Create the administrator account now?"):
        # create_admin checks the name, emails and password rules and says what is wrong;
        # a refused attempt can be tried again here instead of starting over
        while True:
            name = console.prompt("Full name")
            email = console.prompt("Administrator email")
            console.write(console.paint(
                "    Administrators only manage accounts. To use the traffic pages, also create an\n"
                "    engineer account with the same password (a different email), or press Enter to skip.",
                "2",
            ))
            engineer = console.prompt("Engineer email")
            command = [python, "-m", "backend.accounts.create_admin", "--name", name, "--email", email]
            if engineer:
                command += ["--engineer-email", engineer]
            if subprocess.run(command, cwd=REPO_ROOT).returncode == 0:
                fixed = True
                break
            if not console.ask("The account was not created (the reason is above). Try again?"):
                break

    return fixed


def show_problems(console: Console, problems: list[str]) -> None:
    console.fail("Jaadah cannot start yet:")
    console.write()
    for number, problem in enumerate(problems, start=1):
        console.write(f"    {console.paint(f'{number}.', '1')} {problem}")
    console.write()


def load_report(console: Console, python: str, report: Path) -> bool:
    console.note(f"The RCRC report is not loaded yet; loading {report.name} (only needed once).")
    result = subprocess.run((python, "-m", "traffic_source.rcrc_replay.load", str(report)), cwd=REPO_ROOT)
    return result.returncode == 0


def summary_rows(services: list[Service], reuse_feed: bool = False) -> list[tuple[str, str]]:
    rows = [("RCRC traffic feed", f"http://127.0.0.1:{RCRC_PORT} (already running)")] if reuse_feed else []
    for service in services:
        if service.label == "website":
            rows.insert(0, (service.name, WEBSITE_URL))
        elif service.port:
            rows.append((service.name, f"http://127.0.0.1:{service.port}"))
        else:
            rows.append((service.name, "running"))
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start every Jaadah service in one terminal.")
    parser.add_argument("--no-live", action="store_true", help="Do not start the live update loop.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the website when it is ready.")
    parser.add_argument("--verbose", action="store_true", help="Also show every request the servers answer.")
    return parser.parse_args(argv)


def prepare(console: Console, args: argparse.Namespace, python: str) -> SetupCheck | None:
    """The setup check, its fixes and the report load; None if Jaadah cannot start."""

    console.heading("Checking the setup")
    check = check_setup(with_live=not args.no_live)

    if check.problems:
        show_problems(console, check.problems)
        if not (check.fixable and offer_fixes(console, check, python)):
            return None

        check = check_setup(with_live=not args.no_live)
        if check.problems:
            show_problems(console, check.problems)
            return None

    console.ok("Everything is set up")
    for note in check.notes:
        console.note(note)

    if check.report_to_load is not None and not load_report(console, python, check.report_to_load):
        console.fail("Loading the RCRC report failed; its output is above.")
        return None

    return check


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    console = Console()
    python = sys.executable

    console.banner()
    try:
        check = prepare(console, args, python)
    except (KeyboardInterrupt, EOFError):
        # Ctrl+C at a prompt, or during npm ci or the report load
        console.write()
        console.note("Cancelled; nothing was started.")
        return 130
    if check is None:
        return 1

    launcher = Launcher(console, verbose=args.verbose)
    groups = build_services(
        python, shutil.which("node"), None if args.no_live else check.sumo_bin, reuse_feed=check.reuse_feed
    )
    services = [service for group in groups for service in group]

    console.heading("Starting the services")
    console.write()
    panel = StatusPanel(console, services)
    launcher.panel = panel
    panel.run()

    try:
        for group in groups:
            started = [(service, launcher.start(service)) for service in group]
            failure = launcher.wait_ready(started)
            if failure:
                panel.finish()
                return launcher.fail(*failure)

        panel.finish()
        for service, process in launcher.running:
            if not service.required and process.poll() is not None:
                launcher.report_exit(service, process.returncode)

        console.box(
            f"{console.symbols['ok']} Jaadah is running",
            summary_rows(services, reuse_feed=check.reuse_feed),
            "Press Ctrl+C to stop everything.",
        )
        if not args.no_browser:
            webbrowser.open(WEBSITE_URL)

        console.heading("Live output")
        launcher.streaming = True
        return launcher.fail(*launcher.watch())

    except KeyboardInterrupt:
        panel.finish()
        console.write()
        console.write("  Stopping everything...")
        try:
            launcher.stop_all(interrupted=True)
        except KeyboardInterrupt:
            for _, process in launcher.running:
                process.kill()
        console.ok("Stopped. See you next time.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
