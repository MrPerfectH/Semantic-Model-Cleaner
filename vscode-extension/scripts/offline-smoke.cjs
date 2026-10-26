// Isolate only this disposable test process; never disconnect the user's computer.
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const child = path.join(__dirname, 'offline-child.cjs');
const options = { stdio: 'inherit', env: { ...process.env } };
if (process.platform === 'linux') {
  options.env.SMC_NETWORK_ISOLATION = 'linux-network-namespace';
  execFileSync('unshare', ['--user', '--map-root-user', '--net', '--', process.execPath, child], options);
} else if (process.platform === 'darwin') {
  options.env.SMC_NETWORK_ISOLATION = 'macos-process-sandbox';
  const profile = '(version 1)(allow default)(deny network-outbound)(allow network-outbound (remote ip "localhost:*"))';
  execFileSync('/usr/bin/sandbox-exec', ['-p', profile, process.execPath, child], options);
} else if (process.platform === 'win32') {
  options.env.SMC_NETWORK_ISOLATION = 'windows-program-firewall';
  execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
    path.join(__dirname, 'offline-windows.ps1'), '-NodeExecutable', process.execPath, '-ChildScript', child], options);
} else throw new Error('Offline verification is unsupported on this platform.');
