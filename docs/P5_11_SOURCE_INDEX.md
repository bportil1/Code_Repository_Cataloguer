# P5-11 — Project-local source and symbol index

This is a **rebuildable lookup index**, not a replacement for the AST catalog.
`CodeAnalyzer.catalog()` remains authoritative for source analysis, and the
existing similarity, graph, report, move-preview, apply, and undo behavior is
unchanged.

## Ownership and data model

Each analyzed repository owns its own SQLite file:

```
<repository>/.codebase_catalog/source_index.sqlite3
```

The index is deliberately scoped to the Python sources supported by the
current AST engine. It records:

- Relative `.py` file paths, SHA-256 hashes, byte sizes, mtimes, module names,
  line counts, and syntax errors.
- The catalog's existing IDs, types, qualified names, parent IDs, and source
  spans for modules, classes, functions, and methods.
- Import, call, and other pre-existing catalog relationship records, including
  existing source evidence fields.

Source bodies, model outputs, cross-project state, and full function similarity
matrices are **not** copied into SQLite. Non-Python source indexing remains a
future capability, requiring a parser contract of its own. The `.codebase_catalog`
folder is already excluded by the repository scanner.

## Python API

```python
from code_analyzer import CodeAnalyzer

analyzer = CodeAnalyzer('/absolute/path/to/project')
state = analyzer.source_index_status()
# Optional explicit build (lookup will also build when needed):
analyzer.rebuild_source_index()

files = analyzer.lookup_source_files(path='service.py', limit=50)
symbols = analyzer.lookup_symbols(kind='function', text='parse', limit=50)
locations = analyzer.lookup_symbols(path='src/service.py', line=42)
calls = analyzer.lookup_dependencies(relationship='calls', source_id='function:service.parse')
```

Searches transparently build an absent or stale index from a **fresh AST
catalog**. The index can be deleted and rebuilt without changing source files
or previous report artifacts.

All lookup APIs return `{total, limit, offset, items}`; unbounded results are
not exposed. IDs and source ranges retain the existing catalog semantics.

## Command-line access

The existing HTML-report CLI remains unchanged. A separate optional local
command is available:

```bash
python -m code_analyzer.source_index /path/to/repo build
python -m code_analyzer.source_index /path/to/repo status
python -m code_analyzer.source_index /path/to/repo files --path service.py
python -m code_analyzer.source_index /path/to/repo symbols --kind function --text parse
python -m code_analyzer.source_index /path/to/repo dependencies --relationship calls --limit 100
```

## Invalidation and integrity

Normal lookup checks the discovered Python file set, file sizes, and
nanosecond modification times. Missing, modified, or corrupt indexes are
rebuilt atomically. Explicit `source_index_status(verify_contents=True)` also
re-hashes every source file to detect same-size/same-mtime changes.

A SHA-256 hash is returned with source lookup results. **Before using a source
location to edit or remediate code, consumers must re-read the targeted file,
verify its SHA-256 hash, and verify the relevant source span.** A lookup is
historical evidence, not authorization to edit. The normal fast freshness
check cannot detect tampering that preserves the source file's mtime and size.

A snapshot is never written outside the project root. Index paths and scanned
source files that escape via symlinks are rejected, and failed rebuilds leave
previous index bytes unchanged. Rebuild can be invoked explicitly after
refactoring, and the next lookup will also recognize ordinary source changes.

## Migration boundaries and future work

This sprint adds a headless index and public API only; no Flask route or visual
component is replaced. Indexed similarity caches, incremental AST indexing,
source navigation within PAH, and the source remediation handoff are separate
future sprints. PAH must not access this SQLite file directly: cross-module
requests should go through the CodeAnalyzer API or a module-owned adapter.
