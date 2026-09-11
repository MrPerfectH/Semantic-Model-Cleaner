"""V2 keeps report identity separate from display names throughout review flows."""
from pathlib import Path
import shutil
import subprocess

import pytest

TEMPLATE = Path(__file__).parents[1] / 'src/semantic_model_cleaner/templates/index_v2.html'


def js_function(source, name):
    start = source.index('function ' + name + '(')
    line_end = source.index('\n', start)
    if source[start:line_end].rstrip().endswith('}'):
        return source[start:line_end]
    return source[start:source.index('\n}', line_end) + 2]


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js unavailable')
def test_v2_same_named_reports_have_distinct_keys_filters_counts_and_mutation_paths(tmp_path):
    source = TEMPLATE.read_text()
    names = ['itemKey','reportIssueKey','reportReferenceId','reportReferenceLabel','getReportPathByName',
             'getReportPathForReference','reportIssueCleanupEntry','reportIssueActionEntry',
             'usageLocationKey','usageLocatorKey','renderUsageDetails','uniqueCount','detailCounts', 'filterReportIssues']
    harness = tmp_path / 'v2-identity.cjs'
    harness.write_text("const assert = require('node:assert/strict');\n"
        "var chosenReports=[{name:'Same',path:'/A/Same.Report'},{name:'Same',path:'/B/Same.Report'}];\n"
        "function isReportItem(item){return item.sourceKind==='report';}\n"
        "function esc(text){return String(text||'');} function issueValue(){return '';}\n"
        "var reportIssueGroupFilter='all',reportIssueRootCauseFilter='__all__',reportIssueReportFilter='/B/Same.Report',reportIssuePageFilter='__all__';\n"
        "function $(id){return {value:''};}\n"
        + '\n'.join(js_function(source, name) for name in names) + '\n'
        + r'''
const base={report:'Same',page:'P',visualId:'V',artifactPath:'definition/pages/P/visuals/V/visual.json',sourcePath:'visual.query.Measure',table:'Sales',name:'Revenue',refType:'Measure'};
var allReportIssues=[{...base,reportPath:'/A/Same.Report'},{...base,reportPath:'/B/Same.Report'}];
assert.notEqual(reportIssueKey(allReportIssues[0]),reportIssueKey(allReportIssues[1]));
assert.notEqual(usageLocatorKey(allReportIssues[0]),usageLocatorKey(allReportIssues[1]));
assert.notEqual(usageLocationKey(allReportIssues[0]),usageLocationKey(allReportIssues[1]));
assert.equal(filterReportIssues().length,1);
assert.equal(filterReportIssues()[0].reportPath,'/B/Same.Report');
assert.match(reportReferenceLabel('/B/Same.Report'),/B\/Same.Report/);
assert.equal(reportIssueCleanupEntry(allReportIssues[1]).report_path,'/B/Same.Report');
assert.equal(reportIssueActionEntry(allReportIssues[1],'remove').report_path,'/B/Same.Report');
assert.equal(reportIssueCleanupEntry({...base,reportPath:'/outside/Same.Report'}),null);
assert.equal(reportIssueCleanupEntry(base),null);
var item={sourceKind:'report',type:'Measure',table:'Sales',name:'Local'};
assert.notEqual(itemKey({...item,sourceFile:'/A/Same.Report/definition/reportExtensions.json'}),itemKey({...item,sourceFile:'/B/Same.Report/definition/reportExtensions.json'}));
assert.notEqual(itemKey(item),itemKey({...item,sourceKind:'model'}));
var counts=detailCounts({usageDetails:allReportIssues});
assert.equal(counts.reports,2);assert.equal(counts.pages,2);
var tree=renderUsageDetails({usageDetails:allReportIssues});
assert.equal((tree.match(/<details open>/g)||[]).length,2);
assert(tree.includes('/A/Same.Report')&&tree.includes('/B/Same.Report'));
chosenReports=[{name:'Same',path:'C:/A/Same.Report'},{name:'Same',path:'C:/B/Same.Report'}];
assert.equal(getReportPathForReference({report:'Same',reportPath:['c:','b','same.report'].join(String.fromCharCode(92))}),'C:/B/Same.Report');
assert.equal(getReportPathByName('Same',['c:','a','same.report','definition','reportExtensions.json'].join(String.fromCharCode(92))),'C:/A/Same.Report');
''')
    result = subprocess.run([shutil.which('node'), str(harness)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_v2_preserves_inventory_polish_and_passes_exact_reference_builders():
    source = TEMPLATE.read_text()
    assert "filename='detail-workspace.js'" in source
    assert 'getReportPathForReference(issue)' in js_function(source, 'reportIssueCleanupEntry')
    assert 'getReportPathForReference(issue)' in js_function(source, 'reportIssueActionEntry')
    assert 'getReportPathForReference(ref)' in js_function(source, 'staleCleanupEntriesForItem')
    assert 'reportReferenceId(issue) !== reportIssueReportFilter' in js_function(source, 'filterReportIssues')
    assert 'reports.map(function(report) { return reportIssueOptionHtml(report, reportReferenceLabel(report)' in js_function(source, 'renderReportHealthControls')
