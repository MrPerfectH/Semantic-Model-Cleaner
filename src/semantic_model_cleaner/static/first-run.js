/* Shared first-run flow: prepare scope, review binding evidence, then analyze. */
(function () {
  'use strict';
  var generation = 0, loadVersion = 0, checkedKey = '', pending = false;
  var projectModels = [], projectReports = [];
  var originalRender = renderPills;
  var originalAnalyze = runAnalyze;
  function key() { return JSON.stringify([chosenModels, chosenReports]); }
  function openSetup() {
    if (window.smcOpenScope) window.smcOpenScope();
    if ($('setupBody').classList.contains('hidden')) $('btnToggleSetup').click();
  }
  function text(parent, tag, value) {
    var el = document.createElement(tag); el.textContent = value; parent.appendChild(el); return el;
  }
  function showBinding(binding) {
    var panel = $('scopeReview'); panel.hidden = false; panel.replaceChildren();
    text(panel, 'h3', 'Review analysis scope');
    text(panel, 'p', binding.selected.length + ' connected Report(s) selected; ' + binding.excluded.length + ' excluded.');
    var list = document.createElement('ul'); list.style.paddingLeft = '18px'; panel.appendChild(list);
    binding.selected.forEach(function (row) { text(list, 'li', 'Selected — ' + row.name + ': ' + row.message); });
    binding.excluded.forEach(function (row) { text(list, 'li', 'Excluded — ' + row.name + ': ' + row.message); });
    text(panel, 'p', 'Only selected Reports are checked. Other Reports may use these items. Analysis limitations are identified during analysis; this scope review does not establish complete coverage.');
    if (!binding.selected.length) text(panel, 'p', 'Add connected Reports below, or choose a different Semantic Model.');
  }
  async function review() {
    var currentKey = key();
    if (currentKey === checkedKey) return !pending;
    var version = ++generation; pending = true; $('btnAnalyze').disabled = true;
    if (chosenModels.length !== 1) {
      pending = false; checkedKey = currentKey; $('scopeReview').hidden = true; return false;
    }
    $('scopeReview').hidden = false; $('scopeReview').textContent = 'Checking connected Reports…';
    try {
      var data = await apiPost('/api/scope', {model_paths: chosenModels.map(function (m) { return m.path; }), report_paths: chosenReports.map(function (r) { return r.path; })});
      if (version !== generation || currentKey !== key()) return false;
      if (data.error) throw new Error(data.error);
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
  renderPills = function () { ++loadVersion; originalRender(); review(); };
  runAnalyze = async function () {
    if (pending) return;
    if (await review() && chosenModels.length === 1 && chosenReports.length) await originalAnalyze();
  };
  $('btnAnalyze').onclick = runAnalyze;
  window.smcOpenProject = function () { openSetup(); openExplorer('project'); };
  function chooseModel() {
    chosenModels = projectModels.filter(function (m) { return m.path === $('projectModelSelect').value; });
    chosenReports = projectReports.slice(); checkedKey = ''; renderPills();
  }
  function propose(data) {
    projectModels = data.models || []; projectReports = data.reports || [];
    var choice = $('projectModelChoice'), select = $('projectModelSelect');
    select.replaceChildren(); text(select, 'option', 'Choose a Semantic Model…').value = '';
    projectModels.forEach(function (m) { var option = text(select, 'option', m.name + ' — ' + m.path); option.value = m.path; });
    choice.hidden = projectModels.length < 2;
    chosenModels = projectModels.length === 1 ? projectModels.slice() : [];
    chosenReports = chosenModels.length ? projectReports.slice() : []; checkedKey = ''; renderPills();
    if (projectModels.length > 1) $('projectStatus').textContent = 'Multiple Semantic Models found. Choose one to review its connected Reports.';
  }
  $('projectModelSelect').onchange = chooseModel;
  function beginLoad() {
    var version = ++loadVersion;
    ++generation; pending = false; checkedKey = '';
    chosenModels = []; chosenReports = []; originalRender();
    $('scopeReview').hidden = true; $('projectModelChoice').hidden = true;
    return version;
  }
  window.smcDiscoverProject = async function (path) {
    var version = beginLoad();
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
  // Offer a choice for ambiguous startup roots instead of taking the first model.
  if (initialConfig.availableModels.length > 1) {
    propose({models:initialConfig.availableModels, reports:initialConfig.availableReports});
  } else if (chosenModels.length) {
    chosenReports = initialConfig.availableReports.slice(); review();
  }
})();
