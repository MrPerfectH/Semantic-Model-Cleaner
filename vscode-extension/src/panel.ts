import * as vscode from 'vscode';
import { randomBytes } from 'node:crypto';
import { Cancelled } from './server';
import { validateAncestors } from './config';

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
}
function document(body: string, script = '', frameOrigin = ''): string {
  const nonce = randomBytes(24).toString('hex');
  return `<!doctype html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; base-uri 'none'; form-action 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}'; frame-src ${frameOrigin || "'none'"};">
<style nonce="${nonce}">html,body{height:100%;margin:0;background:var(--vscode-editor-background);color:var(--vscode-editor-foreground);font-family:var(--vscode-font-family)}body{display:flex;flex-direction:column}header{padding:8px 12px;border-bottom:1px solid var(--vscode-panel-border);font-size:12px;overflow-wrap:anywhere}main{padding:20px}iframe{width:100%;flex:1;border:0;min-height:0}</style>
</head><body>${body}${script ? `<script nonce="${nonce}">${script}</script>` : ''}</body></html>`;
}
export function showMessage(panel: vscode.WebviewPanel, message: string): void {
  panel.webview.html = document(`<main>${escapeHtml(message)}</main>`);
}
export function showApp(panel: vscode.WebviewPanel, port: number, project: string): void {
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid loopback port.');
  const origin = `http://127.0.0.1:${port}`;
  // Desktop-only. No external URI resolution or public tunnel is requested.
  panel.webview.options = { enableScripts: true, enableForms: true, localResourceRoots: [],
    portMapping: [{ webviewPort: port, extensionHostPort: port }] };
  panel.webview.html = document(`<header>Power BI Project: ${escapeHtml(project)}</header>
<iframe title="Semantic Model Cleaner" src="${origin}/" sandbox="allow-scripts allow-same-origin allow-forms allow-downloads allow-modals"></iframe>`, `
// Relay only: sidebar scope down to the app, page state up to the extension.
// The app's messages must come from this exact frame and loopback origin.
const api = acquireVsCodeApi();
const frame = document.querySelector('iframe');
const app = ${JSON.stringify(origin)};
const up = new Set(${JSON.stringify(PAGE_MESSAGES)});
window.addEventListener('message', event => {
  const data = event.data;
  if (!data || typeof data.type !== 'string') return;
  if (event.source === frame.contentWindow) {
    if (event.origin === app && up.has(data.type)) api.postMessage(data);
  } else if (data.type === ${JSON.stringify(HOST_SCOPE)} && frame.contentWindow) {
    frame.contentWindow.postMessage(data, app);
  }
});`, origin);
}
export const HOST_SCOPE = 'smc-host-scope';
export const PAGE_MESSAGES = ['smc-page-ready', 'smc-analysis', 'smc-focus-scope'];
export function getAncestors(panel: vscode.WebviewPanel, signal: AbortSignal): Promise<string[]> {
  return new Promise((resolve, reject) => {
    let timer: NodeJS.Timeout;
    const done = (error?: Error, origins?: string[]) => {
      clearTimeout(timer); subscription.dispose(); signal.removeEventListener('abort', abort);
      if (error) reject(error); else resolve(origins!);
    };
    const abort = () => done(new Cancelled());
    const subscription = panel.webview.onDidReceiveMessage(message => {
      if (message?.type !== 'smc-origins') return;
      try { done(undefined, validateAncestors(message.origins)); }
      catch (error) { done(error as Error); }
    });
    timer = setTimeout(() => done(new Error('VS Code webview did not initialize. Reopen Cleaner or reload the VS Code window.')), 15000);
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) { abort(); return; }
    panel.webview.html = document('<main>Starting Semantic Model Cleaner…</main>', `
const api = acquireVsCodeApi();
api.postMessage({ type: 'smc-origins', origins: [...new Set([location.origin, ...Array.from(location.ancestorOrigins)])] });`);
  });
}
