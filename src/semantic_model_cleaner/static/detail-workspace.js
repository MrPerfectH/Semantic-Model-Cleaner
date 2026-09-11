/* Stable object workspaces. The analyzer remains the source of classification. */
(function () {
  'use strict';
  var tabs = ['Overview', 'References', 'Dependencies', 'Definition', 'Changes'];
  var activeTabs = { item: 'overview', table: 'overview' };
  var itemTabByType = {};
  var lastItemType = null;
  var tableSearch = '';
  var tableSort = { key: 'name', direction: 1 };
  var returnTo = null;
  var inventoryScroll = 0;
  function card(title, content) { return '<section class="detail-card"><h4>' + esc(title) + '</h4>' + content + '</section>'; }
  function empty(text) { return '<p class="detail-empty">' + esc(text) + '</p>'; }
  function properties(entries) {
    return '<dl class="object-properties">' + entries.filter(function (e) { return e[1] !== undefined && e[1] !== null && e[1] !== ''; }).map(function (e) {
      return '<dt>' + esc(e[0]) + '</dt><dd>' + esc(String(e[1])) + '</dd>';
    }).join('') + '</dl>';
  }
  function createTabs(kind, root) {
    var nav = document.createElement('div'); nav.className = 'object-tabs'; nav.setAttribute('role', 'tablist'); nav.setAttribute('aria-label', kind === 'item' ? 'Item details' : 'Table details');
    nav.innerHTML = tabs.map(function (name) { var key = name.toLowerCase(); return '<button type="button" role="tab" id="' + kind + '-tab-' + key + '" aria-controls="' + kind + '-pane-' + key + '" aria-selected="false" tabindex="-1" data-object-tab="' + key + '">' + name + '</button>'; }).join('');
    root.appendChild(nav);
    tabs.forEach(function (name) { var key = name.toLowerCase(); var pane = document.createElement('div'); pane.id = kind + '-pane-' + key; pane.className = 'object-pane'; pane.setAttribute('role', 'tabpanel'); pane.setAttribute('aria-labelledby', kind + '-tab-' + key); root.appendChild(pane); });
    nav.addEventListener('click', function (event) { var btn = event.target.closest('[data-object-tab]'); if (btn) selectTab(kind, btn.dataset.objectTab); });
    nav.addEventListener('keydown', function (event) {
      var buttons = Array.from(nav.querySelectorAll('button')); var index = buttons.indexOf(document.activeElement); if (index < 0) return;
      var next = event.key === 'ArrowRight' ? (index + 1) % buttons.length : event.key === 'ArrowLeft' ? (index + buttons.length - 1) % buttons.length : event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : -1;
      if (next >= 0) { event.preventDefault(); selectTab(kind, buttons[next].dataset.objectTab); buttons[next].focus(); }
    });
    selectTab(kind, activeTabs[kind]);
  }
  function selectTab(kind, key) {
    if (!tabs.some(function (name) { return name.toLowerCase() === key; })) key = 'overview';
    activeTabs[kind] = key;
    if (kind === 'item' && lastItemType) itemTabByType[lastItemType] = key;
    tabs.forEach(function (name) { var tab = name.toLowerCase(); var btn = $(kind + '-tab-' + tab); if (!btn) return; btn.setAttribute('aria-selected', String(tab === key)); btn.tabIndex = tab === key ? 0 : -1; $(kind + '-pane-' + tab).hidden = tab !== key; });
  }
  function initItem() {
    var section = $('itemDetailSection'); section.classList.add('object-workspace');
    parkDetailModules();
    section.querySelectorAll('.detail-layout,.detail-layout-switcher').forEach(function (node) { node.remove(); });
    var crumbs = document.createElement('nav'); crumbs.id = 'objectItemBreadcrumb'; crumbs.className = 'object-crumbs'; crumbs.setAttribute('aria-label', 'Breadcrumb'); section.insertBefore(crumbs, section.querySelector('.detail-header'));
    var summary = document.createElement('div'); summary.id = 'objectItemSummary'; summary.className = 'object-summary'; section.appendChild(summary);
    createTabs('item', section);
    $('item-pane-overview').innerHTML = '<div class="object-grid"><div class="object-stack" id="objectItemPrimary"></div><aside class="object-stack" id="objectItemProperties"></aside></div>';
    moveDetailNode('detailUsageSection', 'item-pane-references'); moveDetailNode('detailStaleUsageSection', 'item-pane-references');
    moveDetailNode('detailTechnicalPanel', 'item-pane-definition'); moveDetailNode('detailSharedActions', 'item-pane-changes'); moveDetailNode('detailReportMeasureSection', 'item-pane-changes');
    $('detailTechnicalPanel').querySelector('h4').textContent = 'Definition';
    $('detailSharedActions').querySelector('h4').textContent = 'Plan a change';
    $('detailReportMeasureSection').querySelector('h4').textContent = 'Promote report measure to model';
    $('detailBtnSaveDax').textContent = 'Review DAX change';
    ['detailBtnApply', 'tableBtnApply', 'btnApply'].forEach(function (id) { $(id).textContent = 'Review queued changes'; });
    $('detailDaxEditor').setAttribute('aria-label', 'DAX expression');
    ['detailDaxBackup', 'detailMigrateBackup', 'applyBackupCheckbox'].forEach(function (id) { var input = $(id); if (input && input.closest('label')) input.closest('label').hidden = true; });
    $('detailSharedActions').querySelector('.detail-actions').insertAdjacentHTML('afterbegin', '<div class="detail-action-group hidden" id="objectColumnRenameGroup"><label class="object-note" for="objectColumnRenameInput">Column name</label><input id="objectColumnRenameInput" class="folder-input detail-action-field" placeholder="New column name"><button type="button" class="btn btn-warning btn-sm" id="objectColumnRename">Review rename</button></div>');
    $('objectColumnRename').onclick = function () { var item = getItemByKey(detailItemKey); if (!item) return; var name = $('objectColumnRenameInput').value.trim(); return reviewOperations([{ kind: 'rename', column_renames: [{ table: item.table, name: item.name, target_name: name }] }], 'Rename column', function () { detailItemKey = item.type + ':::' + item.table + ':::' + name; }); };

    section.querySelector('.detail-pagenav button').onclick = function () { backFromItem(); };
    section.addEventListener('click', function (event) {
      var action = event.target.closest('[data-object-action]'); if (!action) return;
      if (action.dataset.objectAction === 'definition') { selectTab('item', 'definition'); $('detailDaxEditor').focus(); }
      if (action.dataset.objectAction === 'changes') selectTab('item', 'changes');
      if (action.dataset.objectAction === 'references') selectTab('item', 'references');
      if (action.dataset.objectAction === 'dependencies') selectTab('item', 'dependencies');
      if (action.dataset.objectAction === 'copy') {
        var item = getItemByKey(detailItemKey);
        if (item && navigator.clipboard) navigator.clipboard.writeText(item.daxExpression || '').then(function () { action.textContent = 'Copied'; }).catch(function () { action.textContent = 'Copy unavailable'; });
      }
    });
  }
  function roles(item) {
    var out = [];
    [['isKey', 'Key column'], ['isRelationship', 'Relationship endpoint'], ['isSortColumn', 'Sort-by target'], ['isHierarchy', 'Hierarchy level'], ['isRls', 'Row-level security'], ['isFieldParameter', 'Field parameter']].forEach(function (entry) { if (item[entry[0]]) out.push(entry[1]); });
    var roleLabels = {Sort: 'Sort-by target', Hierarchy: 'Hierarchy level', Key: 'Key column', RLS: 'Row-level security', 'Field param': 'Field parameter'};
    (item.otherModelUses || []).forEach(function (role) { out.push(roleLabels[role] || role); });
    if (item.relationshipRefCount) out.push('Relationship endpoint');
    if (item.sortByColumn) out.push('Sorted by ' + item.sortByColumn);
    return Array.from(new Set(out));
  }
  renderDetailLayoutContent = function (item) {
    if (!$('objectItemPrimary')) return;
    if (!item) { $('objectItemPrimary').innerHTML = empty('Select a measure or column from Items.'); return; }
    var type = item.type || 'Item';
    if (lastItemType !== type) { lastItemType = type; selectTab('item', itemTabByType[type] || 'overview'); }
    $('objectItemBreadcrumb').innerHTML = '<button type="button" data-back-items>Items</button><span>/</span><button type="button" class="detail-table-link" data-table-name="' + esc(item.table) + '">' + esc(item.table) + '</button><span>/</span><span aria-current="page">' + esc(item.name) + '</span>';
    $('objectItemBreadcrumb').querySelector('[data-back-items]').onclick = function () { switchView('details'); $('mainArea').scrollTop = inventoryScroll; };
    var cleanup = deleteSafetyValue(item); var cleanupLabel = cleanup === 'Blocked' ? 'Deletion blocked' : cleanup === 'Keep' ? 'Retain for model dependencies' : 'Cleanup: ' + cleanup;
    $('objectItemSummary').innerHTML = '<div class="detail-status-row">' + usageBadge(item) + '<span class="badge badge-muted">' + esc(cleanupLabel) + '</span>' + (issueValue(item) ? issueBadge(item) : '<span class="badge badge-muted">No recorded issues</span>') + '</div><p>' + esc(detailDecisionCopy(item)) + ' Evidence covers the selected reports.</p>';
    var counts = detailCounts(item);
    var source = item.type === 'Measure' || item.type === 'Calculated Column'
      ? '<section class="detail-card"><div class="object-card-head"><h4>DAX expression</h4><div><button type="button" class="btn btn-secondary btn-sm" data-object-action="copy">Copy</button> <button type="button" class="btn btn-secondary btn-sm" data-object-action="definition">' + (isReportItem(item) ? 'View definition' : 'Edit DAX') + '</button></div></div>' + formatCodeBlock(item.daxExpression, 'Expression unavailable in this analysis.') + '</section>'
      : card('Column source and roles', properties([['Source column', item.sourceColumn || 'Not recorded'], ['Data type', item.dataType || 'Not recorded'], ['Structural roles', roles(item).join(' · ') || 'See model dependencies below']]) + '<p class="object-note">' + esc(usageHelpText(item)) + '</p><button type="button" class="object-link" data-object-action="definition">Inspect table source</button>');
    var consumers = '<div class="object-impact"><div><strong>' + counts.reports + '</strong><span>Selected reports</span></div><div><strong>' + counts.directRefs + '</strong><span>Direct references</span></div><div><strong>' + counts.dependents + '</strong><span>DAX consumers</span></div></div>';
    consumers += counts.directRefs ? '<button type="button" class="object-link" data-object-action="references">Inspect report references</button>' : '<p class="object-note">No direct report references. ' + esc(counts.dependents ? 'Other model items depend on this item.' : (item.otherModelUseCount || item.relationshipRefCount) ? 'Retained structural metadata uses this item.' : 'No downstream consumers were found in the selected scope.') + '</p>';
    consumers += formatDetailList(item.dependentItems || item.usedByItems || [], { linkItems: true });
    if ((item.indirectVia || []).length) consumers += '<h4>Required through</h4>' + formatDetailList(item.indirectVia, { linkItems: true });
    consumers += '<button type="button" class="object-link" data-object-action="dependencies">Inspect all dependencies</button>';
    $('objectItemPrimary').innerHTML = source + card('Where this item is used', consumers);
    $('objectItemProperties').innerHTML = card('Properties', properties([['Type', type], ['Origin', sourceSummary(item)], ['Home table', item.table], ['Display folder', item.displayFolder || 'None'], ['Format string', item.formatString], ['Visibility', item.isHidden ? 'Hidden' : 'Visible'], ['Description', item.description], ['Source file', item.sourceFile || 'Not recorded']])) + '<button type="button" class="btn btn-primary" data-object-action="changes">' + (isReportItem(item) ? 'Promote to model…' : 'Plan a change…') + '</button>';
    var dependencies = (item.dependencyItems || (item.dependsOnMeasures || []).concat(item.dependsOnColumns || [])).concat(item.dependsOnTables || []);
    $('item-pane-dependencies').innerHTML = '<div class="object-grid"><div class="object-stack">' + card('Depends on — inputs to this item', formatDetailList(dependencies, { linkItems: true })) + card('Used by — downstream consumers', formatDetailList(item.dependentItems || item.usedByItems || [], { linkItems: true })) + '</div><aside class="object-stack">' + card('Model role and retention', '<p class="object-note">' + esc(usageHelpText(item)) + '</p>' + formatDetailList(roles(item))) + card('Reference problems', formatBrokenRefDetails(item.brokenDaxRefDetails || [], item.brokenDaxRefs || [])) + '</aside></div>';
    $('detailSharedActions').classList.toggle('hidden', isReportItem(item));
    var canRenameColumn = !isReportItem(item) && (item.type === 'Column' || item.type === 'Calculated Column');
    $('objectColumnRenameGroup').classList.toggle('hidden', !canRenameColumn);
    $('objectColumnRenameInput').value = canRenameColumn ? item.name : '';
    $('detailActionHelpText').textContent = 'Choose a change, then review its files and validation before applying.';
    $('detailFolderInput').placeholder = 'Display folder';

    $('detailTechnicalSummary').textContent = 'Inspect the definition before editing. Changes are reviewed and statically validated before writing.';
    detailExpressionOpen = type === 'Measure' || type === 'Calculated Column'; detailMSourceOpen = !detailExpressionOpen; setDetailTechnicalVisibility();
    $('detailBtnToggleExpression').classList.toggle('hidden', !detailExpressionOpen);
    bindDetailLinks($('itemDetailSection'));
  };
  // Nodes have stable homes; rendering must not reparent editors and lose focus.
  placeDetailModules = function () {};
  setDetailLayoutMode = function (mode) { selectTab('item', mode === 'workbench' ? 'changes' : mode === 'inspector' ? 'references' : 'overview'); };
  function initTable() {
    var root = $('tableDetailSection'); root.classList.add('object-workspace');
    var children = Array.from(root.children).filter(function (el) { return !el.classList.contains('detail-pagenav') && !['tableDetailTitle', 'tableDetailMeta'].includes(el.id); });
    var parking = document.createElement('div'); parking.hidden = true; root.appendChild(parking); children.forEach(function (el) { parking.appendChild(el); });
    createTabs('table', root);
    var overview = $('table-pane-overview'); overview.innerHTML = '<div id="objectTableSummary" class="object-summary"></div><section class="detail-card"><div class="object-card-head"><h4>Items in this table</h4><input class="object-search" id="objectTableSearch" type="search" aria-label="Search items in this table" placeholder="Search name, type or state…"></div><div id="objectTableCount" class="object-note" aria-live="polite"></div><div class="object-grid-scroll" id="objectTableGrid"></div></section>';
    function moveCard(id, pane) { var node = $(id); if (node) $(pane).appendChild(node.closest('.detail-card')); }
    moveCard('tableDetailUsage', 'table-pane-references');
    moveCard('tableDetailRelationshipList', 'table-pane-dependencies'); moveCard('tableDetailRole', 'table-pane-dependencies'); moveCard('tableDetailRelatedTables', 'table-pane-dependencies');
    moveCard('tableActionStatus', 'table-pane-changes');
    $('table-pane-definition').innerHTML = '<section class="detail-card"><h4>Table source</h4><div id="objectTableSource"></div></section>';
    $('tableDetailGroupInput').value = '';
    $('objectTableSearch').addEventListener('input', function () { tableSearch = this.value; renderChildGrid(); });
    $('objectTableGrid').addEventListener('click', function (event) {
      var sort = event.target.closest('[data-child-sort]'); if (sort) { var key = sort.dataset.childSort; tableSort.direction = tableSort.key === key ? -tableSort.direction : 1; tableSort.key = key; renderChildGrid(); }
      var item = event.target.closest('[data-child-key]'); if (item) openItemDetails(item.dataset.childKey);
    });
  }
  function renderChildGrid() {
    var items = getItemsByTableName(detailTableName).filter(function (item) { return [item.name, item.type, usageValue(item), issueValue(item), deleteSafetyValue(item)].join(' ').toLowerCase().includes(tableSearch.toLowerCase()); });
    function value(item, key) { return key === 'usage' ? usageValue(item) : key === 'issues' ? issueValue(item) : key === 'cleanup' ? deleteSafetyValue(item) : item[key] || ''; }
    items.sort(function (a, b) { return String(value(a, tableSort.key)).localeCompare(String(value(b, tableSort.key))) * tableSort.direction; });
    $('objectTableCount').textContent = items.length + ' of ' + getItemsByTableName(detailTableName).length + ' items';
    $('objectTableGrid').innerHTML = '<table class="object-child-table"><thead><tr>' + [['name', 'Name'], ['type', 'Type'], ['usage', 'Usage'], ['issues', 'Issues'], ['cleanup', 'Cleanup']].map(function (entry) { return '<th scope="col" aria-sort="' + (entry[0] === tableSort.key ? tableSort.direction === 1 ? 'ascending' : 'descending' : 'none') + '"><button type="button" data-child-sort="' + entry[0] + '">' + entry[1] + (entry[0] === tableSort.key ? tableSort.direction === 1 ? ' ↑' : ' ↓' : '') + '</button></th>'; }).join('') + '</tr></thead><tbody>' + items.map(function (item) { return '<tr><td><button type="button" class="object-link" data-child-key="' + esc(itemKey(item)) + '">' + esc(item.name) + '</button></td><td>' + esc(item.type) + '</td><td>' + usageBadge(item) + '</td><td>' + (issueValue(item) ? issueBadge(item) : '<span class="detail-empty">None</span>') + '</td><td>' + deleteSafetyBadge(item) + '</td></tr>'; }).join('') + (items.length ? '' : '<tr><td colspan="5">No items match this search.</td></tr>') + '</tbody></table>';
  }
  var oldRenderTable = renderTableDetails;
  renderTableDetails = function () {
    oldRenderTable(); if (!$('objectTableSummary') || !detailTableName) return;
    var table = getTableByName(detailTableName); if (!table) return;
    var children = getItemsByTableName(table.name); var broken = children.filter(function (i) { return issueValue(i).includes('Broken'); }).length; var stale = children.filter(function (i) { return issueValue(i).includes('Stale'); }).length;
    $('tableDetailMeta').textContent = 'Table · ' + children.length + ' items · ' + (table.reportCount || 0) + ' selected reports';
    $('objectTableSummary').innerHTML = '<div class="detail-status-row">' + tableStatusBadge(table) + '<span class="badge badge-muted">' + (table.columnCount || 0) + ' columns</span><span class="badge badge-muted">' + (table.measureCount || 0) + ' measures</span>' + (broken ? '<span class="badge badge-caution">' + broken + ' broken items</span>' : '') + (stale ? '<span class="badge badge-warning">' + stale + ' stale items</span>' : '') + '</div><p>' + esc(table.roleReason || 'Inspect child items and model relationships before changing this table.') + '</p>';
    var sourceItem = children.find(function (i) { return i.mSourceDetails; });
    $('objectTableSource').innerHTML = formatCodeBlock(sourceItem && sourceItem.mSourceDetails, 'No table-level source was recorded in this analysis.');
    var virtual = children.length && children.every(isReportItem);
    ['tableBtnDelete', 'tableBtnRename', 'tableBtnMoveToTableGroup'].forEach(function (id) { $(id).disabled = !!virtual; });
    if (virtual) $('tableDetailMeta').textContent = 'Report-only virtual table · model table edits unavailable';
    renderChildGrid();
  };
  var oldSwitch = switchView;
  switchView = function (view) { oldSwitch(view); document.body.classList.toggle('object-view', view === 'item' || view === 'table'); document.querySelectorAll('.view-tab').forEach(function (button) { button.setAttribute('aria-current', button.dataset.view === view || (view === 'item' && button.dataset.view === 'details') || (view === 'table' && button.dataset.view === 'tables') ? 'page' : 'false'); }); };
  var oldOpenItem = openItemDetails;
  openItemDetails = function (key) { if (currentView === 'details') inventoryScroll = $('mainArea').scrollTop; if (currentView === 'table') returnTo = { table: detailTableName }; else if (currentView === 'item' && detailItemKey !== key) returnTo = { item: detailItemKey }; else if (currentView !== 'item') returnTo = null; oldOpenItem(key); $('itemDetailSection').querySelector('.detail-pagenav button').textContent = returnTo ? '← Back to ' + (returnTo.table || 'previous item') : '← Items'; $('mainArea').scrollTop = 0; };
  function backFromItem() { var destination = returnTo; returnTo = null; if (destination && destination.table) openTableDetails(destination.table); else if (destination && destination.item) oldOpenItem(destination.item); else { switchView('details'); $('mainArea').scrollTop = inventoryScroll; } }
  var oldOpenTable = openTableDetails;
  openTableDetails = function (name) { if (name !== detailTableName) { tableSearch = ''; $('objectTableSearch').value = ''; } oldOpenTable(name); $('mainArea').scrollTop = 0; };
  initItem(); initTable();
  var originalOpenScope = window.smcOpenScope;
  var originalCloseScope = window.smcCloseScope;
  window.smcOpenScope = function () { $('scopeDrawer').inert = false; $('scopeDrawer').removeAttribute('aria-hidden'); originalOpenScope(); };
  window.smcCloseScope = function () { originalCloseScope(); $('scopeDrawer').inert = true; $('scopeDrawer').setAttribute('aria-hidden', 'true'); };
  if (!document.body.classList.contains('scope-open')) window.smcCloseScope();

  window.smcSelectObjectTab = selectTab;
  var dialog = document.createElement('dialog'); dialog.className = 'object-review'; dialog.setAttribute('aria-labelledby', 'objectReviewTitle');
  dialog.innerHTML = '<header><h2 id="objectReviewTitle">Review change</h2><button type="button" class="btn btn-secondary btn-sm" id="objectReviewClose" aria-label="Close change review">Close</button></header><div class="object-review-content" id="objectReviewBody" aria-live="polite"></div><footer><span class="object-note" id="objectReviewStatus"></span><button type="button" class="btn btn-primary" id="objectReviewApply" disabled>Apply reviewed plan</button></footer>';
  document.body.appendChild(dialog);
  var reviewBusy = false;
  $('objectReviewClose').onclick = function () { if (!reviewBusy) dialog.close(); };
  dialog.addEventListener('cancel', function (event) { if (reviewBusy) event.preventDefault(); });
  function validationHtml(validation) {
    validation = validation || {};
    var labels = { json_syntax: 'JSON metadata', reference_integrity: 'Reference integrity', existing_problem_count: 'Existing problems', remaining_problem_count: 'Remaining problems', tmdl_syntax: 'TMDL syntax' };
    var rows = Object.keys(labels).filter(function (key) { return validation[key] !== undefined; }).map(function (key) { return '<dt>' + labels[key] + '</dt><dd>' + esc(String(validation[key])) + '</dd>'; }).join('');
    if (validation.pbir_schema) { var schema = validation.pbir_schema; var counts = schema.after; rows += '<dt>Declared PBIR schemas</dt><dd>' + counts.valid + ' valid · ' + counts.invalid + ' existing invalid · ' + counts.not_validated + ' not validated</dd><dt>Changed JSON coverage</dt><dd>' + (schema.comparison_complete ? 'No unvalidated JSON changes' : 'Incomplete — review unvalidated files') + '</dd>'; }
    var limitations = Array.isArray(validation.limitations) ? validation.limitations : [];
    return '<section class="object-validation"><h3>Validation</h3><dl class="object-properties">' + rows + '</dl>' + (limitations.length ? '<ul class="object-note">' + limitations.map(function (text) { return '<li>' + esc(text) + '</li>'; }).join('') + '</ul>' : '<p class="object-note">Static checks cover selected files. Power BI runtime results are not verified.</p>') + '</section>';
  }
  function scopeHtml(scope) {
    scope = scope || {};
    function name(path) { return String(path || '').split(/[\\/]/).filter(Boolean).pop() || 'Not selected'; }
    var model = scope.model || scope.model_path || '';
    var reports = Object.keys(scope).filter(function (key) { return key !== 'model' && key !== 'model_path'; }).flatMap(function (key) { return Array.isArray(scope[key]) ? scope[key] : [scope[key]]; }).filter(function (path) { return typeof path === 'string'; });
    return '<details class="object-scope-summary"><summary>' + esc(name(model)) + ' · ' + reports.length + ' selected report(s)</summary><dl class="object-properties"><dt>Model</dt><dd>' + esc(model) + '</dd><dt>Reports</dt><dd>' + (reports.length ? '<ul>' + reports.map(function (path) { return '<li>' + esc(path) + '</li>'; }).join('') + '</ul>' : 'None selected') + '</dd></dl></details>';
  }
  function planHtml(plan) {
    var changes = plan.changes || [];
    return '<p><strong>' + changes.length + ' file change(s)</strong> · Review differences before applying.</p>' + scopeHtml(plan.scope) + validationHtml(plan.validation) + changes.map(function (change, index) { return '<details' + (index === 0 ? ' open' : '') + '><summary>' + esc(change.path || change.artifact || 'File') + ' · ' + esc(change.change || 'modified') + '</summary><pre>' + esc(change.diff || 'No text difference available.') + '</pre></details>'; }).join('');
  }
  function receiptHtml(receipt) {
    return '<h3>' + esc(receipt.status || 'Change recorded') + '</h3><p class="object-note">Receipt ' + esc(receipt.id || '') + '</p>' + validationHtml(receipt.validation) + '<h3>Files</h3>' + formatDetailList((receipt.changed_files || []).map(function (file) { return typeof file === 'string' ? file : file.path || JSON.stringify(file); }));
  }
  async function reviewOperations(operations, title, onApplied) {
    if (dialog.open) return;
    var origin = document.activeElement;
    $('objectReviewTitle').textContent = title || 'Review change'; $('objectReviewBody').innerHTML = '<p>Preparing a validated preview…</p>'; $('objectReviewStatus').textContent = 'No files have been changed.'; $('objectReviewApply').disabled = true; $('objectReviewApply').hidden = false;
    dialog.showModal();
    var requestId = Date.now() + Math.random(); dialog.dataset.requestId = String(requestId);
    try {
      var response = await apiPost('/api/plans', { operations: operations, model_path: getModelPath(), report_paths: chosenReports.map(function (report) { return report.path; }) });
      if (!dialog.open || dialog.dataset.requestId !== String(requestId)) return;
      if (!response.ok || !response.plan) throw new Error(response.error || 'Could not prepare this change.');
      var plan = response.plan; $('objectReviewBody').innerHTML = planHtml(plan); $('objectReviewApply').disabled = !(plan.changes || []).length;
      $('objectReviewStatus').textContent = (plan.changes || []).length ? 'Files are checked again before apply. Recovery is recorded automatically.' : 'No file changes in this plan.';
      $('objectReviewApply').onclick = async function () {
        if (reviewBusy) return; reviewBusy = true; $('objectReviewApply').disabled = true; $('objectReviewClose').disabled = true; $('objectReviewStatus').textContent = 'Applying and validating…';
        try {
          var result = await apiPost('/api/plans/' + encodeURIComponent(plan.id) + '/apply', {});
          if (!result.ok) throw new Error(result.error || 'Apply failed. Open Changes & history for recovery status.');
          $('objectReviewBody').innerHTML = receiptHtml(result.receipt || {}); $('objectReviewApply').hidden = true; $('objectReviewStatus').textContent = 'Change recorded. Refreshing selected scope…';
          if (onApplied) onApplied(result.receipt);
          await reAnalyze({}); $('objectReviewStatus').textContent = 'Completed. The analysis has been refreshed.';
          logEntry(title || 'Reviewed plan applied', 'ok');
        } catch (error) { $('objectReviewStatus').textContent = error.message; $('objectReviewBody').insertAdjacentHTML('afterbegin', '<p class="object-error">' + esc(error.message) + '</p>'); }
        finally { reviewBusy = false; $('objectReviewClose').disabled = false; }
      };
    } catch (error) { if (dialog.open && dialog.dataset.requestId === String(requestId)) { $('objectReviewBody').innerHTML = '<p class="object-error">' + esc(error.message) + '</p>'; $('objectReviewStatus').textContent = 'Preview did not succeed. No changes applied.'; } }
    dialog.addEventListener('close', function () { if (origin && origin.isConnected) origin.focus(); }, { once: true });
  }
  window.smcReviewOperations = reviewOperations;
  function currentItemOperation(make, title, after) { var item = getItemByKey(detailItemKey); if (!item) return; var operation = make(item); if (operation) return reviewOperations([operation], title, function () { if (after) after(item, operation); }); }
  applyQueuedActions = function () { if (!pendingActions.size) return; return reviewOperations([{ kind: 'actions', actions: Array.from(pendingActions.values()) }], 'Review queued changes', function () { pendingActions.forEach(function (action, key) { actionStatus.set(key, 'Applied: ' + actionLabel(action)); }); pendingActions.clear(); clearActionPlanPreview(); updateApplyButtonState(); }); };
  renameCurrentMeasure = function () { return currentItemOperation(function (item) { return { kind: 'rename', measure_renames: [{ table: item.table, name: item.name, target_name: $('detailMeasureRenameInput').value.trim() }] }; }, 'Rename measure', function (item, operation) { detailItemKey = item.type + ':::' + item.table + ':::' + operation.measure_renames[0].target_name; }); };
  moveCurrentMeasureToTable = function () { return currentItemOperation(function (item) { return { kind: 'move', moves: [{ table: item.table, name: item.name, target_table: $('detailMoveMeasureTableSelect').value }] }; }, 'Move measure home table', function (item, operation) { detailItemKey = item.type + ':::' + operation.moves[0].target_table + ':::' + item.name; }); };
  renameCurrentTable = function () { return reviewOperations([{ kind: 'rename', table_renames: [{ table: detailTableName, target_table: $('tableRenameInput').value.trim() }] }], 'Rename table', function () { detailTableName = $('tableRenameInput').value.trim(); }); };
  saveCurrentItemDax = function () { return currentItemOperation(function (item) { return { kind: 'dax', table: item.table, name: item.name, item_type: item.type, dax_expression: $('detailDaxEditor').value, source_file: item.sourceFile }; }, 'Review DAX change'); };
  migrateCurrentReportMeasure = function () { return currentItemOperation(function (item) { return { kind: 'promote', report_path: (item.sourceFile || '').replace(/[\\/]definition[\\/]reportExtensions\.json$/i, ''), table: item.table, name: item.name, target_table: item.table, target_name: item.name, include_dependencies: true }; }, 'Promote measure and required dependencies'); };
  cleanCurrentItemStaleRefs = function () { return currentItemOperation(function (item) { return { kind: 'clean_stale', entries: staleCleanupEntriesForItems([item]) }; }, 'Clean stale report metadata'); };
  applyReportIssueActions = function (entries, label) { if (entries.length) return reviewOperations([{ kind: 'report_issues', entries: entries }], label || 'Review report changes', function () { selectedReportIssueKeys.clear(); }); };
  confirmRemoveWithPreview = function (entries, label) { return applyReportIssueActions(entries, label); };
  applyReportHealthStaleCleanup = function () { if (reportHealthStaleCleanupEntries.length) return reviewOperations([{ kind: 'clean_stale', entries: reportHealthStaleCleanupEntries }], 'Clean stale report metadata'); };
  applyRepair = function () { var group = activeRootCauseGroup(); if (group) return reviewOperations([{ kind: 'report_repair', table_renames: [{ table: group.targetLabel, target_table: repairTargetTable }] }], 'Repair table references in reports'); };
  applyColumnRepair = function () { var group = activeRootCauseGroup(); if (group) return reviewOperations([{ kind: 'report_repair', column_renames: buildColumnRenames(group) }], 'Repair column references in reports'); };
  cleanReportIssueEntries = function (entries) { if (entries.length) return reviewOperations([{ kind: 'clean_stale', entries: entries }], 'Clean stale report metadata', function () { selectedReportIssueKeys.clear(); }); };
  cleanReportIssueCleanupEntries = function (staleEntries, removeEntries) {
    var entries = staleEntries.concat(removeEntries.map(function (entry) { return { report_path: entry.report_path, artifact_path: entry.artifact_path, source_path: entry.source_path, selector_value: '', stale_kind: 'exact_reference' }; }));
    return cleanReportIssueEntries(entries);
  };
  cleanVisibleReportStaleIssues = function () { var entries = reportCleanupEntriesForIssues(getSelectedReportIssues()); return cleanReportIssueCleanupEntries(entries.stale, entries.remove); };
  cleanAllReportCleanupIssues = function () { var entries = reportCleanupEntriesForIssues(allReportIssues.filter(isReportIssueCleanup)); return cleanReportIssueCleanupEntries(entries.stale, entries.remove); };
  applyVisibleReportSuggestions = function () {
    var entries = getSelectedReportIssues().map(function (issue) { var suggestion = reportIssueSelectedSuggestion(issue); return suggestion && reportIssueActionEntry(issue, 'replace', suggestion); }).filter(Boolean);
    return applyReportIssueActions(entries, 'Review selected report replacements');
  };
  $('btnCleanStaleShown').onclick = cleanVisibleReportStaleIssues;
  $('btnCleanAllCleanup').onclick = cleanAllReportCleanupIssues;
  $('btnApplyReportSuggestionsShown').onclick = applyVisibleReportSuggestions;
  // Buttons assigned the original function directly need an explicit new handler.
  ['btnApply', 'detailBtnApply', 'tableBtnApply'].forEach(function (id) { $(id).onclick = applyQueuedActions; });
  var history = document.createElement('button'); history.type = 'button'; history.className = 'rail-item'; history.textContent = 'Changes & history'; $('viewTabs').appendChild(history);
  history.onclick = async function () {
    if (dialog.open) return;
    $('objectReviewTitle').textContent = 'Changes & history'; $('objectReviewApply').hidden = true; $('objectReviewStatus').textContent = 'Recovery refuses to overwrite subsequent file edits.'; $('objectReviewBody').innerHTML = '<p>Loading history…</p>'; dialog.showModal();
    try {
      var result = await apiGet('/api/plans'); if (result.error) throw new Error(result.error);
      var receipts = result.receipts || []; var plans = result.plans || [];
      $('objectReviewBody').innerHTML = '<h3>Receipts</h3>' + (receipts.length ? receipts.map(function (receipt) { return '<details><summary>' + esc(receipt.status || 'Recorded') + ' · ' + esc(receipt.id || '') + '</summary>' + receiptHtml(receipt) + '<button type="button" class="btn btn-secondary btn-sm" data-restore-id="' + esc(receipt.plan_id || receipt.id || '') + '">Review recovery</button></details>'; }).join('') : empty('No changes have been applied.')) + '<h3>Prepared plans</h3>' + (plans.length ? plans.map(function (plan) { return '<details><summary>' + esc(plan.id || '') + '</summary>' + planHtml(plan) + '</details>'; }).join('') : empty('No prepared plans.'));
      $('objectReviewBody').querySelectorAll('[data-restore-id]').forEach(function (button) { button.onclick = function () {
        var id = button.dataset.restoreId; $('objectReviewStatus').textContent = 'Restore the original files from this plan. Later edits will block recovery.'; $('objectReviewApply').textContent = 'Restore original files'; $('objectReviewApply').hidden = false; $('objectReviewApply').disabled = false;
        $('objectReviewApply').onclick = async function () { reviewBusy = true; $('objectReviewApply').disabled = true; $('objectReviewClose').disabled = true; try { var restored = await apiPost('/api/plans/' + encodeURIComponent(id) + '/restore', {}); if (!restored.ok) throw new Error(restored.error || 'Recovery refused.'); $('objectReviewBody').innerHTML = receiptHtml(restored.receipt || {status: 'restored', id: id}); $('objectReviewStatus').textContent = 'Original files restored.'; $('objectReviewApply').hidden = true; await reAnalyze({}); } catch (error) { $('objectReviewStatus').textContent = error.message; } finally { reviewBusy = false; $('objectReviewClose').disabled = false; } };
      }; });
    } catch (error) { $('objectReviewBody').innerHTML = '<p class="object-error">' + esc(error.message) + '</p>'; }
  };
  dialog.addEventListener('close', function () { $('objectReviewApply').textContent = 'Apply reviewed plan'; });
  renderItemDetails(); renderTableDetails();
})();

