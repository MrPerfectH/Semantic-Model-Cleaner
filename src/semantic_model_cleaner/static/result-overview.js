/* Compact analysis context. Existing counters and filters keep their semantics. */
(function () {
  'use strict';
  var buttons = [];
  function updatePressed() {
    var selected = getSelectedValues('filterRisk');
    buttons.forEach(function (button) { button.setAttribute('aria-pressed', String(selected.length === 1 && selected[0] === button.dataset.cleanup)); });
  }
  function initialize(panel) {
    if (panel.dataset.compactReady) return;
    panel.dataset.compactReady = 'true';
    var summary = $('summarySection'), guide = $('resultGuideSection');
    var inventory = ['sumUsed','sumUnused','sumMeasures','sumColumns','sumReviewEntity','sumReviewEvidence'].map(function (id) { return $(id).closest('.rail-row'); });
    var total = $('sumTotal');
    [['sumSafe','Safe'],['sumReview','Review'],['sumCaution','Blocked'],['sumKeep','Keep']].forEach(function (entry) {
      var value = $(entry[0]), row = value.closest('.rail-row'), button = document.createElement('button');
      button.type = 'button'; button.className = 'result-count'; button.dataset.cleanup = entry[1];
      button.title = 'Filter Items by ' + entry[1] + '. ' + cleanupHelpText(entry[1]);
      button.append(document.createTextNode(entry[1] + ' '), value); row.replaceWith(button); buttons.push(button);
      button.onclick = function () {
        var selected = getSelectedValues('filterRisk');
        filterState.filterRisk = selected.length === 1 && selected[0] === entry[1] ? [] : [entry[1]];
        renderFilterDropdownOptions('filterRisk'); switchView('details'); applyFilters();
      };
    });
    summary.replaceChildren.apply(summary, buttons);
    panel.innerHTML = '<div class="result-summary-row"><div id="resultCleanup" aria-label="Cleanup recommendations"></div><details id="resultInventory" class="result-inventory"><summary>Inventory <span id="resultInventoryTotal"></span></summary><div class="result-inventory-body" id="resultInventoryBody"></div></details></div>'
      + '<div class="result-context-row"><span class="result-safety-note">Safe is limited to this analyzed scope.</span><button type="button" class="result-context-link" id="overviewLimitations">Scan details</button><button type="button" class="result-context-link" id="overviewReportFindings" hidden></button><details class="result-scope" id="resultScope"><summary>Scope details</summary><div id="resultScopeBody"></div></details></div>';
    $('resultCleanup').appendChild(summary); $('resultInventoryTotal').append(total, document.createTextNode(' items'));
    inventory.forEach(function (row) { $('resultInventoryBody').appendChild(row); });
    guide.querySelector('.result-guide-title').textContent = 'How to read results';
    guide.querySelector('.result-guide-subtitle').hidden = true;
    panel.querySelector('.result-context-row').appendChild(guide);
    $('overviewLimitations').onclick = function () { switchView('limitations'); };
    $('overviewReportFindings').onclick = function () { switchView('reports'); };
    var originalFilters = applyFilters;
    applyFilters = function () { var result = originalFilters.apply(this, arguments); updatePressed(); return result; };
  }
  window.smcRenderResultOverview = function (data) {
    var panel = $('resultOverview'); initialize(panel); panel.classList.remove('hidden');
    var limits = data.analysisLimitations || {}, reports = data.reportBinding ? data.reportBinding.selected : chosenReports;
    var impacted = !!(limits.affectedItemCount || limits.sharedCount);
    $('overviewLimitations').hidden = !(limits.limitations || []).length;
    $('overviewLimitations').textContent = impacted ? 'Coverage limitations · ' + (limits.affectedItemCount || 0) + ' affected items' + (limits.sharedCount ? ' · ' + limits.sharedCount + ' shared' : '') : 'Scan details';
    $('overviewLimitations').classList.toggle('has-impact', impacted);
    var findings = (data.reportHealth || {}).totalIssueCount || (data.reportIssues || []).length;
    $('overviewReportFindings').hidden = !findings;
    $('overviewReportFindings').textContent = findings + ' report metadata finding(s)';
    $('resultScopeBody').innerHTML = '<p>Analysis checked the following scope. Pending selection changes do not change these results.</p><ul>'
      + chosenModels.map(function (m) { return '<li>Model: ' + esc(m.path) + '</li>'; }).join('')
      + reports.map(function (r) { return '<li>Report: ' + esc(r.name) + ' <span>' + esc(r.path) + '</span></li>'; }).join('') + '</ul>'
      + (!reports.length ? '<p>Model-only analysis: report usage was not checked.</p>' : '')
      + '<p>Other reports and Power BI runtime behavior are not verified. Open an item to inspect usage and dependencies before reviewing any changes.</p>';
    updatePressed();
  };
})();
