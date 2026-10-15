import { spawn, ChildProcessWithoutNullStreams } from 'node:child_process';
import { randomBytes, createHash } from 'node:crypto';
import * as http from 'node:http';
import { LaunchConfig, validateAncestors } from './config';

export class Cancelled extends Error { constructor() { super('Launch cancelled.'); } }
export interface RunningServer {
  port: number;
  stop(): Promise<void>;
  /** Authenticated loopback JSON request; the launch token never leaves this module. */
  request(path: string, body: unknown): Promise<unknown>;
}
export class HttpError extends Error { constructor(readonly status: number, message: string) { super(message); } }
export type Log = (line: string) => void;

// Buffer whole lines before redaction, including secrets split across chunks.
// An overlong line is discarded in full, not split into potentially secret pieces.
export class SafeLines {
  private pending = '';
  private discarding = false;
  constructor(private token: string, private emit: Log) {}
  push(chunk: string): void {
    for (const part of chunk.split(/(?<=\n)/)) {
      if (!this.discarding) this.pending += part;
      if (this.pending.length > 8192) { this.pending = ''; this.discarding = true; }
      if (part.endsWith('\n')) {
        if (this.discarding) this.emit('[overlong server log line omitted]');
        else this.emit(this.pending.split(this.token).join('[redacted]').replace(/[\x00-\x08\x0b-\x1f\x7f]/g, '').trimEnd());
        this.pending = ''; this.discarding = false;
      }
    }
  }
  // Never flush a partial line on process exit: it could be part of a secret.
}

export function probe(port: number, token: string, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const req = http.get({ hostname: '127.0.0.1', port, path: '/api/vscode/ready',
      headers: { 'X-SMC-Token': token }, signal, timeout: 2000 }, res => {
      let body = '';
      res.on('data', chunk => {
        body += chunk;
        if (body.length > 4096) req.destroy(new Error('Invalid readiness response.'));
      });
      res.on('error', reject);
      res.on('end', () => {
        try {
          const value = JSON.parse(body);
          const expected = createHash('sha256').update(token).digest('hex');
          if (res.statusCode !== 200 || value.protocol !== 1 || value.instance !== expected)
            throw new Error('Server instance verification failed.');
          resolve();
        } catch { reject(new Error('Server instance verification failed.')); }
      });
    });
    req.on('timeout', () => req.destroy(new Error('Server readiness request timed out.')));
    req.on('error', reject);
  });
}

const MAX_RESPONSE = 16 * 1024 * 1024;
export function requestJson(port: number, token: string, path: string, body: unknown,
  timeoutMs = 120000): Promise<unknown> {
  if (!/^\/api\/[a-z0-9/-]+$/.test(path)) return Promise.reject(new Error('Invalid local API path.'));
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify(body ?? {});
    const req = http.request({ hostname: '127.0.0.1', port, path, method: 'POST', timeout: timeoutMs,
      headers: { 'X-SMC-Token': token, 'Content-Type': 'application/json', 'Accept-Encoding': 'identity',
        'Content-Length': Buffer.byteLength(payload) } }, res => {
      const chunks: Buffer[] = [];
      let size = 0;
      res.on('data', (chunk: Buffer) => {
        size += chunk.length;
        if (size > MAX_RESPONSE) req.destroy(new Error('Server response is too large.'));
        else chunks.push(chunk);
      });
      res.on('error', reject);
      res.on('end', () => {
        let value: any;
        try { value = JSON.parse(Buffer.concat(chunks).toString('utf8')); }
        catch { reject(new Error('Invalid server response.')); return; }
        if (res.statusCode !== 200) {
          reject(new HttpError(res.statusCode || 0, typeof value?.error === 'string' && value.error.length < 2000
            ? value.error : `Server request failed (${res.statusCode}).`));
        } else resolve(value);
      });
    });
    req.on('timeout', () => req.destroy(new Error('Server request timed out.')));
    req.on('error', reject);
    req.end(payload);
  });
}

