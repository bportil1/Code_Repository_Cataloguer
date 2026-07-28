from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Sequence

from similarity_engine import FunctionGraph

import numpy as np

from similarity_matrix import SimilarityMatrixResult


@dataclass(frozen=True)
class ClusterPoint:
    function_id: str
    cluster: int
    x: float
    y: float
    distance_to_centroid: float


@dataclass(frozen=True)
class ClusterSummary:
    cluster: int
    size: int
    representative_id: str
    mean_distance: float


@dataclass(frozen=True)
class SimilarityClusterResult:
    k: int
    inertia: float
    iterations: int
    points: tuple[ClusterPoint, ...]
    clusters: tuple[ClusterSummary, ...]

    def to_dict(self) -> dict:
        return {
            "k": self.k,
            "inertia": self.inertia,
            "iterations": self.iterations,
            "points": [asdict(point) for point in self.points],
            "clusters": [asdict(cluster) for cluster in self.clusters],
        }


def _pca_2d(features: np.ndarray) -> np.ndarray:
    if features.shape[0] == 0:
        return np.empty((0, 2), dtype=float)
    centered = features - features.mean(axis=0, keepdims=True)
    if centered.shape[0] == 1 or np.allclose(centered, 0.0):
        return np.zeros((centered.shape[0], 2), dtype=float)
    u, singular_values, _ = np.linalg.svd(centered, full_matrices=False)
    components = u[:, :2] * singular_values[:2]
    if components.shape[1] == 1:
        components = np.column_stack([components[:, 0], np.zeros(components.shape[0])])
    return components


def _kmeans_plus_plus(features: np.ndarray, k: int, rng: np.random.Generator) -> np.ndarray:
    n = features.shape[0]
    centers = [features[rng.integers(0, n)].copy()]
    while len(centers) < k:
        distances = np.min(
            np.stack([np.sum((features - center) ** 2, axis=1) for center in centers]),
            axis=0,
        )
        total = float(distances.sum())
        if total <= 0:
            remaining = [i for i in range(n) if not any(np.array_equal(features[i], c) for c in centers)]
            index = remaining[0] if remaining else int(rng.integers(0, n))
        else:
            index = int(rng.choice(n, p=distances / total))
        centers.append(features[index].copy())
    return np.asarray(centers, dtype=float)



def cluster_common_factors(
    graph: FunctionGraph,
    result: SimilarityClusterResult,
    *,
    limit: int = 25,
) -> dict[int, list[dict[str, object]]]:
    """Rank descriptor factors that are prevalent and distinctive per cluster.

    Each function contributes at most one presence count per factor so large
    functions cannot dominate the explanation through repeated tokens.
    """
    all_ids = [point.function_id for point in result.points]
    repository_size = len(all_ids)
    presence = {
        function_id: set(graph.nodes[function_id].descriptor_counts())
        for function_id in all_ids
        if function_id in graph.nodes
    }
    repository_counts: dict[str, int] = {}
    for factors in presence.values():
        for factor in factors:
            repository_counts[factor] = repository_counts.get(factor, 0) + 1

    grouped: dict[int, list[str]] = {cluster.cluster: [] for cluster in result.clusters}
    for point in result.points:
        grouped[point.cluster].append(point.function_id)

    output: dict[int, list[dict[str, object]]] = {}
    for cluster_id, member_ids in grouped.items():
        cluster_size = len(member_ids)
        cluster_counts: dict[str, int] = {}
        for function_id in member_ids:
            for factor in presence.get(function_id, set()):
                cluster_counts[factor] = cluster_counts.get(factor, 0) + 1

        rows: list[dict[str, object]] = []
        for factor, count in cluster_counts.items():
            namespace, _, value = factor.partition(":")
            cluster_prevalence = count / cluster_size if cluster_size else 0.0
            repository_prevalence = (
                repository_counts.get(factor, 0) / repository_size
                if repository_size else 0.0
            )
            rows.append({
                "factor": factor,
                "namespace": namespace,
                "value": value,
                "cluster_count": count,
                "cluster_prevalence": cluster_prevalence,
                "repository_prevalence": repository_prevalence,
                "distinctiveness": cluster_prevalence - repository_prevalence,
            })

        rows.sort(
            key=lambda row: (
                float(row["distinctiveness"]),
                float(row["cluster_prevalence"]),
                int(row["cluster_count"]),
                str(row["factor"]),
            ),
            reverse=True,
        )
        output[cluster_id] = rows[: max(1, int(limit))]
    return output

def cluster_similarity_matrix(
    result: SimilarityMatrixResult,
    *,
    k: int = 3,
    random_state: int = 42,
    max_iterations: int = 100,
    tolerance: float = 1e-6,
) -> SimilarityClusterResult:
    labels: Sequence[str] = result.labels
    features = np.asarray(result.matrix, dtype=float)
    n = features.shape[0]
    if n == 0:
        raise ValueError("Cannot cluster an empty similarity matrix.")
    if k < 1 or k > n:
        raise ValueError(f"k must be between 1 and {n}.")

    rng = np.random.default_rng(random_state)
    centers = _kmeans_plus_plus(features, k, rng)
    assignments = np.zeros(n, dtype=int)
    iterations = 0

    for iterations in range(1, max_iterations + 1):
        squared = np.stack([np.sum((features - center) ** 2, axis=1) for center in centers], axis=1)
        new_assignments = np.argmin(squared, axis=1)
        new_centers = centers.copy()
        for cluster_id in range(k):
            member_indices = np.where(new_assignments == cluster_id)[0]
            if len(member_indices):
                new_centers[cluster_id] = features[member_indices].mean(axis=0)
            else:
                # Repair an empty cluster by moving the point currently farthest
                # from its assigned centroid into the empty cluster. Updating the
                # assignment here guarantees the final summaries are never empty.
                assigned_distance = squared[np.arange(n), new_assignments]
                counts = np.bincount(new_assignments, minlength=k)
                candidates = np.where(counts[new_assignments] > 1)[0]
                if len(candidates) == 0:
                    candidates = np.arange(n)
                farthest = int(candidates[np.argmax(assigned_distance[candidates])])
                new_assignments[farthest] = cluster_id
                new_centers[cluster_id] = features[farthest]
        shift = float(np.linalg.norm(new_centers - centers))
        centers = new_centers
        assignments = new_assignments
        if shift <= tolerance:
            break

    distances = np.linalg.norm(features - centers[assignments], axis=1)
    inertia = float(np.sum(distances ** 2))
    coordinates = _pca_2d(features)

    points = tuple(
        ClusterPoint(
            function_id=str(labels[index]),
            cluster=int(assignments[index]),
            x=float(coordinates[index, 0]),
            y=float(coordinates[index, 1]),
            distance_to_centroid=float(distances[index]),
        )
        for index in range(n)
    )

    summaries: list[ClusterSummary] = []
    for cluster_id in range(k):
        member_indices = np.where(assignments == cluster_id)[0]
        if len(member_indices) == 0:
            raise RuntimeError(f"K-means produced empty cluster {cluster_id}.")
        representative_index = int(member_indices[np.argmin(distances[member_indices])])
        summaries.append(
            ClusterSummary(
                cluster=cluster_id,
                size=int(len(member_indices)),
                representative_id=str(labels[representative_index]),
                mean_distance=float(np.mean(distances[member_indices])),
            )
        )

    return SimilarityClusterResult(
        k=k,
        inertia=inertia,
        iterations=iterations,
        points=points,
        clusters=tuple(summaries),
    )
