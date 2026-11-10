"""Rebuildable, project-local SQLite lookup for Code Analyzer source evidence.

The existing AST catalog is authoritative. This module stores only index metadata:
file hashes, symbol identities/locations, and dependency edges. It never edits code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Iterable

from .catalog.models import ProjectCatalog
from .catalog.scanner import discover_entries

SCHEMA_VERSION = 1
INDEX_RELATIVE_PATH = Path('.codebase_catalog') / 'source_index.sqlite3'
SYMBOL_KINDS = frozenset({'module', 'class', 'function', 'method'})


class SourceIndexError(ValueError):
    """Source index is missing, stale, damaged, or unsafe to use."""


def _is_inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def _fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _source_files(root: Path, excludes: set[str], gitignore: bool) -> dict[str, Path]:
    _dirs, files = discover_entries(root, excludes, gitignore)
    result = {}
    for path in files:
        if path.suffix != '.py':
            continue
        relative = path.relative_to(root).as_posix()
        if not _is_inside(root, path):
            raise SourceIndexError(f'Source file escapes project root: {relative}')
        result[relative] = path
    return result


def _page(limit: int, offset: int) -> tuple[int, int]:
    if isinstance(limit, bool) or isinstance(offset, bool) or not isinstance(limit, int) or not isinstance(offset, int):
        raise ValueError('limit and offset must be integers')
    if limit < 1 or limit > 500 or offset < 0:
        raise ValueError('limit must be 1..500 and offset must be nonnegative')
    return limit, offset


def _like(term: str) -> str:
    return '%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


class SourceIndex:
    """Index owned by one repository, never by the PAH host or another module."""

    def __init__(self, project_root: str | Path, *, extra_excludes: Iterable[str] = (), use_gitignore: bool = True):
        root = Path(project_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f'Not a repository directory: {root}')
        self.root = root
        self.path = root / INDEX_RELATIVE_PATH
        self.extra_excludes = set(extra_excludes)
        self.use_gitignore = use_gitignore

    def _connect(self) -> sqlite3.Connection:
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise SourceIndexError('Source index cannot be accessed through a symlink')
        if not self.path.is_file():
            raise SourceIndexError('Source index has not been built')
        try:
            conn = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.DatabaseError as exc:
            raise SourceIndexError('Source index cannot be opened') from exc

    def status(self, *, verify_contents: bool = False) -> dict:
        """Cheap stat-based freshness by default; full SHA checks when requested.

        Callers acting on source locations must separately verify the specific file
        hash immediately before editing or applying a source transformation.
        """
        if self.path.is_symlink() or self.path.parent.is_symlink():
            return {'state': 'invalid', 'reason': 'index_symlink'}
        if not self.path.exists():
            return {'state': 'missing', 'reason': 'not_built'}
        try:
            with self._connect() as conn:
                version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
                stored_root = conn.execute("SELECT value FROM meta WHERE key='project_root'").fetchone()
                options = conn.execute("SELECT value FROM meta WHERE key='scan_options'").fetchone()
                if not version or version[0] != str(SCHEMA_VERSION) or not stored_root or stored_root[0] != str(self.root):
                    return {'state': 'invalid', 'reason': 'schema_or_root_mismatch'}
                expected_options = json.dumps([sorted(self.extra_excludes), self.use_gitignore])
                if not options or options[0] != expected_options:
                    return {'state': 'stale', 'reason': 'scan_options_changed'}
                old_files = {row['path']: row for row in conn.execute('SELECT path, size_bytes, mtime_ns, sha256 FROM files')}
                count = conn.execute('SELECT COUNT(*) FROM symbols').fetchone()[0]
                edge_count = conn.execute('SELECT COUNT(*) FROM dependencies').fetchone()[0]
            current = _source_files(self.root, self.extra_excludes, self.use_gitignore)
            if set(current) != set(old_files):
                return {'state': 'stale', 'reason': 'source_set_changed'}
            for relative, path in current.items():
                stats = path.stat()
                saved = old_files[relative]
                if stats.st_size != saved['size_bytes'] or stats.st_mtime_ns != saved['mtime_ns']:
                    return {'state': 'stale', 'reason': 'source_modified', 'path': relative}
                if verify_contents and _fingerprint(path) != saved['sha256']:
                    return {'state': 'stale', 'reason': 'source_hash_changed', 'path': relative}
            return {'state': 'current', 'files': len(current), 'symbols': count, 'dependencies': edge_count}
        except (sqlite3.DatabaseError, OSError, ValueError) as exc:
            return {'state': 'invalid', 'reason': type(exc).__name__}

    def rebuild(self, catalog: ProjectCatalog) -> dict:
        """Rebuild atomically from a freshly computed authoritative catalog."""
        if Path(catalog.project_root).resolve() != self.root:
            raise SourceIndexError('Catalog belongs to a different project')
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise SourceIndexError('Refusing index location through a symlink')
        sources = _source_files(self.root, self.extra_excludes, self.use_gitignore)
        indexed_modules = {m.path for m in catalog.modules}
        if indexed_modules != set(sources):
            raise SourceIndexError('Catalog source inventory differs from scanned files; refresh the catalog')
        file_info = []
        module_info = {m.path: m for m in catalog.modules}
        for relative, path in sorted(sources.items()):
            before = path.stat()
            digest = _fingerprint(path)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise SourceIndexError(f'Source changed during indexing: {relative}')
            module = module_info[relative]
            file_info.append((relative, digest, after.st_size, after.st_mtime_ns,
                              module.module_name, module.line_count, module.parse_error))
        symbols = []
        for node in catalog.nodes.values():
            if node.node_type not in SYMBOL_KINDS or not node.path:
                continue
            if node.path not in sources:
                raise SourceIndexError(f'Catalog symbol outside source inventory: {node.path}')
            meta = node.metadata or {}
            start = meta.get('line_start')
            end = meta.get('line_end')
            symbols.append((node.id, node.node_type, node.name, node.qualified_name, node.path,
                            node.parent_id, int(start) if start is not None else None,
                            int(end) if end is not None else None, str(meta.get('signature', ''))))
        edges = []
        for edge in catalog.relationships:
            evidence = edge.evidence or {}
            path = evidence.get('file')
            if path is not None and path not in sources:
                # Other kinds of relationships can be derived without a file.
                path = None
            edges.append((edge.source_id, edge.target_id, edge.relationship_type,
                          edge.source_level, edge.target_level, path,
                          json.dumps(evidence, sort_keys=True, default=str)))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.source_index-', suffix='.sqlite3', dir=self.path.parent)
        os.close(fd)
        try:
            with sqlite3.connect(temporary) as conn:
                conn.executescript('''
                    PRAGMA journal_mode=DELETE;
                    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE files (path TEXT PRIMARY KEY, sha256 TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
                        module_name TEXT NOT NULL, line_count INTEGER NOT NULL, parse_error TEXT);
                    CREATE TABLE symbols (id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
                        qualified_name TEXT, path TEXT NOT NULL REFERENCES files(path),
                        parent_id TEXT, line_start INTEGER, line_end INTEGER, signature TEXT NOT NULL);
                    CREATE INDEX symbols_kind_name ON symbols(kind, name);
                    CREATE INDEX symbols_path_line ON symbols(path, line_start, line_end);
                    CREATE TABLE dependencies (source_id TEXT NOT NULL, target_id TEXT NOT NULL,
                        relationship TEXT NOT NULL, source_level TEXT NOT NULL, target_level TEXT NOT NULL,
                        evidence_file TEXT, evidence_json TEXT NOT NULL);
                    CREATE INDEX dependencies_from ON dependencies(source_id, relationship);
                    CREATE INDEX dependencies_to ON dependencies(target_id, relationship);
                    CREATE INDEX dependencies_path ON dependencies(evidence_file);
                ''')
                conn.executemany('INSERT INTO meta VALUES (?, ?)', [
                    ('schema_version', str(SCHEMA_VERSION)), ('project_root', str(self.root)),
                    ('scan_options', json.dumps([sorted(self.extra_excludes), self.use_gitignore])),
                ])
                conn.executemany('INSERT INTO files VALUES (?,?,?,?,?,?,?)', file_info)
                conn.executemany('INSERT INTO symbols VALUES (?,?,?,?,?,?,?,?,?)', symbols)
                conn.executemany('INSERT INTO dependencies VALUES (?,?,?,?,?,?,?)', edges)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {'state': 'current', 'files': len(file_info), 'symbols': len(symbols), 'dependencies': len(edges), 'path': str(self.path)}

    def _require_current(self) -> None:
        result = self.status()
        if result['state'] != 'current':
            raise SourceIndexError(f"Index is {result['state']}: {result.get('reason')}")

    def files(self, *, path: str | None = None, limit: int = 100, offset: int = 0) -> dict:
        """Search indexed Python source paths and parse-error metadata."""
        limit, offset = _page(limit, offset)
        self._require_current()
        clause = " WHERE path LIKE ? ESCAPE '\\'" if path else ""
        args = [_like(path)] if path else []
        with self._connect() as conn:
            count = conn.execute('SELECT COUNT(*) FROM files' + clause, args).fetchone()[0]
            rows = conn.execute('SELECT * FROM files' + clause +
                                ' ORDER BY path LIMIT ? OFFSET ?', [*args, limit, offset]).fetchall()
        return {'total': count, 'limit': limit, 'offset': offset,
                'items': [dict(row) for row in rows]}

    def symbols(self, *, text: str = '', path: str | None = None, kind: str | None = None,
                line: int | None = None, limit: int = 100, offset: int = 0) -> dict:
        limit, offset = _page(limit, offset)
        self._require_current()
        if kind is not None and kind not in SYMBOL_KINDS:
            raise ValueError(f'Unknown symbol kind: {kind}')
        if line is not None and (path is None or isinstance(line, bool) or not isinstance(line, int) or line < 1):
            raise ValueError('line must be a positive integer and requires path')
        clauses, params = [], []
        if text:
            clauses.append("(s.name LIKE ? ESCAPE '\\' OR s.qualified_name LIKE ? ESCAPE '\\')")
            params.extend([_like(text), _like(text)])
        if path is not None:
            clauses.append('s.path = ?')
            params.append(path)
        if kind:
            clauses.append('s.kind = ?')
            params.append(kind)
        if line is not None:
            clauses.append('s.line_start <= ? AND s.line_end >= ?')
            params.extend([line, line])
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        with self._connect() as conn:
            count = conn.execute('SELECT COUNT(*) FROM symbols s' + where, params).fetchone()[0]
            rows = conn.execute('''SELECT s.*, f.sha256 AS source_sha256 FROM symbols s
                JOIN files f ON f.path = s.path''' + where + '''
                ORDER BY s.path, COALESCE(s.line_start, 0), s.kind, s.id LIMIT ? OFFSET ?''',
                [*params, limit, offset]).fetchall()
        return {'total': count, 'offset': offset, 'limit': limit, 'items': [dict(row) for row in rows]}

    def dependencies(self, *, source_id: str | None = None, target_id: str | None = None,
                     relationship: str | None = None, path: str | None = None,
                     limit: int = 100, offset: int = 0) -> dict:
        limit, offset = _page(limit, offset)
        self._require_current()
        clauses, params = [], []
        for col, value in (('source_id', source_id), ('target_id', target_id),
                           ('relationship', relationship), ('evidence_file', path)):
            if value is not None:
                clauses.append(col + ' = ?')
                params.append(value)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        with self._connect() as conn:
            count = conn.execute('SELECT COUNT(*) FROM dependencies' + where, params).fetchone()[0]
            rows = conn.execute('SELECT * FROM dependencies' + where +
                                ' ORDER BY source_id, target_id, relationship, evidence_json LIMIT ? OFFSET ?',
                                [*params, limit, offset]).fetchall()
        return {'total': count, 'offset': offset, 'limit': limit,
                'items': [{**dict(row), 'evidence': json.loads(row['evidence_json'])} for row in rows]}


def main() -> None:
    parser = argparse.ArgumentParser(description='Local Code Analyzer source index (no network access)')
    parser.add_argument('project_root', type=Path)
    parser.add_argument('action', choices=('build', 'status', 'files', 'symbols', 'dependencies'))
    parser.add_argument('--text', default='')
    parser.add_argument('--path')
    parser.add_argument('--kind')
    parser.add_argument('--line', type=int)
    parser.add_argument('--source-id')
    parser.add_argument('--target-id')
    parser.add_argument('--relationship')
    parser.add_argument('--limit', type=int, default=50)
    parser.add_argument('--offset', type=int, default=0)
    args = parser.parse_args()
    from .api import CodeAnalyzer
    analyzer = CodeAnalyzer(args.project_root)
    if args.action == 'build':
        value = analyzer.rebuild_source_index()
    elif args.action == 'status':
        value = analyzer.source_index_status()
    elif args.action == 'files':
        value = analyzer.lookup_source_files(path=args.path, limit=args.limit, offset=args.offset)
    elif args.action == 'symbols':
        value = analyzer.lookup_symbols(text=args.text, path=args.path, kind=args.kind,
                                        line=args.line, limit=args.limit, offset=args.offset)
    else:
        value = analyzer.lookup_dependencies(source_id=args.source_id, target_id=args.target_id,
                                             relationship=args.relationship, path=args.path,
                                             limit=args.limit, offset=args.offset)
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
