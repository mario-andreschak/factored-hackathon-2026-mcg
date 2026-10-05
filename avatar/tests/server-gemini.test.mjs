import test from 'node:test';
import assert from 'node:assert/strict';
import { createAvatarServer } from '../server/app.mjs';
import { readConfig } from '../server/config.mjs';
import { GEMINI_TOKEN_URL, GEMINI_WEBSOCKET_URL } from '../server/gemini.mjs';

const clock = Date.parse('2026-10-01T12:00:00Z');
const key = 'server-only-gemini-sentinel';
const token = 'auth_tokens/short-lived-test-token';

test('Portuguese native language policy is pinned into the server-owned Gemini setup', async t => {
  let calls = 0;
  const { request } = await fixture(t, async (_url, options) => {
    calls++;
    const setup = JSON.parse(options.body).bidiGenerateContentSetup;
    assert.match(setup.systemInstruction.parts[0].text, /Converse sempre em português do Brasil/);
    assert.match(setup.systemInstruction.parts[0].text, /read-only/);
    assert.equal(setup.tools[0].functionDeclarations[1].name, 'delegate_task');
    return Response.json({ name: token });
  });
  const response = await request({ avatar: 'moss', locale: 'pt' });
  assert.equal(response.status, 200);
  assert.equal(calls, 1);
});

async function fixture(t, fetchImpl, overrides = {}) {
  const config = { ...readConfig({ NODE_ENV: 'test', GEMINI_API_KEY: key }), ...overrides };
  const server = createAvatarServer({ config, fetchImpl, now: () => clock });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const base = `http://127.0.0.1:${server.address().port}`;
  const configResponse = await fetch(`${base}/api/avatar/config`);
  const cookie = configResponse.headers.getSetCookie()[0]?.split(';')[0];
  const request = (body = { avatar: 'moss' }, options = {}) => fetch(`${base}/api/avatar/gemini-token${options.query || ''}`, {
    method: 'POST', ...options,
    headers: { Origin: base, Cookie: cookie, 'Content-Type': 'application/json', ...options.headers },
    body: JSON.stringify(body),
  });
  return { request, configResponse, base, cookie };
}

test('Gemini native key wins defaults, Google key alias works, and operator selections remain explicit', () => {
  const native = readConfig({ GEMINI_API_KEY: key, GOOGLE_API_KEY: 'alias', OPENAI_API_KEY: 'openai', OPENROUTER_API_KEY: 'router' });
  assert.equal(native.voiceProvider, 'gemini-live');
  assert.equal(native.geminiKey, key);
  assert.equal(native.geminiModel, 'gemini-3.8-live');
  assert.equal(readConfig({ GOOGLE_API_KEY: 'alias' }).voiceProvider, 'gemini-live');
  assert.equal(readConfig({ GOOGLE_API_KEY: 'alias' }).geminiKey, 'alias');
  assert.equal(readConfig({ GEMINI_API_KEY: key, AVATAR_VOICE_PROVIDER: 'openai-realtime' }).voiceProvider, 'openai-realtime');
  assert.throws(() => readConfig({ GEMINI_LIVE_MODEL: 'https://attacker.example' }), /Invalid/);
  assert.throws(() => readConfig({ GEMINI_LIVE_VOICE_MOSS: 'attacker?key=secret' }), /Invalid/);
});

