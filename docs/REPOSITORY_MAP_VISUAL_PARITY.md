# Code Analyzer repository map — visual and interaction parity

The **standalone Code Analyzer** source continues to own its symbol graph, relationship semantics, source-linked inspector, and drag/pan camera. This change does **not** replace them with pyPIQUE model semantics or a generic graph adapter. It aligns presentation and interaction affordances with the pyPIQUE model network while retaining all Code Analyzer-specific behavior.

## Presentation

- The map occupies the full width of the Repository Map section. The repository tree and original symbol inspector remain visible below the map.
- The 32-pixel visible graph-paper grid is removed. A quiet pale canvas, white outlined nodes, blue module nodes, purple class nodes, green function/method nodes, and amber external nodes provide a consistent light palette without changing graph data.
- **Fullscreen map** uses the Fullscreen API when available, with an in-page expanded fallback when embedded browser permissions forbid it. Escape exits the fallback. Fit, zoom, layout reset, node dragging, source selection, all five lenses, Call Path and the legend remain accessible.
- **New map window** loads the same local Code Analyzer UI in its own window, preserving the current focus, view mode, lens, depth, incoming/outgoing choices and similarity settings. It retains the tree, inspector, and export controls. It does not create or store a new network or alter PAH workspaces. Browser popup permission may be required.
- **Highlight neighbors** locks the original hover-neighborhood highlight onto the selected node; turning it off restores the previous hover-only behavior.
- The small **Selected symbol details** disclosure exposes source identity while the map is fullscreen, without replacing the original inspector.

## Exports and scientific boundaries

Original **JSON, GraphML, Graphviz DOT, and SVG** exports remain unchanged. **PNG** exports the currently rendered SVG to a local raster file (and reports an actionable failure if browser canvas export is unavailable). **CSV** exports the source/target/type/score values for the **currently displayed graph**, using quoted RFC-style fields. None of these exports implies the complete repository is displayed when a lens/depth restricts scope. JSON keeps the full existing per-edge evidence and metadata available within that view.

The existing **Structure, Calls, Imports, Similarity, Duplication, Symbol Map, Call Path**, selection/hover/drag behavior, reference information, and similarity parameters remain source-owned. Export and layout changes do not compute or change relationships.

## Acceptance on a running installation

Apply from `~/cluster/Code_Repository_Cataloguer` only. Reinstall through the normal local PAH lifecycle (never edit PAH's `modules/` directory). In Code Analyzer's Repository Map, verify canvas grid is absent, all lenses and node selection still work, fullscreen/Exit works, separate map window carries the selected node and lens, and exports JSON/GraphML/DOT/SVG/PNG/CSV download. Browser tests need a real hosted instance; source and package-level regression tests cannot substitute for that validation.
