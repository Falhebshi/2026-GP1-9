import json
from pathlib import Path

from ..models.mappings import NetworkMappingConfig
from .validator import validate_network_mappings


# ============================================================
# NETWORK MAPPING LOADER
# ============================================================

def load_network_mappings(
    file_path: str | Path,
    *,
    network_path: str | Path | None = None,
) -> NetworkMappingConfig:
    """Load and validate mappings; also check SUMO if network_path is supplied."""

    with Path(file_path).open("r", encoding="utf-8") as file:
        data = json.load(file)

    config = NetworkMappingConfig.model_validate(data)
    if network_path is not None:
        errors = validate_network_mappings(config, network_path)
        if errors:
            raise ValueError("Invalid SUMO network mappings:\n" + "\n".join(errors))
    return config
