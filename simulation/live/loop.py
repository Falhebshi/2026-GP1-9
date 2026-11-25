"""
The live update loop (Issue #48, option A2): keeps the Current Traffic
page up to date by simulating each 15-minute interval as soon as the
traffic source delivers it.

Each pass of the loop asks the source how far its data goes, then runs
every update that is due, in order (simulation/live/update.py), and
publishes each one (simulation/live/publish.py). The page reads
frontend/public/data/<intersection>/live/. docs/live_update_loop.md
describes the whole design.

What the loop does, and why:

- Next interval: the chain's next interval is simulated once the source
  has delivered it. Missed intervals (the loop was stopped for a while)
  are caught up one by one, up to MAX_CATCH_UP intervals; after a longer
  stop the loop starts a new chain at the newest data instead, because
  catching up a whole day would take most of an hour and the page would
  wait for it.
- New day: an interval that starts at or after 03:00 of a new day starts
  a new chain, with its warm-up from 02:45 (simulation/live/chain.py).
- Detector outages: a silent detector is estimated however long it is
  silent (backend/demand/imputation.py), and the interval is marked as
  estimated, so the page shows "No detector data" for it (estimated
  results are not shown on Current Traffic). The chain goes on through
  the outage, so the queues after it are right. When an interval cannot
  be built at all (its time slot has too few earlier values to estimate
  from, or any other demand problem), the loop pauses: run.json says so and why, and the last
  results stay on the page. As soon as an interval can be built again,
  a new chain starts, because the old chain cannot continue across an
  interval that has no demand.
- New chain at the newest data: a chain started in the middle of a day
  (first start, after a pause or a long stop) warms up from the start of
  the day (02:45), as far back as the intervals can be built, and shows
  the newest interval at once. The warm-up runs SUMO only, so it takes a
  few minutes; it gives the chain the queues the day's chain would have.
- Cleaning up: the FCD of a segment is deleted once it is older than the
  45 minutes the KPIs and playback read; the last KEEP_STATES saved
  states are kept, so a segment can be rerun; trip information and
  signal states are small and kept for the chain. A chain's folder is
  deleted 24 hours after its last update; only chain folders
  (RUN_LIVE_* with a chain.json) are ever deleted.
"""

import json
import logging
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import httpx2

from jaadah.mapping.loader import load_network_mappings
from jaadah.sumo_demand.planner import compute_free_flow_times
from simulation.live.chain import (
    INTERVAL,
    RECORD_FILE as CHAIN_FILE,
    RIYADH,
    WARMUP_S,
    ChainError,
    ChainRecord,
    chain_day,
    check_lag,
    day_epoch,
    load_record,
    run_id_of,
    save_record,
)
from simulation.live.demand import (
    HISTORY_DAYS,
    build_interval_demand,
    estimated_interval,
    load_demand,
)
from simulation.live.publish import FCD_INTERVALS, LivePublisher, interval_summary
from simulation.live.segments import FCD_FILE, RAW_DIR, STATE_FILE
from simulation.live.update import run_update

log = logging.getLogger("jaadah.live")

ACTIVE_FILE = "active.json"
RUN_PREFIX = "RUN_LIVE_"
MAX_CATCH_UP = 8
MAX_FAILURES = 3
# A pass can run a whole day's intervals: a chain started during the day
# warms up from 03:00 (up to 96 intervals), plus a new chain and catching up.
MAX_STEPS_PER_PASS = 2 * 96 + 4
KEEP_STATES = 4
KEEP_CHAIN = timedelta(hours=24)
POLL_S = 10
# A chain started during the day warms up from the start of the day
# (02:45, as the day's chain), as far back as the intervals can be built,
# so it has the same queues the day's chain would have. Where an approach
# is over capacity, its queue builds up over the afternoon: no fixed
# warm-up length was enough at the workday evening peak, but warming up
# from 03:00 matches the day's chain by construction
# (docs/live_update_loop.md, 2.5). Warm-up intervals run SUMO only (no
# KPIs, no playback), so this takes a few minutes even late in the day.
# None means from the start of the day; a number limits the warm-up to
# that many intervals (the tests use 4, to stay quick).
RESTART_WARMUP_INTERVALS = None


@dataclass
class LoopSettings:
    """What the loop runs with; the defaults are those of the baseline runner."""

    source: str
    work_root: Path
    mapping_path: Path
    network_path: Path
    seed: int = 42
    step_length_s: float = 0.4
    sumo_bin: str = "sumo"
    sumo_version: str = "unknown"
    output_dir: Path | None = None
    history_days: int = HISTORY_DAYS
    restart_warmup_intervals: int | None = RESTART_WARMUP_INTERVALS


