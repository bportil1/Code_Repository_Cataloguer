# P5-17 — Read-only shared call-network projection

The optional `code_analyzer.shared_call_graph_pilot.shared_call_network_graph(network, positions)`
projects the **existing** `CodeAnalyzer.call_network(...)` output to
`pah-shared.graph@1`. The caller must provide a display coordinate for every
node; the adapter does **not** infer positions, run a layout algorithm, rescan
source files, or invoke a PAH service. The module does not import PAH_Shared;
consumers may independently validate/render the returned payload with their
installed version of PAH_Shared.

Example (after producing a call-network snapshot):

```python
from code_analyzer.shared_call_graph_pilot import shared_call_network_graph

positions = {node["id"]: (float(i), 0.0) for i, node in enumerate(network["nodes"])}
view = shared_call_network_graph(network, positions)
```

The example supplies its own simple coordinates explicitly; production clients
should pass their existing layout. The original network remains authoritative
for node path/line provenance, call evidence, focus, traversal configuration,
`complete` flag and any editing/navigation authorization. Graph@1 cannot
represent those attributes: **never** use this display model to infer
completeness, provenance, or edit targets. Parallel call edges are retained
with distinct display identifiers. Direction is always source to target.

This pilot adds no routes, browser dependency, storage, similarity changes,
AST changes, or source editing behavior. Legacy repository maps and call-network
views remain unchanged. Future renderer adoption requires separate hosted and
standalone browser tests.
