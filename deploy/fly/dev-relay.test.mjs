import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import net from 'node:net';
import { PassThrough } from 'node:stream';
import { once } from 'node:events';
import { createHash } from 'node:crypto';
import { createDevRelay, readRelayConfig } from './dev-relay.mjs';

const HOST = 'flujo-factored-dev-2026.fly.dev';
const ORIGIN = `https://${HOST}`;
const NOW = Date.parse('2026-09-30T12:00:00.000Z');
const DEADLINE = '2026-10-16T05:00:00.000Z';
const config = readRelayConfig({ FLUJO_DEV_RELAY_HOST: HOST, FLUJO_DEV_RELAY_EXPIRES_AT: DEADLINE });
const nativeRequest = http.request;
const listen = async server => { server.listen(0, '127.0.0.1'); await once(server, 'listening'); return server.address().port; };

async function fixture(t, { handler, wsStatus, now = () => NOW, expiresAt = config.expiresAt } = {}) {
  const requests = [], upgrades = [], sockets = new Set();
  const upstream = http.createServer(async (req, res) => {
    const chunks = []; for await (const chunk of req) chunks.push(chunk);
    requests.push({ url: req.url, method: req.method, headers: req.headers, body: Buffer.concat(chunks).toString('utf8') });
    if (handler) handler(req, res); else res.end('synthetic authenticated leaf');
  });
  upstream.on('upgrade', (req, socket, head) => {
    upgrades.push({ url: req.url, headers: req.headers });
    const status = wsStatus ?? (Object.hasOwn(req.headers, 'authorization') && req.headers.authorization !== 'Bearer explicit-caller' ? 401 : 101);
    if (status !== 101) { socket.end(`HTTP/1.1 ${status} Rejected\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`); return; }
    const accept = createHash('sha1').update(req.headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
    socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
    if (head.length) socket.write(head); socket.on('data', chunk => socket.write(chunk));
  });
  const upstreamPort = await listen(upstream);
  const relay = createDevRelay({ ...config, expiresAt }, { upstreamHost: '127.0.0.1', upstreamPort, now });
  for (const server of [upstream, relay]) server.on('connection', socket => { sockets.add(socket); socket.on('close', () => sockets.delete(socket)); });
  const port = await listen(relay);
  t.after(async () => {
    for (const socket of sockets) socket.destroy();
    await Promise.all([relay, upstream].map(server => new Promise(resolve => { server.close(resolve); server.closeAllConnections(); })));
  });
  return { port, relay, requests, upgrades };
}

function request(port, path = '/api/models', { method = 'GET', headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const req = nativeRequest({ hostname: '127.0.0.1', port, path, method, headers: { Host: HOST, ...headers } }, res => {
      const chunks = []; res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks).toString('utf8') }));
    }); req.on('error', reject); req.end(body);
  });
}

function websocket(port, { host = HOST, origin = ORIGIN, authorization, keepOpen = false } = {}) {
  return new Promise((resolve, reject) => {
    const socket = net.connect(port, '127.0.0.1'); let output = '';
    const timer = setTimeout(() => { socket.destroy(); reject(new Error('Synthetic relay upgrade timed out')); }, 3000);
    socket.on('connect', () => {
      const lines = ['GET /runtime/ws HTTP/1.1', `Host: ${host}`, 'Connection: Upgrade,Authorization,Cookie,Origin,Referer,Sec-Fetch-Site',
        'Upgrade: websocket', 'Sec-WebSocket-Version: 13', 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==',
        'Cookie: __Host-flujo-live-dev-session=synthetic', `Origin: ${origin}`, `Referer: ${ORIGIN}/`, 'Sec-Fetch-Site: same-origin'];
      if (authorization !== undefined) lines.push(`Authorization: ${authorization}`);
      socket.write(lines.join('\r\n') + '\r\n\r\n' + (keepOpen ? '' : 'synthetic relay echo'));
    });
    socket.on('data', chunk => {
      output += chunk;
      if (output.includes('synthetic relay echo') || /^HTTP\/1\.1 (401|403|410)/.test(output)
        || (keepOpen && output.includes('\r\n\r\n'))) {
        clearTimeout(timer); if (!keepOpen) socket.destroy(); resolve({ socket, output });
      }
    });
    socket.on('error', error => { clearTimeout(timer); reject(error); });
    socket.on('end', () => { clearTimeout(timer); resolve({ socket, output }); });
  });
}

