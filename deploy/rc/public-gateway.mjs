import http from 'node:http';
import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto';
import { pathToFileURL } from 'node:url';

const COOKIE = '__Host-rc-visitor';
const SESSION_SECONDS = 8 * 60 * 60;
const HOP_HEADERS = new Set(['connection', 'proxy-connection', 'keep-alive', 'transfer-encoding',
  'te', 'trailer', 'upgrade', 'proxy-authenticate', 'proxy-authorization']);

function readOrigin(value) {
  let url;
  try { url = new URL(value); } catch { throw new Error('RC_PUBLIC_ORIGIN must be an HTTPS origin'); }
  if (url.protocol !== 'https:' || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('RC_PUBLIC_ORIGIN must be an HTTPS origin');
  }
  return url.origin;
}

export function readConfig(env = process.env) {
  const publicOrigin = readOrigin(env.RC_PUBLIC_ORIGIN || '');
  const demoCode = env.RC_DEMO_CODE;
  if (typeof demoCode !== 'string' || demoCode.length < 1 || demoCode.length > 256) {
    throw new Error('RC_DEMO_CODE must be configured');
  }
  const cookieSecret = env.RC_COOKIE_SECRET;
  if (typeof cookieSecret !== 'string' || Buffer.byteLength(cookieSecret) < 32) {
    throw new Error('RC_COOKIE_SECRET must contain at least 32 bytes');
  }
  const avatarToken = env.AVATAR_ACCESS_GATE_TOKEN;
  if (typeof avatarToken !== 'string' || !/^[a-zA-Z0-9_-]{32,256}$/.test(avatarToken)) {
    throw new Error('AVATAR_ACCESS_GATE_TOKEN must be a private gateway token');
  }
  return { publicOrigin, publicHost: new URL(publicOrigin).host.toLowerCase(), demoCode, cookieSecret, avatarToken };
}

function equal(left, right) {
  const a = Buffer.from(String(left));
  const b = Buffer.from(String(right));
  return a.length === b.length && timingSafeEqual(a, b);
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
}

function plain(res, status, text) {
  res.writeHead(status, { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff' });
  res.end(text);
}

function landing(res, failed = false) {
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store',
    'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'same-origin' });
  res.end(`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Savia demo</title><style>body{font:16px system-ui;margin:0;min-height:100vh;display:grid;place-items:center;background:#10251f;color:#f4f1e8}main{width:min(25rem,82vw);padding:2rem;border:1px solid #49665c;border-radius:1rem}label{display:block;margin:1rem 0}input,button{box-sizing:border-box;width:100%;padding:.8rem;margin-top:.4rem;border:1px solid #789587;border-radius:.4rem;font:inherit}button{background:#b6e2ad;color:#10251f;border:0;cursor:pointer}.notice{color:#cee2d5}.error{color:#ffb5a8}</style><main><h1>Savia</h1><p class="notice">Fictional demonstration. This experience uses invented people, accounts, and transactions. Do not enter real personal or financial information.</p>${failed ? '<p class="error">That demo code was not accepted.</p>' : ''}<form method="post" action="/_rc/enter"><label>Demo code<input name="code" autocomplete="off" required maxlength="256"></label><button type="submit">Enter demo</button></form></main></html>`);
}

function cookieValue(req) {
  return String(req.headers.cookie || '').split(';').map(item => item.trim())
    .find(item => item.startsWith(`${COOKIE}=`))?.slice(COOKIE.length + 1) || '';
}

function sessionCookie(value, maxAge = SESSION_SECONDS) {
  return `${COOKIE}=${value}; Path=/; Max-Age=${maxAge}; HttpOnly; Secure; SameSite=Strict`;
}

function stripVisitorCookie(cookie) {
  const kept = String(cookie || '').split(';').filter(item => item.trim().split('=')[0] !== COOKIE).join(';').trim();
  return kept || undefined;
}

function forwardHeaders(req, config, upgrade = false) {
  const headers = { ...req.headers };
  const connectionHeaders = String(req.headers.connection || '').split(',').map(item => item.trim().toLowerCase());
  for (const name of [...HOP_HEADERS, ...connectionHeaders]) delete headers[name];
  for (const name of Object.keys(headers)) {
    if (name.startsWith('x-forwarded-')) delete headers[name];
  }
  delete headers.forwarded;
  delete headers['x-avatar-gateway-token'];
  if (req.headers.origin !== undefined) headers.origin = req.headers.origin;
  if (req.headers.referer !== undefined) headers.referer = req.headers.referer;
  const cookie = stripVisitorCookie(headers.cookie);
  if (cookie) headers.cookie = cookie; else delete headers.cookie;
  // The upstream validates Origin against its public origin, so retain the
  // caller's Origin and present the configured public host to the app.
  headers.host = config.publicHost;
  headers['x-forwarded-host'] = config.publicHost;
  headers['x-forwarded-proto'] = 'https';
  headers['x-forwarded-for'] = req.socket.remoteAddress || '';
  headers['x-avatar-gateway-token'] = config.avatarToken;
  if (upgrade) { headers.connection = 'Upgrade'; headers.upgrade = req.headers.upgrade; }
  return headers;
}

function cleanResponseHeaders(response) {
  const headers = { ...response.headers };
  const nominated = String(response.headers.connection || '').split(',').map(item => item.trim().toLowerCase());
  for (const name of [...HOP_HEADERS, ...nominated]) delete headers[name];
  return headers;
}

async function readCode(req) {
  if (!/^application\/x-www-form-urlencoded(?:\s*;|$)/i.test(req.headers['content-type'] || '')) throw new Error('invalid_content_type');
  let size = 0;
  const chunks = [];
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 8192) throw new Error('body_too_large');
    chunks.push(chunk);
  }
  return new URLSearchParams(Buffer.concat(chunks).toString('utf8')).get('code') || '';
}

