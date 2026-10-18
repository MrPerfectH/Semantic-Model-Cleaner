const http = require('node:http');
const crypto = require('node:crypto');
const mode = process.argv[2];
if (mode === 'exit') process.exit(7);
if (mode === 'hang') setInterval(() => {}, 1000);
else {
  const server = http.createServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    if (req.url === '/api/vscode/scope') {
      let body = '';
      req.on('data', chunk => { body += chunk; });
      req.on('end', () => {
        if (req.headers['x-smc-token'] !== process.env.SMC_VSCODE_TOKEN || req.headers['content-type'] !== 'application/json') {
          res.statusCode = 403; res.end(JSON.stringify({ error: 'denied' })); return;
        }
        const request = JSON.parse(body);
        if (request.model_path === 'gone') { res.statusCode = 409; res.end(JSON.stringify({ error: 'Model gone.' })); return; }
        res.end(JSON.stringify({ echo: request, features: process.env.SMC_VSCODE_FEATURES }));
      });
      return;
    }
    res.end(JSON.stringify({ protocol: 1, instance: mode === 'wrong' ? 'wrong' :
      crypto.createHash('sha256').update(process.env.SMC_VSCODE_TOKEN).digest('hex') }));
  });
  server.listen(0, '127.0.0.1', () => {
    const line = 'SMC_VSCODE_READY ' + JSON.stringify({ protocol: 1, port: server.address().port }) + '\n';
    if (mode === 'malformed') process.stdout.write('SMC_VSCODE_READY nope\n');
    else if (mode === 'slow') setTimeout(() => process.stdout.write(line), 250);
    else process.stdout.write(line);
    if (mode === 'dies') setTimeout(() => process.exit(8), 250);
  });
}
