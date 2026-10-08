"""Readable object details (#85) and obvious parent navigation (#86).

The analyzer only adds a presentation hint (declared calculation group plus the
items its calculation items can reference); cleanup classification is untouched.
"""
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from semantic_model_cleaner import analyzer, webapp as web_app

ROOT = Path(__file__).parents[1]
JS = ROOT / 'src/semantic_model_cleaner/static/detail-workspace.js'
CSS = ROOT / 'src/semantic_model_cleaner/static/detail-workspace.css'


@pytest.fixture
def project(tmp_path):
    model = tmp_path / 'Sales.SemanticModel'
    report = tmp_path / 'Executive.Report'
    tables = model / 'definition' / 'tables'
    tables.mkdir(parents=True)
    (tables / 'Sales.tmdl').write_text(
        "table Sales\n\tmeasure Revenue = SUM(Sales[Amount])\n"
        "\tcolumn Amount\n\t\tdataType: decimal\n\tcolumn Spare\n\t\tdataType: string\n", encoding='utf-8')
    (tables / 'Time Intelligence.tmdl').write_text(
        "table 'Time Intelligence'\n\tcalculationGroup\n"
        "\t\tcalculationItem Current = SELECTEDMEASURE()\n"
        "\t\tcalculationItem Share = DIVIDE(SELECTEDMEASURE(), SUM('Sales'[Amount]))\n"
        "\tcolumn 'Time Calculation'\n\t\tdataType: string\n\t\tsourceColumn: Name\n", encoding='utf-8')
    (report / 'definition').mkdir(parents=True)
    (report / 'definition.pbir').write_text(json.dumps({'datasetReference': {'byPath': {'path': '../Sales.SemanticModel'}}}), encoding='utf-8')
    (report / 'definition/report.json').write_text('{}', encoding='utf-8')
    return tmp_path, model, report


def test_calculation_group_tables_come_from_tmdl_declarations(project):
    _, model, _ = project
    assert analyzer.parse_calculation_group_tables(model) == {'Time Intelligence'}
    (model / 'definition/tables/Calc Names.tmdl').write_text(
        "table 'Calc Names'\n\tcolumn calculationGroupLabel\n\t\tdataType: string\n", encoding='utf-8')
    assert analyzer.parse_calculation_group_tables(model) == {'Time Intelligence'}


def test_table_summaries_carry_navigation_hint_without_changing_classification(project):
    root, model, report = project
    result = analyzer.analyze(root, model_paths=[model], report_paths=[report])
    summaries = {row['name']: row for row in result['table_summaries']}
    assert summaries['Sales']['is_calculation_group'] is False
    assert summaries['Sales']['calculation_group_targets'] == []
    calc = summaries['Time Intelligence']
    assert calc['is_calculation_group'] is True
    assert calc['calculation_group_targets'] == ['Sales[Amount]']
    assert calc['calculation_group_unresolved'] is False
    rows = {row['item'].name: row for row in result['items']}
    assert rows['Amount']['removal_risk'] == 'Review'
    assert rows['Spare']['removal_risk'] == 'Safe'
    payload = web_app._serialize_results(result, [str(model)])
    tables = {table['name']: table for table in payload['tables']}
    assert tables['Time Intelligence']['isCalculationGroup'] is True
    assert tables['Time Intelligence']['calculationGroupTargets'] == ['Sales[Amount]']
    assert tables['Sales']['isCalculationGroup'] is False


def test_unresolved_calculation_item_references_are_flagged_not_guessed(project):
    root, model, report = project
    (model / 'definition/tables/Time Intelligence.tmdl').write_text(
        "table 'Time Intelligence'\n\tcalculationGroup\n"
        "\t\tcalculationItem Prior = CALCULATE(SELECTEDMEASURE(), 'Date'[Missing])\n"
        "\tcolumn 'Time Calculation'\n\t\tdataType: string\n", encoding='utf-8')
    result = analyzer.analyze(root, model_paths=[model], report_paths=[report])
    calc = next(row for row in result['table_summaries'] if row['name'] == 'Time Intelligence')
    assert calc['calculation_group_unresolved'] is True
    assert calc['calculation_group_targets'] == ["Date[Missing]"]


def test_item_header_offers_explicit_parent_actions_with_accurate_wording():
    source = JS.read_text(encoding="utf-8")
    assert 'Inspect table source' not in source
    assert "'Open calculation group' : 'Open table'" in source
    assert 'data-object-action="definition">View definition tab' in source
    assert "parentLink(item.table, item.table), 'html'" in source
    assert 'object-parent-action' in source
    assert "backFromTable" in source and "tableReturnTo" in source


