/* VS Code sidebar scope. Loaded only when the extension owns model/report
 * selection: the page analyzes exactly the selection the sidebar sends (zero
 * Reports means model-only) and blocks results that no longer match it. */
(function () {
  'use strict';
  if (!document.querySelector('meta[name="smc-embedded-host"][data-host-scope="sidebar"]')) return;
  var parentOrigin = (location.ancestorOrigins && location.ancestorOrigins[0]) || '';
  if (window.parent === window || !/^vscode-webview:\/\/[a-z0-9-]+$/.test(parentOrigin)) return;

  var current = null;   // latest sidebar selection
  var analyzed = null;  // selection the displayed results belong to
  var running = null;   // key of the analysis in flight
  function post(message) { window.parent.postMessage(message, parentOrigin); }
  function plural(count, noun) { return count + ' ' + noun + (count === 1 ? '' : 's'); }
  function describe(scope) {
    return scope.model.name + ' · ' + (scope.reports.length
      ? scope.reports.length + ' of ' + plural(scope.total, 'report')
      : 'model only (0 of ' + plural(scope.total, 'report') + ')');
  }

  var style = document.createElement('style');
  style.textContent = '#scopeChip,#scopeDrawer,#scopeOverlay,#setupSection,#welcomeCard,#smcHostScope[hidden]{display:none!important}'
    + '#smcHostScope{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:10px 16px;padding:10px 14px;'
    + 'border:1px solid #cbd5e1;border-radius:10px;background:#f8fafc;color:#0f172a;font-size:13px}'
    + '#smcHostScope[data-state="stale"],#smcHostScope[data-state="failed"]{border-color:#f59e0b;background:#fffbeb}'
    + '#smcHostScope strong{font-weight:600}#smcHostScope span{flex:1;min-width:240px}'
    + '[data-smc-stale]{opacity:.35;filter:grayscale(1)}';
  document.head.appendChild(style);
  var banner = document.createElement('section');
  banner.id = 'smcHostScope'; banner.setAttribute('role', 'status'); banner.setAttribute('aria-label', 'Analysis scope');
  var text = document.createElement('span');
  banner.append(text);
  // The sidebar already shows the selection; the banner only speaks up when
  // results are missing, running, stale or failed.
  window.smcHostFocusScope = function () { post({type: 'smc-focus-scope'}); };
  var header = document.querySelector('.header');
  if (header) header.after(banner); else document.body.prepend(banner);

  function render() {
    var stale = !!(analyzed && (!current || analyzed.key !== current.key));
    // Stale results stay visible for reference but cannot be selected or acted on.
    document.querySelectorAll('.cleanup-flow, #mainArea, #viewToolbar, #exportSection').forEach(function (el) {
      if (stale) { el.inert = true; el.setAttribute('data-smc-stale', ''); }
      else { el.inert = false; el.removeAttribute('data-smc-stale'); }
    });
    var state = stale ? 'stale' : banner.dataset.error ? 'failed' : running ? 'running' : analyzed ? 'current' : 'empty';
    banner.dataset.state = state;
    banner.hidden = state === 'current';
    text.textContent = '';
    var strong = document.createElement('strong');
    if (!current || !current.model) {
      strong.textContent = 'Choose a semantic model in the Cleaner sidebar.';
      text.append(strong, ' Then choose its reports and select Analyze.');
    } else if (stale) {
      strong.textContent = 'Results are out of date.';
      text.append(strong, ' They are for ' + describe(analyzed) + '. The sidebar now has ' + describe(current)
        + '. Select Analyze in the sidebar to refresh.');
    } else if (state === 'running') {
      strong.textContent = 'Analyzing ' + describe(current) + '…';
      text.append(strong);
    } else if (state === 'failed') {
      strong.textContent = 'Analysis failed. ';
      text.append(strong, banner.dataset.error);
    } else if (analyzed) {
      strong.textContent = 'Analyzed: ';
      text.append(strong, describe(current));
    } else {
      strong.textContent = 'Ready: ' + describe(current) + '.';
      text.append(strong, ' Select Analyze in the Cleaner sidebar.');
    }
  }

  // The in-page scope controls are hidden. Their render hook also re-checks
  // bindings and rewrites chosenReports, so it must not run against host scope.
  renderPills = function () {};
  // Every analysis request from this page uses the exact sidebar selection.
  var basePost = apiPost;
  apiPost = function (url, body) {
    if (url === '/api/analyze' && body) body = Object.assign({}, body, {report_selection: 'exact'});
    return basePost(url, body);
  };
  function request() {
    return {model_paths: chosenModels.map(function (m) { return m.path; }),
            report_paths: chosenReports.map(function (r) { return r.path; })};
  }
  // Refresh after Apply keeps the analyzed scope, including model-only scope.
  reAnalyze = async function (opts) {
    opts = opts || {};
    if (!analyzed || !current || analyzed.key !== current.key || !chosenModels.length)
      return {ok: false, error: 'Scope changed in the Cleaner sidebar. Select Analyze there to refresh.'};
    logEntry('Re-analyzing...', 'info');
    var data = await apiPost('/api/analyze', request());
    if (data.error) { logEntry('Re-analysis failed: ' + data.error, 'err'); return {ok: false, error: data.error}; }
    loadResults(data, true);
    if (opts.showPostDeleteDisclaimer) showPostRefreshDisclaimer();
    logEntry('Analysis refreshed', 'info');
    return {ok: true};
  };

  async function analyze() {
    var scope = current;
    if (!scope || !scope.model) return;
    if (running) {
      post({type: 'smc-analysis', state: 'failed', key: scope.key, error: 'Another analysis is still running.'});
      return;
    }
    running = scope.key; delete banner.dataset.error; render();
    post({type: 'smc-analysis', state: 'running', key: scope.key});
    var error = '';
    try {
      hidePostRefreshDisclaimer();
      var data = await apiPost('/api/analyze', request());
      if (data.error) error = data.error;
      else if (!current || current.key !== scope.key) error = 'Scope changed during analysis. Select Analyze again.';
      else { loadResults(data); analyzed = scope; }
    } catch (err) {
      error = 'Analysis failed: ' + (err && err.message ? err.message : err);
    } finally {
      running = null;
    }
    if (error) banner.dataset.error = error; else delete banner.dataset.error;
    render();
    post({type: 'smc-analysis', state: error ? 'failed' : 'done', key: scope.key, error: error || undefined});
  }

  function valid(scope) {
    function artifact(row) { return row && typeof row.path === 'string' && typeof row.name === 'string'; }
    return scope && typeof scope.key === 'string' && Array.isArray(scope.reports) && scope.reports.every(artifact)
      && (scope.model === null || artifact(scope.model)) && Number.isInteger(scope.total);
  }
  window.addEventListener('message', function (event) {
    if (event.source !== window.parent || event.origin !== parentOrigin) return;
    var data = event.data;
    if (!data || data.type !== 'smc-host-scope' || !valid(data.scope)) return;
    var previous = current ? current.key : '';
    current = data.scope.model ? data.scope : null;
    if (!current || current.key !== previous || data.analyze) delete banner.dataset.error;
    // The analysis-jobs guard compares these with the request, so a change
    // during a running analysis discards its result instead of showing it.
    chosenModels = current ? [current.model] : [];
    chosenReports = current ? current.reports.slice() : [];
    render();
    if (data.analyze && current) void analyze();
  });
  render();
  post({type: 'smc-page-ready'});
})();
