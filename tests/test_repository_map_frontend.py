from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_repository_map_has_navigation_controls():
    template = (ROOT / "code_analyzer/web/templates/report.html").read_text(encoding="utf-8")
    for control_id in (
        "repository-map-canvas-wrap",
        "repository-map-zoom-in",
        "repository-map-zoom-out",
        "repository-map-center",
        "repository-map-fit",
        "repository-map-reset-layout",
    ):
        assert f'id="{control_id}"' in template


def test_repository_map_uses_scrollable_spaced_layout_and_dragging():
    css = (ROOT / "code_analyzer/web/static/catalog.css").read_text(encoding="utf-8")
    javascript = (ROOT / "code_analyzer/web/static/repository_map.js").read_text(encoding="utf-8")

    assert "overflow: auto" in css
    assert "minimumArcSpacing" in javascript
    assert "horizontalSpacing" in javascript
    assert 'group.addEventListener("pointerdown"' in javascript
    assert 'viewport.addEventListener("pointerdown"' in javascript
    assert "function fitMap()" in javascript
    assert "function centerOnNode(" in javascript


def test_repository_map_supports_full_reachable_depth_and_graph_exports():
    template = (ROOT / "code_analyzer/web/templates/report.html").read_text(encoding="utf-8")
    javascript = (ROOT / "code_analyzer/web/static/repository_map.js").read_text(encoding="utf-8")

    assert '<option value="all">All reachable</option>' in template
    assert 'id="repository-map-export-format"' in template
    assert 'id="repository-map-export"' in template
    for export_format in ("json", "graphml", "dot", "svg"):
        assert f'value="{export_format}"' in template

    assert 'raw === "all" ? Infinity' in javascript
    assert "full reachable closure" in javascript
    assert "fullScope ? Infinity : 28" in javascript
    assert "Complete call network for all functions and methods in the selected scope." in javascript
    assert "function canonicalNetworkPayload(" in javascript
    assert "function graphMl(" in javascript
    assert "function dotGraph(" in javascript
    assert "new XMLSerializer().serializeToString" in javascript
