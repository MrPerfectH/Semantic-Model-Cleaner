import * as vscode from 'vscode';

/** Native navigation only; command handlers own trust checks and server lifecycle. */
export class CleanerActions implements vscode.TreeDataProvider<vscode.TreeItem> {
  private readonly actions = [
    ['Open Cleaner', 'open', 'beaker'],
    ['Restart Server', 'restart', 'debug-restart'],
    ['Stop Server', 'stop', 'debug-stop'],
    ['Show Logs', 'showLogs', 'output']
  ].map(([label, command, icon]) => {
    const item = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.None);
    item.command = { command: `semanticModelCleaner.${command}`, title: label };
    item.iconPath = new vscode.ThemeIcon(icon);
    return item;
  });

  getTreeItem(item: vscode.TreeItem): vscode.TreeItem { return item; }
  getChildren(item?: vscode.TreeItem): vscode.TreeItem[] { return item ? [] : this.actions; }
}
