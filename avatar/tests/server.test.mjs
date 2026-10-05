import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer, request as httpRequest } from 'node:http';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createAvatarServer } from '../server/app.mjs';
import { readConfig } from '../server/config.mjs';
import { BANK_COOKIE } from '../server/savia.mjs';
import { realtimeSession } from '../server/realtime.mjs';

const offer = 'v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n';

test('Realtime locale is constrained before dispatch and Portuguese reaches the authoritative session', async t => {
  let calls = 0;
  const { request } = await fixture(t, { openaiKey: 'locale-server-only-key', realtimeRateLimit: 30 }, async (_url, options) => {
    calls++;
    const session = JSON.parse(options.body.get('session'));
    assert.match(session.instructions, /Converse sempre em português do Brasil/);
    assert.match(session.instructions, /read-only/);
    return new Response(offer, { headers: { 'Content-Type': 'application/sdp' } });
  });
  const options = { method: 'POST', headers: { 'Content-Type': 'application/sdp' }, body: offer };
  for (const query of ['locale=en', 'locale=pt-BR', 'locale=pt&locale=es', 'locale=pt&instructions=override']) {
    assert.equal((await request(`/api/avatar/realtime?avatar=moss&${query}`, options)).status, 400);
  }
  assert.equal(calls, 0);
  assert.equal((await request('/api/avatar/realtime?avatar=moss&locale=pt', options)).status, 201);
  assert.equal(calls, 1);
});

async function listen(server) {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return `http://127.0.0.1:${server.address().port}`;
}
async function stop(server) {
  server.closeAllConnections();
  await new Promise(resolve => server.close(resolve));
}
async function fixture(t, overrides = {}, fetchImpl) {
  const config = { ...readConfig({ NODE_ENV: 'test', OPENAI_API_KEY: overrides.openaiKey }), ...overrides };
  const server = createAvatarServer({ config, ...(fetchImpl ? { fetchImpl } : {}) });
  const base = await listen(server);
  t.after(() => stop(server));
  const configResponse = await fetch(`${base}/api/avatar/config`);
  const cookie = configResponse.headers.getSetCookie()[0]?.split(';')[0];
  const request = (path, options = {}) => fetch(`${base}${path}`, {
    ...options,
    headers: { Origin: base, Cookie: cookie, ...options.headers },
  });
  return { server, config, base, cookie, request, configResponse };
}

test('demo config reports configured capabilities honestly and never serializes a key', async t => {
  const { configResponse, request } = await fixture(t);
  assert.equal(configResponse.status, 200);
  assert.deepEqual(await configResponse.json(), {
    voiceAvailable: false, voiceProvider: 'none', backgroundAsrAvailable: false, nativeReadBridgeAvailable: false, backendAvailable: false, saviaUrl: '', mode: 'demo', realtimeModel: 'gpt-realtime-2.1', geminiModel: 'gemini-3.8-live',
  });
  const response = await request('/api/avatar/realtime', { method: 'POST', headers: { 'Content-Type': 'application/sdp' }, body: offer });
  assert.equal(response.status, 503);
  assert.equal((await response.json()).code, 'voice_unconfigured');
});

test('mutation origin and local Host checks reject browser cross-site requests and DNS rebinding', async t => {
  const { request, base } = await fixture(t);
  for (const headers of [{ Origin: 'https://attacker.example' }, { Origin: '' }, { 'Sec-Fetch-Site': 'cross-site' }]) {
    const response = await request('/api/avatar/task', { method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: '{"message":"hello"}' });
    assert.equal(response.status, 403);
  }
  const status = await new Promise((resolve, reject) => {
    const req = httpRequest(`${base}/api/avatar/config`, { headers: { Host: 'attacker.example' } }, res => { res.resume(); resolve(res.statusCode); });
    req.on('error', reject); req.end();
  });
  assert.equal(status, 403);
});

