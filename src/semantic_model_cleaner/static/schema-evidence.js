/* Offline PBIR schema evidence, shared by both layouts. */
(function () {
  'use strict';
  var host = document.getElementById('reportsTableSection');
  if (!host) return;
  var style = document.createElement('style');
  style.textContent = '.schema-evidence{margin:12px;padding:12px 14px;border:1px solid #cbd5e1;border-radius:9px;background:#f8fafc;color:#172f49;font-size:13px}.schema-evidence>summary{cursor:pointer;font-weight:650;padding:3px}.schema-evidence p{line-height:1.5;margin:10px 0}.schema-evidence .schema-controls{display:flex;gap:12px;flex-wrap:wrap;align-items:end;margin:14px 0}.schema-evidence label{display:grid;gap:5px}.schema-evidence input,.schema-evidence select{padding:7px;border:1px solid #94a3b8;border-radius:5px;background:white;color:inherit;font:inherit}.schema-evidence .schema-file{padding:10px 0;border-top:1px solid #dce4eb;overflow-wrap:anywhere}.schema-evidence .schema-file>summary{cursor:pointer;line-height:1.5}.schema-evidence .schema-error{padding:10px;margin:8px 0;background:white;border-left:3px solid #b45309;overflow-wrap:anywhere}.schema-evidence code{white-space:pre-wrap;overflow-wrap:anywhere}.schema-evidence .schema-pager{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:12px 0}.schema-evidence :focus-visible{outline:3px solid #2563eb;outline-offset:3px}';
  document.head.appendChild(style);
  function node(tag, text, parent) { var el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (parent) parent.appendChild(el); return el; }
  function button(text, parent, action) { var el = node('button', text, parent); el.type = 'button'; el.className = 'btn btn-secondary btn-sm'; el.onclick = action; return el; }
  var panel = node('details'); panel.className = 'schema-evidence';
  var heading = node('summary', 'PBIR schemas · evidence unavailable', panel);
  var body = node('div', undefined, panel);
  host.insertBefore(panel, host.firstChild);
  var evidence = null, filter = 'attention', query = '', page = 0, pageSize = 10;
  var reasons = {missing_schema:'Missing $schema declaration — not validated',unknown_schema:'Declared schema is not in the offline bundle — not validated',invalid_schema_declaration:'Invalid $schema declaration — not validated',invalid_json:'Invalid JSON syntax',schema_errors:'Declared schema errors',declared_schema_valid:'Matches its declared schema',unresolved_bundled_reference:'Bundled schema reference could not be resolved — not validated'};
  function reason(file) { return reasons[file.reason] || 'Schema unavailable: ' + String(file.reason || 'unknown reason').replace(/_/g, ' '); }
  function title(data) {
    if (!data) return 'PBIR schemas · evidence unavailable';
    var counts = data.counts || {}, invalid = counts.invalid || 0, unknown = counts.not_validated || 0;
    return 'PBIR schemas · ' + (counts.valid || 0) + ' valid · ' + invalid + ' invalid · ' + unknown + ' not validated' + (data.complete ? '' : ' · incomplete coverage');
  }
  function selectFiles(data, selected, text, index) {
    var all = (data && data.files || []).filter(function (file) { return (selected === 'all' || (selected === 'attention' ? file.status !== 'valid' : file.status === selected)) && (file.path + ' ' + (file.schema || '') + ' ' + reason(file)).toLowerCase().includes(text.toLowerCase()); });
    var pages = Math.max(1, Math.ceil(all.length / pageSize)); index = Math.min(Math.max(0, index), pages - 1);
    return {files:all.slice(index * pageSize, (index + 1) * pageSize),total:all.length,page:index,pages:pages};
  }
  // Pure helpers also exercise the coverage and pagination contract in tests.
  window.smcSchemaEvidence = {title:title, selectFiles:selectFiles};
  function errors(file, parent) {
    var rows = file.errors || [], index = 0;
    function draw() {
      parent.replaceChildren();
      rows.slice(index * 10, index * 10 + 10).forEach(function (error) {
        var block = node('div', undefined, parent); block.className = 'schema-error';
        node('strong', error.message || 'Schema error', block);
        var location = node('p', 'Instance pointer: ', block); node('code', error.path || '(document root)', location);
        var rule = node('p', 'Schema pointer: ', block); node('code', error.schema_path || '(schema root)', rule);
        if (error.message_truncated) node('p', 'Message shortened by the validator.', block);
      });
      if (rows.length > 10) {
        var nav = node('div', undefined, parent); nav.className = 'schema-pager';
        button('Previous errors', nav, function () { index--; draw(); }).disabled = index === 0;
        node('span', 'Errors ' + (index * 10 + 1) + '–' + Math.min(index * 10 + 10, rows.length) + ' of ' + rows.length, nav);
        button('Next errors', nav, function () { index++; draw(); }).disabled = (index + 1) * 10 >= rows.length;
      }
      if (file.truncated) node('p', 'The validator capped this file’s error list. Additional errors may exist.', parent);
    }
    draw();
  }
  function render() {
    body.replaceChildren();
    node('p', 'Offline checks against the exact declared Microsoft PBIR JSON schema. Missing or unsupported declarations are not validated. This does not validate DAX, TMDL, report rendering, or Power BI engine behavior.', body);
    if (!evidence) { node('p', 'Run an analysis to collect schema evidence. No schema pass is established for these results.', body); return; }
    var files = evidence.files || [];
    var missing = files.filter(function (file) { return file.reason === 'missing_schema'; }).length;
    var unknown = files.filter(function (file) { return file.reason === 'unknown_schema'; }).length;
    node('p', missing + ' files missing a declaration · ' + unknown + ' files declaring an unknown schema. Format annotations are not asserted.', body);
    if (evidence.bundle && evidence.bundle.commit) node('p', 'Offline Microsoft schema bundle: ' + evidence.bundle.commit.slice(0, 12), body);
    if (!evidence.complete) node('p', 'Coverage is incomplete. A zero invalid count does not establish that every report file is valid.', body);
    var controls = node('div', undefined, body); controls.className = 'schema-controls';
    var statusLabel = node('label', 'File status', controls), select = node('select', undefined, statusLabel);
    [['attention','Needs attention'],['all','All files'],['invalid','Invalid'],['not_validated','Not validated'],['valid','Valid']].forEach(function (pair) { var option = node('option', pair[1], select); option.value = pair[0]; }); select.value = filter;
    var searchLabel = node('label', 'Find file or schema', controls), input = node('input', undefined, searchLabel); input.type = 'search'; input.value = query;
    var results = node('div', undefined, body);
    function drawFiles() {
      results.replaceChildren(); var slice = selectFiles(evidence, filter, query, page); page = slice.page;
      var count = node('p', slice.total + ' matching files · page ' + (page + 1) + ' of ' + slice.pages, results); count.setAttribute('role', 'status');
      if (!slice.total) node('p', 'No files match these filters.', results);
      slice.files.forEach(function (file) {
        var row = node('details', undefined, results); row.className = 'schema-file';
        node('summary', file.path + ' · ' + reason(file), row);
        row.addEventListener('toggle', function () {
          if (!row.open || row.dataset.loaded) return; row.dataset.loaded = 'true';
          var declaration = node('p', 'Declared schema: ', row); node('code', file.schema || '(none)', declaration);
          var details = node('div', undefined, row); errors(file, details);
        });
      });
      if (slice.pages > 1) {
        var nav = node('div', undefined, results); nav.className = 'schema-pager';
        button('Previous files', nav, function () { page--; drawFiles(); countFocus(); }).disabled = page === 0;
        button('Next files', nav, function () { page++; drawFiles(); countFocus(); }).disabled = page + 1 >= slice.pages;
      }
    }
    function countFocus() { var target = results.querySelector('[role=status]'); target.tabIndex = -1; target.focus(); }
    select.onchange = function () { filter = select.value; page = 0; drawFiles(); };
    input.oninput = function () { query = input.value; page = 0; drawFiles(); };
    drawFiles();
  }
  panel.addEventListener('toggle', function () { if (panel.open) render(); });
  var original = setResultsData;
  setResultsData = function (data) {
    var result = original.apply(this, arguments);
    evidence = data.schemaValidation || null; page = 0; heading.textContent = title(evidence);
    if (panel.open) render();
    return result;
  };
})();