export function createGateway(config, options = {}) {
  const avatarPort = options.avatarPort ?? 43941;
  const pythonPort = options.pythonPort ?? 43900;
  const now = options.now ?? Date.now;
  const signing = payload => createHmac('sha256', config.cookieSecret).update(payload).digest('base64url');
  const mintSession = () => {
    const payload = Buffer.from(JSON.stringify({ exp: Math.floor(now() / 1000) + SESSION_SECONDS,
      nonce: randomBytes(16).toString('base64url') })).toString('base64url');
    return `${payload}.${signing(payload)}`;
  };
  const checkSession = req => {
    const value = cookieValue(req);
    if (!value || value.length > 1024) return false;
    const [payload, signature, extra] = value.split('.');
    if (!payload || !signature || extra || !equal(signature, signing(payload))) return false;
    try {
      const parsed = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'));
      const seconds = Math.floor(now() / 1000);
      return Number.isInteger(parsed.exp) && parsed.exp > seconds && parsed.exp <= seconds + SESSION_SECONDS
        && typeof parsed.nonce === 'string' && parsed.nonce.length >= 16;
    } catch { return false; }
  };
  const validHost = req => String(req.headers.host || '').toLowerCase() === config.publicHost;
  const sameOrigin = req => req.headers.origin === config.publicOrigin
    && (!req.headers['sec-fetch-site'] || req.headers['sec-fetch-site'] === 'same-origin');

  const proxy = (req, res) => {
    const upstream = http.request({ hostname: '127.0.0.1', port: avatarPort, method: req.method,
      path: req.url, headers: forwardHeaders(req, config) }, response => {
      res.writeHead(response.statusCode || 502, cleanResponseHeaders(response));
      response.pipe(res);
      response.on('error', () => res.destroy());
    });
    upstream.on('error', () => { if (!res.headersSent) plain(res, 502, 'Avatar service unavailable'); else res.destroy(); });
    req.on('aborted', () => upstream.destroy());
    res.on('close', () => { if (!res.writableFinished) upstream.destroy(); });
    req.pipe(upstream);
  };

  const probe = (port, headers) => new Promise(resolve => {
    const request = http.get({ hostname: '127.0.0.1', port, path: '/healthz', headers, timeout: 2500 }, response => {
      const ok = response.statusCode === 200;
      response.resume();
      response.on('end', () => resolve(ok));
      response.on('error', () => resolve(false));
    });
    request.on('timeout', () => request.destroy());
    request.on('error', () => resolve(false));
  });
  const health = async res => {
    const [python, avatar] = await Promise.all([
      probe(pythonPort, { host: config.publicHost }),
      probe(avatarPort, { host: config.publicHost, 'x-avatar-gateway-token': config.avatarToken }),
    ]);
    const ready = python && avatar;
    res.writeHead(ready ? 200 : 503, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff' });
    res.end(JSON.stringify({ status: ready ? 'ok' : 'unavailable', python, avatar }));
  };

  const server = http.createServer(async (req, res) => {
    let pathname;
    try { pathname = new URL(req.url, config.publicOrigin).pathname; } catch { plain(res, 400, 'Bad request'); return; }
    if (pathname === '/healthz' && req.method === 'GET') { await health(res); return; }
    if (!validHost(req)) { plain(res, 421, 'Misdirected request'); return; }
    if (pathname === '/_rc/enter') {
      if (req.method !== 'POST') { plain(res, 405, 'Method not allowed'); return; }
      if (!sameOrigin(req)) { plain(res, 403, 'Same-origin request required'); return; }
      try {
        const code = await readCode(req);
        if (!equal(code, config.demoCode)) { landing(res, true); return; }
        res.writeHead(303, { Location: '/', 'Cache-Control': 'no-store', 'Set-Cookie': sessionCookie(mintSession()),
          'X-Content-Type-Options': 'nosniff' });
        res.end();
      } catch { plain(res, 400, 'Invalid form submission'); }
      return;
    }
    if (checkSession(req)) { proxy(req, res); return; }
    if (pathname === '/' && req.method === 'GET') { landing(res); return; }
    plain(res, 401, 'Demo access required');
  });

  server.on('upgrade', (req, socket, head) => {
    if (!validHost(req) || !checkSession(req)) {
      socket.end('HTTP/1.1 401 Unauthorized\r\nConnection: close\r\nContent-Length: 0\r\n\r\n'); return;
    }
    const upstream = http.request({ hostname: '127.0.0.1', port: avatarPort, method: req.method,
      path: req.url, headers: forwardHeaders(req, config, true) });
    upstream.on('upgrade', (response, upstreamSocket, upstreamHead) => {
      const headers = cleanResponseHeaders(response);
      headers.connection = 'Upgrade';
      headers.upgrade = response.headers.upgrade || 'websocket';
      const lines = [`HTTP/1.1 ${response.statusCode || 101} ${response.statusMessage || 'Switching Protocols'}`,
        ...Object.entries(headers).flatMap(([name, value]) => (Array.isArray(value) ? value : [value]).map(item => `${name}: ${item}`)), '', ''];
      socket.write(lines.join('\r\n'));
      if (head.length) upstreamSocket.write(head);
      if (upstreamHead.length) socket.write(upstreamHead);
      socket.pipe(upstreamSocket).pipe(socket);
    });
    upstream.on('response', response => {
      socket.end(`HTTP/1.1 ${response.statusCode || 502} ${response.statusMessage || 'Bad Gateway'}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`);
      response.resume();
    });
    upstream.on('error', () => socket.end('HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\nContent-Length: 0\r\n\r\n'));
    socket.on('close', () => upstream.destroy());
    upstream.end();
  });
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  let config;
  try { config = readConfig(); } catch (error) {
    console.error(`RC public gateway configuration error: ${error.message}`);
    process.exit(1);
  }
  const server = createGateway(config);
  server.on('error', () => { console.error('RC public gateway failed to listen'); process.exit(1); });
  server.listen(8080, '0.0.0.0', () => console.log('RC public gateway listening on port 8080'));
}
