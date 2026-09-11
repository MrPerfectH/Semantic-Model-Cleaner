"""Exercise the tabbed workspace state without a browser or prototype fixtures."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).parents[1]
JS = ROOT / 'src/semantic_model_cleaner/static/detail-workspace.js'
TEMPLATE = ROOT / 'src/semantic_model_cleaner/templates/index_v2.html'


def function(source, name, indent='  '):
    start = source.index('function ' + name + '(')
    return source[start:source.index('\n' + indent + '}', start) + len(indent) + 2]


def run_js(tmp_path, code):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js unavailable')
    harness = tmp_path / 'workspace.cjs'
    harness.write_text("const assert = require('node:assert/strict');\n" + code)
    result = subprocess.run([node, str(harness)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_roving_tabs_hide_inactive_panels_and_preserve_type_preference(tmp_path):
    source = JS.read_text()
    run_js(tmp_path, """
var tabs=['Overview','Definition','References','Dependencies','Changes'];
var activeTabs={item:'overview'},itemTabByType={},lastItemType='Measure';
var nodes={};
function $(id){return nodes[id];}
for(const name of tabs){const key=name.toLowerCase();nodes['item-tab-'+key]={setAttribute(k,v){this[k]=v;}};nodes['item-pane-'+key]={};}
""" + function(source, 'selectTab') + """
selectTab('item','dependencies');
assert.equal(activeTabs.item,'dependencies');
assert.equal(itemTabByType.Measure,'dependencies');
for(const name of tabs){const key=name.toLowerCase(),active=key==='dependencies';assert.equal(nodes['item-tab-'+key].tabIndex,active?0:-1);assert.equal(nodes['item-pane-'+key].hidden,!active);assert.equal(nodes['item-tab-'+key]['aria-selected'],String(active));}
selectTab('item','missing');assert.equal(activeTabs.item,'overview');
""")


def test_independent_drafts_and_explicit_promotion_dependency_choice(tmp_path):
    source = JS.read_text()
    operation = next(line for line in source.splitlines() if line.strip().startswith('migrateCurrentReportMeasure ='))
    run_js(tmp_path, """
var drafts=new Map(),lastRenderedKey='Measure:::Sales:::Revenue',draftFieldIds=['detailDaxEditor','objectPromotionDependencies'];
""" + function(source, 'rememberDraft') + """
rememberDraft({target:{id:'detailDaxEditor',value:'SUM(Sales[Amount])'}});
lastRenderedKey='report-A:::Ratio';rememberDraft({target:{id:'objectPromotionDependencies',type:'checkbox',checked:true}});
assert.equal(drafts.get('Measure:::Sales:::Revenue').detailDaxEditor,'SUM(Sales[Amount])');
assert.equal(drafts.get('report-A:::Ratio').objectPromotionDependencies,true);
assert.equal(drafts.get('Measure:::Sales:::Revenue').objectPromotionDependencies,undefined);
let fields={objectPromotionName:{value:'Ratio'},objectPromotionTable:{value:'Sales'},objectPromotionDependencies:{checked:false}};
function $(id){return fields[id];}
function currentItemOperation(make){return make({table:'Sales',name:'Ratio',sourceFile:'/reports/Executive.Report/definition/reportExtensions.json'});}
let migrateCurrentReportMeasure;
""" + operation + """
let op=migrateCurrentReportMeasure();assert.equal(op.kind,'promote');assert.equal(op.report_path,'/reports/Executive.Report');assert.equal(op.include_dependencies,false);assert.equal(op.target_name,'Ratio');assert.equal(op.target_table,'Sales');
fields.objectPromotionDependencies.checked=true;assert.equal(migrateCurrentReportMeasure().include_dependencies,true);
""")


def test_table_children_search_cleanup_and_empty_results(tmp_path):
    source = JS.read_text()
    run_js(tmp_path, """
