"""P5-19 acceptance gates: source moves, recovery and safe refusal.

Uses temporary repositories only. No external services or real source edits.
"""
import json

import pytest

from code_analyzer import CodeAnalyzer


def _fixture(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'a.py').write_text('def alpha():\n    return 1\n', encoding='utf-8')
    (project / 'b.py').write_text('def beta():\n    return 2\n', encoding='utf-8')
    analyzer = CodeAnalyzer(project, use_gitignore=False)
    catalog = analyzer.catalog()
    fn = next(k for k, node in catalog.nodes.items() if node.node_type == 'function' and node.name == 'alpha')
    target = next(k for k, node in catalog.nodes.items() if node.node_type == 'module' and node.path == 'b.py')
    return analyzer, project, analyzer.preview_function_move(fn, target)['plan_id']


def _contents(root):
    return tuple((root / name).read_bytes() for name in ('a.py', 'b.py'))


def _history(root):
    path = root / '.codebase_catalog' / 'history.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []


def _pending(analyzer):
    return analyzer._sessions.current().service.pending_transactions()


def test_move_undo_roundtrip_persists_across_service_restart(tmp_path):
    analyzer, root, plan_id = _fixture(tmp_path)
    original = _contents(root)
    assert analyzer.apply_function_move(plan_id)['success']
    moved = _contents(root)
    assert moved != original and len(_history(root)) == 1
    assert not _pending(analyzer)
    fresh = CodeAnalyzer(root, use_gitignore=False)
    assert fresh.undo_last_move()['success']
    assert _contents(root) == original
    assert _history(root) == []
    assert not _pending(fresh)


@pytest.mark.parametrize('name', ['a.py', 'b.py'])
def test_external_post_move_edits_refuse_undo_without_mutation(tmp_path, name):
    analyzer, root, plan_id = _fixture(tmp_path)
    assert analyzer.apply_function_move(plan_id)['success']
    (root / name).write_bytes((root / name).read_bytes() + b'\n# external edit\n')
    before = _contents(root)
    previous_history = _history(root)
    with pytest.raises(ValueError, match='changed since the move'):
        analyzer.undo_last_move()
    assert _contents(root) == before and _history(root) == previous_history
    assert not _pending(analyzer)


def test_partial_crash_reconciles_after_restart_without_history(tmp_path, monkeypatch):
    analyzer, root, plan_id = _fixture(tmp_path)
    original = _contents(root)
    svc = analyzer._sessions.current().service
    original_write = svc._atomic_write
    interrupted = False

    def crash_after_first_file(path, text):
        nonlocal interrupted
        original_write(path, text)
        if path.name == 'a.py' and not interrupted:
            interrupted = True
            raise KeyboardInterrupt('simulated abrupt exit')

    monkeypatch.setattr(svc, '_atomic_write', crash_after_first_file)
    with pytest.raises(KeyboardInterrupt):
        analyzer.apply_function_move(plan_id)
    monkeypatch.undo()
    fresh = CodeAnalyzer(root, use_gitignore=False)
    service = fresh._sessions.current().service
    report = service.pending_transactions()
    assert len(report) == 1 and report[0]['status'] == 'partial'
    assert report[0]['history_state'] == 'before'
    with pytest.raises(ValueError, match='unfinished source transaction'):
        fresh.undo_last_move()
    assert service.reconcile_transaction(report[0]['transaction_id']) == 'rolled_back'
    assert _contents(root) == original and _history(root) == []
    assert not service.pending_transactions()


def test_crash_conflict_preserves_external_edit_and_journal(tmp_path, monkeypatch):
    analyzer, root, plan_id = _fixture(tmp_path)
    svc = analyzer._sessions.current().service
    original_write = svc._atomic_write

    def interrupt(path, text):
        original_write(path, text)
        if path.name == 'a.py':
            raise KeyboardInterrupt('simulated stop')

    monkeypatch.setattr(svc, '_atomic_write', interrupt)
    with pytest.raises(KeyboardInterrupt):
        analyzer.apply_function_move(plan_id)
    monkeypatch.undo()
    (root / 'a.py').write_text('# human change\n', encoding='utf-8')
    fresh = CodeAnalyzer(root, use_gitignore=False)
    service = fresh._sessions.current().service
    report = service.pending_transactions()
    assert len(report) == 1 and report[0]['status'] == 'manual_review'
    before = _contents(root)
    with pytest.raises(ValueError, match='manual recovery'):
        service.reconcile_transaction(report[0]['transaction_id'])
    assert _contents(root) == before and len(service.pending_transactions()) == 1


def test_invalid_journal_fails_closed_and_does_not_change_sources(tmp_path):
    analyzer, root, plan_id = _fixture(tmp_path)
    before = _contents(root)
    service = analyzer._sessions.current().service
    service.journal_dir.mkdir(parents=True, exist_ok=True)
    (service.journal_dir / 'invalid.json').write_text('{invalid', encoding='utf-8')
    assert service.pending_transactions()[0]['status'] == 'manual_review'
    with pytest.raises(ValueError, match='unfinished source transaction'):
        analyzer.apply_function_move(plan_id)
    assert _contents(root) == before and _history(root) == []
