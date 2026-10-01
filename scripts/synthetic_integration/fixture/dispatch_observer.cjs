'use strict';
// Assembly-only instrumentation of the real child stdin transport boundary.
// Does not replace SDK messages, command/args/cwd, authority, results or clocks.
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const net = require('node:net');
const { syncBuiltinESMExports } = require('node:module');
const env = process.env;
const release = JSON.parse(fs.readFileSync('/run/review/release.json', 'utf8'));
if (env.GITHUB_ACTIONS !== 'true' || env.RUNNER_ENVIRONMENT !== 'github-hosted'
  || env.RUNNER_OS !== 'Linux' || env.GITHUB_REPOSITORY !== 'mario-andreschak/factored-hackathon-2026-mcg'
  || release.root_review !== 'approved' || release.reviewed_head !== env.GITHUB_SHA
  || release.derived_source_verified !== true || release.artifact_content_verified !== true
  || !/^PREPARATION_ONLY = False$/m.test(fs.readFileSync('/opt/integration/harness/contract.py', 'utf8'))) {
  throw new Error('Synthetic dispatch observation is held.');
}
const root = fs.realpathSync(env.SYNTHETIC_OBSERVER_ROOT);
const file = path.join(root, 'transport-events.jsonl');
if (!root.startsWith('/run/synthetic-integration/state/') || fs.lstatSync(root).isSymbolicLink()
  || !/^[a-f0-9]{32}$/.test(env.SYNTHETIC_OBSERVER_GENERATION || '')) throw new Error('Observer scope rejected.');
const names = new Set(['banking_status', 'list_my_transactions', 'get_my_transaction',
  'prepare_unrecognized_charge', 'confirm_simulated_intake', 'read_intake_receipt',
  'create_verified_handoff', 'read_verified_handoff']);
let sequence = 0;
const append = fs.appendFileSync.bind(fs);
function record(event, extra = {}) {
  append(file, JSON.stringify({ generation: env.SYNTHETIC_OBSERVER_GENERATION, pid: process.pid,
    sequence: ++sequence, event, ...extra }) + '\n', { mode: 0o600, flag: 'a' });
}
record('observer_ready');
const originalSpawn = cp.spawn;
cp.spawn = function(command, args, options) {
  const child = Reflect.apply(originalSpawn, this, arguments);
  if (command !== '/opt/banking-mcp/.venv/bin/python' || !Array.isArray(args)
    || args.join('\0') !== ['-m', 'banking_mcp', 'serve', '--config', env.SYNTHETIC_BANK_CONFIG,
      '--transport', 'stdio'].join('\0') || options?.cwd !== '/opt/banking-mcp') return child;
  if (!child.stdin) { record('observer_invalid'); throw new Error('Bank stdio missing.'); }
  record('bank_transport_attached');
  const originalWrite = child.stdin.write;
  let buffered = '';
  let sendSequence = 0;
  child.stdin.write = function(chunk, encoding, callback) {
    // SDK sends newline-delimited JSON. Observe bytes; pass the original buffer
    // and encoding once unchanged. The volatile buffer is never written to disk.
    const text = Buffer.isBuffer(chunk) ? chunk.toString('utf8') : String(chunk);
    buffered += text;
    if (Buffer.byteLength(buffered) > 1024 * 1024) { record('observer_invalid'); throw new Error('Bank frame limit.'); }
    const observed = [];
    while (buffered.includes('\n')) {
      const end = buffered.indexOf('\n'), line = buffered.slice(0, end);
      buffered = buffered.slice(end + 1);
      try {
        const message = JSON.parse(line);
        if (message.method === 'tools/call') {
          const name = message.params?.name;
          if (!names.has(name)) { record('forbidden_tool'); throw new Error('Unexpected bank tool.'); }
          const send = ++sendSequence;
          observed.push({ name, send });
          record('send_started', { name, send, child: child.pid });
        }
      } catch (error) { record('observer_invalid'); throw new Error('Bank frame rejected.'); }
    }
    const cb = typeof encoding === 'function' ? encoding : callback;
    const wrapped = function(error) {
      for (const call of observed) record(error ? 'send_failed' : 'send_completed', { ...call, child: child.pid });
      if (typeof cb === 'function') cb(error);
    };
    return originalWrite.call(this, chunk, typeof encoding === 'string' ? encoding : undefined, wrapped);
  };
  child.once('close', () => { if (buffered) record('observer_invalid'); });
  return child;
};
// Conservative egress ceiling: every attempted non-loopback TCP connection is
// counted and rejected. A zero proves this ceiling, not all conceivable APIs.
const originalConnect = net.Socket.prototype.connect;
const allowed = new Set((env.SYNTHETIC_LOOPBACK_PORTS || '').split(',').map(Number));
net.Socket.prototype.connect = function(...args) {
  const normalized = net._normalizeArgs(args)[0];
  if (normalized.path) { record('forbidden_network'); throw new Error('IPC egress rejected.'); }
  const host = normalized.host || 'localhost';
  if (!['127.0.0.1', 'localhost', '::1'].includes(host) || !allowed.has(Number(normalized.port))) {
    record('external_attempt'); throw new Error('Synthetic egress ceiling rejected connection.');
  }
  return Reflect.apply(originalConnect, this, args);
};
syncBuiltinESMExports();
