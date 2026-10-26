const fs = require('node:fs');
const path = require('node:path');

// test-electron's older resolver assumes Electron; current macOS VS Code uses Code.
function resolveVSCodeExecutable(executable, platform = process.platform) {
  const candidates = [executable];
  if (platform === 'darwin') candidates.push(path.join(path.dirname(executable), 'Code'));
  for (const candidate of candidates) {
    try { if (fs.statSync(candidate).isFile()) return candidate; } catch { /* try the current bundle name */ }
  }
  throw new Error(`VS Code executable not found: ${executable}`);
}
module.exports = { resolveVSCodeExecutable };
