from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pah_visual_contract_is_packaged_and_loaded():
    app = (ROOT / "code_analyzer" / "web" / "app.py").read_text(encoding="utf-8")
    html = (ROOT / "code_analyzer" / "web" / "templates" / "report.html").read_text(encoding="utf-8")
    static = ROOT / "code_analyzer" / "web" / "static"

    assert '"pah-module-theme.css"' in app
    assert '"pah-compat.css"' in app
    assert (static / "pah-module-theme.css").is_file()
    assert (static / "pah-compat.css").is_file()
    assert 'class="pah-module"' in html
    assert 'data-pah-module-root' in html
    assert 'pah-tool-nav' in html
