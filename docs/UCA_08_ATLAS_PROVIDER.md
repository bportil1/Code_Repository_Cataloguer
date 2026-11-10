# UCA-08 — ATLAS language provider

This patch bundles the original CPS Analysis Lab ATLAS engine under `code_analyzer.language_providers._atlas_engine`, and provides an **opt-in** `AtlasLanguageProvider`. The original standalone CPS repository remains unchanged. The Python catalog, Python similarity/refactor workflows, default language-provider registry, and PAH UI are unchanged.

```python
from code_analyzer.language_providers.atlas_registry import atlas_enabled_registry
result = atlas_enabled_registry().analyze("src/example.atl", repository_root)
```

The `LanguageAnalysis` result carries the `code-analyzer.language-analysis@1` contract and embeds the original `cps.atlas.analysis@1` artifact unchanged under `provider_artifact`. Node IDs, candidate recognitions, ordering, graph edges, raw spans, and diagnostics are preserved. The `adjacent_in_source` relationship is **not** an execution edge. End-exclusive decoded-text offsets are kept in the original artifact; normalized line ranges are navigation candidates only.

ATLAS grammar conformance, hardware meaning, cross-language references, program execution, and similarity are **not** verified. Provider `semantic` and `similarity` capabilities stay false. The UCA-07 path guard is not a race-safe file verification mechanism; for mutable/untrusted repositories use P5-18 source revision verification before trusting navigation.

To update the copied engine, compare to the original CPS Lab source and rerun its original parser/lexical/semantic test fixtures as well as UCA-08 adapter tests. No legacy removal is authorized.
