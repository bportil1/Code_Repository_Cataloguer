"""P5-12: exact cached comparisons and explicit incomplete matrix windows."""
from __future__ import annotations

import csv
import io
import os
from pathlib import Path
import sqlite3

import pytest

from code_analyzer import CodeAnalyzer
from code_analyzer.similarity import pair_cache
from code_analyzer.similarity.engine import SimilarityConfig, compare_functions
from code_analyzer.similarity.matrix import compute_similarity_matrix


def make_project(root: Path) -> Path:
    root.mkdir(exist_ok=True, parents=True)
    (root / 'a.py').write_text('''def alpha(input):
    return beta(input)

def beta(value):
    return value + 1
''', encoding='utf-8')
    (root / 'b.py').write_text('''def gamma(value):
    return value + 2

def delta(data):
    return gamma(data)
''', encoding='utf-8')
    return root


def test_cache_reuse_is_exhaustive_and_numerically_identical(tmp_path, monkeypatch):
    analyzer = CodeAnalyzer(make_project(tmp_path), use_gitignore=False)
    direct = compute_similarity_matrix(analyzer.graph())
    count = 0
    original = pair_cache.compare_functions

    def counted(*args, **kwargs):
        nonlocal count
        count += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(pair_cache, 'compare_functions', counted)
    first = analyzer.similarity_matrix()
    assert first.matrix == direct.matrix
    assert count == 6  # four functions, every unordered off-diagonal pair
    assert analyzer.similarity_matrix().matrix == direct.matrix
    assert count == 6
    duplicate = analyzer.duplicate_candidates(threshold=0.0)
    assert duplicate['summary']['compared_pair_count'] == 6
    assert count == 6
    target = direct.labels[0]
    assert len(analyzer.similarity_neighbors(target)['neighbors']) == 3
    assert count == 6
    assert len(analyzer.clusters(k=2)['clusters']) == 2
    assert count == 6
    assert (tmp_path / '.codebase_catalog/similarity_pairs.sqlite3').exists()


def test_config_and_source_changes_invalidate_cache(tmp_path, monkeypatch):
    analyzer = CodeAnalyzer(make_project(tmp_path), use_gitignore=False)
    count = 0
    original = pair_cache.compare_functions

    def counted(*args, **kwargs):
        nonlocal count
        count += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(pair_cache, 'compare_functions', counted)
    analyzer.similarity_matrix()
    assert count == 6
    analyzer.similarity_matrix(distance_decay=0.25)
    assert count == 12
    analyzer.similarity_matrix(distance_decay=0.25)
    assert count == 12
    changed = tmp_path / 'a.py'
    before = changed.stat()
    raw = changed.read_text()
    changed.write_text(raw.replace('beta(', 'zeta('))
    os.utime(changed, ns=(before.st_atime_ns, before.st_mtime_ns))
    analyzer.similarity_matrix()
    assert count == 18
    # Repeat after source-index refresh: no more misses.
    analyzer.similarity_matrix()
    assert count == 18


def test_modified_cached_score_is_recomputed(tmp_path, monkeypatch):
    analyzer = CodeAnalyzer(make_project(tmp_path), use_gitignore=False)
    full = analyzer.similarity_matrix()
    path = tmp_path / '.codebase_catalog/similarity_pairs.sqlite3'
    with sqlite3.connect(path) as connection:
        connection.execute('UPDATE pair_scores SET score = 0.99999 LIMIT 1')
    original = pair_cache.compare_functions
    calls = []

    def counted(*args, **kwargs):
        calls.append(args[1:3])
        return original(*args, **kwargs)

    monkeypatch.setattr(pair_cache, 'compare_functions', counted)
    assert analyzer.similarity_matrix().matrix == full.matrix
    assert len(calls) == 1


def test_corrupt_cache_is_rebuilt(tmp_path):
    analyzer = CodeAnalyzer(make_project(tmp_path), use_gitignore=False)
    expected = analyzer.similarity_matrix().matrix
    path = tmp_path / '.codebase_catalog/similarity_pairs.sqlite3'
    path.write_bytes(b'broken sqlite content')
    assert analyzer.similarity_matrix().matrix == expected
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT count(*) FROM pair_scores').fetchone()[0] == 6


