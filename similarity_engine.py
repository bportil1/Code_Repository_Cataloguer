from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from math import sqrt
import re
from typing import Iterable, Mapping

_TOKEN_BOUNDARY_1 = re.compile(r"([a-z0-9])([A-Z])")
_TOKEN_BOUNDARY_2 = re.compile(r"[^A-Za-z0-9]+")


def tokenize_identifier(value: str) -> tuple[str, ...]:
    """Split snake_case, dotted names, and camelCase identifiers."""
    value = _TOKEN_BOUNDARY_1.sub(r"\1 \2", value)
    return tuple(token.lower() for token in _TOKEN_BOUNDARY_2.split(value) if token)


@dataclass(frozen=True)
class FunctionNode:
    qualified_name: str
    name: str
    parameters: tuple[str, ...] = ()
    variables: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    objects: tuple[str, ...] = ()
    calls: tuple[str, ...] = ()
    external_imports: tuple[str, ...] = ()

    def descriptor_counts(self) -> Counter[str]:
        features: Counter[str] = Counter()

        def add(namespace: str, values: Iterable[str]) -> None:
            for value in values:
                for token in tokenize_identifier(value):
                    features[f"{namespace}:{token}"] += 1

        add("name", (self.name,))
        add("parameter", self.parameters)
        add("variable", self.variables)
        add("keyword", self.keywords)
        add("object", self.objects)
        add("call", self.calls)
        add("external", self.external_imports)
        return features


@dataclass(frozen=True)
class CallEdge:
    source: str
    target: str
    is_external: bool = False


@dataclass
class SimilarityConfig:
    context_depth: int = 1
    distance_decay: float = 0.5
    internal_edge_weight: float = 1.0
    external_import_weight: float = 0.20
    node_weight: float = 1.0

    def validate(self) -> None:
        if self.context_depth < 0:
            raise ValueError("context_depth must be non-negative")
        if not 0.0 <= self.distance_decay <= 1.0:
            raise ValueError("distance_decay must be between 0 and 1")
        for name in ("internal_edge_weight", "external_import_weight", "node_weight"):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True)
class LayerScore:
    distance: int
    node_similarity: float
    edge_similarity: float
    combined_similarity: float
    distance_weight: float
    left_count: int
    right_count: int
    pair_count: int


@dataclass(frozen=True)
class SimilarityResult:
    left_root: str
    right_root: str
    score: float
    layers: tuple[LayerScore, ...]
    pairwise_comparisons: tuple[tuple[str, str, float, int], ...] = ()

    def to_dict(self, *, include_pairs: bool = True) -> dict:
        payload = {
            "left_root": self.left_root,
            "right_root": self.right_root,
            "score": self.score,
            "layers": [asdict(layer) for layer in self.layers],
        }
        if include_pairs:
            payload["pairwise_comparisons"] = [
                {"left": left, "right": right, "score": score, "distance": distance}
                for left, right, score, distance in self.pairwise_comparisons
            ]
        return payload


class FunctionGraph:
    def __init__(self, nodes: Iterable[FunctionNode], edges: Iterable[CallEdge]) -> None:
        self.nodes = {node.qualified_name: node for node in nodes}
        self.outgoing: dict[str, list[CallEdge]] = defaultdict(list)
        self.incoming: dict[str, list[CallEdge]] = defaultdict(list)

        for edge in edges:
            if edge.source not in self.nodes:
                raise KeyError(f"Unknown edge source: {edge.source}")
            if not edge.is_external and edge.target not in self.nodes:
                raise KeyError(f"Unknown internal edge target: {edge.target}")
            self.outgoing[edge.source].append(edge)
            if not edge.is_external:
                self.incoming[edge.target].append(edge)

    def layers(self, root: str, depth: int) -> dict[int, set[str]]:
        """Return incoming/outgoing call layers by shortest path from root."""
        if root not in self.nodes:
            raise KeyError(f"Unknown root node: {root}")

        result: dict[int, set[str]] = {0: {root}}
        visited = {root}
        queue = deque([(root, 0)])

        while queue:
            current, distance = queue.popleft()
            if distance >= depth:
                continue

            neighbors = {
                edge.target for edge in self.outgoing[current] if not edge.is_external
            }
            neighbors.update(edge.source for edge in self.incoming[current])

            for neighbor in sorted(neighbors):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                next_distance = distance + 1
                result.setdefault(next_distance, set()).add(neighbor)
                queue.append((neighbor, next_distance))

        for distance in range(depth + 1):
            result.setdefault(distance, set())
        return result


