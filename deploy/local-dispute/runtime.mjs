#!/usr/bin/env node
/** Persistent loopback demo using the joined image's real native worker. */
import fs from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import http from 'node:http';
import path from 'node:path';
import process from 'node:process';
import { pathToFileURL } from 'node:url';
import { initializeNativeModel, supervise } from '../fly/runtime.mjs';

export const ROOT = '/data/local-demo';
export const CONTROL = '/data/native-authority/control';
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const BASE = { PATH: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
  NODE_ENV: 'production', TMPDIR: '/tmp', PYTHONDONTWRITEBYTECODE: '1', PYTHONUNBUFFERED: '1' };

export function localOrigin(value = 'http://127.0.0.1:43900') {
  const url = new URL(value);
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !url.port
    || +url.port <= 1024 || url.username || url.password || url.pathname !== '/'
    || url.search || url.hash || value !== url.origin || value !== 'http://127.0.0.1:43900') throw Error('Exact IPv4 loopback origin required.');
  return url.origin;
}
async function directory(location, uid, gid, mode) {
  let created = false;
  try { await fs.mkdir(location, { mode }); created = true; }
  catch (error) { if (error.code !== 'EEXIST') throw error; }
  const stat = await fs.lstat(location);
  if (!stat.isDirectory() || stat.isSymbolicLink() || await fs.realpath(location) !== location)
    throw Error('Unsafe demo directory.');
  if (created) { await fs.chown(location, uid, gid); await fs.chmod(location, mode); }
  else if (stat.uid !== uid || stat.gid !== gid || (stat.mode & 0o7777) !== mode)
    throw Error('Changed demo directory authority.');
}
async function publish(location, bytes, uid, gid, mode, retain = false) {
  if (retain) {
    try {
      const stat = await fs.lstat(location);
      if (!stat.isFile() || stat.isSymbolicLink() || stat.uid !== uid || stat.gid !== gid
        || (stat.mode & 0o7777) !== mode) throw Error('Changed retained control authority.');
      return;
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  const temporary = path.join(path.dirname(location), '.local-' + randomUUID());
  let file;
  try {
    file = await fs.open(temporary, 'wx', mode);
    await file.writeFile(bytes); await file.chown(uid, gid); await file.chmod(mode);
    await file.sync(); await file.close(); file = undefined;
    await fs.rename(temporary, location);
  } finally { await file?.close(); await fs.unlink(temporary).catch(() => {}); }
}
async function execute(command, args, options = {}) {
  await new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: 'inherit', ...options });
    child.once('error', reject); child.once('exit', code => code === 0 ? resolve() : reject(Error('Local preparation failed.')));
  });
}
export async function bootstrap(origin) {
  if (process.platform !== 'linux' || process.getuid() !== 0) throw Error('Joined Linux image required.');
  const marker = '/data/LOCAL_DISPUTE_VOLUME.json';
  try {
    const stat = await fs.lstat(marker), value = JSON.parse(await fs.readFile(marker, 'utf8'));
    if (!stat.isFile() || stat.isSymbolicLink() || stat.uid !== 0 || (stat.mode & 0o077) !== 0
      || value.schema !== 'local-dispute-volume/v1' || value.origin !== origin) throw Error('Unexpected retained demo volume.');
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    if ((await fs.readdir('/data')).length) throw Error('Fresh dedicated demo volume required.');
    await publish(marker, JSON.stringify({ schema: 'local-dispute-volume/v1', origin,
      data: 'authored-synthetic-fixture', createdAt: new Date().toISOString() }) + '\n', 0, 0, 0o600);
  }
  await directory(ROOT, 10001, 10001, 0o700);
  await directory('/data/native-authority', 0, 10002, 0o751);
  await directory(CONTROL, 10001, 10002, 0o2750);
  await directory(CONTROL + '/revocations', 10001, 10002, 0o2750);
  await directory('/data/native-authority/worker', 1000, 1000, 0o700);
  await directory('/data/native-flujo', 1000, 1000, 0o700);
  await directory('/run/native-login', 0, 1000, 0o750);
  const auth = await fs.readFile('/run/local-input/auth.json');
  if (!JSON.parse(auth)) throw Error('File-backed provider login required.');
  await publish('/run/native-login/auth.json', auth, 0, 1000, 0o440);
  await publish('/run/native-login/config.toml', 'cli_auth_credentials_store = "file"\n', 0, 1000, 0o440);
  const profileBytes = await fs.readFile('/opt/native/native-profile.json');
  const profile = JSON.parse(profileBytes);
  for (const [filename, expected] of [[profile.verifiedCliPath, profile.verifiedCliSha256],
    [profile.verifiedModelCatalogPath, profile.verifiedModelCatalogSha256]]) {
    if (!/^[a-f0-9]{64}$/.test(expected) || sha(await fs.readFile(filename)) !== expected)
      throw Error('Native immutable profile mismatch.');
  }
  await publish(CONTROL + '/native-profile.json', profileBytes, 0, 10002, 0o440);
  await publish(CONTROL + '/admissions.json', '[]\n', 10001, 10002, 0o640, true);
  await execute('/usr/sbin/gosu', ['banking', '/opt/joined/.venv/bin/python',
    '/local-demo-source/scripts/local_dispute_demo.py', 'prepare', '--root', ROOT],
    { cwd: '/local-demo-source', env: { ...BASE, HOME: '/nonexistent' } });
  console.log('Authored local fixture prepared. Native provider and intake acceptance remain to be verified.');
}

