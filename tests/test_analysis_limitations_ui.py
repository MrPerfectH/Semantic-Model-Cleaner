"""The Analysis limitations surface and collapsed cleanup explanations in the v2 workspace."""
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


@pytest.mark.parametrize('layout', ['index_v2.html'])
def test_v2_ship_the_separate_surface(layout):
    html = webapp.app.test_client().get('/').get_data(as_text=True)
    assert 'id="analysisLimitationsBanner"' in html
    assert 'id="analysisLimitationsTitle"' in html
    assert 'analysis-limitations.js' in html
    assert 'metadata the analyzer cannot fully verify' not in html  # Report Health no longer claims model gaps
    assert 'Scan coverage and unsupported metadata.' in html
    assert 'A limitation with no affected items is informational.' in html
    assert "'calculation-group': 'Calculation group'" in html
    assert 'Scan coverage and report findings' in html
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
function el(tag) { return { tag, children: [], className: '', _html: '', textContent: '', classList: { names: new Set(['hidden']), add(n) { this.names.add(n); }, remove(n) { this.names.delete(n); }, toggle(n, force) { if (force) this.names.add(n); else this.names.delete(n); } },
  appendChild(x) { this.children.push(x); }, set innerHTML(v) { this._html = v; if (v === '') this.children = []; }, get innerHTML() { return this._html; } }; }
const nodes = { analysisLimitationsBanner: el('details'), analysisLimitationsTitle: el('span'), analysisLimitationsList: el('div'), analysisLimitationsCount: el('span'), analysisLimitationsHint: el('span') };
const context = { window: {}, document: { getElementById: id => nodes[id] || null, createElement: el },
  allAnalysisLimitations: data.analysisLimitations, esc: s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  deleteSafetyValue: item => item.deleteSafety, cleanupHelpText: v => 'help:' + v };
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[3], 'utf8'), context);
context.window.smcRenderAnalysisLimitations();
assert.equal(nodes.analysisLimitationsBanner.classList.names.has('hidden'), false);
assert.equal(nodes.analysisLimitationsCount.textContent, '(4 distinct limitations · ' + data.analysisLimitations.affectedItemCount + ' affected items)');
assert.ok(nodes.analysisLimitationsHint.textContent.startsWith('4 shared coverage gaps'));
const cards = nodes.analysisLimitationsList.children[0].innerHTML;
// One labelled line per limitation; the effect column says what happens to Cleanup (#132).
assert.ok(cards.includes('limitation-row-header') && cards.includes('Effect on Cleanup</span>'));
assert.ok(cards.includes('Unused-item coverage incomplete · see cleanup recommendations'));
assert.ok(!cards.includes('Targeted · affects referenced items only'));
assert.equal((cards.match(/<details class="limitation-card"/g) || []).length, 4);
assert.ok(cards.includes('definition/tables/Time Intelligence.tmdl:8'));
assert.ok(cards.includes('Checked</dt>') && cards.includes('Not checked</dt>') && cards.includes('Effect on Cleanup</dt>'));
// A table named 'KPI Selector' never produces a limitation (#82); it may still be an affected item.
assert.ok(!cards.replace(/<dt>Affected items<\/dt><dd>.*?<\/dd>/g, '').includes('KPI Selector'));
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
// Perspective membership is informational: it adds no review lead and no perspective-specific next step.
const safeMember = context.window.smcCleanupExplanation({ deleteSafety: 'Safe', reviewTriggers: [], perspectiveMemberships: [{ perspective: 'Executive', sourceFile: 'definition/perspectives/Executive.tmdl' }] });
assert.equal(safeMember.next, 'Next: queue a reviewed delete if the item is not needed elsewhere.');
assert.ok(!/stays at Review/i.test(safeMember.lead + safeMember.next));
const reviewMember = context.window.smcCleanupExplanation({ deleteSafety: 'Review', reviewTriggers: ['Item is hidden'], perspectiveMemberships: [{ perspective: 'Executive' }] });
assert.equal(reviewMember.next, 'Next: inspect the evidence below, then decide with a reviewed plan.');
// Unused wording distinguishes scope from global non-use when coverage is incomplete.
assert.ok(context.window.smcUnusedScopeNote().includes('not proof of global non-use'));
context.allAnalysisLimitations = { distinctCount: 1, sharedCount: 0, targetedCount: 1, affectedItemCount: 0, coverageComplete: true, limitations: [{id:'language',feature:'linguisticMetadata',scope:'targeted',affectedItemCount:0,targets:[],effect:'No recommendations changed'}] };
context.window.smcRenderAnalysisLimitations();
assert.equal(nodes.analysisLimitationsHint.textContent, 'Informational · no cleanup recommendations changed');
assert.equal(nodes.analysisLimitationsTitle.textContent, 'Scan details');
assert.equal(nodes.analysisLimitationsBanner.classList.names.has('is-informational'), true);
assert.ok(nodes.analysisLimitationsList.children[0].innerHTML.includes('Informational · no items affected'));
for (const unknown of [
  {sharedCount:1,coverageComplete:false,limitations:[{scope:'shared',affectedItemCount:0}]},
  {coverageComplete:false,limitations:[{scope:'targeted'}]},
  {coverageComplete:true,limitations:[{scope:'targeted'}]},
]) {
  context.allAnalysisLimitations = {distinctCount:1,sharedCount:0,affectedItemCount:0,...unknown};
  context.window.smcRenderAnalysisLimitations();
  assert.equal(nodes.analysisLimitationsBanner.classList.names.has('is-informational'), false);
  assert.equal(nodes.analysisLimitationsTitle.textContent, 'Analysis limitations');
  assert.ok(!nodes.analysisLimitationsHint.textContent.includes('Informational'));
  assert.ok(!nodes.analysisLimitationsList.children[0].innerHTML.includes('Informational'));
}

