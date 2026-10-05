#!/usr/bin/env node
import { spawn, spawnSync } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { pathToFileURL } from 'node:url';

const publicHostPattern = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.fly\.dev$/;
const sha256Pattern = /^[a-f0-9]{64}$/;

async function directory(filename, uid, gid, mode) {
  await fs.mkdir(filename, { recursive: true, mode });
  const metadata = await fs.lstat(filename);
  if (!metadata.isDirectory() || metadata.isSymbolicLink()) throw new Error('A required directory has an unsafe file type.');
  if (await fs.realpath(filename) !== filename) throw new Error('A required directory traverses a symbolic link.');
  await fs.chown(filename, uid, gid);
  await fs.chmod(filename, mode);
}

async function privateBytes(filename) {
  const metadata = await fs.lstat(filename);
  if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.nlink !== 1
      || metadata.size > 8 * 1024 * 1024 || await fs.realpath(filename) !== filename) {
    throw new Error('A private configuration file has an unsafe file type.');
  }
  return fs.readFile(filename);
}

async function publishPrivate(filename, bytes) {
  const temporary = path.join(path.dirname(filename), `.bootstrap-${randomUUID()}`);
  let file;
  try {
    try {
      const old = await fs.lstat(filename);
      if (!old.isFile() || old.isSymbolicLink() || old.uid !== 0) throw new Error('Unsafe existing private runtime file.');
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
    file = await fs.open(temporary, 'wx', 0o440);
    await file.writeFile(bytes);
    await file.chown(0, 1000);
    await file.chmod(0o440);
    await file.sync();
    await file.close();
    file = undefined;
    await fs.rename(temporary, filename);
  } finally {
    await file?.close().catch(() => undefined);
    await fs.unlink(temporary).catch(() => undefined);
  }
}

async function fixedSymlink(filename, target) {
  try {
    const metadata = await fs.lstat(filename);
    if (metadata.isSymbolicLink() && await fs.readlink(filename) === target) return;
    // Image-created empty mount directories may be replaced with the fixed link.
    if (metadata.isDirectory() && (await fs.readdir(filename)).length === 0) await fs.rmdir(filename);
    else throw new Error('A runtime mount alias has an unexpected target.');
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
  await fs.symlink(target, filename);
}

async function sealDataset() {
  const receipt = '/data/.fly-readonly-dataset.json';
  try {
    const metadata = await fs.lstat(receipt);
    if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.uid !== 0
        || metadata.mode & 0o022) throw new Error('Unsafe dataset permissions receipt.');
    return;
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
  const pending = ['/data/banking-data'];
  while (pending.length) {
    const filename = pending.pop();
    const metadata = await fs.lstat(filename);
    if (metadata.isSymbolicLink() || (!metadata.isFile() && !metadata.isDirectory())) throw new Error('Dataset contains an unsupported file type.');
    if (metadata.isDirectory()) {
      for (const name of await fs.readdir(filename)) pending.push(path.join(filename, name));
    }
    await fs.chown(filename, 0, 1000);
    await fs.chmod(filename, metadata.isDirectory() ? 0o550 : 0o440);
  }
  await publishPrivate(receipt, Buffer.from('{"version":1,"readOnly":true}\n'));
}

async function ownMutableState() {
  const receipt = '/data/.fly-state-ownership.json';
  try {
    const metadata = await fs.lstat(receipt);
    if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.uid !== 0
        || metadata.mode & 0o022) throw new Error('Unsafe state ownership receipt.');
    return;
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
  const pending = ['/data/flujo', '/data/banking-state', '/data/banking-demo-state', '/data/frontend-state'];
  while (pending.length) {
    const filename = pending.pop();
    const metadata = await fs.lstat(filename);
    if (metadata.isSymbolicLink()) {
      // npm's executable links are valid; never follow them outside the tree.
      await fs.lchown(filename, 1000, 1000);
      continue;
    }
    if (!metadata.isFile() && !metadata.isDirectory()) throw new Error('Mutable state contains an unsupported file type.');
    if (metadata.isDirectory()) {
      for (const name of await fs.readdir(filename)) pending.push(path.join(filename, name));
    }
    await fs.chown(filename, 1000, 1000);
  }
  await publishPrivate(receipt, Buffer.from('{"version":1,"uid":1000,"gid":1000}\n'));
}

/** Root-only staging uses private volume contents; no credentials enter images. */
export async function bootstrap(env = process.env) {
  if (process.platform !== 'linux' || process.getuid?.() !== 0) throw new Error('Protected bootstrap requires Linux root.');
  const migration = JSON.parse((await privateBytes('/data/.migration-complete.json')).toString('utf8'));
  if (!migration || typeof migration !== 'object' || Array.isArray(migration)) throw new Error('Migration completion receipt is invalid.');
  await directory('/data', 0, 1000, 0o750);
  await directory('/data/private', 0, 0, 0o700);
  for (const filename of ['/data/flujo', '/data/flujo/banking-authority', '/data/banking-state', '/data/banking-demo-state', '/data/frontend-state']) {
    await directory(filename, 1000, 1000, 0o700);
  }
  for (const filename of ['/run/banking', '/run/frontend', '/run/secrets', '/bootstrap']) await directory(filename, 0, 1000, 0o750);

  for (const name of ['policy.json', 'bank-config.json', 'operator-config.json', 'demo-config.json', 'bank-signer.pem', 'restricted-model-catalog.json', 'source.env']) {
    await publishPrivate(`/run/banking/${name}`, await privateBytes(`/data/private/banking/${name}`));
  }
  await publishPrivate('/bootstrap/worker.snapshot', await privateBytes('/data/private/worker.snapshot'));
  const frontend = JSON.parse((await privateBytes('/data/private/frontend/frontend.json')).toString('utf8'));
  if (!frontend || typeof frontend !== 'object' || !frontend.chat || typeof frontend.chat !== 'object') throw new Error('Frontend chat configuration is missing.');
  frontend.chat.base_url = 'http://127.0.0.1:4200';
  frontend.chat.frontend_signing_key_file = '/run/frontend/frontend-signer.pem';
  await publishPrivate('/run/frontend/frontend.json', Buffer.from(`${JSON.stringify(frontend)}\n`));
  await publishPrivate('/run/frontend/frontend-signer.pem', await privateBytes('/data/private/frontend/signer.pem'));
  for (const [source, target] of [['github-token', 'github_token'], ['github-signing-key', 'github_signing_key'], ['github-allowed-signers', 'github_allowed_signers']]) {
    await publishPrivate(`/run/secrets/${target}`, await privateBytes(`/data/private/github/${source}`));
  }
  await fixedSymlink('/banking-data', '/data/banking-data');
  await fixedSymlink('/banking-state', '/data/banking-state');
  await fixedSymlink('/banking-demo-state', '/data/banking-demo-state');
  await fixedSymlink('/banking-config', '/run/frontend');
  await ownMutableState();
  await sealDataset();

  const policyDigest = env.FLUJO_FLY_POLICY_SHA256?.trim().toLowerCase();
  if (!policyDigest || !sha256Pattern.test(policyDigest)) throw new Error('Bootstrap requires the approved banking policy SHA256.');
  const actualDigest = createHash('sha256').update(await fs.readFile('/run/banking/policy.json')).digest('hex');
  if (actualDigest !== policyDigest) throw new Error('The banking policy does not match its approved digest.');
  const provision = spawnSync(process.execPath, ['/opt/banking-mcp/scripts/provision_banking_runtime_policy.mjs', policyDigest], {
    cwd: '/app', stdio: 'inherit', env,
  });
  if (provision.error || provision.status !== 0) throw new Error('Protected banking policy provisioning failed.');
  console.log('[Savia Fly] Protected bootstrap completed.');
}

function childBase(env) {
  const child = { ...env };
  for (const key of Object.keys(child)) {
    if (key.startsWith('FLUJO_FLY_IMPORT') || key.startsWith('FLUJO_FLY_MIGRATION')
        || key.startsWith('FLUJO_DEV_UI_') || key === 'FLUJO_FLY_DEV_UI_ENABLED'
        || key === 'FLUJO_FLY_POLICY_SHA256') delete child[key];
  }
  return child;
}

function withoutWorkerSecrets(env) {
  for (const key of Object.keys(env)) {
    if (key.startsWith('FLUJO_WORKER_') || key === 'FLUJO_SNAPSHOT_CONTROL_TOKEN'
        || key === 'FLUJO_BANKING_CONFIG') delete env[key];
  }
  return env;
}

export function runtimeEnvironment(env = process.env, { now = Date.now } = {}) {
  const hostname = (env.FLUJO_FLY_MAIN_HOST || 'flujo-factored-2026.fly.dev').trim().toLowerCase();
  if (!publicHostPattern.test(hostname)) throw new Error('Invalid Fly application hostname.');
  const worker = {
    ...childBase(env),
    FLUJO_CONTAINER: '1', FLUJO_APP_ROOT: '/app', FLUJO_DATA_DIR: '/data/flujo',
    FLUJO_WORKER_MODE: '1', FLUJO_WORKER_SNAPSHOT: '/bootstrap/worker.snapshot',
    FLUJO_EXPOSURE_MODE: 'localhost', FLUJO_BASE_URL: 'http://127.0.0.1:4200',
    FLUJO_BANKING_CONFIG: '/run/banking-runtime/policy.json',
    FLUJO_MCP_APP_SANDBOX_HOST: '127.0.0.1', FLUJO_MCP_APP_SANDBOX_PORT: '4201',
    FLUJO_MCP_APP_SANDBOX_ALLOW_ALL: '0',
    GIT_CONFIG_GLOBAL: '/app/github/gitconfig-signing',
  };
  delete worker.FLUJO_FLY_PASSWORD;
  delete worker.FLUJO_FLY_USERNAME;
  delete worker.FLUJO_PARENT_DATA_DIR;
  const frontend = withoutWorkerSecrets(childBase(env));
  delete frontend.FLUJO_FLY_PASSWORD;
  delete frontend.FLUJO_FLY_USERNAME;
  Object.assign(frontend, {
    BANKING_DATA_DIR: '/banking-data', BANKING_CONFIG_FILE: '/run/frontend/frontend.json',
    BANKING_STATE_DIR: '/data/frontend-state', BANKING_STATIC_DIR: '/opt/savia/dist',
    BANKING_PUBLIC_ORIGIN: `https://${hostname}`, BANKING_COOKIE_SECURE: '1',
    PYTHONDONTWRITEBYTECODE: '1', PYTHONUNBUFFERED: '1',
  });
  const gateway = withoutWorkerSecrets(childBase(env));
  gateway.FLUJO_FLY_MAIN_HOST = hostname;
  gateway.FLUJO_FLY_UPSTREAM_PORT = '8082';
  gateway.FLUJO_SNAPSHOT_CONTROL_TOKEN = env.FLUJO_SNAPSHOT_CONTROL_TOKEN;
  let dev;
  if (env.FLUJO_DEV_UI_ENABLED === '1') {
    const devHost = env.FLUJO_DEV_UI_HOST;
    const deadline = Date.parse(env.FLUJO_DEV_UI_EXPIRES_AT);
    if (!publicHostPattern.test(devHost || '') || devHost !== 'flujo-factored-dev-2026.fly.dev'
        || devHost === hostname) throw new Error('A separate development hostname is required.');
    if (!Number.isFinite(deadline) || new Date(deadline).toISOString() !== env.FLUJO_DEV_UI_EXPIRES_AT) {
      throw new Error('A canonical development expiry is required.');
    }
    // An expired optional child must never interrupt Savia on restart.
    if (now() >= deadline) return { worker, frontend, gateway, dev };
    for (const key of ['FLUJO_DEV_UI_MARIO_PASSWORD', 'FLUJO_DEV_UI_GLORIA_PASSWORD']) {
      if (typeof env[key] !== 'string' || env[key].length < 24) throw new Error('Development UI credentials are missing or too short.');
    }
    // Explicit allowlist: this gateway can authenticate its two development
    // users and proxy the worker; no snapshot encryption or banking keys belong
    // in its environment. All existing children use childBase's dev-key filter.
    dev = {
      PATH: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
      HOME: '/home/node', TMPDIR: '/tmp', NODE_ENV: 'production',
      FLUJO_DEV_UI_ENABLED: '1', FLUJO_DEV_UI_HOST: devHost,
      FLUJO_DEV_UI_EXPIRES_AT: env.FLUJO_DEV_UI_EXPIRES_AT,
      FLUJO_DEV_UI_MARIO_PASSWORD: env.FLUJO_DEV_UI_MARIO_PASSWORD,
      FLUJO_DEV_UI_GLORIA_PASSWORD: env.FLUJO_DEV_UI_GLORIA_PASSWORD,
      FLUJO_SNAPSHOT_CONTROL_TOKEN: env.FLUJO_SNAPSHOT_CONTROL_TOKEN,
    };
  }
  return { worker, frontend, gateway, dev };
}

export function runtimeCommands({ worker, frontend, gateway, dev } = runtimeEnvironment()) {
  const commands = [
    { name: 'FLUJO worker', args: ['scripts/launch-next.mjs', 'start', '-p', '4200', '-H', '127.0.0.1'], env: worker },
    { name: 'Savia frontend', command: '/opt/savia/.venv/bin/python', args: ['-m', 'uvicorn', 'server.app:app', '--host', '127.0.0.1', '--port', '8082', '--no-access-log', '--proxy-headers', '--forwarded-allow-ips', '127.0.0.1'], cwd: '/opt/savia', env: frontend },
    { name: 'public gateway', args: ['/opt/savia/fly/gateway.mjs'], env: gateway },
  ];
  if (dev) commands.push({ name: 'development UI gateway', args: ['/opt/savia/fly/dev-gateway.mjs'], env: dev });
  return commands;
}

/** All children lead separate process groups; every shutdown kills descendants. */
export function supervise({ commands, graceMs = 10_000 } = {}) {
  if (!Array.isArray(commands) || !commands.length) throw new Error('No runtime services configured.');
  return new Promise(resolve => {
    const entries = [];
    let stopping = false;
    let starting = true;
    let exitCode = 0;
    let forceTimer;
    const signal = (child, value) => {
      if (!child.pid) return;
      try { process.kill(-child.pid, value); }
      catch (error) { if (error.code !== 'ESRCH') console.error('[Savia Fly] Runtime process group signal failed.'); }
    };
    const cleanup = () => {
      clearTimeout(forceTimer);
      process.removeListener('SIGTERM', onSigterm);
      process.removeListener('SIGINT', onSigint);
    };
    const finish = () => {
      if (starting || !stopping || entries.some(entry => !entry.exited)) return;
      for (const { child } of entries) signal(child, 'SIGKILL');
      cleanup();
      resolve(exitCode);
    };
    const stop = (value, code) => {
      if (stopping) return;
      stopping = true;
      exitCode = code;
      for (const { child } of entries) signal(child, value);
      forceTimer = setTimeout(() => {
        for (const { child } of entries) signal(child, 'SIGKILL');
        cleanup();
        resolve(exitCode);
      }, graceMs);
      finish();
    };
    const onSigterm = () => stop('SIGTERM', 143);
    const onSigint = () => stop('SIGINT', 130);
    process.on('SIGTERM', onSigterm);
    process.on('SIGINT', onSigint);
    for (const { name, command = process.execPath, args, cwd = '/app', env } of commands) {
      if (stopping) break;
      let child;
      try { child = spawn(command, args, { cwd, env, stdio: 'inherit', detached: true }); }
      catch { console.error(`[Savia Fly] Could not launch ${name}.`); stop('SIGTERM', 1); break; }
      const entry = { child, exited: false };
      entries.push(entry);
      child.once('error', () => {
        entry.exited = true;
        console.error(`[Savia Fly] Could not launch ${name}.`);
        stop('SIGTERM', 1);
        finish();
      });
      child.once('exit', code => {
        entry.exited = true;
        if (!stopping) {
          console.error(`[Savia Fly] ${name} exited; stopping the runtime.`);
          stop('SIGTERM', code && code > 0 ? code : 1);
        }
        finish();
      });
    }
    starting = false;
    finish();
  });
}

async function main() {
  if (process.argv[2] === '--bootstrap') return bootstrap();
  if (process.getuid?.() !== 1000) throw new Error('Runtime services must run as the node user.');
  const environment = runtimeEnvironment();
  const { worker } = environment;
  if (!worker.FLUJO_WORKER_SNAPSHOT_KEY || !sha256Pattern.test(worker.FLUJO_WORKER_SNAPSHOT_SHA256 ?? '')
      || !worker.FLUJO_SNAPSHOT_CONTROL_TOKEN) throw new Error('The original worker bootstrap credentials are required.');
  process.exit(await supervise({ commands: runtimeCommands(environment) }));
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  main().catch(error => {
    console.error(`[Savia Fly] ${error.message}`);
    process.exit(1);
  });
}
