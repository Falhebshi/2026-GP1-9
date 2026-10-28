"""
Build the SignalProgram of a run from the SUMO network file.

The KPI engine's HCM calculations and the SUMO run must use the same
greens, so the program is read from the traffic-light plan in the
network file that SUMO runs, never entered separately.

Rules applied, and why:

- Plan: the plan of the intersection's signal (the mapping's
  sumo_tls_id). Only a fixed-time ("static") plan is supported, the
  only control type Jaadah models.
- Steps: consecutive steps with the same state are one step, so a
  green written as two identical steps is one green.
- Phases: each step with a green (G) starts a phase; the yellow (y)
  steps after it are its yellow time and the all-red steps its all-red
  time. The plan must start with a green, so every yellow and all-red
  belongs to the green before it.
- Served movements: a movement is served by a phase when all of its
  signal links are green in the phase's green step. Only the analysed
  movements (those with MovementAttributes) are listed; ramps and
  U-turns have no KPIs and share their phases with analysed movements,
  so leaving them out changes no phase timing.
- Source: baseline_model, so the engine reports the signal timing as a
  modelled assumption.
- Overlaps: a movement that stays green from one phase into the next
  (including from the last phase into the first) would look like two
  separate greens, so its lost time would be counted twice and its HCM
  delay reported unavailable for the wrong reason. SignalProgram
  represents sequential, non-overlapping phases only, so such a plan is
  rejected. The study-area plan serves one approach at a time and ends
  every green with yellow and all-red, so it has no overlap.
- No guessing: a plan the engine cannot use correctly raises an error
  that lists every problem found: states other than G, y and r (such
  as a permitted green g), an overlap, a movement only partly green in
  a step, a green that serves no analysed movement, or an analysed
  signalised movement that is never green.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

from ..mapping.validator import network_checksum_matches
from ..models.mappings import NetworkMappingConfig
from ..models.network import MovementControl
from ..models.signals import (
    SignalControlType,
    SignalPhase,
    SignalProgram,
    SignalProgramSource,
)


SUPPORTED_STATES = {"G", "y", "r"}


class SignalProgramError(ValueError):
    """Raised when a usable SignalProgram cannot be built; lists every problem found."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("Cannot build the signal program:\n" + "\n".join(problems))


def build_signal_program(
    config: NetworkMappingConfig,
    network_path: str | Path,
    *,
    scenario_id: str,
    signal_program_id: str,
    program_id: str | None = None,
) -> SignalProgram:
    """
    The SignalProgram of the intersection's signal plan in the network file.

    program_id selects one plan when the signal has several; with one
    plan it may be left out.
    """

    path = Path(network_path)
    content = path.read_bytes()
    if not network_checksum_matches(content, config.network.sha256):
        raise SignalProgramError(["SUMO network SHA-256 does not match the mapping configuration"])

    tls_id = config.intersection_mapping.sumo_tls_id
    if not tls_id:
        raise SignalProgramError(["the intersection mapping has no sumo_tls_id"])

    plan = _select_plan(ET.fromstring(content), tls_id, program_id)
    steps = _merge_identical_steps(
        [(float(step.get("duration")), step.get("state")) for step in plan.findall("phase")]
    )
    links = _analysed_signal_links(config)

    problems = _state_problems(steps)
    if problems:
        raise SignalProgramError(problems)

    problems = _overlap_problems(steps, links)
    if problems:
        raise SignalProgramError(problems)

    phases, problems = _group_phases(steps, links)
    never_green = sorted(set(links) - {m for phase in phases for m in phase.served_movement_ids})
    problems += [f"{movement_id}: never green in the plan" for movement_id in never_green]
    if problems:
        raise SignalProgramError(problems)

    return SignalProgram(
        signal_program_id=signal_program_id,
        scenario_id=scenario_id,
        control_type=SignalControlType.FIXED_TIME,
        cycle_length_s=sum(duration for duration, _ in steps),
        phases=phases,
        source=SignalProgramSource.BASELINE_MODEL,
    )


