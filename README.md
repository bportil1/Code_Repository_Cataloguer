# Codebase Catalog — Flask Refactor Edition

A local Python repository explorer and organizer. It retains the containment tree,
definition search, source preview, and multi-resolution dependency views, and adds
a Flask backend for safe object-level file changes.

The backend:

- uses the indexed function node and AST line range
- rejects methods, nested functions, same-file moves, and duplicate target names
- validates both changed files with `ast.parse`
- hashes files during preview and rejects stale plans
- writes files atomically
- creates backups under `.codebase_catalog/backups/`
- supports **Undo last move**
- warns when direct imports in other files still need updating

This first version intentionally does not rewrite caller files automatically.

## Install and run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 app.py /path/to/project
```

Open `http://127.0.0.1:5000`.

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py C:\path\to\project
```

## Included sample

```bash
python3 app.py tests/fixtures/sample_project
```

Select `normalize_name()` and move it to `sample_pkg/normalization.py`.

## Test

```bash
python3 tests/smoke_test.py
```

## Function similarity tab

The Flask interface now includes a **Similarity** tab next to Definitions. It compares two functions or methods using:

- namespaced bag-of-words descriptors extracted from indexed source;
- rooted incoming/outgoing call neighborhoods;
- adjustable context depth;
- geometric distance decay;
- fixed internal-edge weight `1.0`;
- adjustable external-import weight, default `0.20`;
- per-depth and matched-node explanations.

The comparison endpoint is `POST /api/similarity/compare`. Changing depth or weights recomputes similarity without rescanning the repository.

## Similarity scoring

At each call-neighborhood depth, the similarity tab compares the full Cartesian
product of functions in the two layers. If the left layer contains `m` functions
and the right layer contains `n` functions, the node score is the arithmetic mean
of all `m * n` descriptor similarities. Distance decay is then applied to the
resulting per-depth score. No greedy or one-to-one assignment is used.

## K-means cluster view

The Similarity tab now includes a **K-means Clusters** mode. It computes the global
function similarity matrix, treats each matrix row as a function's similarity
profile, clusters those profiles with deterministic K-means, and uses a two-
dimensional PCA projection for the interactive scatter plot.

Install the new numerical dependency with:

```bash
pip install -r requirements.txt
```

Clicking a plotted function or a cluster-member name opens a local pairwise
comparison against that cluster's representative function.
