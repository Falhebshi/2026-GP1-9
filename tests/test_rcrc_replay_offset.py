import pytest

from traffic_source.rcrc_replay.config import OFFSET_WEEKS_VARIABLE, ReplayConfig


def test_default_is_13_weeks_without_the_variable():
    assert ReplayConfig.from_environment({}).offset_weeks == 13


def test_blank_variable_keeps_the_default():
    assert ReplayConfig.from_environment({OFFSET_WEEKS_VARIABLE: "  "}).offset_weeks == 13


@pytest.mark.parametrize("value", ["0", "5", " 2 "])
def test_variable_sets_the_offset(value):
    assert ReplayConfig.from_environment({OFFSET_WEEKS_VARIABLE: value}).offset_weeks == int(value)


@pytest.mark.parametrize("value", ["1.5", "two", "-1"])
def test_invalid_values_are_refused(value):
    with pytest.raises(ValueError, match="offset_weeks|whole number"):
        ReplayConfig.from_environment({OFFSET_WEEKS_VARIABLE: value})
