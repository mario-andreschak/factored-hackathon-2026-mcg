import test from 'node:test';
import assert from 'node:assert/strict';
import { createAvatarServer } from '../server/app.mjs';
import { readConfig } from '../server/config.mjs';

// All audio and upstream replies in this file are fixed local fixtures. The
// injected transport rejects every endpoint that the test did not explicitly own.
const ROUTER = 'https://openrouter.ai/api/v1';
const BANK = 'http://127.0.0.1:43800';
const NATIVE_ROUTES = ['native-turn', 'native-observe', 'native-played', 'native-reset', 'native-result', 'native-result-receipt'];
const USAGE = { prompt_tokens: 10, completion_tokens: 10, total_tokens: 20, cost: .001,
  prompt_tokens_details: { audio_tokens: 5 }, completion_tokens_details: { audio_tokens: 5 } };
const PCM = Buffer.from([17, 0, 42, 0]);
const AUDIO_REPLY = 'Estoy contigo. Podemos dar el siguiente paso.';
const USER_TEXT = 'Me preocupa este problema.';
const TASK_REPLY = 'La consulta de prueba terminó. No se realizó ninguna acción.';
const BANK_A = 'synthetic_account_A_123456789';
const BANK_B = 'synthetic_account_B_123456789';

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

async function until(predicate) {
  const deadline = performance.now() + 1500;
  while (!predicate()) {
    if (performance.now() > deadline) throw new Error('The local fixture did not reach its expected state.');
    await new Promise(resolve => setTimeout(resolve, 2));
  }
}

function wav(sample = 11) {
  const data = Buffer.alloc(44 + 4800);
  data.write('RIFF'); data.writeUInt32LE(data.length - 8, 4); data.write('WAVEfmt ', 8);
  data.writeUInt32LE(16, 16); data.writeUInt16LE(1, 20); data.writeUInt16LE(1, 22);
  data.writeUInt32LE(24000, 24); data.writeUInt32LE(48000, 28); data.writeUInt16LE(2, 32); data.writeUInt16LE(16, 34);
  data.write('data', 36); data.writeUInt32LE(data.length - 44, 40); data.writeInt16LE(sample, 44);
  return data.toString('base64');
}
const recorded = { audio: wav(), format: 'wav', avatar: 'moss', locale: 'es' };
const textTurn = { message: 'Siguiente pregunta.', avatar: 'moss', locale: 'es' };
const jsonResponse = (value, options = {}) => new Response(JSON.stringify(value), {
  ...options, headers: { 'Content-Type': 'application/json', ...options.headers },
});
const frame = delta => ({ id: 'synthetic-stream', model: 'openai/gpt-audio',
  choices: [{ index: 0, delta, finish_reason: null, native_finish_reason: null }], usage: null });
const encode = value => `data: ${typeof value === 'string' ? value : JSON.stringify(value)}\n\n`;

function nativeResponse({ delayed = false, text = AUDIO_REPLY } = {}) {
  let controller, closed = false;
  const body = new ReadableStream({
    start(value) { controller = value; },
    cancel() { closed = true; },
  });
  const send = value => { if (!closed) controller.enqueue(new TextEncoder().encode(encode(value))); };
  const finish = () => {
    if (closed) return;
    send(frame({ audio: { id: 'synthetic-audio', data: PCM.toString('base64'), transcript: text } }));
    send(frame({ role: 'assistant', content: '', audio: { expires_at: 2000000000 } }));
    send(frame({ role: 'assistant', content: '' }));
    send({ ...frame({ role: 'assistant', content: '' }), usage: USAGE });
    send('[DONE]'); controller.close(); closed = true;
  };
  if (!delayed) finish();
  return { response: new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }), finish };
}

async function fixture(t, { env = {}, overrides = {}, native, asr, bank, now } = {}) {
  const calls = [];
  const config = { ...readConfig({ NODE_ENV: 'test', OPENROUTER_API_KEY: 'synthetic-router-key',
    AVATAR_VOICE_PROVIDER: 'openrouter-native', ...env }), ...overrides };
  const fetchImpl = async (url, options = {}) => {
    const kind = url === `${ROUTER}/chat/completions` ? 'native' : url === `${ROUTER}/audio/transcriptions` ? 'asr' :
      String(url).startsWith(`${BANK}/`) ? 'bank' : 'unexpected';
    const call = { kind, url, options, body: options.body ? JSON.parse(options.body) : undefined };
    calls.push(call);
    if (kind === 'native') return native ? native(call, calls.filter(item => item.kind === kind).length) : nativeResponse().response;
    if (kind === 'asr') return asr ? asr(call) : jsonResponse({ text: USER_TEXT });
    if (kind === 'bank' && bank) return bank(call);
    throw new Error('The test attempted an unowned upstream endpoint.');
  };
  const server = createAvatarServer({ config, fetchImpl, ...(now ? { now } : {}) });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const base = `http://127.0.0.1:${server.address().port}`;
  const gate = config.publicAccess ? { 'x-avatar-gateway-token': config.accessGateToken } : {};
  const newSession = async () => {
    const response = await fetch(`${base}/api/avatar/config`, { headers: gate });
    assert.equal(response.status, 200);
    return { cookie: response.headers.getSetCookie()[0].split(';')[0], config: await response.json() };
  };
  const first = await newSession();
  const post = (route, body, { cookie = first.cookie, headers = {}, ...options } = {}) => fetch(
    `${base}${route.startsWith('/') ? route : `/api/avatar/${route}`}`, {
      method: 'POST', ...options, headers: { ...gate, Origin: base, Cookie: cookie, 'Content-Type': 'application/json', ...headers },
      body: JSON.stringify(body),
    });
  return { post, newSession, calls, base, cookie: first.cookie, config: first.config };
}

