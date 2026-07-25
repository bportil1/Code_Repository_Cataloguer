(() => {
  const catalog = window.CODEBASE_CATALOG;
  let activeFunctionId = null;
  let activePlanId = null;

  async function api(url, options = {}) {
    const response = await fetch(url, {headers:{'Content-Type':'application/json'}, ...options});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `Request failed: ${response.status}`);
    return payload;
  }

  const esc = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');

  function selectedNode() {
    const selected = document.querySelector('.tree-entry.selected');
    return selected ? catalog.nodes[selected.dataset.nodeId] : catalog.nodes[catalog.root_node_id];
  }

  function addRefactorAction() {
    const details = document.getElementById('details');
    if (!details || details.querySelector('.refactor-actions')) return;
    const item = selectedNode();
    const section = document.createElement('section');
    section.className = 'refactor-actions';
    section.innerHTML = item?.node_type === 'function'
      ? `<h3>Reorganize</h3><button type="button" class="move-function-action">Move selected function</button><p class="muted">Preview and move this indexed top-level function to another existing Python file.</p>`
      : `<h3>Reorganize</h3><p class="muted">Function moves are available when a top-level function is selected.</p>`;
    details.insertBefore(section, details.querySelector('.local-dependencies') || details.lastChild);
    section.querySelector('.move-function-action')?.addEventListener('click', () => openDialog(item));
  }

  function openDialog(item) {
    activeFunctionId = item.id;
    activePlanId = null;
    const modules = Object.values(catalog.nodes)
      .filter(node => node.node_type === 'module' && node.id !== item.parent_id)
      .sort((a,b) => (a.path || '').localeCompare(b.path || ''));
    document.getElementById('move-function-name').textContent = `${item.name}() · ${item.path}`;
    document.getElementById('move-target-module').innerHTML = modules.map(node => `<option value="${esc(node.id)}">${esc(node.path)}</option>`).join('');
    document.getElementById('move-preview').className = 'empty-state';
    document.getElementById('move-preview').textContent = modules.length ? 'Choose a target module and preview the change.' : 'No other Python module is available.';
    document.getElementById('preview-function-move').disabled = !modules.length;
    document.getElementById('apply-move-wrap').classList.add('hidden');
    document.getElementById('move-function-dialog').showModal();
  }

  async function preview() {
    const area = document.getElementById('move-preview');
    area.className = '';
    area.innerHTML = '<p class="muted">Building and validating the change plan…</p>';
    try {
      const result = await api('/api/refactor/move-function/preview', {
        method:'POST',
        body:JSON.stringify({function_id:activeFunctionId,target_module_id:document.getElementById('move-target-module').value})
      });
      activePlanId = result.plan_id;
      area.innerHTML = `<h3>${esc(result.summary.function)}</h3><p><code>${esc(result.summary.source)}</code> → <code>${esc(result.summary.target)}</code></p>${result.warnings.length ? `<div class="move-warning"><strong>Warnings</strong><ul>${result.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></div>` : ''}${result.changes.map(c=>`<section class="move-diff"><h3>${esc(c.path)}</h3><pre><code>${esc(c.diff)}</code></pre></section>`).join('')}`;
      document.getElementById('apply-move-wrap').classList.remove('hidden');
    } catch (error) {
      activePlanId = null;
      area.className = 'empty-state'; area.textContent = error.message;
      document.getElementById('apply-move-wrap').classList.add('hidden');
    }
  }

  async function applyMove() {
    if (!activePlanId) return;
    try {
      const result = await api('/api/refactor/move-function/apply', {method:'POST',body:JSON.stringify({plan_id:activePlanId})});
      sessionStorage.setItem('catalogToast', result.message);
      location.reload();
    } catch (error) { toast(error.message); }
  }

  async function undo() {
    try {
      const result = await api('/api/refactor/undo', {method:'POST',body:'{}'});
      sessionStorage.setItem('catalogToast', result.message);
      location.reload();
    } catch (error) { toast(error.message); }
  }

  function toast(message) {
    const box = document.getElementById('refactor-toast');
    box.textContent = message; box.classList.remove('hidden');
    setTimeout(() => box.classList.add('hidden'), 5000);
  }

  const observer = new MutationObserver(addRefactorAction);
  observer.observe(document.getElementById('details'), {childList:true});
  document.addEventListener('click', event => {
    if (event.target.closest('.tree-entry')) setTimeout(addRefactorAction, 0);
  });
  const previewButton = document.getElementById('preview-function-move');
  const applyButton = document.getElementById('apply-function-move');
  const undoButton = document.getElementById('undo-refactor');

  if (!previewButton || !applyButton || !undoButton) {
    console.error('Refactor controls were not loaded before refactor.js initialized.');
    return;
  }

  previewButton.addEventListener('click', preview);
  applyButton.addEventListener('click', applyMove);
  undoButton.addEventListener('click', undo);
  addRefactorAction();
  const pending = sessionStorage.getItem('catalogToast');
  if (pending) { sessionStorage.removeItem('catalogToast'); toast(pending); }
})();
