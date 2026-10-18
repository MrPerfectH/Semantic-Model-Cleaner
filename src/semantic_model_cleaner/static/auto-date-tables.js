/* Optional summary action: review and remove unused auto-date tables.
   The server decides which tables can go; removal uses the shared reviewed-plan
   workflow, which checks the files again before preview and before apply. */
(function () {
  'use strict';
  var latest = null, sequence = 0, byTable = {};
  var dialog = document.createElement('dialog');
  dialog.className = 'object-review autodate-review'; dialog.setAttribute('aria-labelledby', 'autoDateTitle');
  dialog.innerHTML = '<header><h2 id="autoDateTitle">Auto-date tables</h2><button type="button" class="btn btn-secondary btn-sm" id="autoDateClose" aria-label="Close auto-date tables">Close</button></header>'
    + '<div class="object-review-content" id="autoDateBody"></div>'
    + '<footer><span class="object-note" id="autoDateStatus"></span><button type="button" class="btn btn-primary" id="autoDatePreview" disabled>Preview removal</button></footer>';
  document.body.appendChild(dialog);
  $('autoDateClose').onclick = function () { dialog.close(); };

  function counts(result) {
    return 'Auto-date tables found: ' + result.found + '. ' + result.removable_count + ' can be removed; ' + result.blocked_count + ' cannot.';
  }
  function what(entry) {
    if (entry.kind === 'template') return 'Template table that Power BI copies for new auto-date tables. It is not linked to a column.';
    if (entry.date_column) return 'Date hierarchy for ' + entry.date_column + '.';
    return entry.label + '.';
  }
  function removableRow(entry) {
    var template = entry.kind === 'template';
    var removes = !template
      ? 'Removes the hidden table, its relationship to ' + entry.date_column + ' and the hierarchy link on that column. ' + entry.date_column + ' stays.'
      : 'Removes the hidden template table, only together with every other auto-date table. This is a conservative restriction: removing the template while auto-date tables stay has not been validated in Power BI Desktop.';
    return '<li><label class="autodate-choice"><input type="checkbox" data-autodate-table="' + esc(entry.table) + '"' + (template ? ' data-autodate-template' : '') + ' checked> '
      + '<span><strong>' + esc(what(entry)) + '</strong><span class="object-note">' + esc(removes) + '</span>'
      + (template ? '<span class="object-note autodate-template-note" role="status"></span>' : '')
      + '<code>' + esc(entry.table) + '</code></span></label></li>';
  }
  function blockedRow(entry) {
    return '<li><strong>' + esc(what(entry)) + '</strong> <code>' + esc(entry.table) + '</code><ul class="autodate-blockers">'
      + (entry.blockers || []).map(function (blocker) { return '<li>' + esc(blocker.message) + '</li>'; }).join('') + '</ul></li>';
  }
  function selected() {
    return Array.prototype.slice.call(dialog.querySelectorAll('[data-autodate-table]:checked')).map(function (box) { return box.dataset.autodateTable; });
  }
  function updatePreview() {
    // The server refuses the template while another auto-date table stays; say so before preview.
    var chosen = selected();
    dialog.querySelectorAll('[data-autodate-template]').forEach(function (box) {
      var staying = ((byTable[box.dataset.autodateTable] || {}).requires_tables || []).filter(function (name) { return chosen.indexOf(name) < 0; });
      box.disabled = staying.length > 0;
      if (box.disabled) box.checked = false;
      box.closest('li').querySelector('.autodate-template-note').textContent = staying.length
        ? 'Kept: ' + staying.length + ' other auto-date table(s) stay. Select every auto-date table to remove the template.' : '';
    });
    var count = selected().length;
    $('autoDatePreview').disabled = !count;
    $('autoDatePreview').textContent = count ? 'Preview removal of ' + count + ' table(s)' : 'Preview removal';
  }
  function openReview() {
    var result = latest; if (!result) return;
    byTable = {}; result.tables.forEach(function (entry) { byTable[entry.table] = entry; });
    var removable = result.tables.filter(function (entry) { return entry.removable; });
    var blocked = result.tables.filter(function (entry) { return !entry.removable; });
    var reports = (result.scope && result.scope.reports) || [];
    $('autoDateBody').innerHTML = '<p>' + esc(counts(result)) + '</p>'
      + '<p class="object-note">With Auto date/time on, Power BI Desktop adds a hidden table with a Year/Quarter/Month/Day hierarchy for each date column. '
      + 'This action removes only those generated tables. Your date columns stay in their tables, and visuals can still use them.</p>'
      + (removable.length ? '<h3>Can be removed (' + removable.length + ')</h3><p class="object-note">Nothing in the selected model or reports uses these tables or their date hierarchies.</p>'
        + '<p><button type="button" class="btn btn-link btn-sm" id="autoDateAll">Select all</button> <button type="button" class="btn btn-link btn-sm" id="autoDateNone">Select none</button></p>'
        + '<ul class="autodate-list">' + removable.map(removableRow).join('') + '</ul>' : '')
      + (blocked.length ? '<h3>Cannot be removed (' + blocked.length + ')</h3><ul class="autodate-list">' + blocked.map(blockedRow).join('') + '</ul>' : '')
      + '<p class="object-note">Checked: this model and ' + reports.length + ' selected report(s). Reports that are not selected, Excel and other tools that use the published model were not checked.</p>'
      + (result.time_intelligence_enabled ? '<p class="object-note">Auto date/time stays on for this file. Power BI Desktop can create these tables again. This action does not change that setting.</p>' : '');
    dialog.querySelectorAll('[data-autodate-table]').forEach(function (box) { box.onchange = updatePreview; });
    if ($('autoDateAll')) $('autoDateAll').onclick = function () { dialog.querySelectorAll('[data-autodate-table]').forEach(function (box) { box.checked = true; }); updatePreview(); };
    if ($('autoDateNone')) $('autoDateNone').onclick = function () { dialog.querySelectorAll('[data-autodate-table]').forEach(function (box) { box.checked = false; }); updatePreview(); };
    $('autoDateStatus').textContent = removable.length ? 'Next: a preview shows every file change before anything is written.' : 'No auto-date table can be removed now.';
    updatePreview();
    dialog.showModal();
  }
  $('autoDatePreview').onclick = function () {
    var tables = selected(); if (!tables.length) return;
    dialog.close();
    window.smcReviewOperations([{ kind: 'auto_date_tables', tables: tables }], 'Remove unused auto-date tables');
  };
  function row() {
    var panel = $('resultOverview'), element = $('resultAutoDate');
    if (!element) {
      element = document.createElement('div'); element.id = 'resultAutoDate'; element.className = 'result-autodate-row'; element.hidden = true;
      element.innerHTML = '<span id="resultAutoDateText"></span><button type="button" class="result-context-link" id="resultAutoDateReview">Review and remove unused auto-date tables</button>';
      var anchor = panel.querySelector('.result-context-row');
      panel.insertBefore(element, anchor);
      $('resultAutoDateReview').onclick = openReview;
    }
    return element;
  }
  async function refresh() {
    var element = row(), mine = ++sequence;
    latest = null; element.hidden = true;
    if (chosenModels.length !== 1 || !chosenReports.length) return;
    try {
      var result = await apiPost('/api/auto-date-tables', { model_path: getModelPath(), report_paths: chosenReports.map(function (report) { return report.path; }) });
      if (mine !== sequence || !result || !result.found) return;
      latest = result; $('resultAutoDateText').textContent = counts(result); element.hidden = false;
    } catch (error) { if (mine === sequence) element.hidden = true; }
  }
  var render = window.smcRenderResultOverview;
  window.smcRenderResultOverview = function () { var value = render.apply(this, arguments); refresh(); return value; };
})();
