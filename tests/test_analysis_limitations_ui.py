"""The Analysis limitations surface and collapsed cleanup explanations in both layouts."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from semantic_model_cleaner import analyzer, webapp

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / 'src/semantic_model_cleaner/static/analysis-limitations.js'
FIXTURE = Path(__file__).parent / 'fixtures' / 'calculation_group_dependencies'
MODEL = FIXTURE / 'Models' / 'Synthetic Dependencies.SemanticModel'
REPORT = FIXTURE / 'Reports' / 'Executive.Report'


def run_node(tmp_path, program, *args):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js unavailable')
    harness = tmp_path / 'harness.cjs'
    harness.write_text(program, encoding='utf-8')
    result = subprocess.run([node, str(harness), *args], capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.mark.parametrize('layout', ['index.html', 'index_v2.html'])
def test_both_layouts_ship_the_separate_surface(layout):
    html = webapp.app.test_client().get('/?ui=' + ('v2' if layout == 'index_v2.html' else 'classic')).get_data(as_text=True)
    assert 'id="analysisLimitationsBanner"' in html
    assert 'analysis-limitations.js' in html
    assert 'metadata the analyzer cannot fully verify' not in html  # Report Health no longer claims model gaps
    assert 'Model analysis gaps are listed separately under Analysis limitations.' in html
    assert "'calculation-group': 'Calculation group'" in html
    assert 'Analysis limitations vs Report Health' in html
    assert 'id="tableDetailExternalConsumers"' in html
    assert webapp.app.test_client().get('/static/analysis-limitations.js').status_code == 200


def test_renderer_counts_distinct_limitations_and_collapses_item_explanations(tmp_path):
    results = analyzer.analyze(FIXTURE, model_paths=[MODEL], report_paths=[REPORT])
    payload = webapp._serialize_results(results, model_paths=[str(MODEL)])
    data = tmp_path / 'payload.json'
    data.write_text(json.dumps({
        'analysisLimitations': payload['analysisLimitations'],
        'selector': next(i for i in payload['items'] if i['table'] == 'Time Intelligence' and i['name'] == 'Name'),
        'kpiSelector': next(i for i in payload['items'] if i['table'] == 'KPI Selector' and i['name'] == 'KPI Name'),
    }), encoding='utf-8')
    program = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const data = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
function el(tag) { return { tag, children: [], className: '', _html: '', textContent: '', classList: { names: new Set(['hidden']), add(n) { this.names.add(n); }, remove(n) { this.names.delete(n); } },
  appendChild(x) { this.children.push(x); }, set innerHTML(v) { this._html = v; if (v === '') this.children = []; }, get innerHTML() { return this._html; } }; }
const nodes = { analysisLimitationsBanner: el('details'), analysisLimitationsList: el('div'), analysisLimitationsCount: el('span'), analysisLimitationsHint: el('span') };
const context = { window: {}, document: { getElementById: id => nodes[id] || null, createElement: el },
  allAnalysisLimitations: data.analysisLimitations, esc: s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  deleteSafetyValue: item => item.deleteSafety, cleanupHelpText: v => 'help:' + v };
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[3], 'utf8'), context);
context.window.smcRenderAnalysisLimitations();
assert.equal(nodes.analysisLimitationsBanner.classList.names.has('hidden'), false);
assert.equal(nodes.analysisLimitationsCount.textContent, '(7 distinct limitations · ' + data.analysisLimitations.affectedItemCount + ' affected items)');
assert.ok(nodes.analysisLimitationsHint.textContent.startsWith('4 shared keep every unused item at Review'));
const cards = nodes.analysisLimitationsList.children[1].innerHTML;
assert.equal((cards.match(/<details class="limitation-card"/g) || []).length, 7);
assert.ok(cards.includes('definition/tables/Time Intelligence.tmdl:8'));
assert.ok(cards.includes('Checked</dt>') && cards.includes('Not checked</dt>') && cards.includes('Effect on Cleanup</dt>'));
assert.ok(!cards.includes('KPI Selector'));
assert.ok(!cards.toLowerCase().includes('invalid'));
// Item explanation: short reason + next action first, one collapsed shared line, technical details expandable.
const explanation = context.window.smcCleanupExplanation(data.selector);
assert.ok(explanation.lead.startsWith("Selector column of calculation group 'Time Intelligence'"));
assert.ok(explanation.lead.length < 160);
assert.equal(explanation.next, 'Next: review the whole calculation group through a table plan.');
assert.equal(explanation.shared.length, 1);
assert.equal(explanation.limitations.length, 4);
const html = context.window.smcCleanupExplanationHtml(data.selector);
assert.ok(html.indexOf('cleanup-lead') < html.indexOf('cleanup-technical'));
assert.ok(html.includes('Parent table &#39;Time Intelligence&#39; is required by 10 retained DAX consumers'));
assert.equal((html.match(/<details class="limitation-card"/g) || []).length, 4);
// A table merely named KPI Selector carries only the collapsed shared gap, no KPI evidence.
const kpi = context.window.smcCleanupExplanation(data.kpiSelector);
assert.equal(kpi.specific.length, 0);
assert.equal(kpi.shared.length, 1);
assert.ok(!kpi.triggers.join(' ').includes('KPI target'));
// Unused wording distinguishes scope from global non-use when coverage is incomplete.
assert.ok(context.window.smcUnusedScopeNote().includes('not proof of global non-use'));
context.allAnalysisLimitations = { distinctCount: 0, sharedCount: 0, targetedCount: 0, affectedItemCount: 0, coverageComplete: true, limitations: [] };
context.window.smcRenderAnalysisLimitations();
assert.equal(nodes.analysisLimitationsBanner.classList.names.has('hidden'), true);
assert.equal(context.window.smcUnusedScopeNote(), '');
console.log('ok');
'''
    assert run_node(tmp_path, program, str(data), str(SCRIPT)).strip() == 'ok'
