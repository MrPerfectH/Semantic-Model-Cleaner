/* Integrated workspace navigation. Scope choices never modify model/report files. */
(function () {
  'use strict';
  var embedded = !!document.querySelector('meta[name="smc-embedded-host"][data-host-scope="sidebar"]');
  var rail = document.querySelector('.rail-bottom'), nav = $('viewTabs');
  var secondary = document.createElement('details'); secondary.id = 'workspaceSecondary';
  secondary.innerHTML = '<summary>More</summary>'; rail.prepend(secondary);
  ['tabRefs', 'tabLimitations'].forEach(function (id) { secondary.appendChild($(id)); });
  $('tabLimitations').childNodes[0].textContent = 'Scan details ';
  var history = $('objectHistoryButton'); history.className = 'view-tab'; history.textContent = 'Changes'; nav.appendChild(history);
  document.querySelectorAll('.object-persistent-review').forEach(function (el) { el.remove(); });
  // Counts live with results; retain original count nodes for existing renderers.
  nav.querySelectorAll('.tab-count').forEach(function (el) { el.hidden = true; });
  var policy = Array.from(nav.querySelectorAll('button')).find(function (b) { return b.textContent === 'Review policy'; });
  if (policy) secondary.appendChild(policy);
  var settings = document.createElement('dialog'); settings.id = 'workspaceSettings'; settings.className = 'workspace-settings';
  settings.innerHTML = '<header><h2>Settings</h2><button type="button" class="btn btn-secondary" data-settings-close>Close</button></header>';
  var options = $('autoRefreshAfterApply').closest('.setup-block'); settings.appendChild(options); document.body.appendChild(settings);
  var settingsButton = document.createElement('button'); settingsButton.type = 'button'; settingsButton.className = 'rail-item'; settingsButton.textContent = 'Settings';
  settingsButton.onclick = function () { settings.showModal(); }; settings.querySelector('[data-settings-close]').onclick = function () { settings.close(); settingsButton.focus(); }; rail.appendChild(settingsButton);
  // Summary totals and cleanup controls belong beside the selected results.
  var summary = $('summarySection'); summary.classList.add('workspace-result-counts'); $('mainArea').insertBefore(summary, $('resultOverview'));

  var reportIntro = document.createElement('section'); reportIntro.className = 'reports-intro';
  reportIntro.innerHTML = '<h2>Reports</h2><p>Metadata findings and scan coverage for the selected reports. This does not assess runtime performance, visual quality or rendered behavior.</p><p>Valid means a file matches its declared supported schema. Invalid means that check failed. Not validated means the schema was missing, unsupported or unavailable.</p><p id="reportsFindingSummary" role="status"></p><div id="reportInventory"></div><button type="button" class="btn btn-secondary btn-sm" id="reportsReferences">Browse report references</button>';
  $('reportsTableSection').prepend(reportIntro); $('reportsReferences').onclick = function () { switchView('refs'); };
  $('reportsTableSection').insertBefore($('reportHealthBanner'), reportIntro.nextSibling);
  var oldResults = setResultsData;
  setResultsData = function (data) {
    var result = oldResults.apply(this, arguments);
    $('reportsFindingSummary').textContent = ((data.reportHealth || {}).totalIssueCount || 0) + ' metadata finding row(s). Rows can overlap and do not count unique visuals. Broken references and invalid definitions require a source-report fix.';
    if (data.analysisLimitations && !data.analysisLimitations.affectedItemCount && !data.analysisLimitations.sharedCount) $('analysisLimitationsBanner').open = false;
    return result;
  };

  if (embedded) {
    document.body.classList.add('sidebar-owned-scope');
    document.body.classList.remove('scope-open');
    window.smcOpenScope = function () {
      var focusSidebar = document.querySelector('#smcHostScope button');
      if (focusSidebar) focusSidebar.click();
    };
    return;
  }
  document.body.classList.add('standalone-scope-flow');
  var body = $('setupBody'), drawer = $('scopeDrawer'), footer = drawer.querySelector('.setup-footer');
  drawer.setAttribute('aria-label', 'Set up analysis'); drawer.setAttribute('role', 'dialog'); drawer.setAttribute('aria-modal', 'true');
  drawer.querySelector('h2').textContent = 'Set up analysis';
  $('btnToggleSetup').hidden = true;
  var steps = document.createElement('nav'); steps.className = 'scope-steps'; steps.setAttribute('aria-label', 'Setup steps');
  steps.innerHTML = '<button type="button" data-scope-step="0">1 Â· Model</button><button type="button" data-scope-step="1">2 Â· Reports</button><button type="button" data-scope-step="2">3 Â· Review scope</button>';
  body.before(steps);
  var project = $('btnRefreshProject').closest('.setup-block'), model = $('modelPills').closest('.setup-block'), reports = $('reportPills').closest('.setup-block');
  reports.insertAdjacentHTML('beforeend', '<label class="scope-model-only"><input type="checkbox" id="scopeModelOnly"> Analyze model only â€” do not check report usage</label>');
  var review = document.createElement('section'); review.className = 'scope-review-final'; review.id = 'scopeFinalReview'; body.appendChild(review);
  var back = document.createElement('button'); back.type = 'button'; back.className = 'btn btn-secondary'; back.textContent = 'Back';
  var next = document.createElement('button'); next.type = 'button'; next.className = 'btn btn-primary'; next.textContent = 'Continue';
  footer.insertBefore(back, $('btnAnalyze')); footer.insertBefore(next, $('btnAnalyze'));
  var step = 0;
  window.smcModelOnly = function () { return $('scopeModelOnly').checked; };
  var oldPost = apiPost;
  apiPost = function (url, data) {
    if (url === '/api/analyze' && window.smcModelOnly()) data = Object.assign({}, data, {report_selection: 'exact', report_paths: []});
    return oldPost(url, data);
  };
  window.smcRenderScopeSteps = function () {
    project.hidden = model.hidden = step !== 0; reports.hidden = step !== 1;
    $('scopeReview').hidden = step !== 1; review.hidden = step !== 2;
    back.hidden = step === 0; next.hidden = step === 2; $('btnAnalyze').hidden = step !== 2;
    next.disabled = step === 0 ? chosenModels.length !== 1 : !chosenReports.length && !window.smcModelOnly();
    steps.querySelectorAll('button').forEach(function (b) { var n = Number(b.dataset.scopeStep); b.setAttribute('aria-current', n === step ? 'step' : 'false'); b.disabled = n > 0 && chosenModels.length !== 1; });
    review.innerHTML = '<h3>Review analysis scope</h3><p><strong>Model:</strong> ' + esc(chosenModels.map(function (m) { return m.name; }).join(', ') || 'None selected') + '</p><p>' + (window.smcModelOnly() ? 'Model-only analysis. Report usage is not checked; this is not evidence of model-wide non-use.' : chosenReports.length + ' selected report(s)') + '</p><ul>' + chosenReports.map(function (r) { return '<li>' + esc(r.name) + '<small>' + esc(r.path) + '</small></li>'; }).join('') + '</ul><p>Analyze reads this scope. Changes require a separate reviewed plan.</p>';
    $('btnBrowseReports').disabled = $('btnBrowseConnectedReportRoot').disabled = window.smcModelOnly();
  };
  function go(value) { step = Math.max(0, Math.min(2, value)); window.smcRenderScopeSteps(); steps.querySelector('[data-scope-step="' + step + '"]').focus(); }
  steps.onclick = function (event) { var b = event.target.closest('[data-scope-step]'); if (b) go(Number(b.dataset.scopeStep)); };
  back.onclick = function () { go(step - 1); }; next.onclick = function () { go(step + 1); };
  $('scopeModelOnly').onchange = function () { if (this.checked) chosenReports = []; renderPills(); window.smcRenderScopeSteps(); };
  var oldOpen = window.smcOpenScope;
  window.smcOpenScope = function () { oldOpen(); $('setupBody').classList.remove('hidden'); go(chosenModels.length ? 1 : 0); };
  window.smcRenderScopeSteps();
})();