async function lines(response) {
  assert.equal(response.status, 200);
  assert.match(response.headers.get('content-type'), /application\/x-ndjson/);
  return (await response.text()).trim().split('\n').filter(Boolean).map(line => JSON.parse(line));
}

async function error(response, status, code) {
  assert.equal(response.status, status);
  const value = await response.json();
  assert.equal(value.code, code);
  assert.deepEqual(Object.keys(value).sort(), ['code', 'error']);
  assert.ok(!JSON.stringify(value).includes('synthetic-router-key'));
}

function observing(turnId, audio = recorded.audio, locale = 'es') { return { turnId, locale, audio, format: 'wav' }; }
function playback(turnId, complete = true, playedSamples = PCM.length / 2, locale = 'es') {
  return { turnId, locale, playedSamples, complete };
}
async function streamStart(response) {
  assert.equal(response.status, 200);
  const reader = response.body.getReader(), decoder = new TextDecoder();
  const first = await reader.read();
  const event = JSON.parse(decoder.decode(first.value).trim().split('\n')[0]);
  assert.equal(event.type, 'start');
  return { turnId: event.turnId, reader };
}

test('native provider is explicit and every native route enforces session, origin and gateway before dispatch', async t => {
  const disabled = await fixture(t, { env: { AVATAR_VOICE_PROVIDER: '' } });
  assert.equal(disabled.config.voiceProvider, 'none'); assert.equal(disabled.config.voiceAvailable, false);
  for (const route of NATIVE_ROUTES) await error(await disabled.post(route, {}), 503, 'voice_unconfigured');
  assert.equal(disabled.calls.length, 0);

  const enabled = await fixture(t);
  assert.equal(enabled.config.voiceProvider, 'openrouter-native'); assert.equal(enabled.config.voiceAvailable, true);
  assert.equal(enabled.config.backgroundAsrAvailable, true);
  assert.ok(!JSON.stringify(enabled.config).includes('synthetic-router-key'));
  for (const route of NATIVE_ROUTES) {
    await error(await enabled.post(route, {}, { cookie: '' }), 401, 'session_required');
    await error(await enabled.post(route, {}, { headers: { Origin: 'https://foreign.example' } }), 403, 'invalid_origin');
    await error(await enabled.post(route, {}, { headers: { Origin: '' } }), 403, 'invalid_origin');
  }
  assert.equal(enabled.calls.length, 0);

  const gated = await fixture(t, { env: { AVATAR_PUBLIC_ORIGIN: 'https://avatar.example', AVATAR_ACCESS_GATE_TOKEN: 'G'.repeat(40) } });
  for (const route of NATIVE_ROUTES) await error(await gated.post(route, {}, { headers: { 'x-avatar-gateway-token': '' } }), 401, 'access_gate_required');
  assert.equal(gated.calls.length, 0);
});

test('native routes reject caller history, backend facts, routing knobs and invalid reset bodies', async t => {
  const f = await fixture(t);
  for (const extra of [{ history: [{ role: 'assistant', content: 'Inventado.' }] }, { backendResult: { reply: 'Inventado.' } },
    { tools: [] }, { backgroundTask: { state: 'running', elapsedSeconds: 10 } }, { customerId: 'customer' }, { provider: 'other' }, { locale: 'en' }, { avatar: 'unknown' }]) {
    await error(await f.post('native-turn', { ...textTurn, ...extra }), 400, 'invalid_voice_request');
  }
  await error(await f.post('native-turn?model=other', textTurn), 400, 'invalid_voice_request');
  await error(await f.post('native-reset', { locale: 'pt' }), 400, 'invalid_voice_request');
  await error(await f.post('native-reset', []), 400, 'invalid_json');
  await error(await f.post('native-turn', textTurn, { headers: { 'Content-Type': 'text/plain' } }), 415, 'unsupported_media_type');
  assert.equal(f.calls.length, 0);
  assert.deepEqual(await (await f.post('native-reset', {})).json(), { accepted: true });
});