test('operator voice selection prevents paid OpenAI dispatch with a configured inactive key', async t => {
  let calls = 0;
  for (const voiceProvider of ['none', 'gemini-live', 'openrouter']) {
    const { request } = await fixture(t, { openaiKey: 'private-configured-key', voiceProvider }, async () => { calls++; return new Response(offer); });
    const response = await request('/api/avatar/realtime', { method: 'POST', headers: { 'Content-Type': 'application/sdp' }, body: offer });
    assert.equal(response.status, 503);
    assert.equal((await response.json()).code, 'voice_unconfigured');
  }
  assert.equal(calls, 0);
});

test('Realtime forwards multipart fixed GA session, returns SDP, and keeps API credentials server-side', async t => {
  const sentinel = 'server-only-realtime-sentinel';
  let calls = 0;
  const upstream = async (url, options) => {
    calls++;
    assert.equal(url, 'https://api.openai.com/v1/realtime/calls');
    assert.equal(options.headers.Authorization, `Bearer ${sentinel}`);
    assert.equal(options.redirect, 'manual');
    assert.equal(options.body.get('sdp'), offer);
    const session = JSON.parse(options.body.get('session'));
    assert.equal(session.type, 'realtime');
    assert.equal(session.model, 'gpt-realtime-2.1');
    assert.deepEqual(session.audio.input.turn_detection, { type: 'semantic_vad', eagerness: 'high', create_response: true, interrupt_response: true });
    assert.deepEqual(session.tools.map(tool => tool.name), ['set_world', 'delegate_task']);
    assert.equal(session.audio.output.voice, 'cedar');
    assert.deepEqual(session.tools[1].parameters.required, ['message']);
    return new Response(offer, { status: 201, headers: { 'Content-Type': 'application/sdp' } });
  };
  const { request, configResponse } = await fixture(t, { openaiKey: sentinel }, upstream);
  assert.ok(!(await configResponse.text()).includes(sentinel));
  const response = await request('/api/avatar/realtime?avatar=spark', { method: 'POST', headers: { 'Content-Type': 'application/sdp' }, body: offer });
  assert.equal(response.status, 201);
  assert.equal(response.headers.get('content-type'), 'application/sdp');
  assert.equal(await response.text(), offer);
  assert.equal(calls, 1);
});

test('Realtime rejects missing app sessions, invalid SDP, extra model selectors and invalid avatars before provider dispatch', async t => {
  let calls = 0;
  const { request, base } = await fixture(t, { openaiKey: 'not-printed', realtimeRateLimit: 20 }, async () => { calls++; return new Response(offer); });
  const anonymous = await fetch(`${base}/api/avatar/realtime`, { method: 'POST', headers: { Origin: base, 'Content-Type': 'application/sdp' }, body: offer });
  assert.equal(anonymous.status, 401);
  for (const [path, body] of [['/api/avatar/realtime?avatar=evil', offer], ['/api/avatar/realtime?model=evil', offer], ['/api/avatar/realtime?avatar=moss&avatar=spark', offer], ['/api/avatar/realtime', 'not SDP']]) {
    const response = await request(path, { method: 'POST', headers: { 'Content-Type': 'application/sdp' }, body });
    assert.equal(response.status, 400);
  }
  const response = await request('/api/avatar/realtime', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sdp: offer }) });
  assert.equal(response.status, 415);
  assert.equal(calls, 0);
});

