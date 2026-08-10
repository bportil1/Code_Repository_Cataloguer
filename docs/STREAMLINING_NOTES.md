# Streamlining Notes

This pass reorganized the project around a reusable `code_analyzer` package without intentionally changing analysis behavior or the standalone browser UI.

## Preserved behavior

- repository catalog/tree generation
- definition and source views
- dependency views and hierarchy
- repository switching/reanalysis
- pairwise similarity
- global similarity matrix
- K-means/PCA clustering
- duplicate-candidate analysis and repository health metrics
- safe function move preview/apply/undo
- standalone HTML report generation
- existing Flask endpoint paths
- old top-level analysis import names through compatibility shims
- old `catalog.*` import names through compatibility shims
- `python app.py ...` and `python codebase_catalog.py ...`

## New integration boundary

```python
from code_analyzer import CodeAnalyzer
```

The future Project Assistant should use this interface rather than Flask or analyzer internals.

## Intentionally not added

- terminal
- venv creation/selection
- general-purpose code editing
- debugging
- LSP/autocomplete/type checking
- Markdown/PDF/reference-manager integration

Those belong to the future unifying host.

## Verification performed

- original 11 tests still pass after namespacing
- 4 additional boundary/compatibility tests added; 15 total tests pass
- `pytest -q` and `python -m pytest -q` both work
- public API exercised on a temporary repository
- catalog, comparison, similarity-matrix, duplicate, clustering, move/apply/undo flows exercised
- core `import code_analyzer` confirmed not to import Flask
- original and streamlined core analysis outputs compared and found identical on the same repository fixture
- standalone generated HTML report compared byte-for-byte and found identical
- all original Flask endpoint paths retained
- standalone HTML/CSS/JavaScript assets retained byte-for-byte
- Python compilation check passes

A full Flask/browser click-through was not possible in the streamlining environment because Flask was not installed there. Install `requirements.txt` and run `python run.py <project>` for local UI verification.
