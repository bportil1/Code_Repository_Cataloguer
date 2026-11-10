"""P5-19 apply-time path containment and descriptor-based source tests."""
import pytest
from code_analyzer import CodeAnalyzer


def setup_move(tmp_path, nested=False):
    root = tmp_path / 'project'
    root.mkdir()
    source_dir = root / 'pkg' if nested else root
    source_dir.mkdir(exist_ok=True)
    (source_dir / 'a.py').write_text('def alpha():\n    return 1\n')
    (root / 'b.py').write_text('def beta():\n    return 2\n')
    analyzer = CodeAnalyzer(root, use_gitignore=False)
    cat = analyzer.catalog()
    fn = next(k for k, node in cat.nodes.items() if node.node_type == 'function' and node.name == 'alpha')
    target = next(k for k, node in cat.nodes.items() if node.node_type == 'module' and node.path == 'b.py')
    plan = analyzer.preview_function_move(fn, target)
    return analyzer, root, plan['plan_id']


def test_replaced_source_symlink_after_preview_fails_closed(tmp_path):
    analyzer, root, plan = setup_move(tmp_path)
    outside = tmp_path / 'outside.py'
    outside.write_text('outside\n')
    (root / 'a.py').unlink()
    (root / 'a.py').symlink_to(outside)
    with pytest.raises(ValueError, match='unsafe|symlink'):
        analyzer.apply_function_move(plan)
    assert outside.read_text() == 'outside\n'
    assert 'def beta' in (root / 'b.py').read_text()


def test_symlinked_parent_after_preview_fails_closed(tmp_path):
    analyzer, root, plan = setup_move(tmp_path, nested=True)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'a.py').write_text('outside\n')
    (root / 'pkg').rename(root / 'original_pkg')
    (root / 'pkg').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='unsafe|symlink'):
        analyzer.apply_function_move(plan)
    assert (outside / 'a.py').read_text() == 'outside\n'
    assert 'def beta' in (root / 'b.py').read_text()


def test_source_replaced_immediately_before_write_rolls_back(tmp_path, monkeypatch):
    analyzer, root, plan = setup_move(tmp_path)
    service = analyzer._sessions.current().service
    original = service._atomic_write
    outside = tmp_path / 'outside.py'
    outside.write_text('outside\n')
    def replace_before_write(path, text):
        if path.name == 'a.py':
            path.unlink()
            path.symlink_to(outside)
        return original(path, text)
    monkeypatch.setattr(service, '_atomic_write', replace_before_write)
    with pytest.raises((ValueError, RuntimeError), match='nonregular|symlink|rollback'):
        analyzer.apply_function_move(plan)
    assert outside.read_text() == 'outside\n'
    assert 'def beta' in (root / 'b.py').read_text()


def test_nested_regular_file_move_and_undo(tmp_path):
    analyzer, root, plan = setup_move(tmp_path, nested=True)
    assert analyzer.apply_function_move(plan)['success']
    assert analyzer.undo_last_move()['success']
    assert 'def alpha' in (root / 'pkg' / 'a.py').read_text()
