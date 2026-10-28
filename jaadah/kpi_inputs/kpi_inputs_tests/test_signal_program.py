import hashlib
from pathlib import Path

import pytest

from jaadah.kpi_inputs.signal_program import SignalProgramError, build_signal_program
from jaadah.mapping.loader import load_network_mappings
from jaadah.models.mappings import NetworkMappingConfig
from jaadah.models.signals import SignalControlType, SignalProgramSource

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MAPPING_PATH = PROJECT_ROOT / "data/processed/road_network/network_mappings.json"
NETWORK_PATH = PROJECT_ROOT / "data/processed/road_network/jaadah_study_area.net.xml"

# Link 0: MOV_A; link 1: MOV_B; link 2: MOV_RAMP (no attributes).
PLAN = [("30", "GrG"), ("3", "yry"), ("2", "rrr"), ("20", "rGr"), ("3", "ryr"), ("2", "rrr")]


# ============================================================
# HELPERS
# ============================================================

def network_xml(plans):
    """plans: list of (programID, type, steps)."""
    logic = "".join(
        f'<tlLogic id="tls" type="{kind}" programID="{program}" offset="0">'
        + "".join(f'<phase duration="{d}" state="{s}"/>' for d, s in steps)
        + "</tlLogic>"
        for program, kind, steps in plans
    )
    return f"<net>{logic}</net>"


def movement(movement_id, approach_id, links):
    data = {"movement_id": movement_id, "intersection_id": "INT_001", "approach_id": approach_id,
            "sumo_route_edge_ids": ["in", "out"], "signal_controlled": links is not None}
    if links is not None:
        data.update(sumo_tls_id="tls", signal_crossings=[
            {"crossing_order": 0, "sumo_tls_id": "tls", "controlled_link_indices": links}])
    return data


def case(tmp_path, plans=(("0", "static", PLAN),), *, a_links=(0,), checksum=None):
    path = tmp_path / "network.net.xml"
    path.write_text(network_xml(plans), encoding="utf-8")
    data = {
        "schema_version": "2.0", "mapping_version": "test",
        "network": {"version": "test", "path": str(path),
                    "sha256": checksum or hashlib.sha256(path.read_bytes()).hexdigest()},
        "intersection_mapping": {"intersection_id": "INT_001", "sumo_tls_id": "tls"},
        "approach_mappings": [
            {"approach_id": "APP_E", "intersection_id": "INT_001", "approach_side": "east"},
            {"approach_id": "APP_W", "intersection_id": "INT_001", "approach_side": "west"},
        ],
        "movement_mappings": [
            movement("MOV_A", "APP_E", list(a_links)),
            movement("MOV_B", "APP_W", [1]),
            movement("MOV_RAMP", "APP_E", [2]),
            movement("MOV_SLIP", "APP_W", None),
        ],
        "movement_attributes": [
            {"movement_id": "MOV_A", "movement_type": "through", "control": "signalized"},
            {"movement_id": "MOV_B", "movement_type": "through", "control": "signalized"},
            {"movement_id": "MOV_SLIP", "movement_type": "right", "control": "uncontrolled"},
        ],
    }
    return NetworkMappingConfig.model_validate(data), path


def build(config, path, **kwargs):
    return build_signal_program(config, path, scenario_id="SCN_BASE",
                                signal_program_id="SP_BASE", **kwargs)


def problems_of(config, path, **kwargs):
    with pytest.raises(SignalProgramError) as raised:
        build(config, path, **kwargs)
    return raised.value.problems


# ============================================================
# VALID PLANS
# ============================================================

def test_each_green_with_its_yellow_and_all_red_is_one_phase(tmp_path):
    program = build(*case(tmp_path))

    assert [(p.phase_id, p.sequence_order, p.green_time_s, p.yellow_time_s, p.all_red_time_s)
            for p in program.phases] == [("PHASE_1", 0, 30, 3, 2), ("PHASE_2", 1, 20, 3, 2)]
    assert program.cycle_length_s == 60


def test_only_analysed_signalised_movements_are_served(tmp_path):
    """MOV_RAMP is green in phase 1 but has no attributes; MOV_SLIP has no signal."""
    program = build(*case(tmp_path))

    assert [p.served_movement_ids for p in program.phases] == [["MOV_A"], ["MOV_B"]]


def test_program_identity_and_source(tmp_path):
    program = build(*case(tmp_path))

    assert (program.signal_program_id, program.scenario_id) == ("SP_BASE", "SCN_BASE")
    assert program.control_type is SignalControlType.FIXED_TIME
    assert program.source is SignalProgramSource.BASELINE_MODEL


def test_program_id_selects_one_of_several_plans(tmp_path):
    other = [("50", "GGr"), ("10", "rrr")]
    config, path = case(tmp_path, (("0", "static", PLAN), ("1", "static", other)))

    assert build(config, path, program_id="0").cycle_length_s == 60