def cosine_similarity(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(left[key] * right[key] for key in left.keys() & right.keys())
    left_norm = sqrt(sum(value * value for value in left.values()))
    right_norm = sqrt(sum(value * value for value in right.values()))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def node_similarity(left: FunctionNode, right: FunctionNode) -> float:
    return cosine_similarity(left.descriptor_counts(), right.descriptor_counts())


def _all_pair_node_similarity(
    graph: FunctionGraph,
    left_nodes: set[str],
    right_nodes: set[str],
) -> tuple[float, tuple[tuple[str, str, float], ...]]:
    """Average every Cartesian-product comparison in corresponding layers."""
    if not left_nodes and not right_nodes:
        return 1.0, ()
    if not left_nodes or not right_nodes:
        return 0.0, ()

    comparisons = tuple(
        (left, right, node_similarity(graph.nodes[left], graph.nodes[right]))
        for left in sorted(left_nodes)
        for right in sorted(right_nodes)
    )
    return (
        sum(score for _, _, score in comparisons) / len(comparisons),
        comparisons,
    )


def _edge_counts(graph: FunctionGraph, layer: set[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for node in layer:
        for edge in graph.outgoing[node]:
            counts["external_outgoing" if edge.is_external else "internal_outgoing"] += 1
        counts["internal_incoming"] += len(graph.incoming[node])
    return counts


def _edge_similarity(
    graph: FunctionGraph,
    left_layer: set[str],
    right_layer: set[str],
    config: SimilarityConfig,
) -> float:
    left = _edge_counts(graph, left_layer)
    right = _edge_counts(graph, right_layer)
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0

    matched = 0.0
    maximum = 0.0
    for signature in left.keys() | right.keys():
        weight = (
            config.external_import_weight
            if signature.startswith("external")
            else config.internal_edge_weight
        )
        matched += min(left[signature], right[signature]) * weight
        maximum += max(left[signature], right[signature]) * weight
    return matched / maximum if maximum else 0.0


def compare_functions(
    graph: FunctionGraph,
    left_root: str,
    right_root: str,
    config: SimilarityConfig | None = None,
    *,
    include_pairs: bool = True,
) -> SimilarityResult:
    config = config or SimilarityConfig()
    config.validate()

    left_layers = graph.layers(left_root, config.context_depth)
    right_layers = graph.layers(right_root, config.context_depth)
    layer_results: list[LayerScore] = []
    all_pairs: list[tuple[str, str, float, int]] = []
    weighted_total = 0.0
    total_weight = 0.0

    for distance in range(config.context_depth + 1):
        left_nodes = left_layers[distance]
        right_nodes = right_layers[distance]
        node_score, comparisons = _all_pair_node_similarity(
            graph, left_nodes, right_nodes
        )
        if include_pairs:
            all_pairs.extend(
                (left, right, score, distance)
                for left, right, score in comparisons
            )

        edge_score = _edge_similarity(graph, left_nodes, right_nodes, config)
        denominator = config.node_weight + 1.0
        combined = (
            (config.node_weight * node_score + edge_score) / denominator
            if denominator
            else 0.0
        )
        distance_weight = config.distance_decay ** distance
        weighted_total += combined * distance_weight
        total_weight += distance_weight
        layer_results.append(
            LayerScore(
                distance=distance,
                node_similarity=node_score,
                edge_similarity=edge_score,
                combined_similarity=combined,
                distance_weight=distance_weight,
                left_count=len(left_nodes),
                right_count=len(right_nodes),
                pair_count=len(comparisons),
            )
        )

    return SimilarityResult(
        left_root=left_root,
        right_root=right_root,
        score=weighted_total / total_weight if total_weight else 0.0,
        layers=tuple(layer_results),
        pairwise_comparisons=tuple(all_pairs),
    )
