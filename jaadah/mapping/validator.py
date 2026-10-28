import hashlib
import math
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from jaadah.models.mappings import LaneMapping, NetworkMappingConfig


def require_lane_mapping(config: NetworkMappingConfig, lane_id: str) -> LaneMapping:
    """Return the lane's SUMO mapping or raise if it is missing."""
    for mapping in config.lane_mappings:
        if mapping.lane_id == lane_id:
            return mapping
    raise ValueError(f"Missing SUMO lane mapping for lane {lane_id}")


def network_checksum_matches(content: bytes, expected: str) -> bool:
    """Accept LF/CRLF-equivalent checksums; all other bytes remain significant."""
    lf_content = content.replace(b"\r\n", b"\n")
    variants = (content, lf_content, lf_content.replace(b"\n", b"\r\n"))
    return expected.lower() in {hashlib.sha256(value).hexdigest() for value in variants}


def validate_network_mappings(config: NetworkMappingConfig, network_path: str | Path) -> list[str]:
    """Return network-reference errors; an empty list means static checks passed."""
    path = Path(network_path)
    errors = []

    if not path.is_file():
        return [f"SUMO network file not found: {path}"]

    try:
        content = path.read_bytes()
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        return errors + [f"Invalid SUMO network XML: {exc}"]
    except OSError as exc:
        return errors + [f"Cannot read SUMO network: {exc}"]

    if not network_checksum_matches(content, config.network.sha256):
        errors.append("SUMO network SHA-256 does not match the mapping configuration")

    if root.tag != "net":
        return errors + ["Expected a SUMO <net> document"]

    edges = {}
    lanes = set()
    lane_lengths = {}
    lane_edges = {}
    indexed_lanes = {}
    for edge in root.findall("edge"):
        edge_id = edge.get("id")
        if not edge_id:
            continue
        edges[edge_id] = edge
        for lane in edge.findall("lane"):
            lane_id = lane.get("id")
            if lane_id:
                lanes.add(lane_id)
                lane_lengths[lane_id] = lane.get("length")
                lane_edges[lane_id] = edge_id
                indexed_lanes[(edge_id, lane.get("index"))] = lane_id

    connections = defaultdict(list)
    lane_connections = set()
    controlled = defaultdict(set)
    controlled_edges = defaultdict(set)
    for connection in root.findall("connection"):
        from_edge, to_edge = connection.get("from"), connection.get("to")
        if not from_edge or not to_edge:
            continue
        # SUMO connection records include the legal from-lane/to-lane pairing.
        connections[(from_edge, to_edge)].append(connection)
        from_lane = indexed_lanes.get((from_edge, connection.get("fromLane")))
        to_lane = indexed_lanes.get((to_edge, connection.get("toLane")))
        if from_lane and to_lane:
            lane_connections.add((from_lane, to_lane))
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

    def lane_supports_route(
        lane_id: str, route: list[str], *, at_position: int | None = None
    ) -> bool:
        """Check whether the lane has a legal connection along the route."""
        positions = range(len(route)) if at_position is None else [at_position]
        for position in positions:
            edge_id = route[position]
            if lane_edges.get(lane_id) != edge_id:
                continue
            if position + 1 < len(route):
                if any(
                    indexed_lanes.get((edge_id, item.get("fromLane"))) == lane_id
                    for item in connections[(edge_id, route[position + 1])]
                ):
                    return True
            elif position > 0:
                if any(
                    indexed_lanes.get((edge_id, item.get("toLane"))) == lane_id
                    for item in connections[(route[position - 1], edge_id)]
                ):
                    return True
        return False

    canonical_lanes = {item.lane_id: item for item in config.approach_lanes}
    movements = {item.movement_id: item for item in config.movement_mappings}
    for mapping in config.lane_mappings:
        name = f"Lane {mapping.lane_id}"
        for lane_id in mapping.sumo_lane_ids:
            if lane_id not in lanes:
                errors.append(f"{name}: lane not found: {lane_id}")
            elif edges[lane_edges[lane_id]].get("function") == "internal":
                errors.append(f"{name}: internal SUMO lane is not an approach lane: {lane_id}")
        for left, right in zip(mapping.sumo_lane_ids, mapping.sumo_lane_ids[1:]):
            if (left, right) not in lane_connections:
                errors.append(f"{name}: no legal SUMO lane connection {left} -> {right}")
        route_edges = [lane_edges.get(item) for item in mapping.sumo_lane_ids]
        for movement_id in canonical_lanes[mapping.lane_id].served_movement_ids:
            route = movements[movement_id].sumo_route_edge_ids
            ends = [
                start + len(route_edges) - 1
                for start in range(len(route))
                if route[start:start + len(route_edges)] == route_edges
            ]
            if not ends:
                errors.append(f"{name}: lane segments are not on movement route {movement_id}")
            elif not any(
                lane_supports_route(mapping.sumo_lane_ids[-1], route, at_position=end)
                for end in ends
            ):
                errors.append(f"{name}: terminal lane cannot serve movement {movement_id}")

    lane_mappings = {item.lane_id: item for item in config.lane_mappings}
    for detector in config.detector_mappings:
        if detector.sumo_lane_id is None:
            continue
        name = f"Detector {detector.source.value}/{detector.site_id}/{detector.detector_id}"
        lane_id = detector.sumo_lane_id
        mapping = lane_mappings.get(detector.lane_id)
        # Pending canonical mappings remain valid drafts; membership is checked
        # only when a chain is available. No terminal-segment rule is imposed.
        if mapping is not None and lane_id not in mapping.sumo_lane_ids:
            errors.append(f"{name}: SUMO lane {lane_id} is not in canonical lane {mapping.lane_id} chain")
        if lane_id not in lanes:
            errors.append(f"{name}: lane not found: {lane_id}")
            continue
        if edges[lane_edges[lane_id]].get("function") == "internal":
            errors.append(f"{name}: internal SUMO lane is not a detector traffic lane: {lane_id}")
            continue
        try:
            length = float(lane_lengths[lane_id])
        except (TypeError, ValueError):
            errors.append(f"{name}: missing or invalid SUMO lane length: {lane_id}")
            continue
        if not math.isfinite(length) or length < 0:
            errors.append(f"{name}: invalid SUMO lane length: {lane_id}")
        elif not 0 <= detector.sumo_position_m <= length:
            errors.append(f"{name}: SUMO position {detector.sumo_position_m} outside lane {lane_id} bounds [0, {length}]")

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
            elif not lane_supports_route(lane_id, route):
                errors.append(f"{name}: lane is not connected along the mapped route: {lane_id}")
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

    errors.extend(_zone_errors(config, edges, lane_edges))
    return errors


