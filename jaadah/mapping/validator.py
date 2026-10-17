import hashlib
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from jaadah.models.mappings import NetworkMappingConfig


def validate_network_mappings(config: NetworkMappingConfig, network_path: str | Path) -> list[str]:
    """Return network-reference errors; an empty list means static checks passed."""
    path = Path(network_path)
    errors = []

    if not path.is_file():
        return [f"SUMO network file not found: {path}"]

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest.lower() != config.network.sha256.lower():
        errors.append("SUMO network SHA-256 does not match the mapping configuration")

    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return errors + [f"Invalid SUMO network XML: {exc}"]
    except OSError as exc:
        return errors + [f"Cannot read SUMO network: {exc}"]

    if root.tag != "net":
        return errors + ["Expected a SUMO <net> document"]

    edges = {}
    lanes = set()
    edge_lanes = defaultdict(set)
    for edge in root.findall("edge"):
        edge_id = edge.get("id")
        if not edge_id:
            continue
        edges[edge_id] = edge
        for lane in edge.findall("lane"):
            lane_id = lane.get("id")
            if lane_id:
                lanes.add(lane_id)
                edge_lanes[edge_id].add(lane_id)

    connections = defaultdict(list)
    controlled = defaultdict(set)
    controlled_edges = defaultdict(set)
    for connection in root.findall("connection"):
        from_edge, to_edge = connection.get("from"), connection.get("to")
        if not from_edge or not to_edge:
            continue
        # SUMO connection records include the legal from-lane/to-lane pairing.
        connections[(from_edge, to_edge)].append(connection)
        tls = connection.get("tl")
        idx = connection.get("linkIndex")
        if tls is not None and idx is not None:
            try:
                link_index = int(idx)
            except ValueError:
                errors.append(f"Invalid TLS linkIndex {idx!r} in network")
                continue
            controlled[tls].add(link_index)
            controlled_edges[(tls, link_index)].add((from_edge, to_edge))

    tls_ids = {x.get("id") for x in root.findall("tlLogic") if x.get("id")}

    intersection = config.intersection_mapping
    if intersection.sumo_tls_id and intersection.sumo_tls_id not in tls_ids:
        errors.append(f"Intersection TLS not found: {intersection.sumo_tls_id}")

    for approach in config.approach_mappings:
        for lane in approach.queue_detection_lane_ids:
            if lane not in lanes:
                errors.append(f"Approach {approach.approach_id}: lane not found: {lane}")

    for movement in config.movement_mappings:
        name = f"Movement {movement.movement_id}"
        route = movement.sumo_route_edge_ids
        for edge_id in route:
            if edge_id not in edges or edges[edge_id].get("function") == "internal":
                errors.append(f"{name}: unknown or internal route edge: {edge_id}")
        for left, right in zip(route, route[1:]):
            if (left, right) not in connections:
                errors.append(f"{name}: no legal SUMO connection {left} -> {right}")
        for lane_id in movement.sumo_lanes:
            if lane_id not in lanes:
                errors.append(f"{name}: lane not found: {lane_id}")
        if movement.signal_controlled:
            if movement.sumo_tls_id not in tls_ids:
                errors.append(f"{name}: TLS not found: {movement.sumo_tls_id}")
            if (intersection.sumo_tls_id is not None
                    and movement.sumo_tls_id != intersection.sumo_tls_id):
                errors.append(f"{name}: controlling TLS differs from mapped intersection TLS")
            for crossing in movement.signal_crossings:
                for index in crossing.controlled_link_indices:
                    if index not in controlled[crossing.sumo_tls_id]:
                        errors.append(f"{name}: TLS {crossing.sumo_tls_id} missing link index {index}")
                    elif not any(pair in zip(route, route[1:]) for pair in controlled_edges[(crossing.sumo_tls_id, index)]):
                        errors.append(f"{name}: TLS link index {index} is not on the mapped route")
        else:
            # Catch route crossings that are signal-controlled in the actual network.
            route_pairs = set(zip(route, route[1:]))
            if any(pair in route_pairs for pairs in controlled_edges.values() for pair in pairs):
                errors.append(f"{name}: route contains a controlled link but signal_controlled is false")

    return errors
