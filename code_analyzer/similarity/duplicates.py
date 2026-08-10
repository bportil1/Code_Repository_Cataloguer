from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations
from math import sqrt
from typing import Any

from .engine import FunctionGraph, SimilarityConfig, compare_functions


@dataclass(frozen=True)
class SharedFactor:
    factor: str
    namespace: str
    value: str
    left_count: int
    right_count: int
    matched_count: int
    cosine_contribution: float


@dataclass(frozen=True)
class DuplicateCandidate:
    left_id: str
    right_id: str
    score: float
    root_similarity: float
    shared_factor_count: int
    shared_factors: tuple[SharedFactor, ...]
    explanation: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["shared_factors"] = [asdict(item) for item in self.shared_factors]
        payload["explanation"] = list(self.explanation)
        return payload


def _shared_factors(graph: FunctionGraph, left_id: str, right_id: str, limit: int) -> tuple[SharedFactor, ...]:
    left = graph.nodes[left_id].descriptor_counts()
    right = graph.nodes[right_id].descriptor_counts()
    left_norm = sqrt(sum(value * value for value in left.values()))
    right_norm = sqrt(sum(value * value for value in right.values()))
    denominator = left_norm * right_norm

    factors: list[SharedFactor] = []
    for factor in left.keys() & right.keys():
        namespace, _, value = factor.partition(":")
        cosine_contribution = (left[factor] * right[factor] / denominator) if denominator else 0.0
        factors.append(
            SharedFactor(
                factor=factor,
                namespace=namespace,
                value=value,
                left_count=int(left[factor]),
                right_count=int(right[factor]),
                matched_count=int(min(left[factor], right[factor])),
                cosine_contribution=cosine_contribution,
            )
        )

    factors.sort(
        key=lambda item: (
            -item.cosine_contribution,
            -item.matched_count,
            item.namespace,
            item.value,
        )
    )
    return tuple(factors[:limit])


def _explain(factors: tuple[SharedFactor, ...], root_similarity: float, score: float) -> tuple[str, ...]:
    messages: list[str] = []
    by_namespace: dict[str, list[str]] = {}
    for factor in factors:
        by_namespace.setdefault(factor.namespace, []).append(factor.value)

    labels = {
        "call": "shared calls",
        "parameter": "similarly named parameters",
        "variable": "similarly named local variables",
        "keyword": "shared control-flow constructs",
        "object": "shared referenced objects",
        "external": "shared external dependencies",
        "name": "overlapping name tokens",
    }
    for namespace in ("call", "parameter", "variable", "keyword", "object", "external", "name"):
        values = by_namespace.get(namespace, [])
        if values:
            preview = ", ".join(values[:4])
            messages.append(f"{labels[namespace]}: {preview}")

    if score > root_similarity + 0.05:
        messages.append("their surrounding call neighborhoods increase the overall similarity")
    elif root_similarity > score + 0.05:
        messages.append("their local descriptors are more similar than their surrounding call neighborhoods")

    return tuple(messages[:5])


def find_duplicate_candidates(
    graph: FunctionGraph,
    config: SimilarityConfig | None = None,
    *,
    threshold: float = 0.65,
    limit: int = 50,
    factor_limit: int = 12,
) -> dict[str, Any]:
    config = config or SimilarityConfig()
    config.validate()
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be between 0 and 1")
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if factor_limit < 1:
        raise ValueError("factor_limit must be at least 1")

    candidates: list[DuplicateCandidate] = []
    compared = 0
    labels = sorted(graph.nodes)
    all_scores: list[float] = []
    nearest_scores: dict[str, float] = {label: 0.0 for label in labels}
    duplicate_functions: set[str] = set()

    for left_id, right_id in combinations(labels, 2):
        compared += 1
        result = compare_functions(graph, left_id, right_id, config, include_pairs=False)
        score = float(result.score)
        all_scores.append(score)
        nearest_scores[left_id] = max(nearest_scores[left_id], score)
        nearest_scores[right_id] = max(nearest_scores[right_id], score)
        if score < threshold:
            continue
        duplicate_functions.update((left_id, right_id))

        root_similarity = result.layers[0].node_similarity if result.layers else 0.0
        factors = _shared_factors(graph, left_id, right_id, factor_limit)
        candidates.append(
            DuplicateCandidate(
                left_id=left_id,
                right_id=right_id,
                score=result.score,
                root_similarity=root_similarity,
                shared_factor_count=len(graph.nodes[left_id].descriptor_counts().keys() & graph.nodes[right_id].descriptor_counts().keys()),
                shared_factors=factors,
                explanation=_explain(factors, root_similarity, result.score),
            )
        )

    candidates.sort(
        key=lambda item: (-item.score, -item.root_similarity, -item.shared_factor_count, item.left_id, item.right_id)
    )
    selected = candidates[:limit]
    function_count = len(labels)
    duplicate_pair_rate = (len(candidates) / compared) if compared else 0.0
    duplicate_function_coverage = (len(duplicate_functions) / function_count) if function_count else 0.0
    mean_pair_similarity = (sum(all_scores) / len(all_scores)) if all_scores else 0.0
    mean_nearest_neighbor_similarity = (
        sum(nearest_scores.values()) / function_count if function_count else 0.0
    )
    denominator = max(1e-12, 1.0 - threshold)
    function_duplication_burden = (
        sum(max(0.0, score - threshold) / denominator for score in nearest_scores.values()) / function_count
        if function_count else 0.0
    )

    return {
        "candidates": [item.to_dict() for item in selected],
        "summary": {
            "function_count": function_count,
            "compared_pair_count": compared,
            "matching_pair_count": len(candidates),
            "returned_pair_count": len(selected),
            "threshold": threshold,
            "duplicate_function_count": len(duplicate_functions),
            "duplicate_pair_rate": duplicate_pair_rate,
            "duplicate_function_coverage": duplicate_function_coverage,
            "mean_pair_similarity": mean_pair_similarity,
            "mean_nearest_neighbor_similarity": mean_nearest_neighbor_similarity,
            "function_duplication_burden": function_duplication_burden,
        },
        "config": asdict(config),
    }