class LiveLoop:
    """One live loop: its chain, its source and where it publishes."""

    def __init__(self, client, settings: LoopSettings, now=None) -> None:
        self.client = client
        self.settings = settings
        self.now = now or (lambda: datetime.now(RIYADH))
        self.work_root = Path(settings.work_root)
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.mapping = load_network_mappings(settings.mapping_path, network_path=settings.network_path)
        self.free_flow_s = compute_free_flow_times(self.mapping, settings.network_path)
        check_lag(self.free_flow_s)
        self.publisher = LivePublisher(
            self.mapping, settings.mapping_path, settings.network_path, settings.output_dir,
        )
        self.record: ChainRecord | None = self._load_active()
        self.paused: dict | None = None
        self.failures = 0
        self._built: dict[datetime, object] = {}  # demand built while choosing a warm-up
        self.clock_offset_s = 0

    # ------------------------------------------------------------
    # chains
    # ------------------------------------------------------------

    def chain_dir(self, record: ChainRecord) -> Path:
        return self.work_root / record.run_id

    def _load_active(self) -> ChainRecord | None:
        """The chain the loop was running when it stopped, if it can be continued."""

        path = self.work_root / ACTIVE_FILE
        if not path.is_file():
            return None

        run_id = json.loads(path.read_text(encoding="utf-8"))["run_id"]
        try:
            record = load_record(self.work_root / run_id)
        except (ChainError, ValueError, KeyError, TypeError) as exc:
            log.warning("chain %s cannot be continued (%s); a new chain will start", run_id, exc)
            return None

        if record is None or not record.segments:
            return None
        last_state = self.work_root / run_id / record.segments[-1].folder / STATE_FILE
        if not last_state.is_file():
            log.warning("chain %s has no saved state; a new chain will start", run_id)
            return None
        return record

    def _new_chain(self, epoch: datetime, warmup_s: float = WARMUP_S, restart: bool = False) -> ChainRecord:
        shown_from = epoch + timedelta(seconds=warmup_s) if restart else None
        run_id = run_id_of(epoch, self.settings.seed, shown_from)
        record = ChainRecord(
            run_id=run_id,
            scenario_id=run_id.replace("RUN_LIVE_", "SCN_LIVE_").rsplit("_S", 1)[0],
            epoch=epoch.isoformat(),
            seed=self.settings.seed,
            step_length_s=self.settings.step_length_s,
            sumo_version=self.settings.sumo_version,
            network_version=self.mapping.network.version,
            mapping_version=self.mapping.mapping_version,
            started_at=self.now().isoformat(),
            warmup_s=warmup_s,
        )
        folder = self.chain_dir(record)
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        save_record(record, folder)
        (self.work_root / ACTIVE_FILE).write_text(
            json.dumps({"run_id": record.run_id}) + "\n", encoding="utf-8"
        )
        self.record = record
        log.info("new chain %s from %s, warm-up %d min", record.run_id, epoch.isoformat(), warmup_s // 60)
        return record

    @staticmethod
    def chain_day_of(record: ChainRecord):
        return chain_day(record.analysis_start_time)

    # ------------------------------------------------------------
    # one pass
    # ------------------------------------------------------------

    def step(self) -> dict:
        """
        Run every update that is due and return the loop's state, as
        published in run.json.
        """

        self._built = {}
        latest = self.client.fetch_latest_available_timestamp()
        self.clock_offset_s = self._clock_offset_s()
        if latest is None:
            return self._publish_state("waiting", "The traffic source has no data yet.")

        record = self.record
        if record is not None and not self.paused:
            behind = (latest - record.next_interval_end()) // INTERVAL + 1
            if behind > MAX_CATCH_UP:
                log.info("chain %s is %d intervals behind; starting at the newest data", record.run_id, behind)
                self.record = None

        for _ in range(MAX_STEPS_PER_PASS):
            record = self.record

            if record is None or self.paused:
                started = self._start_at_newest(latest)
                if not started:
                    return self._current_state()
                continue

            interval_end = record.next_interval_end()
            interval_day = chain_day(interval_end - INTERVAL)

            # A new day's interval starts the new day's chain. A chain's own
            # warm-up (its first segment) is always simulated: for the daily
            # chain it is 02:45-03:00, which belongs to the day before.
            in_warmup = interval_end <= record.analysis_start_time
            if not in_warmup and interval_day != self.chain_day_of(record):
                self._new_chain(day_epoch(interval_day))
                continue

            if interval_end > latest:
                return self._publish_state("running", "Up to date; the next interval is due at "
                                           f"{(interval_end).strftime('%H:%M')} (data time).")

            demand = self._build(interval_end, latest)
            if not demand.complete:
                self._pause(interval_end, demand.problems)
                continue

            self._update(record, demand)

        # Never reached in normal operation: a pass runs at most MAX_CATCH_UP
        # updates, a new chain and its warm-up. The bound keeps a logic error
        # from turning one pass into an endless loop.
        log.error("a pass did not finish within %d steps; the next pass goes on", MAX_STEPS_PER_PASS)
        return self._state("running", "Catching up.")

    def _clock_offset_s(self) -> int:
        """
        Seconds the source's clock is behind the real clock: 13 weeks for
        the replay source, 0 for a source on real time (no replay clock).
        The page uses it to play the newest traffic at the time it
        happened in data time.
        """

        fetch = getattr(self.client, "fetch_source_clock", None)
        source_now = fetch() if fetch else None
        if source_now is None:
            return 0
        return round((self.now() - source_now).total_seconds())

    def _build(self, interval_end: datetime, latest: datetime):
        built = self._built.pop(interval_end, None)
        if built is not None:
            return built
        return build_interval_demand(
            self.client, interval_end,
            source=self.settings.source,
            mapping_path=self.settings.mapping_path,
            available_until=latest,
            history_days=self.settings.history_days,
        )

    def _start_at_newest(self, latest: datetime) -> bool:
        """
        Start a chain at the newest data, if the newest interval's demand
        can be built. Returns False when it cannot (the loop stays paused
        or waiting).

        A chain that starts during the day starts on empty roads while
        the real ones are busy. So it warms up on the intervals before
        the newest one, back to the start of the day (02:45) or as many
        as RESTART_WARMUP_INTERVALS allows, stopping at the first one
        that cannot be built, and the newest interval is shown at once.
        When none of them can be built, the newest interval is the
        warm-up, and the page shows results from the next one. The pass
        then simulates the warm-up and the newest interval one by one, as
        a catch-up, with the demand built here.
        """

        if self.paused and latest <= datetime.fromisoformat(self.paused["since_interval_end"]):
            return False

        demand = self._build(latest, latest)
        if not demand.complete:
            if self.paused is None:
                self._pause(latest, demand.problems)
            return False

        limit = self.settings.restart_warmup_intervals
        if limit is None:
            day_start = day_epoch(chain_day(latest - INTERVAL))
            limit = int((latest - INTERVAL - day_start) / INTERVAL)

        self._built = {latest: demand}
        earlier = 0
        while earlier < limit:
            interval_end = latest - (earlier + 1) * INTERVAL
            built = self._build(interval_end, latest)
            if not built.complete:
                break
            self._built[interval_end] = built
            earlier += 1

        if earlier:
            self._new_chain(
                latest - (earlier + 1) * INTERVAL,
                warmup_s=earlier * INTERVAL.total_seconds(), restart=True,
            )
        else:
            self._new_chain(latest - INTERVAL, restart=True)
        self.paused = None
        return True

    def _update(self, record: ChainRecord, demand) -> None:
        folder = self.chain_dir(record)
        started = time.monotonic()
        if demand.rejected_rows:
            log.warning(
                "%s: %d source row(s) of the interval ending %s were rejected and left out; "
                "their detectors are estimated", record.run_id, demand.rejected_rows,
                demand.interval_end.strftime("%H:%M"),
            )
        result = run_update(
            record, folder, load_demand(folder, record.last_interval_end), demand.demands,
            estimated_interval(demand.demands, self.mapping),
            mapping=self.mapping,
            network_path=self.settings.network_path,
            free_flow_s=self.free_flow_s,
            sumo_bin=self.settings.sumo_bin,
        )
        interval_end = record.last_interval_end
        if interval_end > record.analysis_start_time:
            self.publisher.publish(
                record, folder, folder / "demand", result.generated,
                self._state("running", "Updated."),
            )
            # the interval before the newest is final now: what the page shows for it from here on
            final_start = interval_end - 2 * INTERVAL
            if final_start >= record.analysis_start_time:
                log.info(
                    "%s: KPIs %s (final): %s", record.run_id, final_start.strftime("%H:%M"),
                    interval_summary(self.publisher.output_dir, final_start),
                )
        self._clean(record)
        log.info(
            "%s: interval ending %s done in %.0f s%s", record.run_id, interval_end.strftime("%H:%M"),
            time.monotonic() - started, " (estimated)" if record.estimated_intervals
            and record.estimated_intervals[-1].interval_end == interval_end.isoformat() else "",
        )

    def _pause(self, interval_end: datetime, problems: list[str]) -> None:
        self.paused = {"since_interval_end": interval_end.isoformat(), "problems": problems[:10]}
        message = (
            f"Paused: the traffic for the interval ending {interval_end.strftime('%H:%M')} "
            "cannot be built. Detectors sent no data and it could not be estimated (too few "
            "earlier days of the same type to estimate from). Updates restart with the first "
            "interval that can be built."
        )
        log.warning("%s %s", message, "; ".join(problems[:3]))
        self._publish_state("paused", message, problems=problems[:10])

    # ------------------------------------------------------------
    # state and cleaning up
    # ------------------------------------------------------------

    def _state(self, state: str, message: str, **extra) -> dict:
        return {
            "state": state, "message": message, "updated_at": self.now().isoformat(),
            "clock_offset_s": self.clock_offset_s, **extra,
        }

    def _publish_state(self, state: str, message: str, **extra) -> dict:
        """
        Report the loop's state in the published run.json. While a new
        chain warms up, run.json still describes the previous chain: the
        state is then "starting", so the page does not show the previous
        chain's results as live.
        """

        payload = self._state(state, message, **extra)
        published = self.publisher.published_run_id()

        if (
            state == "running" and self.record is not None
            and published is not None and published != self.record.run_id
        ):
            payload = self._state(
                "starting",
                "A new run has started; its first results are due at "
                f"{self.record.next_interval_end().strftime('%H:%M')} (data time).",
            )

        self.publisher.publish_state(payload)
        return payload

    def _current_state(self) -> dict:
        if self.paused:
            return self._state("paused", "Paused until the traffic data returns.", **self.paused)
        return self._state("waiting", "Waiting for traffic data.")

    def stop(self, reason: str = "The live loop was stopped.") -> None:
        self._publish_state("stopped", reason)

    def _clean(self, record: ChainRecord) -> None:
        folder = self.chain_dir(record)
        segments = record.segments
        for item in segments[:-FCD_INTERVALS]:
            (folder / item.folder / RAW_DIR / FCD_FILE).unlink(missing_ok=True)
        for item in segments[:-KEEP_STATES]:
            (folder / item.folder / STATE_FILE).unlink(missing_ok=True)

        # Only the loop's own chain folders are deleted (RUN_LIVE_* with a
        # chain.json), so a --work-dir pointed at another folder, such as
        # simulation/outputs/, never loses the baseline runs.
        now = time.time()
        for path in self.work_root.iterdir():
            marker = path / CHAIN_FILE
            if (
                not path.is_dir() or path.name == record.run_id
                or not path.name.startswith(RUN_PREFIX) or not marker.is_file()
            ):
                continue
            if now - marker.stat().st_mtime > KEEP_CHAIN.total_seconds():
                shutil.rmtree(path, ignore_errors=True)

    # ------------------------------------------------------------
    # running
    # ------------------------------------------------------------

    def run(self, poll_s: float = POLL_S) -> None:
        """Run passes until stopped (Ctrl+C), POLL_S seconds apart."""

        try:
            while True:
                self.pass_once()
                time.sleep(poll_s)
        except KeyboardInterrupt:
            self.stop()

    def pass_once(self) -> dict | None:
        """
        One pass that never stops the twin: a failed update is logged and
        tried again at the next pass. After MAX_FAILURES in a row, or at
        once when the chain itself is inconsistent (ChainError), the loop
        starts a new chain at the newest data instead of retrying forever.
        A source that cannot be reached is not a failed update: the loop
        reports it and waits, keeping its chain.
        """

        try:
            state = self.step()
            self.failures = 0
            log.debug("state: %s", state["state"])
            return state
        except httpx2.HTTPError as exc:
            # The source is down or restarting: nothing was simulated, so
            # the chain is fine. It is not a failed update; the loop waits
            # and catches up when the source answers again.
            log.warning("the traffic source cannot be reached: %s", exc)
            self._publish_state("waiting", "The traffic source cannot be reached; the loop keeps trying.")
            return None
        except Exception as exc:  # one failed pass must not stop the twin
            self.failures += 1
            log.exception("the update failed (%d in a row)", self.failures)
            if isinstance(exc, ChainError) or self.failures >= MAX_FAILURES:
                log.warning("starting a new chain at the newest data")
                self.record = None
                self.paused = None
                self.failures = 0
            self._publish_state("running", "The last update failed and is being retried.")
            return None