test('provider errors are sanitized and timeouts include response-body reads', async t => {
  const secret = 'private-credential-upstream-diagnostic';
  const failed = await fixture(t, { openaiKey: secret }, async () => new Response(secret, { status: 401 }));
  const denied = await failed.request('/api/avatar/realtime', { method: 'POST', headers: { 'Content-Type': 'application/sdp' }, body: offer });
  assert.equal(denied.status, 502);
  assert.ok(!(await denied.text()).includes(secret));
  const quotaFixture = await fixture(t, { openaiKey: secret }, async () => Response.json({ error: { code: 'credit_balance_exhausted', type: 'insufficient_quota', message: secret } }, { status: 429 }));
  const quota = await quotaFixture.request('/api/avatar/realtime', { method: 'POST', headers: { 'Content-Type': 'application/sdp' }, body: offer });
  assert.equal(quota.status, 503);
  const quotaError = await quota.json();
  assert.equal(quotaError.code, 'voice_quota_exhausted');
  assert.ok(quotaError.error.includes('Text and Savia still work'));
  assert.ok(!JSON.stringify(quotaError).includes(secret));
  const stalled = await fixture(t, { openaiKey: secret, realtimeTimeoutMs: 15 }, async (_url, { signal }) => new Response(new ReadableStream({
    start(controller) { signal.addEventListener('abort', () => controller.error(new Error(secret)), { once: true }); },
  }), { status: 201 }));
  const timeout = await stalled.request('/api/avatar/realtime', { method: 'POST', headers: { 'Content-Type': 'application/sdp' }, body: offer });
  assert.equal(timeout.status, 504);
  assert.equal((await timeout.json()).code, 'voice_timeout');
});

test('request body caps apply before provider work and general API limits are bounded', async t => {
  let calls = 0;
  const { request } = await fixture(t, { openaiKey: 'not-printed', rateLimit: 4 }, async () => { calls++; return new Response(offer); });
  const large = await request('/api/avatar/realtime', { method: 'POST', headers: { 'Content-Type': 'application/sdp' }, body: 'x'.repeat(65 * 1024) });
  assert.equal(large.status, 413);
  await request('/api/avatar/config');
  await request('/api/avatar/config');
  const limited = await request('/api/avatar/config');
  assert.equal(limited.status, 429);
  assert.equal(calls, 0);
});

