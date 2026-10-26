const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const { createHash } = require('node:crypto');
const { launchConfig } = require('../dist/config');
const { probe } = require('../dist/server');
const empty = () => ({ get: (_, fallback) => fallback });

test('default launch uses only the packaged native engine, including paths with spaces', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'smc engine '));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const directory = path.join(root, 'engine');
  fs.mkdirSync(directory);
  const executable = process.platform === 'win32' ? 'smc-engine.exe' : 'smc-engine';
  const manifest = { protocol: 1, platform: process.platform, arch: process.arch,
    engineVersion: '0.4.0b10', executable };
  const write = value => fs.writeFileSync(path.join(directory, 'manifest.json'), JSON.stringify(value));
  write(manifest);
  fs.writeFileSync(path.join(directory, executable), 'fixture');
  assert.deepEqual(launchConfig(true, empty, root, root), {
    executable: path.join(directory, executable), args: [], cwd: root, engineVersion: '0.4.0b10'
  });
  write({ ...manifest, arch: 'unsupported' });
  assert.throws(() => launchConfig(true, empty, root, root), /matching platform package/);
  write({ ...manifest, executable: '../untrusted' });
  assert.throws(() => launchConfig(true, empty, root, root), /incompatible/);
  for (const malformed of [null, [], 'not a manifest', 1]) {
    write(malformed);
    assert.throws(() => launchConfig(true, empty, root, root), /manifest is incompatible/);
  }
  write(manifest);
  fs.unlinkSync(path.join(directory, executable));
  assert.throws(() => launchConfig(true, empty, root, root), /executable is missing/);
  fs.unlinkSync(path.join(directory, 'manifest.json'));
  assert.throws(() => launchConfig(true, empty, root, root), /missing or damaged/);
});

test('explicit overrides work without a bundle, and Python retains precedence', () => {
  const read = values => () => ({ get: (key, fallback) => values[key] ?? fallback });
  assert.equal(launchConfig(true, read({ executable: 'smc-web' }), '/tmp').executable, 'smc-web');
  const config = launchConfig(true, read({ pythonPath: process.execPath, executable: 'ignored' }), '/tmp');
  assert.equal(config.executable, process.execPath);
  assert.deepEqual(config.args, ['-I', '-m', 'semantic_model_cleaner.web']);
  assert.throws(() => launchConfig(false, () => { throw Error('read settings'); }, '/tmp'), /Trust/);
});

test('readiness rejects a bundled engine with a mismatched version', async () => {
  const token = 'a'.repeat(64);
  const server = http.createServer((_, res) => res.end(JSON.stringify({ protocol: 1,
    engineVersion: 'wrong', instance: createHash('sha256').update(token).digest('hex') })));
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    await assert.rejects(probe(server.address().port, token, new AbortController().signal, 'expected'), /version mismatch/);
    await probe(server.address().port, token, new AbortController().signal, 'wrong');
  } finally { await new Promise(resolve => server.close(resolve)); }
});

test('malformed readiness never exposes response text through a parser error', async () => {
  const token = 'a'.repeat(64);
  const server = http.createServer((_, res) => res.end(token));
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    await assert.rejects(probe(server.address().port, token, new AbortController().signal),
      { message: 'Server instance verification failed.' });
  } finally { await new Promise(resolve => server.close(resolve)); }
});
