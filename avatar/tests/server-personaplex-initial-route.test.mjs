import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import WebSocket, { WebSocketServer } from 'ws';
import { createAvatarServer } from '../server/app.mjs';
import { readConfig } from '../server/config.mjs';
import { INITIAL_ROLE_HASHES } from '../server/personaplex-initial.mjs';
import { MODEL_REVISION, PERSONAPLEX_PROTOCOL, SOURCE_REVISION } from '../server/personaplex.mjs';

const token = 'local-only-connect-token-sentinel', epoch = 'local-only-epoch-' + 'x'.repeat(32);
const ready = { type: 'ready', protocol: PERSONAPLEX_PROTOCOL, sampleRate: 24000, frameSamples: 1920, format: 'pcm16le' };
const tick = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate) { const end = Date.now() + 2500; while (!predicate()) { if (Date.now() > end) throw Error('Local initial fixture timed out.'); await tick(5); } }
function deferred() { let resolve; const promise = new Promise(yes => { resolve = yes; }); return { promise, resolve }; }
function wav(seconds = .1, rate = 24000) {
  const data = Buffer.alloc(44 + Math.round(seconds * rate) * 2);
  data.write('RIFF'); data.writeUInt32LE(data.length - 8, 4); data.write('WAVEfmt ', 8); data.writeUInt32LE(16, 16);
  data.writeUInt16LE(1, 20); data.writeUInt16LE(1, 22); data.writeUInt32LE(rate, 24); data.writeUInt32LE(rate * 2, 28);
  data.writeUInt16LE(2, 32); data.writeUInt16LE(16, 34); data.write('data', 36); data.writeUInt32LE(data.length - 44, 40);
  return { audio: data.toString('base64'), format: 'wav', language: 'en' };
}
function health(lease) {
  return Object.fromEntries(['ready', 'protocol', 'avatar', 'sourceRevision', 'modelRevision', 'selection', 'phase', 'voice', 'promptHash', 'selectionId'].map(key => [key, lease[key]]));
}
function output(generation = 0, sample = 0n) {
  const result = Buffer.alloc(13 + 3840); result[0] = 0x11; result.writeUInt32LE(generation, 1); result.writeBigUInt64LE(sample, 5); return result;
}

