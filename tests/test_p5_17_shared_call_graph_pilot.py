"""P5-17 display-projection contract, independent of PAH and browser runtime."""
import copy

import pytest

from code_analyzer.shared_call_graph_pilot import shared_call_network_graph


def fixture_network():
    return {
        "schema_version": 1,
        "graph_type": "reachable_call_network",
        "traversal": {"complete": False, "requested_depth": 1},
        "nodes": [
            {"id": "a", "node_type": "function", "name": "alpha", "qualified_name": "m.alpha", "path": "m.py", "line_start": 1},
            {"id": "b", "node_type": "method", "name": "beta", "qualified_name": "C.beta", "path": "m.py", "line_start": 4},
        ],
        "edges": [
            {"source_id": "a", "target_id": "b", "relationship_type": "calls", "evidence": {"line": 2}},
            {"source_id": "a", "target_id": "b", "relationship_type": "calls", "evidence": {"line": 3}},
        ],
    }


def test_projection_preserves_edges_and_producer_positions_without_mutating_evidence():
    network = fixture_network()
    before = copy.deepcopy(network)
    positions = {"a": (0, 1), "b": (2, 3)}
    result = shared_call_network_graph(network, positions)
    assert result["schema"] == "pah-shared.graph@1"
    assert result["nodes"][1] == {"id": "b", "label": "C.beta", "x": 2.0, "y": 3.0}
    assert [(e["source"], e["target"], e["directed"]) for e in result["edges"]] == [("a", "b", True)] * 2
    assert result["edges"][0]["id"] != result["edges"][1]["id"]
    assert "evidence" not in result["edges"][0]
    assert network == before


def test_missing_or_nonfinite_positions_rejected():
    network = fixture_network()
    with pytest.raises(ValueError, match="Missing explicit"):
        shared_call_network_graph(network, {"a": (0, 0)})
    with pytest.raises(ValueError, match="Invalid display"):
        shared_call_network_graph(network, {"a": (0, 0), "b": (float("nan"), 1)})


def test_incompatible_graph_and_dangling_or_unresolved_edges_rejected():
    network = fixture_network()
    positions = {"a": (0, 0), "b": (1, 0)}
    network["graph_type"] = "repository_map"
    with pytest.raises(ValueError, match="reachable_call_network"):
        shared_call_network_graph(network, positions)
    network["graph_type"] = "reachable_call_network"
    network["edges"][0]["relationship_type"] = "imports"
    with pytest.raises(ValueError, match="resolved call"):
        shared_call_network_graph(network, positions)
    network["edges"][0]["relationship_type"] = "calls"
    network["edges"][0]["target_id"] = "unknown"
    with pytest.raises(ValueError, match="absent"):
        shared_call_network_graph(network, positions)


def test_resource_limit_and_duplicate_ids():
    network = fixture_network()
    network["nodes"].append(dict(network["nodes"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        shared_call_network_graph(network, {"a": (0, 0), "b": (1, 0)})
    network = fixture_network()
    network["edges"] *= 5001
    with pytest.raises(ValueError, match="resource limits"):
        shared_call_network_graph(network, {"a": (0, 0), "b": (1, 0)})
