const { test } = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');
const commands = new Map();
let reads = 0, panels = 0;
const errors = [];
const disposable = () => ({ dispose() {} });
const vscode = {
  UIKind: { Desktop: 1, Web: 2 }, env: { uiKind: 1, remoteName: undefined },
  StatusBarAlignment: { Left: 1 },
  workspace: { isTrusted: false, getConfiguration() { reads++; throw new Error('Settings read'); } },
  commands: { registerCommand(name, fn) { commands.set(name, fn); return disposable(); } },
  window: {
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
  await commands.get('semanticModelCleaner.open')();
  await commands.get('semanticModelCleaner.restart')();
  assert.equal(reads, 0); assert.equal(panels, 0);
  assert.equal(errors.length, 2); assert.ok(errors.every(e => e.startsWith('Trust this workspace')));
});
test('unsupported remote host fails before launch configuration', async () => {
  vscode.workspace.isTrusted = true; vscode.env.remoteName = 'ssh-remote';
  await commands.get('semanticModelCleaner.open')();
  assert.match(errors.at(-1), /local desktop VS Code only/);
  assert.equal(reads, 0); assert.equal(panels, 0);
  await extension.deactivate();
});
