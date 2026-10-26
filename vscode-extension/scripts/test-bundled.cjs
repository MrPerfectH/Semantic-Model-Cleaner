// CI entry: test the packaged extension using its bundled engine and a disposable profile.
const { downloadAndUnzipVSCode } = require('@vscode/test-electron');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const root = path.resolve(__dirname, '..');
  const { name, version } = require('../package.json');
  const vsix = path.join(root, `${name}-${version}-${process.platform}-${process.arch}.vsix`);
  if (!fs.existsSync(vsix)) throw new Error(`Package the native VSIX first: ${vsix}`);
  const executable = await downloadAndUnzipVSCode('stable');
  execFileSync(process.execPath, [path.join(__dirname, 'integration.cjs')], { cwd: root, stdio: 'inherit',
    env: { ...process.env, SMC_TEST_VSIX: vsix, SMC_TEST_BUNDLED: '1', SMC_VSCODE_EXECUTABLE: executable } });
})().catch(error => { console.error(error); process.exitCode = 1; });
