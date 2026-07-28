/*
Assumptions:
- Existing controls have IDs:
  similarity-depth, similarity-decay, similarity-external-weight
- Existing pair selectors have IDs:
  similarity-left, similarity-right
- Existing comparison button has ID:
  compare-similarity
- Clicking compare renders the current local explanation.
*/
(() => {
  const pairMode = document.getElementById("similarity-pair-mode");
  const matrixMode = document.getElementById("similarity-matrix-mode");
  const pairPanel = document.getElementById("similarity-pair-panel");
  const matrixPanel = document.getElementById("similarity-matrix-panel");
  const buildButton = document.getElementById("build-similarity-matrix");
  const downloadButton = document.getElementById("download-similarity-matrix");
  const status = document.getElementById("similarity-matrix-status");
  const summary = document.getElementById("similarity-matrix-summary");
  const table = document.getElementById("similarity-matrix-table");

  let latestResult = null;

  function setMode(mode) {
    const matrixActive = mode === "matrix";
    pairMode.classList.toggle("active", !matrixActive);
    matrixMode.classList.toggle("active", matrixActive);
    if (pairPanel) pairPanel.hidden = matrixActive;
    matrixPanel.hidden = !matrixActive;
  }

  function currentConfig() {
    return {
      context_depth: Number(document.getElementById("similarity-depth")?.value ?? 1),
      distance_decay: Number(document.getElementById("similarity-decay")?.value ?? 0.5),
      external_import_weight: Number(
        document.getElementById("similarity-external-weight")?.value ?? 0.2
      ),
      internal_edge_weight: 1.0,
      node_weight: 1.0,
      ordering: "qualified_name"
    };
  }

  function scoreClass(score) {
    if (score >= 0.80) return "matrix-score very-high";
    if (score >= 0.60) return "matrix-score high";
    if (score >= 0.40) return "matrix-score medium";
    if (score >= 0.20) return "matrix-score low";
    return "matrix-score very-low";
  }

  function renderMatrix(result) {
    latestResult = result;
    downloadButton.disabled = false;

    const s = result.summary;
    summary.innerHTML = `
      <div class="matrix-summary-card"><strong>${s.function_count}</strong><span>Functions</span></div>
      <div class="matrix-summary-card"><strong>${s.computed_pair_count}</strong><span>Computed pairs</span></div>
      <div class="matrix-summary-card"><strong>${s.mean_off_diagonal.toFixed(3)}</strong><span>Mean similarity</span></div>
      <div class="matrix-summary-card"><strong>${s.maximum_off_diagonal.toFixed(3)}</strong><span>Maximum non-self</span></div>
    `;

    table.innerHTML = "";
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    headRow.appendChild(document.createElement("th"));
    result.labels.forEach((label, index) => {
      const th = document.createElement("th");
      th.title = label;
      th.textContent = String(index + 1);
      headRow.appendChild(th);
    });
    head.appendChild(headRow);
    table.appendChild(head);

    const body = document.createElement("tbody");
    result.matrix.forEach((row, i) => {
      const tr = document.createElement("tr");
      const rowHeader = document.createElement("th");
      rowHeader.scope = "row";
      rowHeader.title = result.labels[i];
      rowHeader.textContent = `${i + 1}. ${result.labels[i]}`;
      tr.appendChild(rowHeader);

      row.forEach((score, j) => {
        const td = document.createElement("td");
        const button = document.createElement("button");
        button.type = "button";
        button.className = scoreClass(score);
        button.textContent = score.toFixed(2);
        button.title = `${result.labels[i]} ↔ ${result.labels[j]}: ${score.toFixed(6)}`;
        button.addEventListener("click", () => openPair(result.labels[i], result.labels[j]));
        td.appendChild(button);
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    table.appendChild(body);
  }

  function openPair(left, right) {
    const leftSelect = document.getElementById("similarity-left");
    const rightSelect = document.getElementById("similarity-right");
    if (!leftSelect || !rightSelect) return;

    leftSelect.value = left;
    rightSelect.value = right;
    leftSelect.dispatchEvent(new Event("change", { bubbles: true }));
    rightSelect.dispatchEvent(new Event("change", { bubbles: true }));
    setMode("pair");
    document.getElementById("compare-similarity")?.click();
  }

  async function buildMatrix() {
    buildButton.disabled = true;
    downloadButton.disabled = true;
    status.textContent = "Computing repository-wide similarities…";
    try {
      const response = await fetch("/api/similarity/matrix", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(currentConfig())
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      renderMatrix(payload);
      status.textContent = `Complete: ${payload.summary.computed_pair_count} upper-triangle comparisons.`;
    } catch (error) {
      status.textContent = `Matrix failed: ${error.message}`;
    } finally {
      buildButton.disabled = false;
    }
  }

  function downloadCsv() {
    if (!latestResult) return;
    const escape = value => `"${String(value).replaceAll('"', '""')}"`;
    const lines = [
      ["qualified_name", ...latestResult.labels].map(escape).join(","),
      ...latestResult.matrix.map((row, index) =>
        [latestResult.labels[index], ...row.map(value => value.toFixed(10))]
          .map(escape)
          .join(",")
      )
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "function_similarity_matrix.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  pairMode?.addEventListener("click", () => setMode("pair"));
  matrixMode?.addEventListener("click", () => setMode("matrix"));
  buildButton?.addEventListener("click", buildMatrix);
  downloadButton?.addEventListener("click", downloadCsv);
})();
