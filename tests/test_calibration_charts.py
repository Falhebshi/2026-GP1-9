import csv

import pytest

from analysis.calibration.calibration_charts import (
    GEH_LAST_BIN,
    geh_band,
    geh_histogram,
    main,
    read_results,
)
from jaadah.calibration.geh import geh

FIELDS = ["day", "detector_id", "observed_veh_h", "simulated_veh_h", "geh", "match", "within_capacity"]


def write_results(path, rows):
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def row(observed, simulated, within):
    value = geh(simulated, observed)
    return {"day": "2026-09-01", "detector_id": "D1", "observed_veh_h": observed,
            "simulated_veh_h": simulated, "geh": round(value, 2), "match": value < 5,
            "within_capacity": within}


@pytest.mark.parametrize("observed", [50, 600, 1000])
def test_band_edges_are_exactly_geh_5(observed):
    low, high = geh_band(observed)
    assert geh(high, observed) == pytest.approx(5.0)
    if low > 0:
        assert geh(low, observed) == pytest.approx(5.0)
    assert low < observed < high


def test_histogram_bins_and_capacity_classes(tmp_path):
    path = write_results(tmp_path / "r.csv", [
        row(600, 610, True),     # GEH 0.4 -> bin 0
        row(600, 780, False),    # GEH 6.9 -> bin 6
        row(700, 330, False),    # GEH 16  -> last bin (15+)
        row(300, 300, ""),       # capacity unknown
    ])
    rows = read_results(path)
    edges, counts = geh_histogram(rows)
    assert edges[-1] == GEH_LAST_BIN
    assert counts["within"][0] == 1
    assert counts["over"][6] == 1 and counts["over"][-1] == 1
    assert counts["unknown"][0] == 1
    assert sum(map(sum, counts.values())) == 4


def test_main_writes_both_figures(tmp_path):
    pytest.importorskip("matplotlib")
    rows = [row(200 + 10 * i, 205 + 10 * i, i % 2 == 0) for i in range(20)]
    calibration = write_results(tmp_path / "calibration.csv", rows)
    validation = write_results(tmp_path / "validation.csv", rows[:10])
    out = tmp_path / "figures"
    assert main(["--calibration", str(calibration), "--validation", str(validation), "--out", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == [
        "geh_distribution.png", "geh_distribution.svg",
        "observed_vs_simulated.png", "observed_vs_simulated.svg",
    ]


def test_missing_results_file_is_reported(tmp_path):
    assert main(["--calibration", str(tmp_path / "none.csv"), "--out", str(tmp_path)]) == 2
