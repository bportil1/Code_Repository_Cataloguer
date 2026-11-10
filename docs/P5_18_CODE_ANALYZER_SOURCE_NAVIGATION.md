# P5-18 — Code Analyzer read-only source inspection boundary

`code_analyzer.source_evidence_navigation.inspect_verified_finding(locator, *, repository_root, active_project_id)`
accepts the `pah.source-evidence@1` locator produced by the pyPIQUE P5-18 adapter.
The **PAH caller** must authorize its selected repository and active project first.
Code Analyzer independently enforces matching project identity, project-relative
POSIX paths, resolved filesystem confinement, current SHA-256 equality, and
bounded UTF-8 excerpts (80 lines, 24 KiB, source file at most 8 MiB).

This is a **read-only** API with no editor integration, no AST/rescan inference,
no writes or commits, and no implicit current-repository hashing for historical
findings. Evidence without a scan-time SHA-256 remains unavailable. Callers
must not substitute current file fingerprints for absent scan provenance.

The response retains the PAH evidence schema (`schema`, `mode`, producer/finding/
project/source identities, lines, SHA-256, excerpt) for a future host bridge.
This adapter does not grant access rights; authorizations remain with the PAH
workspace and must be checked on every request, especially after project switch.
No source mutation, refactoring, or automatic remediation is implemented.

## Acceptance boundary

Automated tests cover exact-source reading, tampering, untrusted paths,
symlink escape, cross-project access, binary and malformed inputs. Live Flask
routing, pyPIQUE capture-time fingerprint enrichment, host project selection,
and browser navigation are **not** verified by this patch.
