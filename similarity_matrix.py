from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
from pathlib import Path
from typing import Callable, Iterable, Sequence

from similarity_engine import FunctionGraph, SimilarityConfig, compare_functions

ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True)
class MatrixSummary:
    function_count: int
    computed_pair_count: int
    minimum_off_diagonal: float
    maximum_off_diagonal: float
    mean_off_diagonal: float


@dataclass(frozen=True)
class SimilarityMatrixResult:
    labels: tuple[str, ...]
    matrix: tuple[tuple[float, ...], ...]
    config: SimilarityConfig
    summary: MatrixSummary

    def to_dict(self) -> dict:
        return {
            "labels": list(self.labels),
            "matrix": [list(row) for row in self.matrix],
            "config": asdict(self.config),
            "summary": asdict(self.summary),
        }

    def pair(self, left: str, right: str) -> float:
        index = {label: idx for idx, label in enumerate(self.labels)}
        try:
            return self.matrix[index[left]][index[right]]
        except KeyError as exc:
            raise KeyError(f"Unknown matrix label: {exc.args[0]}") from exc

    def write_csv(self, path: str | Path) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["qualified_name", *self.labels])
            for label, row in zip(self.labels, self.matrix):
                writer.writerow([label, *[f"{value:.10f}" for value in row]])


def compute_similarity_matrix(
    graph: FunctionGraph,
    config: SimilarityConfig | None = None,
    *,
    labels: Sequence[str] | None = None,
    ordering: str = "qualified_name",
    progress: ProgressCallback | None = None,
) -> SimilarityMatrixResult:
    """
    Compute the global function-by-function matrix.

    The local rooted-neighborhood similarity remains unchanged. This function
    applies it to every unordered function pair and mirrors the score to keep
    the matrix symmetric.
    """
    config = config or SimilarityConfig()
    config.validate()

    selected = list(labels) if labels is not None else list(graph.nodes)
    unknown = sorted(set(selected) - set(graph.nodes))
    if unknown:
        raise KeyError(f"Unknown graph nodes: {unknown}")

    if ordering == "qualified_name":
        selected.sort()
    elif ordering == "input":
        pass
    else:
        raise ValueError("ordering must be 'qualified_name' or 'input'")

    n = len(selected)
    matrix = [[0.0] * n for _ in range(n)]
    total = n * (n + 1) // 2
    completed = 0
    off_diagonal: list[float] = []

    for i, left in enumerate(selected):
        for j in range(i, n):
            right = selected[j]
            if i == j:
                score = 1.0
            else:
                score = compare_functions(
                    graph,
                    left,
                    right,
                    config,
                    include_pairs=False,
                ).score
                off_diagonal.append(score)

            matrix[i][j] = score
            matrix[j][i] = score
            completed += 1
            if progress:
                progress(completed, total, f"Comparing {left} ↔ {right}")

    if off_diagonal:
        minimum = min(off_diagonal)
        maximum = max(off_diagonal)
        mean = sum(off_diagonal) / len(off_diagonal)
    else:
        minimum = maximum = mean = 1.0 if n == 1 else 0.0

    return SimilarityMatrixResult(
        labels=tuple(selected),
        matrix=tuple(tuple(row) for row in matrix),
        config=config,
        summary=MatrixSummary(
            function_count=n,
            computed_pair_count=total,
            minimum_off_diagonal=minimum,
            maximum_off_diagonal=maximum,
            mean_off_diagonal=mean,
        ),
    )
