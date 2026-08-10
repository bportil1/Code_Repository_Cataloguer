"""Similarity, duplication, matrix, and clustering analysis."""

from .engine import FunctionGraph, SimilarityConfig, compare_functions
from .matrix import SimilarityMatrixResult, compute_similarity_matrix

__all__ = [
    "FunctionGraph",
    "SimilarityConfig",
    "SimilarityMatrixResult",
    "compare_functions",
    "compute_similarity_matrix",
]
