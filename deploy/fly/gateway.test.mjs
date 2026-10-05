import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import net from 'node:net';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import { createGateway, readConfig } from './gateway.mjs';
import { createDevGateway, readDevConfig } from './dev-gateway.mjs';

const PASSWORD = 'correct-password-with-at-least-24-chars';
const MAIN = 'flujo-example.fly.dev';
const SANDBOX = `${MAIN}:8443`;
const WORKER_TOKEN = 'private-test-worker-token';
const config = readConfig({ FLUJO_FLY_PASSWORD: PASSWORD, FLUJO_FLY_MAIN_HOST: MAIN,
  FLUJO_SNAPSHOT_CONTROL_TOKEN: WORKER_TOKEN });
const basic = (username = 'savia', password = PASSWORD) => `Basic ${Buffer.from(`${username}:${password}`).toString('base64')}`;

async function listen(server) {
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  return server.address().port;
}

async function fixture(t, { now } = {}) {
  const mainRequests = [];
  const workerRequests = [];
  let mainStatus = 200;
  let datasetReady = true;
  let workerReady = true;
  const main = http.createServer((req, res) => {
    mainRequests.push({ url: req.url, headers: req.headers });
    if (req.url === '/') { res.writeHead(mainStatus); res.end('private shell body'); return; }
    if (req.url === '/healthz') {
      res.writeHead(mainStatus);
      res.end(JSON.stringify({ status: 'ok', dataset_ready: datasetReady, private_diagnostic: 'must not leak' }));
      return;
    }
    if (req.url === '/stream') {
      res.writeHead(200, { 'Content-Type': 'text/event-stream' });
      res.write('data: first\n\n');
      setTimeout(() => res.end('data: last\n\n'), 100);
      return;
    }
    const chunks = [];
    req.on('data', chunk => chunks.push(chunk));
    req.on('end', () => res.end(JSON.stringify({ headers: req.headers,
      body: Buffer.concat(chunks).toString('utf8') })));
  });
  const worker = http.createServer((req, res) => {
    workerRequests.push({ url: req.url, headers: req.headers });
    if (req.url !== '/api/worker/status' || req.headers.authorization !== `Bearer ${WORKER_TOKEN}`) {
      res.writeHead(401); res.end(); return;
    }
    res.end(JSON.stringify({ mode: 'worker', state: workerReady ? 'ready' : 'locked', private_state: 'must not leak' }));
  });
  const sockets = new Set();
  for (const upstream of [main, worker]) {
    upstream.on('connection', socket => { sockets.add(socket); socket.on('close', () => sockets.delete(socket)); });
    upstream.on('upgrade', (req, socket, head) => {
      (upstream === main ? mainRequests : workerRequests).push({ url: req.url, headers: req.headers });
      const accept = createHash('sha1').update(req.headers['sec-websocket-key']
        + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
      socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
      if (head.length) socket.write(head);
      socket.on('data', bytes => socket.write(bytes));
    });
  }
  const mainPort = await listen(main);
  const workerPort = await listen(worker);
  const gateway = createGateway(config, { mainPort, workerPort, now });
  const gatewayPort = await listen(gateway);
  t.after(async () => {
    for (const socket of sockets) socket.destroy();
    await Promise.all([main, worker, gateway].map(server => new Promise(resolve => {
      server.close(resolve); server.closeAllConnections();
    })));
  });
  return { gatewayPort, mainRequests, workerRequests,
    mainStatus: status => { mainStatus = status; },
    datasetReady: ready => { datasetReady = ready; }, workerReady: ready => { workerReady = ready; } };
}

function request(port, path = '/', { method = 'GET', headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request({ hostname: '127.0.0.1', port, path, method, headers: { Host: MAIN, ...headers } }, res => {
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers,
        body: Buffer.concat(chunks).toString('utf8') }));
    });
    req.on('error', reject);
    req.end(body);
  });
}

async function login(port, next = '/') {
  return request(port, `/_fly/login?next=${encodeURIComponent(next)}`, { method: 'POST',
    headers: { Origin: `https://${MAIN}`, 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: 'savia', password: PASSWORD }).toString() });
}

function cookieOf(response) { return response.headers['set-cookie'][0].split(';')[0]; }

