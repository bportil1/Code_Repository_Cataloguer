# P5-12 — Similarity measurements and matrix-window retrieval

## Ownership and authoritative state

- Code Analyzer owns all source parsing, Python AST catalogs, similarity calculations,
  and repository-local data. PAH and PAH_Shared do not read the module's SQLite
  databases or calculate similarity scores.
- `code_analyzer.similarity.engine.compare_functions` remains authoritative. The
  persisted cache contains **only completed pair measurements**, not inferred or
  approximate candidates. The descriptor/call-edge graph and similarity config
  are fingerprinted with an implementation revision (`rooted-neighborhood-v1`).
- SQLite: `<analyzed repository>/.codebase_catalog/similarity_pairs.sqlite3`.
  It can be deleted without losing source, catalogs, refactoring history, or any
  scientific result. The cache is automatic and optional *in operation*: if it
  cannot be used, the original engine calculates scores as before.
- A changed source file causes an authoritative AST refresh (content-hash verified,
  even when size/timestamps are preserved). A changed similarity descriptor or
  call graph gets a new graph fingerprint and causes old pair rows to be dropped.
  Source edits that do **not** change the similarity input graph may safely
  reuse a measurement, because the result is mathematically unchanged.
- Different similarity settings are separate keys. Each cache row is checked
  against a SHA-256 payload digest; malformed rows and corrupted databases
  are treated as cache misses and rebuilt. Symlinked index locations are not
  trusted. No source file is edited by caching.

## Entry points

`CodeAnalyzer.similarity_matrix`, `similarity_neighbors`, `duplicate_candidates`,
`clusters` all share this cache. The existing public `compare` function and
source refactoring operations remain unchanged. The algorithms remain exhaustive
where they were previously exhaustive; **candidate pruning is not silently
introduced**. Clustering still uses a full matrix, since K-means depends on every
feature column.

`CodeAnalyzer.similarity_matrix_window(row_offset, row_limit, column_offset,
column_limit, ...)` supplies a bounded 2-D rectangular window of **exact** scores.
Each limit is 1–50, and responses include `data_scope: window`, `complete: false`,
and full row/column coordinates. A window is *not* a complete matrix and has no
full-matrix statistical summary. The old full-matrix endpoint is unchanged.

The browser defaults to the original PAH_Shared full-matrix renderer for up to 80
functions. Above 80, it requests 25×25 windows on demand and uses PAH_Shared's
existing table renderer to show the window. Its internal full-table search,
pagination and exports are hidden for an incomplete dataset; page navigation is
handled by explicit server-window controls. The **Download CSV** action instead
streams a complete exact matrix from `/api/similarity/matrix.csv` (it may still
require substantial time for large repositories). No partial export is labeled
as complete.

## Deliberate limits

- The cache accelerates **repeated** expensive comparisons; the first exhaustive
  duplicate detection or matrix run still costs O(n²) pair evaluations.
- The full matrix and clustering endpoints still materialize O(n²) values;
  matrix-window retrieval is the bounded browser path for large repositories.
- The catalog embedded in the initial report is unchanged; this sprint does not
  implement full lazy catalog serialization or graph rendering virtualization.
- No unvalidated shortlist replaces exhaustive duplicate metrics. Candidate
  screening may be considered later, but must be explicitly labeled partial.
- Real browser latency and throughput have not been benchmarked in a full Flask
  environment; the local validation suite uses optional Flask tests when
  available.

## Validation

Run `python -m pytest -q`. Verify source-edit invalidation (including same stat
metadata), config changes, cache hit parity, checksum/corruption recovery,
repo switching, symlink containment, complete CSV scope, and window completeness
metadata. `node --check code_analyzer/web/static/similarity.js` checks syntax.