export async function startServer(config: LaunchConfig, ancestors: string[], signal: AbortSignal,
  log: Log, onExit: () => void, timeoutMs = 15000): Promise<RunningServer> {
  validateAncestors(ancestors);
  if (signal.aborted) throw new Cancelled();
  const token = randomBytes(32).toString('hex');
  const child: ChildProcessWithoutNullStreams = spawn(config.executable,
    [...config.args, '--vscode', '--host', '127.0.0.1', '--port', '0', config.cwd], {
      cwd: config.cwd, shell: false, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, SMC_VSCODE_TOKEN: token,
        SMC_VSCODE_ANCESTORS: JSON.stringify(ancestors), SMC_VSCODE_FEATURES: 'scope', PYTHONUNBUFFERED: '1' }
    });
  let exited = false;
  let stopping = false;
  let stopPromise: Promise<void> | undefined;
  let ready = false;
  let settleExit!: () => void;
  const closed = new Promise<void>(resolve => { settleExit = resolve; });
  child.once('close', () => { exited = true; settleExit(); if (ready && !stopping) onExit(); });
  // A child may close stdin before we stop it; never let EPIPE escape.
  child.stdin.on('error', () => {});
  const stop = (): Promise<void> => {
    if (stopPromise) return stopPromise;
    stopping = true;
    stopPromise = (async () => {
      if (exited) return;
      child.stdin.end();
      child.kill('SIGTERM');
      const force = setTimeout(() => { if (!exited) child.kill('SIGKILL'); }, 1500);
      try { await closed; } finally { clearTimeout(force); signal.removeEventListener('abort', abort); }
    })();
    return stopPromise;
  };
  const abort = () => { void stop(); };
  signal.addEventListener('abort', abort, { once: true });
  let timer: NodeJS.Timeout | undefined;
  try {
    const port = await new Promise<number>((resolve, reject) => {
      let announcement = false;
      const stdout = new SafeLines(token, line => {
        if (line.startsWith('SMC_VSCODE_READY ')) {
          if (announcement) return;
          announcement = true;
          try {
            const value = JSON.parse(line.slice('SMC_VSCODE_READY '.length));
            if (value.protocol !== 1 || !Number.isInteger(value.port) || value.port < 1 || value.port > 65535)
              throw new Error();
            resolve(value.port);
          } catch { reject(new Error('Invalid server startup protocol. Install the matching SMC engine.')); }
        } else log(line);
      });
      const stderr = new SafeLines(token, log);
      child.stdout.setEncoding('utf8').on('data', chunk => stdout.push(chunk));
      child.stderr.setEncoding('utf8').on('data', chunk => stderr.push(chunk));
      child.once('error', () => reject(new Error('Could not start SMC. Set semanticModelCleaner.pythonPath to a Python environment with this SMC checkout installed, or executable to a compatible smc-web. Nothing was installed automatically.')));
      child.once('close', code => reject(signal.aborted ? new Cancelled() :
        new Error(`SMC exited before readiness (code ${code}). Check Show Logs; the engine must support --vscode.`)));
      timer = setTimeout(() => reject(new Error('SMC startup timed out. Check Show Logs and the configured Python/SMC installation.')), timeoutMs);
    });
    await probe(port, token, signal);
    if (signal.aborted) throw new Cancelled();
    if (exited) throw new Error('SMC exited during startup.');
    ready = true;
    log(`SMC ready on loopback port ${port}.`);
    return { port, stop, request: (path, body) => exited || stopping
      ? Promise.reject(new Error('The Cleaner server is not running.')) : requestJson(port, token, path, body) };
  } catch (error) {
    await stop();
    if (signal.aborted) throw new Cancelled();
    throw error;
  } finally { clearTimeout(timer); }
}

// Latest request wins. Every superseded start is aborted and fully stopped
// before the next spawn; panel disposal can cancel an in-flight launch.
export class ServerManager {
  private generation = 0;
  private abort?: AbortController;
  private current?: RunningServer;
  private pending?: Promise<RunningServer>;
  private shutdown: Promise<void> = Promise.resolve();
  async start(config: LaunchConfig, ancestors: string[], log: Log, onExit: () => void): Promise<RunningServer> {
    const shutdown = this.stop();
    const generation = this.generation;
    await shutdown;
    if (generation !== this.generation) throw new Cancelled();
    const abort = this.abort = new AbortController();
    const pending = this.pending = startServer(config, ancestors, abort.signal, log, () => {
      if (generation === this.generation) { this.current = undefined; onExit(); }
    });
    try {
      const server = await pending;
      if (generation !== this.generation) { await server.stop(); throw new Cancelled(); }
      this.current = server;
      return server;
    } finally { if (this.pending === pending) this.pending = undefined; }
  }
  stop(): Promise<void> {
    this.generation++;
    this.abort?.abort();
    const pending = this.pending;
    const current = this.current;
    this.current = undefined;
    this.shutdown = this.shutdown.then(async () => {
      if (current) await current.stop();
      if (pending) { try { await (await pending).stop(); } catch { /* launch handles cleanup */ } }
    });
    return this.shutdown;
  }
}