def _select_plan(root: ET.Element, tls_id: str, program_id: str | None) -> ET.Element:
    plans = [item for item in root.findall("tlLogic") if item.get("id") == tls_id]
    if program_id is not None:
        plans = [item for item in plans if item.get("programID") == program_id]

    if not plans:
        raise SignalProgramError([f"no signal plan found for {tls_id}"
                                  + ("" if program_id is None else f" program {program_id}")])
    if len(plans) > 1:
        found = sorted(str(item.get("programID")) for item in plans)
        raise SignalProgramError([f"{tls_id} has several plans {found}; choose one with program_id"])
    if plans[0].get("type") != "static":
        raise SignalProgramError([f"{tls_id}: only fixed-time (static) plans are supported, "
                                  f"not {plans[0].get('type')!r}"])
    return plans[0]


def _merge_identical_steps(steps: list[tuple[float, str]]) -> list[tuple[float, str]]:
    merged: list[tuple[float, str]] = []
    for duration, state in steps:
        if merged and merged[-1][1] == state:
            merged[-1] = (merged[-1][0] + duration, state)
        else:
            merged.append((duration, state))
    return merged


def _analysed_signal_links(config: NetworkMappingConfig) -> dict[str, list[int]]:
    """Signal link indices of each analysed signalised movement, in attribute order."""

    mappings = {item.movement_id: item for item in config.movement_mappings}
    return {
        item.movement_id: sorted({
            index
            for crossing in mappings[item.movement_id].signal_crossings
            for index in crossing.controlled_link_indices
        })
        for item in config.movement_attributes
        if item.control == MovementControl.SIGNALIZED
    }


def _state_problems(steps: list[tuple[float, str]]) -> list[str]:
    problems = []
    if not steps:
        return ["the signal plan has no steps"]
    for number, (_, state) in enumerate(steps, start=1):
        unsupported = sorted(set(state) - SUPPORTED_STATES)
        if unsupported:
            problems.append(f"step {number}: unsupported signal states {unsupported}; "
                            "only G, y and r are supported")
    if "G" not in steps[0][1]:
        problems.append("the plan must start with a green step")
    return problems


def _overlap_problems(
    steps: list[tuple[float, str]],
    links: dict[str, list[int]],
) -> list[str]:
    """
    Movements green in the step before a phase starts and in its first
    step, so their green continues from one phase into the next. The
    plan repeats, so the step before the first phase is the last step.
    """

    def green(movement_id, state):
        return all(index < len(state) and state[index] == "G" for index in links[movement_id])

    starts = [number for number, (_, state) in enumerate(steps) if "G" in state]
    problems = []
    for phase_number, start in enumerate(starts, start=1):
        previous = steps[start - 1][1]
        for movement_id in links:
            if green(movement_id, previous) and green(movement_id, steps[start][1]):
                before = len(starts) if phase_number == 1 else phase_number - 1
                problems.append(
                    f"{movement_id} stays green from phase {before} into phase "
                    f"{phase_number}; overlapping phases are not supported"
                )
    return problems


def _group_phases(
    steps: list[tuple[float, str]],
    links: dict[str, list[int]],
) -> tuple[list[SignalPhase], list[str]]:
    groups: list[dict] = []
    for duration, state in steps:
        if "G" in state:
            groups.append({"state": state, "green": duration, "yellow": 0.0, "all_red": 0.0})
        elif "y" in state:
            groups[-1]["yellow"] += duration
        else:
            groups[-1]["all_red"] += duration

    phases, problems = [], []
    for order, group in enumerate(groups):
        name = f"phase {order + 1}"
        served = []
        for movement_id, indices in links.items():
            green = [index < len(group["state"]) and group["state"][index] == "G" for index in indices]
            if all(green):
                served.append(movement_id)
            elif any(green):
                problems.append(f"{name}: {movement_id} is only partly green")
        if not served:
            problems.append(f"{name}: serves no analysed movement")
            continue
        phases.append(SignalPhase(
            phase_id=f"PHASE_{order + 1}",
            sequence_order=order,
            served_movement_ids=served,
            green_time_s=group["green"],
            yellow_time_s=group["yellow"],
            all_red_time_s=group["all_red"],
        ))
    return phases, problems
