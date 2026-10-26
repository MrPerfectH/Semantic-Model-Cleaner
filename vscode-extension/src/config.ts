import * as path from 'node:path';
import { readFileSync, statSync } from 'node:fs';

export interface LaunchConfig { executable: string; args: string[]; cwd: string; engineVersion?: string }
export interface Settings { get<T>(key: string, fallback: T): T }

export function assertTrusted(trusted: boolean): void {
  if (!trusted) throw new Error('Trust this workspace in VS Code before opening Semantic Model Cleaner.');
}

// The settings callback must not even execute before this trust check.
export function launchConfig(trusted: boolean, read: () => Settings, cwd: string, extensionPath?: string): LaunchConfig {
  assertTrusted(trusted);
  const settings = read();
  const python = settings.get('pythonPath', '');
  const override = settings.get('executable', '');
  if (!python && !override) return bundledConfig(extensionPath, cwd);
  const executable = python || override;
  if (typeof executable !== 'string' || !executable.trim() || /[\r\n\0]/.test(executable) ||
      (!path.isAbsolute(executable) && /[\\/\s]/.test(executable)) || /\.(cmd|bat)$/i.test(executable)) {
    throw new Error('Set an absolute executable path or a command name on PATH, without arguments. Use pythonPath for Python environments; .cmd/.bat wrappers are unsupported.');
  }
  return { executable, args: python ? ['-I', '-m', 'semantic_model_cleaner.web'] : [], cwd };
}

function bundledConfig(extensionPath: string | undefined, cwd: string): LaunchConfig {
  if (!extensionPath) throw new Error('The bundled Cleaner engine is missing. Reinstall the extension, or configure an engine override for development.');
  const directory = path.join(extensionPath, 'engine');
  let manifest;
  try { manifest = JSON.parse(readFileSync(path.join(directory, 'manifest.json'), 'utf8')); }
  catch { throw new Error('The bundled Cleaner engine is missing or damaged. Reinstall the extension.'); }
  if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest))
    throw new Error('The bundled Cleaner engine manifest is incompatible. Reinstall the extension.');
  if (manifest.platform !== process.platform || manifest.arch !== process.arch)
    throw new Error(`This Cleaner engine does not support ${process.platform}-${process.arch}. Install the matching platform package.`);
  const filename = process.platform === 'win32' ? 'smc-engine.exe' : 'smc-engine';
  if (manifest.protocol !== 1 || manifest.executable !== filename ||
      typeof manifest.engineVersion !== 'string' || !manifest.engineVersion.trim())
    throw new Error('The bundled Cleaner engine manifest is incompatible. Reinstall the extension.');
  const executable = path.join(directory, filename);
  try { if (!statSync(executable).isFile()) throw new Error(); }
  catch { throw new Error('The bundled Cleaner executable is missing. Reinstall the extension; check whether security software quarantined it.'); }
  return { executable, args: [], cwd, engineVersion: manifest.engineVersion };
}

export function validateAncestors(values: unknown): string[] {
  if (!Array.isArray(values) || values.length < 1 || values.length > 4 ||
      values.some(v => typeof v !== 'string' || !/^(https:\/\/[a-z0-9-]+\.vscode-cdn\.net|vscode-webview:\/\/[a-z0-9-]+|vscode-file:\/\/vscode-app)$/.test(v)) ||
      values.every(v => v === 'vscode-file://vscode-app')) {
    throw new Error('This VS Code webview origin is unsupported. Use desktop VS Code locally and report this compatibility issue.');
  }
  return [...new Set(values)];
}