test('Savia proxy preserves auth, rewrites only known surfaces, and delegated tasks project public fields', async t => {
  const bankToken = 'b'.repeat(43);
  const events = [];
  const fake = createServer(async (req, res) => {
    let body = '';
    for await (const chunk of req) body += chunk;
    events.push({ path: req.url, headers: req.headers, body });
    res.setHeader('X-Frame-Options', 'DENY');
    res.setHeader('Content-Security-Policy', "default-src 'self'; frame-ancestors 'none'");
    if (req.url === '/') {
      res.setHeader('Content-Type', 'text/html'); res.end('<script src="/assets/app.js"></script><link href="/favicon.svg">'); return;
    }
    if (req.url === '/assets/app.js') {
      res.setHeader('Content-Type', 'text/javascript'); res.end('fetch("/api/auth/me"); fetch(`/api/transactions?offset=${x}`);'); return;
    }
    if (req.url === '/api/auth/login') {
      res.setHeader('Set-Cookie', [`${BANK_COOKIE}=${bankToken}; Path=/; HttpOnly; SameSite=Strict`, 'worker_control=must-never-forward; Path=/']);
      res.setHeader('Content-Type', 'application/json'); res.end('{"authenticated":true}'); return;
    }
    if (req.url === '/api/auth/logout') {
      res.setHeader('Set-Cookie', `${BANK_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict`);
      res.writeHead(204, { 'X-Banking-Revoke': 'confirmed' }); res.end(); return;
    }
    if (req.url === '/api/chat') {
      if (req.headers.cookie !== `${BANK_COOKIE}=${bankToken}`) { res.writeHead(401); res.end('private details should not leak'); return; }
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify({ reply: 'An authenticated read-only result.', mode: 'flujo', status: 'completed', customer_id: 'private', conversation_id: 'private', token: 'private' })); return;
    }
    res.writeHead(404); res.end();
  });
  const upstream = await listen(fake); t.after(() => stop(fake));
  const { request } = await fixture(t, { saviaUpstream: upstream, saviaOrigin: 'http://localhost:43800' });
  const configResponse = await request('/api/avatar/config');
  assert.equal((await configResponse.json()).saviaUrl, '/savia/');
  const page = await request('/savia/');
  assert.equal(page.headers.get('x-frame-options'), 'SAMEORIGIN');
  assert.ok(page.headers.get('content-security-policy').includes("frame-ancestors 'self'"));
  assert.equal(await page.text(), '<script src="/savia/assets/app.js"></script><link href="/savia/favicon.svg">');
  const bundle = await request('/savia/assets/app.js');
  assert.equal(await bundle.text(), 'fetch("/savia/api/auth/me"); fetch(`/savia/api/transactions?offset=${x}`);');
  const anonymous = await request('/api/avatar/task', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"message":"check"}' });
  assert.equal(anonymous.status, 401);
  const login = await request('/savia/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer caller-must-not-pass', 'X-Flujo-Workspace': 'evil' }, body: '{"profile":"demo","code":"test-only"}' });
  const setCookie = login.headers.getSetCookie();
  assert.equal(setCookie.length, 1);
  assert.ok(setCookie[0].includes('Path=/savia'));
  assert.ok(setCookie[0].includes('HttpOnly'));
  assert.ok(!setCookie[0].includes('worker_control'));
  const result = await request('/api/avatar/task', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"message":" check "}' });
  assert.equal(result.status, 200);
  assert.deepEqual(await result.json(), { reply: 'An authenticated read-only result.', mode: 'flujo', status: 'completed' });
  const sent = events.find(event => event.path === '/api/chat');
  assert.deepEqual(JSON.parse(sent.body), { message: 'check' });
  assert.equal(sent.headers.origin, 'http://localhost:43800');
  assert.equal(sent.headers['sec-fetch-site'], 'same-origin');
  assert.equal(sent.headers.cookie, `${BANK_COOKIE}=${bankToken}`);
  assert.ok(!events.some(event => event.headers.authorization || event.headers['x-flujo-workspace']));
  const logout = await request('/savia/api/auth/logout', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  assert.equal(logout.status, 204);
  assert.equal(logout.headers.get('x-banking-revoke'), 'confirmed');
  const afterLogout = await request('/api/avatar/task', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"message":"check"}' });
  assert.equal(afterLogout.status, 401);
});

