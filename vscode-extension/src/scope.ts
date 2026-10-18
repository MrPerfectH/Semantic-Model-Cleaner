import { createHash } from 'node:crypto';

export interface Artifact { path: string; name: string }
export interface ReportRow extends Artifact { status: string; message?: string }
export interface ScopeResponse {
  project: string;
  models: Artifact[];
  modelExclusions: { path: string; name: string; message: string }[];
  model: string | null;
  reports: ReportRow[];
  unverifiedReports: ReportRow[];
  otherReportCount: number;
}
/** Exactly what the editor analyzes. An empty report list means model-only. */
export interface Selection { key: string; model: Artifact | null; reports: Artifact[]; total: number }
export type Phase = 'idle' | 'loading' | 'ready' | 'error';
export type Fetch = (model?: string) => Promise<unknown>;

const text = (value: unknown, max = 4096): value is string =>
  typeof value === 'string' && value.length > 0 && value.length <= max && !/[\0\r\n]/.test(value);
function rows<T>(value: unknown, read: (row: any) => T): T[] {
  if (!Array.isArray(value) || value.length > 10000) throw new Error('Invalid scope response.');
  return value.map(read);
}
function artifact(row: any): Artifact {
  if (!text(row?.path) || !text(row?.name, 512)) throw new Error('Invalid scope response.');
  return { path: row.path, name: row.name };
}
function report(row: any): ReportRow {
  if (!text(row?.status, 64)) throw new Error('Invalid scope response.');
  return { ...artifact(row), status: row.status,
    ...(typeof row.message === 'string' ? { message: row.message.slice(0, 2000) } : {}) };
}

/** Validate the server's discovery payload before any of it reaches the UI. */
export function parseScope(value: any): ScopeResponse {
  if (!value || typeof value !== 'object') throw new Error('Invalid scope response.');
  const models = rows(value.models, artifact);
  const model = value.model === null ? null : value.model;
  if (model !== null && !models.some(m => m.path === model)) throw new Error('Invalid scope response.');
  if (!Number.isInteger(value.otherReportCount) || value.otherReportCount < 0) throw new Error('Invalid scope response.');
  return {
    project: typeof value.project === 'string' ? value.project : '',
    models, model,
    modelExclusions: rows(value.modelExclusions, row => ({ ...artifact(row),
      message: typeof row.message === 'string' ? row.message.slice(0, 2000) : '' })),
    reports: rows(value.reports, report),
    unverifiedReports: rows(value.unverifiedReports, report),
    otherReportCount: value.otherReportCount
  };
}

/**
 * Sidebar scope for one project folder. Every load is generation-guarded so a
 * slow response for an older folder, server or model can never replace newer state.
 * Connected Reports default to selected; only explicit deselections are remembered.
 */
export class ScopeState {
  phase: Phase = 'idle';
  error = '';
  folder = '';
  data?: ScopeResponse;
  /** Model being loaded after an explicit choice; shown as pending. */
  pendingModel?: string;
  private remembered?: string;
  private deselected = new Set<string>();
  private generation = 0;
  private listeners: (() => void)[] = [];

  onChange(listener: () => void): void { this.listeners.push(listener); }
  private emit(): void { for (const listener of this.listeners) listener(); }

  /** Server for `folder` is starting. Another folder wipes every remembered choice. */
  begin(folder: string): void {
    this.generation++;
    if (folder !== this.folder) { this.folder = folder; this.remembered = undefined; this.deselected.clear(); }
    this.phase = 'loading'; this.error = ''; this.data = undefined; this.pendingModel = undefined;
    this.emit();
  }
  /** Server stopped. Keep choices for a restart of the same folder, drop the data. */
  detach(): void {
    this.generation++;
    this.phase = 'idle'; this.error = ''; this.data = undefined; this.pendingModel = undefined;
    this.emit();
  }
  fail(message: string): void {
    this.generation++;
    this.phase = 'error'; this.error = message; this.data = undefined; this.pendingModel = undefined;
    this.emit();
  }

  /** Load models and the connected Reports of the remembered (or sole) model. */
  async load(fetch: Fetch, model = this.remembered): Promise<boolean> {
    const generation = ++this.generation;
    if (this.phase !== 'ready') this.phase = 'loading';
    this.emit();
    try {
      let value: ScopeResponse;
      try { value = parseScope(await fetch(model)); }
      catch (error) {
        // A remembered model that disappeared falls back to the default choice.
        if (!model || model !== this.remembered || (error as { status?: number }).status !== 409) throw error;
        if (generation !== this.generation) return false;
        this.remembered = undefined; this.deselected.clear();
        value = parseScope(await fetch(undefined));
      }
      if (generation !== this.generation) return false;
      if (value.model !== this.remembered) this.deselected.clear();
      this.remembered = value.model ?? undefined;
      this.data = value; this.phase = 'ready'; this.error = ''; this.pendingModel = undefined;
      this.emit();
      return true;
    } catch (error) {
      if (generation !== this.generation) return false;
      this.phase = 'error'; this.data = undefined; this.pendingModel = undefined;
      this.error = error instanceof Error ? error.message : 'Could not load models and reports.';
      this.emit();
      return false;
    }
  }

  /** Choosing another model resets its Reports to the default: all connected. */
  async selectModel(fetch: Fetch, model: string): Promise<boolean> {
    if (!this.data || !this.data.models.some(m => m.path === model)) return false;
    if (model === this.data.model && this.phase === 'ready') return true;
    this.pendingModel = model;
    return this.load(fetch, model);
  }

  setReport(path: string, selected: boolean): void {
    if (this.phase !== 'ready' || !this.data?.reports.some(r => r.path === path)) return;
    if (selected === !this.deselected.has(path)) return;
    if (selected) this.deselected.delete(path); else this.deselected.add(path);
    this.emit();
  }
  setAll(selected: boolean): void {
    if (this.phase !== 'ready' || !this.data) return;
    const before = this.deselected.size;
    this.deselected = new Set(selected ? [] : this.data.reports.map(r => r.path));
    if (before !== this.deselected.size) this.emit();
  }
  isSelected(path: string): boolean { return !this.deselected.has(path); }

  selection(): Selection | undefined {
    const data = this.data;
    if (this.phase !== 'ready' || !data) return;
    const model = data.models.find(m => m.path === data.model) ?? null;
    const reports = model ? data.reports.filter(r => !this.deselected.has(r.path))
      .map(({ path, name }) => ({ path, name })) : [];
    const key = createHash('sha256').update(JSON.stringify([this.folder, model?.path ?? null,
      reports.map(r => r.path)])).digest('hex').slice(0, 32);
    return { key, model, reports, total: model ? data.reports.length : 0 };
  }
}
