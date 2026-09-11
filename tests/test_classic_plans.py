"""Classic mutation routing must fail closed and require a reviewed plan."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / 'src/semantic_model_cleaner/static/classic-plans.js'
TEMPLATE = ROOT / 'src/semantic_model_cleaner/templates/index.html'


def test_classic_loads_guarded_review_before_analysis_adapter():
    html = TEMPLATE.read_text()
    assert html.index("filename='classic-plans.js'") < html.index("filename='analysis-jobs.js'")
    assert "if (!window.ClassicPlans) throw new Error" in html
    assert "return window.ClassicPlans.post(url, body || {});" in html
    assert "matches.length > 1) return null" in html
    assert "':::report:::' + (item.sourceFile" in html
    js = SCRIPT.read_text()
    ids = set(re.findall(r"el\('([^']+)'\)", js))
    generated = set(re.findall(r'id=\\?"([^"\\]+)', js))
    template_ids = set(re.findall(r'id="([^"]+)"', html))
    assert ids <= generated | template_ids, ids - generated - template_ids


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js unavailable')
def test_classic_write_requires_explicit_review_apply_and_cancel_writes_nothing(tmp_path):
    harness = tmp_path / 'classic-plans.cjs'
    harness.write_text(r'''
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {id, hidden:false, disabled:false, open:false,
    value:'Target', innerHTML:'', textContent:'', dataset:{},
    appendChild(){}, setAttribute(){}, addEventListener(name, fn){this[name]=fn;},
    querySelectorAll(){return [];}, showModal(){this.open=true;}, close(){this.open=false;}});
  return elements.get(id);
}
const requests=[];
const plan={id:'a'.repeat(32), scope:{model:'/M.SemanticModel','report-1':'/R.Report'},
  changes:[{path:'model/definition/tables/Sales.tmdl', change:'modified', diff:'-old\n+new'}],
  validation:{reference_integrity:'no new unresolved references',limitations:['Static validation.']}};
const context={console,Promise,Map,Set,Object,String,Array,Error,encodeURIComponent,
  document:{createElement(kind){return element(kind);},body:{appendChild(){}},getElementById:element,querySelector:element},
  chosenReports:[{path:'/R.Report',name:'R'}], getModelPath:()=>'/M.SemanticModel',
  fetch:async (url,options)=>{requests.push({url,body:options&&options.body&&JSON.parse(options.body)});
    const data=url==='/api/plans'?{ok:true,plan}:{ok:true,receipt:{status:'applied',plan_id:plan.id,changed_files:[]}};
    return {ok:true,json:async()=>data};},
  pendingActions:new Map(),selectedKeys:new Set(),selectedTableNames:new Set(),
  selectedReportIssueKeys:new Set(), clearActionPlanPreview(){},updateApplyButtonState(){},
  getItemByKey:()=>({table:'Sales',name:'Revenue',type:'Measure',sourceFile:'/M.SemanticModel/definition/tables/Sales.tmdl'}),
  detailItemKey:'x',detailTableName:'Sales',logEntry(){},reAnalyze:async()=>{},isReportItem:()=>false,
  staleCleanupEntriesForItems:()=>[],reportHealthStaleCleanupEntries:[],activeRootCauseGroup:()=>null,
  buildColumnRenames:()=>[]};
for(const name of ['applyQueuedActions','moveCurrentMeasureToTable','renameCurrentMeasure','renameCurrentTable',
 'saveCurrentItemDax','migrateCurrentReportMeasure','cleanCurrentItemStaleRefs','applyReportIssueActions',
 'confirmRemoveWithPreview','cleanReportIssueEntries','cleanReportIssueCleanupEntries',
 'applyReportHealthStaleCleanup','applyRepair','applyColumnRepair']) context[name]=()=>{};
context.window=context;
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),context);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  // Even a missed old callback cannot post directly to the legacy DAX writer.
  const pending=context.ClassicPlans.post('/api/dax',{table:'Sales',name:'Revenue',item_type:'Measure',dax_expression:'2'});
  await tick();
  assert.equal(requests.length,1); assert.equal(requests[0].url,'/api/plans');
  assert.equal(requests[0].body.operations[0].kind,'dax');
  assert.match(element('classicPlanBody').innerHTML,/-old/);
  assert.equal(element('classicPlanApply').hidden,false);
  await element('classicPlanApply').onclick();
  assert.equal((await pending).ok,true);
  assert.equal(requests[1].url,'/api/plans/'+plan.id+'/apply');
  element('classicPlanClose').onclick();
  const canceled=context.ClassicPlans.post('/api/model/rename',{table_renames:[{table:'Sales',target_table:'New'}]});
  const rejected=assert.rejects(canceled,/canceled/);
  await tick();
  element('classicPlanClose').onclick();
  await rejected;
  assert.equal(requests.length,3); // canceled preview never applies
  assert.equal(requests[2].url,'/api/plans');
  assert(!requests.some(r=>r.url==='/api/dax'||r.url==='/api/model/rename'));
  for(const [route,kind] of Object.entries({'/api/action':'actions','/api/dax':'dax','/api/model/rename':'rename',
    '/api/measure/move':'move','/api/report-measure/migrate':'promote','/api/report/repair-references':'report_repair',
    '/api/report/cleanup-stale':'clean_stale','/api/report/issues/apply':'report_issues'})) {
      assert(context.ClassicPlans.handles(route));
      assert.equal(context.ClassicPlans.operationForLegacy(route,{}).kind,kind);
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
''')
    result = subprocess.run([shutil.which('node'), str(harness), str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js unavailable')
def test_classic_same_named_report_mutations_and_keys_use_exact_owner(tmp_path):
    html = TEMPLATE.read_text()
    functions = []
    for name in ('getReportPathByName', 'getReportPathForReference', 'reportIssueKey', 'itemKey'):
        match = re.search(r'function ' + name + r'\([^)]*\) \{.*?\n\}', html, re.S)
        assert match, name
        functions.append(match.group())
    harness = tmp_path / 'identity.cjs'
    harness.write_text("const assert = require('node:assert/strict');\n"
        "var chosenReports=[{name:'Same',path:'/A/Same.Report'},{name:'Same',path:'/B/Same.Report'}];\n"
        "function isReportItem(item){return item.sourceKind==='report';}\n"
        + '\n'.join(functions) + "\n"
        "assert.equal(getReportPathByName('Same'),null);\n"
        "assert.equal(getReportPathForReference({report:'Same',reportPath:'/B/Same.Report'}),'/B/Same.Report');\n"
        "assert.equal(getReportPathForReference({report:'Same',reportPath:'/outside/Same.Report'}),null);\n"
        "assert.notEqual(reportIssueKey({report:'Same',reportPath:'/A/Same.Report'}),reportIssueKey({report:'Same',reportPath:'/B/Same.Report'}));\n"
        "var item={sourceKind:'report',type:'Measure',table:'Sales',name:'Local'};\n"
        "assert.notEqual(itemKey({...item,sourceFile:'/A/Same.Report/definition/reportExtensions.json'}),itemKey({...item,sourceFile:'/B/Same.Report/definition/reportExtensions.json'}));\n")
    result = subprocess.run([shutil.which('node'), str(harness)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