test('client IDs, foreign conversation selectors, unapproved routes, and traversal never dispatch upstream', async t => {
  let calls = 0;
  const { request } = await fixture(t, { saviaUpstream: 'http://127.0.0.1:43800', saviaOrigin: 'http://127.0.0.1:43800' }, async () => { calls++; return new Response('{}'); });
  for (const payload of [{ message: 'hello', customer_id: 'foreign' }, { message: 'hello', conversationId: 'foreign' }, { message: 'hello', model: 'foreign' }, { message: '' }, { message: 'x'.repeat(4001) }, { role: 'assistant', message: 'hello' }]) {
    for (const path of ['/api/avatar/task', '/savia/api/chat', '/savia/api/chat/messages']) {
      const response = await request(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      assert.equal(response.status, 400);
    }
  }
  for (const transaction_reference of ['foreign-customer-reference', ['txn_' + 'a'.repeat(24)]]) {
    const invalidReference = await request('/savia/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: 'check', transaction_reference }) });
    assert.equal(invalidReference.status, 400);
  }
  for (const path of ['/savia/api/admin', '/savia/v1/chat/completions', '/savia/api/actions/execute', '/api/chat', '/savia/assets/%2e%2e/private', '/savia/assets/a%2fb.js', '/savia/assets/.env', '/savia/assets/private.key']) {
    const response = await request(path);
    assert.ok([400, 404].includes(response.status));
  }
  assert.equal(calls, 0);
});

test('an authenticated cookie is revalidated by Savia; failure bodies are never disclosed', async t => {
  const bankToken = 'c'.repeat(43);
  const secret = 'upstream-secret';
  const { request, cookie } = await fixture(t, { saviaUpstream: 'http://127.0.0.1:43800', saviaOrigin: 'http://127.0.0.1:43800' }, async () => new Response(secret, { status: 401 }));
  const unauthorized = await request('/savia/api/auth/me', { headers: { Cookie: `${cookie}; ${BANK_COOKIE}=${bankToken}` } });
  assert.equal(unauthorized.status, 401);
  assert.ok(!(await unauthorized.text()).includes(secret));
  const denied = await request('/api/avatar/task', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"message":"check"}' });
  assert.equal(denied.status, 401);
  assert.ok(!(await denied.text()).includes(secret));
});

test('concurrent submissions share a bank-session admission limit and cannot duplicate work', async t => {
  const bankToken = 'd'.repeat(43);
  let unblock;
  let entered;
  const reached = new Promise(resolve => { entered = resolve; });
  const blocked = new Promise(resolve => { unblock = resolve; });
  t.after(() => unblock());
  let calls = 0;
  const { request, cookie } = await fixture(t, { saviaUpstream: 'http://127.0.0.1:43800', saviaOrigin: 'http://127.0.0.1:43800' }, async url => {
    if (url.endsWith('/api/auth/me')) return Response.json({ authenticated: true });
    calls++; entered(); await blocked;
    return Response.json({ reply: 'done', mode: 'flujo', status: 'completed' });
  });
  await request('/savia/api/auth/me', { headers: { Cookie: `${cookie}; ${BANK_COOKIE}=${bankToken}` } });
  const first = request('/api/avatar/task', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"message":"first"}' });
  await reached;
  const second = await request('/savia/api/chat/messages', { method: 'POST', headers: { 'Content-Type': 'application/json', Cookie: `${cookie}; ${BANK_COOKIE}=${bankToken}` }, body: '{"message":"second"}' });
  assert.equal(second.status, 409);
  assert.equal(calls, 1);
  unblock();
  assert.equal((await first).status, 200);
});

test('production public listeners require a fixed origin and trusted access gate, separately from bank auth', async t => {
  assert.throws(() => readConfig({ AVATAR_HOST: '0.0.0.0' }), /non-loopback/);
  assert.throws(() => readConfig({ AVATAR_HOST: '0.0.0.0', AVATAR_ALLOW_PUBLIC_BIND: 'true', AVATAR_PUBLIC_ORIGIN: 'http://example.com' }), /Invalid/);
  assert.throws(() => readConfig({ AVATAR_PUBLIC_ORIGIN: 'https://avatar.example.com' }), /access|AVATAR_ACCESS_GATE_TOKEN/);
  const gate = 'trusted-gateway-test-only-token-0000000000';
  const config = readConfig({ AVATAR_PUBLIC_ORIGIN: 'https://avatar.example.com', AVATAR_ACCESS_GATE_TOKEN: gate, OPENAI_API_KEY: 'test-key', NODE_ENV: 'production' });
  const { request } = await fixture(t, config, async () => new Response(offer, { status: 201 }));
  const anonymous = await request('/api/avatar/config');
  assert.equal(anonymous.status, 401);
  const admitted = await request('/api/avatar/config', { headers: { 'X-Avatar-Gateway-Token': gate } });
  assert.equal(admitted.status, 200);
  const cookie = admitted.headers.getSetCookie()[0].split(';')[0];
  assert.ok(admitted.headers.getSetCookie()[0].includes('Secure'));
  const voice = await request('/api/avatar/realtime', { method: 'POST', headers: { Cookie: cookie, 'Content-Type': 'application/sdp', 'X-Avatar-Gateway-Token': gate }, body: offer });
  assert.equal(voice.status, 201);
});

test('static files are confined to the built frontend and unknown API routes stay closed', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'avatar-server-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  await mkdir(join(directory, 'assets'));
  await writeFile(join(directory, 'index.html'), '<h1>avatar</h1>');
  await writeFile(join(directory, 'assets', 'main.js'), 'console.log("asset");');
  await writeFile(join(directory, '.env'), 'private-file-sentinel');
  await writeFile(join(directory, 'gemini.env'), 'private-file-sentinel');
  const { request } = await fixture(t, { staticDir: directory });
  const page = await request('/');
  assert.equal(page.status, 200);
  assert.equal(await page.text(), '<h1>avatar</h1>');
  assert.ok(page.headers.get('content-security-policy').includes("frame-src 'self'"));
  const deep = await request('/experience');
  assert.equal(deep.status, 200);
  const missing = await request('/assets/missing.js');
  assert.equal(missing.status, 404);
  const unknown = await request('/api/unknown');
  assert.equal(unknown.status, 404);
  for (const path of ['/.env', '/gemini.env', '/.private/index', '/OPENROUTER.ENV']) {
    const hidden = await request(path);
    assert.equal(hidden.status, 404);
    assert.ok(!(await hidden.text()).includes('private-file-sentinel'));
  }
});

test('session tools are constrained schemas without banking identity or action arguments', () => {
  for (const avatar of ['moss', 'orbit', 'spark']) {
    const session = realtimeSession(avatar, 'gpt-realtime-2.1');
    assert.equal(session.tools.every(tool => tool.parameters.additionalProperties === false), true);
    assert.deepEqual(Object.keys(session.tools[1].parameters.properties), ['message']);
    assert.ok(session.instructions.includes('read-only'));
  }
});

test('logout failure still disables cached local delegation and refuses stale cookie rebinding', async t => {
  const bankToken = 'f'.repeat(43);
  const cookies = [];
  const { request, cookie } = await fixture(t, { saviaUpstream: 'http://127.0.0.1:43800', saviaOrigin: 'http://127.0.0.1:43800' }, async (url, options) => {
    cookies.push(options.headers.Cookie);
    if (url.endsWith('/api/auth/logout')) return new Response('private detail', { status: 503 });
    return options.headers.Cookie ? Response.json({ authenticated: true }) : new Response('{}', { status: 401 });
  });
  await request('/savia/api/auth/me', { headers: { Cookie: `${cookie}; ${BANK_COOKIE}=${bankToken}` } });
  const logout = await request('/savia/api/auth/logout', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  assert.equal(logout.status, 502);
  assert.ok(logout.headers.getSetCookie().some(value => value.includes('Path=/savia') && value.includes('Max-Age=0')));
  const stale = await request('/savia/api/auth/me', { headers: { Cookie: `${cookie}; ${BANK_COOKIE}=${bankToken}` } });
  assert.equal(stale.status, 401);
  assert.equal(cookies.at(-1), undefined);
  const task = await request('/api/avatar/task', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"message":"check"}' });
  assert.equal(task.status, 401);
});

test('installed Savia anonymous integration remains protected behind the actual proxy', {
  skip: !process.env.AVATAR_TEST_SAVIA_UPSTREAM,
}, async t => {
  const upstream = process.env.AVATAR_TEST_SAVIA_UPSTREAM;
  const { request } = await fixture(t, { saviaUpstream: upstream, saviaOrigin: process.env.AVATAR_TEST_SAVIA_ORIGIN || upstream });
  const page = await request('/savia/');
  assert.equal(page.status, 200);
  const html = await page.text();
  const bundle = html.match(/src="(\/savia\/assets\/[^" ]+\.js)"/);
  assert.ok(bundle, 'The installed compiled Savia bundle should be under the proxy asset prefix.');
  const script = await request(bundle[1]);
  assert.equal(script.status, 200);
  const code = await script.text();
  assert.ok(code.includes('/savia/api/auth/me'));
  assert.ok(code.includes('/savia/api/chat/messages'));
  const profiles = await request('/savia/api/auth/profiles');
  assert.equal(profiles.status, 200);
  assert.ok(Array.isArray((await profiles.json()).profiles));
  for (const path of ['/savia/api/auth/me', '/savia/api/overview', '/savia/api/chat/history']) {
    const response = await request(path);
    assert.equal(response.status, 401, `Anonymous ${path} must remain unauthorized.`);
  }
  const task = await request('/api/avatar/task', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"message":"hello"}' });
  assert.equal(task.status, 401);
});

test('portal scope and language stay in the cookie-owned proxy, while follow-up routes admit only language', async t => {
  const calls = [];
  const { request } = await fixture(t, { saviaUpstream: 'http://127.0.0.1:43800', saviaOrigin: 'http://127.0.0.1:43800' }, async (url, options) => {
    calls.push({ url, body: options.body ? JSON.parse(Buffer.from(options.body).toString()) : undefined });
    return new Response(JSON.stringify({ items: [] }), { headers: { 'Content-Type': 'application/json' } });
  });
  const post = (path, body) => request(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const body = { message: 'Revisa este cargo.', language: 'pt', transaction_reference: 'txn_' + 'a'.repeat(24), query_scope_id: 'q_' + 'b'.repeat(32) };
  assert.equal((await post('/savia/api/chat', body)).status, 200); assert.deepEqual(calls.at(-1).body, body);
  for (const extra of [{ language: 'en' }, { query_scope_id: 'private_id' }, { customer_id: 'forged' }])
    assert.equal((await post('/savia/api/chat', { ...body, ...extra })).status, 400);
  for (const path of ['/savia/api/followups', '/savia/api/followups/check']) {
    assert.equal((await post(path, { language: 'es' })).status, 200);
    assert.equal((await post(path, { language: 'es', receipt_id: 'forged' })).status, 400);
  }
  assert.equal((await request('/savia/api/followups?language=pt')).status, 200);
  assert.equal((await request('/savia/api/action/status?language=es')).status, 200);
  assert.equal((await post('/savia/api/action/confirm', { language: 'es' })).status, 404);
  assert.equal(calls.length, 5);
});

test('informational inquiry routes admit bounded intake and explicit guidance acceptance without bank action routes', async t => {
  const calls = [];
  const { request } = await fixture(t, { saviaUpstream: 'http://127.0.0.1:43800', saviaOrigin: 'http://127.0.0.1:43800' }, async (url, options) => {
    calls.push({ url, body: options.body ? JSON.parse(Buffer.from(options.body).toString()) : undefined });
    return Response.json({ items: [] });
  });
  const post = (path, body) => request(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const intake = { message: 'Exploren dos perspectivas sobre mi cargo.', language: 'es', transaction_reference: 'txn_' + 'a'.repeat(24) };
  assert.equal((await post('/savia/api/assistant/cases', intake)).status, 200);
  assert.deepEqual(calls.at(-1).body, intake);
  for (const extra of [{ facts: {} }, { message: 'x'.repeat(1001) }, { language: 'en' }, { transaction_reference: 7 }])
    assert.equal((await post('/savia/api/assistant/cases', { ...intake, ...extra })).status, 400);
  assert.equal((await request('/savia/api/assistant/cases?language=pt')).status, 200);
  const resolve = '/savia/api/assistant/cases/i_' + 'b'.repeat(32) + '/resolve';
  assert.equal((await post(resolve, { resolved: true })).status, 200);
  for (const body of [{ resolved: false }, { resolved: true, bank_authority: true }]) assert.equal((await post(resolve, body)).status, 400);
  assert.equal((await post(resolve + '?override=1', { resolved: true })).status, 400);
  assert.equal((await post('/savia/api/assistant/cases/private/resolve', { resolved: true })).status, 404);
  assert.equal((await post('/savia/api/action/confirm', { language: 'es' })).status, 404);
  assert.equal(calls.length, 3);
});
