import json

import pytest

from code_analyzer import CodeAnalyzer


def _move(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    (root / 'a.py').write_text('def alpha():\n    return 1\n', encoding='utf-8')
    (root / 'b.py').write_text('def beta():\n    return 2\n', encoding='utf-8')
    analyzer = CodeAnalyzer(root, use_gitignore=False)
    cat = analyzer.catalog()
    function_id = next(k for k, v in cat.nodes.items() if v.node_type == 'function' and v.name == 'alpha')
    target_id = next(k for k, v in cat.nodes.items() if v.node_type == 'module' and v.path == 'b.py')
    plan = analyzer.preview_function_move(function_id, target_id)
    assert analyzer.apply_function_move(plan['plan_id'])['success']
    return analyzer, root


def test_unchanged_move_can_be_undone(tmp_path):
    analyzer, root = _move(tmp_path)
    assert analyzer.undo_last_move()['success']
    assert 'def alpha' in (root / 'a.py').read_text()
    assert 'def alpha' not in (root / 'b.py').read_text()


@pytest.mark.parametrize('edited', ['a.py', 'b.py'])
def test_modified_source_aborts_entire_undo(tmp_path, edited):
    analyzer, root = _move(tmp_path)
    path = root / edited
    path.write_text(path.read_text() + '\n# subsequent human edit\n')
    before = {name: (root / name).read_bytes() for name in ('a.py', 'b.py')}
    history = root / '.codebase_catalog' / 'history.json'
    old_history = history.read_bytes()
    with pytest.raises(ValueError, match='changed since the move'):
        analyzer.undo_last_move()
    assert before == {name: (root / name).read_bytes() for name in before}
    assert history.read_bytes() == old_history


def test_legacy_history_fails_closed(tmp_path):
    analyzer, root = _move(tmp_path)
    history = root / '.codebase_catalog' / 'history.json'
    records = json.loads(history.read_text())
    del records[-1]['post_move_sha256']
    history.write_text(json.dumps(records))
    before = {name: (root / name).read_bytes() for name in ('a.py', 'b.py')}
    with pytest.raises(ValueError, match='lacks post-move fingerprints'):
        analyzer.undo_last_move()
    assert before == {name: (root / name).read_bytes() for name in before}


def test_missing_backup_aborts_entire_undo(tmp_path):
    analyzer, root = _move(tmp_path)
    history = json.loads((root / '.codebase_catalog' / 'history.json').read_text())
    (root / '.codebase_catalog' / 'backups' / history[-1]['backup_id'] / 'b.py').unlink()
    before = {name: (root / name).read_bytes() for name in ('a.py', 'b.py')}
    with pytest.raises(ValueError, match='Backup file missing'):
        analyzer.undo_last_move()
    assert before == {name: (root / name).read_bytes() for name in before}


def test_symlink_replacement_aborts_without_writing(tmp_path):
    analyzer, root = _move(tmp_path)
    outside = tmp_path / 'outside.py'
    outside.write_text('secret\n')
    (root / 'b.py').unlink()
    (root / 'b.py').symlink_to(outside)
    old_a = (root / 'a.py').read_bytes()
    with pytest.raises(ValueError, match='unsafe undo path'):
        analyzer.undo_last_move()
    assert (root / 'a.py').read_bytes() == old_a
    assert outside.read_text() == 'secret\n'
