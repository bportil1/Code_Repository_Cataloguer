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
