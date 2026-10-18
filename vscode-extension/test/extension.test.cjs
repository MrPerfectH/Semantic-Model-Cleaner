const { test } = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');
const commands = new Map();
let reads = 0, panels = 0;
let actions, scopeView, scopeTree;
const contexts = new Map();
const errors = [];
const disposable = () => ({ dispose() {} });
const vscode = {
  UIKind: { Desktop: 1, Web: 2 }, env: { uiKind: 1, remoteName: undefined },
  StatusBarAlignment: { Left: 1 },
  TreeItemCollapsibleState: { None: 0, Collapsed: 1, Expanded: 2 },
  TreeItemCheckboxState: { Unchecked: 0, Checked: 1 },
  EventEmitter: class { constructor() { this.event = () => disposable(); } fire() {} dispose() {} },
  TreeItem: class { constructor(label, collapsibleState) { Object.assign(this, { label, collapsibleState }); } },
  ThemeIcon: class { constructor(id) { this.id = id; } },
  workspace: { isTrusted: false, getConfiguration() { reads++; throw new Error('Settings read'); } },
  commands: { registerCommand(name, fn) { commands.set(name, fn); return disposable(); },
    async executeCommand(name, key, value) { if (name === 'setContext') contexts.set(key, value); } },
  window: {
    createTreeView(id, options) {
      assert.equal(id, 'semanticModelCleaner.scope'); scopeView = options.treeDataProvider;
      return scopeTree = { ...disposable(), onDidChangeCheckboxState: () => disposable() };
    },
    registerTreeDataProvider(id, provider) {
      assert.equal(id, 'semanticModelCleaner.actions'); actions = provider; return disposable();
    },
    createOutputChannel: () => ({ ...disposable(), clear() {}, append() {}, show() {} }),
    createStatusBarItem: () => ({ ...disposable(), show() {} }),
    showErrorMessage: async message => { errors.push(message); },
    createWebviewPanel: () => { panels++; throw new Error('Panel created'); }
  }
};
const original = Module._load;
Module._load = function(name, ...args) { return name === 'vscode' ? vscode : original.call(this, name, ...args); };
const extension = require('../dist/extension');
Module._load = original;
extension.activate({ subscriptions: [] });

test('actual command handlers enforce trust before settings, panel, or executable', async () => {
  for (const item of actions.getChildren().slice(0, 2)) await commands.get(item.command.command)();
  assert.equal(reads, 0); assert.equal(panels, 0);
  assert.equal(errors.length, 2); assert.ok(errors.every(e => e.startsWith('Trust this workspace')));
});
test('native sidebar exposes four leaf actions using the existing commands', () => {
  const items = actions.getChildren();
  assert.deepEqual(items.map(item => [item.label, item.command.command]), [
    ['Open Cleaner', 'semanticModelCleaner.open'], ['Restart Server', 'semanticModelCleaner.restart'],
    ['Stop Server', 'semanticModelCleaner.stop'], ['Show Logs', 'semanticModelCleaner.showLogs']
  ]);
  for (const item of items) {
    assert.equal(actions.getTreeItem(item), item);
    assert.deepEqual(actions.getChildren(item), []);
    assert.equal(item.collapsibleState, 0);
    assert.ok(commands.has(item.command.command));
  }
  const manifest = require('../package.json');
  assert.deepEqual(manifest.contributes.views.semanticModelCleaner.map(view => view.id),
    ['semanticModelCleaner.scope', 'semanticModelCleaner.actions']);
  const container = manifest.contributes.viewsContainers.activitybar[0];
  assert.equal(container.id, 'semanticModelCleaner');
  assert.ok(require('node:fs').existsSync(require('node:path').join(__dirname, '..', container.icon)));
});
test('scope sidebar starts empty and idle; scope commands require trust and a loaded project', async () => {
  assert.deepEqual(scopeView.getChildren(), []);
  assert.equal(contexts.get('semanticModelCleaner.scopePhase'), 'idle');
  const before = errors.length;
  for (const name of ['analyze', 'chooseModel', 'selectAllReports', 'clearReports'])
    await commands.get(`semanticModelCleaner.${name}`)();
  assert.equal(errors.length, before + 4);
  assert.ok(errors.slice(before).every(e => e.startsWith('Trust this workspace')));
  vscode.workspace.isTrusted = true;
  await commands.get('semanticModelCleaner.analyze')();
  assert.match(errors.at(-1), /Open Cleaner and wait/);
  vscode.workspace.isTrusted = false;
  assert.equal(reads, 0); assert.equal(panels, 0);
  const manifest = require('../package.json');
  const welcome = manifest.contributes.viewsWelcome.filter(v => v.view === 'semanticModelCleaner.scope');
  assert.ok(welcome.some(v => v.when === '!isWorkspaceTrusted'));
  assert.ok(welcome.some(v => v.contents.includes('command:semanticModelCleaner.open')));
  for (const id of ['analyze', 'chooseModel', 'selectModel', 'selectAllReports', 'clearReports', 'refreshScope'])
    assert.ok(manifest.contributes.commands.some(c => c.command === `semanticModelCleaner.${id}`), id);
});
test('unsupported remote host fails before launch configuration', async () => {
  vscode.workspace.isTrusted = true; vscode.env.remoteName = 'ssh-remote';
  await commands.get('semanticModelCleaner.open')();
  assert.match(errors.at(-1), /local desktop VS Code only/);
  assert.equal(reads, 0); assert.equal(panels, 0);
  await extension.deactivate();
});
