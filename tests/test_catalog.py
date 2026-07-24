from pathlib import Path

from catalog.catalog_builder import build_catalog
from catalog.indexer import index_python_files
from catalog.scanner import scan_project


def test_sample_catalog() -> None:
    root = Path(__file__).parent / "fixtures" / "sample_project"
    scan = scan_project(root)
    modules = index_python_files(scan)
    catalog = build_catalog(scan, modules)

    assert catalog.summary.python_files == 3
    assert catalog.summary.classes == 1
    assert catalog.summary.functions == 1
    assert catalog.summary.methods == 1
    assert "sample_pkg.service" in catalog.internal_dependencies["main"]


def test_root_gitignore_is_applied(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored.py\ncache/\n", encoding="utf-8")
    (tmp_path / "kept.py").write_text("def kept():\n    return True\n", encoding="utf-8")
    (tmp_path / "ignored.py").write_text("def ignored():\n    return False\n", encoding="utf-8")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "cached.py").write_text("def cached():\n    return None\n", encoding="utf-8")

    scan = scan_project(tmp_path)
    paths = {path.relative_to(tmp_path).as_posix() for path in scan.all_files}

    assert "kept.py" in paths
    assert "ignored.py" not in paths
    assert "cache/cached.py" not in paths
    assert scan.gitignore_path == tmp_path / ".gitignore"


def test_gitignore_can_be_disabled(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (tmp_path / "ignored.py").write_text("def ignored():\n    return False\n", encoding="utf-8")

    scan = scan_project(tmp_path, use_gitignore=False)
    paths = {path.relative_to(tmp_path).as_posix() for path in scan.all_files}

    assert "ignored.py" in paths
    assert scan.gitignore_path is None


def test_gitignore_negation_and_glob(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text(
        "*.log\nreports/**\n!reports/keep.py\n",
        encoding="utf-8",
    )
    (tmp_path / "debug.log").write_text("ignored", encoding="utf-8")
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "drop.py").write_text("DROP = True\n", encoding="utf-8")
    (reports / "keep.py").write_text("KEEP = True\n", encoding="utf-8")

    scan = scan_project(tmp_path)
    paths = {path.relative_to(tmp_path).as_posix() for path in scan.all_files}

    assert "debug.log" not in paths
    assert "reports/drop.py" not in paths
    assert "reports/keep.py" in paths
