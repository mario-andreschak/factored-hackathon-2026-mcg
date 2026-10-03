/** Credential-free startup verification; normal request verification remains intact. */
import { spawn } from 'node:child_process';
import { readFileSync, readdirSync } from 'node:fs';
import process from 'node:process';

const TIMEOUT_MS = 60000, TERM_GRACE_MS = 1000, JOIN_MS = 5000, OUTPUT_LIMIT = 4096;
const WRAPPER = '/opt/native/codex-wrapper.mjs';
const VERSION = 'codex-cli 0.157.1';
const ENV = Object.freeze({ PATH: '/usr/local/bin:/usr/bin:/bin', HOME: '/nonexistent', NODE_ENV: 'production' });
const system = { platform: process.platform, uid: () => process.getuid?.(), pid: process.pid,
  spawn, readFileSync, readdirSync, kill: (pid, signal) => process.kill(pid, signal),
  on: (signal, task) => process.on(signal, task), off: (signal, task) => process.removeListener(signal, task),
  setTimeout, clearTimeout };

function refusal(code, exitCode = 1) {
  const error = new Error('Native startup verification failed.');
  error.code = code; error.exitCode = exitCode; return error;
}
function identity(pid, io) {
  const location = `/proc/${pid}`;
  const before = io.readFileSync(location + '/stat', 'utf8');
  const first = before.slice(before.lastIndexOf(')') + 2).trim().split(/\s+/);
  const status = io.readFileSync(location + '/status', 'utf8');
  const raw = io.readFileSync(location + '/stat', 'utf8');
  const last = raw.slice(raw.lastIndexOf(')') + 2).trim().split(/\s+/);
  const uids = status.match(/^Uid:\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)/m);
  const gids = status.match(/^Gid:\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)/m);
  if (first[19] !== last[19] || !/^\d+$/.test(last[19] ?? '')
    || !uids || !gids || !uids.slice(1).every(uid => uid === uids[1]) || !gids.slice(1).every(gid => gid === gids[1]))
    throw refusal('native_preflight_identity_refused');
  const uid = Number(uids[1]), gid = Number(gids[1]);
  if (!(uid === 1000 && gid === 1000 || uid === 0 && [0, 1000].includes(gid)))
    throw refusal('native_preflight_identity_refused');
  const groups = status.match(/^Groups:\s*([^\n]*)/m)?.[1].trim().split(/\s+/).filter(Boolean).map(Number);
  if (uid === 1000 && (!groups || groups.some(group => ![1000, 10002].includes(group))))
    throw refusal('native_preflight_identity_refused');
  return { pid, ppid: Number(last[1]), pgid: Number(last[2]), sid: Number(last[3]), birth: last[19], state: last[0], uid, gid };
}

