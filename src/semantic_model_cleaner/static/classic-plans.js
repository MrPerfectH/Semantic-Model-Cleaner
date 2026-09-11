/* Classic layout: every metadata write uses the persisted plan contract. */
(function () {
  'use strict';
  var routes = {
    '/api/action': 'actions', '/api/dax': 'dax', '/api/model/rename': 'rename',
    '/api/measure/move': 'move', '/api/report-measure/migrate': 'promote',
    '/api/report/repair-references': 'report_repair',
    '/api/report/cleanup-stale': 'clean_stale', '/api/report/issues/apply': 'report_issues'
  };
  var busy = false, pending = null, currentPlan = null;
  var dialog = document.createElement('dialog');
  dialog.id = 'classicPlanDialog'; dialog.className = 'classic-plan-dialog';
  dialog.setAttribute('aria-labelledby', 'classicPlanTitle');
  dialog.innerHTML = '<header><div><p class="classic-plan-eyebrow">Changes &amp; history</p><h2 id="classicPlanTitle">Review changes</h2></div><button type="button" id="classicPlanClose" aria-label="Close change review">Close</button></header>'
    + '<div id="classicPlanBody" class="classic-plan-body"></div><footer><p id="classicPlanStatus" role="status" aria-live="polite"></p><button type="button" id="classicPlanApply" class="btn btn-primary" hidden>Apply reviewed changes</button></footer>';
  document.body.appendChild(dialog);
  var el = function (id) { return document.getElementById(id); };
  var escape = function (text) { return String(text == null ? '' : text).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); };
  function status(text) { el('classicPlanStatus').textContent = text; }
  async function request(url, body) {
    var options = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
    var response = await fetch(url, options), data = await response.json();
    if (!response.ok || data.error || data.ok === false) {
      var receipt = data.receipt || {};
      throw new Error(data.error || receipt.error || 'Operation ' + (receipt.status || 'failed') + '. Inspect Changes & history for recovery.');
    }
    return data;
  }
  function scopeHtml(plan) {
    return '<dl class="classic-plan-scope">' + Object.keys(plan.scope || {}).map(function (key) {
      return '<div><dt>' + escape(key) + '</dt><dd>' + escape(plan.scope[key]) + '</dd></div>';
    }).join('') + '</dl>';
  }
  function planHtml(plan, restoring) {
    return '<p>' + (restoring ? 'Restore the original bytes for these reviewed changes. Later edits are protected.' : 'Review the exact changes below. Applying uses this saved preview and refuses files changed since preview.') + '</p>'
      + scopeHtml(plan) + '<p><strong>' + plan.changes.length + ' changed file(s)</strong> · ' + escape(plan.validation.reference_integrity) + '</p>'
      + (plan.validation.pbir_schema ? '<p>Declared PBIR schemas: ' + plan.validation.pbir_schema.after.valid + ' valid · ' + plan.validation.pbir_schema.after.invalid + ' existing invalid · ' + plan.validation.pbir_schema.after.not_validated + ' not validated. Changed JSON coverage: ' + (plan.validation.pbir_schema.comparison_complete ? 'no unvalidated JSON changes' : 'incomplete') + '.</p>' : '')
      + '<ul class="classic-plan-limits">' + (plan.validation.limitations || []).map(function (text) { return '<li>' + escape(text) + '</li>'; }).join('') + '</ul>'
      + plan.changes.map(function (change) {
        return '<details open><summary>' + escape(change.change) + ' · ' + escape(change.path) + '</summary><pre tabindex="0">' + escape(change.diff || 'No text difference') + '</pre></details>';
      }).join('');
  }
  function receiptHtml(receipt) {
    return '<h3>' + escape(receipt.status) + '</h3><p>Operation ' + escape(receipt.plan_id || receipt.id) + '</p>'
      + '<ul>' + (receipt.changed_files || []).map(function (path) { return '<li>' + escape(path) + '</li>'; }).join('') + '</ul>'
      + (receipt.error ? '<p>' + escape(receipt.error) + '</p>' : '')
      + (receipt.recovery_errors || []).map(function (text) { return '<p>' + escape(text) + '</p>'; }).join('');
  }
  function setBusy(value) {
    busy = value; el('classicPlanClose').disabled = value; el('classicPlanApply').disabled = value;
    dialog.querySelectorAll('[data-plan-command]').forEach(function (button) { button.disabled = value; });
  }
  function close() {
    if (busy) return;
    dialog.close();
    if (pending) { pending.reject(new Error('Change canceled; nothing was written.')); pending = null; }
    currentPlan = null;
  }
  el('classicPlanClose').onclick = close;
  dialog.addEventListener('cancel', function (event) { event.preventDefault(); close(); });
  function open(title) {
    if (dialog.open || busy || pending) throw new Error('Finish or close the current change review first.');
    el('classicPlanTitle').textContent = title;
    el('classicPlanApply').hidden = true;
    el('classicPlanBody').innerHTML = '<p>Preparing a staged preview…</p>';
    status('Original model and report files are unchanged.');
    dialog.showModal();
  }
  async function reviewOperations(operations, title, options) {
    options = options || {};
    var model = options.model_path || getModelPath();
    var reports = options.report_paths || chosenReports.map(function (r) { return r.path; });
    if (!model || !reports.length) throw new Error('Select one model and its reports before preparing a change.');
    open(title || 'Review changes'); setBusy(true);
    try {
      var response = await request('/api/plans', {model_path: model, report_paths: reports, operations: operations});
      currentPlan = response.plan;
      el('classicPlanBody').innerHTML = planHtml(currentPlan, false);
      status(currentPlan.changes.length ? 'Review the file diffs, then apply this saved plan.' : 'This operation produces no file changes.');
      setBusy(false);
      if (!currentPlan.changes.length) throw new Error('No file changes to apply.');
      el('classicPlanApply').hidden = false;
      el('classicPlanApply').textContent = 'Apply reviewed changes';
      return await new Promise(function (resolve, reject) {
        pending = {resolve: resolve, reject: reject};
        el('classicPlanApply').onclick = async function () {
          if (busy || !pending) return;
          setBusy(true); status('Applying the reviewed plan…');
          try {
            var result = await request('/api/plans/' + encodeURIComponent(currentPlan.id) + '/apply', {});
            var completed = pending; pending = null;
            result.plan = currentPlan;
            el('classicPlanBody').innerHTML = receiptHtml(result.receipt);
            el('classicPlanApply').hidden = true;
            status('Applied. The receipt and original bytes are available in Changes & history.');
            completed.resolve(result);
          } catch (error) {
            status(error.message);
            // A failed apply can have a recovery receipt. Never offer a blind retry.
            el('classicPlanApply').hidden = true;
            var failed = pending; pending = null; failed.reject(error);
          } finally { setBusy(false); }
        };
      });
    } catch (error) {
      status(error.message); setBusy(false); throw error;
    }
  }
  function operationForLegacy(url, body) {
    var kind = routes[url];
    if (!kind) throw new Error('Unknown legacy mutation endpoint.');
    var operation = {kind: kind};
    var fields = {
      actions: ['actions'], dax: ['table','name','item_type','dax_expression','source_file'],
      rename: ['table_renames','measure_renames','column_renames'], move: ['moves'],
      promote: ['report_path','table','name','target_table','target_name','include_dependencies','allow_metadata_loss'],
      report_repair: ['table_renames','measure_renames','column_renames'], clean_stale: ['entries'], report_issues: ['entries']
    }[kind];
    fields.forEach(function (key) { if (body[key] !== undefined) operation[key] = body[key]; });
    return operation;
  }
  async function legacyPost(url, body) {
    // Only endpoints whose existing dry-run contract is read-only may use it.
    if (body.dry_run === true && ['rename','move','report_repair','clean_stale','report_issues'].indexOf(routes[url]) >= 0) {
      return request(url, body);
    }
    var result = await reviewOperations([operationForLegacy(url, body)], 'Review changes', body);
    // Compatibility for older callbacks. Counts are deliberately not fabricated.
    return {ok: true, result: {ok: true}, results: (body.actions || []).map(function (action) { return Object.assign({}, action, {ok: true}); }),
      receipt: result.receipt, reviewed_plan: result.plan};
  }
  async function run(operations, title, after) {
    try {
      var result = await reviewOperations(operations, title);
      if (after) after(result);
      logEntry(title + ': ' + result.plan.changes.length + ' file(s) changed. Receipt ' + result.plan.id, 'ok');
      await reAnalyze({});
      return result;
    } catch (error) { logEntry(error.message, 'info'); return null; }
  }
  function withItem(build, title, after) {
    var item = getItemByKey(detailItemKey);
    if (!item) { logEntry('Select an item first.', 'info'); return Promise.resolve(null); }
    try { return run([build(item)], title, after); }
    catch (error) { logEntry(error.message, 'err'); return Promise.resolve(null); }
  }
  function owningReport(item) {
    var path = (item.sourceFile || '').replace(/[\\/]definition[\\/]reportExtensions\.json$/i, '');
    if (path !== item.sourceFile && chosenReports.some(function (report) { return report.path === path; })) return path;
    throw new Error('The exact owning report could not be resolved. Re-analyze the selected reports.');
  }
  applyQueuedActions = function () {
    if (!pendingActions.size) return Promise.resolve(null);
    return run([{kind: 'actions', actions: Array.from(pendingActions.values())}], 'Review queued cleanup', function () {
      pendingActions.clear(); selectedKeys.clear(); selectedTableNames.clear(); clearActionPlanPreview(); updateApplyButtonState();
    });
  };
  moveCurrentMeasureToTable = function () { return withItem(function (item) {
    return {kind: 'move', moves: [{table: item.table, name: item.name, target_table: el('detailMoveMeasureTableSelect').value}]};
  }, 'Move measure home table'); };
  renameCurrentMeasure = function () { return withItem(function (item) {
    return {kind: 'rename', measure_renames: [{table: item.table, name: item.name, target_name: el('detailMeasureRenameInput').value.trim()}]};
  }, 'Rename measure'); };
  renameCurrentTable = function () { return run([{kind: 'rename', table_renames: [{table: detailTableName, target_table: el('tableRenameInput').value.trim()}]}], 'Rename table'); };
  saveCurrentItemDax = function () { return withItem(function (item) {
    if (isReportItem(item)) throw new Error('Promote this Report Extension Measure before editing its DAX in the model.');
    return {kind: 'dax', table: item.table, name: item.name, item_type: item.type, dax_expression: el('detailDaxEditor').value, source_file: item.sourceFile};
  }, 'Review DAX changes'); };
  migrateCurrentReportMeasure = function () { return withItem(function (item) {
    if (!isReportItem(item)) throw new Error('Select a Report Extension Measure first.');
    return {kind: 'promote', report_path: owningReport(item), table: item.table, name: item.name, include_dependencies: true};
  }, 'Promote measure and required dependencies'); };
  cleanCurrentItemStaleRefs = function () { return withItem(function (item) { return {kind: 'clean_stale', entries: staleCleanupEntriesForItems([item])}; }, 'Clean stale report metadata'); };
  applyReportIssueActions = function (entries, title) { return entries.length ? run([{kind: 'report_issues', entries: entries}], title || 'Review report changes', function () { selectedReportIssueKeys.clear(); }) : Promise.resolve(null); };
  confirmRemoveWithPreview = function (entries, title) { return applyReportIssueActions(entries, title); };
  cleanReportIssueEntries = function (entries) { return entries.length ? run([{kind: 'clean_stale', entries: entries}], 'Clean stale report metadata', function () { selectedReportIssueKeys.clear(); }) : Promise.resolve(null); };
  cleanReportIssueCleanupEntries = function (stale, remove) {
    var operations = [];
    if (stale.length) operations.push({kind: 'clean_stale', entries: stale});
    if (remove.length) operations.push({kind: 'report_issues', entries: remove});
    return operations.length ? run(operations, 'Review report cleanup', function () { selectedReportIssueKeys.clear(); }) : Promise.resolve(null);
  };
  applyReportHealthStaleCleanup = function () { return cleanReportIssueEntries(reportHealthStaleCleanupEntries); };
  applyRepair = function () { var group = activeRootCauseGroup(); return group ? run([{kind: 'report_repair', table_renames: [{table: group.targetLabel, target_table: repairTargetTable}]}], 'Repair report table references') : Promise.resolve(null); };
  applyColumnRepair = function () { var group = activeRootCauseGroup(); return group ? run([{kind: 'report_repair', column_renames: buildColumnRenames(group)}], 'Repair report column references') : Promise.resolve(null); };
  ['btnApply','detailBtnApply','tableBtnApply'].forEach(function (id) { el(id).onclick = applyQueuedActions; });
  // Original callbacks stored function values before this adapter loaded.
  var handlers = {detailBtnSaveDax: saveCurrentItemDax, detailBtnMigrateReportMeasure: migrateCurrentReportMeasure,
    detailBtnRenameMeasure: renameCurrentMeasure, tableBtnRename: renameCurrentTable};
  Object.keys(handlers).forEach(function (id) { if (el(id)) el(id).onclick = handlers[id]; });
  async function history() {
    try {
      open('Changes & history'); setBusy(true);
      var result = await request('/api/plans');
      var receipts = {}; (result.receipts || []).forEach(function (r) { receipts[r.plan_id || r.id] = r; });
      el('classicPlanBody').innerHTML = (result.plans || []).sort(function (a,b) { return b.created_at.localeCompare(a.created_at); }).map(function (plan) {
        var receipt = receipts[plan.id];
        return '<section class="classic-plan-history"><h3>' + escape((plan.operations || []).map(function (op) { return op.kind; }).join(', ')) + '</h3><p>' + escape(plan.created_at) + ' · ' + escape(receipt ? receipt.status : 'preview') + '</p>'
          + scopeHtml(plan) + '<p>' + plan.changes.length + ' changed file(s) · ' + escape(plan.id) + '</p>'
          + '<button type="button" data-plan-command="inspect" data-plan-id="' + escape(plan.id) + '">Inspect diffs</button> '
          + '<button type="button" data-plan-command="verify" data-plan-id="' + escape(plan.id) + '">Verify files</button> '
          + (receipt && ['applied','applying','recovery_required','restoring'].indexOf(receipt.status) >= 0 ? '<button type="button" data-plan-command="restore" data-plan-id="' + escape(plan.id) + '">Review restore</button> <button type="button" data-plan-command="recover-lock" data-plan-id="' + escape(plan.id) + '">Recover interrupted lock</button>' : '')
          + '</section>';
      }).join('') || '<p>No saved changes yet.</p>';
      status('Inspect a receipt or review restoration. Later file edits are protected.');
      dialog.querySelectorAll('[data-plan-command]').forEach(function (button) {
        button.onclick = function () { historyCommand(button.dataset.planId, button.dataset.planCommand); };
      });
    } catch (error) { status(error.message); } finally { setBusy(false); }
  }
  async function historyCommand(id, command) {
    setBusy(true);
    try {
      if (command === 'verify') {
        var response = await fetch('/api/plans/' + encodeURIComponent(id) + '/verify', {method: 'POST', headers: {'Content-Type':'application/json'}, body:'{}'});
        var verification = await response.json();
        if (verification.error) throw new Error(verification.error);
        status('Files: ' + verification.state + ((verification.changed_since_plan || []).length ? '. Changed paths: ' + verification.changed_since_plan.join(', ') : '.'));
      } else if (command === 'recover-lock') {
        await request('/api/plans/' + encodeURIComponent(id) + '/recover-lock', {});
        status('Interrupted lock recovered. Review restoration before changing files.');
      } else {
        var result = await request('/api/plans/' + encodeURIComponent(id));
        currentPlan = result.plan;
        el('classicPlanTitle').textContent = command === 'restore' ? 'Review restoration' : 'Saved change preview';
        el('classicPlanBody').innerHTML = planHtml(currentPlan, command === 'restore');
        status(command === 'restore' ? 'Restore reverses these diffs using saved original bytes.' : 'Saved diff. Close and return to history for verification or recovery.');
        el('classicPlanApply').hidden = command !== 'restore';
        el('classicPlanApply').textContent = 'Restore reviewed original files';
        el('classicPlanApply').onclick = async function () {
          setBusy(true);
          try {
            var restored = await request('/api/plans/' + encodeURIComponent(id) + '/restore', {});
            el('classicPlanBody').innerHTML = receiptHtml(restored.receipt);
            el('classicPlanApply').hidden = true; status('Original files restored.');
            await reAnalyze({});
          } catch (error) { status(error.message); } finally { setBusy(false); }
        };
      }
    } catch (error) { status(error.message); } finally { setBusy(false); }
  }
  var historyButton = document.createElement('button'); historyButton.type = 'button'; historyButton.id = 'classicPlanHistory';
  historyButton.className = 'btn classic-plan-history-button'; historyButton.textContent = 'Changes & history'; historyButton.onclick = history;
  document.querySelector('.header').appendChild(historyButton);
  window.smcReviewOperations = reviewOperations;
  window.ClassicPlans = {handles: function (url) { return !!routes[url]; }, post: legacyPost,
    reviewOperations: reviewOperations, operationForLegacy: operationForLegacy, history: history};
})();
