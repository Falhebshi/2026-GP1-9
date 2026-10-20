import pytest
from pydantic import ValidationError

from jaadah.models.network import (
    Approach,
    Intersection,
    Movement,
)

# ============================================================
# INTERSECTION TESTS
# ============================================================

def test_valid_intersection_with_all_optional_fields():
    intersection = Intersection(
        intersection_id="INT_001",
        name_en="Prince Turki Al Awwal x Imam Saud bin Abdulaziz",
        name_ar="تقاطع الأمير تركي الأول مع الإمام سعود بن عبدالعزيز",
        center_longitude=46.6500,
        center_latitude=24.7200,
        area_label="Prince Turki Al-Awwal × Imam Saud bin Abdulaziz",
    )

    assert intersection.intersection_id == "INT_001"
    assert intersection.center_longitude == 46.6500
    assert intersection.center_latitude == 24.7200


def test_intersection_optional_fields_can_be_missing():
    intersection = Intersection(
        intersection_id="INT_001",
    )

    assert intersection.name_en is None
    assert intersection.name_ar is None
    assert intersection.center_longitude is None
    assert intersection.center_latitude is None
    assert intersection.area_label is None


def test_intersection_id_whitespace_is_removed():
    intersection = Intersection(
        intersection_id="  INT_001  ",
    )

    assert intersection.intersection_id == "INT_001"


def test_empty_intersection_id_is_rejected():
    with pytest.raises(
        ValidationError,
        match="identifier must not be empty",
    ):
        Intersection(
            intersection_id="   ",
        )


@pytest.mark.parametrize(
    ("longitude", "latitude"),
    [
        (-180, -90),
        (180, 90),
        (46.6500, 24.7200),
    ],
)
def test_valid_coordinate_bounds(longitude, latitude):
    intersection = Intersection(
        intersection_id="INT_001",
        center_longitude=longitude,
        center_latitude=latitude,
    )

    assert intersection.center_longitude == longitude
    assert intersection.center_latitude == latitude


@pytest.mark.parametrize(
    ("longitude", "latitude"),
    [
        (-180.1, 24.0),
        (180.1, 24.0),
        (46.0, -90.1),
        (46.0, 90.1),
    ],
)
def test_invalid_coordinate_bounds_are_rejected(
    longitude,
    latitude,
):
    with pytest.raises(ValidationError):
        Intersection(
            intersection_id="INT_001",
            center_longitude=longitude,
            center_latitude=latitude,
        )


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_non_finite_coordinates_are_rejected(value):
    with pytest.raises(ValidationError):
        Intersection(
            intersection_id="INT_001",
            center_longitude=value,
            center_latitude=24.7200,
        )


def test_longitude_without_latitude_is_rejected():
    with pytest.raises(
        ValidationError,
        match=(
            "center_longitude and center_latitude "
            "must be provided together"
        ),
    ):
        Intersection(
            intersection_id="INT_001",
            center_longitude=46.6500,
        )


def test_latitude_without_longitude_is_rejected():
    with pytest.raises(
        ValidationError,
        match=(
            "center_longitude and center_latitude "
            "must be provided together"
        ),
    ):
        Intersection(
            intersection_id="INT_001",
            center_latitude=24.7200,
        )


def test_intersection_extra_field_is_rejected():
    with pytest.raises(ValidationError):
        Intersection(
            intersection_id="INT_001",
            sumo_tls_id="TLS_001",
        )

# ============================================================
# APPROACH TESTS
# ============================================================

def test_valid_approach():
    approach = Approach(
        approach_id="APP_E",
        intersection_id="INT_001",
    )

    assert approach.approach_id == "APP_E"
    assert approach.intersection_id == "INT_001"


@pytest.mark.parametrize(
    "field",
    [
        "approach_id",
        "intersection_id",
    ],
)
def test_empty_approach_id_fields_are_rejected(field):
    data = {
        "approach_id": "APP_E",
        "intersection_id": "INT_001",
    }
    data[field] = "   "

    with pytest.raises(
        ValidationError,
        match="identifier must not be empty",
    ):
        Approach(**data)


def test_approach_id_whitespace_is_removed():
    approach = Approach(
        approach_id="  APP_E  ",
        intersection_id="  INT_001  ",
    )

    assert approach.approach_id == "APP_E"
    assert approach.intersection_id == "INT_001"


def test_approach_extra_sumo_field_is_rejected():
    with pytest.raises(ValidationError):
        Approach(
            approach_id="APP_E",
            intersection_id="INT_001",
            sumo_edge_ids=["edge_1"],
        )

# ============================================================
# MOVEMENT TESTS
# ============================================================

def test_valid_movement_with_approach():
    movement = Movement(
        movement_id="MOV_E_W",
        intersection_id="INT_001",
        approach_id="APP_E",
    )

    assert movement.movement_id == "MOV_E_W"
    assert movement.intersection_id == "INT_001"
    assert movement.approach_id == "APP_E"


def test_valid_movement_without_approach():
    movement = Movement(
        movement_id="MOV_MAINLINE",
        intersection_id="INT_001",
    )

    assert movement.approach_id is None


@pytest.mark.parametrize(
    "field",
    [
        "movement_id",
        "intersection_id",
    ],
)
def test_empty_required_movement_ids_are_rejected(field):
    data = {
        "movement_id": "MOV_E_W",
        "intersection_id": "INT_001",
    }
    data[field] = "   "

    with pytest.raises(
        ValidationError,
        match="identifier must not be empty",
    ):
        Movement(**data)


def test_blank_optional_approach_id_is_rejected():
    with pytest.raises(
        ValidationError,
        match="identifier must not be empty",
    ):
        Movement(
            movement_id="MOV_E_W",
            intersection_id="INT_001",
            approach_id="   ",
        )


def test_movement_id_whitespace_is_removed():
    movement = Movement(
        movement_id="  MOV_E_W  ",
        intersection_id="  INT_001  ",
        approach_id="  APP_E  ",
    )

    assert movement.movement_id == "MOV_E_W"
    assert movement.intersection_id == "INT_001"
    assert movement.approach_id == "APP_E"


def test_movement_extra_route_field_is_rejected():
    with pytest.raises(ValidationError):
        Movement(
            movement_id="MOV_E_W",
            intersection_id="INT_001",
            sumo_route_edge_ids=[
                "edge_1",
                "edge_2",
            ],
        )