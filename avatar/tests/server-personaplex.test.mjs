import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, writeFile, chmod, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import WebSocket, { WebSocketServer } from 'ws';
import { createAvatarServer } from '../server/app.mjs';
import { readConfig } from '../server/config.mjs';
import { PERSONAPLEX_PROTOCOL, SOURCE_REVISION, MODEL_REVISION, MINIMUM_PERSONAPLEX_LEASE_MS,
  validatePersonaplexLease, readPersonaplexLease } from '../server/personaplex.mjs';

const secret = 'private-modal-connect-sentinel';
const epoch = 'test-worker-epoch-' + 'x'.repeat(32);
const ready = { type: 'ready', protocol: PERSONAPLEX_PROTOCOL, sampleRate: 24000, frameSamples: 1920, format: 'pcm16le' };
const tick = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const deadline = async predicate => { const end = Date.now() + 2000; while (!predicate()) { if (Date.now() > end) throw new Error('Timed out waiting for the bounded fixture.'); await tick(5); } };

function lease(time = Date.now()) {
  return { version: 1, ready: true, protocol: PERSONAPLEX_PROTOCOL, epoch, avatar: 'moss',
    baseUrl: 'https://private-connect.modal.host', connectToken: secret, sourceRevision: SOURCE_REVISION, modelRevision: MODEL_REVISION,
    createdAt: new Date(time - 1000).toISOString(), expiresAt: new Date(time + 180_000).toISOString(), updatedAt: new Date(time).toISOString() };
}

function output(generation = 0, sample = 0n, samples = 1920) {
  const packet = Buffer.alloc(13 + samples * 2);
  packet[0] = 0x11; packet.writeUInt32LE(generation, 1); packet.writeBigUInt64LE(sample, 5); return packet;
}

async function fixture(t, overrides = {}, options = {}) {
  const state = { reads: 0, connects: 0, bankCalls: 0, worker: null, lease: lease(options.fixedNow ?? Date.now()), input: [], headers: null, clockOffset: 0 };
  if (options.remainingMs !== undefined) state.lease.expiresAt = new Date((options.fixedNow ?? Date.now()) + options.remainingMs).toISOString();
  const upstream = createServer();
  const wss = new WebSocketServer({ server: upstream, perMessageDeflate: false });
  wss.on('connection', (socket, request) => {
    state.connects++; state.worker = socket; state.headers = request.headers;
    assert.equal(request.url, '/api/chat');
    if (options.autoReady !== false) socket.send(JSON.stringify(ready));
    socket.on('message', (data, binary) => state.input.push({ data, binary }));
  });
  await new Promise(resolve => upstream.listen(0, '127.0.0.1', resolve));
  state.lease.baseUrl = `http://127.0.0.1:${upstream.address().port}`;
  const config = { ...readConfig({ NODE_ENV: 'test', AVATAR_VOICE_PROVIDER: 'personaplex', AVATAR_PERSONAPLEX_LEASE_FILE: 'ignored-fixture.json' }),
    realtimeRateLimit: 100, ...overrides };
  const server = createAvatarServer({ config, now: () => (options.fixedNow ?? Date.now()) + state.clockOffset, fetchImpl: options.fetchImpl || (async () => { state.bankCalls++; throw new Error('No bank call authorized by this fixture.'); }),
    personaplexOptions: { allowLocalWorker: true, readLeaseImpl: async () => { state.reads++; return state.lease; } } });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const gate = config.publicAccess ? { 'X-Avatar-Gateway-Token': config.accessGateToken } : {};
  const response = await fetch(base + '/api/avatar/config', { headers: gate });
  const cookie = response.headers.getSetCookie()[0]?.split(';')[0];
  const request = (body = { avatar: 'moss' }, options = {}) => fetch(base + '/api/avatar/personaplex-session' + (options.query || ''), {
    method: 'POST', headers: { Origin: base, Cookie: cookie, 'Content-Type': 'application/json', ...gate, ...options.headers },
    body: JSON.stringify(body),
  });
  const connect = (ticket, options = {}) => {
    const socket = new WebSocket(base.replace('http:', 'ws:') + '/api/avatar/personaplex?ticket=' + ticket,
      { headers: { Origin: base, Cookie: cookie, ...gate, ...options.headers }, perMessageDeflate: false });
    const messages = []; let rejection;
    socket.on('message', (data, binary) => messages.push(binary ? data : JSON.parse(data.toString())));
    socket.on('error', () => {});
    const opened = new Promise(resolve => {
      socket.once('open', () => resolve(true));
      socket.once('unexpected-response', (_req, rejected) => {
        const chunks = [];
        rejected.on('data', chunk => chunks.push(chunk));
        rejected.on('end', () => { rejection = { status: rejected.statusCode, body: Buffer.concat(chunks).toString() }; socket.terminate(); resolve(false); });
      });
    });
    return { socket, messages, opened, get rejection() { return rejection; } };
  };
  t.after(async () => {
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
    for (const socket of wss.clients) socket.terminate(); await new Promise(resolve => wss.close(resolve));
    await new Promise(resolve => upstream.close(resolve));
  });
  return { state, request, connect, config: await response.json(), base, cookie, gate, server, serverConfig: config };
}

