"""
The Current Traffic timeline turns one KPI engine reason into its own
short label ("Delay not measured: South queue beyond the measured area").
It finds that reason by a few of its words (ZONE_END_WORDS in
frontend/src/services/currentTrafficService.js). This test fails if the
engine's wording and those words drift apart, so the label never quietly
falls back to the general "Delay not measured".
"""

import re
from pathlib import Path

from backend.analytics.kpi.queue import ZONE_END_REASON


SERVICE = (
    Path(__file__).resolve().parents[1]
    / "frontend/src/services/currentTrafficService.js"
)


def test_timeline_finds_the_zone_end_reason():
    match = re.search(r"const ZONE_END_WORDS = '([^']+)'", SERVICE.read_text())

    assert match, "ZONE_END_WORDS is missing from currentTrafficService.js"
    assert match.group(1) in ZONE_END_REASON