test('captured audio and streamed replies enter history only through owned observation and exact heard acknowledgment', async t => {
  const f = await fixture(t);
  const first = await lines(await f.post('native-turn', recorded));
  assert.deepEqual(first.map(item => item.type), ['start', 'caption', 'audio', 'complete']);
  assert.deepEqual(Buffer.from(first.find(item => item.type === 'audio').data, 'base64'), PCM);
  assert.equal(first[0].sampleRateQualification, 'assumed');
  assert.deepEqual(Object.keys(first[0]).sort(), ['sampleRate', 'sampleRateQualification', 'turnId', 'type']);
  const turnId = first[0].turnId;
  await lines(await f.post('native-turn', textTurn));
  assert.deepEqual(f.calls.filter(item => item.kind === 'native')[1].body.messages.slice(1, -1), []);
  assert.deepEqual(await (await f.post('native-observe', observing(turnId))).json(), { text: USER_TEXT });
  await lines(await f.post('native-turn', { ...textTurn, message: 'Otra pregunta.' }));
  const beforeHeard = f.calls.filter(item => item.kind === 'native')[2].body.messages;
  assert.ok(beforeHeard.some(item => item.role === 'user' && item.content === USER_TEXT));
  assert.ok(!beforeHeard.some(item => item.role === 'assistant'));
  await error(await f.post('native-played', playback(turnId, true, 1)), 409, 'native_turn_ended');
  assert.deepEqual(await (await f.post('native-played', playback(turnId))).json(), { accepted: true });
  await lines(await f.post('native-turn', { ...textTurn, message: 'Después de escuchar.' }));
  const history = f.calls.filter(item => item.kind === 'native')[3].body.messages;
  assert.equal(history.filter(item => item.role === 'assistant' && item.content === AUDIO_REPLY).length, 1);
  assert.equal(history.filter(item => item.role === 'user' && item.content === USER_TEXT).length, 1);
  assert.ok(!JSON.stringify(first).includes('synthetic-audio'));
});

test('observation is single-use and binds the original audio, locale and browser cookie', async t => {
  const f = await fixture(t), foreign = await f.newSession();
  const [start] = await lines(await f.post('native-turn', recorded));
  await error(await f.post('native-observe', observing(start.turnId), { cookie: foreign.cookie }), 409, 'native_turn_ended');
  await error(await f.post('native-played', playback(start.turnId), { cookie: foreign.cookie }), 409, 'native_turn_ended');
  await error(await f.post('native-observe', observing(start.turnId, wav(12))), 409, 'native_turn_ended');
  await error(await f.post('native-observe', observing(start.turnId, recorded.audio, 'pt')), 409, 'native_turn_ended');
  assert.equal(f.calls.filter(item => item.kind === 'asr').length, 0);
  assert.equal((await f.post('native-observe', observing(start.turnId))).status, 200);
  await error(await f.post('native-observe', observing(start.turnId)), 409, 'native_observer_used');
  const calls = f.calls.filter(item => item.kind === 'asr');
  assert.equal(calls.length, 1); assert.equal(calls[0].body.input_audio.data, recorded.audio); assert.equal(calls[0].body.language, 'es');
});

test('slow observer recognition runs in parallel and never holds up native audio completion', async t => {
  const speech = nativeResponse({ delayed: true }), recognized = deferred();
  const f = await fixture(t, { native: () => speech.response, asr: () => recognized.promise });
  const started = await streamStart(await f.post('native-turn', recorded));
  const observed = f.post('native-observe', observing(started.turnId));
  await until(() => f.calls.some(item => item.kind === 'asr'));
  speech.finish();
  const output = [];
  while (true) { const part = await started.reader.read(); if (part.done) break; output.push(Buffer.from(part.value)); }
  assert.match(Buffer.concat(output).toString(), /"type":"complete"/);
  assert.equal(f.calls.find(item => item.kind === 'asr').options.signal.aborted, false);
  recognized.resolve(jsonResponse({ text: USER_TEXT }));
  assert.deepEqual(await (await observed).json(), { text: USER_TEXT });
});

for (const cancellation of ['client abort', 'superseding utterance']) test(`${cancellation} cancels assistant output but preserves the independent captured-input observer`, async t => {
  const speech = nativeResponse({ delayed: true }), recognized = deferred();
  const f = await fixture(t, { native: (_, index) => index === 1 ? speech.response : nativeResponse().response, asr: () => recognized.promise });
  const controller = new AbortController();
  const started = await streamStart(await f.post('native-turn', recorded, { signal: controller.signal }));
  const observed = f.post('native-observe', observing(started.turnId));
  await until(() => f.calls.some(item => item.kind === 'asr'));
  if (cancellation === 'client abort') controller.abort();
  else await lines(await f.post('native-turn', textTurn));
  await until(() => f.calls.find(item => item.kind === 'native').options.signal.aborted);
  assert.equal(f.calls.find(item => item.kind === 'asr').options.signal.aborted, false);
  recognized.resolve(jsonResponse({ text: USER_TEXT }));
  assert.deepEqual(await (await observed).json(), { text: USER_TEXT });
  await error(await f.post('native-played', playback(started.turnId)), 409, 'native_turn_ended');
  await lines(await f.post('native-turn', { ...textTurn, message: 'Continúa.' }));
  const messages = f.calls.filter(item => item.kind === 'native').at(-1).body.messages;
  assert.ok(messages.some(item => item.role === 'user' && item.content === USER_TEXT));
  assert.ok(!messages.some(item => item.role === 'assistant'));
  await started.reader.cancel().catch(() => {});
});

