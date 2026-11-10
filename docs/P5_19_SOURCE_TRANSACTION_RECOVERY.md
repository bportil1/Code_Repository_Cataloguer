# P5-19 — Function-move partial-failure recovery (increment 2)

The existing function-move **apply** and **Undo** workflows now use one bounded
best-effort replacement coordinator. All involved source files are checked
against the previously established contents before each replacement. If a
source replacement or the final history publication fails, the coordinator
attempts to restore already-replaced files in reverse order.

Rollback is conditional: the coordinator restores a file only when its current
contents still equal the output it wrote. If another actor has changed the
file, it reports an incomplete rollback rather than overwriting that actor's
changes. Previously prepared backups remain on disk for manual recovery.
History is written with an atomic temporary-file replacement and is published
only after all source replacements succeed. Undo leaves the prior history
record intact unless all restorations and history publication succeed.

**Not a true atomic transaction:** multiple `os.replace` operations cannot be
committed together. Process termination, power loss, concurrent changes between
check and write, path/symlink replacement races, failure while rolling back,
and durability across directory fsync boundaries remain open. This patch does
not authorize unattended or remote source mutation. Further P5-19 work must
add descriptor-based path identity protection and crash recovery/reconciliation.

No new routes, source transformations, or scientific computation are added.
