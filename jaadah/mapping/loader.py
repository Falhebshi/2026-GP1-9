import json
from pathlib import Path

from ..models.mappings import NetworkMappingConfig


# ============================================================
# NETWORK MAPPING LOADER
# ============================================================

def load_network_mappings(file_path: str | Path) -> NetworkMappingConfig:
    """Read mapping JSON and validate it against NetworkMappingConfig."""

    with Path(file_path).open("r", encoding="utf-8") as file:
        data = json.load(file)

    return NetworkMappingConfig.model_validate(data)