function recognition(f, body = { audio: pcmWav(), format: 'wav' }, options = {}) {
  return fetch(f.base + '/api/avatar/transcribe' + (options.query || ''), {
    method: 'POST', ...options, headers: { Origin: f.base, Cookie: f.cookie, 'Content-Type': 'application/json', ...f.gate, ...options.headers },
    body: JSON.stringify(body),
  });
}

function pcmWav() {
  const value = Buffer.alloc(44 + 3200);
  value.write('RIFF'); value.writeUInt32LE(value.length - 8, 4); value.write('WAVEfmt ', 8);
  value.writeUInt32LE(16, 16); value.writeUInt16LE(1, 20); value.writeUInt16LE(1, 22);
  value.writeUInt32LE(16000, 24); value.writeUInt32LE(32000, 28);
  value.writeUInt16LE(2, 32); value.writeUInt16LE(16, 34); value.write('data', 36);
  value.writeUInt32LE(value.length - 44, 40);
  return value.toString('base64');
}

async function nativeStream(f) {
  const stream = f.connect((await (await f.request()).json()).ticket);
  await stream.opened; await deadline(() => stream.messages.length);
  return stream;
}

const observerConfig = { backgroundAsr: 'openrouter', openrouterKey: 'private-test-observer-key' };

test('expired and sub120s leases report unavailable and refuse tickets before any worker or provider call', async t => {
  assert.equal(MINIMUM_PERSONAPLEX_LEASE_MS, 120_000);
  let calls = 0;
  for (const remainingMs of [-1, 0, 1, 119_999]) {
    const f = await fixture(t, observerConfig, { fixedNow: Date.now(), remainingMs,
      fetchImpl: async () => { calls++; return Response.json({ text: 'Must not dispatch.' }); } });
    assert.equal(f.config.voiceAvailable, false);
    const response = await f.request(); assert.equal(response.status, 503);
    assert.equal((await response.json()).code, 'personaplex_unavailable');
    assert.equal((await recognition(f)).status, 409);
    assert.equal(f.state.connects, 0); assert.equal(f.state.bankCalls, 0);
  }
  assert.equal(calls, 0);
});

test('exact120s lease boundary permits one fresh ready native stream without extending expiry', async t => {
  const f = await fixture(t, {}, { fixedNow: Date.now(), remainingMs: 120_000 });
  const originalExpiry = f.state.lease.expiresAt;
  assert.equal(f.config.voiceAvailable, true);
  const response = await f.request(); assert.equal(response.status, 200);
  const ticket = await response.json();
  assert.ok(Date.parse(ticket.expiresAt) < Date.parse(originalExpiry));
  const stream = f.connect(ticket.ticket); assert.equal(await stream.opened, true);
  await deadline(() => stream.messages.length);
  assert.deepEqual(stream.messages[0], ready);
  assert.equal(f.state.connects, 1); assert.equal(f.state.lease.expiresAt, originalExpiry);
  assert.equal(f.state.bankCalls, 0);
});

