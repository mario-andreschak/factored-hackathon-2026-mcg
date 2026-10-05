import http from 'node:http';
import { pathToFileURL } from 'node:url';

const HOP = new Set(['connection', 'proxy-connection', 'keep-alive', 'transfer-encoding',
  'te', 'trailer', 'upgrade', 'proxy-authenticate', 'proxy-authorization']);
const BACKEND = 'flujo-factored-2026.internal';
const PUBLIC_HOST = 'flujo-factored-dev-2026.fly.dev';

export function readRelayConfig(env = process.env) {
  if (env.FLUJO_DEV_RELAY_HOST !== PUBLIC_HOST) throw new Error('Invalid development relay hostname.');
  const expiresAt = Date.parse(env.FLUJO_DEV_RELAY_EXPIRES_AT);
  if (!Number.isFinite(expiresAt) || expiresAt <= 0
    || new Date(expiresAt).toISOString() !== env.FLUJO_DEV_RELAY_EXPIRES_AT) {
    throw new Error('A UTC development expiry is required.');
  }
  return { host: PUBLIC_HOST, expiresAt };
}

function relayHeaders(req, upgrade = false) {
  const headers = { ...req.headers };
  const nominated = String(req.headers.connection || '').split(',').map(name => name.trim().toLowerCase());
  for (const name of [...HOP, ...nominated]) delete headers[name];
  for (const name of Object.keys(headers)) if (name === 'forwarded' || name.startsWith('x-forwarded-')) delete headers[name];
  // The authenticated leaf must see every original security input. In
  // particular, an explicit bad/empty Authorization may never become absent.
  for (const name of ['authorization', 'cookie', 'origin', 'referer', 'x-flujo-user-assertion']) {
    if (Object.hasOwn(req.headers, name)) headers[name] = req.headers[name];
  }
  for (const name of Object.keys(req.headers)) if (name.startsWith('sec-fetch-')) headers[name] = req.headers[name];
  headers.host = req.headers.host;
  headers['x-forwarded-host'] = req.headers.host;
  headers['x-forwarded-proto'] = 'https';
  if (upgrade) { headers.connection = 'Upgrade'; headers.upgrade = req.headers.upgrade; }
  return headers;
}
function responseHeaders(response, upgrade = false) {
  const headers = { ...response.headers };
  const nominated = String(headers.connection || '').split(',').map(name => name.trim().toLowerCase());
  for (const name of [...HOP, ...nominated]) delete headers[name];
  if (upgrade) { headers.connection = 'Upgrade'; headers.upgrade = response.headers.upgrade; }
  return headers;
}
function plain(res, status, body) {
  res.writeHead(status, { 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'no-store',
    'x-content-type-options': 'nosniff', 'x-frame-options': 'DENY' });
  res.end(body);
}
function rejectSocket(socket, status) {
  socket.on('error', () => {});
  socket.end(`HTTP/1.1 ${status} Rejected\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`);
}

