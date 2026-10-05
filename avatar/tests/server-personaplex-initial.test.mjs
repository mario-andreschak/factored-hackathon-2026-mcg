import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { INITIAL_ROLE_HASHES, createPersonaplexInitialCoordinator, validateInitialAudio, validatePersonaplexInitialLease } from '../server/personaplex-initial.mjs';
import { MODEL_REVISION, PERSONAPLEX_PROTOCOL, SOURCE_REVISION, validatePersonaplexLease } from '../server/personaplex.mjs';

const START = Date.parse('2026-10-01T12:00:00Z');
const EPOCH = 'fixtureEpoch_123456789012345678901234567890';
const config = { voiceProvider: 'personaplex', backgroundAsr: 'openrouter', personaplexLeaseFile: 'operator-only-fixture', openrouterKey: 'mock-only-asr-key' };
function wav(seconds = .1, rate = 24000) {
  const bytes = Math.round(seconds * rate) * 2, b = Buffer.alloc(44 + bytes);
  b.write('RIFF'); b.writeUInt32LE(36 + bytes, 4); b.write('WAVEfmt ', 8); b.writeUInt32LE(16, 16);
  b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22); b.writeUInt32LE(rate, 24); b.writeUInt32LE(rate * 2, 28);
  b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34); b.write('data', 36); b.writeUInt32LE(bytes, 40);
  return { audio: b.toString('base64'), format: 'wav', language: 'en' };
}
function warm(time = START, remaining = 400_000) {
  return { version: 2, ready: false, protocol: PERSONAPLEX_PROTOCOL, epoch: EPOCH, avatar: null,
    selection: 'initial', phase: 'warm', voice: 'NATM1.pt', promptHash: null, selectionId: null,
    baseUrl: 'https://fixture.modal.host', connectToken: 'mock-only-connect-token-sentinel',
    sourceRevision: SOURCE_REVISION, modelRevision: MODEL_REVISION,
    createdAt: new Date(time - 100_000).toISOString(), expiresAt: new Date(time + remaining).toISOString(), updatedAt: new Date(time).toISOString() };
}
function health(lease) {
  return Object.fromEntries(['ready', 'protocol', 'avatar', 'sourceRevision', 'modelRevision', 'selection', 'phase', 'voice', 'promptHash', 'selectionId'].map(key => [key, lease[key]]));
}
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
function manualTimers() {
  const pending = new Map(); let next = 0;
  return { setTimeout(callback, ms) { const key = ++next; pending.set(key, { callback, ms }); return key; },
    clearTimeout(key) { pending.delete(key); },
    fire(ms) { const entry = [...pending].find(([, value]) => value.ms === ms); assert.ok(entry, `No pending ${ms}ms deadline`);
      pending.delete(entry[0]); entry[1].callback(); }, get size() { return pending.size; } };
}
function fixture(t, options = {}) {
  let time = START, lease = warm(), asrCalls = 0, primeCalls = 0, primeBody;
  const session = { id: 'authenticated-avatar-session', expires: START + 600_000 };
  const controller = new AbortController(); let active = session;
  const api = createPersonaplexInitialCoordinator({ config, enabled: true, now: () => time,
    readLeaseImpl: async () => ({ ...lease, updatedAt: new Date(time).toISOString() }),
    transcribeImpl: async (payload, signal) => { asrCalls++; assert.equal(payload.audio, wav().audio); assert.ok(signal instanceof AbortSignal); return { text: 'Please review my plan for tomorrow.' }; },
    primeImpl: async (checked, body, signal) => {
      primeCalls++; primeBody = body; assert.equal(checked.phase, 'warm'); assert.ok(signal instanceof AbortSignal);
      lease = { ...lease, ...body, promptHash: INITIAL_ROLE_HASHES[body.avatar], phase: 'primed', ready: true };
      return health(lease);
    }, waitImpl: async ms => { time += ms; }, ...options });
  t.after(() => api.close());
  return { api, session, controller, options: { signal: controller.signal, isSessionCurrent: candidate => candidate === active },
    get lease() { return lease; }, set lease(value) { lease = value; }, get time() { return time; }, set time(value) { time = value; },
    get asrCalls() { return asrCalls; }, get primeCalls() { return primeCalls; }, get primeBody() { return primeBody; },
    retire() { active = null; } };
}
const code = expected => error => error?.code === expected;

