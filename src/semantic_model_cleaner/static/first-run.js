/* Shared first-run flow: prepare connected Report scope, then analyze. */
(function () {
  'use strict';
  var generation = 0, loadVersion = 0, checkedKey = '', pending = false;
  var projectModels = [], projectReports = [], projectRoot = initialConfig.defaultRoot;
  var originalRender = renderPills;
  var originalAnalyze = runAnalyze;
  var previousModel = '', reviewCandidates = null;
  function modelOnly() { return !!($('scopeModelOnly') && $('scopeModelOnly').checked); }
  function key() { return JSON.stringify([chosenModels, chosenReports, modelOnly()]); }
  function openSetup() {
    if (window.smcOpenScope) window.smcOpenScope();
    if ($('setupBody').classList.contains('hidden')) $('btnToggleSetup').click();
  }
  function text(parent, tag, value) {
    var el = document.createElement(tag); el.textContent = value; parent.appendChild(el); return el;
  }
  function showBinding(binding) {
    var panel = $('scopeReview'); panel.replaceChildren();
    panel.hidden = false;
    text(panel, 'p', chosenModels.length ? chosenModels[0].name + ' · ' + binding.selected.length + ' connected report(s) selected.' : 'Choose a semantic model.');
    if (!binding.selected.length) text(panel, 'p', modelOnly() ? 'Model-only scope: report usage is not checked.' : 'Choose connected or separate report folders, or explicitly select model-only analysis.');
    if (window.smcRenderScopeSteps) window.smcRenderScopeSteps();
  }
  async function review() {
    var currentKey = key();
    if (currentKey === checkedKey) return !pending;
    var version = ++generation; pending = true; $('btnAnalyze').disabled = true;
    if (chosenModels.length !== 1) {
      pending = false; checkedKey = currentKey; $('scopeReview').hidden = true; return false;
    }
    if (modelOnly()) { pending = false; chosenReports = []; checkedKey = key(); originalRender(); $('btnAnalyze').disabled = false; showBinding({selected: []}); return true; }
    $('scopeReview').hidden = false; $('scopeReview').textContent = 'Checking connected Reports…';
    try {
      var data = await apiPost('/api/scope', {model_paths: chosenModels.map(function (m) { return m.path; }), report_paths: (reviewCandidates || chosenReports).map(function (r) { return r.path; })});
      if (version !== generation || currentKey !== key()) return false;
      if (data.error) throw new Error(data.error);
      reviewCandidates = null;
      chosenReports = data.reportBinding.selected.map(function (r) { return {path:r.path, name:r.name}; });
      checkedKey = key(); pending = false; originalRender(); showBinding(data.reportBinding);
      return chosenReports.length > 0;
    } catch (error) {
      if (version === generation) {
        pending = false; $('scopeReview').textContent = 'Unable to review scope: ' + error.message + ' Choose another folder or retry Analyze.';
        $('btnAnalyze').disabled = false;
      }
      return false;
    }
  }
  renderPills = function () {
    var selectedModel = chosenModels.map(function (m) { return m.path; }).join('|');
    if (previousModel && previousModel !== selectedModel) {
      chosenReports = []; checkedKey = ''; reviewCandidates = projectReports.slice();
      if ($('scopeModelOnly')) $('scopeModelOnly').checked = false;
    }
    previousModel = selectedModel;
    ++loadVersion; originalRender(); review();
    if (modelOnly() && chosenModels.length === 1 && !pending) $('btnAnalyze').disabled = false;
    if (window.smcRenderScopeSteps) window.smcRenderScopeSteps();
  };
  runAnalyze = async function () {
    if (pending) return;
    if (await review() && chosenModels.length === 1 && (chosenReports.length || modelOnly())) await originalAnalyze();
  };
  $('btnAnalyze').onclick = runAnalyze;
  window.smcOpenProject = function () { openSetup(); openExplorer('project'); };
  function chooseModel() {
    chosenModels = projectModels.filter(function (m) { return m.path === $('projectModelSelect').value; });
    chosenReports = []; checkedKey = ''; reviewCandidates = projectReports.slice(); renderPills();
  }
  function propose(data) {
    projectModels = data.models || []; projectReports = data.reports || [];
    if (data.workspace) projectRoot = data.workspace;
    var choice = $('projectModelChoice'), select = $('projectModelSelect');
    select.replaceChildren(); text(select, 'option', 'Choose a Semantic Model…').value = '';
    projectModels.forEach(function (m) { var option = text(select, 'option', m.name + ' — ' + m.path); option.value = m.path; });
    choice.hidden = projectModels.length === 0;
    chosenModels = projectModels.length === 1 ? projectModels.slice() : [];
    select.value = chosenModels.length ? chosenModels[0].path : '';
    chosenReports = chosenModels.length ? projectReports.slice() : []; checkedKey = ''; renderPills();
    if (projectModels.length > 1) $('projectStatus').textContent = 'Multiple Semantic Models found. Choose one to review its connected Reports.';
  }
  $('projectModelSelect').onchange = chooseModel;
  function beginLoad() {
    var version = ++loadVersion;
    ++generation; pending = false; checkedKey = '';
    // Keep the prior identity until discovery resolves, so a new model resets explicit mode.
    chosenModels = []; chosenReports = []; reviewCandidates = null; originalRender();
    $('scopeReview').hidden = true; $('projectModelChoice').hidden = true;
    return version;
  }
  window.smcDiscoverProject = async function (path) {
    var version = beginLoad();
    projectRoot = path;
    openSetup(); $('projectStatus').textContent = 'Finding Semantic Models and Reports…';
    try {
      var data = await apiPost('/api/discover', {model_roots:[path], report_roots:[path]});
      if (version !== loadVersion) return;
      if (data.error) throw new Error(data.error);
      $('projectStatus').textContent = 'Project: ' + path;
      propose(data);
      if (!projectModels.length) $('projectStatus').textContent = 'No supported Semantic Model found. Choose a Power BI Project folder containing a .SemanticModel folder with a TMDL definition. A .pbix file cannot be opened here: save it as a Power BI Project in Power BI Desktop first. You can also choose model and report folders separately below.';
      if ((data.modelExclusions || []).length) $('projectStatus').textContent += ' ' + data.modelExclusions.map(function (m) { return m.name + ': ' + m.message; }).join(' ');
    } catch (error) { if (version !== loadVersion) return; $('projectStatus').textContent = 'Could not open this Power BI Project: ' + error.message + ' Choose another folder or use the manual controls below.'; }
  };
  var loadingDemo = false;
  window.smcLoadDemo = async function () {
    if (loadingDemo) return;
    var version = beginLoad();
    loadingDemo = true; openSetup(); $('btnLoadDemo').disabled = true;
    $('projectStatus').textContent = 'Preparing a disposable demo…';
    try {
      var data = await apiPost('/api/demo', {});
      if (version !== loadVersion) return;
      if (data.error) throw new Error(data.error);
      $('projectStatus').textContent = 'Demo ready. Review the Semantic Model and connected Reports, then select Analyze. The demo is a disposable copy.';
      propose(data);
    } catch (error) { if (version !== loadVersion) return; $('projectStatus').textContent = 'Could not load the demo: ' + error.message + ' Try again or open a Power BI Project.'; }
    finally { loadingDemo = false; $('btnLoadDemo').disabled = false; }
  };
  $('btnLoadDemo').onclick = window.smcLoadDemo;
  $('btnRefreshProject').onclick = function () { window.smcDiscoverProject(projectRoot); };
  // Always populate folder scope, including a sole model and empty roots.
  propose({models:initialConfig.availableModels, reports:initialConfig.availableReports});
  if (!projectModels.length) {
    $('projectStatus').textContent = 'No supported Semantic Model found in ' + projectRoot + '. Refresh folder after adding files, or choose a Power BI Project folder.';
  } else if (projectModels.length === 1) {
    $('projectStatus').textContent = 'Project: ' + projectRoot;
  }
})();
