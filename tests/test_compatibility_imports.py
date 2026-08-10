def test_old_top_level_similarity_imports_remain_available():
    from duplicate_candidates import find_duplicate_candidates
    from similarity_clustering import cluster_similarity_matrix
    from similarity_engine import SimilarityConfig
    from similarity_matrix import compute_similarity_matrix

    assert callable(find_duplicate_candidates)
    assert callable(cluster_similarity_matrix)
    assert SimilarityConfig is not None
    assert callable(compute_similarity_matrix)


def test_old_catalog_package_imports_remain_available():
    from catalog.catalog_builder import build_catalog
    from catalog.refactor.function_mover import FunctionMoveService

    assert callable(build_catalog)
    assert FunctionMoveService is not None
