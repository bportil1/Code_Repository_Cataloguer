# Code Analyzer — independent PAH module instances (MI-01)

Code Analyzer owns its repository selection, source analysis, caches, source
revision verification, and refactor operations. PAH owns registered child
process identities, ports, logs, lifecycle and window routing. No Code Analyzer
engine/API/ATLAS logic is imported into PAH to implement multiple instances.

## Launch contract

The installed package exposes `pah.runtimes` entry point `code_analyzer`.
`CodeAnalyzerRuntimeAdapter.process_launch_spec(context=...)` supplies a trusted,
non-browser-controlled command for `python -m code_analyzer.process_ui`, the
initial repository, a request for an allocated port, and `/` as its UI path.
It makes no global changes and starts no child process itself.

The repository is selected from `context.resources['repository']` if available,
otherwise `context.project_root`. A missing/invalid selection is an error:
PAH's own working directory must never become an accidental repository.
The child requires `PAH_MODULE_INSTANCE_ID`, `PAH_MODULE_RUNTIME_DIR`,
`PAH_MODULE_PORT`, and `CODE_ANALYZER_INITIAL_REPOSITORY`; it binds only to
`127.0.0.1`, with no debug server or reloader.

The existing standalone `python run.py /path/to/repository` and
`code_analyzer.web.app.create_app()` remain unchanged, as does PAH's separately
hosted legacy Analysis surface. The obsolete `RuntimeRegistry.launch()`
module-type adapter method does not create unmanaged children; users launch
individual processes from the Instances dialog. `shutdown()` is a no-op for
this legacy adapter method: PAH targets modern children by instance ID.

## Persistence and concurrency boundary

Each process has an independent `CodeAnalyzer` and `RepositorySessionManager`.
Opening/reloading a repository in one instance does not alter a sibling's
process-local repository selection.

**Caution:** the module intentionally stores `.codebase_catalog/` source indexes,
similarity caches, and refactor operation history *inside the analyzed repository*.
Different repository roots keep those artifacts separate. Opening the SAME
writable repository in two instances is not a transactionally isolated editing
session: simultaneous source-index rebuilds, cache operations or source edits
may conflict. This patch does not change their algorithms or locking policy.
Use separate working trees when independently editing the same codebase.

`.gitignore` excludes host-root `/analysis/` and other generated trees and
SQLite journal files. The analyzed repository has its own `.gitignore`; Code
Analyzer does not change another project's Git configuration. Previously tracked
files must be reviewed and untracked separately if appropriate.

## Local acceptance checklist

1. Install this module locally in PAH's own environment with its `web` extra.
2. Launch a Code Analyzer instance for repository A using PAH Instances.
3. Switch the PAH workspace to repository B and launch a second instance.
4. Confirm two distinct localhost ports, process IDs and independent repository
   selections in `/api/repository/current`.
5. Open a different repository in one Code Analyzer window; verify the other
   window remains bound to its previously selected root.
6. Stop the first instance from PAH; confirm the second remains running.
7. Confirm no `/analysis/` or `/.pah/` generated output gets staged by Git.

Requires Flask and PAH's process supervisor for complete end-to-end validation.
