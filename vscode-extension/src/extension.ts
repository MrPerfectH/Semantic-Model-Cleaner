import * as vscode from 'vscode';
import * as path from 'node:path';
import { stat } from 'node:fs/promises';
import { assertTrusted, launchConfig } from './config';
import { Cancelled, RunningServer, ServerManager } from './server';
import { getAncestors, HOST_SCOPE, showApp, showMessage } from './panel';
import { CleanerActions } from './actions';
import { ScopeState } from './scope';
import { AnalysisState, ScopeView } from './scopeView';

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
  let running: RunningServer | undefined;
  let pageReady = false;
  let pendingAnalyze = false;
  const scope = new ScopeState();
  const scopeView = new ScopeView(scope);
  const scopeTree = vscode.window.createTreeView('semanticModelCleaner.scope',
    { treeDataProvider: scopeView, manageCheckboxStateManually: true, showCollapseAll: false });
  const fetchScope = (model?: string) => {
    const server = running;
    if (!server) return Promise.reject(new Error('Open Cleaner to load models and reports.'));
    return server.request('/api/vscode/scope', model ? { model_path: model } : {});
  };
  // The page analyzes exactly this selection; every change marks older results stale.
  const sendScope = (analyze = false) => {
    if (!panel || !pageReady) { if (analyze) pendingAnalyze = true; return; }
    const selection = scope.selection() ?? { key: '', model: null, reports: [], total: 0 };
    void panel.webview.postMessage({ type: HOST_SCOPE, scope: selection, analyze });
  };
  scope.onChange(() => {
    scopeTree.description = scopeView.summary();
    scopeTree.message = scope.phase === 'error' ? scope.error : undefined;
    void vscode.commands.executeCommand('setContext', 'semanticModelCleaner.scopePhase', scope.phase);
    scopeView.refresh();
    sendScope();
  });
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
  const detach = () => {
    running = undefined; pageReady = false; pendingAnalyze = false; scopeView.analysis = undefined;
    scope.detach();
  };
  const stop = async () => {
    epoch++; selectionEpoch++;
    opening?.abort(); opening = undefined;
    const previous = panel; panel = undefined;
    detach();
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
    running = undefined; pageReady = false; pendingAnalyze = false; scopeView.analysis = undefined;
    scope.begin(uri.fsPath);
    const abort = opening = new AbortController();
    const ownPanel = panel = vscode.window.createWebviewPanel('semanticModelCleaner',
      `Cleaner — ${path.basename(uri.fsPath) || uri.fsPath}`, vscode.ViewColumn.One,
      { enableScripts: true, localResourceRoots: [], retainContextWhenHidden: true });
    ownPanel.onDidDispose(() => { if (panel === ownPanel) void stop(); });
    ownPanel.webview.onDidReceiveMessage(message => {
      if (panel !== ownPanel || generation !== epoch || !running || !message || typeof message.type !== 'string') return;
      if (message.type === 'smc-page-ready') {
        pageReady = true;
        const analyze = pendingAnalyze; pendingAnalyze = false;
        sendScope(analyze);
      } else if (message.type === 'smc-analysis' && ['running', 'done', 'failed'].includes(message.state) &&
          typeof message.key === 'string' && message.key.length <= 64) {
        scopeView.analysis = { state: message.state, key: message.key,
          error: typeof message.error === 'string' ? message.error.slice(0, 500) : undefined } as AnalysisState;
        scopeView.refresh();
      } else if (message.type === 'smc-focus-scope') {
        void vscode.commands.executeCommand('semanticModelCleaner.scope.focus');
      }
    });
    state('starting');
    try {
      const ancestors = await getAncestors(ownPanel, abort.signal);
      await shutdown;
      if (generation !== epoch) throw new Cancelled();
      requireLocalTrusted();
      const config = launchConfig(vscode.workspace.isTrusted,
        () => vscode.workspace.getConfiguration('semanticModelCleaner', uri), uri.fsPath);
      const started = await server.start(config, ancestors, log, () => {
        if (generation !== epoch) return;
        state('stopped');
        detach();
        showMessage(ownPanel, 'The Cleaner server exited. Use Semantic Model Cleaner: Show Logs, then Restart Server.');
      });
      if (generation !== epoch) throw new Cancelled();
      running = started;
      showApp(ownPanel, started.port, uri.fsPath);
      state('running');
      void scope.load(fetchScope);
    } catch (error) {
      if (generation !== epoch || error instanceof Cancelled) return;
      await server.stop();
      state('error');
      scope.fail(error instanceof Error ? error.message : 'Could not start Cleaner.');
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
  const requireScope = () => {
    requireLocalTrusted();
    if (!running || scope.phase !== 'ready') throw new Error('Open Cleaner and wait for models and reports to load.');
  };
  async function analyze(): Promise<void> {
    requireScope();
    const selection = scope.selection();
    if (!selection?.model) {
      await chooseModel();
      if (!scope.selection()?.model) return;
    }
    panel?.reveal(undefined, false);
    sendScope(true);
  }
  async function chooseModel(): Promise<void> {
    requireScope();
    const models = scope.data?.models ?? [];
    if (!models.length) throw new Error('No semantic models were found in this folder.');
    const choice = await vscode.window.showQuickPick(models.map(m => ({ label: m.name, description: m.path,
      picked: m.path === scope.data?.model, path: m.path })), { placeHolder: 'Choose the semantic model to analyze' });
    if (choice) await selectModel(choice.path);
  }
  async function selectModel(modelPath: unknown): Promise<void> {
    requireScope();
    if (typeof modelPath !== 'string') return;
    await scope.selectModel(fetchScope, modelPath);
  }
  context.subscriptions.push(output, status, scopeTree,
    scopeTree.onDidChangeCheckboxState(event => {
      for (const [node, value] of event.items)
        if (node.kind === 'report') scope.setReport(node.path, value === vscode.TreeItemCheckboxState.Checked);
    }),
    vscode.window.registerTreeDataProvider('semanticModelCleaner.actions', new CleanerActions()),
    command('analyze', analyze),
    command('chooseModel', chooseModel),
    command('selectModel', selectModel),
    command('selectAllReports', () => { requireScope(); scope.setAll(true); }),
    command('clearReports', () => { requireScope(); scope.setAll(false); }),
    command('refreshScope', async () => {
      requireLocalTrusted();
      if (running) await scope.load(fetchScope);
      else if (folder) await begin(folder);
      else await open();
    }),
    command('open', open),
    command('restart', async () => {
      requireLocalTrusted(); selectionEpoch++;
      if (folder) await begin(folder); else await open();
    }),
    command('stop', stop),
    command('showLogs', () => output.show(true)),
    { dispose: () => { void stop(); } });
  state(vscode.workspace.isTrusted ? 'stopped' : 'trust required');
  void vscode.commands.executeCommand('setContext', 'semanticModelCleaner.scopePhase', scope.phase);
}

export async function deactivate(): Promise<void> { await stopExtension?.(); stopExtension = undefined; }
