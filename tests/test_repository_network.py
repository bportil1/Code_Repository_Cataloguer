from pathlib import Path

from code_analyzer import CodeAnalyzer


def _network_project(tmp_path: Path) -> tuple[CodeAnalyzer, dict[str, str]]:
    (tmp_path / "network.py").write_text(
        "def alpha(value):\n"
        "    return beta(value)\n\n"
        "def beta(value):\n"
        "    return gamma(value)\n\n"
        "def gamma(value):\n"
        "    return delta(value)\n\n"
        "def delta(value):\n"
        "    if value > 0:\n"
        "        return beta(value - 1)\n"
        "    return value\n\n"
        "def isolated(value):\n"
        "    return value\n",
        encoding="utf-8",
    )
    analyzer = CodeAnalyzer(tmp_path, use_gitignore=False)
    catalog = analyzer.catalog()
    ids = {
        node.name: node_id
        for node_id, node in catalog.nodes.items()
        if node.node_type == "function"
    }
    return analyzer, ids


def test_call_network_all_reachable_is_cycle_safe_and_complete(tmp_path: Path):
    analyzer, ids = _network_project(tmp_path)

    network = analyzer.call_network(ids["alpha"], depth=None, include_incoming=False)

    assert network["graph_type"] == "reachable_call_network"
    assert network["traversal"]["requested_depth"] == "all"
    assert network["traversal"]["complete"] is True
    assert network["traversal"]["maximum_depth_reached"] == 3
    assert network["summary"]["node_count"] == 4
    assert network["summary"]["edge_count"] == 4
    assert network["summary"]["repository_function_count"] == 5
    assert {node["name"] for node in network["nodes"]} == {"alpha", "beta", "gamma", "delta"}
    assert "isolated" not in {node["name"] for node in network["nodes"]}
    distances = {node["name"]: node["distance_from_focus"] for node in network["nodes"]}
    assert distances == {"alpha": 0, "beta": 1, "gamma": 2, "delta": 3}


def test_call_network_finite_depth_reports_truncation(tmp_path: Path):
    analyzer, ids = _network_project(tmp_path)

    network = analyzer.call_network(ids["alpha"], depth=2, include_incoming=False)

    assert network["traversal"]["requested_depth"] == 2
    assert network["traversal"]["maximum_depth_reached"] == 2
    assert network["traversal"]["complete"] is False
    assert {node["name"] for node in network["nodes"]} == {"alpha", "beta", "gamma"}


def test_call_network_can_follow_only_incoming_edges(tmp_path: Path):
    analyzer, ids = _network_project(tmp_path)

    network = analyzer.call_network(
        ids["gamma"],
        depth=None,
        include_incoming=True,
        include_outgoing=False,
    )

    assert {node["name"] for node in network["nodes"]} == {"alpha", "beta", "gamma", "delta"}
    assert network["traversal"]["include_outgoing"] is False


def test_repository_network_http_endpoint_supports_all_depth(tmp_path: Path):
    import pytest

    pytest.importorskip("flask")
    from code_analyzer.web.app import create_app

    analyzer, ids = _network_project(tmp_path)
    app = create_app(tmp_path, use_gitignore=False)
    client = app.test_client()

    response = client.post(
        "/api/repository/network",
        json={
            "focus_id": ids["alpha"],
            "depth": "all",
            "include_incoming": True,
            "include_outgoing": True,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["traversal"]["requested_depth"] == "all"
    assert payload["summary"]["node_count"] == 4
