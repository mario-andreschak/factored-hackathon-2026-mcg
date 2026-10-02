#!/usr/bin/env node
/** Root supervisor; one native worker and one joined banking application. */
import { spawn } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { pathToFileURL } from 'node:url';

const HOST = 'flujo-factored-2026.fly.dev';
const PRIVATE = '/data/private/joined';
const CONTROL = '/data/native-authority/control';
const EVIDENCE = '/data/native-transition-evidence';
const BANK_ARCHIVE = '/data/banking-state/legacy-bank-before-native.sqlite3';
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
async function directory(filename, uid, gid, mode) {
  await fs.mkdir(filename, { recursive: true, mode });
  const stat = await fs.lstat(filename);
  if (!stat.isDirectory() || stat.isSymbolicLink() || await fs.realpath(filename) !== filename) throw Error('Unsafe runtime directory.');
  await fs.chown(filename, uid, gid); await fs.chmod(filename, mode);
}
async function privateBytes(filename, uid = 0) {
  const stat = await fs.lstat(filename);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.nlink !== 1 || stat.size > 16 * 1024 * 1024
    || stat.uid !== uid || (stat.mode & 0o022) !== 0
    || await fs.realpath(filename) !== filename) throw Error('Unsafe private runtime input.');
  const bytes = await fs.readFile(filename), after = await fs.lstat(filename);
  if (stat.ino !== after.ino || stat.dev !== after.dev || stat.size !== bytes.length
    || stat.mtimeMs !== after.mtimeMs || stat.ctimeMs !== after.ctimeMs) throw Error('Private runtime input changed during bootstrap.');
  return bytes;
}
async function publish(filename, bytes, uid, gid, mode) {
  const temporary = path.join(path.dirname(filename), '.bootstrap-' + randomUUID());
  let file;
  try {
    try { const old = await fs.lstat(filename); if (!old.isFile() || old.isSymbolicLink()) throw Error('Unsafe runtime file.'); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    file = await fs.open(temporary, 'wx', mode); await file.writeFile(bytes);
    await file.chown(uid, gid); await file.chmod(mode); await file.sync(); await file.close(); file = undefined;
    await fs.rename(temporary, filename);
  } finally { await file?.close(); await fs.unlink(temporary).catch(() => {}); }
}
async function sealTree(root, uid, gid, directoryMode, fileMode, excluded = new Set()) {
  const pending = [root];
  while (pending.length) {
    const filename = pending.pop();
    if (excluded.has(filename)) continue;
    const stat = await fs.lstat(filename);
    if (stat.isSymbolicLink() || !stat.isFile() && !stat.isDirectory()
      || stat.isFile() && stat.nlink !== 1) throw Error('Unsupported persistent state file.');
    if (stat.isDirectory()) for (const name of await fs.readdir(filename)) pending.push(path.join(filename, name));
    await fs.chown(filename, uid, gid); await fs.chmod(filename, stat.isDirectory() ? directoryMode : fileMode);
  }
}
/** Pin evidence paths before migration; never relocate paths inside a saved receipt. */
export function transitionEvidenceFiles(saved) {
  const proof = saved?.operator_proof;
  if (!proof || !Array.isArray(proof.obligation_artifacts) || !proof.archives
    || saved.archive_path !== BANK_ARCHIVE) throw Error('Incomplete retained transition evidence.');
  const files = [proof.path, proof.coverage_proof_path, proof.lease_artifact?.path,
    proof.authority_artifact?.path, ...proof.obligation_artifacts.map(item => item?.path),
    proof.archives.frontend?.path, proof.archives.worker?.path];
  if (files.some(filename => typeof filename !== 'string' || !filename.startsWith(EVIDENCE + '/')
    || path.posix.normalize(filename) !== filename || filename.includes('\0')))
    throw Error('Transition evidence must use the retained bank-only directory.');
  return [...new Set(files), BANK_ARCHIVE];
}
async function sealTransitionEvidence(saved) {
  const files = transitionEvidenceFiles(saved);
  for (const filename of files) {
    const stat = await fs.lstat(filename);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.nlink !== 1 || stat.uid !== 0
      || (stat.mode & 0o022) !== 0 || await fs.realpath(filename) !== filename)
      throw Error('Unsafe retained transition evidence file.');
  }
  await sealTree(EVIDENCE, 0, 10001, 0o550, 0o440);
  return files;
}
export async function bootstrap() {
  if (process.platform !== 'linux' || process.getuid() !== 0) throw Error('Linux root bootstrap required.');
  const privateParent = await fs.lstat('/data/private');
  if (!privateParent.isDirectory() || privateParent.isSymbolicLink() || privateParent.uid !== 0
    || (privateParent.mode & 0o777) !== 0o700) throw Error('Private input parent is not sealed.');
  // The source-owned transition validator in run_dispute rechecks this receipt
  // against the retained ledger before creating the new application.
  const receipt = await privateBytes(PRIVATE + '/transition-receipt.json');
  const bank = await privateBytes(PRIVATE + '/bank-config.json');
  const frontend = await privateBytes(PRIVATE + '/frontend.json');
  const savedReceipt = JSON.parse(receipt.toString());
  if (!savedReceipt || !JSON.parse(bank.toString()) || !JSON.parse(frontend.toString())) throw Error('Incomplete joined deployment inputs.');
  await sealTransitionEvidence(savedReceipt);
  await directory('/data', 0, 0, 0o755);
  await directory('/data/private', 0, 0, 0o700);
  await directory('/data/native-authority', 0, 10002, 0o751);
  await directory(CONTROL, 10001, 10002, 0o2750);
  await directory(CONTROL + '/revocations', 10001, 10002, 0o2750);
  await directory('/data/native-authority/worker', 1000, 1000, 0o700);
  await directory('/data/native-flujo', 1000, 1000, 0o700);
  await directory('/data/native-frontend-state', 10001, 10001, 0o700);
  await directory('/run/dispute', 0, 10001, 0o750);
  // Bank state and dataset never become readable by the worker UID.
  await sealTree('/data/banking-state', 10001, 10001, 0o700, 0o600, new Set([BANK_ARCHIVE]));
  await fs.chown(BANK_ARCHIVE, 0, 10001); await fs.chmod(BANK_ARCHIVE, 0o440);
  await sealTree('/data/banking-data', 0, 10001, 0o550, 0o440);
  await publish('/run/dispute/bank-config.json', bank, 0, 10001, 0o440);
  await publish('/run/dispute/frontend.json', frontend, 0, 10001, 0o440);
  await publish('/run/dispute/transition-receipt.json', receipt, 0, 10001, 0o440);
  await publish('/run/dispute/legacy-admission.json', await privateBytes(PRIVATE + '/legacy-admission.json'), 0, 10001, 0o440);
  await publish('/run/dispute/frontend-signer.pem', await privateBytes('/data/private/frontend/signer.pem'), 0, 10001, 0o440);
  await publish('/run/dispute/source.env', await privateBytes('/data/private/banking/source.env'), 0, 10001, 0o440);
  await publish(CONTROL + '/native-profile.json', await fs.readFile('/opt/native/native-profile.json'), 0, 10002, 0o440);
  try { await fs.lstat(CONTROL + '/admissions.json'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; await publish(CONTROL + '/admissions.json', Buffer.from('[]\n'), 10001, 10002, 0o640); }
  const admissionsPath = CONTROL + '/admissions.json', admissionMetadata = await fs.lstat(admissionsPath);
  if (!admissionMetadata.isFile() || admissionMetadata.isSymbolicLink() || admissionMetadata.nlink !== 1
    || admissionMetadata.uid !== 10001 || admissionMetadata.gid !== 10002
    || (admissionMetadata.mode & 0o7777) !== 0o640 || await fs.realpath(admissionsPath) !== admissionsPath
    || !Array.isArray(JSON.parse(await privateBytes(admissionsPath, 10001)))) throw Error('Unsafe retained native admissions.');
  // Retain existing tombstones and admissions on restart; never reset them.
  await directory('/run/native-login', 0, 1000, 0o750);
  const login = await privateBytes('/data/flujo/workspaces/default-workspace/db/codex-runtime/auth.json', 1000);
  await publish('/run/native-login/auth.json', login, 0, 1000, 0o440);
  await publish('/run/native-login/config.toml', Buffer.from('cli_auth_credentials_store = "file"\n'), 0, 1000, 0o440);
  // Retained legacy transcripts and worker authority remain private archives.
  // The read-only login copy above is the only credential granted to the worker.
  for (const filename of ['/data/flujo', '/data/frontend-state', '/data/banking-demo-state'])
    await directory(filename, 0, 0, 0o700);
  const profile = JSON.parse(await fs.readFile('/opt/native/native-profile.json', 'utf8'));
  for (const [filename, expected] of [[profile.verifiedCliPath, profile.verifiedCliSha256],
    [profile.verifiedModelCatalogPath, profile.verifiedModelCatalogSha256]]) {
    if (!/^[a-f0-9]{64}$/.test(expected) || sha(await fs.readFile(filename)) !== expected) throw Error('Native immutable profile mismatch.');
  }
  console.log('[Savia Fly] Joined private inputs staged; startup will validate retained ledger.');
}

const BASE = { PATH: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
  NODE_ENV: 'production', TMPDIR: '/tmp', PYTHONDONTWRITEBYTECODE: '1', PYTHONUNBUFFERED: '1' };
export function runtimeEnvironment(env = process.env, now = Date.now()) {
  if ((env.FLUJO_FLY_MAIN_HOST || HOST) !== HOST) throw Error('Unexpected application host.');
  const worker = { ...BASE, HOME: '/home/node', CODEX_HOME: '/run/native-login',
    FLUJO_CONTAINER: '1', FLUJO_APP_ROOT: '/app', FLUJO_DATA_DIR: '/data/native-flujo',
    FLUJO_EXPOSURE_MODE: 'localhost', FLUJO_BASE_URL: 'http://127.0.0.1:4200',
    FLUJO_MCP_APP_SANDBOX_HOST: '127.0.0.1', FLUJO_MCP_APP_SANDBOX_PORT: '4201',
    FLUJO_MCP_APP_SANDBOX_ALLOW_ALL: '0', FLUJO_EXECUTION_ADAPTER_MODULE: '/app/fly-native-execution.ts',
    FLUJO_SNAPSHOT_CONTROL_TOKEN: env.FLUJO_SNAPSHOT_CONTROL_TOKEN };
  const frontend = { ...BASE, HOME: '/nonexistent', BANKING_DATA_DIR: '/data/banking-data',
    BANKING_CONFIG_FILE: '/run/dispute/frontend.json', BANKING_STATE_DIR: '/data/native-frontend-state',
    BANKING_STATIC_DIR: '/opt/savia/dist', BANKING_PUBLIC_ORIGIN: 'https://' + HOST, BANKING_COOKIE_SECURE: '1' };
  const gateway = { ...BASE, HOME: '/home/node', FLUJO_FLY_MAIN_HOST: HOST, FLUJO_FLY_USERNAME: env.FLUJO_FLY_USERNAME || 'savia',
    FLUJO_FLY_PASSWORD: env.FLUJO_FLY_PASSWORD, FLUJO_SNAPSHOT_CONTROL_TOKEN: env.FLUJO_SNAPSHOT_CONTROL_TOKEN,
    FLUJO_FLY_UPSTREAM_PORT: '8082', FLUJO_FLY_NATIVE_MODE: '1' };
  let dev;
  if (env.FLUJO_DEV_UI_ENABLED === '1') {
    const expiry = Date.parse(env.FLUJO_DEV_UI_EXPIRES_AT);
    if (env.FLUJO_DEV_UI_HOST !== 'flujo-factored-dev-2026.fly.dev' || !Number.isFinite(expiry)) throw Error('Invalid development access boundary.');
    if (now < expiry) {
      for (const name of ['FLUJO_DEV_UI_MARIO_PASSWORD', 'FLUJO_DEV_UI_GLORIA_PASSWORD'])
        if (typeof env[name] !== 'string' || env[name].length < 24) throw Error('Missing development credential.');
      dev = { ...BASE, HOME: '/home/node', FLUJO_DEV_UI_ENABLED: '1', FLUJO_DEV_UI_HOST: env.FLUJO_DEV_UI_HOST,
        FLUJO_DEV_UI_EXPIRES_AT: env.FLUJO_DEV_UI_EXPIRES_AT, FLUJO_DEV_UI_MARIO_PASSWORD: env.FLUJO_DEV_UI_MARIO_PASSWORD,
        FLUJO_DEV_UI_GLORIA_PASSWORD: env.FLUJO_DEV_UI_GLORIA_PASSWORD, FLUJO_SNAPSHOT_CONTROL_TOKEN: env.FLUJO_SNAPSHOT_CONTROL_TOKEN };
    }
  }
  return { worker, frontend, gateway, dev };
}
export function runtimeCommands({ worker, frontend, gateway, dev } = runtimeEnvironment()) {
  const commands = [
    { name: 'native worker', command: '/usr/sbin/gosu', args: ['node', 'node', 'scripts/launch-next.mjs', 'start', '-p', '4200', '-H', '127.0.0.1'], cwd: '/app', env: worker },
    { name: 'joined banking application', command: '/usr/sbin/gosu', args: ['banking', '/opt/joined/.venv/bin/python', '/opt/joined/scripts/run_dispute.py',
      '--state-dir', '/data/banking-state', '--bank-config-file', '/run/dispute/bank-config.json', '--native-url', 'http://127.0.0.1:4200',
      '--native-authority-dir', CONTROL, '--transition-receipt', '/run/dispute/transition-receipt.json', '--application-source-root', '/opt/joined',
      '--native-reader-group', '10002', '--port', '8082', '--enable-simulated-intake'], cwd: '/opt/joined', env: frontend },
    { name: 'public gateway', command: '/usr/sbin/gosu', args: ['node', 'node', '/opt/savia/fly/gateway.mjs'], cwd: '/app', env: gateway },
  ];
  if (dev) commands.push({ name: 'development gateway', command: '/usr/sbin/gosu', args: ['node', 'node', '/opt/savia/fly/dev-gateway.mjs'], cwd: '/app', env: dev });
  return commands;
}
export async function initializeNativeModel() {
  const model = { id: 'dispute-native-model', name: 'gpt-6-sol', displayName: 'Dispute native qualified model',
    provider: 'codex', adapter: 'codex-cli', ApiKey: '', reasoningEffort: 'low', contextWindow: 100000, supportsTools: true, maxTurns: 4 };
  for (let attempt = 0; attempt < 90; attempt++) {
    try {
      const response = await fetch('http://127.0.0.1:4200/api/model', { signal: AbortSignal.timeout(2000) });
      if (!response.ok) throw Error('Worker is not ready.');
      const models = await response.json(), current = models.find(item => item.id === model.id);
      if (current) {
        if (Object.keys(model).some(key => current[key] !== model[key])) throw Error('Saved native model differs from the approved configuration.');
        return;
      }
      const installed = await fetch('http://127.0.0.1:4200/api/model', { method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify(model), signal: AbortSignal.timeout(5000) });
      if (installed.status !== 201) throw Error('Native model installation failed.');
    } catch (error) {
      if (error.message.includes('differs')) throw error;
      if (attempt === 89) throw Error('Native saved model did not become ready.');
    }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  throw Error('Native saved model read-back missing.');
}
export function supervise({ commands, graceMs = 10000, onStarted } = {}) {
  if (!commands?.length) throw Error('No runtime services configured.');
  return new Promise(resolve => {
    const entries = []; let stopping = false, starting = true, code = 0, timer;
    const signal = (child, value) => { if (child.pid) try { process.kill(-child.pid, value); } catch (error) { if (error.code !== 'ESRCH') console.error('Process group signal failed.'); } };
    const cleanup = () => { clearTimeout(timer); process.removeListener('SIGTERM', term); process.removeListener('SIGINT', interrupt); };
    const finish = () => { if (!starting && stopping && entries.every(item => item.exited)) { entries.forEach(item => signal(item.child, 'SIGKILL')); cleanup(); resolve(code); } };
    const stop = (value, result) => { if (stopping) return; stopping = true; code = result; entries.forEach(item => signal(item.child, value));
      timer = setTimeout(() => { entries.forEach(item => signal(item.child, 'SIGKILL')); cleanup(); resolve(code); }, graceMs); finish(); };
    const term = () => stop('SIGTERM', 143), interrupt = () => stop('SIGINT', 130);
    process.on('SIGTERM', term); process.on('SIGINT', interrupt);
    for (const { name, command, args, cwd, env } of commands) {
      if (stopping) break;
      const child = spawn(command, args, { cwd, env, stdio: 'inherit', detached: true }), entry = { child, exited: false }; entries.push(entry);
      child.once('error', () => { entry.exited = true; console.error('Could not launch ' + name); stop('SIGTERM', 1); finish(); });
      child.once('exit', result => { entry.exited = true; if (!stopping) { console.error(name + ' exited; stopping runtime.'); stop('SIGTERM', result || 1); } finish(); });
    }
    starting = false; finish();
    if (onStarted) Promise.resolve().then(onStarted).catch(() => { console.error('Runtime admission startup failed.'); stop('SIGTERM', 1); });
  });
}
async function main() {
  if (process.argv[2] === '--bootstrap') return bootstrap();
  if (process.getuid?.() !== 0) throw Error('UID-separated supervisor requires root.');
  process.exit(await supervise({ commands: runtimeCommands(), onStarted: initializeNativeModel }));
}
if (import.meta.url === pathToFileURL(process.argv[1] || '').href) main().catch(error => { console.error('[Savia Fly] ' + error.message); process.exit(1); });
