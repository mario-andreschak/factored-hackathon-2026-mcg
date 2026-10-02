// Provider-free unit/component fixtures only: no CLI, OS, credentials or runtime acceptance.
import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { nativeStartupPreflight } from './native-preflight.mjs';

function fixture() {
  const child = new EventEmitter(), signals = new EventEmitter(), timers = new Map(), kills = [], commands = [];
  child.pid = 222; child.stdout = new EventEmitter(); child.stderr = new EventEmitter();
  child.stdout.destroy = () => {}; child.stderr.destroy = () => {}; child.unref = () => {};
  child.kill = signal => { kills.push({ direct: true, signal }); };
  let timerId = 0, birth = '123', uid = 1000, gid = 1000, ppid = 111, groupPresent = true, leaderPresent = true, rawChild = false;
  function procStat(pid) { const values = Array(30).fill('0'); values[0] = 'S'; values[1] = String(pid === 223 ? leaderPresent ? 222 : 1 : ppid);
    values[2] = '222'; values[3] = '222'; values[19] = pid === 223 ? '456' : birth; return pid + ' (synthetic process) ' + values.join(' '); }
  const io = { platform: 'linux', uid: () => 0, pid: 111,
    spawn: (...args) => { commands.push(args); return child; },
    readFileSync: filename => {
      const pid = Number(filename.split('/')[2]);
      if (pid === 222 && !leaderPresent || pid === 223 && !rawChild) { const error = Error('absent'); error.code = 'ENOENT'; throw error; }
      return filename.endsWith('/stat') ? procStat(pid)
        : `Uid:\t${uid}\t${uid}\t${uid}\t${uid}\nGid:\t${gid}\t${gid}\t${gid}\t${gid}\nGroups:\t1000 10002\n`;
    },
    readdirSync: () => rawChild ? ['222', '223'] : ['222'],
    kill: (pid, signal) => {
      if (signal === 0) { if (!groupPresent) { const error = Error('absent'); error.code = 'ESRCH'; throw error; } return; }
      kills.push({ pid, signal });
    },
    on: (signal, task) => signals.on(signal, task), off: (signal, task) => signals.removeListener(signal, task),
    setTimeout: (task, ms) => { const id = ++timerId; timers.set(id, { task, ms }); return id; },
    clearTimeout: id => timers.delete(id),
  };
  return { child, signals, timers, kills, commands, io,
    spawned: () => child.emit('spawn'), close: (code = 0, signal = null, remainingGroup = false) => {
      groupPresent = remainingGroup; leaderPresent = false; child.emit('close', code, signal);
    },
    stdout: value => child.stdout.emit('data', Buffer.from(value)), stderr: value => child.stderr.emit('data', Buffer.from(value)),
    fire: ms => { const selected = [...timers].find(([, timer]) => timer.ms === ms); assert.ok(selected);
      timers.delete(selected[0]); selected[1].task(); },
    changeBirth: () => { birth = '999'; }, wrongIdentity: () => { uid = 10001; gid = 10001; },
    wrongParent: () => { ppid = 999; },
    rootIdentity: () => { uid = 0; gid = 0; }, workerIdentity: () => { uid = 1000; gid = 1000; },
    rawVersionChild: () => { rawChild = true; }, groupGone: () => { groupPresent = false; rawChild = false; },
  };
}

