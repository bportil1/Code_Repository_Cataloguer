(() => {
  const byId = id => document.getElementById(id);
  const root = byId("atlas-view");
  if (!root) return;
  const fileList = byId("atlas-file-list");
  const fileStatus = byId("atlas-files-status");
  const runStatus = byId("atlas-analysis-status");
  const overview = byId("atlas-overview");
  const nodeList = byId("atlas-node-list");
  const nodeDetail = byId("atlas-node-detail");
  const diagnostics = byId("atlas-diagnostics");
  const filter = byId("atlas-filter");
  const nodeFilter = byId("atlas-node-search");
  const analyze = byId("atlas-analyze");
  const prev = byId("atlas-prev");
  const next = byId("atlas-next");
  const pageLabel = byId("atlas-page-label");
  let selectedPath = null;
  let offset = 0;
  let generation = 0;
  let snapshot = null;
  const pageSize = 100;

  async function jsonRequest(url, options) {
    const res = await fetch(url, options);
    const result = await res.json().catch(() => ({error: `Non-JSON response (HTTP ${res.status})`}));
    if (!res.ok) throw new Error(result.error || `HTTP ${res.status}`);
    return result;
  }

  function showFiles(data) {
    fileList.replaceChildren();
    const entries = data.paths || [];
    for (const path of entries) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "atlas-file-entry";
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", String(path === selectedPath));
      button.textContent = path;
      button.addEventListener("click", () => {
        selectedPath = path;
        fileList.querySelectorAll(".atlas-file-entry").forEach(el =>
          el.setAttribute("aria-selected", String(el === button)));
        analyze.disabled = false;
        runStatus.textContent = `Selected: ${path}. Run structural analysis.`;
      });
      fileList.appendChild(button);
    }
    fileStatus.textContent = `${data.total} ATLAS files in ${data.repository}; showing ${entries.length}.`;
    pageLabel.textContent = data.total ? `${data.offset + 1}–${data.offset + entries.length} / ${data.total}` : "0 files";
    prev.disabled = data.offset <= 0;
    next.disabled = !data.has_more;
  }

  async function loadFiles(newOffset = 0) {
    const current = ++generation;
    offset = newOffset;
    selectedPath = null;
    snapshot = null;
    analyze.disabled = true;
    nodeList.replaceChildren();
    nodeDetail.replaceChildren();
    overview.replaceChildren();
    diagnostics.textContent = "No analysis yet.";
    fileStatus.textContent = "Finding ATLAS sources…";
    try {
      const params = new URLSearchParams({offset: String(offset), limit: String(pageSize), q: filter.value.trim()});
      const data = await jsonRequest(`/api/atlas/files?${params}`);
      if (current !== generation) return;
      showFiles(data);
    } catch (error) {
      if (current === generation) fileStatus.textContent = error.message;
    }
  }

  function addLine(parent, label, value) {
    const span = document.createElement("span");
    span.textContent = `${label}: ${value}`;
    parent.appendChild(span);
  }

  function showNodes() {
    const data = snapshot;
    nodeList.replaceChildren();
    if (!data) return;
    const term = nodeFilter.value.trim().toLowerCase();
    const entries = (data.items || []).filter(node =>
      !term || [node.name, node.kind, node.start_line, node.end_line].join(" ").toLowerCase().includes(term));
    const table = document.createElement("table");
    table.className = "atlas-node-table";
    const head = document.createElement("thead");
    const heading = document.createElement("tr");
    for (const col of ["Line(s)", "Kind", "Name", "Confidence"]) {
      const th = document.createElement("th");
      th.textContent = col;
      heading.appendChild(th);
    }
    head.appendChild(heading);
    table.appendChild(head);
    const body = document.createElement("tbody");
    for (const node of entries) {
      const row = document.createElement("tr");
      const linkCell = document.createElement("td");
      const link = document.createElement("button");
      link.type = "button";
      link.textContent = node.start_line === node.end_line ? String(node.start_line) : `${node.start_line}–${node.end_line}`;
      link.title = "Inspect structural candidate";
      link.addEventListener("click", () => {
        nodeDetail.replaceChildren();
        const detail = document.createElement("div");
        detail.className = "atlas-overview-list";
        addLine(detail, "File", data.relative_path);
        addLine(detail, "Lines", link.textContent);
        addLine(detail, "Kind", node.kind);
        addLine(detail, "Name", node.name);
        addLine(detail, "Candidate", node.id);
        addLine(detail, "Interpretation", node.confidence);
        nodeDetail.appendChild(detail);
      });
      linkCell.appendChild(link);
      row.appendChild(linkCell);
      for (const value of [node.kind, node.name, node.confidence]) {
        const cell = document.createElement("td");
        cell.textContent = String(value ?? "");
        row.appendChild(cell);
      }
      body.appendChild(row);
    }
    table.appendChild(body);
    nodeList.appendChild(table);
  }

  async function analyzeSelected() {
    if (!selectedPath) return;
    const requestedPath = selectedPath;
    const current = ++generation;
    analyze.disabled = true;
    runStatus.textContent = `Running CPS ATLAS parser on ${requestedPath}…`;
    try {
      const data = await jsonRequest("/api/atlas/analyze", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({path: requestedPath}),
      });
      if (current !== generation) return;
      snapshot = data.snapshot;
      if (snapshot.language !== "atlas" || snapshot.relative_path !== requestedPath) {
        throw new Error("Provider returned a mismatched source");
      }
      const summary = document.createElement("div");
      summary.className = "atlas-overview-list";
      addLine(summary, "Provider", snapshot.provider_id);
      addLine(summary, "Items", snapshot.items.length);
      addLine(summary, "Source SHA-256", snapshot.source_sha256.slice(0, 16) + "…");
      addLine(summary, "Grammar verified", "No");
      addLine(summary, "Hardware semantics verified", "No");
      overview.replaceChildren(summary);
      runStatus.textContent = `Parsed ${requestedPath}; ${snapshot.items.length} structural candidates, ${snapshot.diagnostics.length} diagnostics. Source bytes verified before/after parsing. No IEEE 716 semantic certification.`;
      diagnostics.replaceChildren();
      if (!snapshot.diagnostics.length) diagnostics.textContent = "No parser diagnostics for this file.";
      for (const message of snapshot.diagnostics) {
        const p = document.createElement("p");
        p.textContent = message;
        diagnostics.appendChild(p);
      }
      showNodes();
    } catch (error) {
      if (current === generation) runStatus.textContent = error.message;
    } finally {
      if (current === generation) analyze.disabled = !selectedPath;
    }
  }

  byId("atlas-refresh").addEventListener("click", () => loadFiles(0));
  filter.addEventListener("keydown", event => {if (event.key === "Enter") loadFiles(0);});
  prev.addEventListener("click", () => loadFiles(Math.max(0, offset - pageSize)));
  next.addEventListener("click", () => loadFiles(offset + pageSize));
  analyze.addEventListener("click", analyzeSelected);
  nodeFilter.addEventListener("input", showNodes);
  // Active repository changes force document reload via repository_session.js.
  // Page initialization must still explicitly load the source inventory.
  loadFiles(0);
})();
