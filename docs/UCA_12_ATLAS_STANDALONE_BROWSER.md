# Standalone Code Analyzer — ATLAS/CPS source view (UCA-12)

This is an **opt-in, read-only UI** connected to the preexisting CPS Analysis Lab engine snapshot installed under `code_analyzer/language_providers/_atlas_engine`. It does not replace the legacy Python AST index or merge ATLAS candidates into Python call graphs, similarity, or refactoring.

1. Install Code Analyzer with the UCA-07 language-provider, UCA-08 ATLAS adapter and UCA-09 navigation patches.
2. Start its existing local Flask UI, using a repository containing `.as`, `.atl`, or `.atlas` files.
3. Choose **ATLAS · CPS**, select an ATLAS file, then **Analyze selected**.
4. Browse source-linked structural items and parser diagnostics. Source SHA-256 is checked before/after parsing. Any candidate statement, symbol, operation or reference remains unverified semantic evidence. No IEEE 716 validation is claimed.
5. Use **Open repository** to change the active source repository; its ATLAS file inventory reloads with the app.

## APIs

- `GET /api/atlas/files?offset=0&limit=100&q=`: paginated repository-relative source discovery. Non-source dependency directories and symlinks are not traversed.
- `POST /api/atlas/analyze` JSON `{"path":"relative/file.atl"}`: returns the existing `code-analyzer.provider-navigation@1` source-linked snapshot, not source text. This calls the CPS-derived ATLAS parser, validates source identity before/after and preserves confidence.

**Scope:** The standalone Code Analyzer view exposes the CPS ATLAS parser. The PAH hosted UCA provider pane, connected via the UCA-09 host route, is a separate UI with its own project-scoped authorization. Neither workflow changes source files.
