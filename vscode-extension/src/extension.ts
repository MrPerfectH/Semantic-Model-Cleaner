import * as vscode from 'vscode';
import * as path from 'node:path';
import { stat } from 'node:fs/promises';
import { assertTrusted, launchConfig } from './config';
import { Cancelled, ServerManager } from './server';
import { getAncestors, showApp, showMessage } from './panel';

let stopExtension: (() => Promise<void>) | undefined;

export function activate(context: vscode.ExtensionContext): void {
  const server = new ServerManager();
  const output = vscode.window.createOutputChannel('Semantic Model Cleaner');
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 40);
  status.command = 'semanticModelCleaner.open';
  let panel: vscode.WebviewPanel | undefined;
  let folder: vscode.Uri | undefined;
  let opening: AbortController | undefined;
  let epoch = 0;
  let selectionEpoch = 0;
  let logText = '';
  const log = (line: string) => {
    logText = (logText + line + '\n').slice(-65536);
    output.clear(); output.append(logText);
  };
  const state = (value: string) => {
    status.text = `$(beaker) Cleaner: ${value}`;
    status.tooltip = folder ? `Semantic Model Cleaner — ${folder.fsPath}` : 'Open Semantic Model Cleaner';
    status.show();
  };
  const requireLocalTrusted = () => {
    assertTrusted(vscode.workspace.isTrusted);
    if (vscode.env.uiKind !== vscode.UIKind.Desktop || vscode.env.remoteName)
      throw new Error('This preview supports local desktop VS Code only. Open a local folder in a desktop window. Remote SSH, WSL, containers, Codespaces and browser hosts are not yet supported.');
  };
  const stop = async () => {
    epoch++; selectionEpoch++;
    opening?.abort(); opening = undefined;
    const previous = panel; panel = undefined;
    previous?.dispose();
    state('stopped');
    await server.stop();
  };
  stopExtension = stop;

  async function chooseFolder(uri?: vscode.Uri): Promise<vscode.Uri | undefined> {
    if (uri) return uri;
    const roots = vscode.workspace.workspaceFolders || [];
    if (roots.length === 1) return roots[0].uri;
    if (roots.length > 1) {
      const choice = await vscode.window.showQuickPick([
        ...roots.map(root => ({ label: root.name, description: root.uri.fsPath, uri: root.uri })),
        { label: 'Choose another folder…', description: '', uri: undefined }
      ], { placeHolder: 'Select the Power BI Project folder' });
      if (!choice) return;
      if (choice.uri) return choice.uri;
    }
    return (await vscode.window.showOpenDialog({ canSelectFiles: false, canSelectFolders: true,
      canSelectMany: false, openLabel: 'Open Cleaner', title: 'Select the Power BI Project folder' }))?.[0];
  }

  async function begin(uri: vscode.Uri): Promise<void> {
    requireLocalTrusted();
    const generation = ++epoch;
    if (uri.scheme !== 'file' || !(await stat(uri.fsPath)).isDirectory())
      throw new Error('Choose a local filesystem folder containing your Power BI Project.');
    if (generation !== epoch) throw new Cancelled();
    opening?.abort();
    const previous = panel; panel = undefined; previous?.dispose();
    const shutdown = server.stop();
    folder = uri;
    const abort = opening = new AbortController();
    const ownPanel = panel = vscode.window.createWebviewPanel('semanticModelCleaner',
      `Cleaner — ${path.basename(uri.fsPath) || uri.fsPath}`, vscode.ViewColumn.One,
      { enableScripts: true, localResourceRoots: [], retainContextWhenHidden: true });
    ownPanel.onDidDispose(() => { if (panel === ownPanel) void stop(); });
    state('starting');
    try {
      const ancestors = await getAncestors(ownPanel, abort.signal);
      await shutdown;
      if (generation !== epoch) throw new Cancelled();
      requireLocalTrusted();
      const config = launchConfig(vscode.workspace.isTrusted,
        () => vscode.workspace.getConfiguration('semanticModelCleaner', uri), uri.fsPath);
      const running = await server.start(config, ancestors, log, () => {
        if (generation !== epoch) return;
        state('stopped');
        showMessage(ownPanel, 'The Cleaner server exited. Use Semantic Model Cleaner: Show Logs, then Restart Server.');
      });
      if (generation !== epoch) throw new Cancelled();
      showApp(ownPanel, running.port, uri.fsPath);
      state('running');
    } catch (error) {
      if (generation !== epoch || error instanceof Cancelled) return;
      await server.stop();
      state('error');
      const message = error instanceof Error ? error.message : 'Could not start Cleaner.';
      log(message); showMessage(ownPanel, message);
      throw error;
    }
  }
  async function open(uri?: vscode.Uri): Promise<void> {
    requireLocalTrusted();
    const selection = ++selectionEpoch;
    const selected = await chooseFolder(uri);
    if (!selected || selection !== selectionEpoch) return;
    if (panel && folder?.toString() === selected.toString()) { panel.reveal(); return; }
    await begin(selected);
  }
  const command = (name: string, action: (...args: any[]) => unknown) =>
    vscode.commands.registerCommand(`semanticModelCleaner.${name}`, async (...args: any[]) => {
      try { await action(...args); }
      catch (error) {
        if (error instanceof Cancelled) return;
        const message = error instanceof Error ? error.message : 'Cleaner command failed.';
        const choice = await vscode.window.showErrorMessage(message, 'Show Logs');
        if (choice) output.show(true);
      }
    });
  context.subscriptions.push(output, status,
    command('open', open),
    command('restart', async () => {
      requireLocalTrusted(); selectionEpoch++;
      if (folder) await begin(folder); else await open();
    }),
    command('stop', stop),
    command('showLogs', () => output.show(true)),
    { dispose: () => { void stop(); } });
  state(vscode.workspace.isTrusted ? 'stopped' : 'trust required');
}

export async function deactivate(): Promise<void> { await stopExtension?.(); stopExtension = undefined; }
