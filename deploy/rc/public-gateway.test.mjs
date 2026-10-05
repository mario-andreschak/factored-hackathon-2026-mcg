import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import net from 'node:net';
import { createHash } from 'node:crypto';
import { once } from 'node:events';
import { createGateway, readConfig } from './public-gateway.mjs';

const ORIGIN = 'https://savia-fictional.example';
const HOST = 'savia-fictional.example';
const CODE = 'SAVIA-2026';
const SECRET = 'visitor-cookie-signing-secret-0123456789';
const config = readConfig({ RC_PUBLIC_ORIGIN: ORIGIN, RC_DEMO_CODE: CODE,
  RC_COOKIE_SECRET: SECRET });

async function listen(server) {
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  return server.address().port;
}

async function fixture(t, { now = Date.now } = {}) {
  const forwarded = [];
  const sockets = new Set();
  const app = http.createServer((req, res) => {
    forwarded.push({ url: req.url, headers: req.headers });
    if (req.url === '/stream') {
      res.writeHead(200, { 'Content-Type': 'text/event-stream' });
      res.write('data: first\n\n');
      setTimeout(() => res.end('data: last\n\n'), 40);
      return;
    }
    req.resume();
    req.on('end', () => res.end('Savia response'));
  });
  app.on('upgrade', (req, socket, head) => {
    forwarded.push({ url: req.url, headers: req.headers });
    const accept = createHash('sha1').update(req.headers['sec-websocket-key']
      + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
    socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
    if (head.length) socket.write(head);
    socket.on('data', bytes => socket.write(bytes));
  });
  for (const server of [app]) server.on('connection', socket => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
  });
  const appPort = await listen(app);
  const gateway = createGateway(config, { appPort, now });
  gateway.on('connection', socket => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
  });
  const gatewayPort = await listen(gateway);
  t.after(async () => {
    for (const socket of sockets) socket.destroy();
    await Promise.all([app, gateway].map(server => new Promise(resolve => {
      server.close(resolve);
      server.closeAllConnections();
    })));
  });
  return { gatewayPort, forwarded };
}

function request(port, path = '/', { method = 'GET', headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request({ hostname: '127.0.0.1', port, path, method,
      headers: { Host: HOST, ...headers } }, res => {
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers,
        body: Buffer.concat(chunks).toString('utf8') }));
    });
    req.on('error', reject);
    req.end(body);
  });
}