async function openStream(port) {
  return new Promise((resolve, reject) => {
    const req = nativeRequest({ hostname: '127.0.0.1', port, path: '/v1/chat/events', headers: { Host: HOST, Origin: ORIGIN } }, res => {
      res.on('error', () => {}); res.once('data', chunk => { assert.equal(chunk.toString(), 'data: first\n\n'); resolve(res); });
    }); req.on('error', reject); req.end();
  });
}

test('configuration requires the fixed hostname and canonical finite UTC expiry', () => {
  for (const expires of [undefined, 'forever', '2026-10-16', '2026-10-16T05:00:00Z',
    '2026-10-16T05:00:00.000+00:00', '2026-02-30T05:00:00.000Z', '1970-01-01T00:00:00.000Z']) {
    assert.throws(() => readRelayConfig({ FLUJO_DEV_RELAY_HOST: HOST, FLUJO_DEV_RELAY_EXPIRES_AT: expires }));
  }
  assert.throws(() => readRelayConfig({ FLUJO_DEV_RELAY_HOST: 'evil.test', FLUJO_DEV_RELAY_EXPIRES_AT: DEADLINE }));
  assert.throws(() => createDevRelay({ ...config, expiresAt: NaN }));
  assert.throws(() => createDevRelay(config, { upstreamHost: 'evil.test' }));
  assert.throws(() => createDevRelay(config, { upstreamPort: 4200 }));
  assert.deepEqual(readRelayConfig({ FLUJO_DEV_RELAY_HOST: HOST, FLUJO_DEV_RELAY_EXPIRES_AT: DEADLINE,
    FLUJO_DEV_RELAY_BACKEND: 'evil.test', FLUJO_DEV_RELAY_PORT: '4200' }), config);
});

test('production target stays fixed regardless of URL query or forwarded headers', async t => {
  const seen = [];
  const relay = createDevRelay(config, { now: () => NOW }); const port = await listen(relay);
  t.after(() => new Promise(resolve => { relay.close(resolve); relay.closeAllConnections(); }));
  http.request = (options, callback) => {
    seen.push(options); const outgoing = new PassThrough();
    queueMicrotask(() => {
      const incoming = new PassThrough(); incoming.statusCode = 200; incoming.headers = {};
      callback(incoming); incoming.end('fixed backend response');
    }); return outgoing;
  };
  try {
    const path = '/api/models?upstream=http://evil.test:4200&port=4200';
    const response = await request(port, path, { headers: { 'X-Forwarded-Host': 'evil.test', Forwarded: 'host=evil.test' } });
    assert.equal(response.status, 200); assert.equal(seen.length, 1);
    assert.equal(seen[0].hostname, 'flujo-factored-2026.internal'); assert.equal(seen[0].port, 8081);
    assert.equal(seen[0].path, path); assert.equal(seen[0].headers.host, HOST);
    assert.equal(seen[0].headers['x-forwarded-host'], HOST); assert.equal(seen[0].headers.forwarded, undefined);
  } finally { http.request = nativeRequest; }
});

