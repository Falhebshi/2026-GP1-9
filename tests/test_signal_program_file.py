"""The website's copy of the signal program (backend/outputs/signal_program.py)."""

import json

from backend.analytics.service import FRONTEND_DATA_DIR
from backend.outputs.signal_program import FILE_NAME, signal_program_payload, write_signal_program


def test_the_payload_is_the_network_s_webster_plan():
    """
    The Release 1 plan (docs/kpi_engine.md, 9.8): greens 90, 27, 41 and
    47 s, each followed by 3 s of yellow and 2 s of all-red, so the cycle
    is 205 + 4 x 5 = 225 s. Its timings were derived for the model, so
    its source is baseline_model.
    """

    payload = signal_program_payload()

    assert payload["control_type"] == "fixed_time"
    assert payload["source"] == "baseline_model"
    assert [p["green_time_s"] for p in payload["phases"]] == [90, 27, 41, 47]
    assert {(p["yellow_time_s"], p["all_red_time_s"]) for p in payload["phases"]} == {(3, 2)}
    assert payload["cycle_length_s"] == 90 + 27 + 41 + 47 + 4 * (3 + 2) == 225
    assert payload["phases"][0]["served_movement_ids"] == ["MOV_E_W", "MOV_E_S"]


def test_the_committed_file_matches_the_network():
    """A plan changed in the network without rebuilding the file fails here."""

    payload = signal_program_payload()
    committed = json.loads((FRONTEND_DATA_DIR / payload["intersection_id"] / FILE_NAME).read_text(encoding="utf-8"))

    assert committed == payload, "run: python -m backend.outputs.signal_program"


def test_the_file_is_written_where_asked(tmp_path):
    path = write_signal_program(out_dir=tmp_path)

    assert path == tmp_path / FILE_NAME
    assert json.loads(path.read_text(encoding="utf-8")) == signal_program_payload()
