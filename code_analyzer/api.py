from __future__ import annotations

from contextlib import contextmanager
import csv
import io
from pathlib import Path
import sqlite3
from typing import Iterator
from typing import Iterable

try:
    from pah_jobs.exchange import observed as _monitor
except ImportError:
    def _monitor(owner, label):
        return lambda function: function

from .catalog.models import CatalogNode, ProjectCatalog
from .catalog.similarity_adapter import compare_catalog_functions, graph_from_catalog
from .network import build_reachable_call_network
from .session import RepositorySessionManager
from .similarity.clustering import cluster_common_factors, cluster_similarity_matrix
from .similarity.duplicates import find_duplicate_candidates
from .similarity.engine import FunctionGraph, SimilarityConfig, compare_functions
from .similarity.matrix import SimilarityMatrixResult, compute_similarity_matrix
from .similarity.pair_cache import PairwiseScoreCache


class CodeAnalyzer:
    """Public, UI-independent interface to the code cataloguer engine.

    The class owns a repository session and exposes the analysis operations used
    by the standalone Flask application.  Consumers such as the future unified
    project assistant should import this class rather than reaching into the
    analyzer's internal packages.
    """

    def __init__(
        self,
        project_root: str | Path,
        *,
        extra_excludes: Iterable[str] | None = None,
        use_gitignore: bool = True,
        recent_limit: int = 8,
    ) -> None:
        self._sessions = RepositorySessionManager(
            Path(project_root),
            extra_excludes=extra_excludes,
            use_gitignore=use_gitignore,
            recent_limit=recent_limit,
        )

    @property
    def project_root(self) -> Path:
        return self._sessions.current().root

    def status(self) -> dict:
        return self._sessions.status()

    def open_repository(self, path: str | Path) -> dict:
        session = self._sessions.load(path)
        return {
            "success": True,
            "message": f"Loaded {session.root.name}",
            "session": self._sessions.status(),
        }

    def reload(self) -> dict:
        session = self._sessions.reload()
        return {
            "success": True,
            "message": f"Reloaded {session.root.name}",
            "session": self._sessions.status(),
        }

    def source_index_status(self, *, verify_contents: bool = False) -> dict:
        """Report project-local source-index freshness without changing it."""
        return self._source_index().status(verify_contents=verify_contents)

    def _source_index(self) -> SourceIndex:
        from .source_index import SourceIndex
        return SourceIndex(
            self.project_root,
            extra_excludes=self._sessions.extra_excludes,
            use_gitignore=self._sessions.use_gitignore,
        )

    def rebuild_source_index(self) -> dict:
        """Atomically rebuild from the authoritative, freshly parsed AST catalog."""
        return self._source_index().rebuild(self.catalog(refresh=True))

    def _ready_source_index(self) -> SourceIndex:
        index = self._source_index()
        if index.status().get('state') != 'current':
            index.rebuild(self.catalog(refresh=True))
        return index

    def lookup_source_files(
        self, *, path: str | None = None, limit: int = 100, offset: int = 0,
    ) -> dict:
        """Find indexed Python source files, rebuilding stale indexes on demand."""
        return self._ready_source_index().files(path=path, limit=limit, offset=offset)

    def lookup_symbols(
        self, *, text: str = '', path: str | None = None,
        kind: str | None = None, line: int | None = None,
        limit: int = 100, offset: int = 0,
    ) -> dict:
        """Find indexed symbols, rebuilding stale indexes transparently."""
        return self._ready_source_index().symbols(
            text=text, path=path, kind=kind, line=line, limit=limit, offset=offset,
        )

    def lookup_dependencies(
        self, *, source_id: str | None = None, target_id: str | None = None,
        relationship: str | None = None, path: str | None = None,
        limit: int = 100, offset: int = 0,
    ) -> dict:
        """Search indexed call/import edges using the same project-local index."""
        return self._ready_source_index().dependencies(
            source_id=source_id, target_id=target_id,
            relationship=relationship, path=path, limit=limit, offset=offset,
        )

    @_monitor("code_analyzer", "Repository catalog")
    def catalog(self, *, refresh: bool = False) -> ProjectCatalog:
        return self._sessions.current().service.catalog(refresh=refresh)

    def catalog_dict(self, *, refresh: bool = False) -> dict:
        return self.catalog(refresh=refresh).to_dict()

    def get_node(self, node_id: str) -> CatalogNode:
        node = self.catalog(refresh=False).nodes.get(node_id)
        if node is None:
            raise KeyError(f"Unknown catalog node: {node_id}")
        return node

    def graph(self, *, refresh: bool = False) -> FunctionGraph:
        return graph_from_catalog(self.catalog(refresh=refresh))

    def call_network(
        self,
        focus_id: str,
        *,
        depth: int | None = None,
        include_incoming: bool = True,
        include_outgoing: bool = True,
    ) -> dict:
        """Return a reusable, cycle-safe reachable call-network artifact."""
        return build_reachable_call_network(
            self.catalog(refresh=False),
            focus_id,
            depth=depth,
            include_incoming=include_incoming,
            include_outgoing=include_outgoing,
        )

    @staticmethod
    def similarity_config(
        *,
        context_depth: int = 1,
        distance_decay: float = 0.5,
        external_import_weight: float = 0.20,
    ) -> SimilarityConfig:
        config = SimilarityConfig(
            context_depth=int(context_depth),
            distance_decay=float(distance_decay),
            internal_edge_weight=1.0,
            external_import_weight=float(external_import_weight),
            node_weight=1.0,
        )
        config.validate()
        return config

    def compare(
        self,
        left_id: str,
        right_id: str,
        *,
        context_depth: int = 1,
        distance_decay: float = 0.5,
        external_import_weight: float = 0.20,
    ) -> dict:
        return compare_catalog_functions(
            self.catalog(refresh=False),
            left_id,
            right_id,
            context_depth=int(context_depth),
            distance_decay=float(distance_decay),
            external_import_weight=float(external_import_weight),
        )

    def _current_similarity_graph(self) -> FunctionGraph:
        """Refresh the authoritative AST catalog if its source index is stale.

        The full content check is deliberate: similarity results must not survive
        a same-size source edit or misleading filesystem timestamps.
        """
        index = self._source_index()
        if index.status(verify_contents=True).get('state') != 'current':
            # A stale catalog cannot be used to compute or identify cached scores.
            self.catalog(refresh=True)
            try:
                index.rebuild(self.catalog(refresh=False))
            except (OSError, ValueError, sqlite3.DatabaseError):
                # Source indexing is an optimization; AST analysis still works.
                pass
        return self.graph()

    @contextmanager
    def _similarity_scores(self, graph: FunctionGraph, config: SimilarityConfig):
        """Provide exact scores; cache problems never change the algorithm."""
        try:
            cache = PairwiseScoreCache(self.project_root, graph, config)
        except (OSError, ValueError, sqlite3.DatabaseError):
            def direct(left: str, right: str) -> tuple[float, float]:
                result = compare_functions(graph, left, right, config, include_pairs=False)
                return float(result.score), float(result.layers[0].node_similarity)
            yield direct
        else:
            with cache:
                yield cache.score

    @_monitor("code_analyzer", "Similarity matrix")
    def similarity_matrix(
        self,
        *,
        context_depth: int = 1,
        distance_decay: float = 0.5,
        external_import_weight: float = 0.20,
        ordering: str = "qualified_name",
    ) -> SimilarityMatrixResult:
        config = self.similarity_config(
            context_depth=context_depth,
            distance_decay=distance_decay,
            external_import_weight=external_import_weight,
        )
        graph = self._current_similarity_graph()
        with self._similarity_scores(graph, config) as scores:
            return compute_similarity_matrix(graph, config, ordering=ordering, scores=scores)

    def similarity_matrix_window(
        self, *, row_offset: int = 0, row_limit: int = 25,
        column_offset: int = 0, column_limit: int = 25,
        context_depth: int = 1, distance_decay: float = 0.5,
        external_import_weight: float = 0.20,
    ) -> dict:
        """Compute only a bounded rectangular window, explicitly incomplete.

        No pruning or approximation: every cell in the window is the same exact
        rooted comparison used by the full matrix. Pairs outside it are omitted.
        """
        for name, value, low, high in (
            ('row_offset', row_offset, 0, 100_000_000),
            ('column_offset', column_offset, 0, 100_000_000),
            ('row_limit', row_limit, 1, 50),
            ('column_limit', column_limit, 1, 50),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError(f'{name} must be an integer between {low} and {high}')
        config = self.similarity_config(context_depth=context_depth,
            distance_decay=distance_decay, external_import_weight=external_import_weight)
        graph = self._current_similarity_graph()
        labels = sorted(graph.nodes)
        row_labels = labels[row_offset:row_offset + row_limit]
        column_labels = labels[column_offset:column_offset + column_limit]
        with self._similarity_scores(graph, config) as scores:
            matrix = [[1.0 if left == right else scores(left, right)[0]
                      for right in column_labels] for left in row_labels]
        return {
            'data_scope': 'window', 'complete': False, 'total_functions': len(labels),
            'total_upper_triangle_pairs': len(labels) * (len(labels) + 1) // 2,
            'row_offset': row_offset, 'column_offset': column_offset,
            'row_limit': row_limit, 'column_limit': column_limit,
            'row_labels': row_labels, 'column_labels': column_labels,
            'matrix': matrix,
        }

    def iter_similarity_matrix_csv(
        self, *, context_depth: int = 1, distance_decay: float = 0.5,
        external_import_weight: float = 0.20,
    ) -> Iterator[str]:
        """Stream the *complete* exact matrix without constructing it in memory."""
        config = self.similarity_config(context_depth=context_depth,
            distance_decay=distance_decay, external_import_weight=external_import_weight)
        graph = self._current_similarity_graph()
        labels = sorted(graph.nodes)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(['qualified_name', *labels])
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        with self._similarity_scores(graph, config) as scores:
            for left in labels:
                writer.writerow([left, *[
                    f'{(1.0 if left == right else scores(left, right)[0]):.10f}'
                    for right in labels
                ]])
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)

    def similarity_neighbors(
        self,
        function_id: str,
        *,
        limit: int = 8,
        threshold: float = 0.0,
        context_depth: int = 1,
        distance_decay: float = 0.5,
        external_import_weight: float = 0.20,
    ) -> dict:
        graph = self._current_similarity_graph()
        if function_id not in graph.nodes:
            raise ValueError(f"Unknown function node: {function_id}")
        if limit < 1:
            raise ValueError("limit must be positive")
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0 and 1")

        config = self.similarity_config(
            context_depth=context_depth,
            distance_decay=distance_decay,
            external_import_weight=external_import_weight,
        )
        scored = []
        with self._similarity_scores(graph, config) as scores:
            for other_id in graph.nodes:
                if other_id == function_id:
                    continue
                score = scores(function_id, other_id)[0]
                if score < threshold:
                    continue
                scored.append((other_id, score))
        scored.sort(key=lambda item: (-item[1], item[0]))

        catalog = self.catalog(refresh=False)
        neighbors = []
        for other_id, score in scored[: int(limit)]:
            item = catalog.nodes.get(other_id)
            neighbors.append({
                "id": other_id,
                "score": score,
                "name": item.name if item else other_id,
                "qualified_name": (item.qualified_name if item else other_id),
                "path": (item.path if item else None),
                "node_type": (item.node_type if item else "function"),
            })
        return {
            "function_id": function_id,
            "neighbors": neighbors,
            "config": {
                "context_depth": config.context_depth,
                "distance_decay": config.distance_decay,
                "external_import_weight": config.external_import_weight,
            },
        }

    @_monitor("code_analyzer", "Duplicate candidates")
    def duplicate_candidates(
        self,
        *,
        threshold: float = 0.65,
        limit: int = 50,
        factor_limit: int = 12,
        context_depth: int = 1,
        distance_decay: float = 0.5,
        external_import_weight: float = 0.20,
        include_source: bool = True,
    ) -> dict:
        config = self.similarity_config(
            context_depth=context_depth,
            distance_decay=distance_decay,
            external_import_weight=external_import_weight,
        )
        graph = self._current_similarity_graph()
        with self._similarity_scores(graph, config) as scores:
            result = find_duplicate_candidates(
                graph, config, threshold=float(threshold), limit=int(limit),
                factor_limit=int(factor_limit), scores=scores,
            )
        if include_source:
            catalog = self.catalog(refresh=False)
            for candidate in result["candidates"]:
                for side in ("left", "right"):
                    node_id = candidate[f"{side}_id"]
                    item = catalog.nodes.get(node_id)
                    if item is None:
                        continue
                    metadata = item.metadata or {}
                    candidate[side] = {
                        "id": node_id,
                        "name": item.name,
                        "qualified_name": item.qualified_name or item.name,
                        "node_type": item.node_type,
                        "path": item.path or metadata.get("path"),
                        "line_start": metadata.get("line_start"),
                        "line_end": metadata.get("line_end"),
                        "source_code": metadata.get("source_code", ""),
                    }
        return result

    def clusters(
        self,
        *,
        k: int = 3,
        random_state: int = 42,
        context_depth: int = 1,
        distance_decay: float = 0.5,
        external_import_weight: float = 0.20,
        ordering: str = "qualified_name",
        common_factor_limit: int = 25,
    ) -> dict:
        graph = self._current_similarity_graph()
        config = self.similarity_config(
            context_depth=context_depth,
            distance_decay=distance_decay,
            external_import_weight=external_import_weight,
        )
        with self._similarity_scores(graph, config) as scores:
            matrix_result = compute_similarity_matrix(graph, config, ordering=ordering, scores=scores)
        cluster_result = cluster_similarity_matrix(
            matrix_result,
            k=int(k),
            random_state=int(random_state),
        )
        response = cluster_result.to_dict()
        common_factors = cluster_common_factors(
            graph, cluster_result, limit=int(common_factor_limit)
        )
        for cluster in response["clusters"]:
            cluster["common_factors"] = common_factors.get(cluster["cluster"], [])
        matrix_payload = matrix_result.to_dict()
        response["matrix_summary"] = matrix_payload["summary"]
        response["config"] = matrix_payload["config"]
        return response

    # Existing standalone refactoring behavior is intentionally retained.
    # The future unified host is free to ignore these operations and use its
    # own editor for ordinary source changes.
    def preview_function_move(self, function_id: str, target_module_id: str) -> dict:
        plan = self._sessions.current().service.preview(function_id, target_module_id)
        return plan.public_dict()

    def apply_function_move(self, plan_id: str) -> dict:
        return self._sessions.current().service.apply(plan_id)

    def undo_last_move(self) -> dict:
        return self._sessions.current().service.undo_last()
