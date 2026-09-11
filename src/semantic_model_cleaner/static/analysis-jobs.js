/* Read-only background analysis. Existing callers retain their result contract. */
(function () {
  'use strict';
  function hydrate(payload) {
    if (payload._transport !== 'smc-browser-v1') return payload;
    var sources = new Map();
    payload.tables.forEach(function (table) { sources.set(table.name, table.mSourceDetails); table.items = table.itemIndices.map(function (i) { return payload.items[i]; }); delete table.itemIndices; });
    var common = ['type','table','name','sourceKind','sourceArtifact','sourceFile','isHidden','displayFolder','formatString','status','usageState','issueState','removalRisk','deleteSafety','reviewTriggers','brokenDaxRefs','brokenDaxRefDetails'];
    var empty = {report:'',reportPath:'',page:'',pageHidden:false,visualHidden:false,visualType:'',visualTitle:'',visualId:'',context:'',sourcePath:'',artifactKind:'',artifactPath:'',selectorValue:'',staleKind:''};
    payload.references = [];
    payload.items.forEach(function (item) {
      item.ref = item.table + '[' + item.name + ']';
      if (item.mSourceTable) { item.mSourceDetails = sources.get(item.mSourceTable) || null; delete item.mSourceTable; }
      var base = {}; common.forEach(function (key) { base[key] = item[key]; });
      (item.usageDetails.length ? item.usageDetails : [empty]).forEach(function (usage) { var ref = Object.assign({}, base, usage, {isStale:false}); delete ref.refType; payload.references.push(ref); });
      item.staleUsageDetails.forEach(function (usage) { var ref = Object.assign({}, base, usage, {isStale:true}); delete ref.refType; payload.references.push(ref); });
    });
    delete payload._transport; return payload;
  }
  window.smcHydrateAnalysis = hydrate;
  var originalPost = apiPost;
  var active = false;
  var panel = document.createElement('section');
  panel.setAttribute('aria-label', 'Analysis progress');
  panel.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:11000;background:white;color:#172f49;border:1px solid #cbd5e1;border-radius:10px;padding:18px;box-shadow:0 6px 24px #0002;max-width:calc(100vw - 40px)';
  panel.hidden = true;
  var status = document.createElement('p'); status.setAttribute('role', 'status'); status.style.margin = '0 0 12px';
  var cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'btn btn-secondary'; cancel.textContent = 'Cancel analysis';
  panel.append(status, cancel); document.body.appendChild(panel);
  apiPost = async function (url, data) {
    if (url !== '/api/analyze') return originalPost(url, data);
    if (active) return {error: 'Analysis is already running. Cancel it or wait for completion.'};
    active = true; panel.hidden = false; cancel.disabled = true; status.textContent = 'Starting analysis…';
    try {
      var response = await originalPost('/api/analysis-jobs', data);
      if (response.error || !response.job) return {error: response.error || 'Could not start analysis.', reportBinding: response.reportBinding};
      var id = response.job.id; cancel.disabled = false;
      cancel.onclick = async function () {
        cancel.disabled = true; status.textContent = 'Cancelling after current scan step…';
        try {
          var stopped = await fetch('/api/analysis-jobs/' + encodeURIComponent(id), {method: 'DELETE'});
          if (!stopped.ok) throw new Error('Cancellation request failed.');
        } catch (err) { cancel.disabled = false; status.textContent = err.message; }
      };
      for (;;) {
        var poll = await fetch('/api/analysis-jobs/' + encodeURIComponent(id));
        var payload = await poll.json(); var job = payload.job;
        if (!poll.ok || !job) return {error: payload.error || 'Analysis status unavailable.'};
        if (job.status === 'completed') {
          if (JSON.stringify(chosenModels.map(function (m) { return m.path; })) !== JSON.stringify(data.model_paths) || JSON.stringify(chosenReports.map(function (r) { return r.path; })) !== JSON.stringify(data.report_paths)) return {error: 'Scope changed during analysis. Analyze the current selection again.'};
          return hydrate(job.result);
        }
        if (job.status === 'cancelled') return {error: 'Analysis cancelled. Previous results are unchanged.'};
        if (job.status === 'failed') return {error: job.error || 'Analysis failed.'};
        status.textContent = job.stage + (job.total ? ' · ' + job.current + ' / ' + job.total : '');
        await new Promise(function (resolve) { setTimeout(resolve, 300); });
      }
    } catch (error) { return {error: error.message || 'Analysis connection failed.'}; }
    finally { active = false; panel.hidden = true; cancel.onclick = null; }
  };
})();