for (const change of ['reset', 'locale', 'account', 'logout']) test(`${change} invalidates pending native replies, observer results and old acknowledgments`, async t => {
  const speech = nativeResponse({ delayed: true }), recognized = deferred(); let login = 0;
  const f = await fixture(t, { env: { SAVIA_UPSTREAM: BANK }, native: (_, index) => index === 1 ? speech.response : nativeResponse().response,
    asr: () => recognized.promise,
    bank: call => {
      if (call.url.endsWith('/api/auth/logout')) return new Response(null, { status: 204, headers: { 'X-Banking-Revoke': 'logout' } });
      assert.equal(call.url, `${BANK}/api/auth/login`);
      return jsonResponse({ authenticated: true }, { headers: { 'Set-Cookie': `flujo_bank_session=${++login === 1 ? BANK_A : BANK_B}; Path=/; HttpOnly; SameSite=Strict` } });
    } });
  if (['account', 'logout'].includes(change)) assert.equal((await f.post('/savia/api/auth/login', { profile: 'synthetic', code: 'synthetic' })).status, 200);
  const started = await streamStart(await f.post('native-turn', recorded));
  const observed = f.post('native-observe', observing(started.turnId));
  await until(() => f.calls.some(item => item.kind === 'asr'));
  if (change === 'reset') assert.equal((await f.post('native-reset', {})).status, 200);
  else if (change === 'locale') await lines(await f.post('native-turn', { ...textTurn, locale: 'pt' }));
  else if (change === 'logout') assert.equal((await f.post('/savia/api/auth/logout', {})).status, 204);
  else assert.equal((await f.post('/savia/api/auth/login', { profile: 'synthetic', code: 'synthetic' })).status, 200);
  await until(() => f.calls.find(item => item.kind === 'native').options.signal.aborted && f.calls.find(item => item.kind === 'asr').options.signal.aborted);
  // Deliberately ignore cancellation upstream: the route must still suppress it.
  recognized.resolve(jsonResponse({ text: 'Texto obsoleto que no debe aparecer.' }));
  await error(await observed, 409, 'native_turn_ended');
  await error(await f.post('native-played', playback(started.turnId)), 409, 'native_turn_ended');
  await lines(await f.post('native-turn', { ...textTurn, locale: change === 'locale' ? 'pt' : 'es' }));
  assert.ok(!JSON.stringify(f.calls.filter(item => item.kind === 'native').at(-1).body.messages).includes('Texto obsoleto'));
  await started.reader.cancel().catch(() => {});
});

test('only a server-observed Savia result can be narrated once, after a fresh matching account check', async t => {
  const f = await fixture(t, { env: { SAVIA_UPSTREAM: BANK }, bank: call => {
    if (call.url.endsWith('/api/auth/login')) return jsonResponse({ authenticated: true }, { headers: { 'Set-Cookie': `flujo_bank_session=${BANK_A}; Path=/; HttpOnly` } });
    if (call.url.endsWith('/api/auth/me')) return jsonResponse({ authenticated: true });
    if (call.url.endsWith('/api/chat/messages')) return jsonResponse({ reply: TASK_REPLY, mode: 'flujo', status: 'completed', private_worker_field: 'not-public' });
    throw new Error('Unowned synthetic banking path.');
  } });
  await error(await f.post('native-result', { taskId: 'forged', avatar: 'moss', locale: 'es' }), 401, 'sign_in_required');
  await f.post('/savia/api/auth/login', { profile: 'synthetic', code: 'synthetic' });
  await error(await f.post('native-result-receipt', { reply: TASK_REPLY, locale: 'es' }), 409, 'native_turn_ended');
  assert.equal((await f.post('/savia/api/chat/messages', { message: 'Consulta sintética fija.' })).status, 200);
  await error(await f.post('native-result-receipt', { reply: 'Una respuesta inventada.', locale: 'es' }), 409, 'native_turn_ended');
  const receipt = await (await f.post('native-result-receipt', { reply: TASK_REPLY, locale: 'es' })).json();
  assert.deepEqual(Object.keys(receipt), ['taskId']);
  const foreign = await f.newSession();
  await error(await f.post('native-result-receipt', { reply: TASK_REPLY, locale: 'es' }, { cookie: foreign.cookie }), 409, 'native_turn_ended');
  await error(await f.post('native-result', { ...receipt, avatar: 'moss', locale: 'es', reply: 'Inventado.' }), 400, 'invalid_voice_request');
  const output = await lines(await f.post('native-result', { ...receipt, avatar: 'moss', locale: 'es' }));
  assert.equal(output.at(-1).type, 'complete');
  const native = f.calls.find(item => item.kind === 'native');
  assert.ok(JSON.stringify(native.body.messages).includes(TASK_REPLY));
  assert.ok(!JSON.stringify(native.body).includes('private_worker_field'));
  assert.equal(f.calls.filter(item => item.url.endsWith('/api/auth/me')).length, 2);
  await error(await f.post('native-result', { ...receipt, avatar: 'moss', locale: 'es' }), 409, 'native_turn_ended');
  assert.equal(f.calls.filter(item => item.kind === 'native').length, 1);
});