async function fixture(t, options = {}) {
  const started = Date.now();
  const state = { time: started, asr: 0, prime: 0, connects: 0, bank: 0, bodies: [], input: [], worker: null,
    lease: { version: 2, ready: false, protocol: PERSONAPLEX_PROTOCOL, epoch, avatar: null, selection: 'initial', phase: 'warm',
      voice: 'NATM1.pt', promptHash: null, selectionId: null, connectToken: token,
      sourceRevision: SOURCE_REVISION, modelRevision: MODEL_REVISION,
      createdAt: new Date(started - 60_000).toISOString(), expiresAt: new Date(started + (options.remaining ?? 400_000)).toISOString(),
      updatedAt: new Date(started).toISOString() } };
  const upstream = createServer(async (req, res) => {
    assert.equal(req.url, '/api/prime'); assert.equal(req.method, 'POST');
    assert.equal(req.headers.authorization, `Bearer ${token}`); assert.match(req.headers['content-type'], /^application\/json/);
    let raw = ''; for await (const bytes of req) raw += bytes;
    const body = JSON.parse(raw); state.bodies.push(body); state.prime++;
    assert.deepEqual(Object.keys(body).sort(), ['avatar', 'selectionId']);
    assert.match(body.selectionId, /^[A-Za-z0-9_-]{43}$/);
    if (options.primeWait) await options.primeWait;
    state.time += options.primeAdvance || 0;
    if (options.primeError) { res.writeHead(500); res.end('private-provider-url-and-key-must-not-escape'); return; }
    state.lease = { ...state.lease, ...body, phase: 'primed', ready: true, promptHash: INITIAL_ROLE_HASHES[body.avatar] };
    res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(health(state.lease)));
  });
  const wss = new WebSocketServer({ server: upstream, perMessageDeflate: false });
  wss.on('connection', (socket, req) => {
    assert.equal(req.url, '/api/chat'); assert.equal(req.headers.authorization, `Bearer ${token}`);
    state.connects++; state.worker = socket; state.lease.phase = 'streaming';
    if (options.autoReady !== false) socket.send(JSON.stringify(ready));
    socket.on('message', (data, binary) => state.input.push({ data, binary }));
  });
  upstream.listen(0, '127.0.0.1'); await once(upstream, 'listening');
  state.lease.baseUrl = `http://127.0.0.1:${upstream.address().port}`;
  const config = { ...readConfig({ NODE_ENV: 'test', AVATAR_VOICE_PROVIDER: 'personaplex', AVATAR_PERSONAPLEX_LEASE_FILE: 'local-fixture-only',
    AVATAR_BACKGROUND_ASR: 'openrouter', OPENROUTER_API_KEY: 'local-only-asr-sentinel', AVATAR_PERSONAPLEX_INITIAL_ROLE: 'initial' }),
    realtimeRateLimit: 100, voiceOperationRateLimit: 100, ...(options.config || {}) };
  const server = createAvatarServer({ config, now: () => state.time,
    fetchImpl: async (url, init) => {
      if (url === 'https://openrouter.ai/api/v1/audio/transcriptions') {
        state.asr++; state.asrSignal = init.signal; assert.equal(init.headers.Authorization, 'Bearer local-only-asr-sentinel');
        const body = JSON.parse(init.body); assert.equal(body.input_audio.format, 'wav');
        assert.equal(body.input_audio.data, (options.expectedAudio || wav()).audio); assert.equal(init.redirect, 'manual');
        if (options.asrWait) await options.asrWait;
        state.time += options.asrAdvance || 0;
        return Response.json({ text: options.text || 'I am anxious and worried. Please help me breathe.' });
      }
      if (url === state.lease.baseUrl + '/api/prime') return fetch(url, init);
      state.bank++; throw Error('No banking or other provider call is authorized by this fixture.');
    }, personaplexOptions: { allowLocalWorker: true,
      readLeaseImpl: async () => ({ ...state.lease, updatedAt: new Date(state.time).toISOString() }) } });
  if (options.holdResponse) server.prependListener('request', (req, res) => {
    if (req.url !== '/api/avatar/personaplex-initial' || state.responseHeld) return;
    const end = res.end;
    res.end = function (...args) {
      state.heldTicket = JSON.parse(args[0]).ticket;
      state.releaseResponse = () => end.apply(res, args);
      state.responseHeld = true;
      return res;
    };
    res.once('close', () => { state.deliveryClosed = true; });
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  const base = `http://127.0.0.1:${server.address().port}`;
  const gate = config.publicAccess ? { 'X-Avatar-Gateway-Token': config.accessGateToken } : {};
  async function browserSession() {
    const response = await fetch(base + '/api/avatar/config', { headers: gate });
    return { response, cookie: response.headers.getSetCookie()[0]?.split(';')[0], body: await response.json() };
  }
  const initial = await browserSession(), cookie = initial.cookie;
  const request = (body = wav(), supplied = {}) => fetch(base + '/api/avatar/personaplex-initial' + (supplied.query || ''), {
    method: 'POST', ...(supplied.signal ? { signal: supplied.signal } : {}),
    headers: { Origin: base, Cookie: cookie, 'Content-Type': 'application/json', ...gate, ...supplied.headers }, body: JSON.stringify(body),
  });
  const connect = (ticket, supplied = {}) => {
    const socket = new WebSocket(base.replace('http:', 'ws:') + '/api/avatar/personaplex?ticket=' + ticket,
      { headers: { Origin: base, Cookie: cookie, ...gate, ...supplied.headers }, perMessageDeflate: false });
    const messages = []; let rejection;
    socket.on('message', (data, binary) => messages.push(binary ? data : JSON.parse(data.toString())));
    socket.on('error', () => {});
    const opened = new Promise(resolve => { socket.once('open', () => resolve(true));
      socket.once('unexpected-response', (_req, response) => {
        let raw = ''; response.on('data', part => raw += part); response.on('end', () => {
          rejection = { status: response.statusCode, body: JSON.parse(raw) }; socket.terminate(); resolve(false);
        });
      }); });
    return { socket, messages, opened, get rejection() { return rejection; } };
  };
  t.after(async () => {
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
    for (const socket of wss.clients) socket.terminate(); await new Promise(resolve => wss.close(resolve));
    upstream.closeAllConnections(); await new Promise(resolve => upstream.close(resolve));
  });
  return { state, base, cookie, gate, config: initial.body, request, connect, browserSession, server, serverConfig: config };
}

test('warm v2 capability is distinct from ready voice; initial opt-in configuration is strict', async t => {
  assert.throws(() => readConfig({ AVATAR_PERSONAPLEX_INITIAL_ROLE: 'true' }));
  assert.throws(() => readConfig({ AVATAR_PERSONAPLEX_INITIAL_ROLE: 'initial', AVATAR_VOICE_PROVIDER: 'personaplex' }));
  const f = await fixture(t);
  assert.equal(f.config.initialVoiceAvailable, true); assert.equal(f.config.voiceAvailable, false); assert.equal(f.config.voiceAvatar, null);
  assert.equal(f.config.backendAvailable, false); assert.equal(f.config.backgroundAsrAvailable, true);
  assert.equal(f.state.asr, 0); assert.equal(f.state.prime, 0); assert.equal(f.state.connects, 0); assert.equal(f.state.bank, 0);
});

test('actual initial HTTP response contains public recognition/ticket only; one static prime and one native stream', async t => {
  const f = await fixture(t), response = await f.request(); assert.equal(response.status, 200);
  assert.match(response.headers.get('cache-control'), /no-store/); const ticket = await response.json();
  assert.deepEqual(Object.keys(ticket).sort(), ['avatar', 'expiresAt', 'initialContextDelivered', 'inputSampleRate', 'outputSampleRate', 'protocol', 'streamPath', 'ticket', 'transcript'].sort());
  assert.equal(ticket.avatar, 'moss'); assert.equal(ticket.initialContextDelivered, false); assert.match(ticket.transcript, /anxious/);
  assert.equal(ticket.streamPath, '/api/avatar/personaplex'); assert.match(ticket.ticket, /^[A-Za-z0-9_-]{43}$/);
  assert.equal(JSON.stringify(ticket).includes(token), false); assert.equal(JSON.stringify(ticket).includes('modal'), false);
  assert.equal(JSON.stringify(ticket).includes('selectionId'), false); assert.equal(JSON.stringify(ticket).includes('promptHash'), false);
  assert.equal(f.state.asr, 1); assert.equal(f.state.prime, 1); assert.equal(f.state.lease.promptHash, INITIAL_ROLE_HASHES.moss);
  const stream = f.connect(ticket.ticket); assert.equal(await stream.opened, true);
  await until(() => stream.messages.some(value => value.type === 'ready'));
  assert.deepEqual(stream.messages[0], ready); assert.equal(f.state.connects, 1);
  const input = Buffer.alloc(3841); input[0] = 0x10; stream.socket.send(input);
  await until(() => f.state.input.length === 1); assert.equal(f.state.input[0].binary, true);
  f.state.worker.send(output()); await until(() => stream.messages.some(Buffer.isBuffer));
  stream.socket.close(); await until(() => f.state.worker.readyState === WebSocket.CLOSED);
  assert.equal(f.state.bank, 0);
});

test('first audio rate/header/duration, forged context and query are rejected before ASR/private prime', async t => {
  const f = await fixture(t);
  for (const payload of [wav(12.01), wav(.1, 16000), { ...wav(), avatar: 'spark' }, { ...wav(), prompt: 'browser-selected' },
    { ...wav(), customerId: 'identity' }, { ...wav(), transcript: 'client bank facts' }]) {
    assert.equal((await f.request(payload)).status, 400);
  }
  assert.equal((await f.request(wav(), { query: '?avatar=spark' })).status, 400);
  assert.equal((await f.request(wav(), { headers: { 'Content-Type': 'text/plain' } })).status, 415);
  assert.equal(f.state.asr, 0); assert.equal(f.state.prime, 0); assert.equal(f.state.bank, 0);
});

test('exact twelve-second canonical capture fits ingress cap; larger JSON fails before ASR', async t => {
  const maximum = wav(12), f = await fixture(t, { expectedAudio: maximum });
  assert.equal((await f.request(maximum)).status, 200); assert.equal(f.state.asr, 1); assert.equal(f.state.prime, 1);
  const g = await fixture(t);
  assert.equal((await g.request({ audio: 'A'.repeat(800_000), format: 'wav' })).status, 413);
  assert.equal(g.state.asr, 0); assert.equal(g.state.prime, 0);
});

test('cookie lookup and exact-origin/CSRF checks reject before any paid initial work', async t => {
  const f = await fixture(t);
  for (const headers of [{ Cookie: '' }, { Cookie: 'avatar_session=forged' }, { Origin: 'https://untrusted.test' },
    { Origin: '' }, { 'Sec-Fetch-Site': 'cross-site' }]) assert.ok((await f.request(wav(), { headers })).status >= 400);
  assert.equal(f.state.asr, 0); assert.equal(f.state.prime, 0); assert.equal(f.state.connects, 0);
});

test('public gateway rejects initial admission and WebSocket upgrade without operator ingress proof', async t => {
  const gateToken = 'trusted-gateway-' + 'x'.repeat(32);
  const f = await fixture(t, { config: { publicAccess: true, accessGateToken: gateToken } });
  const denied = await f.request(wav(), { headers: { 'X-Avatar-Gateway-Token': '' } });
  assert.equal(denied.status, 401); assert.equal((await denied.json()).code, 'access_gate_required');
  assert.equal(f.state.asr, 0); assert.equal(f.state.prime, 0);
  const ticket = await (await f.request()).json();
  const stream = f.connect(ticket.ticket, { headers: { 'X-Avatar-Gateway-Token': '' } }); assert.equal(await stream.opened, false);
  assert.equal(stream.rejection.status, 401); assert.equal(f.state.connects, 0);
});

test('primed v2 cannot be stolen by ordinary fixed-session issuance or a different browser cookie', async t => {
  const f = await fixture(t, { text: 'Please explain my business plan.' });
  const ticket = await (await f.request()).json(); assert.equal(ticket.avatar, 'orbit');
  const other = await f.browserSession();
  const ordinary = await fetch(f.base + '/api/avatar/personaplex-session', {
    method: 'POST', headers: { Origin: f.base, Cookie: other.cookie, 'Content-Type': 'application/json' }, body: JSON.stringify({ avatar: 'orbit' }),
  });
  assert.equal(ordinary.status, 503);
  const theft = f.connect(ticket.ticket, { headers: { Cookie: other.cookie } }); assert.equal(await theft.opened, false);
  assert.equal(theft.rejection.status, 401); assert.equal(f.state.connects, 0);
  const owner = f.connect(ticket.ticket); assert.equal(await owner.opened, true);
  await until(() => owner.messages.some(value => value.type === 'ready'));
  const replay = f.connect(ticket.ticket); assert.equal(await replay.opened, false); assert.equal(replay.rejection.status, 401);
  assert.equal(f.state.asr, 1); assert.equal(f.state.prime, 1); assert.equal(f.state.connects, 1);
});

test('initial ASR is reserved once even under concurrent HTTP attempts', async t => {
  const wait = deferred(), f = await fixture(t, { asrWait: wait.promise });
  const first = f.request(); await until(() => f.state.asr === 1);
  const second = await f.request(); assert.equal(second.status, 503); assert.equal(f.state.asr, 1); assert.equal(f.state.prime, 0);
  wait.resolve(); assert.equal((await first).status, 200); assert.equal(f.state.prime, 1);
});

test('HTTP cancellation during ignored ASR burns warm epoch and prevents late prime/ticket', async t => {
  const wait = deferred(), f = await fixture(t, { asrWait: wait.promise }); const controller = new AbortController();
  const request = f.request(wav(), { signal: controller.signal });
  await until(() => f.state.asr === 1); controller.abort(); await assert.rejects(request);
  await until(() => f.state.asrSignal.aborted);
  wait.resolve(); await tick(30);
  assert.equal(f.state.prime, 0); assert.equal((await f.request()).status, 503);
  assert.equal((await f.browserSession()).body.initialVoiceAvailable, false); assert.equal(f.state.connects, 0);
});

test('HTTP cancellation after actual private prime admission never transfers or retries that worker', async t => {
  const wait = deferred(), f = await fixture(t, { primeWait: wait.promise }); const controller = new AbortController();
  const request = f.request(wav(), { signal: controller.signal });
  await until(() => f.state.prime === 1); controller.abort(); await assert.rejects(request);
  wait.resolve(); await tick(30);
  const retry = await f.request(); assert.equal(retry.status, 503);
  assert.equal(f.state.asr, 1); assert.equal(f.state.prime, 1); assert.equal(f.state.connects, 0);
  assert.equal((await f.browserSession()).body.initialVoiceAvailable, false);
});

test('private prime receipt cannot acknowledge browser delivery before actual HTTP finish', async t => {
  const f = await fixture(t, { holdResponse: true }), controller = new AbortController();
  const request = f.request(wav(), { signal: controller.signal });
  await until(() => f.state.responseHeld);
  assert.equal(f.state.prime, 1); assert.equal(f.state.lease.phase, 'primed'); assert.ok(f.state.heldTicket);
  controller.abort(); await assert.rejects(request); await until(() => f.state.deliveryClosed);
  const late = f.connect(f.state.heldTicket); assert.equal(await late.opened, false); assert.equal(late.rejection.status, 503);
  assert.equal(f.state.connects, 0); assert.equal(f.state.asr, 1); assert.equal(f.state.prime, 1);
  assert.equal((await f.request()).status, 503);
});

test('unknown private-prime response is sanitized, consumed and never retried', async t => {
  const f = await fixture(t, { primeError: true }); const response = await f.request(); assert.equal(response.status, 502);
  const body = await response.json(); assert.equal(body.code, 'initial_selection_failed'); assert.equal(JSON.stringify(body).includes('key'), false);
  assert.equal((await f.request()).status, 503); assert.equal(f.state.prime, 1); assert.equal(f.state.asr, 1); assert.equal(f.state.bank, 0);
});

test('warm capture and POST budgets fail before ASR; no new provider is started', async t => {
  const f = await fixture(t, { remaining: 206_999 }); assert.equal(f.config.initialVoiceAvailable, false);
  f.state.time += 12_000; assert.equal((await f.request()).status, 503);
  assert.equal(f.state.asr, 0); assert.equal(f.state.prime, 0); assert.equal(f.state.connects, 0);
});

test('initial ticket cannot dial once less than140s remains and cannot be replayed after rejection', async t => {
  const f = await fixture(t, { remaining: 195_000, asrAdvance: 37_000, primeAdvance: 12_000 }), ticket = await (await f.request()).json();
  assert.ok(ticket.ticket); assert.equal(Date.parse(f.state.lease.expiresAt) - f.state.time, 146_000);
  f.state.time = Date.parse(f.state.lease.expiresAt) - 139_999;
  const rejected = f.connect(ticket.ticket); assert.equal(await rejected.opened, false); assert.equal(rejected.rejection.status, 503);
  const replay = f.connect(ticket.ticket); assert.equal(await replay.opened, false); assert.equal(replay.rejection.status, 401);
  assert.equal(f.state.connects, 0);
});

test('native READY crossing132s replay+native floor is withheld and upstream is cleaned', async t => {
  const f = await fixture(t, { autoReady: false }), ticket = await (await f.request()).json();
  const stream = f.connect(ticket.ticket); assert.equal(await stream.opened, true); await until(() => f.state.worker);
  f.state.time = Date.parse(f.state.lease.expiresAt) - 131_999;
  f.state.worker.send(JSON.stringify(ready));
  await until(() => stream.socket.readyState === WebSocket.CLOSED && f.state.worker.readyState === WebSocket.CLOSED);
  assert.equal(stream.messages.some(value => value.type === 'ready'), false);
  assert.equal(stream.messages.find(value => value.type === 'error')?.code, 'voice_expired'); assert.equal(f.state.bank, 0);
});

test('v2 identity mutation during active native stream terminates exact owner without re-prime', async t => {
  const f = await fixture(t), ticket = await (await f.request()).json(), stream = f.connect(ticket.ticket);
  assert.equal(await stream.opened, true); await until(() => stream.messages.some(value => value.type === 'ready'));
  f.state.worker.send(output()); await until(() => stream.messages.some(Buffer.isBuffer));
  f.state.lease.selectionId = 'aDifferentOpaqueBinding';
  await until(() => stream.socket.readyState === WebSocket.CLOSED && f.state.worker.readyState === WebSocket.CLOSED);
  assert.equal(stream.messages.find(value => value.type === 'error')?.code, 'voice_expired');
  assert.equal(f.state.prime, 1); assert.equal(f.state.asr, 1); assert.equal(f.state.connects, 1); assert.equal(f.state.bank, 0);
});
