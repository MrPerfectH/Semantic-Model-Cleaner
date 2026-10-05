"""Exercise the shared request helper used by both UI layouts."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js unavailable')
def test_request_headers_origin_checks_and_downloads(tmp_path):
    source = Path(__file__).parents[1] / 'src/semantic_model_cleaner/static/local-http.js'
    harness = tmp_path / 'local-http.cjs'
    harness.write_text(r'''
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const requests = [], downloads = [], revoked = [], alerts = [];
const token = 'per-launch-secret';
const context = {URL, Headers, Promise, Object, Error, decodeURIComponent,
  setTimeout: fn => fn(),
  location: {href: 'http://127.0.0.1:5001/?ui=v2', origin: 'http://127.0.0.1:5001'},
  document: {
    querySelector: selector => {assert.equal(selector, 'meta[name="smc-local-token"]'); return {content: token};},
    body: {appendChild(){}},
    createElement: () => ({click(){downloads.push({href: this.href, name: this.download});}, remove(){}}),
  },
  alert: message => alerts.push(message),
  fetch: async (url, options) => {
    requests.push({url, options});
    return {ok: true, headers: new Headers({'Content-Disposition': 'attachment; filename="analysis.xlsx"'}),
      blob: async () => new Blob(['export'])};
  },
};
context.URL.createObjectURL = blob => {assert.equal(blob.size, 6); return 'blob:local-export';};
context.URL.revokeObjectURL = url => revoked.push(url);
context.window = context;
vm.createContext(context); vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), context);
(async () => {
  await context.smcFetch('/api/plans', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
  await context.smcFetch('/api/analysis-jobs/id', {method:'DELETE'});
  await context.smcFetch('/api/browse');
  for (const {url, options} of requests) {
    assert.equal(options.headers.get('X-SMC-Token'), token);
    assert.equal(options.mode, 'same-origin');
    assert.equal(options.redirect, 'error');
    assert.equal(url.includes(token), false);
  }
  assert.equal(requests[1].options.headers.get('Content-Type'), 'application/json');
  await assert.rejects(context.smcFetch('http://foreign.example/api/plans'));
  await assert.rejects(context.smcFetch('http://127.0.0.1:9999/api/plans'));
  await assert.rejects(context.smcFetch('/static/script.js'));
  assert.equal(requests.length, 3);
  await context.smcDownload('/api/export?format=xlsx');
  assert.deepEqual(downloads, [{href:'blob:local-export', name:'analysis.xlsx'}]);
  assert.deepEqual(revoked, ['blob:local-export']);
  assert.equal(alerts.length, 0);
})().catch(error => {console.error(error); process.exitCode = 1;});
''', encoding='utf-8')
    subprocess.run([shutil.which('node'), str(harness), str(source)], check=True, capture_output=True, text=True)