test('an account change during fresh receipt verification prevents provider dispatch and revokes the old result', async t => {
  const checked = deferred(); let login = 0;
  const f = await fixture(t, { env: { SAVIA_UPSTREAM: BANK }, bank: call => {
    if (call.url.endsWith('/api/auth/login')) return jsonResponse({ authenticated: true }, { headers: { 'Set-Cookie': `flujo_bank_session=${++login === 1 ? BANK_A : BANK_B}; Path=/; HttpOnly` } });
    if (call.url.endsWith('/api/chat')) return jsonResponse({ reply: TASK_REPLY, mode: 'flujo', status: 'completed' });
    if (call.url.endsWith('/api/auth/me')) return checked.promise;
    throw new Error('Unowned synthetic banking path.');
  } });
  await f.post('/savia/api/auth/login', { profile: 'synthetic', code: 'synthetic' });
  assert.equal((await f.post('task', { message: 'Consulta sintética fija.' })).status, 200);
  const receipt = await (await f.post('native-result-receipt', { reply: TASK_REPLY, locale: 'es' })).json();
  const narrating = f.post('native-result', { ...receipt, avatar: 'moss', locale: 'es' });
  await until(() => f.calls.some(item => item.url.endsWith('/api/auth/me')));
  await f.post('/savia/api/auth/login', { profile: 'synthetic', code: 'synthetic' });
  checked.resolve(jsonResponse({ authenticated: true }));
  await error(await narrating, 409, 'native_turn_ended');
  await error(await f.post('native-result-receipt', { reply: TASK_REPLY, locale: 'es' }), 409, 'native_turn_ended');
  assert.equal(f.calls.filter(item => item.kind === 'native').length, 0);
});

test('a narration receipt is consumed before upstream dispatch even when the provider rejects the request', async t => {
  const f = await fixture(t, { env: { SAVIA_UPSTREAM: BANK },
    native: () => new Response('private transport diagnostic sentinel', { status: 500 }),
    bank: call => {
      if (call.url.endsWith('/api/auth/login')) return jsonResponse({ authenticated: true }, { headers: { 'Set-Cookie': `flujo_bank_session=${BANK_A}; Path=/; HttpOnly` } });
      if (call.url.endsWith('/api/chat')) return jsonResponse({ reply: TASK_REPLY, mode: 'flujo', status: 'completed' });
      if (call.url.endsWith('/api/auth/me')) return jsonResponse({ authenticated: true });
      throw new Error('Unowned synthetic banking path.');
    } });
  await f.post('/savia/api/auth/login', { profile: 'synthetic', code: 'synthetic' });
  await f.post('task', { message: 'Consulta sintética fija.' });
  const receipt = await (await f.post('native-result-receipt', { reply: TASK_REPLY, locale: 'es' })).json();
  const value = { ...receipt, avatar: 'moss', locale: 'es' };
  const first = await f.post('native-result', value);
  assert.equal(first.status, 502);
  assert.ok(!(await first.text()).includes('sentinel'));
  await error(await f.post('native-result', value), 409, 'native_turn_ended');
  await error(await f.post('native-result-receipt', { reply: TASK_REPLY, locale: 'es' }), 409, 'native_turn_ended');
  assert.equal(f.calls.filter(item => item.kind === 'native').length, 1);
});

test('voice capacity and whole-operation timeout are enforced and released after cancellation', async t => {
  let mode = 'pending';
  const f = await fixture(t, { overrides: { maxVoiceOperations: 1, voiceTimeoutMs: 100 }, native: call => {
    if (mode === 'success') return nativeResponse().response;
    return new Promise((_, reject) => call.options.signal.addEventListener('abort', () => reject(new Error('synthetic canceled transport')), { once: true }));
  } });
  const pending = f.post('native-turn', textTurn);
  await until(() => f.calls.some(item => item.kind === 'native'));
  await error(await f.post('native-turn', textTurn), 503, 'capacity');
  await error(await pending, 504, 'voice_timeout');
  assert.equal(f.calls.filter(item => item.kind === 'native').length, 1);
  mode = 'success';
  assert.equal((await lines(await f.post('native-turn', textTurn))).at(-1).type, 'complete');
});

