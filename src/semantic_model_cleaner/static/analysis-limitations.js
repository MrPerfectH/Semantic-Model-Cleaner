/* Analysis limitations surface, shared by both layouts.
 *
 * Analysis limitations are model/scan gaps the analyzer detects but cannot fully
 * check (calculation items, KPI expressions, unreadable PBIR files). They are not
 * Report Health problems and must never read as a count of broken things:
 * distinct limitations and affected items are shown with explicit units.
 */
(function () {
  'use strict';
  var EMPTY = { distinctCount: 0, sharedCount: 0, targetedCount: 0, affectedItemCount: 0, coverageComplete: true, limitations: [] };
  var SHARED_PREFIX = 'No use found in the selected scope, but ';

  function state() {
    var value = typeof allAnalysisLimitations !== 'undefined' && allAnalysisLimitations ? allAnalysisLimitations : EMPTY;
    return value.limitations ? value : EMPTY;
  }
  function plural(count, singular, pluralForm) { return count + ' ' + (count === 1 ? singular : pluralForm || singular + 's'); }
  function text(value) { return typeof esc === 'function' ? esc(String(value == null ? '' : value)) : String(value == null ? '' : value); }

  function limitationsForItem(item) {
    var ids = item && Array.isArray(item.analysisLimitationIds) ? item.analysisLimitationIds : [];
    if (!ids.length) return [];
    var index = {};
    state().limitations.forEach(function (limitation) { index[limitation.id] = limitation; });
    return ids.map(function (id) { return index[id]; }).filter(Boolean);
  }

  function isSharedTrigger(trigger) { return typeof trigger === 'string' && trigger.indexOf(SHARED_PREFIX) === 0; }

  function nextAction(item) {
    var cleanup = typeof deleteSafetyValue === 'function' ? deleteSafetyValue(item) : (item && item.deleteSafety) || 'Review';
    if (cleanup === 'Safe') return 'Next: queue a reviewed delete if the item is not needed elsewhere.';
    if (cleanup === 'Blocked') return 'Next: keep the item; update or remove its consumers first.';
    if (cleanup === 'Keep') return 'Next: treat as required model structure.';
    if (item && item.reviewBasis === 'entity_type') return 'Next: confirm the whole ' + (item.entityKind || 'entity') + ' is no longer needed, then delete all of its items in one reviewed plan.';
    if (item && item.modelRole === 'Calculation group selector') return 'Next: review the whole calculation group through a table plan.';
    return 'Next: inspect the evidence below, then decide with a reviewed plan.';
  }

  /* Short reason first; the full trigger list and limitation explanations stay expandable. */
  function cleanupExplanation(item) {
    var triggers = item && Array.isArray(item.reviewTriggers) ? item.reviewTriggers.slice() : [];
    var specific = triggers.filter(function (trigger) { return !isSharedTrigger(trigger); });
    var shared = triggers.filter(isSharedTrigger);
    var limitations = limitationsForItem(item);
    var cleanup = typeof deleteSafetyValue === 'function' ? deleteSafetyValue(item) : (item && item.deleteSafety) || 'Review';
    var lead;
    if (specific.length) lead = specific[0].split('. ')[0] + '.';
    else if (shared.length) lead = 'No use found in the selected scope; analysis coverage is incomplete, so Safe is not asserted.';
    else if (typeof cleanupHelpText === 'function') lead = cleanupHelpText(cleanup);
    else lead = 'Cleanup recommendation: ' + cleanup + '.';
    return { lead: lead, next: nextAction(item), triggers: triggers, specific: specific, shared: shared, limitations: limitations };
  }

  /* What a limitation does to Cleanup, in plain words: both kinds keep items at Review. */
  function effectLabel(limitation) {
    if (limitation.scope === 'shared') return 'Keeps every unused item at Review';
    var count = limitation.affectedItemCount != null ? limitation.affectedItemCount : (limitation.targets || []).length;
    return count ? 'Keeps ' + plural(count, 'item') + ' at Review' : 'No items affected';
  }
  function fileLabel(location) {
    var value = String(location || '');
    return value.split(/[\\/]/).pop() || value;
  }
  function affectedItemsHtml(limitation) {
    var rows = Array.isArray(limitation.affectedItems) ? limitation.affectedItems : [];
    if (!rows.length) return limitation.targets && limitation.targets.length ? text(limitation.targets.join(', ')) : '';
    var links = rows.map(function (row) {
      var label = (row.table ? row.table + '[' + row.name + ']' : row.name);
      return '<a href="#" class="detail-link detail-item-link" data-item-key="' + text(row.type + ':::' + row.table + ':::' + row.name) + '">' + text(label) + '</a>';
    });
    var more = (limitation.affectedItemCount || 0) - rows.length;
    return links.join(', ') + (more > 0 ? ' and ' + plural(more, 'more item') : '');
  }

  /* One line per limitation; the evidence stays one click away. */
  function limitationRowHtml(limitation) {
    var construct = text(limitation.feature || limitation.area);
    var owner = limitation.owner ? text(limitation.owner) : '';
    var location = limitation.location || limitation.source_file || '';
    var summary = '<summary class="limitation-row">'
      + '<span class="limitation-construct" title="' + construct + (owner ? ' of ' + owner : '') + '"><strong>' + construct + '</strong>' + (owner ? ' <span class="limitation-owner">' + owner + '</span>' : '') + '</span>'
      + '<span class="limitation-location" title="' + text(location) + '">' + text(fileLabel(location)) + '</span>'
      + '<span class="limitation-effect">' + text(effectLabel(limitation)) + '</span>'
      + '</summary>';
    var affected = affectedItemsHtml(limitation);
    var body = '<dl class="limitation-facts">'
      + '<dt>Source</dt><dd>' + text(location) + (limitation.area ? ' · ' + text(limitation.area) : '') + '</dd>'
      + '<dt>Checked</dt><dd>' + text(limitation.checked || '') + '</dd>'
      + '<dt>Not checked</dt><dd>' + text(limitation.unchecked || '') + '</dd>'
      + '<dt>Effect on Cleanup</dt><dd>' + text(limitation.effect || '') + '</dd>'
      + (affected ? '<dt>Affected items</dt><dd>' + affected + '</dd>' : '')
      + '</dl>';
    return '<details class="limitation-card">' + summary + body + '</details>';
  }
  function limitationListHeader() {
    return '<div class="limitation-row limitation-row-header" aria-hidden="true"><span>Construct</span><span>Source</span>'
      + '<span title="Items whose Cleanup Recommendation stays at Review because of this limitation">Effect on Cleanup</span></div>';
  }

  function explanationHtml(item, options) {
    options = options || {};
    var explanation = cleanupExplanation(item);
    var html = '<div class="cleanup-lead">' + text(explanation.lead) + '</div><div class="cleanup-next">' + text(explanation.next) + '</div>';
    var details = '';
    if (explanation.triggers.length) {
      details += '<p class="object-note">' + (item && item.reviewBasis === 'entity_type' ? 'Review by entity type, not because of evidence' : plural(explanation.specific.length, 'item-specific reason')) + (explanation.shared.length ? ' · shared coverage gap collapsed into one line' : '') + '</p>';
      details += '<ul class="detail-list cleanup-triggers">' + explanation.triggers.map(function (trigger) { return '<li>' + text(trigger) + '</li>'; }).join('') + '</ul>';
    }
    if (explanation.limitations.length) {
      details += '<p class="object-note">' + plural(explanation.limitations.length, 'analysis limitation') + ' affecting this item</p>' + '<div class="limitation-groups">' + explanation.limitations.map(limitationRowHtml).join('') + '</div>';
    }
    if (details) html += '<details class="cleanup-technical"' + (options.open ? ' open' : '') + '><summary>Technical details and source evidence</summary>' + details + '</details>';
    return html;
  }

  function unusedScopeNote() {
    var current = state();
    if (current.coverageComplete !== false) return '';
    return ' Analysis coverage is incomplete (' + plural(current.sharedCount, 'shared analysis limitation') + '), so this is not proof of global non-use.';
  }

  function render() {
    var banner = document.getElementById('analysisLimitationsBanner');
    if (!banner) return;
    var list = document.getElementById('analysisLimitationsList');
    var count = document.getElementById('analysisLimitationsCount');
    var hint = document.getElementById('analysisLimitationsHint');
    var current = state();
    var tab = document.getElementById('tabLimitations');
    var tabCount = document.getElementById('tabLimitationsCount');
    if (tab) tab.classList.toggle('hidden', !current.limitations.length);
    if (tabCount) tabCount.textContent = current.limitations.length ? '(' + current.distinctCount + ')' : '';
    list.innerHTML = '';
    if (!current.limitations.length) { banner.classList.add('hidden'); if (count) count.textContent = ''; if (hint) hint.textContent = ''; return; }
    banner.classList.remove('hidden');
    if (count) count.textContent = '(' + plural(current.distinctCount, 'distinct limitation') + ' · ' + plural(current.affectedItemCount, 'affected item') + ')';
    if (hint) hint.textContent = plural(current.sharedCount, 'shared', 'shared') + ' keep every unused item at Review · ' + plural(current.targetedCount, 'targeted', 'targeted') + ' affect referenced items only';
    var wrap = document.createElement('div');
    wrap.className = 'limitation-groups';
    wrap.innerHTML = limitationListHeader() + current.limitations.map(limitationRowHtml).join('');
    list.appendChild(wrap);
    if (typeof bindDetailLinks === 'function') bindDetailLinks(wrap);
  }

  window.smcRenderAnalysisLimitations = render;
  window.smcCleanupExplanation = cleanupExplanation;
  window.smcCleanupExplanationHtml = explanationHtml;
  window.smcLimitationsForItem = limitationsForItem;
  window.smcUnusedScopeNote = unusedScopeNote;
  window.smcIsSharedLimitationTrigger = isSharedTrigger;
})();
