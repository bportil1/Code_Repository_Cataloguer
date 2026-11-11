"""Standalone Code Analyzer: explicit, read-only ATLAS/CPS provider endpoints.

Retains the Python catalog untouched. The integrated CPS parser is opt-in and
returns structural hypotheses, *not* executable hardware/test semantics.
"""
from __future__ import annotations

from pathlib import Path

from code_analyzer.language_providers.inventory import atlas_files, ATLAS_SUFFIXES

def register_atlas_routes(app, analyzer) -> None:
    """Register read-only ATLAS endpoints on the existing standalone app."""
    from flask import jsonify, request

    @app.get("/api/atlas/files")
    def atlas_source_inventory():
        try:
            offset = int(request.args.get("offset", "0"))
            limit = int(request.args.get("limit", "100"))
            query = request.args.get("q", "")
            if offset < 0 or not 1 <= limit <= 500 or len(query) > 256:
                raise ValueError("Invalid ATLAS file inventory parameters")
            files = atlas_files(analyzer.project_root, query=query)
            return jsonify({
                "schema": "code-analyzer.atlas-files@1",
                "repository": analyzer.project_root.name,
                "paths": files[offset:offset + limit],
                "offset": offset,
                "limit": limit,
                "total": len(files),
                "has_more": offset + limit < len(files),
            })
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/atlas/analyze")
    def atlas_analyze_selected_file():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "JSON object required"}), 400
        relative = data.get("path")
        if (not isinstance(relative, str) or not relative
                or len(relative) > 2048 or Path(relative).suffix.lower() not in ATLAS_SUFFIXES):
            return jsonify({"error": "Select a repository-relative ATLAS .as, .atl or .atlas file"}), 400
        try:
            from code_analyzer.language_providers.navigation import (SourceChangedError, build_navigation_snapshot)
        except ImportError:
            return jsonify({"error": "ATLAS parser provider is not installed. Apply Code Analyzer UCA-07, UCA-08 and UCA-09 patches."}), 503
        try:
            # The UCA-09 adapter checks path identity, rejects symlinks,
            # fingerprints bytes before and after CPS Lab parser execution,
            # and preserves explicit structural-only confidence.
            snapshot = build_navigation_snapshot(relative, analyzer.project_root)
            if snapshot["language"] != "atlas":
                raise ValueError("Selected source did not resolve to the ATLAS provider")
            return jsonify({"ok": True, "snapshot": snapshot})
        except SourceChangedError as exc:
            return jsonify({"error": str(exc)}), 409
        except (ValueError, OSError) as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception:
            app.logger.exception("ATLAS provider analysis failed")
            return jsonify({"error": "ATLAS provider analysis failed; check local server logs"}), 500
