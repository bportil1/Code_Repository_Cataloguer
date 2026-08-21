from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from .catalog.models import DependencyEdge, ProjectCatalog

FUNCTION_NODE_TYPES = {"function", "method"}


def _public_node(node: Any, distance: int) -> dict[str, Any]:
    metadata = node.metadata or {}
    return {
        "id": node.id,
        "node_type": node.node_type,
        "name": node.name,
        "qualified_name": node.qualified_name,
        "path": node.path or metadata.get("path"),
        "parent_id": node.parent_id,
        "line_start": metadata.get("line_start"),
        "line_end": metadata.get("line_end"),
        "distance_from_focus": distance,
    }


def _public_edge(edge: DependencyEdge) -> dict[str, Any]:
    return {
        "source_id": edge.source_id,
        "target_id": edge.target_id,
        "relationship_type": edge.relationship_type,
        "evidence": edge.evidence,
        "metadata": edge.metadata,
    }


def build_reachable_call_network(
    catalog: ProjectCatalog,
    focus_id: str,
    *,
    depth: int | None = None,
    include_incoming: bool = True,
    include_outgoing: bool = True,
) -> dict[str, Any]:
    """Return the statically resolved call network reachable from ``focus_id``.

    ``depth=None`` means traverse until no additional call-graph nodes can be
    discovered. A finite depth preserves the Repository Map's bounded-hop
    behavior. Traversal is cycle-safe and every node is assigned its shortest
    discovered hop distance from the focus node.
    """

    focus = catalog.nodes.get(focus_id)
    if focus is None:
        raise KeyError(f"Unknown catalog node: {focus_id}")
    if focus.node_type not in FUNCTION_NODE_TYPES:
        raise ValueError("Call-network focus must be a function or method")
    if depth is not None and int(depth) < 0:
        raise ValueError("depth must be non-negative or None")
    depth = None if depth is None else int(depth)

    outgoing: dict[str, list[DependencyEdge]] = defaultdict(list)
    incoming: dict[str, list[DependencyEdge]] = defaultdict(list)
    call_edges: list[DependencyEdge] = []
    for edge in catalog.relationships:
        if edge.relationship_type != "calls":
            continue
        source = catalog.nodes.get(edge.source_id)
        target = catalog.nodes.get(edge.target_id)
        if source is None or target is None:
            continue
        if source.node_type not in FUNCTION_NODE_TYPES or target.node_type not in FUNCTION_NODE_TYPES:
            continue
        call_edges.append(edge)
        outgoing[edge.source_id].append(edge)
        incoming[edge.target_id].append(edge)

    visited = {focus_id}
    distances = {focus_id: 0}
    queue: deque[str] = deque([focus_id])

    while queue:
        current_id = queue.popleft()
        current_distance = distances[current_id]
        if depth is not None and current_distance >= depth:
            continue

        candidates: list[str] = []
        if include_outgoing:
            candidates.extend(edge.target_id for edge in outgoing.get(current_id, ()))
        if include_incoming:
            candidates.extend(edge.source_id for edge in incoming.get(current_id, ()))

        for candidate_id in candidates:
            if candidate_id in visited:
                continue
            visited.add(candidate_id)
            distances[candidate_id] = current_distance + 1
            queue.append(candidate_id)

    selected_edges = [
        edge for edge in call_edges
        if edge.source_id in visited and edge.target_id in visited
    ]

    truncated = False
    if depth is not None:
        for node_id, node_distance in distances.items():
            if node_distance < depth:
                continue
            if include_outgoing and any(edge.target_id not in visited for edge in outgoing.get(node_id, ())):
                truncated = True
                break
            if include_incoming and any(edge.source_id not in visited for edge in incoming.get(node_id, ())):
                truncated = True
                break

    ordered_ids = sorted(
        visited,
        key=lambda node_id: (
            distances[node_id],
            catalog.nodes[node_id].qualified_name or catalog.nodes[node_id].name,
            node_id,
        ),
    )
    ordered_edges = sorted(
        selected_edges,
        key=lambda edge: (edge.source_id, edge.target_id, edge.relationship_type),
    )
    function_count = sum(
        1 for node in catalog.nodes.values() if node.node_type in FUNCTION_NODE_TYPES
    )
    maximum_depth = max(distances.values(), default=0)

    return {
        "schema_version": 1,
        "graph_type": "reachable_call_network",
        "project": {
            "name": catalog.project_name,
        },
        "focus_id": focus_id,
        "traversal": {
            "requested_depth": "all" if depth is None else depth,
            "include_incoming": bool(include_incoming),
            "include_outgoing": bool(include_outgoing),
            "maximum_depth_reached": maximum_depth,
            "complete": not truncated,
        },
        "summary": {
            "node_count": len(ordered_ids),
            "edge_count": len(ordered_edges),
            "repository_function_count": function_count,
            "reachable_fraction": (len(ordered_ids) / function_count) if function_count else 0.0,
        },
        "nodes": [_public_node(catalog.nodes[node_id], distances[node_id]) for node_id in ordered_ids],
        "edges": [_public_edge(edge) for edge in ordered_edges],
    }
