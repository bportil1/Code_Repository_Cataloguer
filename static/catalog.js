(() => {
  const catalog = window.CODEBASE_CATALOG;
  const state = { query: "" };
  const moduleByPath = new Map(catalog.modules.map(module => [module.path, module]));
  const definitions = [];

  for (const module of catalog.modules) {
    for (const fn of module.functions) definitions.push({ ...fn, file: module.path });
    for (const cls of module.classes) {
      definitions.push({
        name: cls.name, qualified_name: cls.qualified_name, kind: "class",
        parent: null, line_start: cls.line_start, line_end: cls.line_end,
        file: module.path, source: cls
      });
      for (const method of cls.methods) definitions.push({ ...method, file: module.path });
    }
  }

  document.getElementById("project-name").textContent = `${catalog.project_name} Codebase Catalog`;
  document.getElementById("project-root").textContent = catalog.project_root;

  const summaryLabels = {
    directories: "Directories", files: "Files", python_files: "Python files",
    classes: "Classes", functions: "Functions", methods: "Methods",
    internal_imports: "Internal imports", external_imports: "External packages"
  };
  document.getElementById("summary").innerHTML = Object.entries(summaryLabels)
    .map(([key, label]) => `<div class="summary-card"><strong>${catalog.summary[key]}</strong><span>${label}</span></div>`)
    .join("");

  function matches(...values) {
    if (!state.query) return true;
    const haystack = values.filter(Boolean).join(" ").toLowerCase();
    return haystack.includes(state.query);
  }

  function renderTreeEntry(entry, isRoot = false) {
    const li = document.createElement("li");
    const row = document.createElement("div");
    row.className = "tree-row";
    const isDirectory = entry.entry_type === "directory";

    if (isDirectory) {
      const toggle = document.createElement("button");
      toggle.className = "tree-toggle";
      toggle.textContent = "▾";
      toggle.setAttribute("aria-label", `Toggle ${entry.name}`);
      row.appendChild(toggle);

      const label = document.createElement("button");
      label.className = "tree-item";
      label.textContent = `📁 ${entry.name}`;
      label.addEventListener("click", () => showDirectory(entry));
      row.appendChild(label);
      li.appendChild(row);

      const children = document.createElement("ul");
      children.className = `tree-list tree-children${isRoot ? " root" : ""}`;
      for (const child of entry.children) children.appendChild(renderTreeEntry(child));
      li.appendChild(children);
      toggle.addEventListener("click", () => {
        children.classList.toggle("collapsed");
        toggle.textContent = children.classList.contains("collapsed") ? "▸" : "▾";
      });
    } else {
      const spacer = document.createElement("span");
      spacer.className = "tree-toggle";
      row.appendChild(spacer);
      const label = document.createElement("button");
      label.className = "tree-item";
      label.textContent = `${entry.name.endsWith(".py") ? "🐍" : "📄"} ${entry.name}`;
      label.dataset.search = `${entry.name} ${entry.path}`.toLowerCase();
      label.addEventListener("click", () => showFile(entry.path, label));
      row.appendChild(label);
      li.appendChild(row);
    }
    return li;
  }

  const treeRoot = document.createElement("ul");
  treeRoot.className = "tree-list root";
  treeRoot.appendChild(renderTreeEntry(catalog.tree, true));
  document.getElementById("tree").appendChild(treeRoot);

  function selectTreeItem(element) {
    document.querySelectorAll(".tree-item.selected").forEach(item => item.classList.remove("selected"));
    if (element) element.classList.add("selected");
  }

  function showDirectory(entry) {
    selectTreeItem(null);
    document.getElementById("details").innerHTML = `
      <h3>${entry.name} <span class="badge">directory</span></h3>
      <dl class="metadata"><dt>Path</dt><dd><code>${entry.path || "."}</code></dd><dt>Items</dt><dd>${entry.children.length}</dd></dl>`;
  }

  function showFile(path, selectedElement = null) {
    selectTreeItem(selectedElement);
    const module = moduleByPath.get(path);
    if (!module) {
      document.getElementById("details").innerHTML = `<h3>${path.split("/").pop()} <span class="badge">file</span></h3><dl class="metadata"><dt>Path</dt><dd><code>${path}</code></dd></dl>`;
      return;
    }
    const importItems = module.imports.map(item => {
      const names = item.names.length ? `: ${item.names.join(", ")}` : "";
      const prefix = ".".repeat(item.level);
      return `<li><code>${prefix}${item.module}${names}</code> <small>line ${item.line}</small></li>`;
    }).join("") || "<li>None</li>";
    const definitionItems = [
      ...module.classes.map(item => `<li><button class="link-button" data-definition="${item.qualified_name}">${item.name}</button> <span class="badge">class</span></li>`),
      ...module.functions.map(item => `<li><button class="link-button" data-definition="${item.qualified_name}">${item.name}</button> <span class="badge">function</span></li>`)
    ].join("") || "<li>None</li>";
    document.getElementById("details").innerHTML = `
      <h3>${module.module_name} <span class="badge">Python module</span></h3>
      <dl class="metadata"><dt>Path</dt><dd><code>${module.path}</code></dd><dt>Lines</dt><dd>${module.line_count}</dd><dt>Docstring</dt><dd>${module.docstring || "—"}</dd></dl>
      <h3>Definitions</h3><ul class="list">${definitionItems}</ul>
      <h3>Imports</h3><ul class="list">${importItems}</ul>`;
    bindDefinitionLinks();
  }

  function showDefinition(qualifiedName) {
    const item = definitions.find(entry => entry.qualified_name === qualifiedName);
    if (!item) return;
    const isClass = item.kind === "class";
    const source = item.source || item;
    const extras = isClass
      ? `<dt>Bases</dt><dd>${source.bases?.length ? source.bases.map(value => `<code>${value}</code>`).join(" ") : "—"}</dd>`
      : `<dt>Signature</dt><dd><code>${item.signature}</code></dd><dt>Parent</dt><dd>${item.parent || "—"}</dd>`;
    const mentions = !isClass && item.mentions?.length
      ? `<h3>Names mentioned</h3><p>${item.mentions.map(value => `<code>${value}</code>`).join(" ")}</p>` : "";
    document.getElementById("details").innerHTML = `
      <h3>${item.name} <span class="badge">${item.kind}</span></h3>
      <dl class="metadata"><dt>Qualified name</dt><dd><code>${item.qualified_name}</code></dd><dt>File</dt><dd><code>${item.file}</code></dd><dt>Lines</dt><dd>${item.line_start}–${item.line_end}</dd>${extras}<dt>Docstring</dt><dd>${source.docstring || "—"}</dd></dl>${mentions}`;
    setView("repository");
  }

  function bindDefinitionLinks() {
    document.querySelectorAll("[data-definition]").forEach(button => button.addEventListener("click", () => showDefinition(button.dataset.definition)));
  }

  function renderDefinitions() {
    const body = document.getElementById("definitions-body");
    body.innerHTML = "";
    for (const item of definitions.filter(item => matches(item.name, item.qualified_name, item.kind, item.file, item.parent))) {
      const row = document.createElement("tr");
      row.innerHTML = `<td><code>${item.name}</code></td><td>${item.kind}</td><td><code>${item.file}</code></td><td>${item.parent || "—"}</td><td>${item.line_start}–${item.line_end}</td>`;
      row.addEventListener("click", () => showDefinition(item.qualified_name));
      body.appendChild(row);
    }
  }

  function renderDependencies(targetId, dependencyMap) {
    const target = document.getElementById(targetId);
    const entries = Object.entries(dependencyMap).filter(([module, dependencies]) => matches(module, ...dependencies));
    target.innerHTML = entries.map(([module, dependencies]) => `
      <div class="dep-module"><strong><code>${module}</code></strong><div class="dep-targets">${dependencies.length ? dependencies.map(value => `<code>${value}</code>`).join(" → ") : "None"}</div></div>`).join("") || `<div class="empty-state">No matching entries.</div>`;
  }

  function setView(name) {
    document.querySelectorAll(".tab").forEach(tab => tab.classList.toggle("active", tab.dataset.view === name));
    document.querySelectorAll(".view").forEach(view => view.classList.toggle("active", view.id === `${name}-view`));
  }

  document.querySelectorAll(".tab").forEach(tab => tab.addEventListener("click", () => setView(tab.dataset.view)));
  document.getElementById("search").addEventListener("input", event => {
    state.query = event.target.value.trim().toLowerCase();
    document.querySelectorAll(".tree-item[data-search]").forEach(item => item.closest("li").classList.toggle("hidden", !matches(item.dataset.search)));
    renderDefinitions();
    renderDependencies("internal-dependencies", catalog.internal_dependencies);
    renderDependencies("external-dependencies", catalog.external_dependencies);
  });

  renderDefinitions();
  renderDependencies("internal-dependencies", catalog.internal_dependencies);
  renderDependencies("external-dependencies", catalog.external_dependencies);
  showDirectory(catalog.tree);
})();
