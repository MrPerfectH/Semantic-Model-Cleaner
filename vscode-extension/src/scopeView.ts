import * as vscode from 'vscode';
import { ScopeState } from './scope';

export type AnalysisState = { state: 'running' | 'done' | 'failed'; key: string; error?: string };

type Node =
  | { kind: 'models' } | { kind: 'reports' } | { kind: 'analyze' } | { kind: 'loading' }
  | { kind: 'model'; path: string; name: string }
  | { kind: 'report'; path: string; name: string; status: string }
  | { kind: 'note'; label: string; tooltip?: string; icon: string; description?: string };

const plural = (count: number, noun: string) => `${count} ${noun}${count === 1 ? '' : 's'}`;

/** Native Cleaner scope picker. Selection lives in ScopeState; this only renders it. */
export class ScopeView implements vscode.TreeDataProvider<Node> {
  private readonly changed = new vscode.EventEmitter<Node | undefined>();
  readonly onDidChangeTreeData = this.changed.event;
  analysis?: AnalysisState;
  constructor(private readonly scope: ScopeState) {}
  refresh(): void { this.changed.fire(undefined); }

  summary(): string {
    const selection = this.scope.selection();
    if (!selection?.model) return '';
    return `${selection.reports.length}/${selection.total} reports`;
  }

  getChildren(node?: Node): Node[] {
    const scope = this.scope, data = scope.data;
    if (!node) {
      if (scope.phase === 'loading' && !data) return [{ kind: 'loading' }];
      if (!data) return [];
      return [{ kind: 'models' }, { kind: 'reports' }, { kind: 'analyze' }];
    }
    if (!data) return [];
    if (node.kind === 'models') {
      const rows: Node[] = data.models.map(m => ({ kind: 'model', path: m.path, name: m.name }));
      for (const excluded of data.modelExclusions)
        rows.push({ kind: 'note', label: excluded.name, icon: 'warning', description: 'not supported', tooltip: excluded.message });
      if (!rows.length) rows.push({ kind: 'note', label: 'No semantic models found in this folder', icon: 'info' });
      return rows;
    }
    if (node.kind === 'reports') {
      if (scope.pendingModel) return [{ kind: 'loading' }];
      if (!data.model) return [{ kind: 'note', label: 'Choose a semantic model first', icon: 'arrow-up' }];
      const rows: Node[] = data.reports.map(r => ({ kind: 'report', path: r.path, name: r.name, status: r.status }));
      if (!rows.length) rows.push({ kind: 'note', label: 'No connected reports found', icon: 'info',
        tooltip: 'Analyze checks the model only. Report usage stays unknown.' });
      for (const row of data.unverifiedReports)
        rows.push({ kind: 'note', label: row.name, icon: 'warning', description: 'binding not verified',
          tooltip: `${row.message || row.status}\nNot selectable. Fix its definition.pbir to include it.` });
      if (data.otherReportCount)
        rows.push({ kind: 'note', label: `${plural(data.otherReportCount, 'report')} use other models`, icon: 'info',
          tooltip: 'Reports connected to a different semantic model are not part of this analysis.' });
      return rows;
    }
    return [];
  }

  getTreeItem(node: Node): vscode.TreeItem {
    const scope = this.scope, data = scope.data, selection = scope.selection();
    const None = vscode.TreeItemCollapsibleState.None, Expanded = vscode.TreeItemCollapsibleState.Expanded;
    switch (node.kind) {
      case 'loading': {
        const item = new vscode.TreeItem(scope.pendingModel ? 'Loading connected reports…' : 'Loading models and reports…', None);
        item.iconPath = new vscode.ThemeIcon('loading~spin');
        return item;
      }
      case 'models': {
        const item = new vscode.TreeItem('Semantic model', Expanded);
        item.id = 'group:models';
        item.description = selection?.model?.name ?? (data?.models.length ? 'choose one' : 'none found');
        item.iconPath = new vscode.ThemeIcon('database');
        return item;
      }
      case 'reports': {
        const item = new vscode.TreeItem('Reports', Expanded);
        item.id = 'group:reports';
        item.description = selection?.model ? `${selection.reports.length} of ${selection.total} selected` : '';
        item.tooltip = 'Reports in this folder connected to the chosen semantic model. All are selected by default.';
        item.iconPath = new vscode.ThemeIcon('graph');
        item.contextValue = 'reportsGroup';
        return item;
      }
      case 'model': {
        const chosen = (scope.pendingModel ?? data?.model) === node.path;
        const item = new vscode.TreeItem(node.name, None);
        item.id = `model:${node.path}`;
        item.description = chosen ? (scope.pendingModel ? 'loading…' : 'selected') : '';
        item.tooltip = node.path;
        item.iconPath = new vscode.ThemeIcon(chosen ? 'pass-filled' : 'circle-large-outline');
        item.command = { command: 'semanticModelCleaner.selectModel', title: 'Select semantic model', arguments: [node.path] };
        item.accessibilityInformation = { label: `${node.name}${chosen ? ', selected' : ''}`, role: 'radio' };
        return item;
      }
      case 'report': {
        const item = new vscode.TreeItem(node.name, None);
        item.id = `report:${node.path}`;
        item.checkboxState = scope.isSelected(node.path)
          ? vscode.TreeItemCheckboxState.Checked : vscode.TreeItemCheckboxState.Unchecked;
        item.description = node.status === 'connected_by_name' ? 'by model name' : '';
        item.tooltip = node.path;
        item.contextValue = 'report';
        return item;
      }
      case 'analyze': {
        const item = new vscode.TreeItem('Analyze', None);
        item.id = 'action:analyze';
        item.iconPath = new vscode.ThemeIcon('play');
        if (!selection?.model) { item.description = 'choose a semantic model'; return item; }
        const reports = selection.reports.length
          ? `${selection.reports.length} of ${plural(selection.total, 'report')}`
          : `model only (0 of ${plural(selection.total, 'report')})`;
        const analysis = this.analysis?.key === selection.key ? this.analysis : undefined;
        const state = !this.analysis ? '' : analysis?.state === 'running' ? ' · analyzing…'
          : analysis?.state === 'done' ? ' · results current' : analysis?.state === 'failed' ? ' · failed'
          : this.analysis.state === 'done' ? ' · results stale' : '';
        item.description = reports + state;
        item.tooltip = (analysis?.state === 'failed' && analysis.error ? analysis.error + '\n' : '') +
          (selection.reports.length ? 'Analyze the chosen model with exactly the selected reports.'
            : 'No reports selected: inspects model dependencies only. Report usage stays unknown, so nothing is called Safe.');
        item.command = { command: 'semanticModelCleaner.analyze', title: 'Analyze' };
        return item;
      }
      case 'note': {
        const item = new vscode.TreeItem(node.label, None);
        item.iconPath = new vscode.ThemeIcon(node.icon);
        item.description = node.description;
        item.tooltip = node.tooltip;
        return item;
      }
    }
  }
}
