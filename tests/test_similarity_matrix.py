import math

from similarity_engine import CallEdge, FunctionGraph, FunctionNode, SimilarityConfig, compare_functions
from similarity_matrix import compute_similarity_matrix


def make_graph():
    nodes = [
        FunctionNode("a.load", "load_data", parameters=("path",), calls=("read_csv",)),
        FunctionNode("a.clean", "clean_data", parameters=("data",), variables=("normalized_data",)),
        FunctionNode("b.load", "read_dataset", parameters=("file_path",), calls=("read_csv",)),
        FunctionNode("b.clean", "normalize_dataset", parameters=("dataset",), variables=("normalized_dataset",)),
    ]
    edges = [
        CallEdge("a.load", "a.clean"),
        CallEdge("b.load", "b.clean"),
    ]
    return FunctionGraph(nodes, edges)


def test_all_pairs_are_recorded_per_layer():
    graph = make_graph()
    result = compare_functions(
        graph,
        "a.load",
        "b.load",
        SimilarityConfig(context_depth=1),
    )
    assert result.layers[0].pair_count == 1
    assert result.layers[1].pair_count == 1
    assert len(result.pairwise_comparisons) == 2


def test_matrix_is_symmetric_and_diagonal_is_one():
    result = compute_similarity_matrix(make_graph(), SimilarityConfig(context_depth=1))
    n = len(result.labels)
    assert n == 4
    for i in range(n):
        assert result.matrix[i][i] == 1.0
        for j in range(n):
            assert math.isclose(result.matrix[i][j], result.matrix[j][i])


def test_matrix_matches_direct_local_comparison():
    graph = make_graph()
    config = SimilarityConfig(context_depth=1, distance_decay=0.5)
    matrix = compute_similarity_matrix(graph, config)
    direct = compare_functions(graph, "a.load", "b.load", config, include_pairs=False)
    assert math.isclose(matrix.pair("a.load", "b.load"), direct.score)


def test_upper_triangle_pair_count():
    result = compute_similarity_matrix(make_graph())
    assert result.summary.computed_pair_count == 4 * 5 // 2
