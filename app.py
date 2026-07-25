#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
from flask import Flask, jsonify, request
from catalog.catalog_builder import build_catalog
from catalog.refactor.function_mover import FunctionMoveService

ROOT = Path(__file__).resolve().parent

def create_app(project_root: Path, extra_excludes=None, use_gitignore=True):
    root = project_root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Project root is not a directory: {root}")
    app = Flask(__name__)
    service = FunctionMoveService(root, lambda: build_catalog(root, extra_excludes or set(), use_gitignore))

    @app.get('/')
    def index():
        catalog = service.catalog(refresh=True).to_dict()
        html = (ROOT/'templates'/'report.html').read_text(encoding='utf-8')
        css = (ROOT/'static'/'catalog.css').read_text(encoding='utf-8') + '\n' + (ROOT/'static'/'refactor.css').read_text(encoding='utf-8')
        js = (ROOT/'static'/'catalog.js').read_text(encoding='utf-8')
        refactor_js = (ROOT/'static'/'refactor.js').read_text(encoding='utf-8')
        data = json.dumps(catalog, ensure_ascii=False).replace('</', '<\\/')
        controls = (ROOT/'templates'/'refactor_controls.html').read_text(encoding='utf-8')
        return (html.replace('/*__CATALOG_CSS__*/', css)
                    .replace('/*__CATALOG_DATA__*/', data)
                    .replace('</main>', '</main>\n' + controls)
                    .replace('/*__CATALOG_JS__*/', js + '\n' + refactor_js))

    @app.get('/api/catalog')
    def api_catalog():
        return jsonify(service.catalog(refresh=True).to_dict())

    @app.post('/api/refactor/move-function/preview')
    def preview():
        payload = request.get_json(silent=True) or {}
        try:
            plan = service.preview(str(payload.get('function_id','')), str(payload.get('target_module_id','')))
            return jsonify(plan.public_dict())
        except ValueError as exc:
            return jsonify({'valid': False, 'error': str(exc)}), 400

    @app.post('/api/refactor/move-function/apply')
    def apply():
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify(service.apply(str(payload.get('plan_id',''))))
        except ValueError as exc:
            return jsonify({'success': False, 'error': str(exc)}), 409

    @app.post('/api/refactor/undo')
    def undo():
        try:
            return jsonify(service.undo_last())
        except ValueError as exc:
            return jsonify({'success': False, 'error': str(exc)}), 409

    return app

def main():
    parser = argparse.ArgumentParser(description='Run Codebase Catalog locally with Flask.')
    parser.add_argument('project_root', type=Path)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--exclude', action='append', default=[])
    parser.add_argument('--no-gitignore', action='store_true')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()
    create_app(args.project_root, set(args.exclude), not args.no_gitignore).run(host=args.host, port=args.port, debug=args.debug)

if __name__ == '__main__':
    main()
