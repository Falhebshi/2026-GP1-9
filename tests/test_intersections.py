import json

import pytest
from pydantic import ValidationError

from backend.outputs.intersections import (
    REPO_ROOT,
    load_intersections,
)
from jaadah.mapping.loader import load_network_mappings


MAPPING_PATH = (
    REPO_ROOT
    / "data"
    / "processed"
    / "road_network"
    / "network_mappings.json"
)

FRONTEND_COPY_PATH = (
    REPO_ROOT
    / "frontend"
    / "public"
    / "data"
    / "intersections.json"
)


def make_record(
    intersection_id: str,
) -> dict:
    """Create one intersection record for loader tests."""

    return {
        "intersection_id": intersection_id,
        "name_en": "Test Rd × Other Rd",
        "center_longitude": 46.6,
        "center_latitude": 24.7,
        "area_label": "Test area",
    }


def write_records(
    tmp_path,
    content,
):
    """Write test content to an intersections file."""

    path = tmp_path / "intersections.json"
    path.write_text(
        json.dumps(content),
        encoding="utf-8",
    )

    return path


def test_study_intersection_is_loaded() -> None:
    intersections = load_intersections()

    assert len(intersections) == 1
    assert intersections[0].intersection_id == "INT_001"
    assert intersections[0].name_ar == (
        "طريق الأمير تركي الأول × طريق الإمام سعود"
    )


def test_study_intersection_matches_the_network_mapping() -> None:
    mapping = load_network_mappings(MAPPING_PATH)
    intersections = load_intersections()

    assert intersections[0].intersection_id == (
        mapping.intersection_mapping.intersection_id
    )


def test_duplicate_intersection_ids_are_refused(tmp_path) -> None:
    path = write_records(
        tmp_path=tmp_path,
        content=[
            make_record(intersection_id="INT_A"),
            make_record(intersection_id="INT_A"),
        ],
    )

    with pytest.raises(
        ValueError,
        match="duplicate intersection_id: INT_A",
    ):
        load_intersections(path)


def test_file_without_a_list_is_refused(tmp_path) -> None:
    path = write_records(
        tmp_path=tmp_path,
        content=make_record(intersection_id="INT_A"),
    )

    with pytest.raises(
        ValueError,
        match="must contain a list",
    ):
        load_intersections(path)


def test_record_with_one_coordinate_is_refused(tmp_path) -> None:
    record = make_record(intersection_id="INT_A")
    del record["center_latitude"]

    path = write_records(
        tmp_path=tmp_path,
        content=[record],
    )

    with pytest.raises(ValidationError):
        load_intersections(path)


def test_frontend_copy_matches_the_study_intersections() -> None:
    assert load_intersections(FRONTEND_COPY_PATH) == (
        load_intersections()
    )