test('v2 validates actual warm and unavailable primed shapes without changing fixed v1', () => {
  const lease = warm(); assert.equal(validatePersonaplexInitialLease(lease, START).deadline, START + 400_000);
  const bound = { ...lease, avatar: 'orbit', phase: 'primed', ready: false, selectionId: 'opaqueSelection_123', promptHash: INITIAL_ROLE_HASHES.orbit };
  assert.equal(validatePersonaplexInitialLease(bound, START).ready, false);
  assert.throws(() => validatePersonaplexLease(lease, START));
  const fixed = { ...lease, version: 1, avatar: 'moss', ready: true };
  assert.equal(validatePersonaplexLease(fixed, START).version, 1);
  assert.throws(() => validatePersonaplexInitialLease(fixed, START));
});

test('v2 rejects stale, spoofed, conflicting, public-URL and excess metadata', () => {
  const lease = warm();
  for (const change of [{ updatedAt: new Date(START - 6001).toISOString() }, { modelRevision: 'unapproved' },
    { baseUrl: 'https://example.com' }, { baseUrl: 'https://fixture.modal.host/api/prime' }, { baseUrl: 'https://fixture.modal.host/?token=client' },
    { baseUrl: 'https://user:password@fixture.modal.host' }, { createdAt: new Date(START - 300_000).toISOString() },
    { ready: true }, { avatar: 'spark' }, { voice: 'other.pt' }, { systemPrompt: 'browser-selected' },
    { phase: 'primed', ready: true, avatar: 'moss', selectionId: 'selection', promptHash: INITIAL_ROLE_HASHES.spark }]) {
    assert.throws(() => validatePersonaplexInitialLease({ ...lease, ...change }, START));
  }
  assert.throws(() => validatePersonaplexInitialLease({ ...lease, baseUrl: 'http://127.0.0.1:8080' }, START));
  assert.equal(validatePersonaplexInitialLease({ ...lease, baseUrl: 'http://127.0.0.1:8080' }, START, true).baseUrl, 'http://127.0.0.1:8080');
});

test('initial audio validates canonical PCM and rejects client prompt/role and >12 seconds', () => {
  const source = wav(12); assert.equal(validateInitialAudio(source).duration, 12);
  assert.equal(validateInitialAudio(source).audioHash, createHash('sha256').update(Buffer.from(source.audio, 'base64')).digest('hex'));
  assert.throws(() => validateInitialAudio(wav(12.01)), code('invalid_initial_audio'));
  assert.throws(() => validateInitialAudio(wav(.1, 16000)), code('invalid_initial_audio'));
  const extra = Buffer.from(wav().audio, 'base64');
  const noncanonical = Buffer.concat([extra.subarray(0, 36), Buffer.from('JUNK\x00\x00\x00\x00', 'binary'), extra.subarray(36)]);
  noncanonical.writeUInt32LE(noncanonical.length - 8, 4);
  assert.throws(() => validateInitialAudio({ audio: noncanonical.toString('base64'), format: 'wav' }), code('invalid_initial_audio'));
  for (const extra of [{ avatar: 'spark' }, { transcript: 'client facts' }, { providerUrl: 'https://evil.test' }, { customerId: 'customer' }]) {
    assert.throws(() => validateInitialAudio({ ...wav(), ...extra }));
  }
});

