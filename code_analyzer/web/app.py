#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from flask import Flask, jsonify, make_response, request

from code_analyzer import CodeAnalyzer

ROOT = Path(__file__).resolve().parent


def create_app(project_root: Path, extra_excludes=None, use_gitignore=True):
    analyzer = CodeAnalyzer(
        project_root,
        extra_excludes=extra_excludes or set(),
        use_gitignore=use_gitignore,
    )

    app = Flask(__name__)

    @app.get("/")
    def index():
        catalog = analyzer.catalog_dict(refresh=False)
        html = (ROOT / "templates" / "report.html").read_text(encoding="utf-8")
        css = "\n".join(
            (ROOT / "static" / filename).read_text(encoding="utf-8")
            for filename in (
                "catalog.css",
                "refactor.css",
                "similarity.css",
                "pah-module-theme.css",
                "pah-compat.css",
            )
        )
        # Keep each module in its own script element. A repository-specific
        # rendering error in one view must not prevent repository controls or
        # the other tabs from initializing.
        script_blocks = "\n".join(
            "<script>\n"
            + (ROOT / "static" / filename).read_text(encoding="utf-8")
            + "\n</script>"
            for filename in (
                "catalog.js",
                "repository_map.js",
                "refactor.js",
                "similarity.js",
                "repository_session.js",
            )
        )
        data = json.dumps(catalog, ensure_ascii=False).replace("</", "<\\/")
        controls = (ROOT / "templates" / "refactor_controls.html").read_text(
            encoding="utf-8"
        )
        rendered = (
            html.replace("/*__CATALOG_CSS__*/", css)
            .replace("/*__CATALOG_DATA__*/", data)
            .replace("</main>", "</main>\n" + controls)
            .replace("<script>\n/*__CATALOG_JS__*/\n  </script>", script_blocks)
        )
        response = make_response(rendered)
        # Repository switching changes process-local state. Never let the browser
        # reuse the HTML/embedded catalog from the previous repository.
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @app.get("/api/catalog")
    def api_catalog():
        return jsonify(analyzer.catalog_dict(refresh=True))

    @app.get("/api/repository/current")
    def repository_current():
        return jsonify(analyzer.status())

    @app.post("/api/repository/open")
    def repository_open():
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify(analyzer.open_repository(str(payload.get("path", ""))))
        except (OSError, TypeError, ValueError) as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        except Exception as exc:
            app.logger.exception("Repository load failed")
            return jsonify({
                "success": False,
                "error": f"{type(exc).__name__}: {exc}",
            }), 500

    @app.post("/api/repository/reload")
    def repository_reload():
        try:
            return jsonify(analyzer.reload())
        except Exception as exc:
            app.logger.exception("Repository reload failed")
            return jsonify({
                "success": False,
                "error": f"{type(exc).__name__}: {exc}",
            }), 500

    @app.post("/api/repository/network")
    def repository_network():
        payload = request.get_json(silent=True) or {}
        try:
            raw_depth = payload.get("depth", "all")
            depth = None if raw_depth in (None, "all") else int(raw_depth)
            return jsonify(analyzer.call_network(
                str(payload.get("focus_id", "")),
                depth=depth,
                include_incoming=bool(payload.get("include_incoming", True)),
                include_outgoing=bool(payload.get("include_outgoing", True)),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/similarity/compare")
    def compare_similarity():
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify(analyzer.compare(
                str(payload.get("left_id", "")),
                str(payload.get("right_id", "")),
                context_depth=int(payload.get("context_depth", 1)),
                distance_decay=float(payload.get("distance_decay", 0.5)),
                external_import_weight=float(payload.get("external_import_weight", 0.20)),
            ))
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/similarity/matrix")
    def similarity_matrix():
        payload = request.get_json(silent=True) or {}
        try:
            result = analyzer.similarity_matrix(
                context_depth=int(payload.get("context_depth", 1)),
                distance_decay=float(payload.get("distance_decay", 0.5)),
                external_import_weight=float(payload.get("external_import_weight", 0.20)),
                ordering=str(payload.get("ordering", "qualified_name")),
            )
            return jsonify(result.to_dict())
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/similarity/neighbors")
    def similarity_neighbors():
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify(analyzer.similarity_neighbors(
                str(payload.get("function_id", "")),
                limit=int(payload.get("limit", 8)),
                threshold=float(payload.get("threshold", 0.0)),
                context_depth=int(payload.get("context_depth", 1)),
                distance_decay=float(payload.get("distance_decay", 0.5)),
                external_import_weight=float(payload.get("external_import_weight", 0.20)),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/similarity/duplicates")
    def similarity_duplicates():
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify(analyzer.duplicate_candidates(
                threshold=float(payload.get("threshold", 0.65)),
                limit=int(payload.get("limit", 50)),
                factor_limit=int(payload.get("factor_limit", 12)),
                context_depth=int(payload.get("context_depth", 1)),
                distance_decay=float(payload.get("distance_decay", 0.5)),
                external_import_weight=float(payload.get("external_import_weight", 0.20)),
                include_source=True,
            ))
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            app.logger.exception("Duplicate candidate analysis failed")
            return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500

    @app.post("/api/similarity/clusters")
    def similarity_clusters():
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify(analyzer.clusters(
                k=int(payload.get("k", 3)),
                random_state=int(payload.get("random_state", 42)),
                context_depth=int(payload.get("context_depth", 1)),
                distance_decay=float(payload.get("distance_decay", 0.5)),
                external_import_weight=float(payload.get("external_import_weight", 0.20)),
                ordering=str(payload.get("ordering", "qualified_name")),
                common_factor_limit=25,
            ))
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
            return jsonify(analyzer.preview_function_move(
                str(payload.get("function_id", "")),
                str(payload.get("target_module_id", "")),
            ))
        except ValueError as exc:
            return jsonify({"valid": False, "error": str(exc)}), 400

    @app.post("/api/refactor/move-function/apply")
    def apply():
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify(analyzer.apply_function_move(str(payload.get("plan_id", ""))))
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 409

    @app.post("/api/refactor/undo")
    def undo():
        try:
            return jsonify(analyzer.undo_last_move())
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 409

    app.extensions["code_analyzer"] = analyzer
    # Compatibility for code that inspected the old standalone Flask extension.
    app.extensions["repository_session_manager"] = analyzer._sessions
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