test('stillvalid ticket cannot dial a worker once fresh handshake lease has fallen below120s', async t => {
  const f = await fixture(t, observerConfig, { fixedNow: Date.now(), remainingMs: 121_000 });
  const ticket = (await (await f.request()).json()).ticket;
  f.state.clockOffset = 1001;
  const stream = f.connect(ticket); assert.equal(await stream.opened, false);
  assert.equal(stream.rejection.status, 503);
  assert.equal(JSON.parse(stream.rejection.body).code, 'personaplex_unavailable');
  const replay = f.connect(ticket); assert.equal(await replay.opened, false); assert.equal(replay.rejection.status, 401);
  const config = await (await fetch(f.base + '/api/avatar/config')).json();
  assert.equal(config.voiceAvailable, false);
  assert.equal((await recognition(f)).status, 409);
  assert.equal(f.state.connects, 0); assert.equal(f.state.bankCalls, 0);
});

test('worker readiness delayed across120s boundary is never published as a fresh observer owner', async t => {
  let calls = 0;
  const f = await fixture(t, observerConfig, { fixedNow: Date.now(), remainingMs: 121_000, autoReady: false,
    fetchImpl: async () => { calls++; return Response.json({ text: 'Must remain withheld.' }); } });
  const stream = f.connect((await (await f.request()).json()).ticket);
  assert.equal(await stream.opened, true); await deadline(() => f.state.worker);
  f.state.clockOffset = 1001;
  f.state.worker.send(JSON.stringify(ready));
  await deadline(() => stream.socket.readyState === WebSocket.CLOSED && f.state.worker.readyState === WebSocket.CLOSED);
  assert.equal(stream.messages.some(value => value.type === 'ready'), false);
  assert.equal(stream.messages.find(value => value.type === 'error')?.code, 'voice_expired');
  assert.equal((await recognition(f)).status, 409);
  assert.equal(calls, 0); assert.equal(f.state.connects, 1); assert.equal(f.state.bankCalls, 0);
});

test('alreadyready stream and observer continue below120s then stop at original expiry without grace', async t => {
  let calls = 0;
  const f = await fixture(t, observerConfig, { fixedNow: Date.now(), remainingMs: 120_001,
    fetchImpl: async () => { calls++; return Response.json({ text: 'Existing owner remains valid.' }); } });
  const originalExpiry = f.state.lease.expiresAt, stream = await nativeStream(f);
  f.state.worker.send(output()); await deadline(() => stream.messages.some(Buffer.isBuffer));
  f.state.clockOffset = 2; //119999ms remain; this is already admitted, not a fresh stream.
  const input = Buffer.alloc(3841); input[0] = 0x10; stream.socket.send(input);
  await deadline(() => f.state.input.length);
  const reads = f.state.reads; await deadline(() => f.state.reads > reads); //Exercise actual heartbeat monitor.
  assert.equal(stream.socket.readyState, WebSocket.OPEN);
  const config = await (await fetch(f.base + '/api/avatar/config')).json();
  assert.equal(config.voiceAvailable, false); assert.equal(config.voiceAvatar, 'moss');
  f.state.worker.send(output(0, 1920n));
  await deadline(() => stream.messages.filter(Buffer.isBuffer).length === 2);
  assert.equal((await recognition(f)).status, 200); assert.equal(calls, 1);
  assert.equal(f.state.lease.expiresAt, originalExpiry);
  f.state.clockOffset = 120_001;
  assert.equal((await recognition(f)).status, 409); assert.equal(calls, 1);
  await deadline(() => stream.socket.readyState === WebSocket.CLOSED && f.state.worker.readyState === WebSocket.CLOSED);
  assert.equal(stream.messages.find(value => value.type === 'error')?.code, 'voice_expired');
  assert.equal(f.state.lease.expiresAt, originalExpiry); assert.equal(f.state.connects, 1); assert.equal(f.state.bankCalls, 0);
});

test('native recognition capability stays false unless PersonaPlex, opt-in and a server key are all configured', async t => {
  let calls = 0;
  for (const overrides of [{}, { backgroundAsr: 'openrouter' }, { openrouterKey: 'test-key' },
    { ...observerConfig, voiceProvider: 'none' }, { ...observerConfig, voiceProvider: 'gemini-live' }]) {
    const f = await fixture(t, overrides, { fetchImpl: async () => { calls++; return Response.json({ text: 'wrongly admitted' }); } });
    assert.equal(f.config.backgroundAsrAvailable, false);
    assert.equal((await recognition(f)).status, 503);
    assert.equal(f.state.connects, 0);
  }
  assert.equal(calls, 0);
});

