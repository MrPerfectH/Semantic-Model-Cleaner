const { execFileSync } = require('node:child_process');
const net = require('node:net');
if (!process.env.SMC_NETWORK_ISOLATION) throw new Error('Run through offline-smoke.cjs to establish network isolation.');
if (process.platform === 'linux') execFileSync('ip', ['link', 'set', 'lo', 'up']);
new Promise((resolve, reject) => {
  // No application data is sent. A successful handshake means isolation failed.
  const socket = net.connect({ host: '1.1.1.1', port: 443 });
  socket.once('connect', () => { socket.destroy(); reject(new Error('External network access is still possible.')); });
  socket.once('error', error => {
    if (['EACCES', 'EPERM', 'ENETUNREACH', 'EHOSTUNREACH', 'ETIMEDOUT'].includes(error.code)) resolve(error.code);
    else reject(new Error(`Cannot establish offline isolation: ${error.code}`));
  });
  socket.setTimeout(3000, () => {
    const error = new Error('Connection blocked/timed out'); error.code = 'ETIMEDOUT'; socket.destroy(error);
  });
}).then(code => {
  console.log(JSON.stringify({ networkIsolation: process.env.SMC_NETWORK_ISOLATION, externalConnection: code }));
  require('./smoke-engine.cjs');
}).catch(error => { console.error(error); process.exitCode = 1; });
