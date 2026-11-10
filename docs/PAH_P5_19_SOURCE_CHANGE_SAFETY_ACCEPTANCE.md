# P5-19 — Source-change safety acceptance

Scope: **Code Analyzer** existing function-move preview, apply, Undo, conflict refusal, and explicit recovery. This check does not authorize new edits through PAH or modify scientific results. Tests operate only on isolated temporary repositories and use no network access.

## Offline acceptance

Run from the Code Analyzer repository with its local test dependencies installed:

```bash
python -m pytest -q tests/test_p519_undo_revision_guards.py tests/test_p519_transaction_recovery.py tests/test_p519_descriptor_source_races.py tests/test_p519_crash_journal.py tests/test_p519_source_change_acceptance.py
python -m pytest -q
```

The first command covers revision-checked Undo; fail-closed legacy backups; failure-injected apply/Undo; descriptor-safe path opening and races; journals; explicit reconciliation across service restarts; and external-edit conflicts. A passing assertion establishes only the particular simulated interleavings exercised by these tests.

## Preservation requirements

- The source tree remains authoritative. Only explicitly previewed function moves and Undo can alter it.
- Revision mismatches, path/symlink substitutions, incomplete history, corrupted journals, and unresolved transaction conflicts **must not** trigger speculative source recovery.
- An interrupted journal blocks further source changes until explicit reconciliation or manual recovery. Recovery must not overwrite an external edit.
- Existing AST analysis, similarity computation, standalone operation and source-evidence navigation remain separate from the move operation.
- Tests must never be run against a real repository as a source-editing fixture.

## Unverified and residual risks

- **No all-or-nothing guarantee across files:** write/rename and history publication occur in stages; journal recovery is deliberate and conservative.
- **Uncooperative concurrent writers:** descriptor-relative access narrows path-race risks but does not provide cross-process compare-and-swap semantics for directory entries.
- **Durability:** power loss, filesystem corruption, and storage-hardware failures are not exhaustively tested. Recovery can require manual intervention.
- **Authorization:** UI/server permission checks, hosted PAH integration, and browser workflows are not established by these unit tests.
- **Dependency/platform coverage:** tests exercise the installed local environment, not every operating system or filesystem.

Do not retire legacy editing paths or declare P5-19 production-complete solely on these offline results. Defer hosted and cross-module smoke testing to P5-20.
