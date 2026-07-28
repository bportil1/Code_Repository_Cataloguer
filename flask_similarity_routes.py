"""Drop-in Flask routes.

Expected integration:
    - `get_similarity_graph()` must return the cached FunctionGraph built from
      the current catalog.
    - Add these routes to the same Flask module that already exposes
      /api/similarity/compare.
"""

from dataclasses import asdict
from flask import jsonify, request

from similarity_engine import SimilarityConfig, compare_functions
from similarity_matrix import compute_similarity_matrix


def config_from_payload(data: dict) -> SimilarityConfig:
    return SimilarityConfig(
        context_depth=int(data.get("context_depth", 1)),
        distance_decay=float(data.get("distance_decay", 0.5)),
        internal_edge_weight=float(data.get("internal_edge_weight", 1.0)),
        external_import_weight=float(data.get("external_import_weight", 0.20)),
        node_weight=float(data.get("node_weight", 1.0)),
    )


def register_similarity_routes(app, get_similarity_graph):
    @app.post("/api/similarity/compare")
    def api_similarity_compare():
        try:
            data = request.get_json(force=True)
            graph = get_similarity_graph()
            result = compare_functions(
                graph,
                str(data["left"]),
                str(data["right"]),
                config_from_payload(data),
                include_pairs=True,
            )
            return jsonify(result.to_dict())
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/similarity/matrix")
    def api_similarity_matrix():
        try:
            data = request.get_json(silent=True) or {}
            graph = get_similarity_graph()
            result = compute_similarity_matrix(
                graph,
                config_from_payload(data),
                labels=data.get("labels"),
                ordering=str(data.get("ordering", "qualified_name")),
            )
            return jsonify(result.to_dict())
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
