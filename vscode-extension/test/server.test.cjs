const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const http = require('node:http');
const { startServer, ServerManager, SafeLines, Cancelled, probe } = require('../dist/server');
const { launchConfig, validateAncestors } = require('../dist/config');
const origins = ['https://specific-panel.vscode-cdn.net', 'vscode-file://vscode-app'];
const config = mode => ({ executable: process.execPath, args: [path.join(__dirname, 'fake-server.cjs'), mode], cwd: __dirname });
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function isClosed(port) {
  await assert.rejects(probe(port, 'irrelevant', new AbortController().signal));
}

test('untrusted workspace cannot even read executable settings', () => {
  let reads = 0;
  assert.throws(() => launchConfig(false, () => { reads++; }, '/tmp'), /Trust/);
  assert.equal(reads, 0);
});
test('Python executable with spaces is one argv item; no shell arguments', () => {
  const c = launchConfig(true, () => ({ get: (key, fallback) => key === 'pythonPath' ? '/tmp/python env/bin/python' : fallback }), '/tmp');
  assert.equal(c.executable, '/tmp/python env/bin/python');
  assert.deepEqual(c.args, ['-I', '-m', 'semantic_model_cleaner.web']);
  for (const value of ['python -c evil', './python', 'run.cmd', 'bad\nname'])
    assert.throws(() => launchConfig(true, () => ({ get: () => value }), '/tmp'));
});
test('exact origins only', () => {
  assert.deepEqual(validateAncestors(origins), origins);
  for (const value of [['*'], ['https:'], ['https://*.vscode-cdn.net'], ['null'], ['http://localhost:80'], ['vscode-file://vscode-app']])
    assert.throws(() => validateAncestors(value));
});
test('chunk boundaries and oversized lines never expose a launch token', () => {
  const token = 'a'.repeat(64), output = [];
  const lines = new SafeLines(token, line => output.push(line));
  lines.push('secret ' + token.slice(0, 32)); lines.push(token.slice(32) + '\n');
  lines.push('x'.repeat(8200) + token.slice(0, 32)); lines.push(token.slice(32) + '\n');
  assert.deepEqual(output, ['secret [redacted]', '[overlong server log line omitted]']);
});
test('owned process verifies readiness and closes its port on stop', async () => {
  const server = await startServer(config('ok'), origins, new AbortController().signal, () => {}, () => {});
  await server.stop(); await server.stop(); await isClosed(server.port);
});
for (const mode of ['wrong', 'malformed', 'exit', 'hang']) {
  test(`startup ${mode} fails and cleans up`, async () => {
    await assert.rejects(startServer(config(mode), origins, new AbortController().signal, () => {}, () => {}, 500));
  });
}
test('missing executable is actionable', async () => {
  await assert.rejects(startServer({ ...config('ok'), executable: '/does/not/exist' }, origins,
    new AbortController().signal, () => {}, () => {}), /Could not start SMC/);
});
test('cancellation during startup stops pending process', async () => {
  const abort = new AbortController();
  const running = startServer(config('slow'), origins, abort.signal, () => {}, () => {});
  abort.abort(); await assert.rejects(running, Cancelled);
});
test('unexpected process exit is reported', async () => {
  let exited;
  const event = new Promise(resolve => { exited = resolve; });
  const running = await startServer(config('dies'), origins, new AbortController().signal, () => {}, exited);
  await event; await running.stop(); await isClosed(running.port);
});
test('rapid start/start/stop cancels all superseded launches', async () => {
  const manager = new ServerManager();
  const first = manager.start(config('slow'), origins, () => {}, () => {});
  const observedFirst = first.catch(e => e);
  await pause(30);
  const second = manager.start(config('slow'), origins, () => {}, () => {});
  const observedSecond = second.catch(e => e);
  await manager.stop();
  assert.ok(await observedFirst instanceof Cancelled);
  assert.ok(await observedSecond instanceof Cancelled);
  const last = await manager.start(config('ok'), origins, () => {}, () => {});
  await manager.stop(); await isClosed(last.port);
});
test('unrelated HTTP service cannot satisfy readiness', async () => {
  const unrelated = http.createServer((_, response) => response.end('{"protocol":1,"instance":"another"}'));
  await new Promise(resolve => unrelated.listen(0, '127.0.0.1', resolve));
  try { await assert.rejects(probe(unrelated.address().port, 'a'.repeat(64), new AbortController().signal), /verification/); }
  finally { await new Promise(resolve => unrelated.close(resolve)); }
});
