from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .catalog.models import CatalogNode, ProjectCatalog
from .catalog.similarity_adapter import compare_catalog_functions, graph_from_catalog
from .session import RepositorySessionManager
from .similarity.clustering import cluster_common_factors, cluster_similarity_matrix
from .similarity.duplicates import find_duplicate_candidates
from .similarity.engine import FunctionGraph, SimilarityConfig, compare_functions
from .similarity.matrix import SimilarityMatrixResult, compute_similarity_matrix


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
        return compute_similarity_matrix(self.graph(), config, ordering=ordering)

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
        graph = self.graph()
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
        for other_id in graph.nodes:
            if other_id == function_id:
                continue
            result = compare_functions(
                graph, function_id, other_id, config, include_pairs=False
            )
            if result.score < threshold:
                continue
            scored.append((other_id, result.score))
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
        result = find_duplicate_candidates(
            self.graph(),
            config,
            threshold=float(threshold),
            limit=int(limit),
            factor_limit=int(factor_limit),
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
        graph = self.graph()
        config = self.similarity_config(
            context_depth=context_depth,
            distance_decay=distance_decay,
            external_import_weight=external_import_weight,
        )
        matrix_result = compute_similarity_matrix(graph, config, ordering=ordering)
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
