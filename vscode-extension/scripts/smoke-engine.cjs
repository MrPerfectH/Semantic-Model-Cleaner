// Exercise the frozen binary through the production launcher with no Python on PATH.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { createHash } = require('node:crypto');
const { launchConfig } = require('../dist/config');
const { startServer, probe } = require('../dist/server');

async function snapshot(root) {
  const result = {};
  for (const entry of await fs.readdir(root, { withFileTypes: true })) {
    const file = path.join(root, entry.name);
    if (entry.isDirectory()) Object.assign(result, await snapshot(file));
    else result[file] = createHash('sha256').update(await fs.readFile(file)).digest('hex');
  }
  return result;
}

(async () => {
  const root = path.resolve(__dirname, '..');
  const extension = process.env.SMC_ENGINE_EXTENSION || root;
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'smc bundled engine '));
  let server;
  const originalPath = process.env.PATH;
  const originalUserDir = process.env.SMC_USER_DIR;
  try {
    const project = path.join(temp, 'Power BI Project');
    await fs.cp(path.join(root, '../src/semantic_model_cleaner/demo_workspace'), project, { recursive: true });
    const before = await snapshot(project);
    process.env.PATH = '';
    process.env.SMC_USER_DIR = path.join(temp, 'user');
    const config = launchConfig(true, () => ({ get: (_, fallback) => fallback }), project, extension);
    const start = () => startServer(config,
      ['https://smoke-panel.vscode-cdn.net', 'vscode-file://vscode-app'],
      new AbortController().signal, line => console.log(line), () => {});
    server = await start();
    const scope = await server.request('/api/vscode/scope', {});
    assert.equal(scope.models.length, 1);
    assert.ok(scope.reports.length > 0);
    const response = await fetch(`http://127.0.0.1:${server.port}/`);
    assert.equal(response.status, 200);
    assert.match(await response.text(), /<html/i);
    const asset = await fetch(`http://127.0.0.1:${server.port}/static/host-scope.js`);
    assert.equal(asset.status, 200);
    const analysis = await server.request('/api/analyze', { model_paths: [scope.model],
      report_paths: scope.reports.map(report => report.path), report_selection: 'exact' });
    assert.ok(analysis.items.length > 0, 'Analysis must return Semantic Model Items.');
    assert.ok(analysis.items.some(item => item.deleteSafety === 'Safe'), 'Clean demo scope must retain Safe recommendations.');
    // Keep the session token in memory; never print it or put it in a URL/file.
    const session = await fetch(`http://127.0.0.1:${server.port}/api/session`);
    assert.equal(session.status, 200);
    const { token } = await session.json();
    for (const format of ['json', 'xlsx']) {
      const exported = await fetch(`http://127.0.0.1:${server.port}/api/export?format=${format}`,
        { headers: { 'X-SMC-Token': token } });
      assert.equal(exported.status, 200, `${format} export failed`);
      if (format === 'json') {
        const value = await exported.json();
        assert.equal(value.ok, true);
        assert.equal(value.items.length, analysis.items.length);
      } else {
        const bytes = Buffer.from(await exported.arrayBuffer());
        assert.equal(bytes.readUInt32LE(0), 0x04034b50, 'XLSX must be a ZIP archive');
        for (const entry of ['[Content_Types].xml', 'xl/workbook.xml', 'xl/worksheets/sheet1.xml'])
          assert.ok(bytes.includes(Buffer.from(entry)), `XLSX is missing ${entry}`);
      }
    }
    const { plan } = await server.request('/api/plans', { model_path: scope.model,
      report_paths: scope.reports.map(report => report.path), operations: [
        { kind: 'actions', actions: [{ action: 'hide', table: 'Sales', name: 'Revenue', item_type: 'Measure' }] }
      ] });
    assert.ok(plan.changes.length > 0 && plan.changes.every(change => change.diff));
    assert.deepEqual(await snapshot(project), before, 'Preparing a plan must not change project files');
    const planPath = `/api/plans/${plan.id}`;
    // Verification returns 409 until the reviewed output bytes have been applied.
    const unmodified = await fetch(`http://127.0.0.1:${server.port}${planPath}/verify`, {
      method: 'POST', headers: { 'X-SMC-Token': token, 'Content-Type': 'application/json' }, body: '{}'
    });
    assert.equal(unmodified.status, 409);
    assert.equal((await unmodified.json()).state, 'original');
    assert.equal((await server.request(`${planPath}/apply`, {})).receipt.status, 'applied');
    assert.notDeepEqual(await snapshot(project), before, 'Apply must change the disposable model');
    assert.equal((await server.request(`${planPath}/verify`, {})).state, 'applied');
    assert.equal((await server.request(`${planPath}/restore`, {})).ok, true);
    assert.deepEqual(await snapshot(project), before, 'Restore must recover every original byte');
    const port = server.port;
    await server.stop();
    await assert.rejects(probe(port, 'irrelevant', new AbortController().signal));
    server = await start();
    assert.equal((await server.request('/api/vscode/scope', {})).models.length, 1);
    console.log('Bundled engine: startup, assets, analysis, JSON/XLSX export, plan apply/verify/restore, shutdown and restart passed without Python on PATH.');
  } finally {
    if (server) await server.stop();
    if (originalPath === undefined) delete process.env.PATH; else process.env.PATH = originalPath;
    if (originalUserDir === undefined) delete process.env.SMC_USER_DIR; else process.env.SMC_USER_DIR = originalUserDir;
    await fs.rm(temp, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
