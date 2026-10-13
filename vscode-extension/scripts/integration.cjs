// Isolated desktop host + browser smoke. Never reads/writes a user's VS Code profile.
const { runTests } = require('@vscode/test-electron');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
// Some Electron-based agent hosts inherit this; it turns VS Code into plain Node.
delete process.env.ELECTRON_RUN_AS_NODE;
(async () => {
  const root = path.resolve(__dirname, '..');
  const repo = path.dirname(root);
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'smc-vscode-'));
  const project = path.join(temp, 'Demo Project');
  await fs.cp(path.join(repo, 'src/semantic_model_cleaner/demo_workspace'), project, { recursive: true });
  const multiProject = path.join(temp, 'Repository Project');
  const modelDir = 'Models/' + (await fs.readdir(path.join(project, 'Models'))).find(name => name.endsWith('.SemanticModel'));
  const reportDir = 'Reports/' + (await fs.readdir(path.join(project, 'Reports'))).find(name => name.endsWith('.Report'));
  await fs.mkdir(path.join(multiProject, 'Models'), { recursive: true });
  await fs.mkdir(path.join(multiProject, 'Department'), { recursive: true });
  await fs.cp(path.join(project, modelDir), path.join(multiProject, 'Models/Primary.SemanticModel'), { recursive: true });
  await fs.cp(path.join(project, modelDir), path.join(multiProject, 'Department/Secondary.SemanticModel'), { recursive: true });
  for (const [name, target] of [['Primary', '../Models/Primary.SemanticModel'], ['Secondary', '../Department/Secondary.SemanticModel']]) {
    const destination = path.join(multiProject, name + '.Report');
    await fs.cp(path.join(project, reportDir), destination, { recursive: true });
    const definition = JSON.parse(await fs.readFile(path.join(destination, 'definition.pbir'), 'utf8'));
    definition.datasetReference = { byPath: { path: target } };
    await fs.writeFile(path.join(destination, 'definition.pbir'), JSON.stringify(definition));
  }
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
  const artifacts = path.join(root, 'integration-artifacts');
  await fs.mkdir(artifacts, { recursive: true });
  try {
    await runTests({
      ...(process.env.SMC_VSCODE_EXECUTABLE ? { vscodeExecutablePath: process.env.SMC_VSCODE_EXECUTABLE } : {}),
      extensionDevelopmentPath: root,
      extensionTestsPath: path.join(root, 'test/integration-host.cjs'),
      extensionTestsEnv: { SMC_TEST_CDP_PORT: String(port), SMC_TEST_ARTIFACTS: artifacts,
        SMC_TEST_PROJECT: project, SMC_TEST_MULTI_PROJECT: multiProject, SMC_USER_DIR: path.join(temp, 'smc-user') },
      launchArgs: [project, '--user-data-dir', path.join(temp, 'profile'), '--extensions-dir', path.join(temp, 'extensions'),
        '--disable-extensions', '--disable-workspace-trust', '--skip-welcome', '--skip-release-notes',
        `--remote-debugging-port=${port}`]
    });
  } finally { await fs.rm(temp, { recursive: true, force: true }); }
})().catch(error => { console.error(error); process.exitCode = 1; });