test('exact credential-free worker command joins before success and never retries', async () => {
  const f = fixture(), result = nativeStartupPreflight({}, f.io);
  assert.deepEqual(f.commands, [['/usr/sbin/gosu', ['node', '/opt/native/codex-wrapper.mjs', '--version'], {
    cwd: '/', env: { PATH: '/usr/local/bin:/usr/bin:/bin', HOME: '/nonexistent', NODE_ENV: 'production' },
    detached: true, stdio: ['ignore', 'pipe', 'pipe'] }]]);
  f.spawned(); f.stdout('codex-cli 0.157.1\n');
  f.child.emit('exit', 0, null);
  let done = false; result.then(() => { done = true; }); await Promise.resolve(); assert.equal(done, false);
  f.close(); assert.deepEqual(await result, { version: '0.157.1', uid: 1000, gid: 1000,
    credentialInputSupplied: false, providerExecuted: false, childCompletionConfirmed: true });
  assert.equal(f.commands.length, 1); assert.equal(f.timers.size, 0); assert.equal(f.signals.listenerCount('SIGTERM'), 0);
});
test('wrong version, exit failure and stderr refuse without disclosing their bytes', async () => {
  for (const variant of ['version', 'exit', 'stderr']) {
    const f = fixture(), result = nativeStartupPreflight({}, f.io);
    f.spawned(); f.stdout(variant === 'version' ? 'synthetic-private-body' : 'codex-cli 0.157.1\n');
    if (variant === 'stderr') f.stderr('synthetic-private-credential');
    f.close(variant === 'exit' ? 7 : 0);
    await assert.rejects(result, error => error.code === 'native_preflight_version_refused'
      && error.message === 'Native startup verification failed.' && !error.message.includes('synthetic'));
    assert.equal(f.commands.length, 1);
  }
});
test('60-second deadline signals only the proven group and waits for joined completion', async () => {
  const f = fixture(), result = nativeStartupPreflight({}, f.io); f.spawned();
  f.fire(60000); assert.deepEqual(f.kills, [{ pid: -222, signal: 'SIGTERM' }]);
  f.fire(1000); assert.deepEqual(f.kills.at(-1), { pid: -222, signal: 'SIGKILL' });
  f.close(null, 'SIGKILL'); await assert.rejects(result, error => error.code === 'native_preflight_timeout');
  assert.equal(f.commands.length, 1); assert.equal(f.timers.size, 0);
});
test('gosu must settle to worker UID/GID before successful verification', async () => {
  const f = fixture(), result = nativeStartupPreflight({}, f.io);
  f.rootIdentity(); f.spawned(); f.workerIdentity(); f.fire(20);
  f.stdout('codex-cli 0.157.1\n'); f.close(); assert.equal((await result).uid, 1000);
});
test('TERM leader close retains KILL escalation for its captured same-session raw child', async () => {
  const f = fixture(), result = nativeStartupPreflight({}, f.io); f.spawned(); f.rawVersionChild();
  f.fire(60000); f.close(null, 'SIGTERM', true);
  let joined = false; result.catch(() => { joined = true; }); await Promise.resolve(); assert.equal(joined, false);
  f.fire(1000); assert.deepEqual(f.kills, [{ pid: -222, signal: 'SIGTERM' }, { pid: -222, signal: 'SIGKILL' }]);
  f.groupGone(); f.fire(20); await assert.rejects(result, error => error.code === 'native_preflight_timeout');
  assert.equal(f.timers.size, 0);
});
test('nonzero leader close with an untracked surviving group is bounded and never retried', async () => {
  const f = fixture(), result = nativeStartupPreflight({}, f.io); f.spawned(); f.rawVersionChild();
  f.close(7, null, true); f.fire(1000); f.fire(6000);
  await assert.rejects(result, error => error.code === 'native_preflight_shutdown_unconfirmed');
  assert.equal(f.commands.length, 1); assert.equal(f.timers.size, 0);
  assert.deepEqual(f.kills, [], 'an untracked group after leader exit must not be signalled');
});
test('root startup signals and AbortSignal cancellation stop the owned preflight', async () => {
  for (const chosen of ['SIGTERM', 'SIGINT', 'abort']) {
    const f = fixture(), controller = new AbortController();
    const result = nativeStartupPreflight({ signal: controller.signal }, f.io); f.spawned();
    if (chosen === 'abort') controller.abort(); else f.signals.emit(chosen);
    f.close(null, 'SIGTERM');
    await assert.rejects(result, error => error.code === 'native_preflight_cancelled'
      && error.exitCode === (chosen === 'SIGTERM' ? 143 : chosen === 'SIGINT' ? 130 : 1));
    assert.deepEqual(f.kills, [{ pid: -222, signal: 'SIGTERM' }]); assert.equal(f.timers.size, 0);
  }
  const f = fixture(), controller = new AbortController(); controller.abort();
  await assert.rejects(nativeStartupPreflight({ signal: controller.signal }, f.io)); assert.equal(f.commands.length, 0);
});
test('PID reuse, foreign identity and unconfirmed shutdown cannot become success', async () => {
  const reused = fixture(), result = nativeStartupPreflight({}, reused.io); reused.spawned(); reused.changeBirth();
  reused.fire(60000); reused.fire(1000); assert.deepEqual(reused.kills, []); reused.fire(6000);
  await assert.rejects(result, error => error.code === 'native_preflight_shutdown_unconfirmed');
  for (const change of ['wrongIdentity', 'wrongParent']) {
    const f = fixture(), refused = nativeStartupPreflight({}, f.io); f[change](); f.spawned(); f.close(0);
    await assert.rejects(refused, error => error.code === 'native_preflight_identity_refused');
    assert.ok(f.kills.every(item => item.direct), 'no unproven process group may be signalled');
  }
  const remaining = fixture(), pending = nativeStartupPreflight({}, remaining.io);
  remaining.spawned(); remaining.stdout('codex-cli 0.157.1\n'); remaining.close(0, null, true);
  remaining.fire(6000);
  await assert.rejects(pending, error => error.code === 'native_preflight_shutdown_unconfirmed');
  assert.deepEqual(remaining.kills, [], 'never signal a group after its owned leader has exited');
});
test('launch errors, output limits, wrong host identity and arbitrary options refuse', async () => {
  const failed = fixture(); failed.io.spawn = () => { throw Error('synthetic secret'); };
  await assert.rejects(nativeStartupPreflight({}, failed.io), error => error.code === 'native_preflight_launch_failed');
  for (const side of ['stdout', 'stderr']) {
    const f = fixture(), result = nativeStartupPreflight({}, f.io); f.spawned(); f[side]('x'.repeat(4097)); f.close(0);
    await assert.rejects(result, error => error.code === 'native_preflight_output_refused');
  }
  for (const options of [{ command: '/bin/sh' }, { wrapper: '/tmp/foreign' }, { timeout: 999999 }, { signal: {} }]) {
    const f = fixture(); await assert.rejects(nativeStartupPreflight(options, f.io)); assert.equal(f.commands.length, 0);
  }
  for (const mutate of [io => { io.platform = 'win32'; }, io => { io.uid = () => 1000; }]) {
    const f = fixture(); mutate(f.io); await assert.rejects(nativeStartupPreflight({}, f.io)); assert.equal(f.commands.length, 0);
  }
});
