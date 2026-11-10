"""Crash interleaving and explicit reconciliation, no automatic overwrites."""
import pytest
from code_analyzer import CodeAnalyzer
from test_p519_transaction_recovery import fixture, sources, history


def _crash_after_first_write(analyzer, monkeypatch):
    svc = analyzer._sessions.current().service
    original = svc._atomic_write
    fired = False
    def interrupt(path, text):
        nonlocal fired
        original(path, text)
        if path.name == 'a.py' and not fired:
            fired = True
            raise KeyboardInterrupt('simulated process stop')
    monkeypatch.setattr(svc, '_atomic_write', interrupt)
    return svc


def test_interrupted_move_preserves_journal_and_requires_explicit_recovery(tmp_path, monkeypatch):
    analyzer, root, plan_id = fixture(tmp_path)
    before = sources(root)
    svc = _crash_after_first_write(analyzer, monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        analyzer.apply_function_move(plan_id)
    reports = svc.pending_transactions()
    assert len(reports) == 1 and reports[0]['status'] == 'partial'
    assert reports[0]['history_state'] == 'before'
    with pytest.raises(ValueError, match='unfinished source transaction'):
        analyzer.apply_function_move(plan_id)
    assert svc.reconcile_transaction(reports[0]['transaction_id']) == 'rolled_back'
    assert sources(root) == before
    assert history(root) is None
    assert svc.pending_transactions() == []


def test_external_edit_refuses_crash_recovery(tmp_path, monkeypatch):
    analyzer, root, plan_id = fixture(tmp_path)
    svc = _crash_after_first_write(analyzer, monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        analyzer.apply_function_move(plan_id)
    (root / 'a.py').write_text('# external change\n')
    report = svc.pending_transactions()[0]
    assert report['status'] == 'manual_review'
    with pytest.raises(ValueError, match='manual recovery'):
        svc.reconcile_transaction(report['transaction_id'])
    assert (root / 'a.py').read_text() == '# external change\n'
    assert len(svc.pending_transactions()) == 1


def test_crash_after_history_publish_finalizes_without_source_rewrite(tmp_path, monkeypatch):
    analyzer, root, plan_id = fixture(tmp_path)
    svc = analyzer._sessions.current().service
    def interrupted_cleanup(_transaction_id):
        raise KeyboardInterrupt('simulated process stop after publication')
    monkeypatch.setattr(svc, '_clear_journal', interrupted_cleanup)
    with pytest.raises(KeyboardInterrupt):
        analyzer.apply_function_move(plan_id)
    report = svc.pending_transactions()[0]
    assert report['status'] == 'written' and report['history_state'] == 'after'
    snapshot = sources(root)
    monkeypatch.undo()
    assert svc.reconcile_transaction(report['transaction_id']) == 'committed'
    assert sources(root) == snapshot
    assert svc.pending_transactions() == []


def test_corrupt_journal_blocks_changes(tmp_path):
    analyzer, root, plan_id = fixture(tmp_path)
    svc = analyzer._sessions.current().service
    svc.journal_dir.mkdir(parents=True)
    (svc.journal_dir / 'unknown.json').write_text('not json')
    assert svc.pending_transactions()[0]['status'] == 'manual_review'
    with pytest.raises(ValueError, match='unfinished source transaction'):
        analyzer.apply_function_move(plan_id)
