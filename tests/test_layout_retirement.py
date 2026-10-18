"""The workspace has one layout and preserves exact report ownership."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest
from semantic_model_cleaner import webapp

ROOT = Path(__file__).parents[1]
TEMPLATE = ROOT / 'src/semantic_model_cleaner/templates/index_v2.html'


@pytest.mark.parametrize('query', ['', '?ui=classic', '?ui=CLASSIC', '?ui=v2', '?ui=new', '?ui=nonsense'])
@pytest.mark.parametrize('cookie', [None, 'classic', 'v2', 'unknown'])
def test_legacy_layout_inputs_always_render_v2_without_a_switch(query, cookie):
    client = webapp.app.test_client()
    if cookie is not None:
        client.set_cookie('smc_ui', cookie)
    for url in ('/' + query, '/'):
        response = client.get(url)
        assert response.status_code == 200
        assert b'id="scopeChip"' in response.data
        assert b'detail-workspace.js' in response.data
        for retired in (b'Classic layout', b'ui-switch-link', b'/?ui=', b'ClassicPlans', b'classic-plans', b'railCompare', b'compareFlow'):
            assert retired not in response.data
        assert client.get_cookie('smc_ui') is None


def test_retired_assets_are_absent_and_cannot_be_served():
    assert not (ROOT / 'src/semantic_model_cleaner/templates/index.html').exists()
    client = webapp.app.test_client()
    for asset in ('classic-plans.js', 'classic-plans.css'):
        assert not (ROOT / 'src/semantic_model_cleaner/static' / asset).exists()
        assert client.get('/static/' + asset).status_code == 404


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js unavailable')
def test_v2_same_named_report_mutations_and_keys_use_exact_owner(tmp_path):
    html = TEMPLATE.read_text(encoding="utf-8")
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
        "assert.notEqual(itemKey({...item,sourceFile:'/A/Same.Report/definition/reportExtensions.json'}),itemKey({...item,sourceFile:'/B/Same.Report/definition/reportExtensions.json'}));\n", encoding="utf-8")
    result = subprocess.run([shutil.which('node'), str(harness)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