def _zone_errors(config: NetworkMappingConfig, edges: dict, lane_edges: dict) -> list[str]:
    """
    Check that each approach's measurement zone fits on the routes of the
    movements its lanes serve: zone_upstream_m on the route up to the stop
    line, zone_downstream_m on the route after the junction exit.

    The stop line is the end of the last SUMO lane of the movement's
    canonical lanes; the junction exit is the start of the next route edge.
    Movements whose lanes are not mapped yet are not checked.
    """

    def edge_length(edge_id):
        lanes = edges[edge_id].findall("lane")
        try:
            length = float(lanes[0].get("length")) if lanes else None
        except (TypeError, ValueError):
            return None
        return length if length is not None and math.isfinite(length) and length >= 0 else None

    sumo_lanes = {item.lane_id: item.sumo_lane_ids for item in config.lane_mappings}
    routes = {item.movement_id: item.sumo_route_edge_ids for item in config.movement_mappings}
    errors = []

    for approach in config.approach_mappings:
        if approach.zone_upstream_m is None:
            continue
        stop_edges = defaultdict(set)
        for lane in config.approach_lanes:
            if lane.approach_id != approach.approach_id or lane.lane_id not in sumo_lanes:
                continue
            for movement_id in lane.served_movement_ids:
                stop_edges[movement_id].add(lane_edges.get(sumo_lanes[lane.lane_id][-1]))

        for movement_id, found in sorted(stop_edges.items()):
            name = f"Approach {approach.approach_id} zone, movement {movement_id}"
            route = routes.get(movement_id, [])
            stop_edge = next(iter(found)) if len(found) == 1 else None
            if stop_edge not in route or any(edge not in edges for edge in route):
                # Lane and route errors are reported by the checks above.
                continue
            lengths = [edge_length(edge) for edge in route]
            if None in lengths:
                errors.append(f"{name}: invalid SUMO edge length on the route")
                continue
            position = route.index(stop_edge)
            upstream = sum(lengths[: position + 1])
            downstream = sum(lengths[position + 1 :])
            if approach.zone_upstream_m > upstream:
                errors.append(
                    f"{name}: zone_upstream_m {approach.zone_upstream_m} m exceeds "
                    f"the {upstream:.1f} m of route before the stop line"
                )
            if approach.zone_downstream_m > downstream:
                errors.append(
                    f"{name}: zone_downstream_m {approach.zone_downstream_m} m exceeds "
                    f"the {downstream:.1f} m of route after the junction exit"
                )

    return errors