test('default-disabled capability performs no lease/ASR/prime calls', async () => {
  const api = createPersonaplexInitialCoordinator({ config, readLeaseImpl: () => { throw Error('unexpected read'); } });
  assert.equal(await api.available(), false);
  await assert.rejects(api.select(wav(), {}, {}), code('initial_voice_unavailable'));
  api.close();
});

test('explicit initial opt-in still requires native provider and configured background recognizer', async () => {
  for (const changed of [{ voiceProvider: 'none' }, { backgroundAsr: '' }, { openrouterKey: '' }, { personaplexLeaseFile: '' }]) {
    const api = createPersonaplexInitialCoordinator({ enabled: true, config: { ...config, ...changed },
      readLeaseImpl: () => { throw Error('not admitted'); } });
    assert.equal(await api.available(), false); api.close();
  }
});

test('shutdown during initial private disk read cannot create a reservation or dispatch ASR afterwards', async t => {
  const pending = deferred(); const f = fixture(t, { readLeaseImpl: () => pending.promise });
  const selecting = f.api.select(wav(), f.session, f.options);
  await new Promise(resolve => setImmediate(resolve)); f.api.close(); pending.resolve(warm());
  await assert.rejects(selecting, code('initial_voice_unavailable')); assert.equal(f.asrCalls, 0);
});

test('capability leaves 12s capture budget; POST reservation boundary is exactly 195s', async t => {
  const f = fixture(t); f.lease = warm(START, 206_999); assert.equal(await f.api.available(), false);
  f.lease = warm(START, 207_000); assert.equal(await f.api.available(), true);
  f.lease = warm(START, 194_999);
  await assert.rejects(f.api.select(wav(), f.session, f.options), code('initial_voice_unavailable'));
  assert.equal(f.asrCalls, 0);
  f.lease = warm(START, 195_000);
  const selected = await f.api.select(wav(), f.session, f.options);
  assert.equal(selected.publicResult.avatar, 'orbit'); assert.equal(f.asrCalls, 1);
});

test('selection chooses shared deterministic mood once and binds private prime without audio or transcript', async t => {
  const f = fixture(t); const result = await f.api.select(wav(), f.session, f.options);
  assert.deepEqual(result.publicResult, { avatar: 'orbit', transcript: 'Please review my plan for tomorrow.', initialContextDelivered: false });
  assert.deepEqual(Object.keys(f.primeBody).sort(), ['avatar', 'selectionId']);
  assert.match(f.primeBody.selectionId, /^[A-Za-z0-9_-]{43}$/);
  assert.equal(f.primeCalls, 1); assert.equal(await f.api.available(), false);
  const grant = await f.api.claim(result.binding, f.session);
  assert.equal(grant.avatar, 'orbit'); assert.equal(grant.promptHash, INITIAL_ROLE_HASHES.orbit);
  assert.equal(grant.audioHash, validateInitialAudio(wav()).audioHash); assert.equal(grant.audioSeconds, .1);
  assert.equal(grant.sessionId, f.session.id); assert.equal(grant.isValid(), true);
  assert.equal(JSON.stringify(grant), '{}'); assert.deepEqual({ ...grant }, {});
  assert.equal(JSON.stringify(result).includes('connect-token'), false);
  await assert.rejects(f.api.claim(result.binding, f.session), code('initial_selection_cancelled'));
});

test('shared mood classifier calms distressed energetic speech and selects brisk ordinary urgency', async t => {
  const calm = fixture(t, { transcribeImpl: async () => ({ text: 'I am anxious and need a quick plan.' }) });
  assert.equal((await calm.api.select(wav(), calm.session, calm.options)).publicResult.avatar, 'moss');
  const brisk = fixture(t, { transcribeImpl: async () => ({ text: 'Let us go fast, I need this ASAP!' }) });
  assert.equal((await brisk.api.select(wav(), brisk.session, brisk.options)).publicResult.avatar, 'spark');
});