context.allAnalysisLimitations = { distinctCount: 0, sharedCount: 0, targetedCount: 0, affectedItemCount: 0, coverageComplete: true, limitations: [] };
context.window.smcRenderAnalysisLimitations();
assert.equal(nodes.analysisLimitationsBanner.classList.names.has('hidden'), true);
assert.equal(context.window.smcUnusedScopeNote(), '');
console.log('ok');
'''
    assert run_node(tmp_path, program, str(data), str(SCRIPT)).strip() == 'ok'


@pytest.mark.parametrize("count", [1, 2])
def test_targeted_effect_counts_affected_items_without_status_claims(tmp_path, count):
    items = [
        {"type": "measure", "table": "Sales", "name": "Review item",
         "deleteSafety": "Review", "analysisLimitationIds": ["targeted"]},
        {"type": "measure", "table": "Sales", "name": "Blocked item",
         "deleteSafety": "Blocked", "analysisLimitationIds": ["targeted"]},
    ][:count]
    before = json.loads(json.dumps(items))
    limits = webapp._build_analysis_limitations(
        {"analysis_limitations": [{"id": "targeted", "scope": "targeted",
                                  "feature": "Synthetic coverage"}]}, items)
    assert items == before
    assert limits["affectedItemCount"] == count
    assert limits["limitations"][0]["affectedItemCount"] == count
    data = tmp_path / "targeted.json"
    data.write_text(json.dumps({"items": items, "limits": limits}), encoding="utf-8")
    program = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const data = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const before = JSON.stringify(data);
const nodes = {};
for (const id of ['analysisLimitationsBanner','analysisLimitationsList','analysisLimitationsCount','analysisLimitationsHint','analysisLimitationsTitle']) {
  nodes[id] = {classList:{add(){},remove(){},toggle(){}},appendChild(child){this.child=child;}};
}
const context = {window:{},allAnalysisLimitations:data.limits,esc:String,
  document:{getElementById:id=>nodes[id],createElement:()=>({})}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[3], 'utf8'), context);
context.window.smcRenderAnalysisLimitations();
const count = data.items.length, unit = count === 1 ? 'item' : 'items';
const html = nodes.analysisLimitationsList.child.innerHTML;
assert.ok(html.includes('Coverage incomplete for ' + count + ' ' + unit + ' · see cleanup recommendations'));
assert.ok(!html.includes('Keeps ' + count + ' ' + unit + ' at Review</span>'));
assert.equal(nodes.analysisLimitationsCount.textContent, '(1 distinct limitation · ' + count + ' affected ' + unit + ')');
for (const item of data.items) {
  assert.ok(html.includes(item.name));
  assert.equal(context.window.smcCleanupExplanation(item).next, item.deleteSafety === 'Blocked'
    ? 'Next: keep the item; update or remove its consumers first.'
    : 'Next: inspect the evidence below, then decide with a reviewed plan.');
}
assert.equal(JSON.stringify(data), before);
console.log('ok');
"""
    assert run_node(tmp_path, program, str(data), str(SCRIPT)).strip() == "ok"


@pytest.mark.parametrize("gap", ["targeted_calendar", "shared_metadata", "report_scan"])
def test_real_payload_expanded_coverage_preserves_recommendations(tmp_path, gap):
    model = tmp_path / "Test.SemanticModel"
    tables = model / "definition/tables"
    tables.mkdir(parents=True)
    declaration = (
        "table Sales\n\tcolumn Amount\n\t\tdataType: int64\n"
        "\tcolumn Spare\n\t\tdataType: string\n"
        "\tcolumn Inferred\n\t\tdataType: string\n\t\tisNameInferred\n"
    )
    if gap == "targeted_calendar":
        # An unmapped calendar has targeted, incomplete column coverage.
        declaration += "\tcalendar Fiscal\n"
    elif gap == "shared_metadata":
        declaration += (
            "\tmeasure Detail = 1\n"
            "\t\tdetailRowsDefinition = Sales[Amount] + [Missing]\n"
        )
    (tables / "Sales.tmdl").write_text(declaration, encoding="utf-8")
    report = tmp_path / "Test.Report"
    visual = report / "definition/pages/P/visuals/V/visual.json"
    visual.parent.mkdir(parents=True)
    (report / "definition.pbir").write_text(json.dumps({
        "datasetReference": {"byPath": {"path": "../Test.SemanticModel"}}
    }), encoding="utf-8")
    (report / "definition/report.json").write_text(
        "{invalid" if gap == "report_scan" else "{}", encoding="utf-8")
    visual.write_text(json.dumps({"visual": {"query": {"Column": {
        "Expression": {"SourceRef": {"Entity": "Sales"}}, "Property": "Amount"
    }}}}), encoding="utf-8")
    result = analyzer.analyze(tmp_path, model_paths=[model], report_paths=[report])
    payload = webapp._serialize_results(result, model_paths=[str(model)])
    items = {item["name"]: item for item in payload["items"]}
    assert {name: items[name]["deleteSafety"] for name in ("Amount", "Spare", "Inferred")} == {
        "Amount": "Blocked", "Spare": "Review", "Inferred": "Keep",
    }
    limitation = payload["analysisLimitations"]["limitations"][0]
    affected = [item for item in payload["items"]
                if limitation["id"] in item["analysisLimitationIds"]]
    assert affected
    if gap != "report_scan":
        assert {"Review", "Blocked"} <= {item["deleteSafety"] for item in affected}
    if gap == "targeted_calendar":
        assert limitation["scope"] == "targeted"
        assert items["Inferred"] in affected
        assert limitation["affectedItemCount"] == 3
    assert limitation["location"]
    assert limitation["checked"] and limitation["unchecked"]
    assert "stay at Review" not in limitation["checked"] + limitation["effect"]
    assert "stays at Review" not in limitation["effect"]
    assert "existing Blocked or Keep recommendations remain unchanged" in limitation["effect"]
    data = tmp_path / "real-payload.json"
    data.write_text(json.dumps(payload), encoding="utf-8")
    program = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const data = JSON.parse(fs.readFileSync(process.argv[2], 'utf8')), before = JSON.stringify(data);
const nodes = {};
for (const id of ['analysisLimitationsBanner','analysisLimitationsList','analysisLimitationsCount','analysisLimitationsHint','analysisLimitationsTitle']) {
  nodes[id] = {classList:{add(){},remove(){},toggle(){}},appendChild(child){this.child=child;}};
}
const context = {window:{},allAnalysisLimitations:data.analysisLimitations,esc:String,
  document:{getElementById:id=>nodes[id],createElement:()=>({})}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[3], 'utf8'), context);
context.window.smcRenderAnalysisLimitations();
const html = nodes.analysisLimitationsList.child.innerHTML;
assert.ok(!/Keeps .*Review|stay[s]? at Review/.test(html));
assert.ok(html.includes('actual cleanup recommendations are shown per item'));
assert.ok(html.includes('existing Blocked or Keep recommendations remain unchanged'));
for (const item of data.items.filter(i=>i.analysisLimitationIds.length)) {
  const body = context.window.smcCleanupExplanationHtml(item, {open:true});
  assert.ok(!/stay[s]? at Review/.test(body));
  assert.ok(body.includes('Technical details and source evidence'));
  assert.ok(body.includes('existing Blocked or Keep recommendations remain unchanged'));
}
assert.equal(JSON.stringify(data), before);
console.log('ok');
"""
    assert run_node(tmp_path, program, str(data), str(SCRIPT)).strip() == "ok"