test('native recognition requires a ready relay owned by this avatar session and forwards only bounded WAV', async t => {
  let calls = 0;
  const audio = pcmWav();
  const f = await fixture(t, observerConfig, { autoReady: false, fetchImpl: async (url, options) => {
    calls++;
    assert.equal(url, 'https://openrouter.ai/api/v1/audio/transcriptions');
    assert.equal(options.redirect, 'manual');
    assert.equal(options.headers.Authorization, 'Bearer ' + observerConfig.openrouterKey);
    assert.deepEqual(JSON.parse(options.body), { model: 'openai/whisper-large-v3', input_audio: { data: audio, format: 'wav' }, response_format: 'json', temperature: 0 });
    return Response.json({ text: '  I need a little perspective.  ', usage: 'private-metadata' });
  } });
  assert.equal(f.config.backgroundAsrAvailable, true);
  assert.ok(!JSON.stringify(f.config).includes(observerConfig.openrouterKey));
  assert.equal((await recognition(f)).status, 409);
  const ticket = (await (await f.request()).json()).ticket;
  assert.equal((await recognition(f)).status, 409); // A ticket is not native readiness.
  const stream = f.connect(ticket); await stream.opened; await deadline(() => f.state.worker);
  assert.equal((await recognition(f)).status, 409); // Neither is a connected but unready worker.
  f.state.worker.send(JSON.stringify(ready)); await deadline(() => stream.messages.length);
  const other = await fetch(f.base + '/api/avatar/config');
  const otherCookie = other.headers.getSetCookie()[0].split(';')[0];
  assert.equal((await other.json()).backgroundAsrAvailable, true);
  assert.equal((await recognition(f, undefined, { headers: { Cookie: otherCookie } })).status, 409);
  for (const body of [{ audio, format: 'wav', epoch }, { audio, format: 'wav', ticket },
    { audio, format: 'wav', customer_id: 'foreign' }, { audio: 'https://attacker.example/audio', format: 'wav' }]) {
    assert.equal((await recognition(f, body)).status, 400);
  }
  assert.equal(calls, 0);
  const response = await recognition(f, { audio, format: 'wav' });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { text: 'I need a little perspective.' });
  assert.equal(calls, 1); assert.equal(f.state.bankCalls, 0);
});

