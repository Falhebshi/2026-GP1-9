"""
Run the live update loop: simulate each 15-minute interval as the
traffic source delivers it, and publish the results for the Current
Traffic page (Issue #48, option A2; docs/live_update_loop.md).

Usage (from the repository root, with the source running):

    python simulation/scripts/run_live.py --source rcrc
    python simulation/scripts/run_live.py --source rcrc --once     # one pass, then exit

The page reads frontend/public/data/INT_001/live/. The chain's working
files (segments, saved states, demand) go to simulation/outputs/live/.
Both folders are ignored by git. Stop the loop with Ctrl+C; run.json
then says it was stopped, and the next start continues the chain if it
is less than two hours behind.

Exit codes: 0 stopped normally, 2 the loop could not start.
"""

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.ingestion.client import RcrcReplayClient, SyntheticTrafficClient  # noqa: E402
from simulation.live.chain import ChainError  # noqa: E402
from simulation.live.loop import POLL_S, LiveLoop, LoopSettings  # noqa: E402
from simulation.scripts.run_baseline import (  # noqa: E402
    DEFAULT_MAPPING,
    DEFAULT_NETWORK,
    DEFAULT_SOURCE_URLS,
    BaselineNotStarted,
    sumo_version,
)

DEFAULT_WORK_ROOT = PROJECT_ROOT / "simulation" / "outputs" / "live"
CLIENTS = {"rcrc": RcrcReplayClient, "synthetic": SyntheticTrafficClient}


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--source", choices=sorted(CLIENTS), default="rcrc")
    parser.add_argument("--source-url", help="Default: :8002 (rcrc), :8000 (synthetic)")
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--out", type=Path, help="Default: frontend/public/data/<intersection>/live/")
    parser.add_argument("--poll", type=float, default=POLL_S, help=f"Seconds between passes (default {POLL_S}).")
    parser.add_argument("--once", action="store_true", help="Run one pass and exit.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--net", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--sumo-bin", default="sumo")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        settings = LoopSettings(
            source=args.source,
            work_root=args.work_dir,
            mapping_path=args.mapping,
            network_path=args.net,
            seed=args.seed,
            sumo_bin=args.sumo_bin,
            sumo_version=sumo_version(args.sumo_bin),
            output_dir=args.out,
        )
        loop = LiveLoop(CLIENTS[args.source](args.source_url or DEFAULT_SOURCE_URLS[args.source]), settings)
    except (BaselineNotStarted, ChainError, ValueError, OSError) as exc:
        print(f"The live loop did not start: {exc}", file=sys.stderr)
        return 2

    if args.once:
        state = loop.step()
        print(f"{state['state']}: {state['message']}")
        return 0

    loop.run(poll_s=args.poll)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
