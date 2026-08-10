from code_analyzer.similarity.duplicates import find_duplicate_candidates
from code_analyzer.similarity.engine import CallEdge, FunctionGraph, FunctionNode, SimilarityConfig


def make_graph():
    nodes = [
        FunctionNode("a.normalize", "normalize_values", parameters=("values",), variables=("mean", "centered"), calls=("mean",), keywords=("return",)),
        FunctionNode("b.center", "center_data", parameters=("data",), variables=("mean", "centered"), calls=("mean",), keywords=("return",)),
        FunctionNode("c.write", "write_report", parameters=("path",), variables=("handle",), calls=("open", "write"), keywords=("with",)),
    ]
    return FunctionGraph(nodes, [CallEdge("a.normalize", "c.write"), CallEdge("b.center", "c.write")])


def test_duplicate_candidates_are_ranked_and_explained():
    result = find_duplicate_candidates(
        make_graph(),
        SimilarityConfig(context_depth=1),
        threshold=0.25,
        limit=10,
    )
    summary = result["summary"]
    assert summary["compared_pair_count"] == 3
    assert 0.0 <= summary["duplicate_pair_rate"] <= 1.0
    assert 0.0 <= summary["duplicate_function_coverage"] <= 1.0
    assert 0.0 <= summary["mean_pair_similarity"] <= 1.0
    assert 0.0 <= summary["mean_nearest_neighbor_similarity"] <= 1.0
    assert 0.0 <= summary["function_duplication_burden"] <= 1.0
    assert summary["duplicate_function_count"] >= 2
    assert result["candidates"]
    first = result["candidates"][0]
    assert {first["left_id"], first["right_id"]} == {"a.normalize", "b.center"}
    assert first["shared_factors"]
    assert any(row["factor"] == "call:mean" for row in first["shared_factors"])
    assert first["explanation"]


def test_threshold_validation():
    try:
        find_duplicate_candidates(make_graph(), threshold=1.5)
    except ValueError as exc:
        assert "threshold" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_repo_metrics_drop_when_threshold_excludes_all_pairs():
    result = find_duplicate_candidates(make_graph(), threshold=1.0, limit=10)
    summary = result["summary"]
    assert summary["matching_pair_count"] == 0
    assert summary["duplicate_pair_rate"] == 0.0
    assert summary["duplicate_function_coverage"] == 0.0
    assert summary["function_duplication_burden"] == 0.0
