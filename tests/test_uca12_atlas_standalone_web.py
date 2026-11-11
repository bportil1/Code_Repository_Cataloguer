"""UCA: ATLAS is discoverable and used by the standalone Code Analyzer UI."""
from pathlib import Path

import pytest

from code_analyzer.language_providers.inventory import atlas_files
from code_analyzer.language_providers.navigation import build_navigation_snapshot


def test_inventory_does_not_follow_symlinks_or_dependencies(tmp_path):
    (tmp_path / "example.as").write_text("TEST A;\nEND;\n")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "sub.atl").write_text("TEST B;\nEND;\n")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "hidden.as").write_text("TEST C;\n")
    (tmp_path / "link.as").symlink_to(tmp_path / "example.as")
    (tmp_path / "linked_dir").symlink_to(tmp_path / "nested", target_is_directory=True)
    assert atlas_files(tmp_path) == ["example.as", "nested/sub.atl"]
    assert atlas_files(tmp_path, query="sub") == ["nested/sub.atl"]


def test_cps_parser_runs_through_navigation_snapshot(tmp_path):
    (tmp_path / "sample.atlas").write_text("TEST ALPHA;\nMEASURE VOLTAGE;\nEND;\n")
    snapshot = build_navigation_snapshot("sample.atlas", tmp_path)
    assert snapshot["provider_id"] == "cps.atlas.structural"
    assert snapshot["language"] == "atlas"
    assert snapshot["items"]
    assert snapshot["source_revision_verified"] is True
    assert snapshot["semantics_verified"] is False
    assert all(node["confidence"] == "unverified" for node in snapshot["items"])


def test_standalone_ui_exposes_atlas_tab_and_script():
    root = Path(__file__).parents[1] / "code_analyzer" / "web"
    assert 'data-view="atlas"' in (root / "templates/report.html").read_text()
    assert 'id="atlas-view"' in (root / "templates/report.html").read_text()
    assert '"atlas.js"' in (root / "app.py").read_text()
    assert 'register_atlas_routes(app, analyzer)' in (root / "app.py").read_text()


@pytest.mark.skipif(__import__("importlib").util.find_spec("flask") is None,
                    reason="Flask not installed in isolated test environment")
def test_web_endpoints_use_active_repository_and_cps_parser(tmp_path):
    from code_analyzer.web.app import create_app
    (tmp_path / "trial.as").write_text("TEST ALPHA;\nMEASURE VOLTAGE;\nEND;\n")
    app = create_app(tmp_path)
    with app.test_client() as client:
        listing = client.get("/api/atlas/files").get_json()
        assert "trial.as" in listing["paths"]
        bad = client.post("/api/atlas/analyze", json={"path": "../trial.as"})
        assert bad.status_code == 400
        good = client.post("/api/atlas/analyze", json={"path": "trial.as"})
        assert good.status_code == 200
        assert good.get_json()["snapshot"]["provider_id"] == "cps.atlas.structural"


def test_atlas_route_handlers_execute_with_active_repository_without_flask(tmp_path, monkeypatch):
    """Exercise real registered route handlers when Flask is not installed."""
    import runpy
    import sys
    import types
    (tmp_path / "cps.as").write_text("TEST ALPHA;\nMEASURE VOLTAGE;\nEND;\n")
    routes = {}

    class DummyApp:
        logger = types.SimpleNamespace(exception=lambda *args, **kwargs: None)

        def get(self, url):
            def register(function):
                routes[("GET", url)] = function
                return function
            return register

        def post(self, url):
            def register(function):
                routes[("POST", url)] = function
                return function
            return register

    fake_request = types.SimpleNamespace(args={"offset": "0", "limit": "100"}, get_json=lambda **kwargs: {"path": "cps.as"})
    monkeypatch.setitem(sys.modules, "flask", types.SimpleNamespace(
        jsonify=lambda data: data, request=fake_request,
    ))
    impl = runpy.run_path(str(Path(__file__).parents[1] / "code_analyzer/web/atlas_routes.py"))
    analyzer = types.SimpleNamespace(project_root=tmp_path)
    impl["register_atlas_routes"](DummyApp(), analyzer)
    found = routes[("GET", "/api/atlas/files")]()
    assert found["paths"] == ["cps.as"]
    ok = routes[("POST", "/api/atlas/analyze")]()
    assert ok["snapshot"]["provider_id"] == "cps.atlas.structural"
    fake_request.get_json = lambda **kwargs: {"path": "../cps.as"}
    rejected, status = routes[("POST", "/api/atlas/analyze")]()
    assert status == 400 and "error" in rejected
    fake_request.get_json = lambda **kwargs: {"path": "cps.py"}
    rejected, status = routes[("POST", "/api/atlas/analyze")]()
    assert status == 400
