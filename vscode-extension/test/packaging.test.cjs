const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const manifest = require('../package.json');
const root = path.join(__dirname, '..');

test('Mac acceptance resolves current Code bundles and retains older Electron bundles', t => {
  const { resolveVSCodeExecutable } = require('../scripts/vscode-executable.cjs');
  const directory = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'smc-mac-host-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const old = path.join(directory, 'Electron'), current = path.join(directory, 'Code');
  fs.writeFileSync(old, 'old executable fixture');
  assert.equal(resolveVSCodeExecutable(old, 'darwin'), old);
  fs.renameSync(old, current);
  assert.equal(resolveVSCodeExecutable(old, 'darwin'), current);
  assert.throws(() => resolveVSCodeExecutable(old, 'linux'), /not found/);
  fs.unlinkSync(current);
  assert.throws(() => resolveVSCodeExecutable(old, 'darwin'), /not found/);
});

test('release version agrees with lockfile, package output and changelog', () => {
  const lock = require('../package-lock.json');
  assert.equal(manifest.version, '0.1.8');
  assert.equal(manifest.publisher, 'MrPerfectH');
  assert.equal(`${manifest.publisher}.${manifest.name}`, 'MrPerfectH.semantic-model-cleaner');
  assert.equal(lock.version, manifest.version);
  assert.equal(lock.packages[''].version, manifest.version);
  assert.equal(manifest.scripts.package, 'node scripts/package.cjs');
  assert.match(fs.readFileSync(path.join(root, 'CHANGELOG.md'), 'utf8'),
    new RegExp(`^## ${manifest.version.replaceAll('.', '\\.')} — unpublished pre-release$`, 'm'));
});

test('listing has its own 256px PNG rather than the generic extension icon', () => {
  assert.equal(manifest.icon, 'media/cleaner.png');
  const png = fs.readFileSync(path.join(root, manifest.icon));
  assert.deepEqual(png.subarray(0, 8), Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  assert.equal(png.toString('ascii', 12, 16), 'IHDR');
  assert.equal(png.readUInt32BE(16), 256);
  assert.equal(png.readUInt32BE(20), 256);
  assert.equal(png[25], 6, 'RGBA image');
  assert.ok(png.length > 1000, 'listing icon contains image data');
});

test('existing Cleaner launch entry uses a self-contained monochrome mask', () => {
  const containers = manifest.contributes.viewsContainers.activitybar;
  assert.equal(containers.length, 1);
  assert.equal(containers[0].id, 'semanticModelCleaner');
  assert.equal(containers[0].title, 'Cleaner');
  assert.equal(containers[0].icon, 'media/cleaner-broom.svg');
  assert.notEqual(containers[0].icon, manifest.icon);
  const svg = fs.readFileSync(path.join(root, containers[0].icon), 'utf8');
  assert.match(svg, /viewBox="0 0 24 24"/);
  assert.match(svg, /fill="#fff"/);
  assert.match(svg, /<path /);
  assert.doesNotMatch(svg, /currentColor|transform=|clipPath|stroke=|fill="none"|<image|<script|<style|href=|url\(|opacity=/i);
  const ignore = fs.readFileSync(path.join(root, '.vscodeignore'), 'utf8');
  assert.doesNotMatch(ignore, /^media(?:\/|$)/m);
});
