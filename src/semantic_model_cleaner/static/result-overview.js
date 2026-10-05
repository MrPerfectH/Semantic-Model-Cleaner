/* A snapshot of the analyzed scope, independent of pending setup selections. */
(function () {
  'use strict';
  window.smcRenderResultOverview = function (data) {
    var panel = document.getElementById('resultOverview');
    var limits = data.analysisLimitations || {};
    var safe = data.items.filter(function (item) { return item.deleteSafety === 'Safe'; }).length;
    var review = data.items.filter(function (item) { return item.deleteSafety === 'Review'; }).length;
    var reports = data.reportBinding ? data.reportBinding.selected : chosenReports;
    var issues = (data.reportHealth || {}).totalIssueCount || (data.reportIssues || []).length;
    panel.classList.remove('hidden');
    panel.innerHTML = '<div class="result-overview-heading"><div><span class="result-eyebrow">Analyzed scope</span><h2>' + esc(chosenModels.map(function (m) { return m.name; }).join(', ')) + '</h2></div>'
      + '<button type="button" class="btn btn-secondary btn-sm" id="overviewHistory">Changes &amp; history</button></div>'
      + '<details class="result-scope"><summary>' + reports.length + ' checked Report(s) · inspect scope</summary><ul>' + reports.map(function (r) { return '<li>' + esc(r.name) + ' <span>' + esc(r.path) + '</span></li>'; }).join('') + '</ul></details>'
      + '<div class="result-facts"><div><strong>' + safe + ' Safe · ' + review + ' Review</strong><span>Cleanup Recommendations</span></div>'
      + '<div><strong>' + (limits.distinctCount || 0) + ' distinct limitation(s)</strong><span>' + (limits.coverageComplete === false ? 'Incomplete analysis coverage' : 'No shared coverage gap detected') + '</span></div>'
      + '<div><strong>' + issues + ' Report Health issue(s)</strong><span>Report metadata findings</span></div></div>'
      + '<p><strong>Safe applies to supported scanned metadata in this scope.</strong> Other Reports and Power BI runtime behavior are not verified.</p>'
      + '<p class="result-next">' + (safe ? 'Next: open a candidate to inspect Usage and dependency evidence, then prepare and review the exact file changes.' : 'No Safe cleanup candidates in this scope. Inspect item evidence and any Analysis Limitations before deciding on a change.') + '</p>';
    document.getElementById('overviewHistory').onclick = function () {
      document.getElementById('objectHistoryButton') ? document.getElementById('objectHistoryButton').click() : window.ClassicPlans.history();
    };
  };
})();
