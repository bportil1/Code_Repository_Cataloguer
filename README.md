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
