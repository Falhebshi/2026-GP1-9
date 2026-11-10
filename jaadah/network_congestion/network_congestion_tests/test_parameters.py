import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from jaadah.models.network_congestion import (
    CongestionLevel,
    RoadSegment,
    SegmentCongestion,
)
from jaadah.network_congestion.parameters import (
    congestion_level,
    segment_capacity,
)
from jaadah.network_congestion.segments import DEFAULT_OUTPUT_DIR

RIYADH = timezone(timedelta(hours=3))
START = datetime(2026, 11, 10, 8, 0, tzinfo=RIYADH)
END = START + timedelta(minutes=15)


def segment(**changes):
    """A two-lane primary segment ending at a signal."""

    fields = {
        "segment_id": "SEG_00001",
        "road_class": "primary",
        "lane_count": 2,
        "free_flow_speed_kmh": 80.0,
        "signal_at_end": True,
        "geometry": [(46.60, 24.70), (46.61, 24.70)],
    }
    fields.update(changes)

    return RoadSegment(**fields)


def test_signal_capacity_uses_the_green_share_of_the_road_class():
    # 2 lanes x 1,900 x 0.26 (main road)
    assert segment_capacity(segment()) == pytest.approx(988)
    # 2 lanes x 1,900 x 0.13 (side road)
    assert segment_capacity(
        segment(road_class="secondary")
    ) == pytest.approx(494)


def test_freeway_capacity_follows_the_free_flow_speed():
    def capacity(speed):
        return segment_capacity(
            segment(
                road_class="motorway",
                signal_at_end=False,
                free_flow_speed_kmh=speed,
            )
        )

    assert capacity(120) == 2 * 2400
    assert capacity(110) == 2 * 2350
    assert capacity(100) == 2 * 2300
    assert capacity(60) == 2 * 2250


def test_city_street_without_a_signal_gets_the_base_flow():
    for road_class in ("primary", "secondary"):
        assert segment_capacity(
            segment(road_class=road_class, signal_at_end=False)
        ) == 2 * 1900


def test_levels_change_at_the_limits():
    assert congestion_level(0.0) == CongestionLevel.LOW
    assert congestion_level(0.59) == CongestionLevel.LOW
    assert congestion_level(0.60) == CongestionLevel.MODERATE
    assert congestion_level(0.85) == CongestionLevel.HIGH
    assert congestion_level(1.4) == CongestionLevel.HIGH

    with pytest.raises(ValueError):
        congestion_level(-0.1)


def test_ok_result_needs_every_value():
    result = SegmentCongestion(
        segment_id="SEG_00001", interval_start=START, interval_end=END,
        source="synthetic", status="ok", volume_veh=200,
        capacity_veh_h=988, volume_to_capacity=0.81, level="moderate",
        congestion=0.81,
    )

    assert result.level == CongestionLevel.MODERATE

    with pytest.raises(ValidationError):
        SegmentCongestion(
            segment_id="SEG_00001", interval_start=START,
            interval_end=END, source="synthetic", status="ok",
            volume_veh=200,
        )


def test_unavailable_result_has_a_reason_and_no_level():
    SegmentCongestion(
        segment_id="SEG_00001", interval_start=START, interval_end=END,
        source="rcrc", status="unavailable",
        reason="no data for this interval",
    )

    with pytest.raises(ValidationError):
        SegmentCongestion(
            segment_id="SEG_00001", interval_start=START,
            interval_end=END, source="rcrc", status="unavailable",
            level="low", reason="no data for this interval",
        )

    with pytest.raises(ValidationError):
        SegmentCongestion(
            segment_id="SEG_00001", interval_start=START,
            interval_end=END, source="rcrc", status="unavailable",
        )


def test_every_written_segment_fits_the_model():
    path = DEFAULT_OUTPUT_DIR / "road_segments.json"

    if not path.exists():
        pytest.skip("road_segments.json has not been built")

    content = json.loads(path.read_text(encoding="utf-8"))

    for record in content["segments"]:
        RoadSegment(**record)
