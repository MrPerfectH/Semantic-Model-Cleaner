/* Optional summary action: remove all auto-date tables, or none.
   The server decides for the whole group; there is no per-table choice. Removal
   uses the shared reviewed-plan workflow, which checks every file again before
   preview and before apply. */
(function () {
  'use strict';
  var sequence = 0;
  function row() {
    var panel = $('resultOverview'), element = $('resultAutoDate');
    if (!element) {
      element = document.createElement('div'); element.id = 'resultAutoDate'; element.className = 'result-autodate-row'; element.hidden = true;
      element.innerHTML = '<span id="resultAutoDateText"></span>'
        + '<button type="button" class="result-context-link" id="resultAutoDateRemove" hidden>Preview removal of all auto-date tables</button>'
        + '<details class="result-autodate-why" id="resultAutoDateWhy" hidden><summary>Why</summary><ul id="resultAutoDateReasons"></ul></details>'
        + '<span class="result-autodate-scope" id="resultAutoDateScope"></span>';
      panel.insertBefore(element, panel.querySelector('.result-context-row'));
      $('resultAutoDateRemove').onclick = function () {
        window.smcReviewOperations([{ kind: 'auto_date_tables', remove: 'all' }], 'Remove all auto-date tables');
      };
    }
    return element;
  }
  function show(element, result) {
    var reasons = result.reasons || [], button = $('resultAutoDateRemove');
    $('resultAutoDateText').textContent = result.message;
    // One action for the whole group, offered only when every table can go.
    button.hidden = button.disabled = !result.can_remove_all;
    $('resultAutoDateReasons').innerHTML = reasons.map(function (reason) { return '<li>' + esc(reason) + '</li>'; }).join('');
    $('resultAutoDateWhy').hidden = !reasons.length;
    $('resultAutoDateScope').textContent = result.status === 'none' ? ''
      : result.scope_note + (result.can_remove_all && result.time_intelligence_enabled
        ? ' Auto date/time stays on, so Power BI Desktop can create these tables again.' : '');
    element.hidden = false;
  }
  async function refresh() {
    var element = row(), mine = ++sequence;
    element.hidden = true;
    if (chosenModels.length !== 1) return;
    try {
      var result = await apiPost('/api/auto-date-tables', { model_path: getModelPath(), report_paths: chosenReports.map(function (report) { return report.path; }) });
      if (mine !== sequence || !result || !result.ok || !result.message) return;
      show(element, result);
    } catch (error) { if (mine === sequence) element.hidden = true; }
  }
  var render = window.smcRenderResultOverview;
  window.smcRenderResultOverview = function () { var value = render.apply(this, arguments); refresh(); return value; };
})();
