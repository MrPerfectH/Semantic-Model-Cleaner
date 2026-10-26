// Isolated desktop host + browser smoke. Never reads/writes a user's VS Code profile.
// SMC_TEST_VSIX=<file> installs that package into the disposable extensions
// directory and tests it instead of this source folder.
const { runTests } = require('@vscode/test-electron');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const { createHash } = require('node:crypto');
// Some Electron-based agent hosts inherit this; it turns VS Code into plain Node.
delete process.env.ELECTRON_RUN_AS_NODE;

// Two models (TestModel: 2 Reports, ProductQA: 2 Reports) and one Report with a
// broken binding, so default/deselect/switch behavior is meaningful.
async function multiModelProject(repo, project) {
  await fs.cp(path.join(repo, 'src/semantic_model_cleaner/demo_workspace'), project, { recursive: true });
  const qa = path.join(repo, 'examples/product-qa-workspace');
  await fs.cp(path.join(qa, 'Models'), path.join(project, 'Models'), { recursive: true });
  await fs.cp(path.join(qa, 'Reports'), path.join(project, 'Reports'), { recursive: true });
  const bind = async (name, model) => {
    await fs.cp(path.join(project, 'Reports/TestReport.Report'), path.join(project, `Reports/${name}.Report`), { recursive: true });
    await fs.writeFile(path.join(project, `Reports/${name}.Report/definition.pbir`), JSON.stringify(
      { version: '4.0', datasetReference: { byPath: { path: `../../Models/${model}.SemanticModel` } } }));
  };
  await bind('Sales Overview', 'TestModel');
  await fs.cp(path.join(project, 'Reports/Executive.Report'), path.join(project, 'Reports/Operations.Report'), { recursive: true });
  await bind('Legacy Draft', 'TestModel');
  await fs.writeFile(path.join(project, 'Reports/Legacy Draft.Report/definition.pbir'), '{ broken');
}