test('relay preserves explicit bad/empty auth, cookies and all nominated browser security inputs', async t => {
  const f = await fixture(t, { handler: (_req, res) => {
    res.writeHead(401, { 'Set-Cookie': '__Host-flujo-live-dev-session=synthetic; Path=/; Secure; HttpOnly; SameSite=Strict' }); res.end('leaf rejected caller');
  } });
  for (const authorization of [undefined, '', 'Basic invalid', 'Bearer invalid']) {
    const headers = { Origin: ORIGIN, Referer: ORIGIN + '/', Cookie: '__Host-flujo-live-dev-session=synthetic; bank_cookie=private',
      'Sec-Fetch-Site': 'same-origin', 'Sec-Fetch-Mode': 'cors', 'X-Flujo-User-Assertion': 'synthetic-signed-assertion',
      Connection: 'Authorization,Cookie,Origin,Referer,Sec-Fetch-Site,Sec-Fetch-Mode,X-Flujo-User-Assertion' };
    if (authorization !== undefined) headers.Authorization = authorization;
    const response = await request(f.port, '/api/flow', { method: 'POST', headers, body: '{"name":"synthetic"}' });
    assert.equal(response.status, 401); assert.ok(response.headers['set-cookie']);
    const forwarded = f.requests.at(-1);
    assert.equal(forwarded.headers.authorization, authorization);
    assert.equal(Object.hasOwn(forwarded.headers, 'authorization'), authorization !== undefined);
    assert.equal(forwarded.headers.cookie, headers.Cookie); assert.equal(forwarded.headers.origin, ORIGIN);
    assert.equal(forwarded.headers.referer, ORIGIN + '/'); assert.equal(forwarded.headers['sec-fetch-site'], 'same-origin');
    assert.equal(forwarded.headers['sec-fetch-mode'], 'cors'); assert.equal(forwarded.headers['x-flujo-user-assertion'], 'synthetic-signed-assertion');
    assert.equal(forwarded.body, '{"name":"synthetic"}');
  }
  assert.equal(f.requests.length, 4);
});

test('wrong hosts, null/foreign origins and absolute request targets never reach the backend', async t => {
  const f = await fixture(t);
  for (const headers of [{ Host: 'flujo-factored-2026.fly.dev' }, { Host: HOST + ':8443' }, { Host: 'evil.test' },
    { Origin: 'null' }, { Origin: 'https://flujo-factored-2026.fly.dev' }, { Origin: ORIGIN + ':8443' }]) {
    assert.equal((await request(f.port, '/api/models', { headers })).status, 403);
  }
  for (const path of ['//evil.test/path', 'http://evil.test/path']) assert.equal((await request(f.port, path)).status, 403);
  assert.equal(f.requests.length, 0);
});

test('health probes only the fixed login path and returns no backend content', async t => {
  let status = 200;
  const f = await fixture(t, { handler: (_req, res) => { res.writeHead(status); res.end('synthetic private backend diagnostic'); } });
  const healthy = await request(f.port, '/_relay/health');
  assert.equal(healthy.status, 200); assert.equal(healthy.body, 'ready');
  assert.equal(f.requests[0].url, '/_dev/login'); assert.equal(f.requests[0].headers.host, HOST);
  assert.equal((await request(f.port, '/_relay/health', { method: 'POST' })).status, 405);
  assert.equal(f.requests.length, 1); status = 401;
  const unhealthy = await request(f.port, '/_relay/health');
  assert.equal(unhealthy.status, 503); assert.equal(unhealthy.body, 'unavailable');
});

test('HTTP/SSE reaches the browser before upstream completion', async t => {
  let finish; const done = new Promise(resolve => { finish = resolve; });
  const f = await fixture(t, { handler: async (_req, res) => {
    res.writeHead(200, { 'Content-Type': 'text/event-stream' }); res.write('data: first\n\n'); await done; res.end('data: last\n\n');
  } });
  const incoming = await openStream(f.port); let remainder = '';
  const ended = new Promise(resolve => { incoming.on('data', chunk => { remainder += chunk; }); incoming.once('end', resolve); });
  finish(); await ended; assert.equal(remainder, 'data: last\n\n'); assert.equal(incoming.complete, true);
});

