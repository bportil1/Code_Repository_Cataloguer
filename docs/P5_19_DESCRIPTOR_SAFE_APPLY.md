# P5-19 — Descriptor-safe source move I/O

This incremental patch protects Code Analyzer's apply-time and Undo source reads
with project-root-relative directory descriptor traversal (`O_NOFOLLOW`). Sources
must be regular files <=16 MiB and retain identity and metadata during reads.
Writes use a temporary file created within a verified parent directory descriptor
and `os.replace` with relative directory descriptors. This rejects path-symlink
substitution and many concurrent replacement cases; it does **not** implement an
OS-level atomic compare-and-swap. An uncooperative writer can still race the
final metadata check and rename, and multi-file source replacements remain
best-effort compensating transactions rather than crash-atomic.

Existing Undo conflict checking and rollback remain in force. On systems without
POSIX `O_NOFOLLOW`, source operations fail closed. No schema, SAT, or AST semantics
change. Crash-safe journal/recovery and complete cross-process locking remain
future work.
