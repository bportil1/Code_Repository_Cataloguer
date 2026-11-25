"""Repository map UI expansion must preserve original Code Analyzer interactions."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "code_analyzer" / "web"
HTML = (WEB / "templates" / "report.html").read_text(encoding="utf-8")
CSS = (WEB / "static" / "catalog.css").read_text(encoding="utf-8")
JS = (WEB / "static" / "repository_map.js").read_text(encoding="utf-8")
CATALOG_JS = (WEB / "static" / "catalog.js").read_text(encoding="utf-8")


def test_map_controls_preserve_lenses_and_original_interactions():
    for lens in ("structure", "calls", "imports", "similarity", "duplication"):
        assert f'data-map-lens="{lens}"' in HTML
    for view in ("symbol", "call-path"):
        assert f'data-map-view="{view}"' in HTML
    for control in ("repository-map-zoom-in", "repository-map-zoom-out", "repository-map-center",
                    "repository-map-fit", "repository-map-reset-layout", "repository-map-depth",
                    "repository-map-incoming", "repository-map-outgoing", "repository-map-export",
                    "repository-map-fullscreen", "repository-map-new-window", "repository-map-highlight"):
        assert f'id="{control}"' in HTML
    for callback in ('group.addEventListener("pointerdown"', 'viewport.addEventListener("pointerdown"',
                     'group.addEventListener("keydown"', 'window.addEventListener("catalog-node-selected"',
                     'function highlightNeighborhood(', 'function centerOnNode('):
        assert callback in JS


def test_all_old_exports_preserved_plus_png_and_edges_csv():
    for fmt in ("json", "graphml", "dot", "svg", "png", "csv"):
        assert f'value="{fmt}"' in HTML
    for fn in ("function canonicalNetworkPayload(", "function graphMl(", "function dotGraph(",
               "function inlineSvgPresentation(", "function serializeVisibleSvg(",
               "function exportVisiblePng(", "function csvValue("):
        assert fn in JS
    assert "const fields = [\"source_id\", \"target_id\", \"relationship_type\", \"score\"];" in JS
    assert 'function downloadText(' in JS
    assert 'function downloadBlob(' in JS


def test_no_visible_grid_and_map_gets_full_width():
    canvas = CSS.split('.repository-map-canvas-wrap {', 1)[1].split('}', 1)[0]
    assert "linear-gradient(" not in canvas
    assert "background: #f7fafd;" in canvas
    assert 'grid-column: 1 / -1;' in CSS
    assert 'height: max(36rem, 68vh);' in canvas
    assert '.repository-map-panel:fullscreen' in CSS
    assert '.repository-map-panel.repository-map-expanded' in CSS
    assert '.repository-map-node-module rect' in CSS
    assert 'class="repository-map-legend"' in HTML
    assert 'repository-map-inspector-text' in HTML


def test_popout_is_an_independent_interactive_report_and_retains_context():
    # New windows intentionally load the SAME report and renderer, not an inert SVG clone.
    assert 'window.open(url.toString(), "_blank")' in JS
    for param in ("repository_map_window", "map_focus", "map_view", "map_lens", "map_depth",
                  "map_incoming", "map_outgoing", "map_similarity_depth", "map_decay",
                  "map_import_weight", "map_duplicate_threshold"):
        assert param in JS
    assert "document.body.classList.add(\"repository-map-window\")" in JS
    assert "showNodeDetails(initialFocus);" in CATALOG_JS
    assert 'body.repository-map-window .topbar' in CSS
    assert 'body.repository-map-window #repository-view' in CSS
    assert 'body.repository-map-window .repository-map-canvas-wrap' in CSS


def test_fullscreen_has_keyboard_escape_and_non_api_fallback():
    assert 'mapPanel.requestFullscreen()' in JS
    assert 'document.addEventListener("fullscreenchange", refreshFullscreenButton)' in JS
    assert 'event.key === "Escape"' in JS
    assert 'mapPanel.classList.add("repository-map-expanded")' in JS
    assert 'aria-pressed="false"' in HTML
    assert 'repository-map-viewport-locked' in CSS
