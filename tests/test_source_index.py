"""P5-11: source-index preservation, freshness, and isolation tests."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3

import pytest

from code_analyzer import CodeAnalyzer
from code_analyzer.source_index import SourceIndex, SourceIndexError


def _repository(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'alpha.py').write_text(
        'from beta import helper\n\n'
        'class Thing:\n'
        '    def method(self, x):\n'
        '        return helper(x)\n\n'
        'def top(x):\n'
        '    return helper(x)\n', encoding='utf-8'
    )
    (root / 'beta.py').write_text(
        'def helper(x):\n'
        '    return x + 1\n', encoding='utf-8'
    )
    (root / 'README.txt').write_text('Not a Python file', encoding='utf-8')
    return root


def test_source_index_uses_existing_ast_catalog_and_paths(tmp_path: Path):
    analyzer = CodeAnalyzer(_repository(tmp_path), use_gitignore=False)
    assert analyzer.source_index_status()['state'] == 'missing'
    snapshot = analyzer.rebuild_source_index()
    assert snapshot['files'] == 2
    assert snapshot['symbols'] == 6
    assert snapshot['dependencies'] >= 2
    assert analyzer.source_index_status()['state'] == 'current'
    method = analyzer.lookup_symbols(text='method')['items'][0]
    assert method['id'] == 'method:alpha.Thing.method'
    assert method['kind'] == 'method'
    assert method['path'] == 'alpha.py'
    assert (method['line_start'], method['line_end']) == (4, 5)
    assert method['source_sha256'] == hashlib.sha256((tmp_path / 'alpha.py').read_bytes()).hexdigest()
    # No source code bodies are placed in the reference index.
    with sqlite3.connect(snapshot['path']) as conn:
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table'").fetchall()
        assert all('source_code' not in (entry[0] or '') for entry in sql)
    assert analyzer.catalog().nodes[method['id']].metadata['source_code'].strip().startswith('def method')


def test_symbols_filters_pagination_and_line_ranges(tmp_path: Path):
    analyzer = CodeAnalyzer(_repository(tmp_path))
    only = analyzer.lookup_symbols(path='alpha.py', kind='function', limit=1)
    assert only['total'] == 1
    assert only['items'][0]['name'] == 'top'
    assert analyzer.lookup_symbols(path='alpha.py', kind='method', line=4)['items'][0]['name'] == 'method'
    assert analyzer.lookup_symbols(text='Thi%')['total'] == 0
    all_symbols = analyzer.lookup_symbols(limit=2, offset=2)
    assert all_symbols['total'] == 6
    assert len(all_symbols['items']) == 2
    with pytest.raises(ValueError, match='requires path'):
        analyzer.lookup_symbols(line=2)
    with pytest.raises(ValueError, match='Unknown symbol'):
        analyzer.lookup_symbols(kind='import')
    with pytest.raises(ValueError):
        analyzer.lookup_symbols(limit=2000)


def test_file_lookup_includes_parse_errors_and_hashes(tmp_path: Path):
    root = _repository(tmp_path)
    (root / 'broken.py').write_text('def wrong(:\n    pass\n', encoding='utf-8')
    analyzer = CodeAnalyzer(root)
    result = analyzer.lookup_source_files(path='.py', limit=2)
    assert result['total'] == 3
    assert len(result['items']) == 2
    bad = analyzer.lookup_source_files(path='broken.py')['items'][0]
    assert bad['parse_error']
    assert bad['module_name'] == 'broken'
    assert bad['sha256'] == hashlib.sha256((root / 'broken.py').read_bytes()).hexdigest()
    assert all('/' not in row['path'] for row in result['items'])


def test_dependency_queries_preserve_import_and_call_evidence(tmp_path: Path):
    analyzer = CodeAnalyzer(_repository(tmp_path))
    calls = analyzer.lookup_dependencies(relationship='calls', path='alpha.py')
    assert calls['total'] == 2
    assert set(e['source_id'] for e in calls['items']) == {
        'method:alpha.Thing.method', 'function:alpha.top'
    }
    assert all(e['target_id'] == 'function:beta.helper' for e in calls['items'])
    assert all(e['evidence_file'] == 'alpha.py' for e in calls['items'])
    assert analyzer.lookup_dependencies(source_id='function:alpha.top')['total'] >= 1
    assert analyzer.lookup_dependencies(target_id='function:beta.helper')['total'] == 2


def test_automatic_rebuild_on_change_and_file_add_delete(tmp_path: Path):
    analyzer = CodeAnalyzer(_repository(tmp_path))
    original = analyzer.lookup_symbols(text='top')['items'][0]['source_sha256']
    (tmp_path / 'alpha.py').write_text('def top(x):\n    return x * 10\n', encoding='utf-8')
    assert analyzer.source_index_status()['state'] == 'stale'
    current = analyzer.lookup_symbols(text='top')
    assert current['total'] == 1
    assert current['items'][0]['source_sha256'] != original
    assert analyzer.lookup_symbols(text='Thing')['total'] == 0
    (tmp_path / 'extra.py').write_text('class Extra:\n    pass\n', encoding='utf-8')
    assert analyzer.source_index_status()['reason'] == 'source_set_changed'
    assert analyzer.lookup_symbols(text='Extra', kind='class')['total'] == 1
    (tmp_path / 'extra.py').unlink()
    assert analyzer.lookup_symbols(text='Extra')['total'] == 0
    assert analyzer.source_index_status()['state'] == 'current'


def test_deep_hash_detects_same_stat_source_change(tmp_path: Path):
    analyzer = CodeAnalyzer(_repository(tmp_path))
    analyzer.rebuild_source_index()
    path = tmp_path / 'beta.py'
    old = path.stat()
    old_bytes = path.read_bytes()
    path.write_bytes(old_bytes.replace(b'+ 1', b'+ 2'))
    import os
    os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert analyzer.source_index_status()['state'] == 'current'
    assert analyzer.source_index_status(verify_contents=True)['reason'] == 'source_hash_changed'


def test_corrupt_db_rebuilt_automatically(tmp_path: Path):
    analyzer = CodeAnalyzer(_repository(tmp_path))
    analyzer.rebuild_source_index()
    index_path = tmp_path / '.codebase_catalog' / 'source_index.sqlite3'
    index_path.write_bytes(b'not a sqlite database')
    assert analyzer.source_index_status()['state'] == 'invalid'
    assert analyzer.lookup_symbols(text='helper')['total'] == 1
    assert analyzer.source_index_status()['state'] == 'current'


def test_failed_rebuild_preserves_existing_index(tmp_path: Path):
    root = _repository(tmp_path / 'repo')
    other = _repository(tmp_path / 'other')
    analyzer = CodeAnalyzer(root)
    analyzer.rebuild_source_index()
    index = SourceIndex(root)
    old_hash = hashlib.sha256(index.path.read_bytes()).hexdigest()
    with pytest.raises(SourceIndexError, match='different project'):
        index.rebuild(CodeAnalyzer(other).catalog())
    assert hashlib.sha256(index.path.read_bytes()).hexdigest() == old_hash
    assert analyzer.lookup_symbols(text='top')['total'] == 1


def test_isolation_and_repository_switching(tmp_path: Path):
    first = _repository(tmp_path / 'first')
    second = _repository(tmp_path / 'second')
    (second / 'gamma.py').write_text('def gamma():\n    pass\n', encoding='utf-8')
    analyzer = CodeAnalyzer(first)
    assert analyzer.lookup_symbols(text='gamma')['total'] == 0
    analyzer.open_repository(second)
    assert analyzer.lookup_symbols(text='gamma', kind='function')['total'] == 1
    assert analyzer.lookup_symbols(text='gamma', kind='function')['items'][0]['path'] == 'gamma.py'
    assert SourceIndex(first).symbols(text='gamma')['total'] == 0
    assert SourceIndex(second).symbols(text='gamma', kind='function')['total'] == 1
    assert (first / '.codebase_catalog' / 'source_index.sqlite3').is_file()
    assert (second / '.codebase_catalog' / 'source_index.sqlite3').is_file()


def test_external_symlink_not_indexed(tmp_path: Path):
    root = _repository(tmp_path / 'repo')
    outside = tmp_path / 'outside.py'
    outside.write_text('def secret():\n    pass\n', encoding='utf-8')
    (root / 'link.py').symlink_to(outside)
    analyzer = CodeAnalyzer(root)
    with pytest.raises(SourceIndexError, match='escapes project'):
        analyzer.rebuild_source_index()
    assert not (root / '.codebase_catalog' / 'source_index.sqlite3').exists()


def test_symlink_index_location_rejected(tmp_path: Path):
    root = _repository(tmp_path / 'repo')
    other = tmp_path / 'other.sqlite3'
    other.write_bytes(b'unrelated')
    state = root / '.codebase_catalog'
    state.mkdir()
    (state / 'source_index.sqlite3').symlink_to(other)
    analyzer = CodeAnalyzer(root)
    assert analyzer.source_index_status()['state'] == 'invalid'
    with pytest.raises(SourceIndexError, match='symlink'):
        analyzer.rebuild_source_index()
    assert other.read_bytes() == b'unrelated'


def test_change_scan_options_marks_index_stale(tmp_path: Path):
    root = _repository(tmp_path)
    source = CodeAnalyzer(root, use_gitignore=True)
    source.rebuild_source_index()
    different = SourceIndex(root, use_gitignore=False)
    assert different.status() == {'state': 'stale', 'reason': 'scan_options_changed'}


def test_source_edits_via_existing_move_workflow_stale_index(tmp_path: Path):
    root = _repository(tmp_path)
    analyzer = CodeAnalyzer(root)
    analyzer.rebuild_source_index()
    moved = analyzer.preview_function_move('function:alpha.top', 'module:beta')
    assert moved['valid'] is True
    analyzer.apply_function_move(moved['plan_id'])
    assert analyzer.source_index_status()['state'] == 'stale'
    moved_record = analyzer.lookup_symbols(text='beta.top')
    assert moved_record['total'] == 1
    analyzer.undo_last_move()
    assert analyzer.lookup_symbols(text='alpha.top')['total'] == 1