test('a complete event is acknowledgment-ready even while upstream reader cleanup is still pending', async t => {
  const complete = nativeResponse();
  const reader = complete.response.body.getReader();
  let cleanupStarted = false;
  const f = await fixture(t, { native: () => ({ ok: true, status: 200, headers: complete.response.headers,
    body: { getReader: () => ({ read: () => reader.read(), cancel() { cleanupStarted = true; return new Promise(() => {}); }, releaseLock() {} }) },
  }) });
  const output = await lines(await f.post('native-turn', recorded));
  assert.equal(output.at(-1).type, 'complete');
  assert.equal(cleanupStarted, true);
  // Receiving complete is the public boundary, rather than a later cleanup timer.
  const acknowledged = await f.post('native-played', playback(output[0].turnId));
  assert.equal(acknowledged.status, 200);
  assert.deepEqual(await acknowledged.json(), { accepted: true });
});

test('logout revokes both native owners before awaiting an unavailable upstream revocation service', async t => {
  const speech = nativeResponse({ delayed: true }), recognized = deferred(), revoked = deferred();
  const f = await fixture(t, { env: { SAVIA_UPSTREAM: BANK }, native: () => speech.response, asr: () => recognized.promise,
    bank: call => {
      if (call.url.endsWith('/api/auth/login')) return jsonResponse({ authenticated: true }, { headers: { 'Set-Cookie': `flujo_bank_session=${BANK_A}; Path=/; HttpOnly` } });
      if (call.url.endsWith('/api/auth/logout')) return revoked.promise;
      throw new Error('Unowned synthetic banking path.');
    } });
  await f.post('/savia/api/auth/login', { profile: 'synthetic', code: 'synthetic' });
  const started = await streamStart(await f.post('native-turn', recorded));
  const observingRequest = f.post('native-observe', observing(started.turnId));
  await until(() => f.calls.some(item => item.kind === 'asr'));
  const logout = f.post('/savia/api/auth/logout', {});
  await until(() => f.calls.some(item => item.url.endsWith('/api/auth/logout')));
  try {
    assert.equal(f.calls.find(item => item.kind === 'native').options.signal.aborted, true);
    assert.equal(f.calls.find(item => item.kind === 'asr').options.signal.aborted, true);
  } finally {
    revoked.resolve(new Response(null, { status: 204 }));
    recognized.resolve(jsonResponse({ text: 'Respuesta obsoleta.' }));
    await logout;
    await observingRequest;
    await started.reader.cancel().catch(() => {});
  }
});

test('an upstream authentication rejection clears the bound account and immediately revokes native owners', async t => {
  const speech = nativeResponse({ delayed: true }), recognized = deferred();
  const f = await fixture(t, { env: { SAVIA_UPSTREAM: BANK }, native: () => speech.response, asr: () => recognized.promise,
    bank: call => {
      if (call.url.endsWith('/api/auth/login')) return jsonResponse({ authenticated: true }, { headers: { 'Set-Cookie': `flujo_bank_session=${BANK_A}; Path=/; HttpOnly` } });
      if (call.url.endsWith('/api/auth/me')) return jsonResponse({ detail: 'Synthetic expired session.' }, { status: 401 });
      throw new Error('Unowned synthetic banking path.');
    } });
  await f.post('/savia/api/auth/login', { profile: 'synthetic', code: 'synthetic' });
  const started = await streamStart(await f.post('native-turn', recorded));
  const observingRequest = f.post('native-observe', observing(started.turnId));
  await until(() => f.calls.some(item => item.kind === 'asr'));
  const expired = await fetch(`${f.base}/savia/api/auth/me`, { headers: { Cookie: f.cookie } });
  assert.equal(expired.status, 401);
  try {
    assert.equal(f.calls.find(item => item.kind === 'native').options.signal.aborted, true);
    assert.equal(f.calls.find(item => item.kind === 'asr').options.signal.aborted, true);
  } finally {
    recognized.resolve(jsonResponse({ text: 'Respuesta obsoleta.' }));
    await observingRequest;
    await started.reader.cancel().catch(() => {});
  }
  await error(await f.post('native-result', { taskId: 'unknown', avatar: 'moss', locale: 'es' }), 401, 'sign_in_required');
});

const CONFIRMED_AMOUNT = 'El importe confirmado es 42.17. No se realizó ninguna acción.';
const PRIVATE_SPOKEN_REPLY = 'La consulta indica 42.17. Este final todavía no se escuchó.';
function trustedAmountBank(authenticated = () => true) {
  return call => {
    if (call.url.endsWith('/api/auth/login')) return jsonResponse({ authenticated: true }, { headers: { 'Set-Cookie': `flujo_bank_session=${BANK_A}; Path=/; HttpOnly` } });
    if (call.url.endsWith('/api/auth/me')) return authenticated() ? jsonResponse({ authenticated: true }) : jsonResponse({ detail: 'Synthetic expired session.' }, { status: 401 });
    if (call.url.endsWith('/api/chat')) return jsonResponse({ reply: CONFIRMED_AMOUNT, mode: 'flujo', status: 'completed' });
    throw new Error('Unowned synthetic banking path.');
  };
}
async function seedAmountNarration(f, { locale = 'es', heard = false } = {}) {
  assert.equal((await f.post('task', { message: 'Consulta sintética fija.' })).status, 200);
  const receipt = await (await f.post('native-result-receipt', { reply: CONFIRMED_AMOUNT, locale })).json();
  const output = await lines(await f.post('native-result', { ...receipt, avatar: 'moss', locale }));
  assert.equal(output.at(-1).type, 'complete');
  assert.deepEqual(await (await f.post('native-played', playback(output[0].turnId, heard, heard ? 2 : 1, locale))).json(), { accepted: true });
  return output[0].turnId;
}
function assertOriginalAudio(body, audio = recorded.audio) {
  const audioMessages = body.messages.filter(item => Array.isArray(item.content));
  assert.equal(audioMessages.length, 1);
  assert.deepEqual(audioMessages[0], { role: 'user', content: [{ type: 'input_audio', input_audio: { data: audio, format: 'wav' } }] });
}