test('native background recognition never opens chained chat or speech', async t => {
  let calls = 0;
  const f = await fixture(t, observerConfig, { fetchImpl: async () => { calls++; return Response.json({}); } });
  await nativeStream(f);
  for (const [path, body] of [['conversation', { message: 'hello', avatar: 'moss' }], ['speech', { text: 'hello', avatar: 'moss' }]]) {
    const response = await fetch(f.base + '/api/avatar/' + path, { method: 'POST',
      headers: { Origin: f.base, Cookie: f.cookie, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    assert.equal(response.status, 503);
  }
  assert.equal(calls, 0); assert.equal(f.state.bankCalls, 0);
});

test('native recognition preserves origin, session, ingress gate and JSON boundaries before provider dispatch', async t => {
  let calls = 0;
  const f = await fixture(t, { ...observerConfig, publicAccess: true, accessGateToken: 'a'.repeat(40), publicOrigin: 'https://avatar.example.com' },
    { fetchImpl: async () => { calls++; return Response.json({ text: 'not admitted' }); } });
  await nativeStream(f);
  for (const [headers, status] of [[{ Origin: 'https://attacker.example' }, 403], [{ Cookie: '' }, 401],
    [{ 'X-Avatar-Gateway-Token': '' }, 401], [{ 'Content-Type': 'text/plain' }, 415]]) {
    assert.equal((await recognition(f, undefined, { headers })).status, status);
  }
  assert.equal((await recognition(f, undefined, { query: '?model=foreign' })).status, 400);
  assert.equal(calls, 0);
});

test('native recognition capacity and timeout guards leave PCM flowing and release the observer slot', async t => {
  let calls = 0, aborted = false;
  const f = await fixture(t, { ...observerConfig, maxVoiceOperations: 1, voiceTimeoutMs: 100 }, { fetchImpl: async (_url, { signal }) => {
    calls++;
    if (calls > 1) return Response.json({ text: 'Still here.' });
    return new Promise((_resolve, reject) => signal.addEventListener('abort', () => { aborted = true; reject(new Error('private-provider-detail')); }, { once: true }));
  } });
  const stream = await nativeStream(f);
  const pending = recognition(f); await deadline(() => calls === 1);
  assert.equal((await recognition(f)).status, 503);
  const input = Buffer.alloc(3841); input[0] = 0x10; stream.socket.send(input);
  await deadline(() => f.state.input.length);
  assert.deepEqual(f.state.input[0].data, input);
  const response = await pending; assert.equal(response.status, 504);
  assert.equal((await response.json()).code, 'voice_timeout'); assert.equal(aborted, true);
  assert.equal(stream.socket.readyState, WebSocket.OPEN);
  assert.equal((await recognition(f)).status, 200);
  assert.equal(calls, 2);
});

test('native teardown aborts recognition and withholds a provider result even if it ignores cancellation', async t => {
  let calls = 0, signal, finish;
  const f = await fixture(t, observerConfig, { fetchImpl: async (_url, options) => {
    calls++; signal = options.signal;
    return new Promise(resolve => { finish = resolve; });
  } });
  const stream = await nativeStream(f);
  const pending = recognition(f); await deadline(() => calls === 1);
  stream.socket.close(); await deadline(() => stream.socket.readyState === WebSocket.CLOSED && signal.aborted);
  finish(Response.json({ text: 'stale user utterance must not escape' }));
  const response = await pending; assert.equal(response.status, 409);
  const body = await response.json(); assert.equal(body.code, 'background_asr_session_ended');
  assert.ok(!JSON.stringify(body).includes('stale user'));
  assert.equal((await recognition(f)).status, 409); assert.equal(calls, 1);
});

test('native observer rejects an expired active lease before dispatch even before the monitor closes it', async t => {
  let calls = 0;
  const f = await fixture(t, observerConfig, { fetchImpl: async () => { calls++; return Response.json({ text: 'not admitted' }); } });
  await nativeStream(f);
  f.state.clockOffset = 180_001;
  assert.equal((await recognition(f)).status, 409);
  assert.equal(calls, 0);
});

test('native observer withholds a recognition result if its lease expires before the monitor catches up', async t => {
  let calls = 0, finish;
  const f = await fixture(t, observerConfig, { fetchImpl: async () => {
    calls++; return new Promise(resolve => { finish = resolve; });
  } });
  await nativeStream(f);
  const pending = recognition(f); await deadline(() => calls === 1);
  f.state.clockOffset = 180_001;
  finish(Response.json({ text: 'stale post-expiry utterance' }));
  const response = await pending; assert.equal(response.status, 409);
  const body = await response.json(); assert.equal(body.code, 'background_asr_session_ended');
  assert.ok(!JSON.stringify(body).includes('post-expiry'));
});

test('native observer retains the voice request rate bound before any additional paid dispatch', async t => {
  let calls = 0;
  const f = await fixture(t, { ...observerConfig, voiceOperationRateLimit: 1 }, { fetchImpl: async () => {
    calls++; return Response.json({ text: 'One request only.' });
  } });
  await nativeStream(f);
  assert.equal((await recognition(f)).status, 200);
  assert.equal((await recognition(f)).status, 429);
  assert.equal(calls, 1);
});

test('PersonaPlex is explicit, lease-gated and never exposes Modal credentials or starts providers', async t => {
  assert.equal(readConfig({ OPENROUTER_API_KEY: 'optional' }).voiceProvider, 'none');
  const disabled = await fixture(t, { voiceProvider: 'none' });
  assert.equal(disabled.config.voiceAvailable, false); assert.equal((await disabled.request()).status, 503);
  assert.equal(disabled.state.reads, 0); assert.equal(disabled.state.connects, 0); assert.equal(disabled.state.bankCalls, 0);
  const f = await fixture(t);
  assert.equal(f.config.voiceAvailable, true); assert.equal(f.config.voiceProvider, 'personaplex'); assert.equal(f.config.voiceAvatar, 'moss');
  assert.ok(!JSON.stringify(f.config).includes(secret)); assert.ok(!JSON.stringify(f.config).includes(f.state.lease.baseUrl));
  const response = await f.request(); assert.equal(response.status, 200);
  const body = await response.json();
  assert.match(body.ticket, /^[A-Za-z0-9_-]{43}$/); assert.equal(body.streamPath, '/api/avatar/personaplex');
  assert.equal(body.inputSampleRate, 24000); assert.equal(body.outputSampleRate, 24000);
  assert.ok(Date.parse(body.expiresAt) <= Date.now() + 15000);
  assert.ok(!JSON.stringify(body).includes(secret)); assert.ok(!JSON.stringify(body).includes('modal'));
  assert.equal(f.state.connects, 0); assert.equal(f.state.bankCalls, 0);
  f.state.lease.ready = false;
  assert.equal((await f.request()).status, 503); assert.equal(f.state.connects, 0);
});

test('lease pins, authenticated origin, bounded lifetime and heartbeat are mandatory', () => {
  const time = Date.now(), valid = lease(time);
  assert.equal(validatePersonaplexLease(valid, time).baseUrl, valid.baseUrl);
  for (const patch of [{ ready: false }, { epoch: '' }, { modelRevision: 'foreign' }, { sourceRevision: 'foreign' },
    { connectToken: 'bad\nsecret' }, { baseUrl: 'https://attacker.example' }, { baseUrl: 'http://127.0.0.1:9000' },
    { baseUrl: 'https://user:secret@private.modal.host' }, { baseUrl: 'https://private.modal.host/?signed=secret' },
    { updatedAt: new Date(time - 7000).toISOString() }, { expiresAt: new Date(time + 700000).toISOString() },
    { expiresAt: new Date(time - 1).toISOString() }]) assert.throws(() => validatePersonaplexLease({ ...valid, ...patch }, time));
});

test('local operator lease files are bounded and reject symlinks and permissive Unix modes', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'avatar-personaplex-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const path = join(directory, 'lease.json'); await writeFile(path, JSON.stringify(lease()), { mode: 0o600 });
  assert.equal((await readPersonaplexLease(path)).connectToken, secret);
  await writeFile(path, 'x'.repeat(17000)); await assert.rejects(readPersonaplexLease(path));
  if (process.platform !== 'win32') {
    await writeFile(path, JSON.stringify(lease())); await chmod(path, 0o644); await assert.rejects(readPersonaplexLease(path));
    await chmod(path, 0o600); const link = join(directory, 'link.json'); await symlink(path, link); await assert.rejects(readPersonaplexLease(link));
  }
});

test('admission rejects cross-origin, identity selectors, bad types and launch-avatar changes without upstream work', async t => {
  const f = await fixture(t);
  for (const body of [{}, { avatar: 'evil' }, { avatar: 'moss', customer_id: 'foreign' }, { avatar: 'moss', model: 'foreign' },
    { avatar: 'moss', baseUrl: 'https://attacker.example' }, { avatar: 'moss', prompt: 'different' }]) assert.equal((await f.request(body)).status, 400);
  assert.equal((await f.request({ avatar: 'spark' })).status, 503);
  assert.equal((await f.request(undefined, { query: '?model=foreign' })).status, 400);
  assert.equal((await f.request(undefined, { headers: { Origin: 'https://attacker.example' } })).status, 403);
  assert.equal((await f.request(undefined, { headers: { Cookie: '' } })).status, 401);
  assert.equal((await f.request(undefined, { headers: { 'Content-Type': 'text/plain' } })).status, 415);
  assert.equal((await f.request({ avatar: 'moss', pad: 'x'.repeat(1100) })).status, 413);
  assert.equal(f.state.connects, 0); assert.equal(f.state.bankCalls, 0);
});

test('WebSocket admission consumes one bound ticket and forwards only private auth to the fixed native worker', async t => {
  const f = await fixture(t);
  const ticket = (await (await f.request()).json()).ticket;
  const wrong = f.connect(ticket, { headers: { Cookie: '' } }); assert.equal(await wrong.opened, false); assert.equal(wrong.rejection.status, 401);
  const cross = f.connect(ticket, { headers: { Origin: 'https://attacker.example' } }); assert.equal(await cross.opened, false); assert.equal(cross.rejection.status, 403);
  assert.equal(f.state.connects, 0);
  const stream = f.connect(ticket); assert.equal(await stream.opened, true); await deadline(() => stream.messages.length);
  assert.deepEqual(stream.messages[0], ready);
  assert.equal(f.state.headers.authorization, 'Bearer ' + secret); assert.equal(f.state.headers.cookie, undefined);
  assert.equal(f.state.headers['x-avatar-gateway-token'], undefined);
  const replay = f.connect(ticket); assert.equal(await replay.opened, false); assert.equal(replay.rejection.status, 401);
  assert.equal(f.state.connects, 1); assert.equal((await f.request()).status, 503);
  stream.socket.close(); await deadline(() => f.state.worker.readyState === WebSocket.CLOSED);
});

test('native PCM clocks, caption generations and interruption ACKs discard stale output without bank calls', async t => {
  const f = await fixture(t);
  const stream = f.connect((await (await f.request()).json()).ticket); await stream.opened; await deadline(() => stream.messages.length);
  const input = Buffer.alloc(3841); input[0] = 0x10; stream.socket.send(input);
  await deadline(() => f.state.input.length); assert.deepEqual(f.state.input[0].data, input); assert.equal(f.state.input[0].binary, true);
  f.state.worker.send(output()); await deadline(() => stream.messages.some(Buffer.isBuffer));
  stream.socket.send(JSON.stringify({ type: 'interrupt', id: 'interrupt-1' }));
  await deadline(() => f.state.input.length === 2);
  f.state.worker.send(output(0, 1920n)); // Pending generation is deliberately dropped.
  f.state.worker.send(JSON.stringify({ type: 'interrupted', id: 'interrupt-1', generation: 1 }));
  f.state.worker.send(output(0, 3840n)); // Late old generation is deliberately dropped.
  f.state.worker.send(JSON.stringify({ type: 'transcript', id: 'old', role: 'assistant', text: 'stale', done: true, generation: 0 }));
  f.state.worker.send(output(1, 5760n));
  f.state.worker.send(JSON.stringify({ type: 'transcript', id: 'new', role: 'assistant', text: 'Hello.', done: true, generation: 1 }));
  await deadline(() => stream.messages.some(value => value.id === 'new'));
  assert.equal(stream.messages.filter(Buffer.isBuffer).length, 2);
  assert.equal(stream.messages.some(value => value.id === 'old'), false);
  assert.equal(stream.messages.some(value => value.id === 'interrupt-1'), true);
  assert.equal(f.state.bankCalls, 0);
});

test('malformed audio, fabricated user ASR and upstream diagnostic messages fail closed and clean both sockets', async t => {
  for (const [source, value, binary] of [['client', Buffer.from([0x10, 0]), true], ['worker', output(0, 1920n), true],
    ['worker', { type: 'transcript', id: 'fake', role: 'user', text: 'invented user speech', done: true, generation: 0 }, false],
    ['worker', { type: 'error', code: 'private', message: secret }, false],
    ['client', { type: 'backendResult', reply: 'foreign bank fact', customer_id: 'foreign' }, false]]) {
    const f = await fixture(t);
    const stream = f.connect((await (await f.request()).json()).ticket); await stream.opened; await deadline(() => stream.messages.length);
    (source === 'client' ? stream.socket : f.state.worker).send(binary ? value : JSON.stringify(value), { binary });
    await deadline(() => stream.socket.readyState === WebSocket.CLOSED && f.state.worker.readyState === WebSocket.CLOSED);
    assert.ok(!JSON.stringify(stream.messages).includes(secret)); assert.equal(f.state.bankCalls, 0);
  }
});

test('lease revocation and server shutdown terminate native streams with no new worker dial', async t => {
  const f = await fixture(t);
  const stream = f.connect((await (await f.request()).json()).ticket); await stream.opened; await deadline(() => stream.messages.length);
  f.state.lease.ready = false;
  await deadline(() => stream.socket.readyState === WebSocket.CLOSED);
  assert.equal(f.state.worker.readyState, WebSocket.CLOSED); assert.equal(f.state.connects, 1);
  assert.equal((await f.request()).status, 503);
  const f2 = await fixture(t);
  const s2 = f2.connect((await (await f2.request()).json()).ticket); await s2.opened; await deadline(() => s2.messages.length);
  await new Promise(resolve => f2.server.close(resolve));
  await deadline(() => s2.socket.readyState === WebSocket.CLOSED && f2.state.worker.readyState === WebSocket.CLOSED);
});

test('expired tickets fail before worker dial and release all admission reservations', async t => {
  const f = await fixture(t);
  const ticket = (await (await f.request()).json()).ticket;
  f.state.clockOffset = 16_000;
  const expired = f.connect(ticket); assert.equal(await expired.opened, false); assert.equal(expired.rejection.status, 401);
  assert.equal(f.state.connects, 0);
  f.state.clockOffset = 0;
  const next = f.connect((await (await f.request()).json()).ticket); assert.equal(await next.opened, true);
  await deadline(() => next.messages.length); assert.equal(f.state.connects, 1);
});

test('public native PCM requires the operator ingress gate on both ticket issuance and Upgrade', async t => {
  const f = await fixture(t, { publicAccess: true, accessGateToken: 'a'.repeat(40), publicOrigin: 'https://avatar.example.com' });
  assert.equal((await f.request(undefined, { headers: { 'X-Avatar-Gateway-Token': '' } })).status, 401);
  const stream = f.connect((await (await f.request()).json()).ticket, { headers: { 'X-Avatar-Gateway-Token': '' } });
  assert.equal(await stream.opened, false); assert.equal(stream.rejection.status, 401); assert.equal(f.state.connects, 0);
});

test('the actual Vite development proxy forwards authenticated HTTP and native WebSocket upgrades', async t => {
  const { createServer: createVite, loadConfigFromFile } = await import('vite');
  const f = await fixture(t);
  const root = fileURLToPath(new URL('../', import.meta.url));
  const loaded = await loadConfigFromFile({ command: 'serve', mode: 'test' }, fileURLToPath(new URL('../vite.config.ts', import.meta.url)));
  const proxy = loaded.config.server.proxy['/api/avatar'];
  // Preserve the repository's upgrade/Host settings; change only fixture targets.
  const vite = await createVite({ ...loaded.config, configFile: false, root, logLevel: 'silent', server: {
    ...loaded.config.server, host: '127.0.0.1', port: 0, strictPort: false,
    proxy: { '/api/avatar': typeof proxy === 'string' ? f.base : { ...proxy, target: f.base } },
  } });
  await vite.listen(); t.after(() => vite.close());
  const base = `http://127.0.0.1:${vite.httpServer.address().port}`;
  f.serverConfig.allowedOrigins.add(base);
  const configResponse = await fetch(base + '/api/avatar/config'); assert.equal(configResponse.status, 200);
  const cookie = configResponse.headers.getSetCookie()[0]?.split(';')[0];
  const admission = await fetch(base + '/api/avatar/personaplex-session', { method: 'POST',
    headers: { Origin: base, Cookie: cookie, 'Content-Type': 'application/json' }, body: '{"avatar":"moss"}' });
  assert.equal(admission.status, 200);
  const { ticket } = await admission.json();
  const socket = new WebSocket(base.replace('http:', 'ws:') + '/api/avatar/personaplex?ticket=' + ticket,
    { headers: { Origin: base, Cookie: cookie }, handshakeTimeout: 1500, perMessageDeflate: false });
  const messages = []; socket.on('error', () => {}); socket.on('message', (data, binary) => messages.push(binary ? data : JSON.parse(data)));
  t.after(() => socket.terminate());
  await deadline(() => messages.length); assert.deepEqual(messages[0], ready);
  f.state.worker.send(output()); await deadline(() => messages.some(Buffer.isBuffer));
  socket.close(); await deadline(() => f.state.worker.readyState === WebSocket.CLOSED);
  assert.equal(f.state.headers.authorization, 'Bearer ' + secret); assert.equal(f.state.bankCalls, 0);
});
