#!/usr/local/bin/node
/** The restricted SDK executable. Its hash and the raw CLI hash are separate pins. */
import { createHash } from 'node:crypto';
import { createReadStream, lstatSync, realpathSync } from 'node:fs';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

export const RAW_CLI_PATH = '/opt/native/codex.raw';
export const RAW_CLI_SHA256 = '3e2584f3f3829a43a0495011a1cecb2facbe64a2403e2b682351fd9c2983f970';
export const RAW_CLI_VERSION = '0.157.1';
export const SDK_HOME_PARENT = '/data/native-flujo/workspaces/default-workspace/db';
export const BWRAP_PATH = '/usr/bin/bwrap';
const privateKeys = ['APPDATA', 'LOCALAPPDATA', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME',
  'XDG_DATA_HOME', 'XDG_STATE_HOME', 'XDG_RUNTIME_DIR', 'TMPDIR', 'TMP', 'TEMP'];
const fixedPrivatePaths = {
  APPDATA: 'AppData/Roaming', LOCALAPPDATA: 'AppData/Local', XDG_CONFIG_HOME: '.config',
  XDG_CACHE_HOME: '.cache', XDG_DATA_HOME: '.local/share', XDG_STATE_HOME: '.local/state',
  XDG_RUNTIME_DIR: '.runtime', TMPDIR: 'tmp', TMP: 'tmp', TEMP: 'tmp',
};
const deny = () => { throw new Error('Native filesystem isolation admission denied.'); };

/** Reject broader homes, traversal, resume and inconsistent SDK environment before any bind. */
export function validateInvocation(args, env, io = { lstatSync, realpathSync }, uid = process.getuid?.()) {
  if (uid !== 1000 || !Array.isArray(args) || args[0] !== 'exec'
    || args.some(value => typeof value !== 'string' || value.length > 262144 || value.includes('\0'))
    || args.includes('resume') || args.includes('--dangerously-bypass-approvals-and-sandbox')) deny();
  const home = env.CODEX_HOME;
  if (typeof home !== 'string' || path.posix.dirname(home) !== SDK_HOME_PARENT
    || !/^codex-private-[A-Za-z0-9_-]{6,80}$/.test(path.posix.basename(home))
    || path.posix.normalize(home) !== home || env.HOME !== home || env.USERPROFILE !== home) deny();
  const cwd = path.posix.join(home, 'workspace');
  const positions = args.flatMap((value, index) => value === '--cd' ? [index] : []);
  if (positions.length !== 1 || args[positions[0] + 1] !== cwd) deny();
  for (const key of privateKeys) {
    if (env[key] !== path.posix.join(home, fixedPrivatePaths[key])) deny();
  }
  // Validate every real ancestor: a bind of a symlinked home could expose a broader tree.
  for (const location of [SDK_HOME_PARENT, home, cwd, ...new Set(privateKeys.map(key => env[key]))]) {
    const stat = io.lstatSync(location);
    if (!stat.isDirectory() || stat.isSymbolicLink() || io.realpathSync(location) !== location) deny();
    if (location !== SDK_HOME_PARENT && (stat.uid !== 1000 || (stat.mode & 0o077) !== 0)) deny();
  }
  for (const name of ['auth.json', 'model-catalog.json', 'config.toml']) {
    const location = path.posix.join(home, name), stat = io.lstatSync(location);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.uid !== 1000 || (stat.mode & 0o077) !== 0
      || io.realpathSync(location) !== location) deny();
  }
  return { home, cwd };
}

