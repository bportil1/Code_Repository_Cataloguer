from similarity_clustering import cluster_similarity_matrix
from similarity_engine import SimilarityConfig
from similarity_matrix import MatrixSummary, SimilarityMatrixResult


def sample_matrix():
    return SimilarityMatrixResult(
        labels=("a", "b", "c", "d"),
        matrix=(
            (1.0, .95, .10, .08),
            (.95, 1.0, .12, .09),
            (.10, .12, 1.0, .92),
            (.08, .09, .92, 1.0),
        ),
        config=SimilarityConfig(),
        summary=MatrixSummary(4, 10, .08, .95, .3767),
    )


def test_kmeans_groups_two_clear_pairs():
    result = cluster_similarity_matrix(sample_matrix(), k=2, random_state=42)
    assignments = {point.function_id: point.cluster for point in result.points}
    assert assignments["a"] == assignments["b"]
    assert assignments["c"] == assignments["d"]
    assert assignments["a"] != assignments["c"]
    assert sum(cluster.size for cluster in result.clusters) == 4


def test_projection_returns_finite_coordinates():
    result = cluster_similarity_matrix(sample_matrix(), k=2)
    assert all(abs(point.x) < 100 and abs(point.y) < 100 for point in result.points)


def test_kmeans_repairs_empty_clusters_for_duplicate_profiles():
    result = SimilarityMatrixResult(
        labels=("a", "b", "c"),
        matrix=((1.0, 1.0, 1.0), (1.0, 1.0, 1.0), (1.0, 1.0, 1.0)),
        config=SimilarityConfig(),
        summary=MatrixSummary(3, 6, 1.0, 1.0, 1.0),
    )
    clustered = cluster_similarity_matrix(result, k=3, random_state=42)
    assert sorted(cluster.size for cluster in clustered.clusters) == [1, 1, 1]
    assert len(clustered.points) == 3


def test_cluster_common_factors_rank_distinctive_presence():
    from similarity_clustering import cluster_common_factors
    from similarity_engine import FunctionGraph, FunctionNode

    graph = FunctionGraph(
        [
            FunctionNode("a", "train_step", calls=("backward",), objects=("optimizer",)),
            FunctionNode("b", "train_epoch", calls=("backward",), objects=("optimizer",)),
            FunctionNode("c", "load_file", calls=("open",), objects=("path",)),
        ],
        [],
    )
    matrix = SimilarityMatrixResult(
        labels=("a", "b", "c"),
        matrix=((1.0, .9, .1), (.9, 1.0, .1), (.1, .1, 1.0)),
        config=SimilarityConfig(),
        summary=MatrixSummary(3, 6, .1, .9, .3666666667),
    )
    result = cluster_similarity_matrix(matrix, k=2, random_state=1)
    factors = cluster_common_factors(graph, result, limit=25)
    training_cluster = next(point.cluster for point in result.points if point.function_id == "a")
    names = {row["factor"] for row in factors[training_cluster]}
    assert "call:backward" in names
    assert "object:optimizer" in names
    backward = next(row for row in factors[training_cluster] if row["factor"] == "call:backward")
    assert backward["cluster_prevalence"] == 1.0
    assert backward["distinctiveness"] > 0
