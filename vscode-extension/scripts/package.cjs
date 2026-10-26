// Every published package must contain a native engine for its declared target.
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { createHash } = require('node:crypto');
const root = path.resolve(__dirname, '..');
const { name, version } = require('../package.json');
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'engine/manifest.json'), 'utf8'));
const target = `${manifest.platform}-${manifest.arch}`;
const sourceVersion = fs.readFileSync(path.join(root, '../pyproject.toml'), 'utf8').match(/^version = "([^"]+)"$/m)?.[1];
if (!sourceVersion || manifest.engineVersion !== sourceVersion)
  throw new Error('The staged engine version differs from the source version. Rebuild the engine.');
if (manifest.platform !== process.platform || manifest.arch !== process.arch || manifest.protocol !== 1)
  throw new Error('Build the engine on the target platform before packaging.');
const expected = process.platform === 'win32' ? 'smc-engine.exe' : 'smc-engine';
if (manifest.executable !== expected || !fs.statSync(path.join(root, 'engine', expected)).isFile())
  throw new Error('The staged engine executable is missing or incompatible.');
const vsce = require.resolve('@vscode/vsce/vsce');
const output = `${name}-${version}-${target}.vsix`;
execFileSync(process.execPath, [vsce, 'package', '--pre-release', '--no-dependencies',
  '--target', target, '--out', output], { cwd: root, stdio: 'inherit' });
const checksum = createHash('sha256').update(fs.readFileSync(path.join(root, output))).digest('hex');
fs.writeFileSync(path.join(root, `${output}.sha256`), `${checksum}  ${output}\n`);
