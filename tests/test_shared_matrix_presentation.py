"""Source-level acceptance for the shared similarity-matrix UI."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_similarity_matrix_uses_single_shared_renderer():
    text = (ROOT / 'code_analyzer/web/static/similarity.js').read_text()
    assert "mountTable(matrixTable, sharedMatrixSnapshot" in text
    assert "onCellActivate" in text and "openMatrixPair" in text
    assert 'document.createElement("thead")' not in text
    assert "downloadTable(snapshot,'csv'" in text


def test_standalone_html_uses_shared_matrix_host():
    html = (ROOT / 'code_analyzer/web/templates/report.html').read_text()
    assert '<div id="similarity-matrix-table"' in html
    assert 'href="/pah-shared/table.css"' in html