test('an interrupted result survives as quoted trusted facts on the next real audio turn, without claiming its tail was heard', async t => {
  const f = await fixture(t, { env: { SAVIA_UPSTREAM: BANK }, bank: trustedAmountBank(),
    native: () => nativeResponse({ text: PRIVATE_SPOKEN_REPLY }).response });
  await f.post('/savia/api/auth/login', { profile: 'synthetic', code: 'synthetic' });
  await seedAmountNarration(f);
  await lines(await f.post('native-turn', recorded));
  const body = f.calls.filter(item => item.kind === 'native').at(-1).body;
  assertOriginalAudio(body);
  const quote = body.messages.at(-1);
  assert.equal(quote.role, 'user');
  assert.match(quote.content, /^Trusted backend data follows;/);
  assert.ok(quote.content.includes(CONFIRMED_AMOUNT));
  assert.ok(quote.content.includes('42.17'));
  assert.ok(!body.messages.some(item => item.role === 'assistant' && item.content === PRIVATE_SPOKEN_REPLY));
  assert.equal(f.calls.filter(item => item.url.endsWith('/api/auth/me')).length, 2);
});

test('private context requires fresh auth before another paid audio turn; auth failure clears both facts and heard history', async t => {
  let authenticated = true;
  const f = await fixture(t, { env: { SAVIA_UPSTREAM: BANK }, bank: trustedAmountBank(() => authenticated),
    native: () => nativeResponse({ text: PRIVATE_SPOKEN_REPLY }).response });
  await f.post('/savia/api/auth/login', { profile: 'synthetic', code: 'synthetic' });
  await seedAmountNarration(f, { heard: true });
  assert.equal(f.calls.filter(item => item.kind === 'native').length, 1);
  authenticated = false;
  await error(await f.post('native-turn', recorded), 401, 'sign_in_required');
  assert.equal(f.calls.filter(item => item.kind === 'native').length, 1);
  assert.equal(f.calls.filter(item => item.url.endsWith('/api/auth/me')).length, 2);
  // Once revoked, an anonymous general conversation can resume without old facts.
  await lines(await f.post('native-turn', recorded));
  const body = f.calls.filter(item => item.kind === 'native').at(-1).body;
  assertOriginalAudio(body);
  assert.deepEqual(body.messages.slice(1), [{ role: 'user', content: [{ type: 'input_audio', input_audio: { data: recorded.audio, format: 'wav' } }] }]);
  assert.ok(!JSON.stringify(body).includes('42.17'));
  assert.ok(!JSON.stringify(body).includes(PRIVATE_SPOKEN_REPLY));
  assert.equal(f.calls.filter(item => item.url.endsWith('/api/auth/me')).length, 2);
});

test('changing locale and explicit reset clear latest trusted facts before the next audio request is built', async t => {
  const f = await fixture(t, { env: { SAVIA_UPSTREAM: BANK }, bank: trustedAmountBank(),
    native: () => nativeResponse({ text: PRIVATE_SPOKEN_REPLY }).response });
  await f.post('/savia/api/auth/login', { profile: 'synthetic', code: 'synthetic' });
  await seedAmountNarration(f);
  await lines(await f.post('native-turn', { ...recorded, locale: 'pt' }));
  const changed = f.calls.filter(item => item.kind === 'native').at(-1).body;
  assertOriginalAudio(changed);
  assert.deepEqual(changed.messages.slice(1), [{ role: 'user', content: [{ type: 'input_audio', input_audio: { data: recorded.audio, format: 'wav' } }] }]);
  assert.ok(!JSON.stringify(changed).includes('42.17'));
  await seedAmountNarration(f, { locale: 'pt' });
  assert.deepEqual(await (await f.post('native-reset', {})).json(), { accepted: true });
  const checksBeforeResetTurn = f.calls.filter(item => item.url.endsWith('/api/auth/me')).length;
  await lines(await f.post('native-turn', { ...recorded, locale: 'pt' }));
  const reset = f.calls.filter(item => item.kind === 'native').at(-1).body;
  assertOriginalAudio(reset);
  assert.deepEqual(reset.messages.slice(1), [{ role: 'user', content: [{ type: 'input_audio', input_audio: { data: recorded.audio, format: 'wav' } }] }]);
  assert.ok(!JSON.stringify(reset).includes('42.17'));
  assert.equal(f.calls.filter(item => item.url.endsWith('/api/auth/me')).length, checksBeforeResetTurn);
});