test('WebSocket relay is bidirectional and retains explicit caller credentials and metadata', async t => {
  const f = await fixture(t);
  const valid = await websocket(f.port, { authorization: 'Bearer explicit-caller' });
  assert.match(valid.output, /^HTTP\/1\.1 101/); assert.match(valid.output, /synthetic relay echo/);
  const forwarded = f.upgrades[0].headers;
  assert.equal(forwarded.authorization, 'Bearer explicit-caller'); assert.equal(forwarded.origin, ORIGIN);
  assert.equal(forwarded.cookie, '__Host-flujo-live-dev-session=synthetic'); assert.equal(forwarded.referer, ORIGIN + '/');
  assert.equal(forwarded['sec-fetch-site'], 'same-origin');
  for (const authorization of ['', 'Basic invalid']) assert.match((await websocket(f.port, { authorization })).output, /^HTTP\/1\.1 401/);
  const count = f.upgrades.length;
  assert.match((await websocket(f.port, { origin: 'https://evil.test' })).output, /^HTTP\/1\.1 403/);
  assert.match((await websocket(f.port, { host: 'evil.test' })).output, /^HTTP\/1\.1 403/);
  assert.equal(f.upgrades.length, count);
  const expiredLeaf = await fixture(t, { wsStatus: 410 });
  assert.match((await websocket(expiredLeaf.port)).output, /^HTTP\/1\.1 410/);
});

test('expiry closes active SSE/WS, returns410 for new traffic and cannot revive after clock rewind', async t => {
  let clock = NOW, upstreamClosed;
  const backendDisconnected = new Promise(resolve => { upstreamClosed = resolve; });
  const f = await fixture(t, { now: () => clock, expiresAt: NOW + 1000, handler: (_req, res) => {
    res.once('close', upstreamClosed); res.writeHead(200, { 'Content-Type': 'text/event-stream' }); res.write('data: first\n\n');
  } });
  const incoming = await openStream(f.port), ws = await websocket(f.port, { keepOpen: true });
  const streamClosed = new Promise(resolve => incoming.once('close', resolve)), socketClosed = once(ws.socket, 'close');
  clock += 1000;
  assert.equal((await request(f.port, '/_dev/login')).status, 410);
  await Promise.all([streamClosed, socketClosed, backendDisconnected]);
  assert.equal(incoming.complete, false);
  for (const path of ['/api/models', '/_dev/login', '/_relay/health']) assert.equal((await request(f.port, path)).status, 410);
  assert.match((await websocket(f.port)).output, /^HTTP\/1\.1 410/);
  clock = NOW - 1000;
  assert.equal((await request(f.port, '/api/models')).status, 410);
  assert.equal(f.requests.length, 1); assert.equal(f.upgrades.length, 1); assert.equal(f.relay.listening, true);
});

test('precise deadline timer closes a stream without a new request and blocks all later backend traffic', { timeout: 4000 }, async t => {
  let upstreamClosed; const backendDisconnected = new Promise(resolve => { upstreamClosed = resolve; });
  const f = await fixture(t, { now: Date.now, expiresAt: Date.now() + 200, handler: (_req, res) => {
    res.once('close', upstreamClosed); res.writeHead(200, { 'Content-Type': 'text/event-stream' }); res.write('data: first\n\n');
  } });
  const incoming = await openStream(f.port);
  await Promise.all([new Promise(resolve => incoming.once('close', resolve)), backendDisconnected]);
  assert.equal(incoming.complete, false); assert.equal(f.relay.listening, true);
  assert.equal((await request(f.port, '/_dev/login')).status, 410); assert.equal(f.requests.length, 1);
  const alreadyExpired = await fixture(t, { expiresAt: NOW - 1 });
  assert.equal((await request(alreadyExpired.port, '/api/models')).status, 410);
  assert.equal(alreadyExpired.requests.length, 0);
});
