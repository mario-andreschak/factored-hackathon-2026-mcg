import http from 'node:http';
import { createHash, createHmac, randomBytes, timingSafeEqual } from 'node:crypto';
import { pathToFileURL } from 'node:url';

// Private demo ingress. The main public listener always reaches Savia.
// Development access uses a separate hostname and authentication gateway.
const COOKIE = '__Host-savia-fly-session';
const SESSION_SECONDS = 12 * 60 * 60;
const HOP_HEADERS = new Set(['connection', 'proxy-connection', 'keep-alive', 'transfer-encoding',
  'te', 'trailer', 'upgrade', 'proxy-authenticate', 'proxy-authorization']);

function authority(value) {
  if (typeof value !== 'string' || value.length > 512 || /[\s/\\?#@,]/.test(value)) return null;
  try {
    const parsed = new URL(`https://${value}`);
    if (parsed.username || parsed.password || parsed.pathname !== '/' || parsed.search || parsed.hash) return null;
    return parsed.host.toLowerCase();
  } catch { return null; }
}

export function readConfig(env = process.env) {
  const password = env.FLUJO_FLY_PASSWORD;
  if (typeof password !== 'string' || password.length < 24) {
    throw new Error('FLUJO_FLY_PASSWORD must contain at least 24 characters');
  }
  const username = env.FLUJO_FLY_USERNAME || 'savia';
  if (/[:\r\n\0]/.test(username) || username.length > 128) throw new Error('Invalid FLUJO_FLY_USERNAME');
  const mainHost = authority(env.FLUJO_FLY_MAIN_HOST);
  if (!mainHost || mainHost !== env.FLUJO_FLY_MAIN_HOST?.toLowerCase()) {
    throw new Error('FLUJO_FLY_MAIN_HOST must be a canonical host authority without a scheme');
  }
  const workerToken = env.FLUJO_SNAPSHOT_CONTROL_TOKEN;
  if (typeof workerToken !== 'string' || workerToken.length < 16 || /\s/.test(workerToken)) {
    throw new Error('FLUJO_SNAPSHOT_CONTROL_TOKEN is required for private worker readiness');
  }
  const configuredDevHost = authority(env.FLUJO_DEV_UI_HOST);
  const devUiHost = configuredDevHost?.endsWith('.fly.dev') && !configuredDevHost.includes(':')
    ? configuredDevHost : 'flujo-factored-dev-2026.fly.dev';
  return { password, username, mainHost, workerToken, devUiHost };
}

function equal(left, right) {
  return timingSafeEqual(createHash('sha256').update(left).digest(), createHash('sha256').update(right).digest());
}

function basicCredentials(value) {
  if (typeof value !== 'string' || value.length > 8192 || !/^Basic [a-zA-Z0-9+/]+={0,2}$/i.test(value)) return null;
  const decoded = Buffer.from(value.slice(6), 'base64').toString('utf8');
  const colon = decoded.indexOf(':');
  if (colon < 0) return null;
  return [decoded.slice(0, colon), decoded.slice(colon + 1)];
}

function sessionCookie(value, maxAge = SESSION_SECONDS) {
  return `${COOKIE}=${value}; Path=/; Max-Age=${maxAge}; HttpOnly; Secure; SameSite=Strict`;
}

function safeNext(raw) {
  if (typeof raw !== 'string' || !raw.startsWith('/') || raw.startsWith('//') || /[\\\r\n\0]/.test(raw)) return '/';
  try {
    const parsed = new URL(raw, 'https://gateway.invalid');
    if (parsed.origin !== 'https://gateway.invalid' || parsed.pathname.startsWith('/_fly/')) return '/';
    return parsed.pathname + parsed.search;
  } catch { return '/'; }
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
}

function loginPage(next, failed = false) {
  return `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sign in to Savia</title><style>body{font:16px system-ui;margin:0;min-height:100vh;display:grid;place-items:center;background:#111827;color:#e5e7eb}main{width:min(22rem,80vw);padding:2rem}h1{font-size:1.5rem}label{display:block;margin:1rem 0}input,button{box-sizing:border-box;width:100%;padding:.8rem;margin-top:.4rem;border:1px solid #4b5563;border-radius:.4rem;font:inherit}button{background:#6366f1;color:white;border:0;cursor:pointer}.error{color:#fca5a5}</style><main><h1>Sign in to Savia</h1><p>Private banking demo</p>${failed ? '<p class="error">Sign-in failed. Check your credentials.</p>' : ''}<form method="post" action="/_fly/login?next=${escapeHtml(encodeURIComponent(next))}"><label>Username<input name="username" autocomplete="username" required maxlength="128"></label><label>Password<input name="password" type="password" autocomplete="current-password" required maxlength="4096"></label><button type="submit">Sign in</button></form></main></html>`;
}

function plain(res, status, text) {
  res.writeHead(status, { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff' });
  res.end(text);
}

function rejectSocket(socket, status = 401) {
  socket.end(`HTTP/1.1 ${status} ${status === 401 ? 'Unauthorized' : 'Forbidden'}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`);
}

function cookiesWithoutSession(cookie) {
  if (typeof cookie !== 'string') return undefined;
  const kept = cookie.split(';').filter(pair => ![COOKIE, '__Host-flujo-live-dev-session']
    .includes(pair.trim().split('=')[0])).join(';').trim();
  return kept || undefined;
}

function forwardHeaders(req, upgrade = false) {
  const headers = { ...req.headers };
  const connectionHeaders = String(req.headers.connection || '').split(',').map(value => value.trim().toLowerCase());
  for (const name of [...HOP_HEADERS, ...connectionHeaders]) delete headers[name];
  delete headers['x-flujo-fly-authorization'];
  delete headers.forwarded;
  if (/^Basic /i.test(headers.authorization || '')) delete headers.authorization;
  // Origin/Referer are security inputs in FLUJO. A caller-supplied Connection
  // token must not remove them before the application checks the request.
  for (const name of ['origin', 'referer']) {
    if (req.headers[name] !== undefined) headers[name] = req.headers[name];
  }
  if (req.headers.authorization && !/^Basic /i.test(req.headers.authorization)) {
    headers.authorization = req.headers.authorization;
  }
  const cookie = cookiesWithoutSession(headers.cookie);
  if (cookie) headers.cookie = cookie; else delete headers.cookie;
  // Do not let a caller override the effective origin used by FLUJO's sandbox allocation.
  headers.host = req.headers.host;
  headers['x-forwarded-host'] = req.headers.host;
  headers['x-forwarded-proto'] = 'https';
  headers['x-forwarded-for'] = req.socket.remoteAddress || '';
  if (upgrade) { headers.connection = 'Upgrade'; headers.upgrade = req.headers.upgrade; }
  return headers;
}

function responseHeaders(res, upgrade = false) {
  const headers = { ...res.headers };
  const connectionHeaders = String(res.headers.connection || '').split(',').map(value => value.trim().toLowerCase());
  for (const name of [...HOP_HEADERS, ...connectionHeaders]) delete headers[name];
  if (upgrade) { headers.connection = 'Upgrade'; headers.upgrade = res.headers.upgrade; }
  return headers;
}

async function readForm(req) {
  let size = 0;
  const chunks = [];
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 8192) throw new Error('body_too_large');
    chunks.push(chunk);
  }
  return new URLSearchParams(Buffer.concat(chunks).toString('utf8'));
}

export function createGateway(config, options = {}) {
  // Keep upstream destinations loopback-only, including tests using ephemeral ports.
  const mainPort = options.mainPort ?? 8082;
  const workerPort = options.workerPort ?? 4200;
  const now = options.now ?? Date.now;
  const sessionKey = createHmac('sha256', config.password).update(`savia-fly-session-v1:${config.mainHost}`).digest();
  const signing = payload => createHmac('sha256', sessionKey).update(payload).digest('base64url');
  const mintSession = () => {
    const payload = Buffer.from(JSON.stringify({ exp: Math.floor(now() / 1000) + SESSION_SECONDS,
      nonce: randomBytes(16).toString('base64url') })).toString('base64url');
    return `${payload}.${signing(payload)}`;
  };
  const checkSession = req => {
    const candidate = String(req.headers.cookie || '').split(';').map(part => part.trim())
      .find(part => part.startsWith(`${COOKIE}=`))?.slice(COOKIE.length + 1);
    if (!candidate || candidate.length > 1024) return false;
    const [payload, signature, extra] = candidate.split('.');
    if (!payload || !signature || extra || !equal(signature, signing(payload))) return false;
    try {
      const parsed = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'));
      const seconds = Math.floor(now() / 1000);
      return Number.isInteger(parsed.exp) && parsed.exp > seconds && parsed.exp <= seconds + SESSION_SECONDS
        && typeof parsed.nonce === 'string';
    } catch { return false; }
  };
  const credentialsMatch = ([username, password] = []) => typeof username === 'string'
    && typeof password === 'string' && equal(username, config.username) && equal(password, config.password);
  const failures = new Map();
  const failureKey = req => req.socket.remoteAddress || 'unknown';
  const rateLimited = req => {
    const previous = failures.get(failureKey(req));
    return previous && previous.until > now() && previous.count >= 10;
  };
  const recordFailure = req => {
    const key = failureKey(req);
    const previous = failures.get(key);
    if (failures.size > 1000) {
      for (const [storedKey, entry] of failures) if (entry.until <= now()) failures.delete(storedKey);
      if (failures.size > 1000) failures.clear();
    }
    failures.set(key, { count: previous?.until > now() ? previous.count + 1 : 1,
      until: previous?.until > now() ? previous.until : now() + 60_000 });
  };
  const authentication = req => {
    const dedicated = req.headers['x-flujo-fly-authorization'];
    const auth = dedicated ?? (/^Basic /i.test(req.headers.authorization || '') ? req.headers.authorization : null);
    if (auth !== null) {
      if (rateLimited(req)) return { ok: false, limited: true };
      const credentials = basicCredentials(auth);
      if (!credentials || !credentialsMatch(credentials)) { recordFailure(req); return { ok: false }; }
      return { ok: true, method: 'basic', cookie: checkSession(req) ? null : sessionCookie(mintSession()) };
    }
    return { ok: checkSession(req), method: 'cookie' };
  };
  const targetFor = req => {
    const host = authority(req.headers.host);
    if (host === config.mainHost) return 'main';
    return null;
  };
  const upstreamOptions = (req, _target, upgrade = false) => ({ hostname: '127.0.0.1',
    port: mainPort, method: req.method, path: req.url,
    headers: forwardHeaders(req, upgrade) });
  const proxyHttp = (req, res, target, auth = {}) => {
    const upstream = http.request(upstreamOptions(req, target), response => {
      const headers = responseHeaders(response);
      if (target === 'main') {
        headers['x-frame-options'] = 'DENY';
        const policy = headers['content-security-policy'];
        headers['content-security-policy'] = [...(Array.isArray(policy) ? policy : policy ? [policy] : []),
          "frame-ancestors 'none'"];
      }
      if (auth.cookie) headers['set-cookie'] = [...(Array.isArray(headers['set-cookie']) ? headers['set-cookie']
        : headers['set-cookie'] ? [headers['set-cookie']] : []), auth.cookie];
      res.writeHead(response.statusCode || 502, headers);
      response.pipe(res);
      response.on('error', () => res.destroy());
    });
    upstream.on('error', () => { if (!res.headersSent) plain(res, 502, 'Upstream unavailable'); else res.destroy(); });
    req.on('aborted', () => upstream.destroy());
    res.on('close', () => { if (!res.writableFinished) upstream.destroy(); });
    req.pipe(upstream);
  };
  const probeJson = (port, path, headers, valid) => new Promise(resolve => {
    const request = http.get({ hostname: '127.0.0.1', port, path,
      headers, timeout: 3000 }, response => {
      if (response.statusCode !== 200) { response.resume(); resolve(false); return; }
      let bytes = 0;
      const chunks = [];
      response.on('data', chunk => {
        bytes += chunk.length;
        if (bytes > 65536) { response.destroy(); resolve(false); } else chunks.push(chunk);
      });
      response.on('end', () => {
        try { resolve(valid(JSON.parse(Buffer.concat(chunks).toString('utf8')))); } catch { resolve(false); }
      });
      response.on('error', () => resolve(false));
    });
    request.on('timeout', () => request.destroy());
    request.on('error', () => resolve(false));
  });
  const probe = async () => {
    const results = await Promise.all([
      probeJson(mainPort, '/healthz', { host: config.mainHost },
        value => value?.status === 'ok' && value.dataset_ready === true),
      probeJson(workerPort, '/api/worker/status', { host: '127.0.0.1:4200',
        authorization: `Bearer ${config.workerToken}` },
      value => value?.mode === 'worker' && value.state === 'ready'),
    ]);
    return results.every(Boolean);
  };
  const server = http.createServer(async (req, res) => {
    const target = targetFor(req);
    if (!target) { plain(res, 421, 'Unrecognized host'); return; }
    if (!req.url?.startsWith('/') || req.url.startsWith('//')) { plain(res, 400, 'Invalid request target'); return; }
    const url = new URL(req.url, `https://${config.mainHost}`);
    if (target === 'main' && url.pathname === '/_fly/health') {
      if (req.method !== 'GET' && req.method !== 'HEAD') { plain(res, 405, 'Method not allowed'); return; }
      const ready = await probe();
      plain(res, ready ? 200 : 503, ready ? 'ready' : 'unavailable');
      return;
    }
    if (target === 'main' && url.pathname === '/_fly/login') {
      const next = safeNext(url.searchParams.get('next'));
      if (req.method === 'POST') {
        if (req.headers.origin !== `https://${config.mainHost}`) { plain(res, 403, 'Forbidden'); return; }
        if (req.headers['content-type']?.split(';')[0] !== 'application/x-www-form-urlencoded') {
          plain(res, 415, 'Expected form submission'); return;
        }
        if (rateLimited(req)) { plain(res, 429, 'Try again later'); return; }
        let form;
        try { form = await readForm(req); } catch { plain(res, 413, 'Invalid form'); return; }
        if (credentialsMatch([form.get('username'), form.get('password')])) {
          res.writeHead(303, { Location: next, 'Set-Cookie': sessionCookie(mintSession()), 'Cache-Control': 'no-store' });
          res.end();
          return;
        }
        recordFailure(req);
      } else if (req.method !== 'GET') { plain(res, 405, 'Method not allowed'); return; }
      res.writeHead(req.method === 'POST' ? 401 : 200, { 'Content-Type': 'text/html; charset=utf-8',
        'Cache-Control': 'no-store', 'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
        // Native form navigations use the referrer policy when serializing
        // Origin. no-referrer makes their POST Origin null and fails our CSRF
        // check; same-origin preserves it without sharing referrers off-site.
        'Referrer-Policy': 'same-origin', 'X-Content-Type-Options': 'nosniff' });
      res.end(loginPage(next, req.method === 'POST'));
      return;
    }
    if (target === 'main' && url.pathname === '/_fly/logout') {
      if (req.method !== 'POST' || req.headers.origin !== `https://${config.mainHost}`) {
        plain(res, 403, 'Forbidden'); return;
      }
      res.writeHead(303, { Location: '/_fly/login', 'Set-Cookie': sessionCookie('', 0), 'Cache-Control': 'no-store' });
      res.end(); return;
    }
    if (url.pathname.startsWith('/_fly/')) { plain(res, 404, 'Not found'); return; }
    if (url.pathname === '/_dev/login') {
      if (req.method !== 'GET') { plain(res, 405, 'Method not allowed'); return; }
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store',
        'Referrer-Policy': 'same-origin', 'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'; base-uri 'none'" });
      res.end(`<!doctype html><html lang="en"><meta charset="utf-8"><title>FLUJO development access</title><h1>FLUJO development access has moved</h1><p><a href="https://${escapeHtml(config.devUiHost)}/_dev/login">Open the separate FLUJO development site</a></p><p><a href="/">Return to Savia</a></p></html>`);
      return;
    }
    if (url.pathname.startsWith('/_dev/') || /^\/(v1|mcp[^/]*)(?:\/|$)/.test(url.pathname)
      || url.pathname.startsWith('/_flujo/')) { plain(res, 404, 'Not found'); return; }
    const auth = authentication(req);
    if (!auth.ok) {
      if (!auth.limited && req.method === 'GET' && !/^\/(api|v1)(?:\/|$)/.test(url.pathname)
        && req.headers.accept?.includes('text/html')) {
        res.writeHead(303, { Location: `/_fly/login?next=${encodeURIComponent(safeNext(req.url))}`, 'Cache-Control': 'no-store' });
        res.end();
      } else { plain(res, auth.limited ? 429 : 401, auth.limited ? 'Try again later' : 'Authentication required'); }
      return;
    }
    if (target === 'main' && auth.method === 'cookie'
      && ((req.headers.origin && req.headers.origin !== `https://${config.mainHost}`)
        || (req.headers['sec-fetch-site'] && !['same-origin', 'none'].includes(req.headers['sec-fetch-site']))
        || (!['GET', 'HEAD', 'OPTIONS'].includes(req.method) && req.headers.origin !== `https://${config.mainHost}`))) {
      plain(res, 403, 'Forbidden'); return;
    }
    proxyHttp(req, res, target, auth);
  });
  server.on('upgrade', (req, socket, head) => {
    const target = targetFor(req);
    if (!target || !req.url?.startsWith('/') || req.url.startsWith('//') || req.url.startsWith('/_fly/') || req.url.startsWith('/_dev/')
      || /^\/(v1|mcp[^/]*)(?:\/|$)/.test(req.url) || req.url.startsWith('/_flujo/')) {
      rejectSocket(socket, 403); return;
    }
    const auth = authentication(req);
    if (!auth.ok) { rejectSocket(socket); return; }
    if (target === 'main' && auth.method === 'cookie' && req.headers.origin !== `https://${config.mainHost}`) {
      rejectSocket(socket, 403); return;
    }
    if (String(req.headers.upgrade).toLowerCase() !== 'websocket') { rejectSocket(socket, 403); return; }
    const upstream = http.request(upstreamOptions(req, target, true));
    upstream.on('upgrade', (response, upstreamSocket, upstreamHead) => {
      const headers = responseHeaders(response, true);
      if (auth.cookie) headers['set-cookie'] = [...(Array.isArray(headers['set-cookie']) ? headers['set-cookie'] : []), auth.cookie];
      const lines = [`HTTP/${response.httpVersion} ${response.statusCode} ${response.statusMessage}`];
      for (const [name, value] of Object.entries(headers)) {
        for (const item of Array.isArray(value) ? value : [value]) if (item !== undefined) lines.push(`${name}: ${item}`);
      }
      socket.write(lines.join('\r\n') + '\r\n\r\n');
      if (upstreamHead.length) socket.write(upstreamHead);
      if (head.length) upstreamSocket.write(head);
      socket.pipe(upstreamSocket).pipe(socket);
      socket.on('error', () => upstreamSocket.destroy());
      upstreamSocket.on('error', () => socket.destroy());
      socket.on('close', () => upstreamSocket.destroy());
      upstreamSocket.on('close', () => socket.destroy());
    });
    upstream.on('response', response => {
      response.resume();
      rejectSocket(socket, response.statusCode === 401 ? 401 : 403);
    });
    upstream.on('error', () => socket.destroy());
    socket.on('error', () => upstream.destroy());
    upstream.end();
  });
  server.requestTimeout = 30_000;
  server.headersTimeout = 15_000;
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const config = readConfig();
    const server = createGateway(config);
    const shutdown = code => {
      server.close(() => process.exit(code));
      server.closeAllConnections();
      setTimeout(() => process.exit(code), 5000).unref();
    };
    server.on('error', () => { console.error('Savia Fly gateway failed to listen'); shutdown(1); });
    server.listen(8080, '0.0.0.0', () => console.log('Savia Fly gateway listening on port 8080'));
    for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => shutdown(0));
  } catch (error) {
    // All configuration errors are fixed messages; credentials never enter logs.
    console.error(error.message);
    process.exitCode = 1;
  }
}
