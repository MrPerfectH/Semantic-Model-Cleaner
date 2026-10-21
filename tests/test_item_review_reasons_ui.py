"""Inline Review explanations preserve recorded evidence and escape model text."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('layout', ['index_v2.html'])
def test_items_show_all_review_reasons_without_details_or_hover(tmp_path, layout):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js unavailable')
    template = Path(__file__).parents[1] / 'src/semantic_model_cleaner/templates' / layout
    html = template.read_text()
    assert "'<td class=\"cell-risk\">' + itemCleanupCell(item)" in html
    assert '.item-review-reasons' in html and 'overflow-wrap: anywhere' in html
    script = tmp_path / 'review.cjs'
    script.write_text(r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[2], 'utf8');
const context = {
  esc: s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  deleteSafetyBadge: item => '<span>' + item.deleteSafety + '</span>',
  deleteSafetyValue: item => item.deleteSafety,
  reviewTriggers: item => item.reviewTriggers || [],
  cleanupHelpText: () => 'Review the available evidence before deletion.'
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function itemCleanupCell('), source.indexOf('function legendItemHtml(')), context);
const reasons = ['Item is hidden', 'Sort column required by retained T[<First>]', 'Sort column required by retained T[Second & "last"]'];
const item = { deleteSafety: 'Review', reviewTriggers: reasons };
const before = JSON.stringify(item);
const result = context.itemCleanupCell(item);
assert.ok(result.startsWith('<span>Review</span><ul'));
assert.ok(result.includes('Hidden item: confirmation required before deletion.'));
assert.ok(result.includes('Sort column required by retained T[&lt;First&gt;]'));
assert.ok(result.includes('Sort column required by retained T[Second &amp; &quot;last&quot;]'));
assert.equal((result.match(/<li>/g) || []).length, 3);
assert.ok(!result.includes('<details') && !result.includes('title='));
assert.equal(JSON.stringify(item), before);
const field = context.itemCleanupCell({deleteSafety:'Review', reviewTriggers:["Entity type requires confirmation: 'FP' is a field parameter, which this tool always asks you to confirm before deletion. Nothing in the model or the selected reports uses it."]});
assert.ok(field.includes('Field parameter: confirmation required before deletion.'));
assert.ok(!field.includes('Nothing in the model'));
const unknown = context.itemCleanupCell({deleteSafety:'Review',reviewTriggers:['<img src=x onerror=alert(1)>']});
assert.ok(unknown.includes('&lt;img') && !unknown.includes('<img'));
assert.ok(context.itemCleanupCell({deleteSafety:'Review'}).includes('Review the available evidence'));
for (const value of ['Safe','Keep','Blocked']) assert.equal(context.itemCleanupCell({deleteSafety:value,reviewTriggers:reasons}), '<span>' + value + '</span>');
''')
    result = subprocess.run([node, str(script), str(template)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