test('native token provisioning fixes REST constraints, tools and lifetimes while exposing only ephemeral credentials', async t => {
  let calls = 0;
  const { request, configResponse } = await fixture(t, async (url, options) => {
    calls++;
    assert.equal(url, GEMINI_TOKEN_URL);
    assert.equal(options.headers['x-goog-api-key'], key);
    assert.equal(options.redirect, 'manual');
    const body = JSON.parse(options.body);
    assert.equal(body.uses, 1);
    assert.equal(body.expireTime, '2026-10-01T12:30:00.000Z');
    assert.equal(body.newSessionExpireTime, '2026-10-01T12:01:00.000Z');
    assert.equal(Object.hasOwn(body, 'fieldMask'), false);
    assert.equal(Object.hasOwn(body, 'liveConnectConstraints'), false);
    const setup = body.bidiGenerateContentSetup;
    assert.equal(setup.model, 'models/gemini-3.8-live');
    assert.deepEqual(setup.generationConfig.responseModalities, ['AUDIO']);
    assert.equal(setup.generationConfig.maxOutputTokens, 512);
    assert.equal(setup.generationConfig.speechConfig.voiceConfig.prebuiltVoiceConfig.voiceName, 'Puck');
    assert.ok(setup.systemInstruction.parts[0].text.includes('read-only'));
    assert.ok(setup.systemInstruction.parts[0].text.includes('continue listening') || setup.systemInstruction.parts[0].text.includes('Continue listening'));
    assert.deepEqual(setup.tools[0].functionDeclarations.map(value => [value.name, value.behavior]), [['set_world', 'NON_BLOCKING'], ['delegate_task', 'NON_BLOCKING']]);
    assert.deepEqual(setup.tools[0].functionDeclarations[1].parametersJsonSchema.required, ['message']);
    assert.equal(setup.tools[0].functionDeclarations[1].parametersJsonSchema.additionalProperties, false);
    assert.equal(setup.realtimeInputConfig.automaticActivityDetection.disabled, false);
    assert.equal(setup.realtimeInputConfig.activityHandling, 'START_OF_ACTIVITY_INTERRUPTS');
    assert.deepEqual(setup.inputAudioTranscription, {});
    assert.deepEqual(setup.outputAudioTranscription, {});
    return Response.json({ name: token, secretMetadata: key });
  });
  const config = await configResponse.json();
  assert.equal(config.voiceProvider, 'gemini-live');
  assert.equal(config.voiceAvailable, true);
  assert.equal(config.geminiModel, 'gemini-3.8-live');
  assert.ok(!JSON.stringify(config).includes(key));
  assert.ok(configResponse.headers.get('content-security-policy').includes('wss://generativelanguage.googleapis.com'));
  const response = await request({ avatar: 'spark' });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.deepEqual(await response.json(), { token, model: 'gemini-3.8-live', websocketUrl: GEMINI_WEBSOCKET_URL, expiresAt: '2026-10-01T12:30:00.000Z', newSessionExpiresAt: '2026-10-01T12:01:00.000Z', setup: { model: 'models/gemini-3.8-live' } });
  assert.equal(calls, 1);
});

test('native token cannot alter setup, choose URL, bypass session or cross origins', async t => {
  let calls = 0;
  const { request, base } = await fixture(t, async () => { calls++; return Response.json({ name: token }); }, { realtimeRateLimit: 30 });
  for (const value of [{}, { avatar: 'evil' }, { avatar: 'moss', model: 'other' }, { avatar: 'moss', customer_id: 'foreign' }, { avatar: 'moss', setup: {} }, { avatar: 'moss', uses: 0 }, { avatar: 'moss', locale: 'en' }, { avatar: 'moss', locale: 'pt-BR' }, { avatar: 'moss', locale: {} }]) {
    assert.equal((await request(value)).status, 400);
  }
  assert.equal((await request({ avatar: 'moss' }, { query: '?model=evil' })).status, 400);
  assert.equal((await request({ avatar: 'moss' }, { headers: { Origin: 'https://attacker.example' } })).status, 403);
  assert.equal((await request({ avatar: 'moss' }, { headers: { Cookie: '' } })).status, 401);
  assert.equal((await request({ avatar: 'moss' }, { headers: { 'Content-Type': 'text/plain' } })).status, 415);
  assert.equal((await request({ avatar: 'moss', pad: 'x'.repeat(1100) })).status, 413);
  assert.equal(calls, 0);
  const anonymous = await fetch(`${base}/api/avatar/gemini-token`, { method: 'POST', headers: { Origin: base, 'Content-Type': 'application/json' }, body: '{"avatar":"moss"}' });
  assert.equal(anonymous.status, 401);
});