/** No host root/system tree is bound: only the current invocation and fixed public TLS/DNS. */
export function buildBubblewrapArgs(invocation, nativeArgs, env, available = location => {
  try { lstatSync(location); return true; } catch { return false; }
}) {
  const { home, cwd } = invocation;
  const result = ['--die-with-parent', '--new-session', '--unshare-user', '--unshare-pid',
    '--unshare-ipc', '--unshare-uts', '--cap-drop', 'ALL', '--clearenv',
    '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--dir', '/run', '--dir', '/home',
    '--dir', '/etc', '--dir', '/etc/ssl', '--dir', '/opt', '--dir', '/opt/native',
    '--ro-bind', RAW_CLI_PATH, RAW_CLI_PATH];
  for (const location of ['/etc/ssl/certs', '/etc/resolv.conf', '/etc/hosts',
    '/etc/nsswitch.conf', '/etc/gai.conf']) {
    if (available(location)) result.push('--ro-bind', location, location);
  }
  const ancestors = [];
  let location = path.posix.dirname(home);
  while (location !== '/') { ancestors.unshift(location); location = path.posix.dirname(location); }
  for (const parent of ancestors) result.push('--dir', parent);
  result.push('--bind', home, home, '--chdir', cwd);
  const environment = { PATH: '/usr/bin:/bin', HOME: home, USERPROFILE: home, CODEX_HOME: home,
    SSL_CERT_FILE: '/etc/ssl/certs/ca-certificates.crt', SSL_CERT_DIR: '/etc/ssl/certs',
    ...Object.fromEntries(privateKeys.map(key => [key, env[key]])) };
  for (const key of ['LANG', 'LC_ALL', 'TZ', 'TERM']) {
    if (typeof env[key] === 'string' && /^[A-Za-z0-9_./:+-]{1,128}$/.test(env[key])) environment[key] = env[key];
  }
  if (env.CODEX_INTERNAL_ORIGINATOR_OVERRIDE === 'codex_sdk_ts') {
    environment.CODEX_INTERNAL_ORIGINATOR_OVERRIDE = 'codex_sdk_ts';
  }
  for (const [key, value] of Object.entries(environment)) result.push('--setenv', key, value);
  // Provider transport remains available; no network namespace is created.
  result.push('--', RAW_CLI_PATH, ...nativeArgs);
  return result;
}

async function verifyRawBinary() {
  const before = lstatSync(RAW_CLI_PATH);
  if (!before.isFile() || before.isSymbolicLink() || before.uid !== 0
    || (before.mode & 0o022) !== 0 || (before.mode & 0o6000) !== 0
    || realpathSync(RAW_CLI_PATH) !== RAW_CLI_PATH) deny();
  const digest = createHash('sha256');
  for await (const bytes of createReadStream(RAW_CLI_PATH)) digest.update(bytes);
  const after = lstatSync(RAW_CLI_PATH);
  if (digest.digest('hex') !== RAW_CLI_SHA256 || before.ino !== after.ino
    || before.size !== after.size || before.mtimeMs !== after.mtimeMs) deny();
}

export async function main(args = process.argv.slice(2)) {
  if (process.platform !== 'linux') deny();
  await verifyRawBinary();
  if (args.length === 1 && args[0] === '--version') {
    const result = spawnSync(RAW_CLI_PATH, ['--version'], { encoding: 'utf8',
      env: { PATH: '/usr/bin:/bin' }, timeout: 10000, maxBuffer: 4096 });
    if (result.status !== 0 || result.stdout.trim() !== 'codex-cli ' + RAW_CLI_VERSION) deny();
    process.stdout.write(result.stdout);
    return;
  }
  const invocation = validateInvocation(args, process.env);
  const child = spawn(BWRAP_PATH, buildBubblewrapArgs(invocation, args, process.env),
    { stdio: 'inherit', env: { PATH: '/usr/bin:/bin' } });
  for (const signal of ['SIGTERM', 'SIGINT', 'SIGHUP']) process.on(signal, () => child.kill(signal));
  await new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('exit', (code, signal) => {
      // Namespace denial/startup failure is terminal. There is no unsandboxed fallback.
      process.exitCode = code ?? (signal ? 128 : 1); resolve();
    });
  });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(() => { process.stderr.write('Native filesystem isolation unavailable.\n'); process.exitCode = 1; });
}
