"""
The timeline and the saved record of one live chain (Issue #48, A2).

A chain is one day of the live twin: a run that starts with a 15-minute
warm-up and grows by one 15-minute interval each time the traffic source
delivers one. Each interval is simulated by one segment
(simulation/live/segments.py) that continues from the state the
previous segment saved.

Rules applied, and why:

- Second 0 of a chain is the start of its warm-up, as in every Jaadah
  run (jaadah/sumo_demand/planner.py), so the KPI engine and the
  playback builder read a chain exactly as they read a baseline run.
- A chain starts each day at 03:00 (warm-up from 02:45), the quietest
  hour, and after a pause (simulation/live/loop.py). The restart bounds
  the chain to one day, gives each day its own run ID and keeps a
  nightly point where the twin starts clean.
- A segment stops LAG_S before the end of the newest interval. The
  planner starts each vehicle earlier than the time it was counted at
  the stop line, by its free-flow travel time (up to about 57 s on this
  network), so some of the next interval's vehicles must start before
  the newest interval ends. Their demand is not known yet: stopping 60 s
  early lets them start on time in the next segment instead of late.
  Experiments 3-5 of #48 found that this removes every late vehicle.
  The newest interval is therefore simulated up to 60 s before its end,
  and its KPIs are provisional until the next update.
- The record of a chain (chain.json) is written whole, under a temporary
  name and then renamed, after every segment, so a loop that stops at
  any moment can continue from the last finished segment.
"""

import json
import os
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

INTERVAL = timedelta(minutes=15)
INTERVAL_S = 900
WARMUP_S = 900
LAG_S = 60
CHAIN_DAY_START = time(3, 0)
RIYADH = timezone(timedelta(hours=3))
RECORD_FILE = "chain.json"
RECORD_FORMAT_VERSION = 1


class ChainError(ValueError):
    """Raised when a chain cannot be planned or its record is invalid."""


# ============================================================
# TIMES
# ============================================================

def chain_day(moment: datetime) -> date:
    """
    The day a moment belongs to in the live twin: days run from 03:00 to
    03:00, so 01:00 on 20 Aug belongs to the chain of 19 Aug.
    """

    local = moment.astimezone(RIYADH)

    if local.time() < CHAIN_DAY_START:
        return local.date() - timedelta(days=1)

    return local.date()


def day_epoch(day: date) -> datetime:
    """Second 0 of a day's chain: 02:45, the start of its warm-up."""

    return datetime.combine(day, CHAIN_DAY_START, RIYADH) - timedelta(seconds=WARMUP_S)


def run_id_of(epoch: datetime, seed: int) -> str:
    """RUN_LIVE_<epoch>_S<seed>, e.g. RUN_LIVE_20260819T0245_S42."""

    return f"RUN_LIVE_{epoch.astimezone(RIYADH):%Y%m%dT%H%M}_S{seed}"


def segment_end_s(epoch: datetime, interval_end: datetime) -> float:
    """Where the segment for the interval ending at interval_end stops."""

    return (interval_end - epoch).total_seconds() - LAG_S


def check_lag(free_flow_s: dict[str, float]) -> None:
    """
    The lag must cover the longest departure shift; otherwise a vehicle of
    the next interval would have to start before its demand is known.
    """

    longest = max(free_flow_s.values(), default=0.0)

    if longest >= LAG_S:
        raise ChainError(
            f"the longest free-flow time to a stop line is {longest:.1f} s, not below "
            f"the {LAG_S} s lag: raise LAG_S in simulation/live/chain.py"
        )


def segment_route_xml(route_xml: bytes, begin_s: float, end_s: float) -> bytes:
    """
    The part of a run's route file that one segment inserts: the vehicle
    type, the routes and the vehicles departing after begin_s, up to and
    including end_s (the first segment's from 0, included).
    """

    root = ET.fromstring(route_xml)
    segment = ET.Element(root.tag, root.attrib)

    for element in root:
        if element.tag == "vehicle":
            depart_s = float(element.get("depart"))
            starts_here = depart_s > begin_s or (begin_s == 0 and depart_s >= 0)
            if not (starts_here and depart_s <= end_s):
                continue
        segment.append(element)

    ET.indent(segment, space="    ")
    return ET.tostring(segment, encoding="utf-8", xml_declaration=True) + b"\n"


# ============================================================
# THE RECORD OF A CHAIN
# ============================================================

@dataclass
class SegmentRecord:
    """One finished segment: the interval it simulated and where its files are."""

    number: int
    interval_end: str
    begin_s: float
    end_s: float
    folder: str


@dataclass
class EstimatedInterval:
    """An interval whose demand includes counts estimated for silent detectors."""

    interval_start: str
    interval_end: str
    approach_ids: list[str]
    methods: list[str]


@dataclass
class ChainRecord:
    """Everything needed to continue a chain, saved after every segment."""

    run_id: str
    scenario_id: str
    epoch: str
    seed: int
    step_length_s: float
    sumo_version: str
    network_version: str
    mapping_version: str
    started_at: str
    segments: list[SegmentRecord] = field(default_factory=list)
    estimated_intervals: list[EstimatedInterval] = field(default_factory=list)
    departures_sha256: str | None = None
    warmup_s: float = WARMUP_S
    format_version: int = RECORD_FORMAT_VERSION

    @property
    def epoch_time(self) -> datetime:
        return datetime.fromisoformat(self.epoch)

    @property
    def analysis_start_time(self) -> datetime:
        """The end of the warm-up: the first moment the page shows."""

        return self.epoch_time + timedelta(seconds=self.warmup_s)

    @property
    def last_interval_end(self) -> datetime | None:
        return datetime.fromisoformat(self.segments[-1].interval_end) if self.segments else None

    @property
    def last_end_s(self) -> float:
        return self.segments[-1].end_s if self.segments else 0.0

    def next_interval_end(self) -> datetime:
        """The end of the interval the next segment simulates."""

        last = self.last_interval_end
        return last + INTERVAL if last else self.epoch_time + INTERVAL


def save_record(record: ChainRecord, folder: str | Path) -> Path:
    """Write chain.json whole: under a temporary name, then renamed."""

    path = Path(folder) / RECORD_FILE
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(asdict(record), indent=1) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def load_record(folder: str | Path) -> ChainRecord | None:
    """The chain saved in folder, or None when there is none."""

    path = Path(folder) / RECORD_FILE

    if not path.is_file():
        return None

    data = json.loads(path.read_text(encoding="utf-8"))

    if data.get("format_version") != RECORD_FORMAT_VERSION:
        raise ChainError(f"{path}: format version {data.get('format_version')} is not {RECORD_FORMAT_VERSION}")

    data["segments"] = [SegmentRecord(**item) for item in data["segments"]]
    data["estimated_intervals"] = [EstimatedInterval(**item) for item in data["estimated_intervals"]]
    return ChainRecord(**data)
