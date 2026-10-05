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

  function limitationRowHtml(limitation, compact) {
    var scope = limitation.scope === 'shared' ? 'Shared · affects every item without use in scope' : 'Targeted · affects referenced items only';
    var affected = limitation.affectedItemCount != null ? plural(limitation.affectedItemCount, 'affected item') : '';
    var head = '<div class="limitation-head"><div><div class="limitation-title">' + text(limitation.feature || limitation.area) + (limitation.owner ? ' <span class="limitation-owner">of ' + text(limitation.owner) + '</span>' : '') + '</div>'
      + '<div class="limitation-meta">' + text(limitation.location || limitation.source_file || '') + ' · ' + text(limitation.area || '') + '</div></div>'
      + '<div class="limitation-badges"><span class="badge badge-review">' + text(scope) + '</span>' + (affected ? '<span class="badge badge-muted">' + text(affected) + '</span>' : '') + '</div></div>';
    var body = '<dl class="limitation-facts">'
      + '<dt>Checked</dt><dd>' + text(limitation.checked || '') + '</dd>'
      + '<dt>Not checked</dt><dd>' + text(limitation.unchecked || '') + '</dd>'
      + '<dt>Effect on Cleanup</dt><dd>' + text(limitation.effect || '') + '</dd>'
      + (limitation.targets && limitation.targets.length ? '<dt>Referenced items</dt><dd>' + text(limitation.targets.join(', ')) + '</dd>' : '')
      + '</dl>';
    return '<details class="limitation-card"' + (compact ? '' : '') + '><summary>' + head + '</summary>' + body + '</details>';
  }

  function explanationHtml(item, options) {
    options = options || {};
    var explanation = cleanupExplanation(item);
    var html = '<div class="cleanup-lead">' + text(explanation.lead) + '</div><div class="cleanup-next">' + text(explanation.next) + '</div>';
    var details = '';
    if (explanation.triggers.length) {
      details += '<p class="object-note">' + plural(explanation.specific.length, 'item-specific reason') + (explanation.shared.length ? ' · shared coverage gap collapsed into one line' : '') + '</p>';
      details += '<ul class="detail-list cleanup-triggers">' + explanation.triggers.map(function (trigger) { return '<li>' + text(trigger) + '</li>'; }).join('') + '</ul>';
    }
    if (explanation.limitations.length) {
      details += '<p class="object-note">' + plural(explanation.limitations.length, 'analysis limitation') + ' affecting this item</p>' + explanation.limitations.map(function (limitation) { return limitationRowHtml(limitation, true); }).join('');
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
    list.innerHTML = '';
    if (!current.limitations.length) { banner.classList.add('hidden'); if (count) count.textContent = ''; if (hint) hint.textContent = ''; return; }
    banner.classList.remove('hidden');
    if (count) count.textContent = '(' + plural(current.distinctCount, 'distinct limitation') + ' · ' + plural(current.affectedItemCount, 'affected item') + ')';
    if (hint) hint.textContent = plural(current.sharedCount, 'shared', 'shared') + ' keep every unused item at Review · ' + plural(current.targetedCount, 'targeted', 'targeted') + ' affect referenced items only';
    var intro = document.createElement('div');
    intro.className = 'limitation-summary';
    intro.innerHTML = '<div><strong>' + text(current.distinctCount) + '</strong> distinct limitations</div><div><strong>' + text(current.affectedItemCount) + '</strong> affected items</div><div><strong>' + text(current.sharedCount) + '</strong> shared</div><div><strong>' + text(current.targetedCount) + '</strong> targeted</div>';
    list.appendChild(intro);
    var wrap = document.createElement('div');
    wrap.className = 'limitation-groups';
    wrap.innerHTML = current.limitations.map(function (limitation) { return limitationRowHtml(limitation, false); }).join('');
    list.appendChild(wrap);
  }

  window.smcRenderAnalysisLimitations = render;
  window.smcCleanupExplanation = cleanupExplanation;
  window.smcCleanupExplanationHtml = explanationHtml;
  window.smcLimitationsForItem = limitationsForItem;
  window.smcUnusedScopeNote = unusedScopeNote;
  window.smcIsSharedLimitationTrigger = isSharedTrigger;
})();
