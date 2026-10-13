import * as path from 'node:path';

export interface LaunchConfig { executable: string; args: string[]; cwd: string }
export interface Settings { get<T>(key: string, fallback: T): T }

export function assertTrusted(trusted: boolean): void {
  if (!trusted) throw new Error('Trust this workspace in VS Code before opening Semantic Model Cleaner.');
}

// The settings callback must not even execute before this trust check.
export function launchConfig(trusted: boolean, read: () => Settings, cwd: string): LaunchConfig {
  assertTrusted(trusted);
  const settings = read();
  const python = settings.get('pythonPath', '');
  const executable = python || settings.get('executable', 'smc-web');
  if (typeof executable !== 'string' || !executable.trim() || /[\r\n\0]/.test(executable) ||
      (!path.isAbsolute(executable) && /[\\/\s]/.test(executable)) || /\.(cmd|bat)$/i.test(executable)) {
    throw new Error('Set an absolute executable path or a command name on PATH, without arguments. Use pythonPath for Python environments; .cmd/.bat wrappers are unsupported.');
  }
  return { executable, args: python ? ['-I', '-m', 'semantic_model_cleaner.web'] : [], cwd };
}

export function validateAncestors(values: unknown): string[] {
  if (!Array.isArray(values) || values.length < 1 || values.length > 4 ||
      values.some(v => typeof v !== 'string' || !/^(https:\/\/[a-z0-9-]+\.vscode-cdn\.net|vscode-webview:\/\/[a-z0-9-]+|vscode-file:\/\/vscode-app)$/.test(v)) ||
      values.every(v => v === 'vscode-file://vscode-app')) {
    throw new Error('This VS Code webview origin is unsupported. Use desktop VS Code locally and report this compatibility issue.');
  }
  return [...new Set(values)];
}
