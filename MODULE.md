# Code Analyzer Module Contract

## Public interface

External consumers should start with:

```python
from code_analyzer import CodeAnalyzer
```

`code_analyzer/api.py` is the primary integration boundary.

Programmatic consumers can also request a reusable call-network artifact with `CodeAnalyzer.call_network(...)`. Passing `depth=None` traverses the selected function or method until no additional statically resolved call nodes are reachable; finite depths preserve bounded-hop analysis.

## Responsibilities

This module owns:

- Python repository scanning
- AST indexing
- repository/entity catalog construction
- source metadata used for analysis views
- dependency and call relationships
- descriptor extraction
- pairwise similarity
- global similarity matrices
- similarity clustering
- duplicate-candidate analysis and duplication-health metrics
- existing safe top-level function-move behavior
- the standalone analysis UI

## Does not own

The future unified host should own:

- general-purpose code editing
- terminal sessions
- Python virtual-environment creation/selection
- running arbitrary project commands
- Markdown/document editing
- PDF/BibTeX management
- cross-module workflows

## Dependency rule

The analyzer must not import the future document manager, reference manager, or unified host.

The intended direction is:

```text
Project Assistant Host
        |
        v
   CodeAnalyzer
        |
        v
 analyzer internals
```

Cross-module behavior belongs in the host's integration layer.

## Local-neighborhood development

Prefer feature-owned packages and narrow imports. Changes to similarity should normally remain under `code_analyzer/similarity/`; catalog/indexing changes should normally remain under `code_analyzer/catalog/`; standalone UI changes should remain under `code_analyzer/web/`.

Do not bypass `CodeAnalyzer` from an external project merely to save a few lines of adapter code.
