"""The module's installed extra must agree with PAH_Shared graph-view v0.4."""
from pathlib import Path
import tomllib


def test_shared_graph_view_package_range():
    root = Path(__file__).resolve().parents[1]
    extras = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    for name in ['web']:
        assert "pah-shared>=0.4,<0.5" in extras[name]
    assert "pah-shared>=0.4,<0.5" in (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
