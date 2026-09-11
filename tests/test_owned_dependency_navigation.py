"""Dependency links preserve report ownership even when display names collide."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).parents[1]


def js_function(source, name):
    start = source.index('function ' + name + '(')
    line_end = source.index('\n', start)
    if source[start:line_end].rstrip().endswith('}'):
        return source[start:line_end]
    return source[start:source.index('\n}', line_end) + 2]


@pytest.mark.parametrize('layout', ['index.html', 'index_v2.html'])
@pytest.mark.skipif(not shutil.which('node'), reason='Node.js unavailable')
def test_dependency_navigation_uses_exact_report_owner(tmp_path, layout):
    source = (ROOT / 'src/semantic_model_cleaner/templates' / layout).read_text()
    names = ['isReportItem', 'itemKey', 'parseItemRefText', 'getItemsByRefText', 'formatLinkedRef', 'bindDetailLinks']
    harness = tmp_path / 'navigation.cjs'
    harness.write_text("const assert = require('node:assert/strict');\nfunction esc(x){return String(x);}\n"
        + '\n'.join(js_function(source, name) for name in names) + r'''
const common={type:'Measure',table:'Sales',name:'Local',sourceKind:'report'};
var allItems=[{...common,sourceFile:'/A/Same.Report/definition/reportExtensions.json'},
 {...common,sourceFile:'/B/Same.Report/definition/reportExtensions.json'}];
assert.deepEqual(getItemsByRefText(allItems[1]),[allItems[1]]);
assert.deepEqual(getItemsByRefText(common),[]);
assert.deepEqual(getItemsByRefText({...common,sourceFile:'/Unknown.Report/definition/reportExtensions.json'}),[]);
const html=formatLinkedRef(allItems[1]);
assert(html.includes('data-item-key="'+itemKey(allItems[1])+'"'));
assert(html.includes('/B/Same.Report'));
assert(!html.includes('/A/Same.Report'));
assert(!formatLinkedRef('Sales[Local]').includes('<a'));
let opened=null;
function openItemDetails(key){opened=key;}
const link={dataset:{itemKey:itemKey(allItems[1])}};
bindDetailLinks({querySelectorAll(selector){return selector==='.detail-item-link'?[link]:[];}});
link.onclick({preventDefault(){}});
assert.equal(opened,itemKey(allItems[1]));
''')
    result = subprocess.run([shutil.which('node'), str(harness)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'item.dependencyItems ||' in source
    assert 'item.dependentItems ||' in source
    assert 'current.dependentItems ||' in source