test('native selection never dispatches the optional chained OpenRouter endpoints', async t => {
  let calls = 0;
  const { base, cookie, request } = await fixture(t, async () => { calls++; return Response.json({ name: token }); }, { openrouterKey: 'optional-configured' });
  for (const path of ['transcribe', 'conversation', 'speech']) {
    const response = await fetch(`${base}/api/avatar/${path}`, { method: 'POST', headers: { Origin: base, Cookie: cookie, 'Content-Type': 'application/json' }, body: '{}' });
    assert.equal(response.status, 503);
    assert.equal((await response.json()).code, 'voice_unconfigured');
  }
  assert.equal(calls, 0);
  assert.equal((await request()).status, 200);
});

test('native provider failures and invalid token responses are sanitized, including body-read deadlines', async t => {
  for (const [status, code] of [[429, 'voice_rate_limited'], [403, 'voice_provider_configuration'], [500, 'voice_unavailable']]) {
    const f = await fixture(t, async () => Response.json({ error: { message: key, details: [key], status: status === 429 ? 'RESOURCE_EXHAUSTED' : undefined } }, { status }));
    const response = await f.request();
    assert.equal((await response.json()).code, code);
  }
  for (const name of [key, 'https://attacker.example/token', 'auth_tokens/bad\nvalue', 'auth_tokens/' + 'x'.repeat(17000)]) {
    const f = await fixture(t, async () => Response.json({ name, diagnostic: key }));
    const response = await f.request();
    assert.equal(response.status, 502);
    const value = await response.text();
    assert.ok(!value.includes(key));
    assert.ok(value.includes('invalid_upstream_response'));
  }
  const stalled = await fixture(t, async (_url, { signal }) => new Response(new ReadableStream({ start(controller) {
    signal.addEventListener('abort', () => controller.error(new Error(key)), { once: true });
  } })), { realtimeTimeoutMs: 15 });
  const timeout = await stalled.request();
  assert.equal(timeout.status, 504);
  assert.equal((await timeout.json()).code, 'voice_timeout');
});

test('native token issuance shares bounded starts and abort releases scarce handshake capacity', async t => {
  const limited = await fixture(t, async () => Response.json({ name: token }), { realtimeRateLimit: 1 });
  assert.equal((await limited.request()).status, 200);
  assert.equal((await limited.request()).status, 429);
  let calls = 0;
  const stalled = await fixture(t, async (_url, { signal }) => {
    calls++;
    if (calls === 1) return new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true }));
    return Response.json({ name: token });
  }, { realtimeTimeoutMs: 15, maxRealtimeStarts: 1 });
  assert.equal((await stalled.request()).status, 504);
  assert.equal((await stalled.request()).status, 200);
});

test('public native voice requires the operator access gate while remaining independent from bank login', async t => {
  const gate = 'trusted-ingress-sentinel-value-123456789';
  const config = readConfig({ NODE_ENV: 'production', GEMINI_API_KEY: key, AVATAR_PUBLIC_ORIGIN: 'https://avatar.example', AVATAR_ACCESS_GATE_TOKEN: gate });
  let calls = 0;
  const server = createAvatarServer({ config, fetchImpl: async () => { calls++; return Response.json({ name: token }); } });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const base = `http://127.0.0.1:${server.address().port}`;
  const blockedConfig = await fetch(`${base}/api/avatar/config`);
  assert.equal(blockedConfig.status, 401);
  const configured = await fetch(`${base}/api/avatar/config`, { headers: { 'X-Avatar-Gateway-Token': gate } });
  assert.equal(configured.status, 200);
  const cookie = configured.headers.getSetCookie()[0].split(';')[0];
  assert.ok(configured.headers.getSetCookie()[0].includes('; Secure'));
  for (const supplied of ['', 'attacker']) {
    const response = await fetch(`${base}/api/avatar/gemini-token`, { method: 'POST', headers: { Origin: base, Cookie: cookie, 'Content-Type': 'application/json', 'X-Avatar-Gateway-Token': supplied }, body: '{"avatar":"moss"}' });
    assert.equal(response.status, 401);
  }
  assert.equal(calls, 0);
  const allowed = await fetch(`${base}/api/avatar/gemini-token`, { method: 'POST', headers: { Origin: 'https://avatar.example', Cookie: cookie, 'Content-Type': 'application/json', 'X-Avatar-Gateway-Token': gate }, body: '{"avatar":"moss"}' });
  assert.equal(allowed.status, 200);
  assert.equal(calls, 1);
});
