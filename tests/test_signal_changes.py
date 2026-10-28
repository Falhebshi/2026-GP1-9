from datetime import datetime, timedelta

import pytest

from backend.outputs.intersections import REPO_ROOT
from backend.outputs.signals import (
    SignalChange,
    check_one_indication_per_approach,
    find_signal_links,
    indication_of,
    read_signal_changes,
)
from jaadah.mapping.loader import load_network_mappings
from jaadah.models.signals import (
    MovementSignalState,
    SignalIndication,
)


MAPPING_PATH = (
    REPO_ROOT
    / "data"
    / "processed"
    / "road_network"
    / "network_mappings.json"
)

RUN_START = datetime.fromisoformat("2026-10-20T07:45:00+03:00")

SIGNAL_LINKS = {
    "MOV_A": [0, 1],
    "MOV_B": [2],
}


def make_tls_state(
    time: str,
    state: str,
    tls_id: str = "TLS_TEST",
) -> str:
    """Create one line of a SUMO SaveTLSStates file."""

    return (
        f'<tlsState time="{time}" id="{tls_id}" programID="0" '
        f'phase="0" state="{state}"/>'
    )


def write_tls_states(
    tmp_path,
    lines: list[str],
):
    """Write a SUMO SaveTLSStates file."""

    path = tmp_path / "tls_states.xml"
    path.write_text(
        "<tlsStates>" + "".join(lines) + "</tlsStates>",
        encoding="utf-8",
    )

    return path


def read_changes(
    tls_path,
):
    """Read the signal changes of TLS_TEST for MOV_A and MOV_B."""

    return read_signal_changes(
        tls_path=tls_path,
        tls_id="TLS_TEST",
        run_start=RUN_START,
        signal_links=SIGNAL_LINKS,
    )


def indications(
    change,
) -> dict[str, str]:
    """Return the indication of every movement of one signal change."""

    return {
        state.movement_id: state.indication.value
        for state in change.movement_states
    }


def test_signal_links_are_found_for_demand_movements() -> None:
    config = load_network_mappings(MAPPING_PATH)

    assert find_signal_links(config) == {
        "MOV_E_W": [0, 1, 2],
        "MOV_E_S": [3, 4, 5],
        "MOV_S_W": [6, 7, 8],
        "MOV_W_E": [9, 10, 11],
        "MOV_W_N": [12, 13],
        "MOV_N_E": [14, 15, 16],
    }


def test_sumo_letters_become_indications() -> None:
    assert indication_of(
        movement_id="MOV_A",
        letters="GGG",
    ) == SignalIndication.GREEN
    assert indication_of(
        movement_id="MOV_A",
        letters="ggg",
    ) == SignalIndication.GREEN
    assert indication_of(
        movement_id="MOV_A",
        letters="yyy",
    ) == SignalIndication.YELLOW
    assert indication_of(
        movement_id="MOV_A",
        letters="rr",
    ) == SignalIndication.RED


def test_unknown_sumo_letter_is_refused() -> None:
    with pytest.raises(
        ValueError,
        match="unknown SUMO signal state o for MOV_A",
    ):
        indication_of(
            movement_id="MOV_A",
            letters="oo",
        )


def test_links_with_different_indications_are_refused() -> None:
    with pytest.raises(
        ValueError,
        match="links of MOV_A show different indications: GGr",
    ):
        indication_of(
            movement_id="MOV_A",
            letters="GGr",
        )


def test_only_changes_are_kept(tmp_path) -> None:
    changes = read_changes(
        write_tls_states(
            tmp_path=tmp_path,
            lines=[
                make_tls_state(time="0.00", state="GGr"),
                make_tls_state(time="0.20", state="GGr"),
                make_tls_state(time="40.00", state="yyr"),
                make_tls_state(time="40.20", state="yyr"),
            ],
        )
    )

    assert [
        change.simulation_time_s
        for change in changes
    ] == [0.0, 40.0]
    assert [
        indications(change)
        for change in changes
    ] == [
        {"MOV_A": "green", "MOV_B": "red"},
        {"MOV_A": "yellow", "MOV_B": "red"},
    ]


def test_change_timestamp_is_run_start_plus_simulation_time(
    tmp_path,
) -> None:
    changes = read_changes(
        write_tls_states(
            tmp_path=tmp_path,
            lines=[
                make_tls_state(time="40.00", state="yyr"),
            ],
        )
    )

    assert changes[0].timestamp == datetime.fromisoformat(
        "2026-10-20T07:45:40+03:00"
    )


def test_other_traffic_lights_are_ignored(tmp_path) -> None:
    changes = read_changes(
        write_tls_states(
            tmp_path=tmp_path,
            lines=[
                make_tls_state(time="0.00", state="GGr"),
                make_tls_state(
                    time="0.00",
                    state="rrr",
                    tls_id="TLS_OTHER",
                ),
            ],
        )
    )

    assert len(changes) == 1
    assert indications(changes[0]) == {
        "MOV_A": "green",
        "MOV_B": "red",
    }


def make_change(
    simulation_time_s: float,
    indications: dict[str, SignalIndication],
) -> SignalChange:
    """Create one signal change for approach checks."""

    return SignalChange(
        simulation_time_s=simulation_time_s,
        timestamp=RUN_START + timedelta(seconds=simulation_time_s),
        movement_states=[
            MovementSignalState(
                movement_id=movement_id,
                indication=indication,
            )
            for movement_id, indication in indications.items()
        ],
    )


def test_approach_with_one_indication_is_accepted() -> None:
    check_one_indication_per_approach(
        changes=[
            make_change(
                simulation_time_s=0.0,
                indications={
                    "MOV_E_W": SignalIndication.GREEN,
                    "MOV_E_S": SignalIndication.GREEN,
                    "MOV_S_W": SignalIndication.RED,
                },
            ),
        ],
        config=load_network_mappings(MAPPING_PATH),
    )


def test_approach_with_two_indications_is_refused() -> None:
    with pytest.raises(
        ValueError,
        match="approach APP_E shows different indications at second 40",
    ):
        check_one_indication_per_approach(
            changes=[
                make_change(
                    simulation_time_s=40.0,
                    indications={
                        "MOV_E_W": SignalIndication.GREEN,
                        "MOV_E_S": SignalIndication.RED,
                    },
                ),
            ],
            config=load_network_mappings(MAPPING_PATH),
        )
