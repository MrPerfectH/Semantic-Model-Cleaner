// Isolated desktop host + browser smoke. Never reads/writes a user's VS Code profile.
// SMC_TEST_VSIX=<file> installs that package into the disposable extensions
// directory and tests it instead of this source folder.
const { runTests } = require('@vscode/test-electron');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
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
  // No spaces: test-electron starts Windows hosts through a shell that splits them.
  const project = path.join(temp, 'Sales-Project');
  const second = path.join(temp, 'Demo-Project');
  await multiModelProject(repo, project);
  await fs.cp(path.join(repo, 'src/semantic_model_cleaner/demo_workspace'), second, { recursive: true });
  const python = process.env.SMC_TEST_PYTHON || path.join(repo, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  await fs.mkdir(path.join(temp, 'profile/User'), { recursive: true });
  await fs.writeFile(path.join(temp, 'profile/User/settings.json'), JSON.stringify({
    'semanticModelCleaner.pythonPath': python,
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
    // Windows builds keep resources in a commit folder: pass SMC_VSCODE_CLI_JS there.
    const cliJs = process.env.SMC_VSCODE_CLI_JS || path.join(app, 'out/cli.js');
    execFileSync(executable, [cliJs, '--user-data-dir', path.join(temp, 'profile'),
      '--extensions-dir', extensions, '--install-extension', vsix, '--force'],
      { stdio: 'inherit', env: { ...process.env, ELECTRON_RUN_AS_NODE: '1', VSCODE_DEV: '' } });
    // The runner needs a development folder; this empty one contributes nothing.
    development = path.join(temp, 'runner');
    await fs.mkdir(development);
    await fs.writeFile(path.join(development, 'package.json'), JSON.stringify(
      { name: 'smc-test-runner', publisher: 'test', version: '0.0.0', engines: { vscode: '*' } }));
  }
  try {
    await runTests({
      ...(process.env.SMC_VSCODE_EXECUTABLE ? { vscodeExecutablePath: process.env.SMC_VSCODE_EXECUTABLE } : {}),
      extensionDevelopmentPath: development,
      extensionTestsPath: path.join(root, 'test/integration-host.cjs'),
      extensionTestsEnv: { SMC_TEST_CDP_PORT: String(port), SMC_TEST_ARTIFACTS: artifacts,
        SMC_TEST_PROJECT: project, SMC_TEST_SECOND_PROJECT: second, SMC_USER_DIR: path.join(temp, 'smc-user'),
        SMC_TEST_EXPECT_VERSION: version, SMC_TEST_EXPECT_EXTENSIONS: vsix ? extensions : '' },
      launchArgs: [project, '--user-data-dir', path.join(temp, 'profile'), '--extensions-dir', extensions,
        ...(vsix ? [] : ['--disable-extensions']), '--disable-workspace-trust', '--skip-welcome', '--skip-release-notes',
        `--remote-debugging-port=${port}`]
    });
  } finally { await fs.rm(temp, { recursive: true, force: true }); }
})().catch(error => { console.error(error); process.exitCode = 1; });
