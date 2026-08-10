(() => {
  const form = document.getElementById("repository-open-form");
  const pathInput = document.getElementById("repository-path");
  const openButton = document.getElementById("repository-open");
  const reloadButton = document.getElementById("repository-reload");
  const status = document.getElementById("repository-status");

  if (!form || !pathInput || !openButton || !reloadButton || !status) return;

  pathInput.value = window.CODEBASE_CATALOG?.project_root || "";

  function setBusy(message, busy) {
    status.textContent = message;
    pathInput.disabled = busy;
    openButton.disabled = busy;
    reloadButton.disabled = busy;
  }

  async function request(url, body = {}) {
    const response = await fetch(url, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `Request failed: ${response.status}`);
    return payload;
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();
    const path = pathInput.value.trim();
    if (!path) {
      status.textContent = "Enter a repository path.";
      pathInput.focus();
      return;
    }
    setBusy("Analyzing repository…", true);
    try {
      const result = await request("/api/repository/open", {path});
      sessionStorage.setItem("catalogToast", result.message || "Repository loaded.");
      // Force a fresh GET instead of reusing the document that embeds the old
      // repository catalog. The query token also avoids stale proxy/browser data.
      // Reload the current application URL rather than navigating to `/`.
      // This also works when the Flask app is hosted beneath a URL prefix.
      window.location.reload();
    } catch (error) {
      setBusy(error.message, false);
    }
  });

  reloadButton.addEventListener("click", async () => {
    setBusy("Reanalyzing current repository…", true);
    try {
      const result = await request("/api/repository/reload");
      sessionStorage.setItem("catalogToast", result.message || "Repository reanalyzed.");
      window.location.reload();
    } catch (error) {
      setBusy(error.message, false);
    }
  });
})();