var detailTableName='Sales',tableSearch='',tableCleanup='Safe',tableSort={key:'name',direction:1};
var children=[{name:'Revenue',type:'Measure',deleteSafety:'Blocked'},{name:'Old Amount',type:'Column',deleteSafety:'Safe'},{name:'DateKey',type:'Column',deleteSafety:'Keep'}];
var nodes={objectTableCount:{},objectTableGrid:{}};function $(id){return nodes[id];}
function getItemsByTableName(){return children;}function usageValue(i){return i.deleteSafety==='Keep'?'Structural':'Used';}function issueValue(){return '';}function deleteSafetyValue(i){return i.deleteSafety;}function usageBadge(i){return usageValue(i);}function deleteSafetyBadge(i){return i.deleteSafety;}function esc(s){return s;}function itemKey(i){return i.name;}
""" + function(source, 'renderChildGrid') + """
renderChildGrid();assert.equal(nodes.objectTableCount.textContent,'1 of 3 items');assert(nodes.objectTableGrid.innerHTML.includes('Old Amount'));assert(!nodes.objectTableGrid.innerHTML.includes('Revenue'));
tableCleanup='';tableSearch='structural';renderChildGrid();assert(nodes.objectTableGrid.innerHTML.includes('DateKey'));assert.equal(nodes.objectTableCount.textContent,'1 of 3 items');
tableSearch='unknown';renderChildGrid();assert(nodes.objectTableGrid.innerHTML.includes('No items match this search.'));assert.equal(children.length,3);
""")


def test_live_and_stale_evidence_keep_hidden_labels_and_source_identity(tmp_path):
    source = TEMPLATE.read_text()
    names = ['usageLocationKey', 'usageLocatorKey', 'summarizeUsageLocation', 'renderUsageDetails', 'renderStaleUsageDetails']
    run_js(tmp_path, """
function esc(s){return String(s||'');}function reportReferenceId(r){return r.reportPath;}
""" + '\n'.join(function(source, name, '') for name in names) + """
var usage={report:'Executive',reportPath:'/A/Executive.Report',page:'Hidden',pageHidden:true,visualHidden:true,visualId:'v1',visualTitle:'Card',artifactKind:'Visual',sourcePath:'visual.query',artifactPath:'pages/p/visuals/v1/visual.json'};
var live=renderUsageDetails({usageDetails:[usage]});var stale=renderStaleUsageDetails({staleUsageDetails:[usage]});
for(const html of [live,stale]){assert(html.includes('Page hidden'));assert(html.includes('Visual hidden'));assert(html.includes('/A/Executive.Report'));assert(html.includes('visual.query'));}
assert(live.includes('1 ref'));
""")


def test_draft_identity_includes_model_and_selected_report_scope(tmp_path):
    run_js(tmp_path, """
var model='/A/Retail.SemanticModel';var chosenReports=[{path:'/Reports/B.Report'},{path:'/Reports/A.Report'}];
function getModelPath(){return model;}var analyzedScope=null;
""" + function(JS.read_text(), 'selectedScope') + function(JS.read_text(), 'draftKeyForItem') + """
const item='Measure:::Sales:::Revenue',first=draftKeyForItem(item);
chosenReports.reverse();assert.equal(draftKeyForItem(item),first);
model='/B/Retail.SemanticModel';assert.notEqual(draftKeyForItem(item),first);
model='/A/Retail.SemanticModel';chosenReports.pop();assert.notEqual(draftKeyForItem(item),first);
""")


def test_successful_unrelated_plan_does_not_consume_item_dax_draft(tmp_path):
    run_js(tmp_path, function(JS.read_text(), 'consumedDraftFields') + """
const item={table:'Sales',name:'Revenue',sourceFile:'/model/Sales.tmdl'};
assert.deepEqual(consumedDraftFields([{kind:'actions',actions:[{table:'Sales',name:'Other',action:'hide'}]}],item,null),[]);
assert.deepEqual(consumedDraftFields([{kind:'clean_stale'}],item,null),[]);
assert.deepEqual(consumedDraftFields([{kind:'dax',table:'Sales',name:'Revenue',source_file:'/model/Sales.tmdl'}],item,null),['detailDaxEditor']);
assert.deepEqual(consumedDraftFields([{kind:'rename',measure_renames:[{table:'Sales',name:'Revenue'}]}],item,null),['detailMeasureRenameInput']);
""")


def test_refresh_reports_cancellation_without_claiming_fresh_results(tmp_path):
    source = TEMPLATE.read_text()
    run_js(tmp_path, """