export function commands(origin) {
  const worker = { ...BASE, HOME: '/home/node', CODEX_HOME: '/run/native-login', FLUJO_CONTAINER: '1',
    FLUJO_APP_ROOT: '/app', FLUJO_DATA_DIR: '/data/native-flujo', FLUJO_EXPOSURE_MODE: 'localhost',
    FLUJO_BASE_URL: 'http://127.0.0.1:4200', FLUJO_MCP_APP_SANDBOX_HOST: '127.0.0.1',
    FLUJO_MCP_APP_SANDBOX_PORT: '4201', FLUJO_MCP_APP_SANDBOX_ALLOW_ALL: '0',
    FLUJO_EXECUTION_ADAPTER_MODULE: '/app/fly-native-execution.ts' };
  return [
    { name: 'native Dispute worker', command: '/usr/sbin/gosu', args: ['node', 'node',
      'scripts/launch-next.mjs', 'start', '-p', '4200', '-H', '127.0.0.1'], cwd: '/app', env: worker },
    { name: 'local Dispute application', command: '/usr/sbin/gosu', args: ['banking',
      '/opt/joined/.venv/bin/python', '/local-demo-source/scripts/local_dispute_demo.py', 'serve',
      '--root', ROOT, '--static-dir', '/opt/savia/dist', '--port', '8082', '--native-url', 'http://127.0.0.1:4200',
      '--native-authority-dir', CONTROL, '--native-reader-group', '10002', '--public-origin', origin],
      cwd: '/local-demo-source', env: { ...BASE, HOME: '/nonexistent' } },
  ];
}

/** Only the user-bound application is exposed; worker APIs stay inside the container. */
export function createGateway(origin, upstreamPort = 8082) {
  const host = new URL(localOrigin(origin)).host;
  return http.createServer((request, response) => {
    if (request.headers.host !== host) { response.writeHead(421); response.end(); return; }
    if (request.headers.origin && request.headers.origin !== origin) { response.writeHead(403); response.end(); return; }
    const headers = { ...request.headers };
    for (const name of ['forwarded', 'x-forwarded-host', 'x-forwarded-proto', 'x-forwarded-for']) delete headers[name];
    const upstream = http.request({ host: '127.0.0.1', port: upstreamPort, method: request.method,
      path: request.url, headers, timeout: 600000 }, incoming => {
      response.writeHead(incoming.statusCode, incoming.headers); incoming.pipe(response);
    });
    upstream.on('timeout', () => upstream.destroy());
    upstream.on('error', () => { if (!response.headersSent) response.writeHead(503); response.end(); });
    request.on('aborted', () => upstream.destroy());
    request.pipe(upstream);
  });
}
async function main() {
  const origin = localOrigin(process.env.LOCAL_DISPUTE_ORIGIN);
  await bootstrap(origin);
  const gateway = createGateway(origin);
  gateway.listen(8080, '0.0.0.0'); // Docker publishes this port on host 127.0.0.1 only.
  const code = await supervise({ commands: commands(origin), onStarted: initializeNativeModel });
  gateway.close(); process.exitCode = code;
}
if (import.meta.url === pathToFileURL(process.argv[1] || '').href)
  main().catch(() => { console.error('Local Dispute runtime startup failed.'); process.exitCode = 1; });