test('concurrent same-epoch callers admit exactly one ASR before any private prime', async t => {
  const pending = deferred(); let calls = 0;
  const f = fixture(t, { transcribeImpl: async () => { calls++; return pending.promise; } });
  const first = f.api.select(wav(), f.session, f.options);
  await new Promise(resolve => setImmediate(resolve));
  await assert.rejects(f.api.select(wav(), { id: 'second', expires: f.session.expires },
    { signal: new AbortController().signal, isSessionCurrent: () => true }), code('initial_voice_unavailable'));
  assert.equal(calls, 1); assert.equal(f.primeCalls, 0);
  pending.resolve({ text: 'Please review my plan.' }); await first;
});

test('aborted ASR which ignores cancellation cannot prime later and epoch remains spent', async t => {
  const pending = deferred(); const f = fixture(t, { transcribeImpl: () => pending.promise });
  const selecting = f.api.select(wav(), f.session, f.options);
  await new Promise(resolve => setImmediate(resolve)); f.controller.abort();
  await assert.rejects(selecting, code('initial_selection_cancelled'));
  pending.resolve({ text: 'Go fast' }); await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.primeCalls, 0);
  await assert.rejects(f.api.select(wav(), f.session, { ...f.options, signal: new AbortController().signal }), code('initial_voice_unavailable'));
});

test('45s ASR deadline aborts ignored work, consumes epoch and releases timers', async t => {
  const timers = manualTimers(), pending = deferred(); let signal;
  const f = fixture(t, { timers, transcribeImpl: async (_, child) => { signal = child; return pending.promise; } });
  const selecting = f.api.select(wav(), f.session, f.options);
  await new Promise(resolve => setImmediate(resolve)); timers.fire(45_000);
  await assert.rejects(selecting, code('initial_selection_timeout'));
  assert.equal(signal.aborted, true); assert.equal(timers.size, 0);
  pending.resolve({ text: 'Please review my plan.' }); await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.primeCalls, 0); assert.equal(await f.api.available(), false);
});

test('15s uncertain private-prime deadline is never retried and late receipt cannot grant', async t => {
  const timers = manualTimers(), pending = deferred(); let calls = 0, signal, receipt;
  const f = fixture(t, { timers, primeImpl: async (lease, body, child) => {
    calls++; signal = child; receipt = { ...health(lease), ...body, ready: true, phase: 'primed', promptHash: INITIAL_ROLE_HASHES.orbit };
    return pending.promise;
  } });
  const selecting = f.api.select(wav(), f.session, f.options);
  await new Promise(resolve => setImmediate(resolve)); timers.fire(15_000);
  await assert.rejects(selecting, code('initial_selection_timeout')); assert.equal(signal.aborted, true);
  pending.resolve(receipt); await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 1); assert.equal(timers.size, 0);
  await assert.rejects(f.api.select(wav(), f.session, f.options), code('initial_voice_unavailable'));
});

test('session map ownership lost during ASR fails closed before private prime', async t => {
  const pending = deferred(); const f = fixture(t, { transcribeImpl: () => pending.promise });
  const selecting = f.api.select(wav(), f.session, f.options);
  await new Promise(resolve => setImmediate(resolve)); f.retire(); pending.resolve({ text: 'Please plan tomorrow.' });
  await assert.rejects(selecting, code('initial_selection_cancelled')); assert.equal(f.primeCalls, 0);
});

test('session expiry and throwing ownership predicate cannot expose session/provider details', async t => {
  const f = fixture(t);
  await assert.rejects(f.api.select(wav(), f.session, { ...f.options, isSessionCurrent: () => { throw Error('private-session-sentinel'); } }),
    error => error.code === 'initial_selection_cancelled' && !error.message.includes('sentinel'));
  const pending = deferred(); const expired = fixture(t, { transcribeImpl: () => pending.promise });
  const selecting = expired.api.select(wav(), expired.session, expired.options);
  await new Promise(resolve => setImmediate(resolve)); expired.session.expires = START;
  pending.resolve({ text: 'Please review my plan.' });
  await assert.rejects(selecting, code('initial_selection_cancelled')); assert.equal(expired.primeCalls, 0);
});