(async () => {
  const root = path.resolve(__dirname, '..');
  const repo = path.dirname(root);
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'smc-vscode-'));
  try {
  // No spaces: test-electron starts Windows hosts through a shell that splits them.
  const project = path.join(temp, 'Sales-Project');
  const second = path.join(temp, 'Demo-Project');
  await multiModelProject(repo, project);
  await fs.cp(path.join(repo, 'src/semantic_model_cleaner/demo_workspace'), second, { recursive: true });
  const bundled = process.env.SMC_TEST_BUNDLED === '1';
  if (bundled && !process.env.SMC_TEST_VSIX) throw new Error('Bundled acceptance requires SMC_TEST_VSIX.');
  const python = process.env.SMC_TEST_PYTHON || path.join(repo, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  await fs.mkdir(path.join(temp, 'profile/User'), { recursive: true });
  await fs.writeFile(path.join(temp, 'profile/User/settings.json'), JSON.stringify({
    ...(bundled ? {} : { 'semanticModelCleaner.pythonPath': python }),
    'window.restoreWindows': 'none', 'workbench.startupEditor': 'none'
  }));
  const listener = net.createServer();
  await new Promise(resolve => listener.listen(0, '127.0.0.1', resolve));
  const port = listener.address().port;
  await new Promise(resolve => listener.close(resolve));
  const vsix = process.env.SMC_TEST_VSIX ? path.resolve(process.env.SMC_TEST_VSIX) : '';
  const version = require('../package.json').version;
  const artifacts = path.join(root, 'integration-artifacts', version + (vsix ? '-vsix' : ''));
  await fs.mkdir(artifacts, { recursive: true });
  const extensions = path.join(temp, 'extensions');
  let development = root;
  if (vsix) {
    if (!process.env.SMC_VSCODE_EXECUTABLE) throw new Error('SMC_TEST_VSIX requires SMC_VSCODE_EXECUTABLE.');
    // Run the product's own CLI entry point in Node mode: no shell, no .cmd wrapper.
    const executable = process.env.SMC_VSCODE_EXECUTABLE;
    const app = process.platform === 'darwin'
      ? path.resolve(path.dirname(executable), '../Resources/app')
      : path.join(path.dirname(executable), 'resources/app');
    const cliCandidates = [path.join(app, 'out/cli.js')];
    // Some Windows distributions put resources beneath a version/commit directory.
    if (process.platform === 'win32') {
      for (const entry of await fs.readdir(path.dirname(executable), { withFileTypes: true }))
        if (entry.isDirectory() && /^[a-f0-9]{6,40}$/i.test(entry.name))
          cliCandidates.push(path.join(path.dirname(executable), entry.name, 'resources/app/out/cli.js'));
    }
    const cliJs = process.env.SMC_VSCODE_CLI_JS || (await Promise.all(cliCandidates.map(async candidate =>
      await fs.stat(candidate).then(value => value.isFile() ? candidate : undefined).catch(() => undefined)))).find(Boolean);
    if (!cliJs) throw new Error('Cannot locate the VS Code CLI. Set SMC_VSCODE_CLI_JS explicitly.');
    execFileSync(executable, [cliJs, '--user-data-dir', path.join(temp, 'profile'),
      '--extensions-dir', extensions, '--install-extension', vsix, '--force'],
      { stdio: 'inherit', env: { ...process.env, ELECTRON_RUN_AS_NODE: '1', VSCODE_DEV: '' } });
    if (bundled) {
      const installed = [];
      for (const entry of await fs.readdir(extensions, { withFileTypes: true })) {
        if (!entry.isDirectory()) continue;
        const directory = path.join(extensions, entry.name);
        const manifest = JSON.parse(await fs.readFile(path.join(directory, 'package.json'), 'utf8'));
        if (manifest.publisher === 'MrPerfectH' && manifest.name === 'semantic-model-cleaner' && manifest.version === version)
          installed.push(directory);
      }
      if (installed.length !== 1) throw new Error('Expected exactly one installed Cleaner package.');
      const offline = process.env.SMC_TEST_OFFLINE === '1';
      const output = execFileSync(process.execPath, [path.join(__dirname, offline ? 'offline-smoke.cjs' : 'smoke-engine.cjs')], {
        encoding: 'utf8', env: { ...process.env, SMC_ENGINE_EXTENSION: installed[0] }
      });
      await fs.writeFile(path.join(artifacts, 'bundled-engine-smoke.txt'), output);
      console.log(output);
    }
    // The runner needs a development folder; this empty one contributes nothing.
    development = path.join(temp, 'runner');
    await fs.mkdir(development);
    await fs.writeFile(path.join(development, 'package.json'), JSON.stringify(
      { name: 'smc-test-runner', publisher: 'test', version: '0.0.0', engines: { vscode: '*' } }));
  }
    await runTests({
      ...(process.env.SMC_VSCODE_EXECUTABLE ? { vscodeExecutablePath: process.env.SMC_VSCODE_EXECUTABLE } : {}),
      extensionDevelopmentPath: development,
      extensionTestsPath: path.join(root, 'test/integration-host.cjs'),
      extensionTestsEnv: { SMC_TEST_CDP_PORT: String(port), SMC_TEST_ARTIFACTS: artifacts,
        SMC_TEST_PROJECT: project, SMC_TEST_SECOND_PROJECT: second, SMC_USER_DIR: path.join(temp, 'smc-user'),
        SMC_TEST_EXPECT_VERSION: version, SMC_TEST_EXPECT_EXTENSIONS: vsix ? extensions : '',
        SMC_TEST_EXPECT_BUNDLED: bundled ? '1' : '',
        SMC_TEST_OFFLINE: process.env.SMC_TEST_OFFLINE || '',
        SMC_TEST_VSIX_SHA256: vsix ? createHash('sha256').update(await fs.readFile(vsix)).digest('hex') : '' },
      launchArgs: [project, '--user-data-dir', path.join(temp, 'profile'), '--extensions-dir', extensions,
        ...(vsix ? [] : ['--disable-extensions']), '--disable-workspace-trust', '--skip-welcome', '--skip-release-notes',
        `--remote-debugging-port=${port}`]
    });
  } finally { await fs.rm(temp, { recursive: true, force: true }); }
})().catch(error => { console.error(error); process.exitCode = 1; });
