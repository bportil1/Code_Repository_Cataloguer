# Code Repository Cataloguer

A local Python repository analysis tool. It can run as a standalone Flask application or be imported as a reusable analysis module through `code_analyzer.CodeAnalyzer`.

The streamlining pass preserves the existing repository explorer, source preview, dependency views, similarity tools, clustering, duplicate-candidate analysis, repository switching, and safe function-move workflow. It does **not** add a terminal, virtual-environment manager, general-purpose code editor, debugger, or IDE analysis; those belong to the future unifying Project Assistant host.

## Architecture

```text
Standalone Flask UI
        |
        v
   CodeAnalyzer        <-- public integration boundary
        |
  +-----+-----------------------------+
  |           |           |           |
Catalog    Similarity   Sessions    Refactor
  |           |
  |        +--+------------------+
  |        |        |       |    |
  |      Matrix  Clusters  Dupes Graph
  |
Python AST/indexing/dependency model
```

The reusable package does not import Flask. The standalone web UI is under `code_analyzer/web/` and delegates analysis work to the public façade.

## Public Python API

```python
from code_analyzer import CodeAnalyzer

analyzer = CodeAnalyzer("/path/to/python/project")

catalog = analyzer.catalog()
comparison = analyzer.compare("function:pkg.a", "function:pkg.b")
matrix = analyzer.similarity_matrix()
duplicates = analyzer.duplicate_candidates()
clusters = analyzer.clusters(k=4)
```

The future unified application should use this façade instead of importing analyzer internals or Flask routes.

## Install

Core analysis only:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-core.txt
```

Standalone Flask application:

```bash
pip install -r requirements.txt
```

## Run the standalone application

Canonical launcher:

```bash
python run.py /path/to/project
```

The previous launcher remains supported:

```bash
python app.py /path/to/project
```

Open `http://127.0.0.1:5000`.

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py C:\path\to\project
```

## Generate a standalone HTML catalog

The original report command remains available:

```bash
python codebase_catalog.py /path/to/project -o codebase_catalog_report.html
```

## Existing standalone functionality retained

### Repository exploration

- containment/directory tree
- Python modules, classes, functions, and methods
- definition search
- source preview
- multi-resolution dependency views
- internal and external dependency information
- dependency import-duplication hierarchy

### Pairwise similarity

The Similarity view compares two functions or methods using:

- namespaced bag-of-descriptor representations extracted from indexed source
- rooted incoming/outgoing call neighborhoods
- adjustable context depth
- geometric distance decay
- fixed internal-edge weight `1.0`
- adjustable external-import weight, default `0.20`
- per-depth and matched-node explanations

At each call-neighborhood depth the score compares the full Cartesian product of functions in the two layers. Distance decay is applied to the resulting per-depth score; no greedy or one-to-one matching is used.

### Global similarity matrix

The analyzer can compute the all-function similarity matrix using the same pairwise engine and selected analysis configuration.

### K-means clustering

The cluster view treats each row of the global similarity matrix as a function similarity profile, applies deterministic K-means, and uses a two-dimensional PCA projection for the interactive display. Cluster-level common factors are also reported.

### Duplicate-function candidates

Every unordered function/method pair can be compared using the same rooted-neighborhood configuration. Results can be filtered by threshold and ranked by similarity, with shared descriptor factors and evidence summaries.

Repository-level duplication-health metrics include:

- duplication burden
- function coverage
- duplicate pair rate
- mean nearest-neighbor similarity

The browser can retain a local baseline for before/after refactoring comparison.

### Dependency import-duplication hierarchy

The Dependencies view retains both:

- list view
- directory hierarchy

It distinguishes likely redundant imports within one module from shared-dependency hotspots across modules and supports internal/external filtering.

### Repository switching

The standalone application retains:

- `GET /api/repository/current`
- `POST /api/repository/open`
- `POST /api/repository/reload`

Repository switching rebuilds repository-scoped analysis state without restarting Flask.

### Safe top-level function moves

The existing object-level move workflow is retained for standalone compatibility:

- AST-derived source range
- preview before apply
- rejects methods/nested functions/same-file moves/duplicate target names
- validates changed files with `ast.parse`
- stale-plan protection using file hashes
- atomic writes
- backups under `.codebase_catalog/backups/`
- undo last move
- warnings for imports that may need manual updating

The future unified host is expected to provide normal code editing separately; this legacy refactor feature remains because streamlining must not remove existing functionality.

## Tests

```bash
pytest -q
```

The test suite covers the original similarity/duplication behavior plus the new public API and compatibility imports.

## Module boundary

See `MODULE.md` and `docs/ARCHITECTURE.md` before adding cross-cutting functionality.

## Repository Map MVP

The standalone web interface now includes a three-pane Repository Map intended for repository comprehension rather than only reporting analysis results:

- Repository tree: locate directories, modules, classes, functions, and methods.
- Repository Map: switch between Structure, Calls, Imports, Similarity, and Duplication lenses.
- Symbol Inspector: inspect source, metadata, calls/callers, and imported dependencies used by the selected symbol.
- Call Path view: follow statically resolved incoming and outgoing call neighborhoods by hop depth.
- Scrollable map workspace: layouts expand beyond the visible viewport instead of compressing nodes into a fixed SVG.
- Interactive navigation: drag nodes to rearrange them, drag empty canvas space to pan, use scrollbars to move through larger graphs, and zoom/fit/center the map with dedicated controls.
- Hover emphasis: hovering a node fades unrelated nodes/edges so its immediate relationships are easier to read.

The catalog also records `uses_import` relationships from functions/methods to imported modules or external packages when the imported binding is referenced inside that definition. This is separate from module-level `imports` relationships and is intended to answer which code symbols actually use a dependency.

Similarity and duplication map lenses use the same context-depth, distance-decay, and external-import-weight controls as the existing similarity analyses.
