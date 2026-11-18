"""Tests of the all-day Webster plan script, on invented counts."""

from datetime import datetime, timedelta, timezone

import pytest

from analysis.rcrc_site_1444 import webster_plan as plan


RIYADH = timezone(timedelta(hours=3))
SUNDAY = datetime(2026, 8, 2, tzinfo=RIYADH)   # a workday
FRIDAY = datetime(2026, 8, 7, tzinfo=RIYADH)


def day_of_counts(day, per_interval):
    """Every lane, every 15 minutes of one day, with per_interval[detector] vehicles."""

    return [
        (detector_id, day + timedelta(minutes=15 * i), per_interval[detector_id])
        for i in range(96)
        for detector_id in plan.DETECTOR_LANES
    ]


def test_left_lanes_count_left_turns_as_1_05_vehicles():
    assert plan.saturation_flow("T") == 1900
    assert plan.saturation_flow("L") == pytest.approx(1900 / 1.05)
    assert plan.saturation_flow("TL") == pytest.approx(1900 / 1.05)


def test_a_phase_is_as_critical_as_its_busiest_lane():
    volumes = {d: 100 for d in plan.DETECTOR_LANES}
    volumes["144420"] = 950          # east through lane 4

    ratios = plan.critical_flow_ratios(volumes)

    assert ratios["E"] == pytest.approx(950 / 1900)
    assert ratios["S"] == pytest.approx(100 / (1900 / 1.05))


def test_only_complete_hours_with_every_lane_are_used():
    counts = day_of_counts(SUNDAY, {d: 10 for d in plan.DETECTOR_LANES})
    counts = [c for c in counts if not (c[0] == "144409" and c[1].hour == 8 and c[1].minute == 15)]

    hours = plan.hourly_volumes(counts)

    assert (SUNDAY.date(), 8) not in hours
    assert hours[(SUNDAY.date(), 9)]["144409"] == 40


def test_webster_cycle():
    assert plan.webster_cycle(0.5) == pytest.approx((1.5 * 20 + 5) / 0.5)


def test_webster_cycle_refuses_a_saturated_intersection():
    with pytest.raises(ValueError, match="Y < 1"):
        plan.webster_cycle(1.0)


@pytest.mark.parametrize("webster, chosen", [(214, 225), (243, 225), (120, 100), (165, 150), (290, 300)])
def test_cycle_is_the_nearest_length_dividing_15_minutes(webster, chosen):
    assert plan.nearest_cycle(webster) == chosen
    assert 900 % chosen == 0


def test_greens_add_up_to_the_effective_green_in_proportion():
    greens = plan.split_greens(225, {"E": 0.4, "S": 0.1, "W": 0.2, "N": 0.2})

    assert sum(greens.values()) == 225 - 20
    assert greens["E"] > greens["W"] > greens["S"]
    assert abs(greens["W"] - greens["N"]) <= 1


def test_greens_use_every_hour_of_every_day_type():
    busy = {d: 60 for d in plan.DETECTOR_LANES}
    busy.update({"144419": 180, "144420": 180})      # east through lanes busiest
    quiet = {d: 5 for d in plan.DETECTOR_LANES}
    counts = []
    for week in range(3):
        counts += day_of_counts(SUNDAY + timedelta(weeks=week), busy)
        counts += day_of_counts(FRIDAY + timedelta(weeks=week), quiet)

    cycle, greens, figures = plan.derive_plan(counts)

    assert 900 % cycle == 0
    assert sum(greens.values()) + 20 == cycle
    assert max(greens, key=greens.get) == "E"
    # East's critical lane: a through lane at 720 veh/h in the 72 Sunday hours; in the
    # 72 Friday hours all lanes carry 20 veh/h, so a left lane (1.05 per vehicle) is critical
    assert figures["phase_weights"]["E"] == pytest.approx(72 * 720 / 1900 + 72 * 20 * 1.05 / 1900)