def test_window_cells_match_full_matrix_without_claiming_exhaustiveness(tmp_path):
    analyzer = CodeAnalyzer(make_project(tmp_path), use_gitignore=False)
    expected = analyzer.similarity_matrix()
    window = analyzer.similarity_matrix_window(row_offset=1, row_limit=2, column_offset=2, column_limit=2)
    assert window['complete'] is False
    assert window['data_scope'] == 'window'
    assert window['total_upper_triangle_pairs'] == 10
    assert window['matrix'] == [list(row[2:4]) for row in expected.matrix[1:3]]
    assert window['row_labels'] == list(expected.labels[1:3])
    assert window['column_labels'] == list(expected.labels[2:4])
    with pytest.raises(ValueError):
        analyzer.similarity_matrix_window(row_offset=-1)
    with pytest.raises(ValueError):
        analyzer.similarity_matrix_window(row_limit=501)
    with pytest.raises(ValueError):
        analyzer.similarity_matrix_window(column_offset=True)


def test_complete_csv_export_includes_cells_outside_window(tmp_path):
    analyzer = CodeAnalyzer(make_project(tmp_path), use_gitignore=False)
    analyzer.similarity_matrix_window(row_offset=2, column_offset=2, row_limit=1, column_limit=1)
    expected = analyzer.similarity_matrix()
    reader = csv.reader(io.StringIO(''.join(analyzer.iter_similarity_matrix_csv())))
    rows = list(reader)
    assert rows[0] == ['qualified_name', *expected.labels]
    assert len(rows) == 1 + len(expected.labels)
    for i, row in enumerate(rows[1:]):
        assert row[0] == expected.labels[i]
        assert [float(item) for item in row[1:]] == pytest.approx(expected.matrix[i], abs=1e-9)


def test_repository_switch_has_separate_cache(tmp_path):
    left = make_project(tmp_path / 'left')
    right = make_project(tmp_path / 'right')
    analyzer = CodeAnalyzer(left, use_gitignore=False)
    analyzer.similarity_matrix()
    analyzer.open_repository(right)
    analyzer.similarity_matrix()
    assert (left / '.codebase_catalog/similarity_pairs.sqlite3').is_file()
    assert (right / '.codebase_catalog/similarity_pairs.sqlite3').is_file()


def test_symlinked_cache_does_not_write_outside_project(tmp_path):
    root = make_project(tmp_path / 'root')
    external = tmp_path / 'other.sqlite3'
    external.write_text('leave intact', encoding='utf-8')
    analyzer = CodeAnalyzer(root, use_gitignore=False)
    cache = root / '.codebase_catalog' / 'similarity_pairs.sqlite3'
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.symlink_to(external)
    expected = compute_similarity_matrix(analyzer.graph()).matrix
    assert analyzer.similarity_matrix().matrix == expected
    assert external.read_text() == 'leave intact'


def test_direct_duplicate_algorithm_unchanged(tmp_path):
    analyzer = CodeAnalyzer(make_project(tmp_path), use_gitignore=False)
    from code_analyzer.similarity.duplicates import find_duplicate_candidates
    graph = analyzer.graph()
    expected = find_duplicate_candidates(graph, threshold=0.0)
    actual = analyzer.duplicate_candidates(threshold=0.0, include_source=False)
    assert actual == expected


def test_browser_window_contract_present():
    root = Path(__file__).resolve().parents[1]
    js = (root / 'code_analyzer/web/static/similarity.js').read_text()
    html = (root / 'code_analyzer/web/templates/report.html').read_text()
    assert '/api/similarity/matrix-window' in js
    assert 'data_scope:isWindow' in js
    assert '/api/similarity/matrix.csv' in js
    assert 'Partial view; no approximation' in js
    assert 'similarity-matrix-window-controls' in html


def test_http_windows_and_full_export_when_flask_available(tmp_path):
    pytest.importorskip('flask')
    from code_analyzer.web.app import create_app
    app = create_app(make_project(tmp_path), use_gitignore=False)
    client = app.test_client()
    window = client.post('/api/similarity/matrix-window', json={
        'row_offset': 0, 'row_limit': 2, 'column_offset': 1, 'column_limit': 2,
    })
    assert window.status_code == 200
    assert window.get_json()['data_scope'] == 'window'
    export = client.post('/api/similarity/matrix.csv', json={})
    assert export.status_code == 200
    assert len(list(csv.reader(io.StringIO(export.get_data(as_text=True))))) == 5