def test_movement_with_two_separate_greens_is_in_two_phases(tmp_path):
    """The engine counts two greens for MOV_A (capacity kept, HCM delay unavailable)."""
    plan = [("20", "Grr"), ("5", "rrr"), ("20", "rGr"), ("5", "rrr"), ("20", "Grr"), ("5", "rrr")]
    program = build(*case(tmp_path, (("0", "static", plan),)))

    assert [p.served_movement_ids for p in program.phases] == [["MOV_A"], ["MOV_B"], ["MOV_A"]]
    assert program.cycle_length_s == 75


def test_green_written_as_two_identical_steps_is_one_green(tmp_path):
    plan = [("20", "GrG"), ("10", "GrG")] + PLAN[1:]
    program = build(*case(tmp_path, (("0", "static", plan),)))

    assert program.phases[0].green_time_s == 30
    assert len(program.phases) == 2


def test_study_area_plan():
    """East 40 s, South 15 s, West 30 s, North 15 s; 3 s yellow and 2 s all-red each."""
    program = build(load_network_mappings(MAPPING_PATH), NETWORK_PATH)

    assert [(p.served_movement_ids, p.green_time_s, p.yellow_time_s, p.all_red_time_s)
            for p in program.phases] == [
        (["MOV_E_W", "MOV_E_S"], 40, 3, 2),
        (["MOV_S_W"], 15, 3, 2),
        (["MOV_W_E", "MOV_W_N"], 30, 3, 2),
        (["MOV_N_E"], 15, 3, 2),
    ]
    assert program.cycle_length_s == 120


# ============================================================
# REJECTED PLANS
# ============================================================

def test_network_must_match_the_mapping(tmp_path):
    config, path = case(tmp_path, checksum="0" * 64)

    assert problems_of(config, path) == [
        "SUMO network SHA-256 does not match the mapping configuration"]


def test_missing_plan_rejected(tmp_path):
    config, path = case(tmp_path)

    assert problems_of(config, path, program_id="9") == ["no signal plan found for tls program 9"]


def test_several_plans_need_a_program_id(tmp_path):
    config, path = case(tmp_path, (("0", "static", PLAN), ("1", "static", PLAN)))

    assert problems_of(config, path) == [
        "tls has several plans ['0', '1']; choose one with program_id"]


def test_non_fixed_time_plan_rejected(tmp_path):
    config, path = case(tmp_path, (("0", "actuated", PLAN),))

    assert "only fixed-time (static) plans are supported" in problems_of(config, path)[0]


def test_permitted_green_rejected(tmp_path):
    plan = [("30", "grG"), ("5", "rrr"), ("20", "rGr"), ("5", "rrr")]
    config, path = case(tmp_path, (("0", "static", plan),))

    assert problems_of(config, path) == [
        "step 1: unsupported signal states ['g']; only G, y and r are supported"]


def test_plan_must_start_with_a_green(tmp_path):
    plan = PLAN[2:] + PLAN[:2]
    config, path = case(tmp_path, (("0", "static", plan),))

    assert problems_of(config, path) == ["the plan must start with a green step"]


def test_partly_green_movement_rejected(tmp_path):
    """MOV_A uses links 0 and 1; phase 1 is green on link 0 only."""
    config, path = case(tmp_path, a_links=(0, 1))

    assert "phase 1: MOV_A is only partly green" in problems_of(config, path)


def test_green_serving_no_analysed_movement_rejected(tmp_path):
    plan = PLAN + [("10", "rrG"), ("5", "rrr")]
    config, path = case(tmp_path, (("0", "static", plan),))

    assert problems_of(config, path) == ["phase 3: serves no analysed movement"]


def test_movement_never_green_rejected(tmp_path):
    plan = [("30", "GrG"), ("5", "rrr")]
    config, path = case(tmp_path, (("0", "static", plan),))

    assert problems_of(config, path) == ["MOV_B: never green in the plan"]


@pytest.mark.parametrize("plan, expected", [
    # MOV_B joins while MOV_A stays green.
    ([("20", "Grr"), ("20", "GGr"), ("3", "yyr"), ("2", "rrr")],
     "MOV_A stays green from phase 1 into phase 2; overlapping phases are not supported"),
    # MOV_B turns yellow while MOV_A stays green.
    ([("20", "GGr"), ("3", "Gyr"), ("20", "Grr"), ("3", "yrr"), ("2", "rrr")],
     "MOV_A stays green from phase 1 into phase 2; overlapping phases are not supported"),
    # MOV_A's green runs from the end of the cycle into its start.
    ([("20", "Grr"), ("3", "yrr"), ("20", "rGr"), ("3", "ryr"), ("10", "Grr")],
     "MOV_A stays green from phase 3 into phase 1; overlapping phases are not supported"),
])
def test_overlap_rejected(tmp_path, plan, expected):
    config, path = case(tmp_path, (("0", "static", plan),))

    assert expected in problems_of(config, path)
