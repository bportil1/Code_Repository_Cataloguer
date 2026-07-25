(() => {
  const catalog = window.CODEBASE_CATALOG;

  if (!catalog) {
    throw new Error("window.CODEBASE_CATALOG is not defined.");
  }

  const state = {
    query: "",
    selectedNodeId: catalog.root_node_id,
    dependencySearch: "",
    selectedRelationshipKey: null,
  };

  const nodes = new Map(Object.entries(catalog.nodes || {}));
  const relationships = catalog.relationships || [];

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function node(nodeId) {
    return nodes.get(nodeId);
  }

  function nodeLabel(item) {
    if (!item) return "Unknown";
    if (item.node_type === "function" || item.node_type === "method") {
      return `${item.name}()`;
    }
    return item.qualified_name || item.name;
  }

  function shortNodeLabel(item) {
    if (!item) return "Unknown";
    if (item.node_type === "function" || item.node_type === "method") {
      return `${item.name}()`;
    }
    return item.name;
  }

  function nodeIcon(item) {
    const icons = {
      project: "P",
      directory: "D",
      file: "•",
      module: "M",
      class: "C",
      method: "m",
      function: "F",
      external: "E",
    };
    return icons[item?.node_type] || "•";
  }

  function searchableText(item) {
    return [
      item.name,
      item.qualified_name,
      item.path,
      item.node_type,
      item.metadata?.signature,
      item.metadata?.docstring,
      ...(item.metadata?.imports || []).flatMap(value => [
        value.module,
        ...(value.names || []),
      ]),
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
  }

  function isDescendant(candidateId, ancestorId) {
    let current = node(candidateId);
    while (current?.parent_id) {
      if (current.parent_id === ancestorId) return true;
      current = node(current.parent_id);
    }
    return false;
  }

  function subtreeMatches(item) {
    if (!state.query) return true;
    if (searchableText(item).includes(state.query)) return true;
    return (item.children || []).some(childId => {
      const child = node(childId);
      return child ? subtreeMatches(child) : false;
    });
  }

  function selectTreeButton(button) {
    document
      .querySelectorAll(".tree-entry.selected")
      .forEach(item => item.classList.remove("selected"));
    if (button) button.classList.add("selected");
  }

  function renderTreeNode(nodeId, isRoot = false) {
    const item = node(nodeId);
    const li = document.createElement("li");
    li.className = `tree-node tree-node-${item.node_type}`;
    li.dataset.nodeId = item.id;

    const row = document.createElement("div");
    row.className = "tree-row";

    const hasChildren = (item.children || []).length > 0;
    let childList = null;

    if (hasChildren) {
      const toggle = document.createElement("button");
      toggle.className = "tree-toggle";
      toggle.type = "button";

      const expanded =
        isRoot ||
        item.node_type === "project" ||
        item.node_type === "directory";

      toggle.textContent = expanded ? "▾" : "▸";
      toggle.setAttribute("aria-expanded", String(expanded));

      toggle.addEventListener("click", event => {
        event.stopPropagation();
        const next = toggle.getAttribute("aria-expanded") !== "true";
        toggle.setAttribute("aria-expanded", String(next));
        toggle.textContent = next ? "▾" : "▸";
        childList.classList.toggle("collapsed", !next);
      });

      row.appendChild(toggle);
    } else {
      const spacer = document.createElement("span");
      spacer.className = "tree-toggle tree-toggle-spacer";
      row.appendChild(spacer);
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = "tree-entry";
    button.dataset.nodeId = item.id;

    const icon = document.createElement("span");
    icon.className = `tree-icon tree-icon-${item.node_type}`;
    icon.textContent = nodeIcon(item);

    const label = document.createElement("span");
    label.className = "tree-label";
    label.textContent = shortNodeLabel(item);

    button.append(icon, label);
    button.addEventListener("click", () => {
      state.selectedNodeId = item.id;
      selectTreeButton(button);
      showNodeDetails(item.id);
    });

    row.appendChild(button);
    li.appendChild(row);

    if (hasChildren) {
      childList = document.createElement("ul");
      childList.className = "tree-list tree-children";

      if (
        !isRoot &&
        item.node_type !== "project" &&
        item.node_type !== "directory"
      ) {
        childList.classList.add("collapsed");
      }

      for (const childId of item.children) {
        childList.appendChild(renderTreeNode(childId));
      }
      li.appendChild(childList);
    }

    return li;
  }

  function applyTreeFilter(nodeId, element) {
    const item = node(nodeId);
    const visible = subtreeMatches(item);
    element.classList.toggle("hidden", !visible);

    if (!visible) return;

    const children = item.children || [];
    const childElements = Array.from(
      element.querySelector(":scope > .tree-children")?.children || []
    );

    children.forEach((childId, index) => {
      if (childElements[index]) {
        applyTreeFilter(childId, childElements[index]);
      }
    });

    if (state.query && children.length) {
      const list = element.querySelector(":scope > .tree-children");
      const toggle = element.querySelector(
        ":scope > .tree-row > .tree-toggle"
      );
      if (list) list.classList.remove("collapsed");
      if (toggle?.tagName === "BUTTON") {
        toggle.textContent = "▾";
        toggle.setAttribute("aria-expanded", "true");
      }
    }
  }

  function relationshipDirectionFor(nodeId) {
    return {
      outgoing: relationships.filter(edge => edge.source_id === nodeId),
      incoming: relationships.filter(edge => edge.target_id === nodeId),
    };
  }

  function localDependencyHtml(nodeId) {
    const { outgoing, incoming } = relationshipDirectionFor(nodeId);

    const renderList = values =>
      values.length
        ? `<ul class="list">${values
            .map(edge => {
              const other =
                edge.source_id === nodeId
                  ? node(edge.target_id)
                  : node(edge.source_id);
              return `
                <li>
                  <button class="link-button" data-open-node="${escapeHtml(
                    other.id
                  )}">
                    ${escapeHtml(nodeLabel(other))}
                  </button>
                  <span class="badge">${escapeHtml(
                    edge.relationship_type
                  )}</span>
                </li>
              `;
            })
            .join("")}</ul>`
        : `<div class="empty-state compact">None recorded.</div>`;

    return `
      <div class="local-dependencies">
        <section>
          <h3>Uses / outgoing</h3>
          ${renderList(outgoing)}
        </section>
        <section>
          <h3>Used by / incoming</h3>
          ${renderList(incoming)}
        </section>
      </div>
    `;
  }

  function showNodeDetails(nodeId) {
    const item = node(nodeId);
    if (!item) return;

    const metadata = item.metadata || {};
    const source = metadata.source_code
      ? `
        <h3>Source</h3>
        <pre class="source-code"><code>${escapeHtml(
          metadata.source_code
        )}</code></pre>
      `
      : "";

    const importList = (metadata.imports || []).length
      ? `
        <h3>Imports</h3>
        <ul class="list">
          ${(metadata.imports || [])
            .map(value => {
              const prefix = ".".repeat(value.level || 0);
              const names = value.names?.length
                ? `: ${value.names.join(", ")}`
                : "";
              return `<li><code>${escapeHtml(
                `${prefix}${value.module || ""}${names}`
              )}</code> <small>line ${value.line}</small></li>`;
            })
            .join("")}
        </ul>
      `
      : "";

    const rows = [
      ["Type", item.node_type],
      ["Qualified name", item.qualified_name],
      ["Path", item.path],
      ["Signature", metadata.signature],
      [
        "Lines",
        metadata.line_start
          ? `${metadata.line_start}–${metadata.line_end}`
          : null,
      ],
      ["Line count", metadata.line_count],
      ["Bases", metadata.bases?.join(", ")],
      ["Decorators", metadata.decorators?.join(", ")],
      ["Docstring", metadata.docstring],
      ["Size", metadata.size_bytes ? `${metadata.size_bytes} bytes` : null],
      ["Parse error", metadata.parse_error],
    ].filter(([, value]) => value !== null && value !== undefined && value !== "");

    document.getElementById("details").innerHTML = `
      <h3>
        ${escapeHtml(nodeLabel(item))}
        <span class="badge">${escapeHtml(item.node_type)}</span>
      </h3>

      <dl class="metadata">
        ${rows
          .map(
            ([label, value]) => `
              <dt>${escapeHtml(label)}</dt>
              <dd>${escapeHtml(value)}</dd>
            `
          )
          .join("")}
      </dl>

      ${importList}
      ${localDependencyHtml(item.id)}
      ${source}
    `;

    bindOpenNodeLinks();
  }

  function bindOpenNodeLinks() {
    document.querySelectorAll("[data-open-node]").forEach(button => {
      button.addEventListener("click", () => {
        const targetId = button.dataset.openNode;
        state.selectedNodeId = targetId;
        showNodeDetails(targetId);
        setView("repository");

        const treeButton = document.querySelector(
          `.tree-entry[data-node-id="${CSS.escape(targetId)}"]`
        );
        selectTreeButton(treeButton);
        treeButton?.scrollIntoView({ block: "nearest" });
      });
    });
  }

  function ancestors(nodeId) {
    const values = [];
    let current = node(nodeId);
    while (current) {
      values.push(current);
      current = current.parent_id ? node(current.parent_id) : null;
    }
    return values;
  }

  function nearestAncestor(nodeId, types) {
    return ancestors(nodeId).find(value => types.includes(value.node_type));
  }

  function directoryOwner(nodeId) {
    const item = nearestAncestor(nodeId, ["directory"]);
    return item || node(catalog.root_node_id);
  }

  function moduleOwner(nodeId) {
    return nearestAncestor(nodeId, ["module"]);
  }

  function classOwner(nodeId) {
    return nearestAncestor(nodeId, ["class"]);
  }

  function functionOwner(nodeId) {
    return nearestAncestor(nodeId, ["function", "method"]);
  }

  function aggregateOwner(nodeId, level) {
    if (level === "directory") return directoryOwner(nodeId);
    if (level === "module") return moduleOwner(nodeId);
    if (level === "class") return classOwner(nodeId) || moduleOwner(nodeId);
    if (level === "function") {
      return functionOwner(nodeId) || classOwner(nodeId) || moduleOwner(nodeId);
    }
    return node(nodeId);
  }

  function edgeInScope(edge, scope) {
    if (scope === "project") return true;
    const selected = state.selectedNodeId;
    if (!selected) return true;

    if (scope === "selected-node") {
      return edge.source_id === selected || edge.target_id === selected;
    }

    return (
      edge.source_id === selected ||
      edge.target_id === selected ||
      isDescendant(edge.source_id, selected) ||
      isDescendant(edge.target_id, selected)
    );
  }

  function edgeMatchesDirection(edge, direction) {
    if (direction === "both" || !state.selectedNodeId) return true;
    if (direction === "outgoing") {
      return edge.source_id === state.selectedNodeId ||
        isDescendant(edge.source_id, state.selectedNodeId);
    }
    return edge.target_id === state.selectedNodeId ||
      isDescendant(edge.target_id, state.selectedNodeId);
  }

  function aggregateRelationships() {
    const scope = document.getElementById("dependency-scope").value;
    const level = document.getElementById("dependency-level").value;
    const direction = document.getElementById("dependency-direction").value;

    const filtered = relationships.filter(
      edge =>
        edgeInScope(edge, scope) &&
        edgeMatchesDirection(edge, direction)
    );

    const groups = new Map();

    for (const edge of filtered) {
      let source = node(edge.source_id);
      let target = node(edge.target_id);

      if (level !== "system") {
        source = aggregateOwner(edge.source_id, level);
        target =
          target?.node_type === "external"
            ? target
            : aggregateOwner(edge.target_id, level);
      } else {
        source = moduleOwner(edge.source_id) || source;
        target =
          target?.node_type === "external"
            ? target
            : moduleOwner(edge.target_id) || target;
      }

      if (!source || !target || source.id === target.id) continue;

      const key = `${source.id}|${target.id}|${edge.relationship_type}`;
      if (!groups.has(key)) {
        groups.set(key, {
          key,
          source,
          target,
          relationshipType: edge.relationship_type,
          edges: [],
        });
      }
      groups.get(key).edges.push(edge);
    }

    return [...groups.values()]
      .filter(group => {
        if (!state.dependencySearch) return true;
        return [
          nodeLabel(group.source),
          nodeLabel(group.target),
          group.relationshipType,
          ...group.edges.flatMap(edge => Object.values(edge.evidence || {})),
        ]
          .join(" ")
          .toLowerCase()
          .includes(state.dependencySearch);
      })
      .sort((a, b) => {
        const sourceCompare = nodeLabel(a.source).localeCompare(
          nodeLabel(b.source)
        );
        return sourceCompare || nodeLabel(a.target).localeCompare(nodeLabel(b.target));
      });
  }

  function renderDependencyDetails(group) {
    const target = document.getElementById("dependency-details");
    if (!group) {
      target.className = "empty-state";
      target.textContent =
        "Select a relationship to inspect its original local evidence.";
      return;
    }

    target.className = "";
    target.innerHTML = `
      <h3>
        ${escapeHtml(nodeLabel(group.source))}
        →
        ${escapeHtml(nodeLabel(group.target))}
      </h3>
      <p>
        <span class="badge">${escapeHtml(group.relationshipType)}</span>
        ${group.edges.length} local relationship${group.edges.length === 1 ? "" : "s"}
      </p>

      <ul class="evidence-list">
        ${group.edges
          .map(edge => {
            const source = node(edge.source_id);
            const targetNode = node(edge.target_id);
            const evidence = edge.evidence || {};
            const location = [
              evidence.file,
              evidence.line ? `line ${evidence.line}` : null,
              evidence.line_start ? `line ${evidence.line_start}` : null,
            ]
              .filter(Boolean)
              .join(", ");

            return `
              <li>
                <button class="link-button" data-open-node="${escapeHtml(
                  source.id
                )}">${escapeHtml(nodeLabel(source))}</button>
                →
                <button class="link-button" data-open-node="${escapeHtml(
                  targetNode.id
                )}">${escapeHtml(nodeLabel(targetNode))}</button>
                <br>
                <small>
                  ${escapeHtml(edge.relationship_type)}
                  ${location ? ` · ${escapeHtml(location)}` : ""}
                  ${
                    evidence.expression
                      ? ` · expression: ${escapeHtml(evidence.expression)}`
                      : ""
                  }
                  ${
                    evidence.import
                      ? ` · import: ${escapeHtml(evidence.import)}`
                      : ""
                  }
                </small>
              </li>
            `;
          })
          .join("")}
      </ul>
    `;
    bindOpenNodeLinks();
  }

  function renderDependencies() {
    const groups = aggregateRelationships();
    const level = document.getElementById("dependency-level").value;
    const scope = document.getElementById("dependency-scope").value;
    const direction = document.getElementById("dependency-direction").value;

    document.getElementById("dependency-title").textContent =
      `${level === "system" ? "System" : level[0].toUpperCase() + level.slice(1)} dependencies`;

    const selected = node(state.selectedNodeId);
    document.getElementById("dependency-context").textContent =
      `${scope.replaceAll("-", " ")} · ${direction}` +
      (scope !== "project" && selected
        ? ` · ${nodeLabel(selected)}`
        : "");

    document.getElementById("dependency-count").textContent =
      `${groups.length} relationship${groups.length === 1 ? "" : "s"}`;

    const bySource = new Map();
    for (const group of groups) {
      if (!bySource.has(group.source.id)) {
        bySource.set(group.source.id, {
          source: group.source,
          groups: [],
        });
      }
      bySource.get(group.source.id).groups.push(group);
    }

    const overview = document.getElementById("dependency-overview");

    if (!groups.length) {
      overview.innerHTML =
        `<div class="empty-state">No relationships match the current view.</div>`;
      renderDependencyDetails(null);
      return;
    }

    overview.innerHTML = [...bySource.values()]
      .map(
        sourceGroup => `
          <section class="dependency-group">
            <header>${escapeHtml(nodeLabel(sourceGroup.source))}</header>
            ${sourceGroup.groups
              .map(
                group => `
                  <button
                    type="button"
                    class="relationship-row"
                    data-relationship-key="${escapeHtml(group.key)}"
                  >
                    <span class="relationship-node">
                      ${escapeHtml(nodeLabel(group.source))}
                    </span>
                    <span class="relationship-arrow">→</span>
                    <span class="relationship-node">
                      ${escapeHtml(nodeLabel(group.target))}
                    </span>
                    <span class="relationship-count">
                      ${escapeHtml(group.relationshipType)} · ${group.edges.length}
                    </span>
                  </button>
                `
              )
              .join("")}
          </section>
        `
      )
      .join("");

    overview.querySelectorAll("[data-relationship-key]").forEach(button => {
      button.addEventListener("click", () => {
        overview
          .querySelectorAll(".relationship-row.selected")
          .forEach(row => row.classList.remove("selected"));
        button.classList.add("selected");

        const group = groups.find(
          value => value.key === button.dataset.relationshipKey
        );
        state.selectedRelationshipKey = group?.key || null;
        renderDependencyDetails(group);
      });
    });

    const selectedGroup = groups.find(
      group => group.key === state.selectedRelationshipKey
    );
    renderDependencyDetails(selectedGroup || null);
  }

  function renderDefinitions() {
    const body = document.getElementById("definitions-body");
    const definitionTypes = new Set(["class", "function", "method"]);

    const values = [...nodes.values()]
      .filter(item => definitionTypes.has(item.node_type))
      .filter(item => !state.query || searchableText(item).includes(state.query))
      .sort((a, b) =>
        (a.qualified_name || a.name).localeCompare(
          b.qualified_name || b.name
        )
      );

    body.innerHTML = values
      .map(
        item => `
          <tr data-definition-node="${escapeHtml(item.id)}">
            <td><code>${escapeHtml(item.name)}</code></td>
            <td>${escapeHtml(item.node_type)}</td>
            <td><code>${escapeHtml(item.path || "—")}</code></td>
            <td>${escapeHtml(node(item.parent_id)?.name || "—")}</td>
            <td>
              ${
                item.metadata?.line_start
                  ? `${item.metadata.line_start}–${item.metadata.line_end}`
                  : "—"
              }
            </td>
          </tr>
        `
      )
      .join("");

    body.querySelectorAll("[data-definition-node]").forEach(row => {
      row.addEventListener("click", () => {
        const targetId = row.dataset.definitionNode;
        state.selectedNodeId = targetId;
        showNodeDetails(targetId);
        setView("repository");

        const button = document.querySelector(
          `.tree-entry[data-node-id="${CSS.escape(targetId)}"]`
        );
        selectTreeButton(button);
      });
    });
  }

  function setView(name) {
    document.querySelectorAll(".tab").forEach(tab => {
      tab.classList.toggle("active", tab.dataset.view === name);
    });
    document.querySelectorAll(".view").forEach(view => {
      view.classList.toggle("active", view.id === `${name}-view`);
    });
    if (name === "dependencies") renderDependencies();
  }

  document.getElementById("project-name").textContent =
    `${catalog.project_name} Codebase Catalog`;
  document.getElementById("project-root").textContent = catalog.project_root;

  const summaryLabels = {
    directories: "Directories",
    files: "Files",
    python_files: "Python files",
    modules: "Modules",
    classes: "Classes",
    functions: "Functions",
    methods: "Methods",
    relationships: "Relationships",
  };

  document.getElementById("summary").innerHTML = Object.entries(summaryLabels)
    .map(
      ([key, label]) => `
        <div class="summary-card">
          <strong>${catalog.summary?.[key] ?? 0}</strong>
          <span>${label}</span>
        </div>
      `
    )
    .join("");

  const treeRoot = document.createElement("ul");
  treeRoot.className = "tree-list root";
  const renderedRoot = renderTreeNode(catalog.root_node_id, true);
  treeRoot.appendChild(renderedRoot);
  document.getElementById("tree").appendChild(treeRoot);

  document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => setView(tab.dataset.view));
  });

  document.getElementById("search").addEventListener("input", event => {
    state.query = event.target.value.trim().toLowerCase();
    applyTreeFilter(catalog.root_node_id, renderedRoot);
    renderDefinitions();
  });

  document.getElementById("dependency-search").addEventListener(
    "input",
    event => {
      state.dependencySearch = event.target.value.trim().toLowerCase();
      renderDependencies();
    }
  );

  [
    "dependency-scope",
    "dependency-level",
    "dependency-direction",
  ].forEach(id => {
    document.getElementById(id).addEventListener("change", () => {
      state.selectedRelationshipKey = null;
      renderDependencies();
    });
  });

  document.getElementById("collapse-tree").addEventListener("click", () => {
    document.querySelectorAll(".tree-children").forEach((list, index) => {
      list.classList.toggle("collapsed", index !== 0);
    });
    document.querySelectorAll(".tree-toggle").forEach((toggle, index) => {
      if (toggle.tagName === "BUTTON") {
        toggle.textContent = index === 0 ? "▾" : "▸";
        toggle.setAttribute("aria-expanded", String(index === 0));
      }
    });
  });

  renderDefinitions();
  showNodeDetails(catalog.root_node_id);
})();
