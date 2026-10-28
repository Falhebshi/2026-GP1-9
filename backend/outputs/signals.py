import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from jaadah.models.mappings import NetworkMappingConfig
from jaadah.models.signals import (
    MovementSignalState,
    SignalIndication,
)
from jaadah.sumo_demand.planner import demand_movement_ids


SUMO_SIGNAL_INDICATIONS = {
    "G": SignalIndication.GREEN,
    "g": SignalIndication.GREEN,
    "y": SignalIndication.YELLOW,
    "r": SignalIndication.RED,
}


@dataclass(frozen=True)
class SignalChange:
    """The movement signal indications from one moment of a run onwards."""

    simulation_time_s: float
    timestamp: datetime
    movement_states: list[MovementSignalState]


def find_signal_links(
    config: NetworkMappingConfig,
) -> dict[str, list[int]]:
    """
    Return the SUMO signal links of every signal-controlled movement
    that receives detector demand. Route variants that share these
    links (ramps and U-turns) are left out.
    """

    demand_movements = demand_movement_ids(config)

    return {
        movement.movement_id: [
            link
            for crossing in movement.signal_crossings
            for link in crossing.controlled_link_indices
        ]
        for movement in config.movement_mappings
        if movement.signal_controlled
        and movement.movement_id in demand_movements
    }


def indication_of(
    movement_id: str,
    letters: str,
) -> SignalIndication:
    """
    Return the indication of a movement from the SUMO state letters of
    its links. All its links must show the same indication.
    """

    unknown = sorted(set(letters) - SUMO_SIGNAL_INDICATIONS.keys())

    if unknown:
        raise ValueError(
            f"unknown SUMO signal state {', '.join(unknown)} "
            f"for {movement_id}"
        )

    indications = {
        SUMO_SIGNAL_INDICATIONS[letter]
        for letter in letters
    }

    if len(indications) != 1:
        raise ValueError(
            f"links of {movement_id} show different indications: "
            f"{letters}"
        )

    return indications.pop()


def read_signal_changes(
    tls_path: str | Path,
    tls_id: str,
    run_start: datetime,
    signal_links: dict[str, list[int]],
) -> list[SignalChange]:
    """
    Read a SUMO SaveTLSStates file and return the movement indications
    each time one of them changes. run_start is the real time of SUMO
    second 0.
    """

    changes: list[SignalChange] = []
    previous_states = None

    for _, element in ET.iterparse(
        tls_path,
        events=("end",),
    ):
        if element.tag == "tlsState" and element.get("id") == tls_id:
            state = element.get("state")
            movement_states = [
                MovementSignalState(
                    movement_id=movement_id,
                    indication=indication_of(
                        movement_id=movement_id,
                        letters="".join(state[link] for link in links),
                    ),
                )
                for movement_id, links in sorted(signal_links.items())
            ]

            if movement_states != previous_states:
                simulation_time_s = float(element.get("time"))
                changes.append(
                    SignalChange(
                        simulation_time_s=simulation_time_s,
                        timestamp=run_start + timedelta(
                            seconds=simulation_time_s
                        ),
                        movement_states=movement_states,
                    )
                )
                previous_states = movement_states

        element.clear()

    return changes


def check_one_indication_per_approach(
    changes: list[SignalChange],
    config: NetworkMappingConfig,
) -> None:
    """
    Raise a ValueError if the movements of one approach ever show
    different indications. The 3D view colours a whole approach with one
    indication, which is only correct while they all change together.
    """

    approach_of_movement = {
        movement.movement_id: movement.approach_id
        for movement in config.movement_mappings
    }

    for change in changes:
        indications: dict[str, set] = {}

        for state in change.movement_states:
            indications.setdefault(
                approach_of_movement[state.movement_id],
                set(),
            ).add(state.indication)

        mixed = sorted(
            approach_id
            for approach_id, values in indications.items()
            if len(values) > 1
        )

        if mixed:
            raise ValueError(
                f"approach {', '.join(mixed)} shows different indications "
                f"at second {change.simulation_time_s}"
            )