for (const { route, change } of [
  { route: '/savia/api/chat', change: 'account rebind' },
  { route: 'task', change: 'logout' },
]) test(`a delayed ${route} reply is withheld after ${change} and cannot become trusted narration`, async t => {
  const delayed = deferred(); let login = 0;
  const oldReply = 'Synthetic old-account secret amount 42.17; never deliver this reply.';
  const f = await fixture(t, { env: { SAVIA_UPSTREAM: BANK }, bank: call => {
    if (call.url.endsWith('/api/auth/login')) return jsonResponse({ authenticated: true }, { headers: { 'Set-Cookie': `flujo_bank_session=${++login === 1 ? BANK_A : BANK_B}; Path=/; HttpOnly` } });
    if (call.url.endsWith('/api/auth/logout')) return new Response(null, { status: 204 });
    if (call.url.endsWith('/api/chat')) {
      assert.equal(call.options.headers.Cookie, `flujo_bank_session=${BANK_A}`);
      return delayed.promise;
    }
    throw new Error('Unowned synthetic banking path.');
  } });
  assert.equal((await f.post('/savia/api/auth/login', { profile: 'synthetic', code: 'synthetic' })).status, 200);
  const previous = f.post(route, { message: 'Consulta sintética fija.' });
  await until(() => f.calls.some(item => item.url.endsWith('/api/chat')));
  if (change === 'account rebind') assert.equal((await f.post('/savia/api/auth/login', { profile: 'other-synthetic', code: 'synthetic' })).status, 200);
  else assert.equal((await f.post('/savia/api/auth/logout', {})).status, 204);
  delayed.resolve(jsonResponse({ reply: oldReply, mode: 'flujo', status: 'completed', private_worker_field: 'old-account-private-marker' }));
  const withheld = await previous;
  assert.equal(withheld.status, 409);
  const publicError = await withheld.json();
  assert.equal(publicError.code, 'bank_session_changed');
  assert.ok(!JSON.stringify(publicError).includes(oldReply));
  assert.ok(!JSON.stringify(publicError).includes('old-account-private-marker'));
  await error(await f.post('native-result-receipt', { reply: oldReply, locale: 'es' }), 409, 'native_turn_ended');
  assert.equal(f.calls.filter(item => item.kind === 'native' || item.kind === 'asr').length, 0);
  await lines(await f.post('native-turn', recorded));
  const next = f.calls.find(item => item.kind === 'native').body;
  assertOriginalAudio(next);
  assert.ok(!JSON.stringify(next).includes(oldReply));
  assert.ok(!JSON.stringify(next).includes('old-account-private-marker'));
  assert.deepEqual(next.messages.slice(1), [{ role: 'user', content: [{ type: 'input_audio', input_audio: { data: recorded.audio, format: 'wav' } }] }]);
});

test('foreground native audio sees only host-owned pending read status and can complete before the read', async t => {
  const pending = deferred();
  const f = await fixture(t, { env: { SAVIA_UPSTREAM: BANK }, bank: async call => {
    if (call.url.endsWith('/api/auth/login')) return jsonResponse({ authenticated: true }, { headers: { 'Set-Cookie': `flujo_bank_session=${BANK_A}; Path=/; HttpOnly` } });
    if (call.url.endsWith('/api/auth/me')) return jsonResponse({ authenticated: true });
    if (call.url.endsWith('/api/chat')) { await pending.promise; return jsonResponse({ reply: TASK_REPLY, mode: 'flujo', status: 'completed' }); }
    throw new Error('Unowned synthetic banking path.');
  } });
  await f.post('/savia/api/auth/login', { profile: 'synthetic', code: 'synthetic' });
  const read = f.post('task', { message: 'Consulta mi cargo ficticio.' });
  await until(() => f.calls.some(call => call.url.endsWith('/api/chat')));
  const output = await lines(await f.post('native-turn', { ...textTurn, message: 'Mientras revisas, ¿qué debo guardar?' }));
  assert.equal(output.at(-1).type, 'complete');
  const prompt = f.calls.filter(item => item.kind === 'native').at(-1).body.messages[0].content;
  assert.match(prompt, /Trusted host status:.*read-only Savia inquiry is running in the background/);
  assert.ok(!prompt.includes(BANK_A)); assert.ok(!prompt.includes('Consulta mi cargo ficticio.'));
  pending.resolve(); assert.equal((await read).status, 200);
  await lines(await f.post('native-turn', textTurn));
  const next = f.calls.filter(item => item.kind === 'native').at(-1).body.messages[0].content;
  assert.ok(!next.includes('Trusted host status:'));
});
