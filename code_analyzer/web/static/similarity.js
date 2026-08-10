(() => {
  const catalog = window.CODEBASE_CATALOG;
  if (!catalog) return;

  const nodes = new Map(Object.entries(catalog.nodes || {}));
  const functionNodes = [...nodes.values()]
    .filter(item => item.node_type === "function" || item.node_type === "method")
    .sort((a, b) => (a.qualified_name || a.name).localeCompare(b.qualified_name || b.name));

  const label = item => `${item.qualified_name || item.name}${item.node_type === "method" ? " [method]" : ""}`;
  const escapeHtml = value => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const similaritySettingInputs = [...document.querySelectorAll("[data-similarity-setting]")];

  function synchronizeSimilaritySetting(source) {
    const setting = source.dataset.similaritySetting;
    if (!setting) return;
    similaritySettingInputs.forEach(input => {
      if (input !== source && input.dataset.similaritySetting === setting) {
        input.value = source.value;
      }
    });
  }

  similaritySettingInputs.forEach(input => {
    input.addEventListener("input", () => synchronizeSimilaritySetting(input));
    input.addEventListener("change", () => synchronizeSimilaritySetting(input));
  });

  function similarityConfigFor(panelId) {
    const panel = document.getElementById(panelId);
    const read = (setting, fallbackId) => {
      const input = panel?.querySelector(`[data-similarity-setting="${setting}"]`)
        || document.getElementById(fallbackId);
      return Number(input?.value);
    };
    return {
      context_depth: read("context_depth", "similarity-depth"),
      distance_decay: read("distance_decay", "similarity-decay"),
      external_import_weight: read("external_import_weight", "similarity-import-weight"),
    };
  }

  function populateSelect(select, selectedIndex) {
    select.innerHTML = functionNodes
      .map((item, index) => `<option value="${escapeHtml(item.id)}"${index === selectedIndex ? " selected" : ""}>${escapeHtml(label(item))}</option>`)
      .join("");
  }

  function sourceLocation(item) {
    if (!item) return "Source unavailable";
    const start = item.metadata?.line_start;
    const end = item.metadata?.line_end;
    const path = item.path || item.metadata?.path || "Unknown file";
    if (Number.isFinite(start) && Number.isFinite(end)) return `${path} · lines ${start}–${end}`;
    if (Number.isFinite(start)) return `${path} · line ${start}`;
    return path;
  }

  function renderSelectedSource() {
    const leftItem = nodes.get(document.getElementById("similarity-left")?.value);
    const rightItem = nodes.get(document.getElementById("similarity-right")?.value);
    const renderColumn = (item, side) => {
      const title = document.getElementById(`similarity-${side}-source-title`);
      const location = document.getElementById(`similarity-${side}-source-location`);
      const code = document.getElementById(`similarity-${side}-source`);
      if (!title || !location || !code) return;
      title.textContent = item ? label(item) : `${side === "left" ? "Left" : "Right"} function`;
      location.textContent = sourceLocation(item);
      const source = item?.metadata?.source_code || "# Source code unavailable for this catalog node.";
      code.textContent = source;
    };
    renderColumn(leftItem, "left");
    renderColumn(rightItem, "right");
  }

  function renderResult(result) {
    const scorePercent = Math.max(0, Math.min(100, result.score * 100));
    const left = nodes.get(result.left_root);
    const right = nodes.get(result.right_root);
    document.getElementById("similarity-summary").className = "";
    document.getElementById("similarity-summary").innerHTML = `
      <div class="similarity-score">${result.score.toFixed(3)}</div>
      <div class="similarity-meter" style="--score-width:${scorePercent.toFixed(1)}%"><span></span></div>
      <p><code>${escapeHtml(left?.qualified_name || result.left_root)}</code><br>↔<br><code>${escapeHtml(right?.qualified_name || result.right_root)}</code></p>
      <p class="muted">Depth ${result.config.context_depth} · decay ${result.config.distance_decay.toFixed(2)} · external imports ${result.config.external_import_weight.toFixed(2)}</p>
    `;

    document.getElementById("similarity-layers").className = "similarity-layer-grid";
    document.getElementById("similarity-layers").innerHTML = result.layers.map(layer => `
      <article class="similarity-layer-card">
        <strong>Depth ${layer.distance}</strong>
        <div>Combined: ${layer.combined_similarity.toFixed(3)}</div>
        <div>Nodes: ${layer.node_similarity.toFixed(3)}</div>
        <div>Edges: ${layer.edge_similarity.toFixed(3)}</div>
        <div>Weight: ${layer.distance_weight.toFixed(3)}</div>
        <div>Pairs: ${layer.pair_count}</div>
      </article>
    `).join("");

    const comparisons = [...result.matched_nodes].sort((a, b) => a.distance - b.distance || b.score - a.score);
    document.getElementById("similarity-matches").className = "table-wrap";
    document.getElementById("similarity-matches").innerHTML = comparisons.length ? `
      <table class="similarity-match-table">
        <thead><tr><th>Depth</th><th>Left</th><th>Right</th><th>Node score</th></tr></thead>
        <tbody>${comparisons.map(match => {
          const leftNode = nodes.get(match.left_id);
          const rightNode = nodes.get(match.right_id);
          return `<tr><td>${match.distance}</td><td><code>${escapeHtml(leftNode?.qualified_name || match.left_id)}</code></td><td><code>${escapeHtml(rightNode?.qualified_name || match.right_id)}</code></td><td>${match.score.toFixed(3)}</td></tr>`;
        }).join("")}</tbody>
      </table>` : `<div class="empty-state">No function pairs were available for comparison.</div>`;
  }

  async function runComparison() {
    const button = document.getElementById("similarity-run");
    const summary = document.getElementById("similarity-summary");
    button.disabled = true;
    summary.className = "empty-state";
    summary.textContent = "Comparing neighborhoods…";
    try {
      const response = await fetch("/api/similarity/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          left_id: document.getElementById("similarity-left").value,
          right_id: document.getElementById("similarity-right").value,
          ...similarityConfigFor("similarity-pair-panel"),
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Comparison failed.");
      renderResult(payload);
    } catch (error) {
      summary.className = "empty-state similarity-error";
      summary.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }

  const left = document.getElementById("similarity-left");
  const right = document.getElementById("similarity-right");
  if (!left || !right) return;
  populateSelect(left, 0);
  populateSelect(right, functionNodes.length > 1 ? 1 : 0);
  renderSelectedSource();
  left.addEventListener("change", renderSelectedSource);
  right.addEventListener("change", renderSelectedSource);
  document.getElementById("similarity-run").addEventListener("click", runComparison);

  const pairMode = document.getElementById("similarity-pair-mode");
  const matrixMode = document.getElementById("similarity-matrix-mode");
  const duplicateMode = document.getElementById("similarity-duplicate-mode");
  const clusterMode = document.getElementById("similarity-cluster-mode");
  const pairPanel = document.getElementById("similarity-pair-panel");
  const matrixPanel = document.getElementById("similarity-matrix-panel");
  const duplicatePanel = document.getElementById("similarity-duplicate-panel");
  const clusterPanel = document.getElementById("similarity-cluster-panel");
  const matrixBuild = document.getElementById("similarity-matrix-build");
  const matrixDownload = document.getElementById("similarity-matrix-download");
  const matrixStatus = document.getElementById("similarity-matrix-status");
  const matrixSummary = document.getElementById("similarity-matrix-summary");
  const matrixTable = document.getElementById("similarity-matrix-table");
  let latestMatrix = null;

  function setSimilarityMode(mode) {
    const showPair = mode === "pair";
    const showMatrix = mode === "matrix";
    const showDuplicates = mode === "duplicates";
    const showClusters = mode === "clusters";
    pairMode?.classList.toggle("active", showPair);
    matrixMode?.classList.toggle("active", showMatrix);
    duplicateMode?.classList.toggle("active", showDuplicates);
    clusterMode?.classList.toggle("active", showClusters);
    if (pairPanel) pairPanel.hidden = !showPair;
    if (matrixPanel) matrixPanel.hidden = !showMatrix;
    if (duplicatePanel) duplicatePanel.hidden = !showDuplicates;
    if (clusterPanel) clusterPanel.hidden = !showClusters;
  }

  function matrixClass(score) {
    if (score >= .8) return "very-high";
    if (score >= .6) return "high";
    if (score >= .4) return "medium";
    if (score >= .2) return "low";
    return "very-low";
  }

  function openMatrixPair(leftId, rightId) {
    left.value = leftId;
    right.value = rightId;
    renderSelectedSource();
    setSimilarityMode("pair");
    runComparison();
  }

  function renderMatrix(result) {
    latestMatrix = result;
    matrixDownload.disabled = false;
    const summary = result.summary;
    matrixSummary.innerHTML = `
      <div class="matrix-summary-card"><strong>${summary.function_count}</strong><span>Functions</span></div>
      <div class="matrix-summary-card"><strong>${summary.computed_pair_count}</strong><span>Upper-triangle pairs</span></div>
      <div class="matrix-summary-card"><strong>${summary.mean_off_diagonal.toFixed(3)}</strong><span>Mean non-self score</span></div>
      <div class="matrix-summary-card"><strong>${summary.maximum_off_diagonal.toFixed(3)}</strong><span>Maximum non-self score</span></div>`;

    matrixTable.innerHTML = "";
    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");
    headerRow.appendChild(document.createElement("th"));
    result.labels.forEach((id, index) => {
      const th = document.createElement("th");
      th.textContent = String(index + 1);
      th.title = label(nodes.get(id) || { name: id });
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    matrixTable.appendChild(thead);

    const tbody = document.createElement("tbody");
    result.matrix.forEach((row, i) => {
      const tr = document.createElement("tr");
      const rowHeader = document.createElement("th");
      const item = nodes.get(result.labels[i]);
      rowHeader.textContent = `${i + 1}. ${label(item || { name: result.labels[i] })}`;
      rowHeader.title = result.labels[i];
      tr.appendChild(rowHeader);
      row.forEach((score, j) => {
        const td = document.createElement("td");
        const button = document.createElement("button");
        button.type = "button";
        button.className = `matrix-score ${matrixClass(score)}`;
        button.textContent = score.toFixed(2);
        button.title = `${result.labels[i]} ↔ ${result.labels[j]}: ${score.toFixed(6)}`;
        button.addEventListener("click", () => openMatrixPair(result.labels[i], result.labels[j]));
        td.appendChild(button);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    matrixTable.appendChild(tbody);
  }

  async function buildMatrix() {
    matrixBuild.disabled = true;
    matrixDownload.disabled = true;
    matrixStatus.textContent = "Computing repository-wide similarities…";
    try {
      const response = await fetch("/api/similarity/matrix", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...similarityConfigFor("similarity-matrix-panel"),
          ordering: "qualified_name",
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Matrix computation failed.");
      renderMatrix(payload);
      matrixStatus.textContent = `Complete: ${payload.summary.computed_pair_count} comparisons computed.`;
    } catch (error) {
      matrixStatus.textContent = `Matrix failed: ${error.message}`;
    } finally {
      matrixBuild.disabled = false;
    }
  }

  function downloadMatrixCsv() {
    if (!latestMatrix) return;
    const quote = value => `"${String(value).replaceAll('"', '""')}"`;
    const lines = [
      ["qualified_name", ...latestMatrix.labels].map(quote).join(","),
      ...latestMatrix.matrix.map((row, index) =>
        [latestMatrix.labels[index], ...row.map(value => value.toFixed(10))].map(quote).join(",")
      ),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "function_similarity_matrix.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  }




  const duplicateBuild = document.getElementById("similarity-duplicate-build");
  const duplicateStatus = document.getElementById("similarity-duplicate-status");
  const duplicateSummary = document.getElementById("similarity-duplicate-summary");
  const duplicateResults = document.getElementById("similarity-duplicate-results");
  const duplicateHealth = document.getElementById("similarity-duplicate-health");
  const duplicateSaveBaseline = document.getElementById("similarity-duplicate-save-baseline");
  const duplicateClearBaseline = document.getElementById("similarity-duplicate-clear-baseline");
  const duplicateBaselineStatus = document.getElementById("similarity-duplicate-baseline-status");
  let latestDuplicationSummary = null;

  function duplicationBaselineKey() {
    const root = window.CODEBASE_CATALOG?.project_root || "unknown-repository";
    return `codebase-catalog:duplication-baseline:${root}`;
  }

  function loadDuplicationBaseline() {
    try {
      const raw = localStorage.getItem(duplicationBaselineKey());
      return raw ? JSON.parse(raw) : null;
    } catch (_) {
      return null;
    }
  }

  function metricDelta(current, baseline, lowerIsBetter = true) {
    if (baseline === null || baseline === undefined) return "";
    const delta = current - baseline;
    const improved = lowerIsBetter ? delta < -1e-9 : delta > 1e-9;
    const worsened = lowerIsBetter ? delta > 1e-9 : delta < -1e-9;
    const state = improved ? "improved" : (worsened ? "worsened" : "unchanged");
    const sign = delta > 0 ? "+" : "";
    return `<span class="duplication-metric-delta ${state}">${sign}${(delta * 100).toFixed(2)} pp vs baseline</span>`;
  }

  function renderDuplicationHealth(summary) {
    latestDuplicationSummary = summary;
    const baseline = loadDuplicationBaseline();
    const metrics = [
      {
        label: "Duplication burden",
        value: summary.function_duplication_burden,
        help: "Average normalized excess above the threshold for each function's closest match.",
      },
      {
        label: "Function coverage",
        value: summary.duplicate_function_coverage,
        help: "Share of functions participating in at least one above-threshold pair.",
      },
      {
        label: "Duplicate pair rate",
        value: summary.duplicate_pair_rate,
        help: "Share of all unordered function pairs above the selected threshold.",
      },
      {
        label: "Mean nearest similarity",
        value: summary.mean_nearest_neighbor_similarity,
        help: "Average similarity between each function and its closest repository neighbor.",
      },
    ];

    duplicateHealth.className = "duplication-health-grid";
    duplicateHealth.innerHTML = metrics.map(metric => {
      const baselineValue = baseline?.summary?.[{
        "Duplication burden": "function_duplication_burden",
        "Function coverage": "duplicate_function_coverage",
        "Duplicate pair rate": "duplicate_pair_rate",
        "Mean nearest similarity": "mean_nearest_neighbor_similarity",
      }[metric.label]];
      return `<article class="duplication-metric-card" title="${escapeHtml(metric.help)}">
        <span>${escapeHtml(metric.label)}</span>
        <strong>${(metric.value * 100).toFixed(2)}%</strong>
        ${metricDelta(metric.value, baselineValue)}
        <small>${escapeHtml(metric.help)}</small>
      </article>`;
    }).join("");

    duplicateSaveBaseline.disabled = false;
    duplicateClearBaseline.disabled = !baseline;
    duplicateBaselineStatus.textContent = baseline
      ? `Baseline saved ${new Date(baseline.saved_at).toLocaleString()} at threshold ${Number(baseline.summary.threshold).toFixed(2)}.`
      : "No baseline saved for this repository.";
  }

  function saveDuplicationBaseline() {
    if (!latestDuplicationSummary) return;
    localStorage.setItem(duplicationBaselineKey(), JSON.stringify({
      saved_at: new Date().toISOString(),
      summary: latestDuplicationSummary,
    }));
    renderDuplicationHealth(latestDuplicationSummary);
  }

  function clearDuplicationBaseline() {
    localStorage.removeItem(duplicationBaselineKey());
    if (latestDuplicationSummary) renderDuplicationHealth(latestDuplicationSummary);
    else {
      duplicateClearBaseline.disabled = true;
      duplicateBaselineStatus.textContent = "No baseline saved for this repository.";
    }
  }

  function openDuplicatePair(leftId, rightId) {
    left.value = leftId;
    right.value = rightId;
    renderSelectedSource();
    setSimilarityMode("pair");
    runComparison();
  }

  function renderDuplicateCandidates(result) {
    const summary = result.summary;
    renderDuplicationHealth(summary);
    duplicateSummary.innerHTML = `
      <div class="matrix-summary-card"><strong>${summary.function_count}</strong><span>Functions</span></div>
      <div class="matrix-summary-card"><strong>${summary.compared_pair_count}</strong><span>Pairs examined</span></div>
      <div class="matrix-summary-card"><strong>${summary.matching_pair_count}</strong><span>Above threshold</span></div>
      <div class="matrix-summary-card"><strong>${summary.threshold.toFixed(2)}</strong><span>Minimum score</span></div>`;

    const candidates = result.candidates || [];
    duplicateResults.className = candidates.length ? "duplicate-candidate-list" : "empty-state";
    duplicateResults.innerHTML = candidates.length ? candidates.map((candidate, index) => {
      const leftItem = candidate.left || nodes.get(candidate.left_id) || { qualified_name: candidate.left_id };
      const rightItem = candidate.right || nodes.get(candidate.right_id) || { qualified_name: candidate.right_id };
      const factors = candidate.shared_factors || [];
      const explanations = candidate.explanation || [];
      return `<article class="duplicate-candidate-card">
        <div class="duplicate-candidate-heading">
          <div>
            <span class="duplicate-rank">Candidate ${index + 1}</span>
            <h3><code>${escapeHtml(leftItem.qualified_name || leftItem.name)}</code> ↔ <code>${escapeHtml(rightItem.qualified_name || rightItem.name)}</code></h3>
            <p class="muted">${escapeHtml(sourceLocation(leftItem))}<br>${escapeHtml(sourceLocation(rightItem))}</p>
          </div>
          <div class="duplicate-score" title="Overall rooted-neighborhood similarity">${candidate.score.toFixed(3)}</div>
        </div>
        <div class="duplicate-score-breakdown">
          <span>Root descriptors: <strong>${candidate.root_similarity.toFixed(3)}</strong></span>
          <span>Shared factors: <strong>${candidate.shared_factor_count}</strong></span>
        </div>
        ${explanations.length ? `<ul class="duplicate-explanations">${explanations.map(text => `<li>${escapeHtml(text)}</li>`).join("")}</ul>` : ""}
        <details class="duplicate-factors">
          <summary>Shared-factor explanation (${factors.length} shown)</summary>
          <div class="table-wrap"><table class="cluster-factor-table">
            <thead><tr><th>Factor</th><th>Namespace</th><th>Left</th><th>Right</th><th>Cosine contribution</th></tr></thead>
            <tbody>${factors.map(factor => `<tr>
              <td><code>${escapeHtml(factor.factor)}</code></td>
              <td>${escapeHtml(factor.namespace)}</td>
              <td>${factor.left_count}</td>
              <td>${factor.right_count}</td>
              <td>${factor.cosine_contribution.toFixed(4)}</td>
            </tr>`).join("")}</tbody>
          </table></div>
        </details>
        <div class="duplicate-actions"><button type="button" data-duplicate-left="${escapeHtml(candidate.left_id)}" data-duplicate-right="${escapeHtml(candidate.right_id)}">Inspect pair</button></div>
      </article>`;
    }).join("") : "No function pairs met the selected similarity threshold.";

    duplicateResults.querySelectorAll("button[data-duplicate-left]").forEach(button => {
      button.addEventListener("click", () => openDuplicatePair(button.dataset.duplicateLeft, button.dataset.duplicateRight));
    });
  }

  async function buildDuplicateCandidates() {
    duplicateBuild.disabled = true;
    duplicateStatus.textContent = "Comparing all function combinations and extracting shared factors…";
    try {
      const response = await fetch("/api/similarity/duplicates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          threshold: Number(document.getElementById("similarity-duplicate-threshold").value),
          limit: Number(document.getElementById("similarity-duplicate-limit").value),
          factor_limit: 12,
          ...similarityConfigFor("similarity-duplicate-panel"),
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Duplicate candidate analysis failed.");
      renderDuplicateCandidates(payload);
      duplicateStatus.textContent = `Complete: ${payload.summary.matching_pair_count} pairs met the threshold; ${payload.summary.returned_pair_count} shown.`;
    } catch (error) {
      duplicateStatus.textContent = `Candidate analysis failed: ${error.message}`;
    } finally {
      duplicateBuild.disabled = false;
    }
  }

  const clusterBuild = document.getElementById("similarity-cluster-build");
  const clusterStatus = document.getElementById("similarity-cluster-status");
  const clusterSummary = document.getElementById("similarity-cluster-summary");
  const clusterLegend = document.getElementById("similarity-cluster-legend");
  const clusterPlot = document.getElementById("similarity-cluster-plot");
  const clusterMembers = document.getElementById("similarity-cluster-members");
  const clusterFactorsPanel = document.getElementById("similarity-cluster-factors-panel");
  const clusterFactorsTitle = document.getElementById("similarity-cluster-factors-title");
  const clusterFactors = document.getElementById("similarity-cluster-factors");
  const clusterFactorsClose = document.getElementById("similarity-cluster-factors-close");
  const clusterPalette = ["#2563eb", "#dc2626", "#059669", "#7c3aed", "#d97706", "#0891b2", "#be185d", "#4d7c0f"];

  function clusterColor(cluster) {
    return clusterPalette[cluster % clusterPalette.length];
  }

  function openClusterRepresentative(functionId, representativeId) {
    left.value = functionId;
    right.value = representativeId === functionId
      ? (functionNodes.find(item => item.id !== functionId)?.id || functionId)
      : representativeId;
    setSimilarityMode("pair");
    if (left.value !== right.value) runComparison();
  }


  function renderClusterFactors(cluster) {
    if (!clusterFactorsPanel || !clusterFactors || !clusterFactorsTitle) return;
    clusterFactorsPanel.hidden = false;
    clusterFactorsTitle.textContent = `Cluster ${cluster.cluster + 1} common factors`;
    const factors = cluster.common_factors || [];
    clusterFactors.className = factors.length ? "table-wrap" : "empty-state";
    clusterFactors.innerHTML = factors.length ? `
      <table class="cluster-factor-table">
        <thead><tr><th>Factor</th><th>Type</th><th>Cluster</th><th>Repository</th><th>Distinctiveness</th></tr></thead>
        <tbody>${factors.map(row => {
          const clusterPct = row.cluster_prevalence * 100;
          const repositoryPct = row.repository_prevalence * 100;
          const distinctivenessPct = row.distinctiveness * 100;
          return `<tr>
            <td><code>${escapeHtml(row.value || row.factor)}</code><div class="cluster-factor-bar" title="${clusterPct.toFixed(1)}% of cluster members"><span style="width:${Math.max(0, Math.min(100, clusterPct)).toFixed(1)}%"></span></div></td>
            <td>${escapeHtml(row.namespace)}</td>
            <td>${clusterPct.toFixed(1)}% <span class="muted">(${row.cluster_count}/${cluster.size})</span></td>
            <td>${repositoryPct.toFixed(1)}%</td>
            <td class="cluster-factor-positive">${distinctivenessPct >= 0 ? "+" : ""}${distinctivenessPct.toFixed(1)} pts</td>
          </tr>`;
        }).join("")}</tbody>
      </table>` : `<div class="empty-state">No descriptor factors were available for this cluster.</div>`;
    clusterFactorsPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function renderClusters(result) {
    clusterSummary.innerHTML = `
      <div class="matrix-summary-card"><strong>${result.points.length}</strong><span>Functions</span></div>
      <div class="matrix-summary-card"><strong>${result.k}</strong><span>Clusters</span></div>
      <div class="matrix-summary-card"><strong>${result.inertia.toFixed(3)}</strong><span>K-means inertia</span></div>
      <div class="matrix-summary-card"><strong>${result.iterations}</strong><span>Iterations</span></div>`;

    clusterLegend.innerHTML = result.clusters.map(cluster => `
      <button type="button" class="cluster-legend-item cluster-factor-button" data-cluster-id="${cluster.cluster}"><span class="cluster-swatch" style="background:${clusterColor(cluster.cluster)}"></span>Cluster ${cluster.cluster + 1} · ${cluster.size}</button>`).join("");
    clusterLegend.querySelectorAll("button[data-cluster-id]").forEach(button => {
      button.addEventListener("click", () => {
        const cluster = result.clusters.find(entry => entry.cluster === Number(button.dataset.clusterId));
        if (cluster) renderClusterFactors(cluster);
      });
    });

    const width = 960, height = 560, padding = 55;
    const xs = result.points.map(point => point.x);
    const ys = result.points.map(point => point.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const spanX = maxX - minX || 1;
    const spanY = maxY - minY || 1;
    const scaleX = value => padding + ((value - minX) / spanX) * (width - 2 * padding);
    const scaleY = value => height - padding - ((value - minY) / spanY) * (height - 2 * padding);
    const ns = "http://www.w3.org/2000/svg";
    clusterPlot.innerHTML = "";

    const xAxis = document.createElementNS(ns, "line");
    xAxis.setAttribute("x1", padding); xAxis.setAttribute("x2", width - padding);
    xAxis.setAttribute("y1", height - padding); xAxis.setAttribute("y2", height - padding);
    xAxis.setAttribute("class", "cluster-axis"); clusterPlot.appendChild(xAxis);
    const yAxis = document.createElementNS(ns, "line");
    yAxis.setAttribute("x1", padding); yAxis.setAttribute("x2", padding);
    yAxis.setAttribute("y1", padding); yAxis.setAttribute("y2", height - padding);
    yAxis.setAttribute("class", "cluster-axis"); clusterPlot.appendChild(yAxis);

    result.points.forEach(point => {
      const circle = document.createElementNS(ns, "circle");
      circle.setAttribute("cx", scaleX(point.x));
      circle.setAttribute("cy", scaleY(point.y));
      circle.setAttribute("r", 5.5);
      circle.setAttribute("fill", clusterColor(point.cluster));
      circle.setAttribute("class", "cluster-point");
      const item = nodes.get(point.function_id);
      const cluster = result.clusters.find(entry => entry.cluster === point.cluster);
      circle.setAttribute("aria-label", `${label(item || {name: point.function_id})}, cluster ${point.cluster + 1}`);
      const title = document.createElementNS(ns, "title");
      title.textContent = `${label(item || {name: point.function_id})}\nCluster ${point.cluster + 1}\nDistance to centroid: ${point.distance_to_centroid.toFixed(4)}`;
      circle.appendChild(title);
      circle.addEventListener("click", () => openClusterRepresentative(point.function_id, cluster.representative_id));
      clusterPlot.appendChild(circle);
    });

    const grouped = new Map(result.clusters.map(cluster => [cluster.cluster, []]));
    result.points.forEach(point => grouped.get(point.cluster).push(point));
    clusterMembers.className = "cluster-members";
    clusterMembers.innerHTML = result.clusters.map(cluster => {
      const members = grouped.get(cluster.cluster).sort((a, b) => a.distance_to_centroid - b.distance_to_centroid);
      return `<section class="cluster-member-group">
        <div class="cluster-member-heading"><strong style="color:${clusterColor(cluster.cluster)}">Cluster ${cluster.cluster + 1}</strong><span>${cluster.size} functions</span><button type="button" class="cluster-factor-button" data-factor-cluster-id="${cluster.cluster}">Common factors</button></div>
        <ol class="cluster-member-list">${members.map(point => {
          const item = nodes.get(point.function_id);
          return `<li><button type="button" data-function-id="${escapeHtml(point.function_id)}" data-representative-id="${escapeHtml(cluster.representative_id)}">${escapeHtml(label(item || {name: point.function_id}))}</button></li>`;
        }).join("")}</ol>
      </section>`;
    }).join("");
    clusterMembers.querySelectorAll("button[data-function-id]").forEach(button => {
      button.addEventListener("click", () => openClusterRepresentative(button.dataset.functionId, button.dataset.representativeId));
    });
    clusterMembers.querySelectorAll("button[data-factor-cluster-id]").forEach(button => {
      button.addEventListener("click", () => {
        const cluster = result.clusters.find(entry => entry.cluster === Number(button.dataset.factorClusterId));
        if (cluster) renderClusterFactors(cluster);
      });
    });
  }

  async function buildClusters() {
    clusterBuild.disabled = true;
    clusterStatus.textContent = "Computing similarity matrix and K-means clusters…";
    try {
      const response = await fetch("/api/similarity/clusters", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          k: Number(document.getElementById("similarity-cluster-k").value),
          ...similarityConfigFor("similarity-cluster-panel"),
          ordering: "qualified_name",
          random_state: 42,
        }),
      });
      const responseText = await response.text();
      let payload;
      try {
        payload = responseText ? JSON.parse(responseText) : {};
      } catch (_) {
        const preview = responseText.trim().slice(0, 240);
        throw new Error(
          `Server returned ${response.status} ${response.statusText} instead of JSON` +
          (preview ? `: ${preview}` : ".")
        );
      }
      if (!response.ok) throw new Error(payload.error || `Clustering failed (${response.status}).`);
      renderClusters(payload);
      clusterStatus.textContent = `Complete: ${payload.points.length} functions assigned to ${payload.k} clusters.`;
    } catch (error) {
      clusterStatus.textContent = `Clustering failed: ${error.message}`;
    } finally {
      clusterBuild.disabled = false;
    }
  }

  pairMode?.addEventListener("click", () => setSimilarityMode("pair"));
  matrixMode?.addEventListener("click", () => setSimilarityMode("matrix"));
  duplicateMode?.addEventListener("click", () => setSimilarityMode("duplicates"));
  duplicateSaveBaseline?.addEventListener("click", saveDuplicationBaseline);
  duplicateClearBaseline?.addEventListener("click", clearDuplicationBaseline);
  clusterMode?.addEventListener("click", () => setSimilarityMode("clusters"));
  matrixBuild?.addEventListener("click", buildMatrix);
  duplicateBuild?.addEventListener("click", buildDuplicateCandidates);
  clusterBuild?.addEventListener("click", buildClusters);
  matrixDownload?.addEventListener("click", downloadMatrixCsv);
  clusterFactorsClose?.addEventListener("click", () => {
    if (clusterFactorsPanel) clusterFactorsPanel.hidden = true;
  });
})();
