# P5-19 — Durable move/undo journal and conservative reconciliation

## Scope

Every function move or Undo now writes an exclusive fsynced JSON transaction journal under `.codebase_catalog/transactions/` **before** replacing source files. The entry records project-relative file paths, complete pre-write text, post-write SHA-256 fingerprints, and before/after history fingerprints. Journal removal is fsynced after publication or verified rollback. It adds no automatic modification at startup.

`FunctionMoveService.pending_transactions()` provides a read-only reconciliation report, including each file's `before`, `after`, or `conflict` status and history's corresponding status. Unrecognized, corrupted, or unsafe journals are reported for manual review and block new mutations. Source reads and replacements reuse the descriptor-safe P5-19 operations.

`FunctionMoveService.reconcile_transaction(transaction_id)` is an **explicit administrative recovery** method. If history was published and every file still matches the intended output, it finalizes the journal without rewriting sources. If history was not published, it restores only known post-write bytes back to their recorded pre-write text and verifies all files before retiring the journal. Other states fail closed, retaining the journal for manual recovery. Applications should surface reconciliation reports to their operator rather than automatically invoking recovery.

## Limits and security

This is a durability/reconciliation increment, **not** a filesystem-wide atomic transaction. It does not guarantee correct behavior under concurrent uncooperative writers during final replacement, hardware failures that lose previously fsynced data, mutation of internal `.codebase_catalog` files by another process, or attacks by privileged local users. The state directory must be writable only by trusted users. No restoration runs silently on service construction.

The journal includes original source text and should be protected like the project's source and backups. Manual cleanup must not remove a journal while a partial operation is unresolved. Reconciliation reports are observational and may become stale before explicit recovery; each source is reverified before a write.

## Acceptance

- Crash between first and second source replacement: journal survives and blocks new moves; explicit reconciliation restores the original files.
- Crash after history publication: explicit reconciliation marks a fully verified transaction committed without replacing files.
- Outside edit: conflicts are reported and never overwritten.
- Corrupted journal: blocked and retained for manual review.
- Normal move/Undo and injected ordinary exceptions continue to pass the existing regression tests.
