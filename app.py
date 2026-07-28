#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from flask import Flask, jsonify, request

from catalog.catalog_builder import build_catalog
from catalog.refactor.function_mover import FunctionMoveService
from catalog.similarity_adapter import compare_catalog_functions, graph_from_catalog
from similarity_engine import SimilarityConfig
from similarity_matrix import compute_similarity_matrix
from similarity_clustering import cluster_common_factors, cluster_similarity_matrix

ROOT = Path(__file__).resolve().parent


def create_app(project_root: Path, extra_excludes=None, use_gitignore=True):
    root = project_root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Project root is not a directory: {root}")

    app = Flask(__name__)
    service = FunctionMoveService(
        root,
        lambda: build_catalog(root, extra_excludes or set(), use_gitignore),
    )

    @app.get("/")
    def index():
        catalog = service.catalog(refresh=True).to_dict()
        html = (ROOT / "templates" / "report.html").read_text(encoding="utf-8")
        css = "\n".join(
            (ROOT / "static" / filename).read_text(encoding="utf-8")
            for filename in ("catalog.css", "refactor.css", "similarity.css")
        )
        js = "\n".join(
            (ROOT / "static" / filename).read_text(encoding="utf-8")
            for filename in ("catalog.js", "refactor.js", "similarity.js")
        )
        data = json.dumps(catalog, ensure_ascii=False).replace("</", "<\\/")
        controls = (ROOT / "templates" / "refactor_controls.html").read_text(
            encoding="utf-8"
        )
        return (
            html.replace("/*__CATALOG_CSS__*/", css)
            .replace("/*__CATALOG_DATA__*/", data)
            .replace("</main>", "</main>\n" + controls)
            .replace("/*__CATALOG_JS__*/", js)
        )

    @app.get("/api/catalog")
    def api_catalog():
        return jsonify(service.catalog(refresh=True).to_dict())

    @app.post("/api/similarity/compare")
    def compare_similarity():
        payload = request.get_json(silent=True) or {}
        try:
            result = compare_catalog_functions(
                service.catalog(refresh=False),
                str(payload.get("left_id", "")),
                str(payload.get("right_id", "")),
                context_depth=int(payload.get("context_depth", 1)),
                distance_decay=float(payload.get("distance_decay", 0.5)),
                external_import_weight=float(
                    payload.get("external_import_weight", 0.20)
                ),
            )
            return jsonify(result)
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/similarity/matrix")
    def similarity_matrix():
        payload = request.get_json(silent=True) or {}
        try:
            graph = graph_from_catalog(service.catalog(refresh=False))
            config = SimilarityConfig(
                context_depth=int(payload.get("context_depth", 1)),
                distance_decay=float(payload.get("distance_decay", 0.5)),
                internal_edge_weight=1.0,
                external_import_weight=float(payload.get("external_import_weight", 0.20)),
                node_weight=1.0,
            )
            result = compute_similarity_matrix(
                graph,
                config,
                ordering=str(payload.get("ordering", "qualified_name")),
            )
            return jsonify(result.to_dict())
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/similarity/clusters")
    def similarity_clusters():
        payload = request.get_json(silent=True) or {}
        try:
            graph = graph_from_catalog(service.catalog(refresh=False))
            config = SimilarityConfig(
                context_depth=int(payload.get("context_depth", 1)),
                distance_decay=float(payload.get("distance_decay", 0.5)),
                internal_edge_weight=1.0,
                external_import_weight=float(payload.get("external_import_weight", 0.20)),
                node_weight=1.0,
            )
            matrix_result = compute_similarity_matrix(
                graph,
                config,
                ordering=str(payload.get("ordering", "qualified_name")),
            )
            cluster_result = cluster_similarity_matrix(
                matrix_result,
                k=int(payload.get("k", 3)),
                random_state=int(payload.get("random_state", 42)),
            )
            response = cluster_result.to_dict()
            common_factors = cluster_common_factors(graph, cluster_result, limit=25)
            for cluster in response["clusters"]:
                cluster["common_factors"] = common_factors.get(cluster["cluster"], [])
            response["matrix_summary"] = matrix_result.to_dict()["summary"]
            response["config"] = matrix_result.to_dict()["config"]
            return jsonify(response)
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            app.logger.exception("Similarity clustering failed")
            return jsonify({
                "error": f"{type(exc).__name__}: {exc}",
                "endpoint": "/api/similarity/clusters",
            }), 500

    @app.post("/api/refactor/move-function/preview")
    def preview():
        payload = request.get_json(silent=True) or {}
        try:
            plan = service.preview(
                str(payload.get("function_id", "")),
                str(payload.get("target_module_id", "")),
            )
            return jsonify(plan.public_dict())
        except ValueError as exc:
            return jsonify({"valid": False, "error": str(exc)}), 400

    @app.post("/api/refactor/move-function/apply")
    def apply():
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify(service.apply(str(payload.get("plan_id", ""))))
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 409

    @app.post("/api/refactor/undo")
    def undo():
        try:
            return jsonify(service.undo_last())
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 409

    return app


def main():
    parser = argparse.ArgumentParser(description="Run Codebase Catalog locally with Flask.")
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--no-gitignore", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    create_app(args.project_root, set(args.exclude), not args.no_gitignore).run(
        host=args.host,
        port=args.port,
        debug=args.debug,
    )


if __name__ == "__main__":
    main()