def test_detail_text_is_readable_at_normal_zoom():
    css = CSS.read_text(encoding="utf-8")
    readable = css[css.index('Readable, responsive object details'):]
    assert '.object-workspace { max-width:none; }' in readable
    for selector in ('.object-properties', '.object-crumbs', '.object-tabs button', '.object-workspace .detail-meta', '.object-child-table td'):
        rule = re.search(re.escape(selector) + r'[^{]*\{[^}]*font-size:(\d+(?:\.\d+)?)px', readable)
        assert rule and float(rule.group(1)) >= 14, selector
    assert 'max-width:80ch' in readable
    assert "body.object-view #warningBanner:not(.object-notice-open) #warningList { display:none; }" in readable


def function(source, name, indent='  '):
    start = source.index('function ' + name + '(')
    return source[start:source.index('\n' + indent + '}', start) + len(indent) + 2]


def run_js(tmp_path, code):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js unavailable')
    harness = tmp_path / 'navigation.cjs'
    harness.write_text("const assert = require('node:assert/strict');\n" + code, encoding="utf-8")
    result = subprocess.run([node, str(harness)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_parent_labels_follow_declared_table_kind_and_properties_allow_links(tmp_path):
    source = JS.read_text(encoding="utf-8")
    run_js(tmp_path, """
var tables={Sales:{name:'Sales'},Time:{name:'Time',isCalculationGroup:true}};
function getTableByName(n){return tables[n]||null;}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
""" + function(source, 'isCalculationGroupTable') + function(source, 'parentKindLabel') + function(source, 'parentActionLabel') + function(source, 'parentLink') + function(source, 'properties') + """
assert.equal(parentActionLabel('Sales'),'Open table: Sales');
assert.equal(parentActionLabel('Time'),'Open calculation group: Time');
assert.equal(parentKindLabel('Missing'),'table');
var html=properties([['Home table',parentLink('A<b',"A<b"),'html'],['Plain','<x>']]);
assert.ok(html.includes('data-table-name="A&lt;b"') && html.includes('detail-table-link'));
assert.ok(html.includes('<dd>&lt;x&gt;</dd>'));
""")


def test_table_back_returns_to_originating_item_and_restores_inventory_scroll(tmp_path):
    source = JS.read_text(encoding="utf-8")
    run_js(tmp_path, """
var currentView='item',detailItemKey='Column:::Sales:::Amount',detailTableName=null,returnTo=null,tableReturnTo=null,tablesScroll=0,tableSearch='x',tableCleanup='';
var calls=[];var focused=null;
var parentButton={focus(){focused='parent';}};
var backButton={textContent:''};
var nodes={mainArea:{scrollTop:55},objectTableSearch:{value:'x'},objectTableCleanup:{value:''},detailTitle:{focus(){focused='item';}},tableDetailTitle:{focus(){focused='table';}},tabTables:{focus(){focused='tabTables';}},
 objectItemParent:{querySelector(){return parentButton;}},tableDetailSection:{querySelector(){return backButton;}},tablesOverviewSection:{querySelectorAll(){return [];}}};
function $(id){return nodes[id];}
var items={'Column:::Sales:::Amount':{name:'Amount',table:'Sales'}};
function getItemByKey(k){return items[k]||null;}
function openTableDetails(name){detailTableName=name;currentView='table';calls.push('table:'+name);}
function switchView(v){currentView=v;calls.push('view:'+v);}
function backFromItem(){calls.push('backFromItem');}
var oldOpenItem=function(k){detailItemKey=k;currentView='item';calls.push('item:'+k);};
""" + function(source, 'backFromTable') + """
var oldOpenTable = openTableDetails;
""" + source[source.index('  openTableDetails = function (name, options) {'):source.index('\n  };', source.index('  openTableDetails = function (name, options) {')) + 4] + """
openTableDetails('Sales');
assert.deepEqual(tableReturnTo,{item:'Column:::Sales:::Amount'});
assert.equal(backButton.textContent,'← Back to Amount');
assert.equal(tableSearch,'');
backFromTable();
assert.equal(currentView,'item'); assert.equal(detailItemKey,'Column:::Sales:::Amount'); assert.equal(focused,'parent'); assert.equal(tableReturnTo,null);
// From the Tables inventory: back restores the scroll position and the label says Tables.
currentView='tables'; nodes.mainArea.scrollTop=120; detailItemKey=null;
openTableDetails('Sales');
assert.equal(backButton.textContent,'← Tables'); assert.equal(nodes.mainArea.scrollTop,0);
backFromTable();
assert.equal(currentView,'tables'); assert.equal(nodes.mainArea.scrollTop,120); assert.equal(focused,'tabTables');
// Opening the parent of an item that was opened from that same table is a return, not a new hop.
currentView='item'; detailItemKey='Column:::Sales:::Amount'; returnTo={table:'Sales'};
openTableDetails('Sales');
assert.equal(calls[calls.length-1],'backFromItem');
// Restoring a table from an item's back navigation keeps the earlier table context.
currentView='item'; returnTo=null; tableReturnTo={item:'Column:::Sales:::Amount'}; detailTableName='Sales';
openTableDetails('Sales',{restoring:true});
assert.deepEqual(tableReturnTo,{item:'Column:::Sales:::Amount'});
""")
