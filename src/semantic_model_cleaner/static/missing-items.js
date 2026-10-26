/* Reports screen: what is missing from the model.
 * Leads with errors (broken fields in visuals, grouped by the missing table,
 * column or measure), then offers a human-reviewed fix per item. Grouping is
 * presentation-only; every fix goes through the reviewed-plan dialog. */
(function () {
  'use strict';
  var host = $('missingItemsHost'); if (!host) return;
  var style = document.createElement('style');
  style.textContent = [
    '.mi-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin:12px 0 16px}',
    '.mi-kpi{border:1px solid var(--border);border-radius:10px;padding:12px 14px;background:#fff;display:flex;flex-direction:column;gap:4px}',
    '.mi-kpi strong{font-size:26px;line-height:1.1}.mi-kpi span{font-size:12.5px;color:var(--text-light)}',
    '.mi-kpi.bad strong{color:#b91c1c}.mi-kpi.good strong{color:#15803d}.mi-kpi .btn{align-self:flex-start;margin-top:4px}',
    '.mi-tools{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 8px}.mi-tools h3{margin:0;font-size:15px;flex:1}',
    '.mi-tools label{font-size:12.5px;display:flex;gap:6px;align-items:center}',
    '.mi-list{border:1px solid var(--border);border-radius:10px;background:#fff;overflow:hidden}',
    '.mi-cols,.mi-head{display:grid;grid-template-columns:minmax(220px,1.5fr) 150px minmax(150px,1fr) minmax(170px,1fr) 92px;gap:12px;align-items:center;padding:10px 14px}',
    '.mi-cols{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;color:var(--text-light);border-bottom:1px solid var(--border-soft);background:#f8fafc}',
    '.mi-row+.mi-row{border-top:1px solid var(--border-soft)}',
    '.mi-head{width:100%;border:0;background:none;text-align:left;font:inherit;color:inherit;cursor:pointer}.mi-head:hover,.mi-row.open .mi-head{background:#f8fafc}',
    '.mi-head>span{min-width:0;overflow-wrap:anywhere}.mi-name{font-weight:650}.mi-sub{font-size:12px;color:var(--text-light)}',
    '.mi-kind{display:inline-block;font-size:10.5px;font-weight:700;padding:1px 7px;border-radius:99px;margin-right:6px;vertical-align:1px}',
    '.mi-kind.table{background:#ede9fe;color:#5b21b6}.mi-kind.column{background:#e0f2fe;color:#075985}.mi-kind.measure{background:#fce7f3;color:#9d174d}.mi-kind.reportMeasure{background:#fef3c7;color:#92400e}',
    '.mi-bar{height:5px;background:#f1f5f9;border-radius:3px;overflow:hidden;margin-top:4px}.mi-bar i{display:block;height:100%;background:#dc2626}',
    '.mi-tag{font-size:11px;background:#f1f5f9;color:var(--text-light);border-radius:99px;padding:1px 7px}',
    '.mi-open{justify-self:end}.mi-body{display:grid;grid-template-columns:minmax(220px,1fr) minmax(320px,1.3fr);gap:18px;padding:6px 14px 16px;background:#f8fafc}',
    '.mi-where{font-size:13px}.mi-where h4,.mi-fix h4{margin:0 0 6px;font-size:13px}.mi-where details{margin:3px 0}.mi-where summary{cursor:pointer}',
    '.mi-where ul{margin:3px 0 3px 18px;padding:0}.mi-where li{margin:1px 0}.mi-muted{color:var(--text-light)}',
    '.mi-fix{display:grid;gap:8px;font-size:13px}.mi-fix p{margin:0}',
    '.mi-fixbox{display:grid;gap:8px;padding:12px;border:1px solid var(--primary-border);border-radius:9px;background:var(--primary-soft)}',
    '.mi-fixbox select{max-width:100%;padding:6px 8px;border:1px solid #94a3b8;border-radius:6px;font:inherit;background:#fff}',
    '.mi-actions{display:flex;flex-wrap:wrap;gap:8px}.mi-note{font-size:12px;color:var(--text-light)}',
    '.mi-empty{padding:18px 14px;color:var(--text-light)}',
    '.mi-other{margin-top:16px}.mi-other h3{margin:0 0 8px;font-size:15px}',
    '.mi-other-row{display:grid;grid-template-columns:minmax(200px,1fr) 70px minmax(240px,2fr) auto;gap:12px;align-items:center;padding:9px 14px;font-size:13px}',
    '.mi-other-row+.mi-other-row{border-top:1px solid var(--border-soft)}',
    '#reportFindingRowsHeading{margin:20px 0 4px;font-size:15px}.mi-rows-note{margin:0 0 8px;font-size:12px;color:var(--text-light)}',
    '@media (max-width:900px){.mi-cols{display:none}.mi-head{grid-template-columns:1fr auto}.mi-head>span:nth-child(2),.mi-head>span:nth-child(3),.mi-head>span:nth-child(4){display:none}.mi-body{grid-template-columns:1fr}}'
  ].join('');
  document.head.appendChild(style);

  var data = {items: [], itemCount: 0, referenceCount: 0, visibleVisualCount: 0, reportCount: 0};
  var open = null, visibleOnly = false, choices = {};
  var KIND = {table: 'Table', column: 'Column', measure: 'Measure', reportMeasure: 'Report measure'};
  function n(value) { return Number(value || 0).toLocaleString(); }
  function plural(count, word) { return n(count) + ' ' + word + (count === 1 ? '' : 's'); }

  // Counts follow the report filter: an item seen through one report shows that report's references.
  function scoped(item) {
    var reports = reportIssueReportFilter === '__all__' ? item.reports
      : item.reports.filter(function (r) { return (r.reportPath || r.report) === reportIssueReportFilter; });
    var total = 0, visible = 0;
    reports.forEach(function (r) { r.pages.forEach(function (p) { total += p.count; if (!p.hidden) visible += p.count; }); });
    return {reports: reports, total: total, visible: visible};
  }
  function rows() {
    var search = ($('filterSearch').value || '').toLowerCase();
    return data.items.map(function (item) { return {item: item, scope: scoped(item)}; })
      .filter(function (row) { return row.scope.total && (!visibleOnly || row.scope.visible)
        && (!search || (row.item.label + ' ' + row.item.fields.map(function (f) { return f.name; }).join(' ')).toLowerCase().includes(search)); })
      .sort(function (a, b) { return (!a.scope.visible - !b.scope.visible) || b.scope.total - a.scope.total || a.item.label.localeCompare(b.item.label); });
  }
  function leftoverCount() { return allReportIssues.filter(isReportIssueCleanup).length; }
  function otherIssues() { return allReportIssues.filter(function (i) { return !i.missingItemKey && !isReportIssueCleanup(i); }); }

  function summary() {
    if (!allAnalyzedReports.length && !allReportIssues.length) return 'No reports were analyzed in this scope, so report errors were not checked.';
    if (!data.itemCount) return 'No broken fields: every visual in the analyzed reports points at something that exists in the model.';
    var sorted = data.items.map(function (i) { return i.totalCount; }).sort(function (a, b) { return b - a; });
    var top = Math.round(sorted.slice(0, 3).reduce(function (a, b) { return a + b; }, 0) / (data.referenceCount || 1) * 100);
    var lead = data.visibleVisualCount
      ? plural(data.visibleVisualCount, 'visual') + ' on visible pages show broken fields'
      : 'Broken fields appear only on hidden pages or hidden visuals';
    return lead + ' across ' + plural(data.reportCount, 'report') + '. They come from ' + plural(data.itemCount, 'missing model item')
      + (data.itemCount > 3 ? '. Fixing the top 3 resolves ' + top + '% of the broken references.' : '.');
  }

  // ---- fix forms (human-reviewed; nothing is written until the plan dialog is applied) ----
  function modelFields(kind) {
    return allItems.filter(function (i) { return i.sourceKind !== 'report' && (kind === 'measure' ? i.type === 'Measure' : /Column/.test(i.type)); })
      .map(function (i) { return {table: i.table, name: i.name}; })
      .sort(function (a, b) { return a.table.localeCompare(b.table) || a.name.localeCompare(b.name); });
  }
  function tableFieldNames(table) {
    var t = allTables.find(function (x) { return x.name === table; }); if (!t) return [];
    return (t.items || []).map(function (i) { return String(i.name).toLowerCase(); });
  }
  function suggestionValue(item) {
    var s = item.suggestion; if (!s) return '';
    if (item.kind === 'table') return allTables.some(function (t) { return t.name === s.table; }) ? s.table : '';
    var value = s.table + '\u0000' + s.name;
    return modelFields(item.kind).some(function (f) { return f.table + '\u0000' + f.name === value; }) ? value : '';
  }
  function fixHtml(item) {
    if (item.kind === 'reportMeasure') return '<p class="mi-note">This measure is defined in the report, not the model. Add or rename it in Power BI Desktop, then analyze again.</p>';
    var chosen = choices[item.key] || '', suggested = suggestionValue(item), options;
    if (item.kind === 'table') {
      options = allTables.map(function (t) { return t.name; }).sort(function (a, b) { return a.localeCompare(b); })
        .map(function (name) { return '<option value="' + esc(name) + '"' + (name === chosen ? ' selected' : '') + '>' + esc(name) + '</option>'; }).join('');
    } else {
      var groups = {};
      modelFields(item.kind).forEach(function (f) { (groups[f.table] = groups[f.table] || []).push(f); });
      options = Object.keys(groups).map(function (table) {
        return '<optgroup label="' + esc(table) + '">' + groups[table].map(function (f) {
          var value = f.table + '\u0000' + f.name;
          return '<option value="' + esc(value) + '"' + (value === chosen ? ' selected' : '') + '>' + esc(f.table + '[' + f.name + ']') + '</option>';
        }).join('') + '</optgroup>';
      }).join('');
    }
    var what = item.kind === 'table' ? 'table' : item.kind;
    var html = '<div class="mi-fixbox"><label><b>Point these references at another ' + what + '</b><br><select data-mi-choice="' + esc(item.key) + '"><option value="">Choose a ' + what + ' in the model…</option>' + options + '</select></label>';
    if (suggested && suggested !== chosen) {
      var s = item.suggestion;
      html += '<div class="mi-note">Closest name in the model: <b>' + esc(item.kind === 'table' ? s.table : s.table + '[' + s.name + ']') + '</b>' + (s.confidence ? ' (' + esc(s.confidence) + ' confidence)' : '')
        + '. This is a guess from names only. <button type="button" class="btn btn-secondary btn-sm" data-mi-suggest="' + esc(item.key) + '">Use it</button></div>';
    }
    if (item.kind === 'table' && chosen) {
      var names = tableFieldNames(chosen), fields = item.fields.map(function (f) { return f.name; });
      var missing = fields.filter(function (f) { return names.indexOf(f.toLowerCase()) < 0; });
      html += '<div class="mi-note">' + (fields.length - missing.length) + ' of ' + fields.length + ' fields used from ' + esc(item.table) + ' exist in ' + esc(chosen) + ' with the same name.'
        + (missing.length ? ' These stay broken and will show as missing columns or measures afterwards: ' + missing.slice(0, 8).map(esc).join(', ') + (missing.length > 8 ? ' and ' + (missing.length - 8) + ' more' : '') + '.' : '') + '</div>';
    }
    html += '<div class="mi-actions"><button type="button" class="btn btn-primary btn-sm" data-mi-review="' + esc(item.key) + '"' + (chosen ? '' : ' disabled') + '>Review change…</button></div>'
      + '<div class="mi-note">Only report files change; the model does not. You see every file before anything is written.</div></div>';
    return html;
  }
  function operationFor(item) {
    var chosen = choices[item.key]; if (!chosen) return null;
    if (item.kind === 'table') return {kind: 'report_repair', table_renames: [{table: item.table, target_table: chosen}]};
    var parts = chosen.split('\u0000'), entry = {table: item.table, name: item.name, target_table: parts[0], target_name: parts[1]};
    return item.kind === 'measure' ? {kind: 'report_repair', measure_renames: [entry]} : {kind: 'report_repair', column_renames: [entry]};
  }

  function explain(item) {
    if (item.kind === 'table') return 'The table <b>' + esc(item.table) + '</b> is not in the model. Visuals still use ' + plural(item.fields.length, 'field') + ' from it.';
    if (item.kind === 'reportMeasure') return 'The report measure <b>' + esc(item.name) + '</b> is no longer defined in the report.';
    return 'The ' + item.kind + ' <b>' + esc(item.name) + '</b> is not in table <b>' + esc(item.table) + '</b>.';
  }
  function whereHtml(scope) {
    return '<div class="mi-where"><h4>Where it is used</h4>' + scope.reports.map(function (r) {
      return '<details' + (scope.reports.length === 1 ? ' open' : '') + '><summary>' + esc(r.report) + ' <span class="mi-muted">· ' + n(r.count) + '</span></summary><ul>'
        + r.pages.map(function (p) { return '<li>' + esc(p.page || 'Report level') + (p.hidden ? ' <span class="mi-tag">hidden page</span>' : '') + ' <span class="mi-muted">· ' + n(p.count) + '</span></li>'; }).join('') + '</ul></details>';
    }).join('') + '</div>';
  }

  function render() {
    var list = rows(), max = Math.max.apply(null, list.map(function (r) { return r.scope.total; }).concat([1]));
    var leftovers = leftoverCount(), others = otherIssues();
    $('reportsFindingSummary').textContent = summary();
    var html = '<div class="mi-kpis">'
      + '<div class="mi-kpi ' + (data.visibleVisualCount ? 'bad' : 'good') + '"><strong>' + n(data.visibleVisualCount) + '</strong><span>visuals on visible pages show broken fields</span></div>'
      + '<div class="mi-kpi ' + (data.itemCount ? 'bad' : 'good') + '"><strong>' + n(data.itemCount) + '</strong><span>missing tables, columns or measures cause them</span></div>'
      + (others.length ? '<div class="mi-kpi"><strong>' + n(others.length) + '</strong><span>other report problems</span><button type="button" class="btn btn-secondary btn-sm" data-mi-goto="other">Show</button></div>' : '')
      + '<div class="mi-kpi"><strong>' + n(leftovers) + '</strong><span>leftover references, safe to remove. Nothing on screen uses them.</span>'
      + (leftovers ? '<button type="button" class="btn btn-secondary btn-sm" data-mi-leftovers>Remove leftovers…</button>' : '') + '</div></div>';
    if (data.itemCount) {
      var reports = reportInventoryRows();
      html += '<div class="mi-tools"><h3>What is missing from the model</h3>'
        + '<label><input type="checkbox" data-mi-visible' + (visibleOnly ? ' checked' : '') + '> Only items on visible pages</label>'
        + '<select class="report-health-select" data-mi-report aria-label="Report"><option value="__all__">All ' + plural(reports.length, 'report') + '</option>'
        + reports.map(function (r) { return '<option value="' + esc(r.id) + '"' + (r.id === reportIssueReportFilter ? ' selected' : '') + '>' + esc(reportReferenceLabel(r.id)) + '</option>'; }).join('') + '</select></div>'
        + '<div class="mi-list" role="list"><div class="mi-cols" aria-hidden="true"><span>Missing item</span><span>Broken references</span><span>Where</span><span>Closest name in model</span><span></span></div>'
        + (list.length ? list.map(function (row) {
          var item = row.item, scope = row.scope, isOpen = open === item.key, s = item.suggestion;
          var head = '<button type="button" class="mi-head" data-mi-open="' + esc(item.key) + '" aria-expanded="' + isOpen + '">'
            + '<span><span class="mi-kind ' + item.kind + '">' + KIND[item.kind] + '</span><span class="mi-name">' + esc(item.kind === 'table' ? item.table : item.name) + '</span>'
            + '<div class="mi-sub">' + (item.kind === 'table' ? plural(item.fields.length, 'field') + ' used from it' : 'in table ' + esc(item.table)) + '</div></span>'
            + '<span><b>' + n(scope.total) + '</b><div class="mi-bar"><i style="width:' + Math.max(2, scope.total / max * 100) + '%"></i></div></span>'
            + '<span class="mi-sub">' + plural(scope.reports.length, 'report') + ' · ' + (scope.visible ? n(scope.visible) + ' on visible pages' : '<span class="mi-tag">hidden pages only</span>') + '</span>'
            + '<span class="mi-sub">' + (s ? esc(item.kind === 'table' ? s.table : s.table + '[' + s.name + ']') : '—') + '</span>'
            + '<span class="mi-open btn btn-secondary btn-sm">' + (isOpen ? 'Close' : 'Details') + '</span></button>';
          if (!isOpen) return '<div class="mi-row" role="listitem">' + head + '</div>';
          return '<div class="mi-row open" role="listitem">' + head + '<div class="mi-body">' + whereHtml(scope)
            + '<div class="mi-fix"><p>' + explain(item) + '</p><div class="mi-actions"><button type="button" class="btn btn-secondary btn-sm" data-mi-rows="' + esc(item.key) + '">Show affected visuals</button></div>'
            + '<h4>Fix it</h4>' + fixHtml(item) + '</div></div></div>';
        }).join('') : '<div class="mi-empty">No missing items match the search, report or visible-pages filter.</div>') + '</div>';
    }
    if (others.length) {
      var byType = {};
      others.forEach(function (i) { (byType[i.issueType] = byType[i.issueType] || []).push(i); });
      html += '<section class="mi-other" id="missingItemsOther"><h3>Other report problems</h3><div class="mi-list">'
        + Object.keys(byType).sort(function (a, b) { return byType[b].length - byType[a].length; }).map(function (type) {
          var sample = byType[type][0];
          return '<div class="mi-other-row"><b>' + esc(reportIssueTypeLabel(type)) + '</b><span>' + n(byType[type].length) + '</span><span class="mi-sub">' + esc(sample.message || '') + '</span>'
            + '<button type="button" class="btn btn-secondary btn-sm" data-mi-type="' + esc(type) + '">Show rows</button></div>';
        }).join('') + '</div></section>';
    }
    host.innerHTML = html;
    wire();
  }
  function showRows() {
    currentPageByView.reports = 1; reportIssueGroupFilter = 'all'; reportIssuePageFilter = '__all__'; reportIssueRootCauseFilter = '__all__';
    applyReportIssueFilters();
    var heading = $('reportFindingRowsHeading'), section = $('reportsTableSection');
    if (heading && section) section.scrollTo({top: heading.offsetTop - 8, behavior: 'smooth'});
  }
  function wire() {
    host.querySelectorAll('[data-mi-open]').forEach(function (b) { b.onclick = function () { open = open === b.dataset.miOpen ? null : b.dataset.miOpen; render(); }; });
    var visible = host.querySelector('[data-mi-visible]'); if (visible) visible.onchange = function () { visibleOnly = visible.checked; render(); };
    var report = host.querySelector('[data-mi-report]');
    if (report) report.onchange = function () { reportIssueReportFilter = report.value; reportIssuePageFilter = '__all__'; currentPageByView.reports = 1; applyReportIssueFilters(); };
    host.querySelectorAll('[data-mi-choice]').forEach(function (s) { s.onchange = function () { choices[s.dataset.miChoice] = s.value; render(); }; });
    host.querySelectorAll('[data-mi-suggest]').forEach(function (b) { b.onclick = function () {
      var item = data.items.find(function (i) { return i.key === b.dataset.miSuggest; }); choices[item.key] = suggestionValue(item); render(); }; });
    host.querySelectorAll('[data-mi-review]').forEach(function (b) { b.onclick = function () {
      var item = data.items.find(function (i) { return i.key === b.dataset.miReview; }), op = item && operationFor(item);
      if (op && window.smcReviewOperations) window.smcReviewOperations([op], 'Fix broken references to ' + item.label);
    }; });
    host.querySelectorAll('[data-mi-rows]').forEach(function (b) { b.onclick = function () { reportIssueMissingItemFilter = b.dataset.miRows; reportIssueTypeFilter = '__all__'; showRows(); }; });
    host.querySelectorAll('[data-mi-type]').forEach(function (b) { b.onclick = function () { reportIssueTypeFilter = b.dataset.miType; reportIssueMissingItemFilter = '__all__'; showRows(); }; });
    var leftovers = host.querySelector('[data-mi-leftovers]'); if (leftovers) leftovers.onclick = function () { $('btnCleanAllCleanup').click(); };
    var goto = host.querySelector('[data-mi-goto]'); if (goto) goto.onclick = function () { var target = $('missingItemsOther'); if (target) $('reportsTableSection').scrollTo({top: target.offsetTop - 8, behavior: 'smooth'}); };
  }

  var originalResults = setResultsData;
  setResultsData = function (payload) {
    var result = originalResults.apply(this, arguments);
    data = payload.missingItems || {items: [], itemCount: 0, referenceCount: 0, visibleVisualCount: 0, reportCount: 0};
    open = null; choices = {}; reportIssueMissingItemFilter = '__all__'; reportIssueTypeFilter = '__all__';
    render();
    return result;
  };
  var originalTable = renderReportsTable;
  renderReportsTable = function () { var result = originalTable.apply(this, arguments); render(); return result; };
  window.smcMissingItems = {summary: summary, operationFor: operationFor, scoped: scoped};
})();