test('operator epoch/token replacement during ASR cannot redirect private prime', async t => {
  const pending = deferred(); const f = fixture(t, { transcribeImpl: () => pending.promise });
  const selecting = f.api.select(wav(), f.session, f.options);
  await new Promise(resolve => setImmediate(resolve)); f.lease = { ...f.lease, connectToken: 'replacement-private-sentinel' };
  pending.resolve({ text: 'Please plan tomorrow.' });
  await assert.rejects(selecting, code('initial_selection_failed')); assert.equal(f.primeCalls, 0);
});

test('unknown private prime error consumes epoch and never retries despite late success', async t => {
  let calls = 0; const f = fixture(t, { primeImpl: async () => { calls++; throw Error('private-url-or-credential-must-not-escape'); } });
  await assert.rejects(f.api.select(wav(), f.session, f.options), error => error.code === 'initial_selection_failed' && !error.message.includes('credential'));
  await assert.rejects(f.api.select(wav(), f.session, f.options), code('initial_voice_unavailable'));
  assert.equal(calls, 1);
});

test('mismatching private prime identity/hash/pins never promotes a grant', async t => {
  for (const change of [{ promptHash: INITIAL_ROLE_HASHES.moss }, { avatar: 'spark' }, { selectionId: 'different' },
    { modelRevision: 'different' }, { ready: false }, { phase: 'streaming' }, { extra: 'private' }]) {
    const f = fixture(t, { primeImpl: async (lease, body) => ({ ...health(lease), ...body, phase: 'primed', ready: true,
      promptHash: INITIAL_ROLE_HASHES.orbit, ...change }) });
    await assert.rejects(f.api.select(wav(), f.session, f.options));
    assert.equal(await f.api.available(), false);
  }
});

test('promotion waits only for matching launcher lease without writing it or repeating prime', async t => {
  let time = START, reads = 0, selected, primeCalls = 0;
  const lease = warm();
  const f = fixture(t, { now: () => time, readLeaseImpl: async () => {
    reads++;
    return { ...lease, updatedAt: new Date(time).toISOString(), ...(selected && reads >= 5 ? selected : {}) };
  }, primeImpl: async (before, body) => { primeCalls++; selected = { ...body, ready: true, phase: 'primed', promptHash: INITIAL_ROLE_HASHES.orbit }; return { ...health(before), ...selected }; },
  waitImpl: async ms => { time += ms; } });
  const result = await f.api.select(wav(), f.session, f.options);
  assert.equal(result.publicResult.avatar, 'orbit'); assert.equal(primeCalls, 1); assert.equal(reads, 5);
});

test('no promotion by 3s is a consumed failure; no second prime or caller transfer', async t => {
  let time = START, calls = 0; const lease = warm();
  const f = fixture(t, { now: () => time, readLeaseImpl: async () => ({ ...lease, updatedAt: new Date(time).toISOString() }),
    primeImpl: async (before, body) => { calls++; return { ...health(before), ...body, ready: true, phase: 'primed', promptHash: INITIAL_ROLE_HASHES.orbit }; },
    waitImpl: async ms => { time += ms; } });
  await assert.rejects(f.api.select(wav(), f.session, f.options), code('initial_selection_timeout'));
  assert.equal(time - START, 3000); assert.equal(calls, 1);
  await assert.rejects(f.api.select(wav(), f.session, f.options), code('initial_voice_unavailable'));
});

test('claim requires 12s replay + bounded READY margin + 120s native lifetime', async t => {
  const f = fixture(t); const result = await f.api.select(wav(), f.session, f.options);
  f.time = Date.parse(f.lease.expiresAt) - 139_999;
  await assert.rejects(f.api.claim(result.binding, f.session), code('initial_voice_unavailable'));
  assert.equal(await f.api.available(), false);
});

