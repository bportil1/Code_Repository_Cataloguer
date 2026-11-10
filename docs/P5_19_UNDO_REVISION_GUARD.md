# P5-19 — Source move undo revision guard (increment 1)

Only the existing function-move undo operation changes in this increment.
New move history includes SHA-256 fingerprints of the post-move source contents.
Undo verifies **every** file and its backup before writing any restored file.
Subsequent edits, missing backups, symlink paths, and legacy history without
fingerprints cause the undo to fail closed and leave history untouched.

The original preview and apply API and responses remain unchanged. Old moves
must be recovered manually from their backups rather than overwritten blindly.
This is not yet a full transactional multi-file mutation system: I/O failure
between individual atomic replacements, write-time filesystem races, and
history-write failure are separate P5-19 hardening gates. Likewise, existing
move application is still responsible for its own revision checks. Do not use
this change as a basis for exposing unattended edits to untrusted callers.