// The second argument is an explicit synthetic OS fixture for unit tests only.
// Command, identity, version, environment and deadlines cannot be supplied as options.
export function nativeStartupPreflight(options = {}, io = system) {
  if (io.platform !== 'linux' || io.uid() !== 0 || !options || typeof options !== 'object'
    || Object.keys(options).some(key => key !== 'signal')
    || options.signal !== undefined && !(options.signal instanceof AbortSignal))
    return Promise.reject(refusal('native_preflight_setup_refused'));
  if (options.signal?.aborted) return Promise.reject(refusal('native_preflight_cancelled'));
  return new Promise((resolve, reject) => {
    let child, starting, owned, failure, stdout = '', stderrBytes = 0, joined = false, closed = false, stopping = false;
    let deadline, escalation, joinDeadline, identityTimer, groupTimer, attempts = 0;
    const members = new Map();
    const cleanup = () => {
      for (const timer of [deadline, escalation, joinDeadline, identityTimer, groupTimer]) io.clearTimeout(timer);
      io.off('SIGTERM', term); io.off('SIGINT', interrupt);
      options.signal?.removeEventListener('abort', abort);
    };
    const finish = error => {
      if (joined) return; joined = true; cleanup();
      if (error) reject(error);
      else resolve(Object.freeze({ version: '0.157.1', uid: 1000, gid: 1000,
        credentialInputSupplied: false, providerExecuted: false, childCompletionConfirmed: true }));
    };
    const anchoredMembers = () => {
      if (!owned) return false;
      let anchored = false;
      for (const [pid, birth] of members) try {
        const current = identity(pid, io);
        // A retained zombie still pins its PID/session birth. A reparented raw
        // child remains owned through its captured birth, not a bare group ID.
        if (current.birth === birth && current.pgid === owned.pid && current.sid === owned.pid
          && current.uid === 1000 && current.gid === 1000) anchored = true;
      } catch {}
      if (!anchored) return false;
      for (const name of io.readdirSync('/proc')) {
        if (!/^\d+$/.test(name) || Number(name) <= 1) continue;
        try {
          const stat = io.readFileSync(`/proc/${name}/stat`, 'utf8');
          const fields = stat.slice(stat.lastIndexOf(')') + 2).trim().split(/\s+/);
          if (Number(fields[2]) !== owned.pid || Number(fields[3]) !== owned.pid) continue;
          const current = identity(Number(name), io);
          if (current.uid !== 1000 || current.gid !== 1000) throw refusal('native_preflight_identity_refused');
          members.set(current.pid, current.birth);
        } catch (error) { if (error.code !== 'ENOENT' && error.code !== 'ESRCH') throw error; }
      }
      return true;
    };
    const signalOwned = signal => {
      if (!owned) { try { child?.kill('SIGKILL'); } catch {} return; }
      try {
        if (!anchoredMembers()) return;
        io.kill(-owned.pid, signal);
      } catch { /* Refuse an unverified group; bounded join below must fail. */ }
    };
    const stop = (code, exitCode = 1) => {
      if (stopping || joined) return;
      stopping = true; failure ??= refusal(code, exitCode); signalOwned('SIGTERM');
      escalation = io.setTimeout(() => signalOwned('SIGKILL'), TERM_GRACE_MS);
      joinDeadline = io.setTimeout(() => {
        child?.stdout?.destroy(); child?.stderr?.destroy(); child?.unref();
        finish(refusal('native_preflight_shutdown_unconfirmed', exitCode));
      }, TERM_GRACE_MS + JOIN_MS);
    };
    const term = () => stop('native_preflight_cancelled', 143);
    const interrupt = () => stop('native_preflight_cancelled', 130);
    const abort = () => stop('native_preflight_cancelled');
    const groupAbsent = () => {
      const pid = owned?.pid ?? starting?.pid;
      if (!pid) return false;
      try { io.kill(-pid, 0); return false; }
      catch (error) { return error.code === 'ESRCH'; }
    };
    const reconcile = () => {
      if (joined || !closed) return;
      if (!groupAbsent()) {
        stop(failure?.code ?? 'native_preflight_shutdown_unconfirmed', failure?.exitCode ?? 1);
        groupTimer = io.setTimeout(reconcile, 20); return;
      }
      if (failure) finish(failure);
      else if (!owned || stdout.trim() !== VERSION || stderrBytes !== 0) finish(refusal('native_preflight_version_refused'));
      else finish();
    };
    const capture = () => {
      if (failure || joined) return;
      try {
        if (!Number.isSafeInteger(child.pid) || child.pid <= 1 || child.pid === io.pid)
          throw refusal('native_preflight_identity_refused');
        const candidate = identity(child.pid, io);
        if (candidate.ppid !== io.pid || candidate.pgid !== child.pid || candidate.sid !== child.pid
          || starting && starting.birth !== candidate.birth) throw refusal('native_preflight_identity_refused');
        starting ??= candidate;
        if (candidate.uid === 0) {
          if (++attempts >= 100) throw refusal('native_preflight_identity_refused');
          identityTimer = io.setTimeout(capture, 20); return;
        }
        owned = candidate; members.set(owned.pid, owned.birth);
      } catch { stop('native_preflight_identity_refused'); }
    };
    io.on('SIGTERM', term); io.on('SIGINT', interrupt);
    options.signal?.addEventListener('abort', abort, { once: true });
    try {
      child = io.spawn('/usr/sbin/gosu', ['node', WRAPPER, '--version'], {
        cwd: '/', env: { ...ENV }, detached: true, stdio: ['ignore', 'pipe', 'pipe'] });
    } catch { finish(refusal('native_preflight_launch_failed')); return; }
    child.once('spawn', capture);
    child.stdout.on('data', bytes => {
      if (Buffer.byteLength(stdout) + bytes.length > OUTPUT_LIMIT) stop('native_preflight_output_refused');
      else stdout += bytes.toString('utf8');
    });
    child.stderr.on('data', bytes => {
      stderrBytes += bytes.length;
      if (stderrBytes > OUTPUT_LIMIT) stop('native_preflight_output_refused');
    });
    child.once('error', () => stop('native_preflight_launch_failed'));
    child.once('close', (code, signal) => {
      closed = true;
      if (!starting) { finish(failure ?? refusal('native_preflight_identity_refused')); return; }
      if (!failure && (code !== 0 || signal)) failure = refusal('native_preflight_version_refused');
      reconcile();
    });
    deadline = io.setTimeout(() => stop('native_preflight_timeout'), TIMEOUT_MS);
    if (options.signal?.aborted) abort();
  });
}
