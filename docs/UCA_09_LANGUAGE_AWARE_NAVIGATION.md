# UCA-09 — Language-aware source navigation (first increment)

`build_navigation_snapshot(relative_path, repository_root)` runs only when explicitly called. It uses the existing UCA-07/08 providers and returns `code-analyzer.provider-navigation@1` with source SHA-256, declared capabilities, structural nodes and diagnostics. The full CPS/Python provider artifacts remain with Code Analyzer. No new PAH HTTP endpoint or UI controller is installed in this increment.

Navigation nodes carry provider-specific kind and `confidence` without inventing common Python AST semantics. In particular ATLAS candidate relationships are not verified hardware/IEEE 716 semantics. No source editing, similarity processing, SAT invocation or model recomputation occurs.

The source is hashed before and after parsing using descriptor-relative, symlink-resistant bounded reads. This detects common changes but is not an immutable snapshot or a defense against every concurrent replacement. PAH must still verify a selected source revision at navigation time. Full hosted/browser tests remain pending.
