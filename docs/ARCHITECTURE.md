# Architecture

## Package layout

```text
code_analyzer/
├── api.py                  Public host-facing façade
├── session.py              Active repository/session ownership
├── cli.py                  Static HTML report command
├── catalog/
│   ├── scanner.py          Filesystem discovery
│   ├── indexer.py          Python AST indexing
│   ├── models.py           Catalog data model
│   ├── catalog_builder.py  Repository graph/catalog assembly
│   ├── similarity_adapter.py
│   ├── report_builder.py
│   └── refactor/           Existing safe function-move implementation
├── similarity/
│   ├── engine.py           Rooted-neighborhood similarity
│   ├── matrix.py           Global pairwise matrix
│   ├── clustering.py       K-means/PCA cluster analysis
│   └── duplicates.py       Duplicate candidates and health metrics
└── web/
    ├── app.py              Thin Flask adapter
    ├── static/
    └── templates/
```

## Standalone versus embedded use

Standalone:

```text
Browser -> Flask routes -> CodeAnalyzer -> analysis packages
```

Embedded in the future Project Assistant:

```text
Project Assistant -> CodeAnalyzer -> analysis packages
```

The embedded path does not require Flask.

## Compatibility layer

Root-level launchers and thin top-level similarity modules are retained so existing commands and imports continue to work. New internal development should use the namespaced `code_analyzer` modules.

## UI preservation

The streamlining pass does not redesign the existing browser interface. The HTML templates, CSS, and JavaScript are intentionally preserved while Flask route implementations delegate through the public façade.