test('claim is consumed before asynchronous disk read so concurrent grant replays fail', async t => {
  const pending = deferred(); let pause = false; const f = fixture(t);
  // A second coordinator uses the same fake private lease, with an explicitly
  // delayed claim read, rather than a second actual provider/worker.
  let lease = warm();
  const g = fixture(t, { readLeaseImpl: async () => pause ? pending.promise : lease,
    primeImpl: async (before, body) => { lease = { ...lease, ...body, ready: true, phase: 'primed', promptHash: INITIAL_ROLE_HASHES.orbit }; return health(lease); } });
  const result = await g.api.select(wav(), g.session, g.options); pause = true;
  const first = g.api.claim(result.binding, g.session);
  await assert.rejects(g.api.claim(result.binding, g.session), code('initial_selection_cancelled'));
  pending.resolve(lease); const grant = await first; assert.equal(grant.isValid(), true); assert.equal(f.primeCalls, 0);
});

test('request cancellation after selection or claim invalidates grant, never releases epoch', async t => {
  const f = fixture(t); const result = await f.api.select(wav(), f.session, f.options);
  const grant = await f.api.claim(result.binding, f.session); f.controller.abort();
  assert.equal(grant.ownerSignal.aborted, true); assert.equal(grant.isValid(), false);
  assert.throws(() => f.api.acknowledgeDelivery(result.binding, f.session), code('initial_selection_cancelled'));
});

test('confirmed delivery detaches request abort but logout/session invalidation still ends owner', async t => {
  const f = fixture(t); const result = await f.api.select(wav(), f.session, f.options);
  const grant = await f.api.claim(result.binding, f.session); f.api.acknowledgeDelivery(result.binding, f.session);
  f.controller.abort(); assert.equal(grant.isValid(), true);
  f.api.invalidateSession(f.session); assert.equal(grant.ownerSignal.aborted, true); assert.equal(grant.isValid(), false);
  assert.equal(await f.api.available(), false);
});

test('different session cannot claim a binding even with identical cookie string', async t => {
  const f = fixture(t); const result = await f.api.select(wav(), f.session, f.options);
  await assert.rejects(f.api.claim(result.binding, { ...f.session }), code('initial_selection_cancelled'));
  await assert.rejects(f.api.claim(result.binding, f.session), code('initial_selection_cancelled'));
});

test('forged serialized binding and session identity replacement never authorize a selected worker', async t => {
  const f = fixture(t); const result = await f.api.select(wav(), f.session, f.options);
  await assert.rejects(f.api.claim(JSON.parse(JSON.stringify(result.binding)), f.session), code('initial_selection_cancelled'));
  const grant = await f.api.claim(result.binding, f.session); f.retire();
  assert.equal(grant.isValid(), false); assert.equal(grant.ownerSignal.aborted, true);
});

test('default private HTTP prime uses fixed lease endpoint/Bearer, capped receipt and manual redirects', async t => {
  let lease = warm(); let calls = 0;
  const server = createServer(async (req, res) => {
    calls++; assert.equal(req.url, '/api/prime'); assert.equal(req.method, 'POST');
    assert.equal(req.headers.authorization, `Bearer ${lease.connectToken}`);
    let text = ''; for await (const part of req) text += part;
    const body = JSON.parse(text); assert.deepEqual(Object.keys(body).sort(), ['avatar', 'selectionId']);
    lease = { ...lease, ...body, phase: 'primed', ready: true, promptHash: INITIAL_ROLE_HASHES.orbit };
    res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(health(lease)));
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => new Promise(resolve => server.close(resolve)));
  lease.baseUrl = `http://127.0.0.1:${server.address().port}`;
  const f = fixture(t, { allowLocalWorker: true, readLeaseImpl: async () => lease, primeImpl: undefined });
  const result = await f.api.select(wav(), f.session, f.options);
  assert.equal(result.publicResult.avatar, 'orbit'); assert.equal(calls, 1);
});