function upgrade(port, { host = MAIN, headers = {}, payload = 'ws payload' } = {}) {
  return new Promise((resolve, reject) => {
    const socket = net.connect(port, '127.0.0.1');
    let received = Buffer.alloc(0);
    const timeout = setTimeout(() => { socket.destroy(); reject(new Error('WebSocket test timed out')); }, 3000);
    socket.on('connect', () => {
      const lines = ['GET /runtime/ws HTTP/1.1', `Host: ${host}`, 'Connection: Upgrade', 'Upgrade: websocket',
        'Sec-WebSocket-Version: 13', 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ=='];
      for (const [name, value] of Object.entries(headers)) lines.push(`${name}: ${value}`);
      socket.write(lines.join('\r\n') + '\r\n\r\n' + payload);
    });
    socket.on('data', chunk => {
      received = Buffer.concat([received, chunk]);
      const text = received.toString('utf8');
      if (text.includes(payload) || /^HTTP\/1\.1 (401|403)/.test(text)) {
        clearTimeout(timeout); socket.destroy(); resolve(text);
      }
    });
    socket.on('error', error => { clearTimeout(timeout); reject(error); });
    socket.on('end', () => { clearTimeout(timeout); resolve(received.toString('utf8')); });
  });
}

test('configuration rejects missing credentials and ambiguous origins without revealing password', () => {
  const base = { FLUJO_FLY_PASSWORD: PASSWORD, FLUJO_FLY_MAIN_HOST: MAIN,
    FLUJO_SNAPSHOT_CONTROL_TOKEN: WORKER_TOKEN };
  for (const env of [{}, { FLUJO_FLY_PASSWORD: 'short', FLUJO_FLY_MAIN_HOST: MAIN },
    { ...base, FLUJO_FLY_MAIN_HOST: `https://${MAIN}` },
    { ...base, FLUJO_SNAPSHOT_CONTROL_TOKEN: '' },
    { ...base, FLUJO_FLY_MAIN_HOST: `${MAIN}:443` }]) {
    assert.throws(() => readConfig(env), error => !error.message.includes(PASSWORD));
  }
  assert.equal(config.username, 'savia');
  assert.equal(Object.hasOwn(readConfig({ ...base, FLUJO_FLY_DEV_UI_ENABLED: '1' }), 'devUiEnabled'), false);
});

test('main listener rejects every unauthenticated dashboard/API route and wrong Host', async t => {
  const f = await fixture(t);
  for (const path of ['/api/overview', '/api/transactions', '/api/chat/history', '/healthz', '/favicon.ico']) {
    assert.equal((await request(f.gatewayPort, path)).status, 401);
  }
  for (const path of ['/v1', '/v1/models', '/v1/chat/completions', '/mcp-proxy/server', '/_flujo/runtime/register']) {
    assert.equal((await request(f.gatewayPort, path)).status, 404);
    assert.equal((await request(f.gatewayPort, path, { headers: { Authorization: basic() } })).status, 404);
  }
  const browser = await request(f.gatewayPort, '/?tab=flows', { headers: { Accept: 'text/html' } });
  assert.equal(browser.status, 303);
  assert.equal(browser.headers.location, '/_fly/login?next=%2F%3Ftab%3Dflows');
  for (const host of ['evil.test', SANDBOX, `${MAIN}:444`, `evil.test@${MAIN}`]) {
    assert.equal((await request(f.gatewayPort, '/_fly/health', { headers: { Host: host } })).status, 421);
  }
  assert.equal(f.mainRequests.length, 0);
});

test('login grants host-only secure signed session and preserves Bearer without leaking gateway credential', async t => {
  const f = await fixture(t);
  const loggedIn = await login(f.gatewayPort, '/');
  assert.equal(loggedIn.status, 303);
  assert.equal(loggedIn.headers.location, '/');
  const rawCookie = loggedIn.headers['set-cookie'][0];
  assert.match(rawCookie, /Path=\/; Max-Age=43200; HttpOnly; Secure; SameSite=Strict/);
  assert.doesNotMatch(rawCookie, /Domain=|correct-password/);
  const cookie = cookieOf(loggedIn);
  const response = await request(f.gatewayPort, '/api/chat/history', { headers: { Cookie: `${cookie}; flujo_bank_session=safe`,
    Authorization: 'Bearer app-model-token', Origin: `https://${MAIN}`,
    'X-Forwarded-Host': 'evil.test', 'X-Forwarded-Proto': 'http' } });
  assert.equal(response.status, 200);
  const proxied = JSON.parse(response.body).headers;
  assert.equal(proxied.authorization, 'Bearer app-model-token');
  assert.equal(proxied.cookie, 'flujo_bank_session=safe');
  assert.equal(proxied.host, MAIN);
  assert.equal(proxied.origin, `https://${MAIN}`);
  assert.equal(proxied['x-forwarded-host'], MAIN);
  assert.equal(proxied['x-forwarded-proto'], 'https');
  assert.equal((await request(f.gatewayPort, '/api/settings', { headers: { Cookie: cookie + 'tampered' } })).status, 401);
});

test('Basic gateway authentication is consumed, dedicated header can coexist with upstream Bearer', async t => {
  const f = await fixture(t);
  const response = await request(f.gatewayPort, '/api/settings', { headers: { Authorization: basic() } });
  assert.equal(response.status, 200);
  assert.ok(response.headers['set-cookie']);
  assert.equal(JSON.parse(response.body).headers.authorization, undefined);
  const bearer = await request(f.gatewayPort, '/api/chat', { method: 'POST',
    headers: { Authorization: 'Bearer model-secret', 'X-Flujo-Fly-Authorization': basic() }, body: 'message' });
  assert.equal(bearer.status, 200);
  assert.equal(JSON.parse(bearer.body).headers.authorization, 'Bearer model-secret');
  assert.equal(JSON.parse(bearer.body).headers['x-flujo-fly-authorization'], undefined);
  assert.equal(JSON.parse(bearer.body).body, 'message');
  assert.equal((await request(f.gatewayPort, '/api/overview', { headers: { Authorization: 'Bearer model-secret' } })).status, 401);
});

test('login rejects CSRF, rate limits failed credentials, and rejects open redirects', async t => {
  const f = await fixture(t);
  for (const origin of [undefined, 'null', 'https://evil.test', `https://${SANDBOX}`]) {
    const csrf = await request(f.gatewayPort, '/_fly/login', { method: 'POST',
      headers: { ...(origin === undefined ? {} : { Origin: origin }),
        'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ username: 'savia', password: PASSWORD }).toString() });
    assert.equal(csrf.status, 403);
    assert.equal(csrf.headers['set-cookie'], undefined);
  }
  for (const unsafeNext of ['//evil.test', '/\\evil.test', '/_fly/health', 'https://evil.test']) {
    assert.equal((await login(f.gatewayPort, unsafeNext)).headers.location, '/');
  }
  for (let index = 0; index < 10; index++) {
    assert.equal((await request(f.gatewayPort, '/api/settings', { headers: { Authorization: basic('savia', 'wrong') } })).status, 401);
  }
  assert.equal((await request(f.gatewayPort, '/api/settings', { headers: { Authorization: basic('savia', 'wrong') } })).status, 429);
});

test('login pages preserve native same-origin form Origin, including a failed sign-in retry', async t => {
  const f = await fixture(t);
  const page = await request(f.gatewayPort, '/_fly/login?next=%2F');
  assert.equal(page.status, 200);
  assert.equal(page.headers['referrer-policy'], 'same-origin');
  assert.match(page.body, /<form method="post" action="\/_fly\/login\?next=%2F">/);
  assert.match(page.headers['content-security-policy'], /form-action 'self'; frame-ancestors 'none'/);
  const failed = await request(f.gatewayPort, '/_fly/login?next=%2F', { method: 'POST',
    headers: { Origin: `https://${MAIN}`, 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: 'savia', password: 'wrong' }).toString() });
  assert.equal(failed.status, 401);
  assert.equal(failed.headers['referrer-policy'], 'same-origin');
  assert.match(failed.body, /Sign-in failed/);
  assert.equal((await login(f.gatewayPort)).status, 303);
  assert.equal(f.mainRequests.length, 0);
});

test('session expires and gateway cookie cannot authorize cross-port sandbox-origin requests', async t => {
  let clock = Date.now();
  const f = await fixture(t, { now: () => clock });
  const cookie = cookieOf(await login(f.gatewayPort));
  for (const method of ['GET', 'POST']) {
    assert.equal((await request(f.gatewayPort, '/api/chat', { method,
      headers: { Cookie: cookie, Origin: `https://${SANDBOX}` } })).status, 403);
  }
  assert.equal((await request(f.gatewayPort, '/api/settings', { method: 'POST', headers: { Cookie: cookie } })).status, 403);
  assert.equal((await request(f.gatewayPort, '/api/settings', { headers: { Cookie: cookie, 'Sec-Fetch-Site': 'same-site' } })).status, 403);
  assert.equal((await request(f.gatewayPort, '/api/settings', { method: 'POST',
    headers: { Cookie: cookie, Origin: `https://${MAIN}` } })).status, 200);
  clock += 12 * 60 * 60 * 1000;
  assert.equal((await request(f.gatewayPort, '/api/settings', { headers: { Cookie: cookie } })).status, 401);
});

test('Connection tokens cannot erase browser security inputs or application cookies and Bearer', async t => {
  const f = await fixture(t);
  const cookie = cookieOf(await login(f.gatewayPort));
  const rejected = await request(f.gatewayPort, '/api/chat', { method: 'POST', headers: {
    Cookie: cookie, Origin: `https://${SANDBOX}`, 'Sec-Fetch-Site': 'same-site',
    Connection: 'Origin,Referer,Sec-Fetch-Site' }, body: '{}' });
  assert.equal(rejected.status, 403);
  assert.equal(f.mainRequests.length, 0);
  const response = await request(f.gatewayPort, '/api/chat', { method: 'POST', headers: {
    'X-Flujo-Fly-Authorization': basic(), Authorization: 'Bearer public-frontend-token',
    Origin: `https://${MAIN}`, Referer: `https://${MAIN}/`, Connection: 'Origin,Referer,Authorization',
    Cookie: 'flujo_bank_session=retained' }, body: '{}' });
  assert.equal(response.status, 200);
  const headers = JSON.parse(response.body).headers;
  assert.equal(headers.origin, `https://${MAIN}`);
  assert.equal(headers.referer, `https://${MAIN}/`);
  assert.equal(headers.authorization, 'Bearer public-frontend-token');
  assert.equal(headers.cookie, 'flujo_bank_session=retained');
});

test('HTTP streams begin before the upstream finishes and main pages cannot be framed', async t => {
  const f = await fixture(t);
  await new Promise((resolve, reject) => {
    const req = http.get({ hostname: '127.0.0.1', port: f.gatewayPort, path: '/stream',
      headers: { Host: MAIN, Authorization: basic() } }, res => {
      assert.equal(res.headers['x-frame-options'], 'DENY');
      assert.equal(res.headers['content-security-policy'], "frame-ancestors 'none'");
      const chunks = [];
      res.on('data', chunk => {
        chunks.push(chunk.toString('utf8'));
        if (chunks.length === 1) assert.equal(chunk.toString('utf8'), 'data: first\n\n');
      });
      res.on('end', () => {
        assert.equal(chunks.join(''), 'data: first\n\ndata: last\n\n');
        assert.equal(chunks.length, 2);
        resolve();
      });
    });
    req.on('error', reject);
  });
});

test('public health proves dataset and private worker ready without returning internal response bodies', async t => {
  const f = await fixture(t);
  const health = await request(f.gatewayPort, '/_fly/health?path=/api/encryption');
  assert.equal(health.status, 200);
  assert.equal(health.body, 'ready');
  assert.equal(f.mainRequests[0].url, '/healthz');
  assert.equal(f.mainRequests[0].headers.host, MAIN);
  assert.equal(f.workerRequests[0].url, '/api/worker/status');
  assert.equal(f.workerRequests[0].headers.authorization, `Bearer ${WORKER_TOKEN}`);
  f.datasetReady(false);
  assert.equal((await request(f.gatewayPort, '/_fly/health')).status, 503);
  f.datasetReady(true);
  f.workerReady(false);
  assert.equal((await request(f.gatewayPort, '/_fly/health')).status, 503);
  f.workerReady(true);
  f.mainStatus(503);
  const unavailable = await request(f.gatewayPort, '/_fly/health');
  assert.equal(unavailable.status, 503);
  assert.equal(unavailable.body, 'unavailable');
  assert.equal((await request(f.gatewayPort, '/_fly/health', { method: 'POST' })).status, 405);
});

test('authenticated frontend requests never route to the FLUJO worker', async t => {
  const f = await fixture(t);
  const cookie = cookieOf(await login(f.gatewayPort));
  const response = await request(f.gatewayPort, '/api/overview', { headers: { Cookie: cookie } });
  assert.equal(response.status, 200);
  assert.equal(f.workerRequests.length, 0);
  assert.equal(f.mainRequests[0].url, '/api/overview');
});

test('WebSocket upgrades require gateway auth and preserve bidirectional data and original origins', async t => {
  const f = await fixture(t);
  assert.match(await upgrade(f.gatewayPort), /^HTTP\/1\.1 401/);
  const cookie = cookieOf(await login(f.gatewayPort));
  assert.match(await upgrade(f.gatewayPort, { headers: { Cookie: cookie, Origin: `https://${SANDBOX}` } }), /^HTTP\/1\.1 403/);
  const response = await upgrade(f.gatewayPort, { headers: { Cookie: cookie, Origin: `https://${MAIN}` } });
  assert.match(response, /^HTTP\/1\.1 101/);
  assert.match(response, /ws payload/);
  assert.equal(f.mainRequests.at(-1).headers.cookie, undefined);
  assert.equal(f.mainRequests.at(-1).headers.origin, `https://${MAIN}`);
  assert.equal(f.workerRequests.length, 0);
});


test('main always serves Savia with valid or stale development cookies and strips them before frontend', async t => {
  const f = await fixture(t);
  const devHost = 'flujo-factored-dev-2026.fly.dev';
  const worker = http.createServer((req, res) => {
    assert.equal(req.headers.authorization, 'Bearer synthetic-dev-worker-token'); res.end('private development worker');
  });
  const workerPort = await listen(worker);
  const dev = createDevGateway(readDevConfig({ FLUJO_DEV_UI_ENABLED: '1', FLUJO_DEV_UI_HOST: devHost,
    FLUJO_DEV_UI_EXPIRES_AT: '2026-10-16T05:00:00.000Z',
    FLUJO_DEV_UI_MARIO_PASSWORD: 'synthetic-mario-password-at-least-24',
    FLUJO_DEV_UI_GLORIA_PASSWORD: 'synthetic-gloria-password-at-least-24',
    FLUJO_SNAPSHOT_CONTROL_TOKEN: 'synthetic-dev-worker-token' }), {
    upstreamPort: workerPort, now: () => Date.parse('2026-09-30T12:00:00.000Z') });
  const devPort = await listen(dev);
  t.after(() => Promise.all([dev, worker].map(server => new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }))));
  const devLogin = await request(devPort, '/_dev/login', { method: 'POST', headers: {
    Host: devHost, Origin: 'https://' + devHost, 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: 'mario', password: 'synthetic-mario-password-at-least-24' }).toString() });
  assert.equal(devLogin.status, 303);
  const validDevCookie = cookieOf(devLogin);
  assert.equal((await request(devPort, '/api/models', { headers: { Host: devHost, Origin: 'https://' + devHost,
    Cookie: validDevCookie } })).body, 'private development worker');
  const mainCookie = cookieOf(await login(f.gatewayPort));
  for (const devCookie of [validDevCookie, '__Host-flujo-live-dev-session=stale-session']) {
    const headers = { Cookie: mainCookie + '; ' + devCookie + '; flujo_bank_session=private-bank-session', Origin: 'https://' + MAIN };
    assert.equal((await request(f.gatewayPort, '/', { headers })).body, 'private shell body');
    const api = await request(f.gatewayPort, '/api/settings', { headers });
    assert.equal(api.status, 200);
    assert.equal(JSON.parse(api.body).headers.cookie, 'flujo_bank_session=private-bank-session');
    assert.equal((await request(f.gatewayPort, '/v1/models', { headers })).status, 404);
    assert.equal((await request(f.gatewayPort, '/api/settings', { headers: { Cookie: devCookie } })).status, 401);
  }
  assert.equal((await request(devPort, '/api/models', { headers: { Host: devHost, Origin: 'https://' + devHost,
    Cookie: mainCookie } })).status, 401);
  assert.equal(f.workerRequests.length, 0);
});

test('main development login is only an explanatory link and never accepts development credentials', async t => {
  const f = await fixture(t);
  const response = await request(f.gatewayPort, '/_dev/login', { headers: {
    Cookie: '__Host-flujo-live-dev-session=legacy', Accept: 'text/html' } });
  assert.equal(response.status, 200);
  assert.match(response.body, /href="https:\/\/flujo-factored-dev-2026\.fly\.dev\/_dev\/login"/);
  assert.equal(response.headers['set-cookie'], undefined);
  assert.equal((await request(f.gatewayPort, '/_dev/login', { method: 'POST', headers: { Origin: 'https://' + MAIN } })).status, 405);
  assert.equal((await request(f.gatewayPort, '/_dev/logout')).status, 404);
  assert.equal(f.mainRequests.length, 0);
  assert.equal(f.workerRequests.length, 0);
});
