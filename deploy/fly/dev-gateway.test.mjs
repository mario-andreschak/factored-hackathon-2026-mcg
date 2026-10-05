import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import net from 'node:net';
import { once } from 'node:events';
import { createHash } from 'node:crypto';
import { createDevGateway, readDevConfig } from './dev-gateway.mjs';

const MAIN = 'flujo-example.fly.dev';
const HOST = 'flujo-dev-example.fly.dev';
const ORIGIN = `https://${HOST}`;
const TEST_NOW = Date.parse('2026-09-30T12:00:00.000Z');
const DEADLINE = '2026-10-16T05:00:00.000Z';
const MARIO = 'synthetic-mario-password-at-least-24';
const GLORIA = 'synthetic-gloria-password-at-least-24';
const TOKEN = 'synthetic-worker-control-token';
const env = { FLUJO_DEV_UI_ENABLED: '1', FLUJO_DEV_UI_HOST: HOST, FLUJO_DEV_UI_EXPIRES_AT: DEADLINE,
  FLUJO_DEV_UI_MARIO_PASSWORD: MARIO, FLUJO_DEV_UI_GLORIA_PASSWORD: GLORIA,
  FLUJO_SNAPSHOT_CONTROL_TOKEN: TOKEN };
const config = readDevConfig(env);
const listen = async server => { server.listen(0, '127.0.0.1'); await once(server, 'listening'); return server.address().port; };