async function enter(port, { origin = ORIGIN, host = HOST, code = CODE } = {}) {
  return request(port, '/_rc/enter', { method: 'POST', headers: { Host: host, Origin: origin,
    'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ code }).toString() });
}

function cookieOf(response) { return response.headers['set-cookie']?.[0].split(';')[0]; }

function upgrade(port, headers = {}) {
  return new Promise((resolve, reject) => {
    const socket = net.connect(port, '127.0.0.1');
    let received = Buffer.alloc(0);
    const timeout = setTimeout(() => { socket.destroy(); reject(new Error('upgrade timed out')); }, 2500);
    socket.on('connect', () => {
      const lines = ['GET /socket HTTP/1.1', `Host: ${HOST}`, 'Connection: Upgrade',
        'Upgrade: websocket', 'Sec-WebSocket-Version: 13', 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ=='];
      for (const [name, value] of Object.entries(headers)) lines.push(`${name}: ${value}`);
      socket.write(lines.join('\r\n') + '\r\n\r\n');
    });
    socket.on('data', chunk => {
      received = Buffer.concat([received, chunk]);
      if (/^HTTP\/1\.1 (?:101|401|403|502)/.test(received.toString('utf8'))) {
        clearTimeout(timeout); socket.destroy(); resolve(received.toString('utf8'));
      }
    });
    socket.on('error', error => { clearTimeout(timeout); reject(error); });
  });
}

test('requires HTTPS origin and private secrets at startup', () => {
  assert.throws(() => readConfig({ RC_PUBLIC_ORIGIN: 'http://savia-fictional.example', RC_DEMO_CODE: CODE,
    RC_COOKIE_SECRET: SECRET }), /HTTPS/);
  assert.throws(() => readConfig({ RC_PUBLIC_ORIGIN: ORIGIN, RC_DEMO_CODE: CODE,
    RC_COOKIE_SECRET: 'short' }), /RC_COOKIE_SECRET/);
  assert.throws(() => readConfig({ RC_PUBLIC_ORIGIN: ORIGIN, RC_DEMO_CODE: '',
    RC_COOKIE_SECRET: SECRET }), /RC_DEMO_CODE/);
});

test('landing is fictional, code entry checks host and same-origin, and issues an eight-hour secure cookie', async t => {
  const f = await fixture(t);
  const page = await request(f.gatewayPort);
  assert.equal(page.status, 200);
  assert.match(page.body, /Fictional demonstration/);
  assert.match(page.body, /Do not enter real personal or financial information/);
  assert.doesNotMatch(page.body, new RegExp(SECRET));
  assert.equal((await enter(f.gatewayPort, { origin: 'https://attacker.example' })).status, 403);
  assert.equal((await enter(f.gatewayPort, { host: 'attacker.example' })).status, 421);
  assert.equal((await enter(f.gatewayPort, { code: 'wrong' })).body.includes('not accepted'), true);
  const accepted = await enter(f.gatewayPort);
  assert.equal(accepted.status, 303);
  assert.equal(accepted.headers.location, '/');
  assert.match(accepted.headers['set-cookie'][0], /Path=\/; Max-Age=28800; HttpOnly; Secure; SameSite=Strict/);
  assert.doesNotMatch(accepted.headers['set-cookie'][0], /Domain=|SAVIA-2026|private-avatar/);
});

test('signed visitor cookie rejects tampering and expiry; unauthenticated APIs return 401', async t => {
  let clock = 1_800_000_000_000;
  const f = await fixture(t, { now: () => clock });
  assert.equal((await request(f.gatewayPort, '/api/avatar/config')).status, 401);
  const accepted = await enter(f.gatewayPort);
  const cookie = cookieOf(accepted);
  assert.equal((await request(f.gatewayPort, '/api/avatar/config', { headers: { Cookie: cookie } })).status, 200);
  const altered = cookie.replace(/.$/, cookie.endsWith('a') ? 'b' : 'a');
  assert.equal((await request(f.gatewayPort, '/api/avatar/config', { headers: { Cookie: altered } })).status, 401);
  clock += 8 * 60 * 60 * 1000 + 1000;
  assert.equal((await request(f.gatewayPort, '/api/avatar/config', { headers: { Cookie: cookie } })).status, 401);
});

test('proxy strips untrusted headers, preserves customer cookie and Origin, and streams Savia', async t => {
  const f = await fixture(t);
  const cookie = cookieOf(await enter(f.gatewayPort));
  const response = await request(f.gatewayPort, '/stream', { headers: { Cookie: cookie,
    Origin: ORIGIN, 'X-Avatar-Gateway-Token': 'attacker-token', 'X-Forwarded-Host': 'attacker.example',
    'X-Forwarded-Proto': 'http', Forwarded: 'host=attacker.example' } });
  assert.equal(response.status, 200);
  assert.match(response.body, /data: first/);
  assert.match(response.body, /data: last/);
  const seen = f.forwarded[0].headers;
  assert.equal(seen.host, HOST);
  assert.equal(seen.origin, ORIGIN);
  assert.equal(seen['x-avatar-gateway-token'], undefined);
  assert.equal(seen['x-forwarded-host'], HOST);
  assert.equal(seen['x-forwarded-proto'], 'https');
  assert.equal(seen.forwarded, undefined);
  assert.doesNotMatch(JSON.stringify(seen), /attacker-token/);
  assert.equal(seen.cookie, undefined);
});

test('authenticated same-origin WebSocket upgrades reach Savia; unauthorized upgrades are denied', async t => {
  const f = await fixture(t);
  assert.match(await upgrade(f.gatewayPort), /^HTTP\/1\.1 401/);
  const cookie = cookieOf(await enter(f.gatewayPort));
  assert.match(await upgrade(f.gatewayPort, { Cookie: cookie }), /^HTTP\/1\.1 403/);
  assert.match(await upgrade(f.gatewayPort, { Cookie: cookie, Origin: ORIGIN, 'X-Avatar-Gateway-Token': 'spoofed' }), /^HTTP\/1\.1 101/);
  assert.equal(f.forwarded[0].headers['x-avatar-gateway-token'], undefined);
  assert.equal(f.forwarded[0].headers.host, HOST);
});

test('public health checks only fixed Savia with public Host and exposes no secret', async t => {
  const f = await fixture(t);
  const response = await request(f.gatewayPort, '/healthz');
  assert.equal(response.status, 200);
  assert.deepEqual(JSON.parse(response.body), { status: 'ok', savia: true });
  assert.equal(f.forwarded[0].url, '/healthz');
  assert.equal(f.forwarded[0].headers['x-avatar-gateway-token'], undefined);
  assert.equal(f.forwarded[0].headers.host, HOST);
  assert.doesNotMatch(response.body, new RegExp(SECRET));
});

test('authenticated Savia mutations reject null or foreign Origin and keep the customer cookie', async t => {
  const f = await fixture(t);
  const cookie = cookieOf(await enter(f.gatewayPort)) + '; bank-session=owned-fictional-cookie';
  for (const origin of ['null', 'https://attacker.example']) {
    assert.equal((await request(f.gatewayPort, '/api/voice/turn', { method: 'POST', headers: { Cookie: cookie, Origin: origin }, body: '{}' })).status, 403);
  }
  const response = await request(f.gatewayPort, '/api/voice/turn', { method: 'POST', headers: { Cookie: cookie, Origin: ORIGIN }, body: '{}' });
  assert.equal(response.status, 200);
  assert.equal(f.forwarded[0].headers.cookie, 'bank-session=owned-fictional-cookie');
});
