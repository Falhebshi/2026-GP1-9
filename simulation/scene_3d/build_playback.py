"""
Build the 3D view's playback files from one SUMO run.

Usage (from the repository root):
    python simulation/scene_3d/build_playback.py <baseline run folder>

    python simulation/scene_3d/build_playback.py <run folder> \
        --run-id RUN_TEST --run-start 2026-10-20T07:45:00+03:00 \
        --duration-s 5400 --warm-up-s 900 --clearance-s 900

A baseline run folder is the one run_baseline.py writes: demand/ (the
manifest and demand files of the SUMO demand generation), run/raw/
(fcd.xml and tls_states.xml) and summary.json, which gives the run ID,
its times and its status, so no option is needed. Any other run folder
holds the same four files in one place and needs the options. FCD must
be written with geo positions and signals, and the signal states with
SaveTLSSwitchStates (or SaveTLSStates). The files are written to
frontend/public/data/<intersection>/<scenario>/.

A run that did not complete (status in summary.json, or the file given
with --run-result) gets only run.json, with status "failed" and the
runner's error, so the view shows the failure instead of a partial run.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import sumolib
from shapely.geometry import LineString, Point


SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parents[1]

sys.path.insert(0, str(REPO_ROOT))

from backend.outputs.playback import (  # noqa: E402
    build_failed_run_index,
    build_run_index,
    pack_signal_changes,
    pack_vehicle_intervals,
    write_failed_run,
    write_playback,
)
from backend.outputs.signals import (  # noqa: E402
    check_one_indication_per_approach,
    find_signal_links,
    read_signal_changes,
)
from backend.outputs.vehicles import (  # noqa: E402
    edge_of_lane,
    load_vehicle_movements,
    read_vehicle_states,
)
from jaadah.mapping.loader import load_network_mappings  # noqa: E402
from jaadah.models.outputs import VehicleState  # noqa: E402
from tunnel import TunnelModel  # noqa: E402


# Project data paths
NETWORK_PATH = (
    REPO_ROOT
    / "data"
    / "processed"
    / "road_network"
    / "jaadah_study_area.net.xml"
)

OSM_PATH = (
    REPO_ROOT
    / "data"
    / "raw"
    / "road_network"
    / "jaadah_study_area.osm"
)

MAPPING_PATH = (
    REPO_ROOT
    / "data"
    / "processed"
    / "road_network"
    / "network_mappings.json"
)

# Length of the vehicles of the SUMO demand generation, in metres. SUMO
# gives the front bumper, so a car leaving the tunnel is still partly
# under the roof until it has driven one car length further.
CAR_LENGTH_M = 5.0

# The tunnel mouths are at an angle to the road, so a front or back corner
# of a car meets the roof edge before the middle of its bumper does. The
# car is hidden this many metres early and shown this many metres late.
ROOF_MARGIN_M = 2.0

FRONTEND_DATA_DIR = (
    REPO_ROOT
    / "frontend"
    / "public"
    / "data"
)


class UnderpassHeight:
    """
    Height of a car relative to street level, from the underpass model
    in tunnel.py. A display assumption: SUMO's network is flat.
    """

    def __init__(
        self,
        network_path: Path = NETWORK_PATH,
        osm_path: Path = OSM_PATH,
    ) -> None:
        self.net = sumolib.net.readNet(
            str(network_path),
            withInternal=True,
        )
        self.tunnel = TunnelModel(
            self.net,
            str(osm_path),
        )
        self.mainline = set(self.tunnel.edge_axis)
        self.mainline_nodes = {
            node.getID()
            for node in self.net.getNodes()
            if self.is_mainline_node(node)
        }

    def is_mainline_node(
        self,
        node,
    ) -> bool:
        """True when every road at a junction is an underpass road."""

        edges = [
            edge.getID()
            for edge in node.getIncoming() + node.getOutgoing()
            if not edge.isSpecial()
        ]

        return bool(edges) and all(
            edge in self.mainline
            for edge in edges
        )

    def underpass_edge(
        self,
        state: VehicleState,
    ) -> tuple[str, float, float] | None:
        """
        Return the underpass road a car is on and its SUMO x, y, or None
        when the car is not on an underpass road.
        """

        edge_id = edge_of_lane(state.sumo_lane_id)
        node_id = edge_id[1:].rsplit("_", 1)[0]

        if edge_id not in self.mainline and not (
            edge_id.startswith(":") and node_id in self.mainline_nodes
        ):
            return None

        x, y = self.net.convertLonLat2XY(
            state.longitude,
            state.latitude,
        )

        if edge_id not in self.mainline:
            edge_id = self.nearest_underpass_edge(x, y)

        return edge_id, x, y

    def __call__(
        self,
        state: VehicleState,
    ) -> float:
        found = self.underpass_edge(state)

        if found is None:
            return 0.0

        return self.tunnel.z(*found)

    def covered(
        self,
        state: VehicleState,
    ) -> bool:
        """True when a car is under the tunnel roof."""

        found = self.underpass_edge(state)

        return found is not None and self.tunnel.covered(*found)


    def nearest_underpass_edge(
        self,
        x: float,
        y: float,
    ) -> str:
        """Return the underpass road closest to a point."""

        point = Point(x, y)

        return min(
            self.mainline,
            key=lambda edge: LineString(
                self.net.getEdge(edge).getShape()
            ).distance(point),
        )

    def roof_crossing_time(
        self,
        start: list[float],
        end: list[float],
        start_s: float,
        end_s: float,
    ) -> float:
        """
        Return when a car between two samples, one under the roof and
        one outside it, passes the roof edge. The point is found on the
        straight line between the samples by halving the distance twelve
        times, to within a few millimetres.
        """

        a = self.net.convertLonLat2XY(*start)
        b = self.net.convertLonLat2XY(*end)
        edge_id = self.nearest_underpass_edge(*b)
        start_covered = self.tunnel.covered(edge_id, *a)
        low, high = 0.0, 1.0

        for _ in range(12):
            middle = (low + high) / 2
            x = a[0] + (b[0] - a[0]) * middle
            y = a[1] + (b[1] - a[1]) * middle

            if self.tunnel.covered(edge_id, x, y) == start_covered:
                low = middle
            else:
                high = middle

        return round(start_s + (end_s - start_s) * high, 2)

    def refine_hidden_spans(
        self,
        payloads: dict[str, dict],
    ) -> None:
        """
        Move the start and end of every hidden span from the first and
        last sample under the roof to the moments the car passes the
        roof edge: it disappears when its front reaches the entrance and
        appears when its back has left the exit, with ROOF_MARGIN_M to
        spare.
        """

        for payload in payloads.values():
            for trip in payload["trips"]:
                times = trip["timestamps"]
                path = trip["path"]

                for span in trip.get("hidden_spans", []):
                    first = times.index(span[0])
                    last = times.index(span[1])

                    if first > 0:
                        front_in_s = self.roof_crossing_time(
                            start=path[first - 1],
                            end=path[first],
                            start_s=times[first - 1],
                            end_s=times[first],
                        )
                        speed = max(trip["speeds"][first - 1], 1.0)
                        span[0] = round(
                            front_in_s - ROOF_MARGIN_M / speed,
                            2,
                        )

                    if last < len(times) - 1:
                        front_out_s = self.roof_crossing_time(
                            start=path[last],
                            end=path[last + 1],
                            start_s=times[last],
                            end_s=times[last + 1],
                        )
                        speed = max(trip["speeds"][last + 1], 1.0)
                        span[1] = round(
                            front_out_s
                            + (CAR_LENGTH_M + ROOF_MARGIN_M) / speed,
                            2,
                        )


def only_file(
    folder: Path,
    pattern: str,
) -> Path:
    """Return the one file in folder that matches pattern."""

    matches = sorted(folder.glob(pattern))

    if len(matches) != 1:
        raise FileNotFoundError(
            f"expected one {pattern} in {folder}, found {len(matches)}"
        )

    return matches[0]


def find_run_files(
    run_dir: Path,
) -> dict[str, Path]:
    """
    Return the SUMO outputs and the demand files of a run: from a
    baseline run folder (demand/ and run/raw/) or from one folder.
    """

    raw_dir = run_dir / "run" / "raw"
    demand_dir = run_dir / "demand"

    if not raw_dir.is_dir():
        raw_dir = run_dir
        demand_dir = run_dir

    return {
        "fcd": raw_dir / "fcd.xml",
        "tls_states": raw_dir / "tls_states.xml",
        "manifest": only_file(
            folder=demand_dir,
            pattern="*manifest.json",
        ),
        "demand": only_file(
            folder=demand_dir,
            pattern="*demand.json",
        ),
    }


def read_run_window(
    summary_path: Path,
) -> dict:
    """
    Return the run ID and the times of a baseline run from its
    summary.json: its start, length, warm-up and clearance.
    """

    with summary_path.open(
        encoding="utf-8",
    ) as file:
        summary = json.load(file)

    window = summary["run_window"]
    start = datetime.fromisoformat(window["start"])
    analysis_start = datetime.fromisoformat(window["analysis_start"])
    analysis_end = datetime.fromisoformat(window["analysis_end"])
    end = datetime.fromisoformat(window["end"])

    return {
        "run_id": summary["run_id"],
        "run_start": start,
        "duration_s": int(window["duration_s"]),
        "warm_up_s": int((analysis_start - start).total_seconds()),
        "clearance_s": int((end - analysis_end).total_seconds()),
    }


def read_run_result(
    path: Path,
) -> tuple[str, str | None]:
    """
    Return the status ("completed" or "failed") and the error of a run
    from the result the scenario runner saved (its "execution" part).
    """

    with path.open(
        encoding="utf-8",
    ) as file:
        execution = json.load(file)["execution"]

    return execution["status"], execution.get("error")


def write_failed_playback(
    run_id: str,
    run_start: datetime,
    scenario: str,
    failure_reason: str,
) -> Path:
    """Write run.json of a failed run, so the view shows the failure."""

    config = load_network_mappings(MAPPING_PATH)
    intersection_id = config.intersection_mapping.intersection_id
    output_dir = FRONTEND_DATA_DIR / intersection_id / scenario

    write_failed_run(
        output_dir=output_dir,
        run_index=build_failed_run_index(
            run_id=run_id,
            intersection_id=intersection_id,
            scenario=scenario,
            run_start=run_start,
            failure_reason=failure_reason,
        ),
    )

    print(f"run.json: {run_id} failed: {failure_reason}")

    return output_dir


def build_playback(
    run_dir: Path,
    run_id: str,
    run_start: datetime,
    duration_s: int,
    warm_up_s: int,
    clearance_s: int,
    scenario: str,
    is_test: bool = False,
) -> Path:
    """
    Convert one run folder into the 3D view's playback files. is_test
    marks a test run (made-up demand) in run.json.
    """

    config = load_network_mappings(MAPPING_PATH)
    intersection_id = config.intersection_mapping.intersection_id

    files = find_run_files(
        run_dir=run_dir,
    )
    vehicle_movements = load_vehicle_movements(
        manifest_path=files["manifest"],
        demand_path=files["demand"],
    )
    run_index = build_run_index(
        run_id=run_id,
        intersection_id=intersection_id,
        scenario=scenario,
        run_start=run_start,
        duration_s=duration_s,
        warm_up_s=warm_up_s,
        clearance_s=clearance_s,
        is_test=is_test,
    )
    underpass = UnderpassHeight()
    vehicle_payloads = pack_vehicle_intervals(
        states=read_vehicle_states(
            fcd_path=files["fcd"],
            run_id=run_id,
            run_start=run_start,
            vehicle_movements=vehicle_movements,
        ),
        intervals=run_index["intervals"],
        height_of=underpass,
        covered_of=underpass.covered,
    )
    underpass.refine_hidden_spans(vehicle_payloads)
    signal_changes = read_signal_changes(
        tls_path=files["tls_states"],
        tls_id=config.intersection_mapping.sumo_tls_id,
        run_start=run_start,
        signal_links=find_signal_links(config),
    )
    check_one_indication_per_approach(
        changes=signal_changes,
        config=config,
    )
    signal_payload = pack_signal_changes(
        run_id=run_id,
        changes=signal_changes,
    )

    output_dir = FRONTEND_DATA_DIR / intersection_id / scenario
    write_playback(
        output_dir=output_dir,
        run_index=run_index,
        vehicle_payloads=vehicle_payloads,
        signal_payload=signal_payload,
    )

    for name, payload in vehicle_payloads.items():
        trips = payload["trips"]
        covered = sum(
            1
            for trip in trips
            if "hidden_spans" in trip
        )
        print(
            f"{name}: {len(trips)} cars, {covered} under the tunnel roof"
        )

    print(
        f"signals.json: {len(signal_payload['changes'])} changes"
    )

    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__.strip().splitlines()[0],
    )
    parser.add_argument(
        "run_dir",
        type=Path,
    )
    parser.add_argument(
        "--run-id",
        help="default: from the run folder's summary.json",
    )
    parser.add_argument(
        "--run-start",
        type=datetime.fromisoformat,
        help="real time of SUMO second 0, e.g. 2026-10-20T07:45:00+03:00; "
        "default: from summary.json",
    )
    parser.add_argument(
        "--duration-s",
        type=int,
        help="default: from summary.json",
    )
    parser.add_argument(
        "--warm-up-s",
        type=int,
        help="seconds before the analysis period; not shown in the view "
        "(default: from summary.json, else 900)",
    )
    parser.add_argument(
        "--clearance-s",
        type=int,
        help="seconds after the analysis period; not shown in the view "
        "(default: from summary.json, else 900)",
    )
    parser.add_argument(
        "--scenario",
        default="baseline",
    )
    parser.add_argument(
        "--run-result",
        type=Path,
        help="the result the scenario runner saved; default: the run "
        "folder's summary.json",
    )
    args = parser.parse_args()

    summary_path = args.run_dir / "summary.json"
    run = {
        "warm_up_s": 900,
        "clearance_s": 900,
    }

    if summary_path.is_file():
        run.update(
            read_run_window(
                summary_path=summary_path,
            )
        )

        if args.run_result is None:
            args.run_result = summary_path

    given = (
        "run_id",
        "run_start",
        "duration_s",
        "warm_up_s",
        "clearance_s",
    )

    for name in given:
        if getattr(args, name) is not None:
            run[name] = getattr(args, name)

    missing = [
        name
        for name in ("run_id", "run_start", "duration_s")
        if name not in run
    ]

    if missing:
        parser.error(
            "the run folder has no summary.json, so give "
            + ", ".join(f"--{name.replace('_', '-')}" for name in missing)
        )

    if args.run_result is not None:
        status, error = read_run_result(
            path=args.run_result,
        )

        if status != "completed":
            output_dir = write_failed_playback(
                run_id=run["run_id"],
                run_start=run["run_start"],
                scenario=args.scenario,
                failure_reason=error or "The simulation did not finish.",
            )
            print(f"Done: {output_dir.relative_to(REPO_ROOT)}")
            return

    output_dir = build_playback(
        run_dir=args.run_dir,
        run_id=run["run_id"],
        run_start=run["run_start"],
        duration_s=run["duration_s"],
        warm_up_s=run["warm_up_s"],
        clearance_s=run["clearance_s"],
        scenario=args.scenario,
    )

    print(f"Done: {output_dir.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
