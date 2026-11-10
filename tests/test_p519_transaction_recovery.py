"""P5-19 fault-injection checks for multi-file move/undo recovery."""
import json

import pytest

from code_analyzer import CodeAnalyzer


def fixture(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.py").write_text("def alpha():\n    return 1\n")
    (root / "b.py").write_text("def beta():\n    return 2\n")
    analyzer = CodeAnalyzer(root, use_gitignore=False)
    cat = analyzer.catalog()
    function_id = next(k for k, v in cat.nodes.items() if v.node_type == "function" and v.name == "alpha")
    target_id = next(k for k, v in cat.nodes.items() if v.node_type == "module" and v.path == "b.py")
    preview = analyzer.preview_function_move(function_id, target_id)
    return analyzer, root, preview["plan_id"]


def sources(root):
    return {p.name: p.read_bytes() for p in (root / "a.py", root / "b.py")}


def history(root):
    p = root / ".codebase_catalog" / "history.json"
    return p.read_bytes() if p.exists() else None


def inject_failure(monkeypatch, service, filename):
    original = service._atomic_write
    triggered = False

    def patched(path, text):
        nonlocal triggered
        if path.name == filename and not triggered:
            triggered = True
            raise OSError("injected replacement failure")
        return original(path, text)

    monkeypatch.setattr(service, "_atomic_write", patched)


def test_apply_second_file_failure_restores_first(tmp_path, monkeypatch):
    analyzer, root, plan_id = fixture(tmp_path)
    before, previous_history = sources(root), history(root)
    inject_failure(monkeypatch, analyzer._sessions.current().service, "b.py")
    with pytest.raises(OSError, match="injected"):
        analyzer.apply_function_move(plan_id)
    assert sources(root) == before
    assert history(root) == previous_history


def test_apply_history_failure_restores_both(tmp_path, monkeypatch):
    analyzer, root, plan_id = fixture(tmp_path)
    before, previous_history = sources(root), history(root)
    inject_failure(monkeypatch, analyzer._sessions.current().service, "history.json")
    with pytest.raises(OSError, match="injected"):
        analyzer.apply_function_move(plan_id)
    assert sources(root) == before
    assert history(root) == previous_history


def test_undo_second_file_failure_preserves_move(tmp_path, monkeypatch):
    analyzer, root, plan_id = fixture(tmp_path)
    analyzer.apply_function_move(plan_id)
    before, previous_history = sources(root), history(root)
    inject_failure(monkeypatch, analyzer._sessions.current().service, "b.py")
    with pytest.raises(OSError, match="injected"):
        analyzer.undo_last_move()
    assert sources(root) == before
    assert history(root) == previous_history


def test_undo_history_failure_restores_moved_files(tmp_path, monkeypatch):
    analyzer, root, plan_id = fixture(tmp_path)
    analyzer.apply_function_move(plan_id)
    before, previous_history = sources(root), history(root)
    inject_failure(monkeypatch, analyzer._sessions.current().service, "history.json")
    with pytest.raises(OSError, match="injected"):
        analyzer.undo_last_move()
    assert sources(root) == before
    assert history(root) == previous_history


def test_rollback_refuses_external_edit(tmp_path, monkeypatch):
    analyzer, root, plan_id = fixture(tmp_path)
    original = analyzer._sessions.current().service._atomic_write
    def sabotage(path, text):
        if path.name == "b.py":
            (root / "a.py").write_text("# external edit\n")
            raise OSError("injected failure with concurrent edit")
        return original(path, text)
    monkeypatch.setattr(analyzer._sessions.current().service, "_atomic_write", sabotage)
    with pytest.raises(RuntimeError, match="rollback incomplete"):
        analyzer.apply_function_move(plan_id)
    assert (root / "a.py").read_text() == "# external edit\n"
    assert history(root) is None