var chosenModels=[{path:'/Model'}],chosenReports=[{path:'/Report'}],loaded=false;
function logEntry(){}function setResultsData(){loaded=true;}function showPostRefreshDisclaimer(){}
async function apiPost(){return {error:'Analysis cancelled. Previous results are unchanged.'};}
""" + 'async ' + function(source, 'reAnalyze', '') + """
(async()=>{const result=await reAnalyze({});assert.equal(result.ok,false);assert(result.error.includes('cancelled'));assert.equal(loaded,false);})();
""")


def test_history_refresh_reveals_results_before_first_analysis_and_preserves_pending_state(tmp_path):
    source = TEMPLATE.read_text()
    run_js(tmp_path, """
var chosenModels=[{path:'/Model'}],chosenReports=[{path:'/Report'}],currentView='details';
var pendingActions=new Map([['draft',{action:'hide'}]]),preserved=[],shown=new Set(),switched=null;
function $(id){return {classList:{remove(name){assert.equal(name,'hidden');shown.add(id);}}};}
function logEntry(){}function setResultsData(data,preserve){preserved.push(preserve);if(!preserve)pendingActions.clear();}
function renderResultGuideLegend(){}function applyResultGuideState(){}function switchView(view){switched=view;}
function requestAnimationFrame(fn){fn();}function setupFilterDropdowns(){}function setupResizableTables(){}
function showPostRefreshDisclaimer(){}async function apiPost(){return {items:[],tables:[]};}
""" + function(source, 'loadResults', '') + 'async ' + function(source, 'reAnalyze', '') + """
(async()=>{
  const result=await reAnalyze({});assert.equal(result.ok,true);assert.deepEqual(preserved,[true]);
  assert.equal(pendingActions.size,1);assert.equal(switched,'details');
  for(const id of ['summarySection','resultGuideSection','filtersSection','viewToolbar','exportSection'])assert(shown.has(id),id+' remains hidden');
  loadResults({});assert.equal(preserved[1],false);assert.equal(pendingActions.size,0);
})();
""")


def test_refresh_navigates_away_from_removed_identity_without_guessing_replacement(tmp_path):
    source = JS.read_text()
    start = source.index('  setResultsData = function (data, preserve) {')
    assigned = source[start:source.index('\n  };', start) + 5]
    run_js(tmp_path, """
var currentView='item',detailItemKey='report:::Ratio',detailTableName='Sales',analyzedScope=null,analysisIsCurrent=false,inventoryScroll=17,focused=null;
var items=new Set(),tables=new Set(['Sales']);
function selectedScope(){return {model:'/Model',reports:[]};}
function originalSetResultsData(){if(!items.has(detailItemKey))detailItemKey=null;if(!tables.has(detailTableName))detailTableName=null;}
function getItemByKey(key){return items.has(key);}function getTableByName(name){return tables.has(name);}
function switchView(view){currentView=view;}function $(id){return {focus(){focused=id;}};}
var window={smcUpdateScopeChip(){}};var setResultsData;
""" + assigned + """
setResultsData({},true);assert.equal(currentView,'details');assert.equal(focused,'tabDetails');assert.equal(detailItemKey,null);assert.equal(analysisIsCurrent,true);
currentView='table';detailTableName='Removed';focused=null;setResultsData({},true);assert.equal(currentView,'tables');assert.equal(focused,'tabTables');
currentView='item';detailItemKey='model:::Renamed';items.add(detailItemKey);focused=null;setResultsData({},true);assert.equal(currentView,'item');assert.equal(detailItemKey,'model:::Renamed');assert.equal(focused,null);
""")
