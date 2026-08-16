from pathlib import Path

from code_analyzer import CodeAnalyzer


def test_catalog_records_function_level_import_usage(tmp_path: Path):
    (tmp_path / "sample.py").write_text(
        "import numpy as np\n"
        "import numba\n"
        "from math import sqrt\n\n"
        "def transform(values):\n"
        "    return np.asarray(values)\n\n"
        "def magnitude(value):\n"
        "    return sqrt(value)\n\n"
        "def plain(value):\n"
        "    return value + 1\n",
        encoding="utf-8",
    )

    catalog = CodeAnalyzer(tmp_path, use_gitignore=False).catalog()
    usage_edges = [
        edge for edge in catalog.relationships if edge.relationship_type == "uses_import"
    ]

    transform_id = next(
        node_id for node_id, node in catalog.nodes.items()
        if node.node_type == "function" and node.name == "transform"
    )
    magnitude_id = next(
        node_id for node_id, node in catalog.nodes.items()
        if node.node_type == "function" and node.name == "magnitude"
    )
    plain_id = next(
        node_id for node_id, node in catalog.nodes.items()
        if node.node_type == "function" and node.name == "plain"
    )

    transform_edges = [edge for edge in usage_edges if edge.source_id == transform_id]
    magnitude_edges = [edge for edge in usage_edges if edge.source_id == magnitude_id]

    assert {edge.target_id for edge in transform_edges} == {"external:numpy"}
    assert transform_edges[0].evidence["binding"] == "np"
    assert "np.asarray" in transform_edges[0].evidence["expressions"]
    assert {edge.target_id for edge in magnitude_edges} == {"external:math"}
    assert not [edge for edge in usage_edges if edge.source_id == plain_id]
    assert not [edge for edge in usage_edges if edge.target_id == "external:numba"]


def test_similarity_neighbor_query_is_ranked(tmp_path: Path):
    (tmp_path / "a.py").write_text(
        "def normalize(values):\n"
        "    mean = sum(values) / len(values)\n"
        "    return [value - mean for value in values]\n\n"
        "def center(data):\n"
        "    mean = sum(data) / len(data)\n"
        "    return [value - mean for value in data]\n\n"
        "def write(path):\n"
        "    return open(path, 'w')\n",
        encoding="utf-8",
    )
    analyzer = CodeAnalyzer(tmp_path, use_gitignore=False)
    catalog = analyzer.catalog()
    normalize_id = next(
        node_id for node_id, node in catalog.nodes.items()
        if node.node_type == "function" and node.name == "normalize"
    )
    center_id = next(
        node_id for node_id, node in catalog.nodes.items()
        if node.node_type == "function" and node.name == "center"
    )

    result = analyzer.similarity_neighbors(normalize_id, limit=2)
    assert result["neighbors"]
    assert result["neighbors"][0]["id"] == center_id
    assert result["neighbors"][0]["score"] >= result["neighbors"][-1]["score"]
