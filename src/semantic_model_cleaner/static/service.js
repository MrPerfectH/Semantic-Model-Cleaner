/* Experimental service workflows. Uses the same backend contracts as the CLI. */
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  let revision = 0, epoch = 0, jobId = null, pollTimer = null, authTimer = null;
  let invalidating = Promise.resolve(), invalidationError = null;
  const fixture = document.body.dataset.fixture === 'true';
  const fields = ['tenant', 'workspace', 'model', 'scope', 'action', 'candidate', 'repository', 'localModel', 'mapping', 'compareRepo'];
  const node = (tag, text, className) => { const item = document.createElement(tag); if (text !== undefined) item.textContent = text; if (className) item.className = className; return item; };
  function error(message) { $('error').textContent = message || ''; $('error').hidden = !message; }
  async function api(path, method = 'GET', body) {
    const response = await smcFetch('/api/service/' + path, {method, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Service request failed.');
    return data;
  }
  function summary() {
    $('targetSummary').textContent = $('model').value ? `Tenant: ${$('tenant').value}\nWorkspace: ${$('workspace').value}\nModel: ${$('model').value}\nReport scope: ${$('scope').value.split(/\s+/).filter(Boolean).join(', ')}` : 'No deployment selected.';
    $('candidateFields').hidden = $('action').value !== 'validate';
    if ($('action').value === 'compare') $('repoFields').open = true;
  }
  function changed(id) {
    epoch += 1; clearTimeout(pollTimer); jobId = null;
    $('results').hidden = true; $('run').disabled = false; $('cancel').hidden = true;
    $('progress').textContent = 'Selection changed. Previous results and exports are invalidated.'; error('');
    if (id === 'tenant' || id === 'workspace') { $('model').replaceChildren(new Option('Load the workspace and select an exact model', '')); $('scope').value = ''; }
    if (id === 'tenant') {
      clearTimeout(authTimer); $('devicePrompt').hidden = true; $('deviceCode').textContent = '';
      api('sign-in', 'DELETE').catch(() => {});
    }
    summary();
    invalidating = invalidating.then(() => api('jobs', 'DELETE')).then(data => { revision = data.revision; invalidationError = null; }).catch(e => { invalidationError = e; error(e.message); });
  }
  fields.forEach(id => $(id).addEventListener('input', () => changed(id)));
  $('identity').addEventListener('click', async () => {
    const started = epoch;
    try {
      error(''); const data = await api('identity'); if (started !== epoch) return;
      if ($('tenant').value && $('tenant').value.toLowerCase() !== data.tenant_id) throw new Error('The credential tenant differs from your selected tenant. Sign in to that tenant explicitly; the target has not changed.');
      $('tenant').value = data.tenant_id;
      changed('tenant');
      $('authStatus').textContent = data.status === 'synthetic_fixture' ? 'Synthetic fixture identity loaded. No live sign-in.' : 'Credential tenant checked. Load workspace models to verify API access.';
    } catch (e) { error(e.message); }
  });
  $('signIn').disabled = fixture;
  $('signIn').addEventListener('click', async () => {
    try {
      error(''); const started = epoch;
      const data = await api('sign-in', 'POST', {tenant_id: $('tenant').value});
      if (started !== epoch) return;
      $('authStatus').textContent = 'Starting local device sign-in…'; $('cancelSignIn').hidden = false;
      pollAuth(started, data);
    } catch (e) { error(e.message); }
  });
  async function pollAuth(started, data) {
    if (started !== epoch) return;
    if (data.status === 'waiting') {
      $('devicePrompt').hidden = false; $('deviceCode').textContent = data.user_code;
      $('authStatus').textContent = 'Complete the Microsoft sign-in on this computer. No app registration or permission grant is performed by Semantic Model Cleaner.';
    }
    if (['ready', 'failed', 'cancelled'].includes(data.status)) {
      $('devicePrompt').hidden = true; $('deviceCode').textContent = ''; $('cancelSignIn').hidden = true;
      $('authStatus').textContent = data.status === 'ready' ? 'Local credential tenant checked. Load models to verify workspace access.' : (data.message || 'Sign-in cancelled.');
      return;
    }
    authTimer = setTimeout(async () => { try { await pollAuth(started, await api('sign-in')); } catch (e) { error(e.message); } }, 800);
  }
  $('cancelSignIn').addEventListener('click', async () => {
    clearTimeout(authTimer);
    try { await api('sign-in', 'DELETE'); $('devicePrompt').hidden = true; $('deviceCode').textContent = ''; $('cancelSignIn').hidden = true; $('authStatus').textContent = 'Sign-in cancelled.'; } catch (e) { error(e.message); }
  });
  $('models').addEventListener('click', async () => {
    const started = epoch; $('models').disabled = true; $('authStatus').textContent = 'Checking access to this exact workspace…';
    try {
      error(''); await invalidating;
      if (started !== epoch) return;
      if (invalidationError) throw invalidationError;
      const data = await api('models', 'POST', {tenant_id: $('tenant').value, workspace_id: $('workspace').value});
      if (started !== epoch) return;
      $('model').replaceChildren(new Option('Select a model by its exact ID', ''));
      data.models.forEach(model => $('model').add(new Option(`${model.display_name} — ${model.id}`, model.id)));
      $('authStatus').textContent = `${data.models.length} visible model(s). ${fixture ? 'Synthetic fixture; live access unverified.' : 'Authenticated workspace access; definition access is checked during the run.'}`;
    } catch (e) { error(e.message); } finally { $('models').disabled = false; }
  });
  $('run').addEventListener('click', async () => {
    const started = epoch;
    try {
      error(''); await invalidating;
      if (started !== epoch) return;
      if (invalidationError) throw invalidationError;
      const payload = {revision, action: $('action').value, tenant_id: $('tenant').value, workspace_id: $('workspace').value, model_id: $('model').value,
        report_workspace_ids: $('scope').value.split(/\s+/).filter(Boolean), candidate: $('candidate').value.trim(), repository: ($('compareRepo').checked || $('action').value === 'compare') ? $('repository').value.trim() : '', local_model: $('localModel').value.trim(), mapping: $('mapping').value.trim()};
      if (!payload.model_id || !payload.report_workspace_ids.length) throw new Error('Select an exact model and at least one report workspace.');
      if (payload.action === 'validate' && !payload.candidate) throw new Error('Choose the exact local candidate directory.');
      if (payload.action === 'compare' && (!payload.repository || !payload.local_model)) throw new Error('Choose the repository and exact local model directories.');
      $('run').disabled = true; $('results').hidden = true; $('progress').textContent = 'Starting read-only check…';
      const job = await api('jobs', 'POST', payload);
      if (started !== epoch) return;
      jobId = job.id; $('cancel').hidden = false; await pollJob(started);
    } catch (e) { error(e.message); $('run').disabled = false; }
  });
  async function pollJob(started) {
    if (started !== epoch || !jobId) return;
    try {
      const job = await api('jobs/' + jobId);
      if (started !== epoch) return;
      $('progress').textContent = job.stage;
      if (['running', 'cancelling'].includes(job.status)) { pollTimer = setTimeout(() => pollJob(started), 400); return; }
      $('run').disabled = false; $('cancel').hidden = true;
      if (job.status === 'completed') render(job.result);
      else if (job.status === 'failed') error(job.error);
      else $('progress').textContent = 'Check cancelled. No service result was applied to local analysis.';
    } catch (e) { if (started === epoch) { error(e.message); $('run').disabled = false; $('cancel').hidden = true; } }
  }
  $('cancel').addEventListener('click', async () => {
    try { if (jobId) await api('jobs/' + jobId, 'DELETE'); $('progress').textContent = 'Cancelling after the current bounded request…'; } catch (e) { error(e.message); }
  });
  function findingList(target, findings) {
    target.replaceChildren();
    if (!findings.length) { target.append(node('p', 'No findings in the metadata that was checked. See Analysis Limitations for unchecked scope.', 'muted')); return; }
    findings.forEach(finding => {
      const card = node('div', undefined, 'finding');
      card.append(node('strong', finding.issueType || finding.code || finding.feature || 'Finding'));
      card.append(node('p', finding.message || finding.effect || ''));
      const location = [finding.report_id, finding.page, finding.visualId, finding.sourcePath || finding.source_file].filter(Boolean).join(' · ');
      if (location) card.append(node('p', location, 'muted'));
      if (finding.unchecked) card.append(node('p', 'Unchecked: ' + finding.unchecked, 'muted'));
      if (finding.service_url && /^https:\/\/app\.powerbi\.com\/groups\/[a-f0-9-]+\/reports\/[a-f0-9-]+$/i.test(finding.service_url)) {
        const link = node('a', 'Open Report'); link.href = finding.service_url; link.target = '_blank'; link.rel = 'noreferrer'; card.append(link);
      }
      target.append(card);
    });
  }
  function render(result) {
    $('results').hidden = false;
    $('progress').textContent = `${result.status} · ${result.evidence_kind} · exit ${result.exit_code}. Live acceptance remains unverified.`;
    if (result.errors.length) error(result.errors.map(row => row.message).join(' '));
    const stats = node('div', undefined, 'stats');
    [['Known direct Reports', result.known_connected_report_count], ['Analyzed Reports', result.reports.filter(r => r.status === 'analyzed').length], ['Report Health findings', result.report_health.findings.length], ['Analysis Limitations', result.analysis_limitations.length]].forEach(([label, value]) => { const item = node('div', undefined, 'stat'); item.append(node('strong', String(value)), node('span', label)); stats.append(item); });
    $('resultSummary').replaceChildren(stats, node('p', `Selected supported scope: ${result.selected_scope_complete ? 'completed' : 'incomplete'}. Global consumers: unknown. Cleanup is unavailable.`, 'muted'));
    $('reports').replaceChildren();
    result.reports.forEach(report => {
      const tr = node('tr'); const name = node('td'); const link = node('a', report.name || report.report_id); link.href = report.service_url; link.target = '_blank'; link.rel = 'noreferrer'; name.append(link);
      const identity = node('td'); identity.append(node('code', `${report.workspace_id}\n${report.report_id}`));
      tr.append(name, identity, node('td', report.status + (report.reason ? ' · ' + report.reason : '')), node('td', report.definition ? `${report.definition.format} · ${report.definition.sha256.slice(0, 12)}` : 'Not retrieved')); $('reports').append(tr);
    });
    $('candidateComparison').hidden = !result.comparison;
    if (result.comparison) {
      $('candidateCounts').textContent = ['pre_existing', 'introduced', 'resolved'].map(key => `${key.replace('_', ' ')}: ${result.comparison[key].length}`).join(' · ');
      findingList($('candidateFindings'), result.comparison.introduced);
    }
    $('repositoryComparison').hidden = !result.repository_comparison;
    if (result.repository_comparison) {
      $('repositoryResults').replaceChildren();
      ['matched', 'additional_published', 'local_only', 'unresolved', 'excluded_local'].forEach(key => {
        const rows = result.repository_comparison[key]; $('repositoryResults').append(node('h4', `${key.replaceAll('_', ' ')} (${rows.length})`));
        rows.forEach(row => $('repositoryResults').append(node('p', `${row.local_report || row.name || row.report_id} · ${row.identity_evidence || row.reason || ''} · ${row.definition_comparison?.status || ''}`)));
      });
    }
    findingList($('health'), result.report_health.findings); findingList($('limitations'), result.analysis_limitations);
    $('provenance').textContent = JSON.stringify({target: result.target, snapshot: result.snapshot, model_definition: result.model_definition, candidate: result.candidate, workspaces: result.workspaces, boundaries: result.boundaries, validation_limits: result.validation_limits}, null, 2);
  }
  $('export').addEventListener('click', () => { if (jobId) smcDownload('/api/service/jobs/' + jobId + '/export'); });
  $('privateExport').addEventListener('click', () => { if (jobId) smcDownload('/api/service/jobs/' + jobId + '/export?private=1'); });
  api('state').then(state => { revision = state.revision; if (!state.azure_cli_available && !fixture) $('authStatus').textContent = 'Azure CLI is not installed. Install it through your approved setup, or start the app with existing Fabric and Power BI tokens. Offline projects remain available.'; }).catch(e => error(e.message));
  summary();
}());
