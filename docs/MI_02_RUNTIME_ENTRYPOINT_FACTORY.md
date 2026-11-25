# MI-02 — Code Analyzer PAH runtime entry-point contract

`pah.runtimes` now resolves the no-argument `create_runtime_adapter` factory,
not the `CodeAnalyzerRuntimeAdapter` class. The factory returns a fresh bound
adapter each time, preserving class availability for direct internal consumers.
This eliminates the unbound `status(self)` failure on older PAH hosts and
complements PAH's own source-level discovery correction for third-party modules.

No repository analysis state, source-index file, AST/parser logic, UI process
configuration or subprocess ownership changes. The existing MI-01 process
entry point remains the supported module-owned launch specification.

Apply this patch only AFTER Code Analyzer MI-01, then reinstall the **local**
Code Analyzer source into the PAH virtualenv to update distribution entry-point
metadata. The install must be performed without fetching from a remote index.

Acceptance: `python -m pytest -q tests/test_pah_multi_instance.py`, followed by
inspection of `importlib.metadata`'s installed `pah.runtimes` entry point and
PAH orchestration status endpoints in the same virtual environment.