export function createDevRelay(config, { upstreamHost = BACKEND, upstreamPort = 8081, now = Date.now } = {}) {
  // Overrides are for local regression fixtures only; the executable always
  // uses this fixed private backend. No URL, header, or query selects a target.
  if (config.host !== PUBLIC_HOST || !Number.isFinite(config.expiresAt) || config.expiresAt <= 0
    || ![BACKEND, '127.0.0.1', '::1'].includes(upstreamHost)
    || !Number.isInteger(upstreamPort) || upstreamPort < 1 || upstreamPort > 65535
    || (upstreamHost === BACKEND && upstreamPort !== 8081)) throw new Error('Invalid fixed development relay configuration.');
  const connections = new Set();
  let hasExpired = false;
  const expired = () => {
    if (hasExpired || now() >= config.expiresAt) {
      hasExpired = true;
      for (const connection of connections) connection.destroy();
    }
    return hasExpired;
  };
  const track = connection => { connections.add(connection); connection.once('close', () => connections.delete(connection)); };
  const allowed = req => req.headers.host?.toLowerCase() === config.host
    && req.url?.startsWith('/') && !req.url.startsWith('//')
    && (!req.headers.origin || req.headers.origin === `https://${config.host}`);
  const options = (req, upgrade = false) => ({ hostname: upstreamHost, port: upstreamPort,
    method: req.method, path: req.url, headers: relayHeaders(req, upgrade) });
  const server = http.createServer((req, res) => {
    if (!allowed(req)) { plain(res, 403, 'Invalid development request.'); return; }
    if (expired()) { plain(res, 410, 'Temporary development access has ended.'); return; }
    track(res);
    if (req.url === '/_relay/health') {
      if (req.method !== 'GET') { plain(res, 405, 'Method not allowed'); return; }
      const probe = http.get({ hostname: upstreamHost, port: upstreamPort, path: '/_dev/login',
        headers: { host: config.host }, timeout: 4000 }, incoming => {
        incoming.resume(); plain(res, incoming.statusCode === 200 ? 200 : 503, incoming.statusCode === 200 ? 'ready' : 'unavailable');
      });
      probe.once('timeout', () => probe.destroy());
      probe.once('error', () => { if (!res.headersSent) plain(res, 503, 'unavailable'); });
      res.once('close', () => { if (!res.writableFinished) probe.destroy(); });
      return;
    }
    const outgoing = http.request(options(req), incoming => {
      res.writeHead(incoming.statusCode || 502, responseHeaders(incoming));
      incoming.pipe(res); incoming.once('error', () => res.destroy());
    });
    outgoing.once('error', () => { if (!res.headersSent) plain(res, 502, 'Development worker unavailable.'); else res.destroy(); });
    req.once('aborted', () => outgoing.destroy());
    res.once('close', () => { if (!res.writableFinished) outgoing.destroy(); });
    req.pipe(outgoing);
  });
  server.on('upgrade', (req, socket, head) => {
    if (!allowed(req)) { rejectSocket(socket, 403); return; }
    if (expired()) { rejectSocket(socket, 410); return; }
    if (String(req.headers.upgrade).toLowerCase() !== 'websocket') { rejectSocket(socket, 403); return; }
    track(socket);
    const outgoing = http.request(options(req, true));
    outgoing.once('upgrade', (incoming, upstream, upstreamHead) => {
      const lines = [`HTTP/${incoming.httpVersion} ${incoming.statusCode} ${incoming.statusMessage}`];
      for (const [name, value] of Object.entries(responseHeaders(incoming, true))) {
        for (const item of Array.isArray(value) ? value : [value]) if (item !== undefined) lines.push(`${name}: ${item}`);
      }
      socket.write(lines.join('\r\n') + '\r\n\r\n');
      if (upstreamHead.length) socket.write(upstreamHead);
      if (head.length) upstream.write(head);
      socket.pipe(upstream).pipe(socket);
      socket.once('error', () => upstream.destroy()); upstream.once('error', () => socket.destroy());
      socket.once('close', () => upstream.destroy()); upstream.once('close', () => socket.destroy());
    });
    outgoing.once('response', incoming => { incoming.resume(); rejectSocket(socket, [401, 410].includes(incoming.statusCode) ? incoming.statusCode : 403); });
    outgoing.once('error', () => socket.destroy()); socket.once('error', () => outgoing.destroy());
    socket.once('close', () => outgoing.destroy()); outgoing.end();
  });
  // Expiry is irreversible and closes active traffic at the precise deadline.
  // New requests retain their own response socket so they can receive 410.
  let deadlineTimer;
  const armDeadline = () => {
    if (expired()) return;
    deadlineTimer = setTimeout(armDeadline, Math.min(Math.max(config.expiresAt - now(), 1), 2_147_483_647));
    deadlineTimer.unref();
  };
  armDeadline();
  server.once('close', () => { clearTimeout(deadlineTimer); for (const connection of connections) connection.destroy(); });
  server.requestTimeout = 30_000; server.headersTimeout = 15_000;
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const server = createDevRelay(readRelayConfig());
    server.on('error', () => { console.error('Development relay failed to listen.'); process.exit(1); });
    server.listen(8080, '::', () => console.log('Temporary development relay listening.'));
    for (const signal of ['SIGTERM', 'SIGINT']) process.once(signal, () => {
      server.close(() => process.exit(0)); server.closeAllConnections();
      setTimeout(() => process.exit(0), 5000).unref();
    });
  } catch { console.error('Development relay configuration is invalid.'); process.exitCode = 1; }
}
