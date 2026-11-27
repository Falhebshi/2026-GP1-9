import json
from pathlib import Path

from jaadah.models.network import Intersection


# Project and data paths
REPO_ROOT = Path(__file__).resolve().parents[2]

# The website's copy is the only one, so the page and the backend can't drift apart
INTERSECTIONS_PATH = (
    REPO_ROOT
    / "frontend"
    / "public"
    / "data"
    / "intersections.json"
)


def load_intersections(
    file_path: str | Path = INTERSECTIONS_PATH,
) -> list[Intersection]:
    """
    Load the study intersections and check that every
    intersection_id is unique.
    """

    with Path(file_path).open(
        "r",
        encoding="utf-8",
    ) as file:
        records = json.load(file)

    if not isinstance(records, list):
        raise ValueError(
            "intersections file must contain a list"
        )

    intersections: list[Intersection] = []
    seen_ids: set[str] = set()

    for record in records:
        intersection = Intersection.model_validate(record)

        if intersection.intersection_id in seen_ids:
            raise ValueError(
                "duplicate intersection_id: "
                + intersection.intersection_id
            )

        seen_ids.add(intersection.intersection_id)
        intersections.append(intersection)

    return intersections