/* Compact inventories retain the complete dataset while revealing only useful
   default columns. Column choices affect presentation, never analysis or scope. */
(function () {
  'use strict';
  var compactSpecs = {
    tableSection: { primary: [0, 3, 7, 8, 9, 15], required: [0, 3, 7, 8, 15], min: {0: 36, 3: 180, 7: 88, 8: 90, 9: 62, 15: 92} },
    reportsTableSection: { primary: [0, 1, 2, 5, 6], required: [0, 1, 2, 5, 6], min: {0: 36, 1: 120, 2: 150, 5: 150, 6: 190} },
    tablesOverviewSection: { primary: [0, 1, 4, 5, 6, 7, 8], required: [0, 1], min: {0: 36, 1: 220, 4: 65, 5: 65, 6: 75, 7: 80, 8: 65} }
  };
  var visibility = {};
  var storagePrefix = 'smc.compact-columns.v1.';
  Object.keys(compactSpecs).forEach(function (id) {
    var spec = compactSpecs[id]; var stored = null;
    try { stored = JSON.parse(localStorage.getItem(storagePrefix + id)); } catch (_) { /* Optional local preference. */ }
    visibility[id] = new Set(Array.isArray(stored) ? stored.filter(function (index) { return Number.isInteger(index) && index >= 0 && index < $(id).querySelectorAll('thead th').length; }) : spec.primary);
    spec.required.forEach(function (index) { visibility[id].add(index); });
    $(id).classList.add('compact-inventory');
  });
  function activeInventory() { return { details: 'tableSection', tables: 'tablesOverviewSection', reports: 'reportsTableSection' }[currentView]; }
  function headerLabel(header, index) { if (index === 0) return 'Selection'; var copy = header.cloneNode(true); copy.querySelectorAll('.sort-arrow,.header-help,.col-resizer,.resize-handle').forEach(function (node) { node.remove(); }); return copy.textContent.trim(); }
  function applyVisibility(id) {
    var section = $(id); var table = section.querySelector('table'); var visible = visibility[id];
    table.querySelectorAll('tr').forEach(function (row) { Array.from(row.children).forEach(function (cell, index) { if (!cell.colSpan || cell.colSpan === 1) cell.classList.toggle('inventory-column-hidden', !visible.has(index)); }); });
    table.querySelectorAll('colgroup col').forEach(function (col, index) { col.classList.toggle('inventory-column-hidden', !visible.has(index)); if (!visible.has(index)) col.style.width = '0px'; });
  }
  var previousApplyWidths = applyTableWidths;
  applyTableWidths = function (id, widths) {
    if (!compactSpecs[id]) return previousApplyWidths(id, widths);
    var info = getTableSectionInfo(id); if (!info || !widths || widths.length !== info.headers.length) return;
    var indexes = Array.from(visibility[id]).sort(function (a, b) { return a - b; });
    var minimums = indexes.map(function (index) { return compactSpecs[id].min[index] || 85; });
    var desired = indexes.map(function (index, n) { return Math.max(minimums[n], Math.min(widths[index] || 120, index === 3 && id === 'tableSection' ? 360 : 260)); });
    var fitted = normalizeWidthsToTarget(desired, minimums, Math.max(info.section.clientWidth, minimums.reduce(function (a, b) { return a + b; }, 0)));
    var effective = widths.map(function () { return 0; }); indexes.forEach(function (index, n) { effective[index] = fitted[n]; });
    previousApplyWidths(id, effective); applyVisibility(id);
  };
  var columnMenu = document.createElement('details'); columnMenu.id = 'inventoryColumnMenu'; columnMenu.className = 'inventory-column-menu';
  columnMenu.innerHTML = '<summary>Columns</summary><div class="inventory-column-options" id="inventoryColumnOptions"></div>';
  $('tableToolsSection').appendChild(columnMenu);
  var status = document.createElement('span'); status.id = 'inventoryResultCount'; status.className = 'inventory-result-count'; status.setAttribute('aria-live', 'polite'); $('viewToolbar').prepend(status);
  function updateMenu() {
    var id = activeInventory(); columnMenu.hidden = !id;
    if (!id) return;
    var headers = Array.from($(id).querySelectorAll('thead th')); var spec = compactSpecs[id];
    $('inventoryColumnOptions').innerHTML = '<p>Core columns stay visible. Other properties are also available in object details.</p>' + headers.map(function (header, index) {
      if (index === 0) return '';
      return '<label><input type="checkbox" data-inventory-column="' + index + '"' + (visibility[id].has(index) ? ' checked' : '') + (spec.required.includes(index) ? ' disabled' : '') + '> ' + esc(headerLabel(header, index)) + '</label>';
    }).join('') + '<button type="button" class="btn btn-secondary btn-sm" id="inventoryResetColumns">Reset to compact defaults</button>';
    $('inventoryColumnOptions').querySelectorAll('[data-inventory-column]').forEach(function (input) { input.onchange = function () {
      var index = Number(input.dataset.inventoryColumn); if (input.checked) visibility[id].add(index); else visibility[id].delete(index);
      try { localStorage.setItem(storagePrefix + id, JSON.stringify(Array.from(visibility[id]))); } catch (_) { /* Optional preference. */ }
      applyVisibility(id); applyTableWidths(id, calculateDefaultWidths(id));
    }; });
    $('inventoryResetColumns').onclick = function () { visibility[id] = new Set(spec.primary); try { localStorage.removeItem(storagePrefix + id); } catch (_) {} updateMenu(); applyTableWidths(id, calculateDefaultWidths(id)); };
  }
  var oldPageControls = updatePageControls;
  updatePageControls = function () {
    oldPageControls(); var rows = getCurrentRowsForView(currentView); var total = currentView === 'details' ? allItems.length : currentView === 'tables' ? allTables.length : currentView === 'reports' ? allReportIssues.length : allRefs.length;
    status.textContent = activeInventory() ? rows.length + ' of ' + total + (currentView === 'reports' ? ' issue rows match' : currentView === 'tables' ? ' tables match' : ' items match') : '';
  };
  function annotateInventory() {
    $('tableBody').querySelectorAll('tr[data-key]').forEach(function (row) {
      var item = getItemByKey(row.dataset.key); if (!item) return;
      row.children[3].insertAdjacentHTML('beforeend', '<div class="inventory-identity-meta">' + esc(item.table) + ' · ' + esc(item.type) + (isReportItem(item) ? ' · Report measure' : '') + (item.isHidden ? ' · Hidden' : '') + '</div>');
      if (pendingActions.has(row.dataset.key)) row.children[3].insertAdjacentHTML('beforeend', '<div class="inventory-identity-meta">' + actionStatusBadge(row.dataset.key) + '</div>');
      if (!issueValue(item)) row.children[8].innerHTML = '<span class="inventory-muted">None</span>';
    });
    var page = getPagedRows(filteredItems, 'details'); var count = page.filter(function (item) { return selectedKeys.has(itemKey(item)); }).length;
    $('checkAll').checked = page.length > 0 && count === page.length; $('checkAll').indeterminate = count > 0 && count < page.length;
    if (!page.length) $('tableBody').innerHTML = '<tr><td colspan="17" class="inventory-empty">No items match these filters. Adjust search or filters to see more items.</td></tr>';
    applyVisibility('tableSection');
  }
  var oldRenderItems = renderTable;
  renderTable = function () { oldRenderItems(); annotateInventory(); };
  var oldTables = renderTablesOverview;
  renderTablesOverview = function () {
    oldTables(); var tables = getPagedRows(filteredTables, 'tables');
    $('tablesOverviewBody').querySelectorAll('tr').forEach(function (row, index) { var table = tables[index]; if (!table) return; var checkbox = row.querySelector('input[type="checkbox"]'); if (checkbox) checkbox.setAttribute('aria-label', 'Select table ' + table.name); row.children[1].insertAdjacentHTML('beforeend', '<div class="inventory-identity-meta">' + tableStatusBadge(table) + (table.issueState && table.issueState !== 'None' ? ' · ' + esc(table.issueState) : '') + '</div>'); });
    applyVisibility('tablesOverviewSection');
  };
  var oldReports = renderReportsTable;
  renderReportsTable = function () {
    oldReports(); var issues = getPagedRows(filteredReportIssues, 'reports');
    $('reportsTableBody').querySelectorAll('tr').forEach(function (row, index) {
      var issue = issues[index]; if (!issue) return;
      row.children[2].insertAdjacentHTML('beforeend', '<div class="inventory-identity-meta">' + esc(issue.page || 'Report level') + '</div><div class="inventory-identity-meta">' + esc(reportIssueVisualLabel(issue) || 'Report metadata') + '</div>' + (reportIssueHiddenLabel(issue) ? '<div class="inventory-identity-meta">' + esc(reportIssueHiddenLabel(issue)) + '</div>' : ''));
      row.children[1].insertAdjacentHTML('beforeend', '<details class="inventory-evidence"><summary>Evidence</summary><p>' + esc(issue.message || 'No additional message recorded.') + '</p><div class="inventory-identity-meta">' + esc(issue.artifactPath || '') + '</div><code>' + esc(issue.sourcePath || '') + '</code></details>');
    });
    if (!issues.length) $('reportsTableBody').innerHTML = '<tr><td colspan="7" class="inventory-empty">' + (allReportIssues.length ? 'No issue rows match the current filters.' : 'No report issues recorded in the selected scope.') + '</td></tr>';
    applyVisibility('reportsTableSection');
  };
  var oldControls = renderReportHealthControls;
  renderReportHealthControls = function () {
    oldControls(); var selected = getSelectedReportIssues(); var matching = new Set(filteredReportIssues); var hiddenSelected = selected.filter(function (issue) { return !matching.has(issue); }).length;
    $('reportHealthSummary').insertAdjacentHTML('beforeend', '<span class="inventory-count-note">Counts describe issue rows, not unique visuals. Categories can overlap.' + (hiddenSelected ? ' ' + hiddenSelected + ' selected row(s) are outside current filters.' : '') + '</span>');
    [['btnApplyReportSuggestionsShown', 'Review replacements'], ['btnRemoveReportIssuesShown', 'Review removals'], ['btnCleanStaleShown', 'Review selected cleanup'], ['btnCleanAllCleanup', 'Review all cleanup']].forEach(function (entry) { var count = $(entry[0]).textContent.match(/\(\d+\)$/); $(entry[0]).textContent = entry[1] + (count ? ' ' + count[0] : ''); });
    document.querySelectorAll('[data-report-issue-group]').forEach(function (button) { button.setAttribute('aria-pressed', String(button.classList.contains('active'))); });
  };
  var oldRootGroups = renderRootCausePanel;
  renderRootCausePanel = function () {
    oldRootGroups(); var panel = $('rootCausePanel'); var impact = panel.querySelector('.root-cause-impact');
    if (impact) impact.insertAdjacentHTML('beforeend', '<span class="inventory-count-note">Group totals cover the selected analysis scope; the table below follows active filters.</span>');
    panel.querySelectorAll('[data-root-cause-key]').forEach(function (button) { button.setAttribute('aria-pressed', String(button.dataset.rootCauseKey === reportIssueRootCauseFilter)); });
    var toggle = panel.querySelector('[data-root-cause-toggle-hidden]'); if (toggle) toggle.setAttribute('aria-expanded', String(rootCauseHiddenExpanded));
  };
  var oldSwitchInventory = switchView;
  switchView = function (view) { oldSwitchInventory(view); updateMenu(); var id = activeInventory(); if (id) applyTableWidths(id, calculateDefaultWidths(id)); };
  document.querySelectorAll('th[data-col],th[data-tablecol],th[data-reportcol],th[data-refcol]').forEach(function (header) {
    var label = headerLabel(header, 1); header.tabIndex = 0; header.setAttribute('aria-label', 'Sort by ' + label); header.setAttribute('aria-sort', 'none');
    header.addEventListener('keydown', function (event) { if (event.target !== header || !['Enter', ' '].includes(event.key)) return; event.preventDefault(); header.click(); });
    header.addEventListener('click', function (event) { if (event.target.closest('.header-help,.col-resizer')) return; header.parentElement.querySelectorAll('th[aria-sort]').forEach(function (other) { other.setAttribute('aria-sort', 'none'); }); var ascending = header.dataset.col ? sortAsc : header.dataset.tablecol ? tableSortAsc : header.dataset.reportcol ? reportIssueSortAsc : refSortAsc; header.setAttribute('aria-sort', ascending ? 'ascending' : 'descending'); });
  });
  $('reportsTableSection').querySelector('th[data-reportcol="report"]').childNodes[0].textContent = 'Location ';
  $('btnToggleFilters').setAttribute('aria-controls', 'filtersPanel');
  var oldToggleFilters = window.smcToggleFilters;
  window.smcToggleFilters = function () { oldToggleFilters(); $('btnToggleFilters').setAttribute('aria-expanded', String(!$('filtersPanel').classList.contains('hidden'))); };
  $('btnToggleFilters').setAttribute('aria-expanded', 'false');
  document.addEventListener('keydown', function (event) { if (event.key === 'Escape' && columnMenu.open) { columnMenu.open = false; columnMenu.querySelector('summary').focus(); } });
  updateMenu(); renderTable(); renderTablesOverview(); renderReportsTable();
})();
