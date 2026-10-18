/* Report usage is a presentation projection. Raw references and safety stay unchanged. */
(function (root) {
  'use strict';
  function isReportRow(row) { return !!(row && (row.reportPath || row.report)); }
  function describe(state, rows, filtered) {
    var total = rows.filter(isReportRow).length;
    var counts = filtered + ' of ' + total + ' report usage rows match the current filters.';
    var prior = state.loaded ? ' Previous analysis remains below; it is not a result of this attempt.' : '';
    if (state.loading) return {kind:'loading', text:'Loading report usage. Wait for analysis to finish.' + prior, action:''};
    if (state.error) return {kind:'error', text:'Report usage could not be refreshed: ' + state.error + prior + ' Check the selected reports and analyze again.', action:'scope'};
    if (!state.loaded) return {kind:'unloaded', text:'No analysis yet. Choose a semantic model and reports, then select Analyze to see where fields are used.', action:'scope'};
    if (!state.available) return {kind:'unavailable', text:'Report usage data was not returned by this analysis. Analyze again; zero usage has not been established.', action:'scope'};
    if (!state.reports) return {kind:'model-only', text:'No reports were analyzed (model-only scope). Choose reports and analyze to check report usage.', action:'scope'};
    if (!total) return {kind:'empty', text:'No report usage entries were recorded in the analyzed reports. This does not prove that the reports use no fields; check Scan details and analyzer warnings for coverage, or choose other reports and analyze.', action:'scope'};
    if (!filtered) return {kind:'filtered-empty', text:counts + ' Clear filters to show recorded report usage.', action:'clear'};
    return {kind:'ready', text:counts, action:''};
  }
  var api = {isReportRow:isReportRow, describe:describe};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.SmcReportUsage = api;
  if (typeof document === 'undefined') return;

  var state = {loaded:false, available:false, reports:0, loading:false, error:''};
  var section = $('refsTableSection'), table = section.querySelector('table');
  var intro = document.createElement('section'); intro.className = 'reports-intro';
  intro.innerHTML = '<h2>Report usage</h2><p>Fields recorded in the analyzed reports, with report, page and visual details when available. Counts are usage rows, not unique fields or visuals; repeated field uses and stale report entries remain visible. Model items without a report entry are listed in Items.</p><p id="reportUsageStatus" role="status"></p><button type="button" class="btn btn-secondary btn-sm" id="reportUsageScope">Choose reports and analyze</button><button type="button" class="btn btn-secondary btn-sm" id="reportUsageClear">Clear filters</button>';
  section.prepend(intro);
  $('tabRefsCount').hidden = true;
  $('reportUsageScope').onclick = function () { window.smcOpenScope(); };
  $('reportUsageClear').onclick = function () {
    $('filterSearch').value = '';
    ['filterStatus','filterIssue','filterRisk','filterType','filterTable','filterHidden','filterFolder','filterModified','filterSource'].forEach(clearFilterOptions);
    resetPageForDataViews(); applyFilters();
  };
  function renderState() {
    var view = describe(state, allRefs, filteredRefs.length);
    $('reportUsageStatus').textContent = view.text; $('reportUsageStatus').dataset.state = view.kind;
    $('reportUsageScope').hidden = view.action !== 'scope'; $('reportUsageClear').hidden = view.action !== 'clear';
    table.hidden = !state.loaded || !state.available || !filteredRefs.length;
    if (currentView === 'refs') {
      $('inventoryResultCount').textContent = state.loaded && state.available ? filteredRefs.length + ' matching / ' + allRefs.filter(isReportRow).length + ' recorded usage rows' : '';
      if (!filteredRefs.length || !state.loaded || !state.available) $('pageStatus').textContent = view.kind === 'loading' ? 'Loading report usage' : 'No report usage rows shown';
    }
  }
  var oldFilter = filterRefs;
  filterRefs = function () { return oldFilter().filter(isReportRow); };
  var oldCounts = updateFilterCounts;
  updateFilterCounts = function () { oldCounts(); $('tabRefsCount').textContent = ''; };
  var oldPages = updatePageControls;
  updatePageControls = function () { oldPages(); renderState(); };
  var oldRefs = renderRefsTable;
  renderRefsTable = function () { oldRefs(); renderState(); };
  var oldResults = setResultsData;
  setResultsData = function (data) {
    state.loaded = true; state.available = Array.isArray(data.references); state.loading = false; state.error = '';
    var result = oldResults.apply(this, arguments); state.reports = allAnalyzedReports.length;
    renderState(); return result;
  };
  var oldPost = apiPost;
  apiPost = async function (url, data) {
    if (url !== '/api/analyze' || state.loading) return oldPost(url, data);
    state.loading = true; state.error = ''; renderState();
    try {
      var result = await oldPost(url, data);
      if (result.error) state.error = result.error;
      return result;
    } catch (error) { state.error = error.message || 'Connection failed.'; throw error; }
    finally { state.loading = false; renderState(); }
  };
  renderRefsTable();
})(typeof window !== 'undefined' ? window : globalThis);
