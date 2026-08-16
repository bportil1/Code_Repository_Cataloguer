(() => {
  const catalog = window.CODEBASE_CATALOG;
  const svg = document.getElementById("repository-map-svg");
  const viewport = document.getElementById("repository-map-canvas-wrap");
  if (!catalog || !svg || !viewport) return;

  const SVG_NS = "http://www.w3.org/2000/svg";
  const nodes = new Map(Object.entries(catalog.nodes || {}));
  const relationships = catalog.relationships || [];
  const functionTypes = new Set(["function", "method"]);
  const mapState = {
    selectedId: catalog.root_node_id,
    viewMode: "symbol",
    lens: "structure",
    requestSerial: 0,
    zoom: 1,
    layout: null,
    currentGraph: null,
    positions: new Map(),
    nodeSizes: new Map(),
    nodeElements: new Map(),
    edgeElements: [],
    drag: null,
    pan: null,
  };
  const neighborCache = new Map();

  const outgoing = new Map();
  const incoming = new Map();
  for (const edge of relationships) {
    if (!outgoing.has(edge.source_id)) outgoing.set(edge.source_id, []);
    if (!incoming.has(edge.target_id)) incoming.set(edge.target_id, []);
    outgoing.get(edge.source_id).push(edge);
    incoming.get(edge.target_id).push(edge);
  }

  function el(name, attrs = {}) {
    const item = document.createElementNS(SVG_NS, name);
    Object.entries(attrs).forEach(([key, value]) => item.setAttribute(key, String(value)));
    return item;
  }

  function item(nodeId) {
    return nodes.get(nodeId);
  }

  function isFunction(nodeId) {
    return functionTypes.has(item(nodeId)?.node_type);
  }

  function label(nodeId) {
    const value = item(nodeId);
    if (!value) return nodeId;
    if (functionTypes.has(value.node_type)) return `${value.name}()`;
    return value.name || value.qualified_name || nodeId;
  }

  function qualifiedLabel(nodeId) {
    const value = item(nodeId);
    return value?.qualified_name || value?.path || label(nodeId);
  }

  function ancestors(nodeId) {
    const result = [];
    let current = item(nodeId);
    while (current?.parent_id) {
      current = item(current.parent_id);
      if (!current) break;
      result.push(current);
    }
    return result;
  }

  function ancestorOfType(nodeId, type) {
    return ancestors(nodeId).find(value => value.node_type === type) || null;
  }

  function descendants(nodeId, predicate = () => true, limit = Infinity) {
    const result = [];
    const stack = [...(item(nodeId)?.children || [])].reverse();
    const visited = new Set();
    while (stack.length && result.length < limit) {
      const currentId = stack.pop();
      if (visited.has(currentId)) continue;
      visited.add(currentId);
      const current = item(currentId);
      if (!current) continue;
      if (predicate(current)) result.push(current);
      [...(current.children || [])].reverse().forEach(child => stack.push(child));
    }
    return result;
  }

  function functionsInScope(nodeId, limit = 28) {
    const current = item(nodeId);
    if (!current) return [];
    if (functionTypes.has(current.node_type)) return [current];
    return descendants(nodeId, value => functionTypes.has(value.node_type), limit);
  }

  function modulesInScope(nodeId, limit = 24) {
    const current = item(nodeId);
    if (!current) return [];
    if (current.node_type === "module") return [current];
    return descendants(nodeId, value => value.node_type === "module", limit);
  }

  function containingModule(nodeId) {
    const current = item(nodeId);
    if (current?.node_type === "module") return current;
    if (current?.node_type === "file" && current.metadata?.module_id) {
      return item(current.metadata.module_id) || null;
    }
    return ancestorOfType(nodeId, "module");
  }

  function visibleRelation(edge) {
    return edge.relationship_type === "calls" || edge.relationship_type === "uses_import";
  }

  function uniqueEdges(edges) {
    const seen = new Set();
    return edges.filter(edge => {
      const key = `${edge.source_id}|${edge.target_id}|${edge.relationship_type}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function graph(nodesList, edges, focusId, layers = null, message = "") {
    const ids = [...new Set(nodesList.map(value => typeof value === "string" ? value : value.id))]
      .filter(nodeId => nodes.has(nodeId));
    return { ids, edges: uniqueEdges(edges), focusId, layers, message };
  }

  function structureGraph(focusId) {
    const focus = item(focusId);
    if (!focus) return graph([], [], focusId);

    if (focus.node_type === "project" || focus.node_type === "directory") {
      const modules = modulesInScope(focusId, 22);
      const edges = modules.map(module => ({
        source_id: focusId,
        target_id: module.id,
        relationship_type: "contains",
      }));
      return graph(
        [focusId, ...modules],
        edges,
        focusId,
        null,
        modules.length ? "High-level module map. Select a module to reveal its functions." : "No Python modules were found in this scope."
      );
    }

    let context = focus;
    if (focus.node_type === "file") context = containingModule(focusId) || focus;
    if (functionTypes.has(focus.node_type)) context = containingModule(focusId) || focus;

    const functions = functionsInScope(context.id, 26);
    if (functions.length) {
      const ids = [context.id, ...functions];
      const edges = functions.map(fn => ({
        source_id: context.id,
        target_id: fn.id,
        relationship_type: "contains",
      }));
      return graph(ids, edges, focusId, null, "Functions and methods contained by the selected module or class context.");
    }

    const children = (context.children || []).map(childId => item(childId)).filter(Boolean).slice(0, 24);
    return graph(
      [context.id, ...children],
      children.map(child => ({ source_id: context.id, target_id: child.id, relationship_type: "contains" })),
      focusId
    );
  }

  function callScopeGraph(focusId) {
    if (!isFunction(focusId)) {
      const functions = functionsInScope(focusId, 28);
      const ids = new Set(functions.map(value => value.id));
      const edges = relationships.filter(edge =>
        edge.relationship_type === "calls" && ids.has(edge.source_id) && ids.has(edge.target_id)
      );
      return graph([...ids], edges, focusId, null,
        functions.length ? "Calls among functions in the selected scope. Select a function for a focused neighborhood." : "No functions are available in this scope."
      );
    }
    return callNeighborhoodGraph(focusId, false);
  }

  function callNeighborhoodGraph(focusId, layered) {
    const depth = Number(document.getElementById("repository-map-depth")?.value || 1);
    const includeIncoming = document.getElementById("repository-map-incoming")?.checked !== false;
    const includeOutgoing = document.getElementById("repository-map-outgoing")?.checked !== false;
    const visited = new Set([focusId]);
    const queue = [{ id: focusId, distance: 0, layer: 0 }];
    const layers = new Map([[focusId, 0]]);

    while (queue.length) {
      const current = queue.shift();
      if (current.distance >= depth) continue;
      const candidates = [];
      // In Call Path mode keep callers above the focus and callees below it.
      // Once a branch has chosen a direction, continue walking that direction
      // instead of mixing incoming and outgoing hops into the same layer.
      if (includeOutgoing && (!layered || current.layer >= 0)) {
        for (const edge of outgoing.get(current.id) || []) {
          if (edge.relationship_type === "calls" && isFunction(edge.target_id)) {
            candidates.push({ id: edge.target_id, signed: current.layer + 1 });
          }
        }
      }
      if (includeIncoming && (!layered || current.layer <= 0)) {
        for (const edge of incoming.get(current.id) || []) {
          if (edge.relationship_type === "calls" && isFunction(edge.source_id)) {
            candidates.push({ id: edge.source_id, signed: current.layer - 1 });
          }
        }
      }
      for (const candidate of candidates) {
        if (visited.has(candidate.id)) continue;
        visited.add(candidate.id);
        const nextDistance = current.distance + 1;
        layers.set(candidate.id, layered ? candidate.signed : nextDistance);
        queue.push({ id: candidate.id, distance: nextDistance, layer: candidate.signed });
      }
    }

    const edges = relationships.filter(edge =>
      edge.relationship_type === "calls" && visited.has(edge.source_id) && visited.has(edge.target_id)
    );
    return graph([...visited], edges, focusId, layered ? layers : null,
      layered ? "Static call neighborhood. Arrows show statically resolved call direction." : "Incoming and outgoing statically resolved function calls."
    );
  }

  function importGraph(focusId) {
    if (isFunction(focusId)) {
      const depth = Number(document.getElementById("repository-map-depth")?.value || 1);
      const seen = new Set([focusId]);
      const edges = [];
      const first = (outgoing.get(focusId) || []).filter(edge => edge.relationship_type === "uses_import");
      first.forEach(edge => {
        edges.push(edge);
        seen.add(edge.target_id);
      });

      if (depth >= 2) {
        for (const dependencyId of [...seen].filter(id => id !== focusId)) {
          for (const edge of incoming.get(dependencyId) || []) {
            if (edge.relationship_type !== "uses_import" || !isFunction(edge.source_id)) continue;
            edges.push(edge);
            seen.add(edge.source_id);
          }
        }
      }
      return graph([...seen], edges, focusId, null,
        first.length ? "Import-use edges connect functions to dependencies they actually reference." : "No function-level imported dependency usage was resolved for this symbol."
      );
    }

    const scopeFunctions = new Set(functionsInScope(focusId, 26).map(value => value.id));
    const edges = relationships.filter(edge =>
      edge.relationship_type === "uses_import" && scopeFunctions.has(edge.source_id)
    );
    const ids = new Set(scopeFunctions);
    edges.forEach(edge => ids.add(edge.target_id));

    if (!edges.length) {
      const moduleIds = new Set(modulesInScope(focusId, 20).map(value => value.id));
      const moduleEdges = relationships.filter(edge =>
        edge.relationship_type === "imports" && moduleIds.has(edge.source_id)
      );
      moduleEdges.forEach(edge => {
        ids.add(edge.source_id);
        ids.add(edge.target_id);
      });
      return graph([...ids], moduleEdges, focusId, null,
        "Module imports are shown because no function-level usage was resolved in this scope."
      );
    }
    return graph([...ids], edges, focusId, null,
      "Functions are connected to imported dependencies they reference. Shared targets reveal dependency concentration."
    );
  }

  function similarityConfig() {
    return {
      context_depth: Number(document.getElementById("repository-map-similarity-depth")?.value || 1),
      distance_decay: Number(document.getElementById("repository-map-decay")?.value || 0.5),
      external_import_weight: Number(document.getElementById("repository-map-import-weight")?.value || 0.2),
    };
  }

  async function similarityGraph(focusId, duplication = false) {
    if (!isFunction(focusId)) {
      return graph([], [], focusId, null, "Select a function or method to view semantic neighbors.");
    }
    const config = similarityConfig();
    const threshold = duplication
      ? Number(document.getElementById("repository-map-duplicate-threshold")?.value || 0.65)
      : 0;
    const cacheKey = JSON.stringify([focusId, duplication, threshold, config]);
    let payload = neighborCache.get(cacheKey);
    if (!payload) {
      const response = await fetch("/api/similarity/neighbors", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          function_id: focusId,
          limit: duplication ? 12 : 8,
          threshold,
          ...config,
        }),
      });
      payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Similarity neighbor analysis failed.");
      neighborCache.set(cacheKey, payload);
    }
    const ids = [focusId, ...payload.neighbors.map(value => value.id)];
    const type = duplication ? "duplication" : "similarity";
    const edges = payload.neighbors.map(value => ({
      source_id: focusId,
      target_id: value.id,
      relationship_type: type,
      score: value.score,
    }));
    return graph(ids, edges, focusId, null,
      duplication
        ? `Functions with similarity at or above ${threshold.toFixed(2)} are shown as potential duplicate candidates.`
        : "Nearest semantic neighbors under the current similarity configuration."
    );
  }

  function wrapText(value, max = 22) {
    if (value.length <= max) return [value];
    const words = value.replace(/([._/])/g, "$1 ").split(/\s+/).filter(Boolean);
    const lines = [""];
    for (const word of words) {
      const current = lines[lines.length - 1];
      if (!current || `${current} ${word}`.trim().length <= max) {
        lines[lines.length - 1] = `${current} ${word}`.trim();
      } else if (lines.length < 2) {
        lines.push(word);
      } else {
        lines[1] = `${lines[1].slice(0, Math.max(0, max - 1))}…`;
        break;
      }
    }
    return lines;
  }

  function nodeSize(nodeId) {
    const value = item(nodeId);
    if (value?.node_type === "project") return { width: 220, height: 72 };
    if (value?.node_type === "module") return { width: 210, height: 70 };
    if (value?.node_type === "external") return { width: 170, height: 66 };
    return { width: 190, height: 66 };
  }

  function radialLayout(graphData) {
    const positions = new Map();
    const focusId = graphData.ids.includes(graphData.focusId) ? graphData.focusId : graphData.ids[0];
    if (!focusId) return { positions, width: 1200, height: 800 };

    const others = graphData.ids.filter(id => id !== focusId);
    const rings = [];
    const minimumArcSpacing = 255;
    const firstRadius = 320;
    const ringSpacing = 245;
    let cursor = 0;
    let ringIndex = 0;

    while (cursor < others.length) {
      const radius = firstRadius + ringIndex * ringSpacing;
      const capacity = Math.max(6, Math.floor((2 * Math.PI * radius) / minimumArcSpacing));
      const count = Math.min(capacity, others.length - cursor);
      rings.push({ radius, values: others.slice(cursor, cursor + count), ringIndex });
      cursor += count;
      ringIndex += 1;
    }

    const maxRadius = rings.length ? rings[rings.length - 1].radius : 0;
    const width = Math.max(1200, Math.ceil((maxRadius + 300) * 2));
    const height = Math.max(820, Math.ceil((maxRadius + 260) * 2));
    const center = { x: width / 2, y: height / 2 };
    positions.set(focusId, center);

    rings.forEach(({ radius, values, ringIndex: currentRing }) => {
      const offset = currentRing % 2 ? Math.PI / Math.max(1, values.length) : 0;
      values.forEach((id, index) => {
        const angle = -Math.PI / 2 + offset + (2 * Math.PI * index) / Math.max(1, values.length);
        positions.set(id, {
          x: center.x + Math.cos(angle) * radius,
          y: center.y + Math.sin(angle) * radius,
        });
      });
    });

    return { positions, width, height };
  }

  function layeredLayout(graphData) {
    if (!graphData.layers) return radialLayout(graphData);
    const positions = new Map();
    const groups = new Map();
    graphData.ids.forEach(id => {
      const layer = graphData.layers.get(id) ?? 0;
      if (!groups.has(layer)) groups.set(layer, []);
      groups.get(layer).push(id);
    });

    const keys = [...groups.keys()].sort((a, b) => a - b);
    const horizontalSpacing = 270;
    const verticalSpacing = 185;
    const paddingX = 240;
    const paddingY = 150;
    const maxRow = Math.max(1, ...keys.map(key => groups.get(key).length));
    const width = Math.max(1200, paddingX * 2 + Math.max(0, maxRow - 1) * horizontalSpacing + 220);
    const height = Math.max(820, paddingY * 2 + Math.max(0, keys.length - 1) * verticalSpacing + 90);

    keys.forEach((layer, rowIndex) => {
      const values = groups.get(layer).sort((a, b) => label(a).localeCompare(label(b)));
      const rowWidth = Math.max(0, values.length - 1) * horizontalSpacing;
      const startX = width / 2 - rowWidth / 2;
      const y = paddingY + rowIndex * verticalSpacing;
      values.forEach((id, index) => {
        positions.set(id, { x: startX + index * horizontalSpacing, y });
      });
    });

    return { positions, width, height };
  }

  function edgeClass(type) {
    if (type === "uses_import" || type === "imports") return "imports";
    if (type === "similarity") return "similarity";
    if (type === "duplication") return "duplication";
    if (type === "contains") return "contains";
    return "calls";
  }

  function svgPoint(event) {
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const matrix = svg.getScreenCTM();
    return matrix ? point.matrixTransform(matrix.inverse()) : { x: 0, y: 0 };
  }

  function clampPosition(nodeId, position) {
    const size = mapState.nodeSizes.get(nodeId) || nodeSize(nodeId);
    const padding = 35;
    return {
      x: Math.max(size.width / 2 + padding, Math.min(mapState.layout.width - size.width / 2 - padding, position.x)),
      y: Math.max(size.height / 2 + padding, Math.min(mapState.layout.height - size.height / 2 - padding, position.y)),
    };
  }

  function clippedEdge(sourceId, targetId) {
    const source = mapState.positions.get(sourceId);
    const target = mapState.positions.get(targetId);
    if (!source || !target) return null;
    const sourceSize = mapState.nodeSizes.get(sourceId) || nodeSize(sourceId);
    const targetSize = mapState.nodeSizes.get(targetId) || nodeSize(targetId);
    const dx = target.x - source.x;
    const dy = target.y - source.y;
    if (!dx && !dy) return { x1: source.x, y1: source.y, x2: target.x, y2: target.y };

    function boundaryFactor(size) {
      const xFactor = dx ? (size.width / 2) / Math.abs(dx) : Infinity;
      const yFactor = dy ? (size.height / 2) / Math.abs(dy) : Infinity;
      return Math.min(xFactor, yFactor);
    }

    const sourceFactor = boundaryFactor(sourceSize);
    const targetFactor = boundaryFactor(targetSize);
    return {
      x1: source.x + dx * sourceFactor,
      y1: source.y + dy * sourceFactor,
      x2: target.x - dx * targetFactor,
      y2: target.y - dy * targetFactor,
    };
  }

  function updateGeometry() {
    for (const [nodeId, group] of mapState.nodeElements.entries()) {
      const position = mapState.positions.get(nodeId);
      const size = mapState.nodeSizes.get(nodeId);
      if (!position || !size) continue;
      group.setAttribute("transform", `translate(${position.x - size.width / 2} ${position.y - size.height / 2})`);
    }

    for (const entry of mapState.edgeElements) {
      const geometry = clippedEdge(entry.edge.source_id, entry.edge.target_id);
      if (!geometry) continue;
      entry.line.setAttribute("x1", geometry.x1);
      entry.line.setAttribute("y1", geometry.y1);
      entry.line.setAttribute("x2", geometry.x2);
      entry.line.setAttribute("y2", geometry.y2);
      if (entry.label) {
        entry.label.setAttribute("x", (geometry.x1 + geometry.x2) / 2);
        entry.label.setAttribute("y", (geometry.y1 + geometry.y2) / 2 - 8);
      }
    }
  }

  function applyCanvasSize() {
    if (!mapState.layout) return;
    const width = Math.max(1, Math.round(mapState.layout.width * mapState.zoom));
    const height = Math.max(1, Math.round(mapState.layout.height * mapState.zoom));
    svg.setAttribute("viewBox", `0 0 ${mapState.layout.width} ${mapState.layout.height}`);
    svg.setAttribute("width", width);
    svg.setAttribute("height", height);
    svg.style.width = `${width}px`;
    svg.style.height = `${height}px`;
    document.getElementById("repository-map-zoom-label").textContent = `${Math.round(mapState.zoom * 100)}%`;
  }

  function setZoom(nextZoom, preserveCenter = true) {
    if (!mapState.layout) return;
    const oldZoom = mapState.zoom;
    const worldCenterX = (viewport.scrollLeft + viewport.clientWidth / 2) / oldZoom;
    const worldCenterY = (viewport.scrollTop + viewport.clientHeight / 2) / oldZoom;
    mapState.zoom = Math.max(0.35, Math.min(1.8, nextZoom));
    applyCanvasSize();
    if (preserveCenter) {
      viewport.scrollLeft = worldCenterX * mapState.zoom - viewport.clientWidth / 2;
      viewport.scrollTop = worldCenterY * mapState.zoom - viewport.clientHeight / 2;
    }
  }

  function centerOnNode(nodeId, behavior = "auto") {
    const position = mapState.positions.get(nodeId);
    if (!position) return;
    viewport.scrollTo({
      left: Math.max(0, position.x * mapState.zoom - viewport.clientWidth / 2),
      top: Math.max(0, position.y * mapState.zoom - viewport.clientHeight / 2),
      behavior,
    });
  }

  function fitMap() {
    if (!mapState.layout) return;
    const xZoom = Math.max(0.01, (viewport.clientWidth - 24) / mapState.layout.width);
    const yZoom = Math.max(0.01, (viewport.clientHeight - 24) / mapState.layout.height);
    setZoom(Math.max(0.35, Math.min(1, xZoom, yZoom)), false);
    viewport.scrollLeft = Math.max(0, (mapState.layout.width * mapState.zoom - viewport.clientWidth) / 2);
    viewport.scrollTop = Math.max(0, (mapState.layout.height * mapState.zoom - viewport.clientHeight) / 2);
  }

  function clearHighlight() {
    mapState.nodeElements.forEach(group => group.classList.remove("dimmed"));
    mapState.edgeElements.forEach(({ line, label }) => {
      line.classList.remove("dimmed", "highlighted");
      label?.classList.remove("dimmed");
    });
  }

  function highlightNeighborhood(nodeId) {
    const connected = new Set([nodeId]);
    mapState.edgeElements.forEach(({ edge }) => {
      if (edge.source_id === nodeId) connected.add(edge.target_id);
      if (edge.target_id === nodeId) connected.add(edge.source_id);
    });
    mapState.nodeElements.forEach((group, id) => group.classList.toggle("dimmed", !connected.has(id)));
    mapState.edgeElements.forEach(({ edge, line, label }) => {
      const active = edge.source_id === nodeId || edge.target_id === nodeId;
      line.classList.toggle("highlighted", active);
      line.classList.toggle("dimmed", !active);
      label?.classList.toggle("dimmed", !active);
    });
  }

  function openNode(nodeId) {
    mapState.selectedId = nodeId;
    if (window.CodebaseCatalogUI?.openNode) {
      window.CodebaseCatalogUI.openNode(nodeId);
    } else {
      renderMap();
    }
  }

  function renderSvg(graphData) {
    svg.replaceChildren();
    mapState.currentGraph = graphData;
    mapState.nodeElements = new Map();
    mapState.nodeSizes = new Map();
    mapState.edgeElements = [];
    mapState.drag = null;
    clearHighlight();

    const empty = document.getElementById("repository-map-empty");
    const status = document.getElementById("repository-map-status");
    const context = document.getElementById("repository-map-context");
    const selected = item(mapState.selectedId);
    context.textContent = selected
      ? `${qualifiedLabel(selected.id)} · ${mapState.viewMode === "call-path" ? "call path" : mapState.lens}`
      : "Repository map";

    if (!graphData.ids.length) {
      empty.hidden = false;
      empty.textContent = graphData.message || "No nodes are available for this view.";
      status.textContent = graphData.message || "No nodes are available for this view.";
      mapState.layout = { width: 1200, height: 820 };
      mapState.positions = new Map();
      applyCanvasSize();
      return;
    }
    empty.hidden = true;

    const layout = mapState.viewMode === "call-path"
      ? layeredLayout(graphData)
      : radialLayout(graphData);
    const visualFocusId = graphData.ids.includes(graphData.focusId) ? graphData.focusId : graphData.ids[0];
    mapState.layout = layout;
    mapState.positions = layout.positions;
    graphData.ids.forEach(nodeId => mapState.nodeSizes.set(nodeId, nodeSize(nodeId)));
    applyCanvasSize();

    status.textContent = graphData.message
      ? `${graphData.message} · ${graphData.ids.length} nodes · ${graphData.edges.length} relationships`
      : `${graphData.ids.length} nodes · ${graphData.edges.length} relationships`;

    const defs = el("defs");
    ["calls", "imports", "similarity", "duplication"].forEach(type => {
      const marker = el("marker", {
        id: `map-arrow-${type}`,
        viewBox: "0 0 10 10",
        refX: 9,
        refY: 5,
        markerWidth: 6,
        markerHeight: 6,
        orient: "auto-start-reverse",
      });
      marker.appendChild(el("path", { d: "M 0 0 L 10 5 L 0 10 z", class: `map-arrow map-arrow-${type}` }));
      defs.appendChild(marker);
    });
    svg.appendChild(defs);

    const edgeLayer = el("g", { class: "repository-map-edges" });
    for (const edge of graphData.edges) {
      if (!mapState.positions.has(edge.source_id) || !mapState.positions.has(edge.target_id)) continue;
      const type = edgeClass(edge.relationship_type);
      const line = el("line", {
        class: `repository-map-edge repository-map-edge-${type}`,
        "data-source-id": edge.source_id,
        "data-target-id": edge.target_id,
      });
      if (edge.relationship_type !== "contains") line.setAttribute("marker-end", `url(#map-arrow-${type})`);
      edgeLayer.appendChild(line);

      let scoreLabel = null;
      if (Number.isFinite(edge.score)) {
        scoreLabel = el("text", { class: `repository-map-edge-label ${type}` });
        scoreLabel.textContent = edge.score.toFixed(2);
        edgeLayer.appendChild(scoreLabel);
      }
      mapState.edgeElements.push({ edge, line, label: scoreLabel });
    }
    svg.appendChild(edgeLayer);

    const nodeLayer = el("g", { class: "repository-map-nodes" });
    for (const nodeId of graphData.ids) {
      const value = item(nodeId);
      const position = mapState.positions.get(nodeId);
      const size = mapState.nodeSizes.get(nodeId);
      if (!value || !position || !size) continue;
      const group = el("g", {
        class: `repository-map-node repository-map-node-${value.node_type}${nodeId === visualFocusId ? " focus" : ""}`,
        tabindex: 0,
        role: "button",
        "aria-label": `${label(nodeId)}, ${value.node_type}`,
        "data-map-node": nodeId,
      });
      group.appendChild(el("rect", { x: 0, y: 0, width: size.width, height: size.height, rx: 12, ry: 12 }));
      const text = el("text", { x: size.width / 2, y: 25, "text-anchor": "middle" });
      const lines = wrapText(label(nodeId));
      lines.forEach((line, index) => {
        const tspan = el("tspan", { x: size.width / 2, dy: index === 0 ? 0 : 17 });
        tspan.textContent = line;
        text.appendChild(tspan);
      });
      group.appendChild(text);
      const kind = el("text", { x: size.width / 2, y: size.height - 8, "text-anchor": "middle", class: "repository-map-node-kind" });
      kind.textContent = value.node_type;
      group.appendChild(kind);

      group.addEventListener("pointerenter", () => {
        if (!mapState.drag) highlightNeighborhood(nodeId);
      });
      group.addEventListener("pointerleave", () => {
        if (!mapState.drag) clearHighlight();
      });
      group.addEventListener("pointerdown", event => {
        if (event.button !== 0) return;
        event.stopPropagation();
        const pointer = svgPoint(event);
        const current = mapState.positions.get(nodeId);
        mapState.drag = {
          nodeId,
          pointerId: event.pointerId,
          offsetX: pointer.x - current.x,
          offsetY: pointer.y - current.y,
          startX: event.clientX,
          startY: event.clientY,
          moved: false,
        };
        group.classList.add("dragging");
        group.setPointerCapture(event.pointerId);
      });
      group.addEventListener("pointermove", event => {
        const drag = mapState.drag;
        if (!drag || drag.nodeId !== nodeId || drag.pointerId !== event.pointerId) return;
        const pointer = svgPoint(event);
        if (Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) > 4) drag.moved = true;
        mapState.positions.set(nodeId, clampPosition(nodeId, {
          x: pointer.x - drag.offsetX,
          y: pointer.y - drag.offsetY,
        }));
        updateGeometry();
      });
      const finishDrag = event => {
        const drag = mapState.drag;
        if (!drag || drag.nodeId !== nodeId || drag.pointerId !== event.pointerId) return;
        const moved = drag.moved;
        mapState.drag = null;
        group.classList.remove("dragging");
        try { group.releasePointerCapture(event.pointerId); } catch (_) { /* already released */ }
        clearHighlight();
        if (!moved) openNode(nodeId);
      };
      group.addEventListener("pointerup", finishDrag);
      group.addEventListener("pointercancel", event => {
        if (mapState.drag?.nodeId === nodeId) {
          mapState.drag = null;
          group.classList.remove("dragging");
          clearHighlight();
        }
      });
      group.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openNode(nodeId);
        }
      });
      mapState.nodeElements.set(nodeId, group);
      nodeLayer.appendChild(group);
    }
    svg.appendChild(nodeLayer);
    updateGeometry();

    requestAnimationFrame(() => centerOnNode(visualFocusId));
  }

  function updateControls() {
    const callPath = mapState.viewMode === "call-path";
    document.querySelectorAll("[data-map-view]").forEach(button => {
      button.classList.toggle("active", button.dataset.mapView === mapState.viewMode);
    });
    document.querySelectorAll("[data-map-lens]").forEach(button => {
      button.disabled = callPath && button.dataset.mapLens !== "calls";
      button.classList.toggle("active", (callPath ? "calls" : mapState.lens) === button.dataset.mapLens);
    });
    const effectiveLens = callPath ? "calls" : mapState.lens;
    const similarityControls = document.getElementById("repository-map-similarity-controls");
    similarityControls.hidden = !["similarity", "duplication"].includes(effectiveLens);
    document.getElementById("repository-map-duplicate-threshold-wrap").hidden = effectiveLens !== "duplication";
  }

  async function renderMap() {
    updateControls();
    const serial = ++mapState.requestSerial;
    const status = document.getElementById("repository-map-status");
    const effectiveLens = mapState.viewMode === "call-path" ? "calls" : mapState.lens;
    try {
      let graphData;
      if (mapState.viewMode === "call-path") {
        if (!isFunction(mapState.selectedId)) {
          graphData = graph([], [], mapState.selectedId, null, "Select a function or method to enter Call Path view.");
        } else {
          graphData = callNeighborhoodGraph(mapState.selectedId, true);
        }
      } else if (effectiveLens === "structure") {
        graphData = structureGraph(mapState.selectedId);
      } else if (effectiveLens === "calls") {
        graphData = callScopeGraph(mapState.selectedId);
      } else if (effectiveLens === "imports") {
        graphData = importGraph(mapState.selectedId);
      } else if (effectiveLens === "similarity" || effectiveLens === "duplication") {
        status.textContent = effectiveLens === "similarity" ? "Finding semantic neighbors…" : "Finding duplicate candidates…";
        graphData = await similarityGraph(mapState.selectedId, effectiveLens === "duplication");
      }
      if (serial !== mapState.requestSerial) return;
      renderSvg(graphData || graph([], [], mapState.selectedId));
    } catch (error) {
      if (serial !== mapState.requestSerial) return;
      renderSvg(graph([], [], mapState.selectedId, null, error.message));
    }
  }

  document.querySelectorAll("[data-map-view]").forEach(button => {
    button.addEventListener("click", () => {
      mapState.viewMode = button.dataset.mapView;
      if (mapState.viewMode === "call-path") mapState.lens = "calls";
      renderMap();
    });
  });
  document.querySelectorAll("[data-map-lens]").forEach(button => {
    button.addEventListener("click", () => {
      if (mapState.viewMode === "call-path") mapState.viewMode = "symbol";
      mapState.lens = button.dataset.mapLens;
      renderMap();
    });
  });

  [
    "repository-map-depth",
    "repository-map-incoming",
    "repository-map-outgoing",
    "repository-map-similarity-depth",
    "repository-map-decay",
    "repository-map-import-weight",
    "repository-map-duplicate-threshold",
  ].forEach(id => {
    const control = document.getElementById(id);
    control?.addEventListener("change", () => renderMap());
  });

  document.getElementById("repository-map-zoom-in")?.addEventListener("click", () => {
    setZoom(mapState.zoom + 0.10);
  });
  document.getElementById("repository-map-zoom-out")?.addEventListener("click", () => {
    setZoom(mapState.zoom - 0.10);
  });
  document.getElementById("repository-map-center")?.addEventListener("click", () => {
    centerOnNode(mapState.selectedId, "smooth");
  });
  document.getElementById("repository-map-fit")?.addEventListener("click", () => {
    fitMap();
  });
  document.getElementById("repository-map-reset-layout")?.addEventListener("click", () => {
    mapState.zoom = 1;
    renderMap();
  });

  viewport.addEventListener("pointerdown", event => {
    if (event.button !== 0 || event.target.closest?.(".repository-map-node")) return;
    mapState.pan = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      scrollLeft: viewport.scrollLeft,
      scrollTop: viewport.scrollTop,
    };
    viewport.classList.add("panning");
    viewport.setPointerCapture(event.pointerId);
    event.preventDefault();
  });
  viewport.addEventListener("pointermove", event => {
    const pan = mapState.pan;
    if (!pan || pan.pointerId !== event.pointerId) return;
    viewport.scrollLeft = pan.scrollLeft - (event.clientX - pan.startX);
    viewport.scrollTop = pan.scrollTop - (event.clientY - pan.startY);
  });
  const finishPan = event => {
    if (!mapState.pan || mapState.pan.pointerId !== event.pointerId) return;
    mapState.pan = null;
    viewport.classList.remove("panning");
    try { viewport.releasePointerCapture(event.pointerId); } catch (_) { /* already released */ }
  };
  viewport.addEventListener("pointerup", finishPan);
  viewport.addEventListener("pointercancel", finishPan);
  viewport.addEventListener("wheel", event => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    setZoom(mapState.zoom + (event.deltaY < 0 ? 0.10 : -0.10));
  }, { passive: false });

  window.addEventListener("catalog-node-selected", event => {
    const nodeId = event.detail?.nodeId;
    if (!nodeId || !nodes.has(nodeId)) return;
    mapState.selectedId = nodeId;
    renderMap();
  });

  renderMap();
})();