async function fixture(t, { handler, now = () => TEST_NOW, expiresAt = DEADLINE } = {}) {
  const requests = [], wsRequests = [], sockets = new Set();
  const upstream = http.createServer(async (req, res) => {
    const chunks = []; for await (const chunk of req) chunks.push(chunk);
    requests.push({ url: req.url, headers: req.headers, body: Buffer.concat(chunks).toString('utf8') });
    if (handler) handler(req, res); else res.end('private worker response');
  });
  upstream.on('upgrade', (req, socket, head) => {
    wsRequests.push({ url: req.url, headers: req.headers });
    if (req.headers.authorization !== `Bearer ${TOKEN}`) {
      socket.end('HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'); return;
    }
    const accept = createHash('sha1').update(req.headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
    socket.write(`HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
    if (head.length) socket.write(head); socket.on('data', chunk => socket.write(chunk));
  });
  const upstreamPort = await listen(upstream);
  const server = createDevGateway(readDevConfig({ ...env, FLUJO_DEV_UI_EXPIRES_AT: expiresAt }), { upstreamPort, now });
  for (const item of [upstream, server]) item.on('connection', socket => { sockets.add(socket); socket.on('close', () => sockets.delete(socket)); });
  const port = await listen(server);
  t.after(async () => {
    for (const socket of sockets) socket.destroy();
    await Promise.all([server, upstream].map(item => new Promise(resolve => { item.close(resolve); item.closeAllConnections(); })));
  });
  return { port, server, requests, wsRequests };
}
function request(port, pathname = '/', { method = 'GET', headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request({ hostname: '127.0.0.1', port, path: pathname, method, headers: { Host: HOST, ...headers } }, res => {
      const chunks = []; res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks).toString('utf8') }));
    }); req.on('error', reject); req.end(body);
  });
}
const login = (port, username = 'mario', password = username === 'gloria' ? GLORIA : MARIO, next = '/') => request(port,
  `/_dev/login?next=${encodeURIComponent(next)}`, { method: 'POST', headers: { Origin: ORIGIN,
    'Content-Type': 'application/x-www-form-urlencoded', 'Sec-Fetch-Site': 'same-origin' },
  body: new URLSearchParams({ username, password }).toString() });
const cookieOf = response => response.headers['set-cookie'][0].split(';')[0];
const authenticated = (port, cookie, pathname = '/api/models', options = {}) => request(port, pathname,
  { ...options, headers: { Cookie: cookie, Origin: ORIGIN, ...options.headers } });

function websocket(port, { cookie, origin = ORIGIN, authorization, host = HOST, keepOpen = false } = {}) {
  return new Promise((resolve, reject) => {
    const socket = net.connect(port, '127.0.0.1'); let output = '';
    const timeout = setTimeout(() => { socket.destroy(); reject(new Error('Synthetic upgrade timed out')); }, 3000);
    socket.on('connect', () => {
      const lines = ['GET /runtime/ws HTTP/1.1', `Host: ${host}`, 'Connection: Upgrade', 'Upgrade: websocket',
        'Sec-WebSocket-Version: 13', 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ=='];
      if (cookie) lines.push(`Cookie: ${cookie}`);
      if (origin !== undefined) lines.push(`Origin: ${origin}`);
      if (authorization !== undefined) lines.push(`Authorization: ${authorization}`);
      socket.write(lines.join('\r\n') + '\r\n\r\n' + (keepOpen ? '' : 'synthetic echo'));
    });
    socket.on('data', chunk => {
      output += chunk;
      if (output.includes('synthetic echo') || /^HTTP\/1\.1 (401|403|410)/.test(output) || (keepOpen && output.includes('\r\n\r\n'))) {
        clearTimeout(timeout); if (!keepOpen) socket.destroy(); resolve({ output, socket });
      }
    });
    socket.on('error', error => { clearTimeout(timeout); reject(error); });
    socket.on('end', () => { clearTimeout(timeout); resolve({ output, socket }); });
  });
}

test('startup fails closed without explicit enablement, distinct strong accounts and worker auth', () => {
  for (const override of [{ FLUJO_DEV_UI_ENABLED: '' }, { FLUJO_DEV_UI_MARIO_PASSWORD: 'short' },
    { FLUJO_DEV_UI_GLORIA_PASSWORD: MARIO }, { FLUJO_SNAPSHOT_CONTROL_TOKEN: '' },
    { FLUJO_DEV_UI_HOST: undefined }, { FLUJO_DEV_UI_HOST: `https://${HOST}` }, { FLUJO_DEV_UI_HOST: `${HOST}:8443` },
    { FLUJO_DEV_UI_HOST: 'evil.test' }, { FLUJO_DEV_UI_EXPIRES_AT: undefined },
    { FLUJO_DEV_UI_EXPIRES_AT: 'forever' }, { FLUJO_DEV_UI_EXPIRES_AT: '2026-10-16' }]) {
    assert.throws(() => readDevConfig({ ...env, ...override }), error => ![MARIO, GLORIA, TOKEN].some(value => error.message.includes(value)));
  }
  assert.equal(config.host, HOST);
});

test('every anonymous worker API, source and data route is gated; browser navigation reaches sign-in', async t => {
  const f = await fixture(t);
  for (const pathname of ['/', '/api/flow', '/api/models', '/api/env', '/_next/static/chunk.js', '/v1/models', '/mcp', '/data/file']) {
    assert.equal((await request(f.port, pathname)).status, 401);
  }
  assert.equal((await request(f.port, '/api/flow', { headers: { Authorization: `Bearer ${TOKEN}` } })).status, 401);
  const browser = await request(f.port, '/?workspace=default-workspace', { headers: { Accept: 'text/html' } });
  assert.equal(browser.status, 303); assert.match(browser.headers.location, /^\/_dev\/login\?next=/);
  assert.equal(f.requests.length, 0);
});

test('only the exact development authority is accepted', async t => {
  const f = await fixture(t);
  for (const host of [MAIN, `${MAIN}:443`, `${MAIN}:8443`, `${HOST}:8443`, `evil.test`, `evil@${HOST}`, `${HOST}.evil`]) {
    assert.equal((await request(f.port, '/_dev/login', { headers: { Host: host } })).status, 421);
  }
  assert.equal((await request(f.port, '//evil.test/path')).status, 400);
  assert.equal(f.requests.length, 0);
});

test('both accounts get separate secure signed sessions; native login and failed retry use same-origin policy', async t => {
  const f = await fixture(t);
  const page = await request(f.port, '/_dev/login', { headers: { 'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate' } });
  assert.equal(page.status, 200); assert.equal(page.headers['referrer-policy'], 'same-origin');
  assert.match(page.body, /Live Fly development/); assert.match(page.headers['content-security-policy'], /form-action 'self'/);
  const failed = await login(f.port, 'mario', 'incorrect');
  assert.equal(failed.status, 401); assert.equal(failed.headers['referrer-policy'], 'same-origin');
  const mario = await login(f.port), gloria = await login(f.port, 'gloria');
  for (const response of [mario, gloria]) {
    assert.equal(response.status, 303);
    assert.match(response.headers['set-cookie'][0], /^__Host-flujo-live-dev-session=.*; Path=\/; Max-Age=43200; HttpOnly; Secure; SameSite=Strict$/);
    assert.doesNotMatch(response.headers['set-cookie'][0], /Domain=/);
    assert.ok(![MARIO, GLORIA, TOKEN].some(value => response.headers['set-cookie'][0].includes(value)));
    assert.equal((await authenticated(f.port, cookieOf(response))).status, 200);
  }
  assert.notEqual(cookieOf(mario), cookieOf(gloria));
});

test('login rejects missing, null, foreign, main-port and cross-site origins without cookies', async t => {
  const f = await fixture(t);
  for (const headers of [{}, { Origin: 'null' }, { Origin: `https://${MAIN}` }, { Origin: 'https://evil.test' },
    { Origin: ORIGIN, 'Sec-Fetch-Site': 'same-site' }, { Origin: ORIGIN, Referer: `https://${MAIN}/` }]) {
    const response = await request(f.port, '/_dev/login', { method: 'POST', headers: {
      'Content-Type': 'application/x-www-form-urlencoded', ...headers },
    body: new URLSearchParams({ username: 'mario', password: MARIO }).toString() });
    assert.equal(response.status, 403); assert.equal(response.headers['set-cookie'], undefined);
  }
  for (const next of ['//evil.test', '/\\evil.test', '/_dev/login', 'https://evil.test']) {
    assert.equal((await login(f.port, 'mario', MARIO, next)).headers.location, '/');
  }
});

test('signed sessions reject tampering, duplicate cookies and the separate main gateway cookie', async t => {
  const f = await fixture(t), cookie = cookieOf(await login(f.port));
  for (const value of [cookie + 'tampered', `${cookie}; ${cookie}`, '__Host-savia-fly-session=main-session']) {
    assert.equal((await authenticated(f.port, value)).status, 401);
  }
  const [name, token] = cookie.split('='), [payload, signature] = token.split('.');
  const claims = JSON.parse(Buffer.from(payload, 'base64url')); claims.sub = 'gloria';
  const forged = `${name}=${Buffer.from(JSON.stringify(claims)).toString('base64url')}.${signature}`;
  assert.equal((await authenticated(f.port, forged)).status, 401);
});

test('authenticated requests are origin-checked before local worker authority is synthesized', async t => {
  const f = await fixture(t), cookie = cookieOf(await login(f.port));
  for (const [method, headers] of [['GET', { Origin: `https://${MAIN}` }], ['GET', { 'Sec-Fetch-Site': 'same-site' }],
    ['GET', { Referer: 'https://evil.test/' }], ['POST', {}], ['POST', { Origin: 'null' }],
    ['POST', { Origin: ORIGIN, 'Sec-Fetch-Site': 'cross-site', Connection: 'Origin,Sec-Fetch-Site' }]]) {
    assert.equal((await request(f.port, '/api/flow', { method, headers: { Cookie: cookie, ...headers } })).status, 403);
  }
  assert.equal(f.requests.length, 0);
});

test('worker receives loopback security headers and control bearer with no browser cookie leakage', async t => {
  const f = await fixture(t, { handler: (_req, res) => {
    res.writeHead(200, { 'set-cookie': 'unwanted-worker-cookie=value', 'access-control-allow-origin': '*', 'content-type': 'application/json' });
    res.end('{"ok":true}');
  } });
  const cookie = cookieOf(await login(f.port));
  const response = await authenticated(f.port, `${cookie}; __Host-savia-fly-session=main; flujo_bank_session=private`, '/api/flow', {
    method: 'POST', headers: { 'X-Forwarded-Host': 'evil.test', 'X-Forwarded-Proto': 'https', Forwarded: 'host=evil.test',
      'X-Flujo-Fly-Authorization': 'private-gateway-basic', Connection: 'Origin,Authorization,Cookie' }, body: '{"name":"synthetic"}' });
  assert.equal(response.status, 200);
  const upstream = f.requests[0];
  assert.equal(upstream.headers.authorization, `Bearer ${TOKEN}`);
  assert.equal(upstream.headers.host, '127.0.0.1:4200'); assert.equal(upstream.headers.origin, 'http://127.0.0.1:4200');
  assert.equal(upstream.headers['x-forwarded-host'], '127.0.0.1:4200'); assert.equal(upstream.headers['x-forwarded-proto'], 'http');
  assert.equal(upstream.headers.cookie, undefined); assert.equal(upstream.headers.forwarded, undefined);
  assert.equal(upstream.headers['x-flujo-fly-authorization'], undefined); assert.equal(upstream.body, '{"name":"synthetic"}');
  assert.equal(response.headers['set-cookie'], undefined); assert.equal(response.headers['access-control-allow-origin'], undefined);
  assert.equal(response.headers['x-frame-options'], 'DENY'); assert.ok(!JSON.stringify(response).includes(TOKEN));
});

test('explicit bad or empty caller Authorization stays unchanged without any admin retry', async t => {
  const f = await fixture(t, { handler: (_req, res) => { res.writeHead(401); res.end('caller rejected'); } });
  const cookie = cookieOf(await login(f.port));
  for (const authorization of ['', 'invalid', 'Basic wrong', 'Bearer bad-execution-token']) {
    assert.equal((await authenticated(f.port, cookie, '/api/models', { headers: {
      Authorization: authorization, Connection: 'Authorization' } })).status, 401);
  }
  assert.deepEqual(f.requests.map(req => req.headers.authorization), ['', 'invalid', 'Basic wrong', 'Bearer bad-execution-token']);
});

test('banking routes keep execution credentials and user assertion separate from worker admin authority', async t => {
  const f = await fixture(t), cookie = cookieOf(await login(f.port));
  assert.equal((await authenticated(f.port, cookie, '/v1/banking/chat', { method: 'POST' })).status, 401);
  assert.equal((await authenticated(f.port, cookie, '/v1/banking/chat', { method: 'POST',
    headers: { Authorization: 'Bearer banking-execution-token' } })).status, 401);
  assert.equal(f.requests.length, 0);
  assert.equal((await authenticated(f.port, cookie, '/v1/banking/chat', { method: 'POST', headers: {
    Authorization: 'Bearer banking-execution-token', 'X-Flujo-User-Assertion': 'synthetic-signed-assertion',
    Connection: 'Authorization,X-Flujo-User-Assertion' } })).status, 200);
  assert.equal(f.requests[0].headers.authorization, 'Bearer banking-execution-token');
  assert.equal(f.requests[0].headers['x-flujo-user-assertion'], 'synthetic-signed-assertion');
});

test('logout and per-user revocation deny replay while preserving the other account', async t => {
  const f = await fixture(t), mario = cookieOf(await login(f.port)), gloria = cookieOf(await login(f.port, 'gloria'));
  assert.equal((await request(f.port, '/_dev/logout', { method: 'POST', headers: { Cookie: mario } })).status, 403);
  const logout = await authenticated(f.port, mario, '/_dev/logout', { method: 'POST' });
  assert.equal(logout.status, 303); assert.match(logout.headers['set-cookie'][0], /Max-Age=0/);
  assert.equal((await authenticated(f.port, mario)).status, 401);
  const mario1 = cookieOf(await login(f.port)), mario2 = cookieOf(await login(f.port));
  f.server.revokeUserSessions('mario');
  for (const value of [mario1, mario2]) assert.equal((await authenticated(f.port, value)).status, 401);
  assert.equal((await authenticated(f.port, gloria)).status, 200);
});

test('sessions expire after twelve hours and login throttling is independent for each user', async t => {
  let clock = TEST_NOW; const f = await fixture(t, { now: () => clock });
  const cookie = cookieOf(await login(f.port)); clock += 12 * 60 * 60 * 1000;
  assert.equal((await authenticated(f.port, cookie)).status, 401);
  for (let index = 0; index < 10; index++) assert.equal((await login(f.port, 'mario', 'wrong')).status, 401);
  assert.equal((await login(f.port)).status, 429);
  assert.equal((await login(f.port, 'gloria')).status, 303);
  clock += 60_001; assert.equal((await login(f.port)).status, 303);
});

test('HTTP/SSE streaming reaches the browser before upstream completion', async t => {
  let finish; const done = new Promise(resolve => { finish = resolve; });
  const f = await fixture(t, { handler: async (_req, res) => {
    res.writeHead(200, { 'Content-Type': 'text/event-stream' }); res.write('data: first\n\n'); await done; res.end('data: last\n\n');
  } });
  const cookie = cookieOf(await login(f.port));
  await new Promise((resolve, reject) => {
    const req = http.get({ hostname: '127.0.0.1', port: f.port, path: '/v1/chat/events', headers: { Host: HOST, Cookie: cookie, Origin: ORIGIN } }, res => {
      let body = '';
      res.on('data', chunk => { if (!body) { assert.equal(chunk.toString(), 'data: first\n\n'); finish(); } body += chunk; });
      res.on('end', () => { assert.equal(body, 'data: first\n\ndata: last\n\n'); resolve(); });
    }); req.on('error', reject);
  });
});

test('WebSockets require a dev session and exact origin, stream bidirectionally and close on logout', async t => {
  const f = await fixture(t), cookie = cookieOf(await login(f.port));
  assert.match((await websocket(f.port)).output, /^HTTP\/1\.1 401/);
  assert.match((await websocket(f.port, { cookie, origin: `https://${MAIN}` })).output, /^HTTP\/1\.1 403/);
  assert.match((await websocket(f.port, { cookie, authorization: 'Bearer rejected' })).output, /^HTTP\/1\.1 401/);
  const streamed = await websocket(f.port, { cookie });
  assert.match(streamed.output, /^HTTP\/1\.1 101/); assert.match(streamed.output, /synthetic echo/);
  assert.equal(f.wsRequests.at(-1).headers.origin, 'http://127.0.0.1:4200');
  assert.equal(f.wsRequests.at(-1).headers.cookie, undefined);
  const active = await websocket(f.port, { cookie, keepOpen: true });
  const closed = once(active.socket, 'close');
  assert.equal((await authenticated(f.port, cookie, '/_dev/logout', { method: 'POST' })).status, 303);
  await closed;
  assert.equal((await authenticated(f.port, cookie)).status, 401);
});

test('logout also terminates an active SSE response and disconnects its worker stream', async t => {
  let upstreamClosed;
  const workerDisconnected = new Promise(resolve => { upstreamClosed = resolve; });
  const f = await fixture(t, { handler: (_req, res) => {
    res.once('close', upstreamClosed);
    res.writeHead(200, { 'Content-Type': 'text/event-stream' }); res.write('data: first\n\n');
  } });
  const cookie = cookieOf(await login(f.port));
  const incoming = await new Promise((resolve, reject) => {
    const req = http.get({ hostname: '127.0.0.1', port: f.port, path: '/v1/chat/events', headers: {
      Host: HOST, Cookie: cookie, Origin: ORIGIN } }, response => {
      response.on('error', () => {});
      response.once('data', chunk => { assert.equal(chunk.toString(), 'data: first\n\n'); resolve(response); });
    }); req.on('error', reject);
  });
  const browserDisconnected = new Promise(resolve => incoming.once('close', resolve));
  assert.equal((await authenticated(f.port, cookie, '/_dev/logout', { method: 'POST' })).status, 303);
  await Promise.all([browserDisconnected, workerDisconnected]);
  assert.equal(incoming.complete, false);
});


test('only the separate dev hostname accepts its session; former main aliases and origins are rejected', async t => {
  const f = await fixture(t), cookie = cookieOf(await login(f.port));
  const oldFlags = readDevConfig({ ...env, FLUJO_DEV_UI_SAME_ORIGIN: '1', FLUJO_FLY_MAIN_HOST: MAIN });
  assert.equal(oldFlags.host, HOST); assert.equal(Object.hasOwn(oldFlags, 'sameOriginHost'), false);
  for (const host of [MAIN, MAIN + ':8443']) {
    assert.equal((await authenticated(f.port, cookie, '/api/models', { headers: { Host: host, Origin: 'https://' + host } })).status, 421);
    assert.equal((await request(f.port, '/_dev/login', { headers: { Host: host } })).status, 421);
  }
  assert.equal((await authenticated(f.port, cookie, '/api/models', { headers: { Origin: 'https://' + MAIN } })).status, 403);
  assert.equal((await authenticated(f.port, cookie, '/api/models', { headers: { Origin: ORIGIN + ':8443' } })).status, 403);
  assert.equal((await authenticated(f.port, cookie)).status, 200);
});

test('sessions and cookie lifetime are clamped to the deadline; expired startup remains alive with410', async t => {
  const deadline = TEST_NOW + 9_000;
  const f = await fixture(t, { expiresAt: new Date(deadline).toISOString() });
  const response = await login(f.port);
  assert.equal(response.status, 303); assert.match(response.headers['set-cookie'][0], /Max-Age=9;/);
  const value = cookieOf(response).split('=')[1].split('.')[0];
  assert.equal(JSON.parse(Buffer.from(value, 'base64url')).exp, deadline / 1000);
  const alreadyExpired = await fixture(t, { expiresAt: new Date(TEST_NOW - 1).toISOString() });
  assert.equal((await request(alreadyExpired.port, '/_dev/login')).status, 410);
  assert.equal(alreadyExpired.server.listening, true);
});

test('deadline rejects new and existing access and revokes active SSE/WS without stopping Savia supervisor', async t => {
  let clock = TEST_NOW, upstreamClosed;
  const workerDisconnected = new Promise(resolve => { upstreamClosed = resolve; });
  const f = await fixture(t, { now: () => clock, expiresAt: new Date(TEST_NOW + 1_000).toISOString(), handler: (_req, res) => {
    res.once('close', upstreamClosed); res.writeHead(200, { 'Content-Type': 'text/event-stream' }); res.write('data: first\n\n');
  } });
  const cookie = cookieOf(await login(f.port));
  const incoming = await new Promise((resolve, reject) => {
    const req = http.get({ hostname: '127.0.0.1', port: f.port, path: '/v1/chat/events', headers: {
      Host: HOST, Cookie: cookie, Origin: ORIGIN } }, response => {
      response.on('error', () => {}); response.once('data', () => resolve(response));
    }); req.on('error', reject);
  });
  const ws = await websocket(f.port, { cookie, keepOpen: true });
  const browserDisconnected = new Promise(resolve => incoming.once('close', resolve));
  const wsDisconnected = once(ws.socket, 'close');
  clock += 1_000;
  assert.equal((await request(f.port, '/_dev/login')).status, 410);
  await Promise.all([browserDisconnected, workerDisconnected, wsDisconnected]);
  assert.equal(incoming.complete, false);
  assert.equal((await login(f.port)).status, 410);
  assert.equal((await authenticated(f.port, cookie)).status, 410);
  assert.equal((await request(f.port, '/api/models')).status, 410);
  assert.match((await websocket(f.port, { cookie })).output, /^HTTP\/1\.1 410/);
  assert.equal(f.server.listening, true);
});

test('deadline timer closes active streams without a new request and keeps the process listener alive', { timeout: 5_000 }, async t => {
  let upstreamClosed;
  const workerDisconnected = new Promise(resolve => { upstreamClosed = resolve; });
  const f = await fixture(t, { now: Date.now, expiresAt: new Date(Date.now() + 1_500).toISOString(), handler: (_req, res) => {
    res.once('close', upstreamClosed); res.writeHead(200, { 'Content-Type': 'text/event-stream' }); res.write('data: first\n\n');
  } });
  const cookie = cookieOf(await login(f.port));
  const incoming = await new Promise((resolve, reject) => {
    const req = http.get({ hostname: '127.0.0.1', port: f.port, path: '/v1/chat/events', headers: {
      Host: HOST, Cookie: cookie, Origin: ORIGIN } }, response => {
      response.on('error', () => {}); response.once('data', () => resolve(response));
    }); req.on('error', reject);
  });
  await Promise.all([new Promise(resolve => incoming.once('close', resolve)), workerDisconnected]);
  assert.equal(incoming.complete, false);
  assert.equal(f.server.listening, true);
  assert.equal((await request(f.port, '/_dev/login')).status, 410);
});
