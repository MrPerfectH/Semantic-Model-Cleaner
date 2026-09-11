"""Schema coverage presentation and bounded evidence selection."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from semantic_model_cleaner import webapp


def test_schema_evidence_contract_and_result_installation():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required for UI contract test')
    script = Path(webapp.__file__).parent / 'static/schema-evidence.js'
    harness = '''
const assert = require('node:assert/strict');
const headings = [];
function element(tag) { return {tag, children:[], dataset:{},
  appendChild(child){this.children.push(child);},
  insertBefore(child){this.children.unshift(child);},
  setAttribute(){}, addEventListener(){}, replaceChildren(){this.children=[];}
}; }
const host=element('div');
global.document={head:element('head'),getElementById(){return host;},createElement(tag){const el=element(tag);if(tag==='summary')headings.push(el);return el;}};
global.window={};let installed;
global.setResultsData=function(data){installed=data;return 17;};
require(SCRIPT);
const helper=window.smcSchemaEvidence;
assert.match(helper.title(null), /unavailable/);
assert.match(helper.title({ok:true,complete:false,counts:{valid:0,invalid:0,not_validated:2}}), /2 not validated.*incomplete coverage/);
const files=Array.from({length:10003},(_,i)=>({path:'report-'+i+'/page.json',status:i%2?'valid':'not_validated',reason:'missing_schema'}));
const data={files};
assert.equal(helper.selectFiles(data,'all','',0).files.length,10);
assert.equal(helper.selectFiles(data,'all','',999999).files.length,3);
assert.equal(helper.selectFiles(data,'attention','',0).total,5002);
assert.equal(helper.selectFiles(data,'not_validated','report-10000/',0).total,1);
assert.equal(helper.selectFiles(data,'invalid','',0).total,0);
const result={schemaValidation:{complete:false,counts:{valid:1,invalid:0,not_validated:2}}};
assert.equal(setResultsData(result),17);assert.equal(installed,result);
assert.match(headings[0].textContent,/incomplete coverage/);
setResultsData({items:[]});assert.match(headings[0].textContent,/unavailable/);
'''.replace('SCRIPT', json.dumps(str(script)))
    subprocess.run([node, '-e', harness], check=True, capture_output=True, text=True)


@pytest.mark.parametrize('layout', ['index.html', 'index_v2.html'])
def test_both_layouts_load_shared_evidence(layout):
    template = Path(webapp.__file__).parent / 'templates' / layout
    text = template.read_text()
    assert text.index("filename='analysis-jobs.js'") < text.index("filename='schema-evidence.js'")
    response = webapp.app.test_client().get('/static/schema-evidence.js')
    assert response.status_code == 200
