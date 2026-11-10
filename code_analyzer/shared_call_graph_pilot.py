"""P5-17 optional, read-only presentation of Code Analyzer call-network snapshots.

The input is the existing ``build_reachable_call_network`` result. This module
never traverses the AST, infers coordinates, or modifies source relationships.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

SCHEMA = "pah-shared.graph@1"
MAX_NODES = 2000
MAX_EDGES = 10000


def shared_call_network_graph(
    network: Mapping[str, Any],
    positions: Mapping[str, tuple[float, float]],
    *,
    title: str = "Call network",
) -> dict[str, Any]:
    """Project a source-owned call network to a display-only shared graph.

    ``positions`` must supply an (x,y) coordinate for every network node.
    The returned graph deliberately omits AST evidence, paths, line numbers,
    and traversal metadata because graph@1 cannot encode them. Preserve the
    original ``network`` for all evidence and completeness decisions.
    """
    if not isinstance(network, Mapping) or network.get("schema_version") != 1 or network.get("graph_type") != "reachable_call_network":
        raise ValueError("Expected Code Analyzer reachable_call_network schema v1")
    if not isinstance(positions, Mapping):
        raise ValueError("positions must be an explicit node-id mapping")
    if not isinstance(title, str) or len(title) > 240:
        raise ValueError("Invalid graph title")
    raw_nodes, raw_edges = network.get("nodes"), network.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise ValueError("Network nodes and edges must be lists")
    if len(raw_nodes) > MAX_NODES or len(raw_edges) > MAX_EDGES:
        raise ValueError("Network exceeds shared graph resource limits")
    nodes = []
    seen = set()
    for raw in raw_nodes:
        if not isinstance(raw, Mapping):
            raise ValueError("Invalid call-network node")
        node_id = raw.get("id")
        if not isinstance(node_id, str) or not node_id or len(node_id) > 96 or node_id in seen:
            raise ValueError("Invalid or duplicate call-network node ID")
        if raw.get("node_type") not in ("function", "method"):
            raise ValueError("Call-network node must be a function or method")
        if node_id not in positions:
            raise ValueError(f"Missing explicit position for {node_id}")
        pair = positions[node_id]
        if not isinstance(pair, (tuple, list)) or len(pair) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in pair):
            raise ValueError(f"Invalid display position for {node_id}")
        label = raw.get("qualified_name") or raw.get("name") or node_id
        if not isinstance(label, str) or len(label) > 240:
            raise ValueError("Invalid node label")
        nodes.append({"id": node_id, "label": label, "x": float(pair[0]), "y": float(pair[1])})
        seen.add(node_id)
    edges = []
    for index, raw in enumerate(raw_edges):
        if not isinstance(raw, Mapping) or raw.get("relationship_type") != "calls":
            raise ValueError("Only existing resolved call edges are supported")
        source, target = raw.get("source_id"), raw.get("target_id")
        if source not in seen or target not in seen:
            raise ValueError("Call edge endpoint absent from network")
        # Each input edge gets a distinct display ID, including parallel edges.
        edges.append({"id": f"call-{index}", "source": source, "target": target, "directed": True, "label": "calls"})
    return {"schema": SCHEMA, "title": title, "nodes": nodes, "edges": edges}
