"""Naming convention repeatability and browser draft lifetime regressions."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from semantic_model_cleaner import review_policy, webapp


@pytest.mark.parametrize('case', ['preserve', 'title', 'pascal', 'snake'])
@pytest.mark.parametrize('prefix,suffix', [('QA ', ''), ('', ' USD'), ('QA ', ' USD')])
def test_literal_affixes_do_not_accumulate(case, prefix, suffix):
    rule = {'find': '', 'replace': '', 'prefix': prefix, 'suffix': suffix, 'case': case}
    first = review_policy._transform('netRevenue', rule)
    assert review_policy._transform(first, rule) == first
    assert not prefix or first.startswith(prefix)
    assert not suffix or first.endswith(suffix)


def test_naming_drafts_survive_refresh_reopen_and_keep_saved_policy_separate():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required for browser draft contract')
    path = Path(webapp.__file__).parent / 'static/policy-workspace.js'
    script = path.read_text()
    start = script.index('  function describeRule(')
    helpers = script[start:script.index('  var storage;', start)]
    harness = '''
const assert=require('node:assert/strict');
const backing=new Map();const storage={getItem(key){return backing.get(key)||null;},setItem(key,value){backing.set(key,value);}};
''' + helpers + '''
const saved=[{id:'qa',prefix:'QA ',case:'preserve'}];
let store=namingDraftStore(storage);
let draft=store.read('/project',saved);
draft.rules.push({id:'suffix',suffix:' USD'});draft.form={policyRuleId:'unfinished',policyRulePrefix:'Test '};
assert.equal(saved.length,1);assert.equal(store.write('/project',draft),true);
// Refresh with unchanged saved policy, switch tabs, or close/reopen.
assert.equal(store.read('/project',saved).rules.length,2);
// A fresh store represents a page reload in the same browser tab.
store=namingDraftStore(storage);draft=store.read('/project',saved);
assert.equal(draft.rules.length,2);assert.equal(draft.form.policyRuleId,'unfinished');
assert.equal(store.read('/different-project',[]).rules.length,0);
const changed=[{id:'different',prefix:'Other '}];
assert.equal(store.conflicts(draft,changed),true);
assert.equal(store.read('/project',changed).rules.length,2);
assert.equal(store.reset('/project',changed).rules[0].id,'different');
assert.deepEqual(store.read('/project',changed).form,{});
// Storage can be disabled; in-memory drafts must still survive Close/Refresh.
const memory=namingDraftStore(null),local=memory.read('/local',[]);local.rules.push({id:'local'});
assert.equal(memory.write('/local',local),false);assert.equal(memory.read('/local',[]).rules.length,1);
assert.equal(describeRule({prefix:'QA ',case:'preserve'}),'Ensure prefix “QA ”');
assert.equal(describeRule({find:'old',replace:''}),'Replace “old” with empty text');
assert.equal(describeRule({case:'snake'}),'snake_case');
'''
    completed = subprocess.run([node, '-e', harness], capture_output=True, text=True)
    assert completed.returncode == 0, json.dumps({'stdout': completed.stdout, 'stderr': completed.stderr})
