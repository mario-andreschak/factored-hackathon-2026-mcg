import http from 'node:http';
import { createHash, createHmac, randomBytes, timingSafeEqual } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { createDevTraces } from './dev-traces.mjs';

const COOKIE = '__Host-flujo-live-dev-session';
const SESSION_SECONDS = 12 * 60 * 60;
const HOP = new Set(['connection', 'proxy-connection', 'keep-alive', 'transfer-encoding',
  'te', 'trailer', 'upgrade', 'proxy-authenticate', 'proxy-authorization']);
const USERNAMES = ['mario', 'gloria'];
const LOCAL = 'http://127.0.0.1:4200';

export function readDevConfig(env = process.env) {
  if (env.FLUJO_DEV_UI_ENABLED !== '1') throw new Error('Live Fly development access is disabled.');
  const configuredHost = env.FLUJO_DEV_UI_HOST;
  let host;
  try {
    const url = new URL(`https://${configuredHost}`);
    if (typeof configuredHost !== 'string' || /[\s/\\?#@,:]/.test(configuredHost) || url.host !== configuredHost.toLowerCase()
      || !url.host.endsWith('.fly.dev')
      || url.pathname !== '/' || url.username || url.password || url.port) throw new Error();
    host = url.host;
  } catch { throw new Error('Invalid live development host.'); }
  const expiresAt = Date.parse(env.FLUJO_DEV_UI_EXPIRES_AT);
  if (!Number.isFinite(expiresAt) || expiresAt <= 0
    || new Date(expiresAt).toISOString() !== env.FLUJO_DEV_UI_EXPIRES_AT) {
    throw new Error('A finite UTC development access deadline is required.');
  }
  const users = Object.fromEntries(USERNAMES.map(username => [username,
    env[`FLUJO_DEV_UI_${username.toUpperCase()}_PASSWORD`]]));
  if (USERNAMES.some(username => typeof users[username] !== 'string' || users[username].length < 24
    || users[username].length > 4096 || /[\r\n\0]/.test(users[username]))
    || users.mario === users.gloria) throw new Error('Distinct strong Mario and Gloria passwords are required.');
  const workerToken = env.FLUJO_SNAPSHOT_CONTROL_TOKEN;
  if (typeof workerToken !== 'string' || workerToken.length < 16 || /\s/.test(workerToken)) {
    throw new Error('Private worker control authentication is required.');
  }
  return { host, users, workerToken, expiresAt };
}

const equal = (left, right) => timingSafeEqual(createHash('sha256').update(left).digest(),
  createHash('sha256').update(right).digest());
const cookie = (value, maxAge = SESSION_SECONDS) => `${COOKIE}=${value}; Path=/; Max-Age=${maxAge}; HttpOnly; Secure; SameSite=Strict`;
const escape = value => value.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
function nextPath(raw) {
  if (typeof raw !== 'string' || !raw.startsWith('/') || raw.startsWith('//') || /[\\\r\n\0]/.test(raw)) return '/';
  try {
    const url = new URL(raw, 'https://dev.invalid');
    return url.origin === 'https://dev.invalid' && !url.pathname.startsWith('/_dev/') ? url.pathname + url.search : '/';
  } catch { return '/'; }
}
function plain(res, status, text) {
  res.writeHead(status, { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY' });
  res.end(text);
}
function rejectSocket(socket, status) {
  socket.on('error', () => {});
  socket.end(`HTTP/1.1 ${status} ${status === 401 ? 'Unauthorized' : status === 410 ? 'Gone' : 'Forbidden'}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n`);
}
function page(next, failed) {
  return `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Live Fly development</title><style>body{font:16px system-ui;margin:0;min-height:100vh;display:grid;place-items:center;background:#111827;color:#e5e7eb}main{width:min(25rem,80vw);padding:2rem}h1{font-size:1.5rem}label{display:block;margin:1rem 0}input,button{box-sizing:border-box;width:100%;padding:.8rem;margin-top:.4rem;border:1px solid #4b5563;border-radius:.4rem;font:inherit}button{background:#6366f1;color:white;border:0;cursor:pointer}.error{color:#fca5a5}</style><main><h1>FLUJO · Live Fly development</h1><p>Development access for Mario and Gloria.</p>${failed ? '<p class="error">Sign-in failed. Check your credentials.</p>' : ''}<form method="post" action="/_dev/login?next=${escape(encodeURIComponent(next))}"><label>Username<input name="username" autocomplete="username" placeholder="mario or gloria" required maxlength="128"></label><label>Password<input name="password" type="password" autocomplete="current-password" required maxlength="4096"></label><button type="submit">Sign in</button></form></main></html>`;
}
async function readForm(req) {
  const chunks = []; let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 8192) throw new Error('Invalid form.');
    chunks.push(chunk);
  }
  return new URLSearchParams(Buffer.concat(chunks).toString('utf8'));
}
function upstreamHeaders(req, config, upgrade) {
  const explicit = Object.hasOwn(req.headers, 'authorization');
  const headers = { ...req.headers };
  const nominated = String(headers.connection || '').split(',').map(name => name.trim().toLowerCase());
  for (const name of [...HOP, ...nominated]) delete headers[name];
  for (const name of Object.keys(headers)) if (name.startsWith('x-forwarded-') || name === 'forwarded') delete headers[name];
  // Browser sessions from both HTTPS ports must never reach the worker.
  delete headers.cookie;
  delete headers['x-flujo-fly-authorization'];
  headers.authorization = explicit ? req.headers.authorization : `Bearer ${config.workerToken}`;
  // Only authenticated, origin-checked requests acquire a local worker origin.
  headers.host = '127.0.0.1:4200';
  headers.origin = LOCAL;
  headers.referer = `${LOCAL}/`;
  headers['sec-fetch-site'] = 'same-origin';
  headers['x-forwarded-host'] = '127.0.0.1:4200';
  headers['x-forwarded-proto'] = 'http';
  headers['x-forwarded-for'] = '127.0.0.1';
  if (req.headers['x-flujo-user-assertion'] !== undefined) headers['x-flujo-user-assertion'] = req.headers['x-flujo-user-assertion'];
  if (upgrade) { headers.connection = 'Upgrade'; headers.upgrade = req.headers.upgrade; }
  return headers;
}
function responseHeaders(response, upgrade = false) {
  const headers = { ...response.headers };
  const nominated = String(headers.connection || '').split(',').map(name => name.trim().toLowerCase());
  for (const name of [...HOP, ...nominated]) delete headers[name];
  for (const name of Object.keys(headers)) if (name.startsWith('access-control-')) delete headers[name];
  // The worker cannot mint cookies for the shared public hostname.
  delete headers['set-cookie'];
  headers['x-frame-options'] = 'DENY';
  headers['cache-control'] = 'no-store';
  headers['referrer-policy'] = 'same-origin';
  headers['x-flujo-dev-target'] = 'Live Fly development';
  const policy = headers['content-security-policy'];
  headers['content-security-policy'] = [...(Array.isArray(policy) ? policy : policy ? [policy] : []), "frame-ancestors 'none'"];
  if (upgrade) { headers.connection = 'Upgrade'; headers.upgrade = response.headers.upgrade; }
  return headers;
}

export function createDevGateway(config, { upstreamPort = 4200, now = Date.now, traceHandler } = {}) {
  if (!Number.isInteger(upstreamPort) || upstreamPort < 1 || upstreamPort > 65535) throw new Error('Invalid private upstream port.');
  if (!Number.isFinite(config.expiresAt) || config.expiresAt <= 0) throw new Error('A finite development deadline is required.');
  const traces = traceHandler ?? createDevTraces({ redactValues: [...Object.values(config.users), config.workerToken] });
  const keys = Object.fromEntries(USERNAMES.map(username => [username,
    createHmac('sha256', config.users[username]).update(`flujo-live-dev-v1:${config.host}:${username}`).digest()]));
  const sign = (username, payload) => createHmac('sha256', keys[username]).update(payload).digest('base64url');
  const sessions = new Map();
  let expired = false;
  const revoke = nonce => {
    const session = sessions.get(nonce); sessions.delete(nonce);
    for (const connection of session?.connections ?? []) connection.destroy();
  };
  const isExpired = () => {
    if (expired || now() >= config.expiresAt) {
      expired = true;
      for (const nonce of sessions.keys()) revoke(nonce);
    }
    return expired;
  };
  const prune = () => {
    const seconds = Math.floor(now() / 1000);
    for (const [nonce, session] of sessions) if (session.exp <= seconds) revoke(nonce);
  };
  const mint = username => {
    prune();
    if (sessions.size >= 256) revoke(sessions.keys().next().value);
    const claims = { sub: username, exp: Math.min(Math.floor(now() / 1000) + SESSION_SECONDS, Math.floor(config.expiresAt / 1000)),
      nonce: randomBytes(24).toString('base64url') };
    sessions.set(claims.nonce, { ...claims, connections: new Set() });
    const payload = Buffer.from(JSON.stringify(claims)).toString('base64url');
    return `${payload}.${sign(username, payload)}`;
  };
  const authenticate = req => {
    prune();
    const pairs = String(req.headers.cookie || '').split(';').map(part => part.trim()).filter(part => part.startsWith(`${COOKIE}=`));
    if (pairs.length !== 1) return null;
    const candidate = pairs[0].slice(COOKIE.length + 1);
    if (candidate.length > 1024) return null;
    const [payload, signature, extra] = candidate.split('.');
    if (!payload || !signature || extra) return null;
    try {
      const claims = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'));
      if (!USERNAMES.includes(claims.sub) || !equal(signature, sign(claims.sub, payload))) return null;
      const session = sessions.get(claims.nonce);
      return session && session.sub === claims.sub && session.exp === claims.exp ? session : null;
    } catch { return null; }
  };
  const browserAllowed = (req, { requireOrigin = false } = {}) => {
    const origin = `https://${req.headers.host.toLowerCase()}`;
    if ((requireOrigin && req.headers.origin !== origin) || (req.headers.origin && req.headers.origin !== origin)) return false;
    if (req.headers['sec-fetch-site'] && !['same-origin', 'none'].includes(req.headers['sec-fetch-site'])) return false;
    if (req.headers.referer) {
      try { if (new URL(req.headers.referer).origin !== origin) return false; } catch { return false; }
    }
    return true;
  };
  const route = req => {
    const host = req.headers.host?.toLowerCase();
    if (host !== config.host) return { status: 421 };
    if (!req.url?.startsWith('/') || req.url.startsWith('//')) return { status: 400 };
    try { return { url: new URL(req.url, `https://${host}`) }; } catch { return { status: 400 }; }
  };
  const bankAllowed = (req, url) => !url.pathname.startsWith('/v1/banking/')
    || (/^Bearer [^\s]+$/.test(req.headers.authorization || '') && Boolean(req.headers['x-flujo-user-assertion']));
  const failures = new Map();
  const failureKey = (req, username) => `${req.socket.remoteAddress}|${USERNAMES.includes(username) ? username : 'unknown'}`;
  const limited = (req, username) => { const entry = failures.get(failureKey(req, username)); return entry?.until > now() && entry.count >= 10; };
  const fail = (req, username) => {
    if (failures.size >= 1000) for (const [key, entry] of failures) if (entry.until <= now()) failures.delete(key);
    if (failures.size >= 1000) failures.delete(failures.keys().next().value);
    const key = failureKey(req, username), previous = failures.get(key);
    failures.set(key, { count: previous?.until > now() ? previous.count + 1 : 1,
      until: previous?.until > now() ? previous.until : now() + 60_000 });
  };
  const attach = (session, connection) => {
    session.connections.add(connection);
    connection.once('close', () => session.connections.delete(connection));
  };
  const options = (req, upgrade = false) => ({ hostname: '127.0.0.1', port: upstreamPort,
    method: req.method, path: req.url, headers: upstreamHeaders(req, config, upgrade) });
  const server = http.createServer(async (req, res) => {
    const parsed = route(req);
    if (parsed.status) { plain(res, parsed.status, 'Invalid development request.'); return; }
    if (isExpired()) { plain(res, 410, 'Development access has expired'); return; }
    const { url } = parsed;
    if (url.pathname === '/_dev/login') {
      const next = nextPath(url.searchParams.get('next'));
      if (req.method === 'POST') {
        if (!browserAllowed(req, { requireOrigin: true })) { plain(res, 403, 'Forbidden'); return; }
        if (req.headers['content-type']?.split(';')[0] !== 'application/x-www-form-urlencoded') { plain(res, 415, 'Expected form submission'); return; }
        let form;
        try { form = await readForm(req); } catch { plain(res, 413, 'Invalid form'); return; }
        const username = form.get('username'), password = form.get('password');
        if (limited(req, username)) { plain(res, 429, 'Try again later'); return; }
        if (USERNAMES.includes(username) && typeof password === 'string' && equal(password, config.users[username])) {
          failures.delete(failureKey(req, username));
          const value = mint(username);
          const maxAge = Math.min(SESSION_SECONDS, Math.max(0, Math.floor(config.expiresAt / 1000) - Math.floor(now() / 1000)));
          res.writeHead(303, { Location: next, 'Set-Cookie': cookie(value, maxAge), 'Cache-Control': 'no-store' });
          res.end(); return;
        }
        fail(req, username);
      } else if (req.method !== 'GET') { plain(res, 405, 'Method not allowed'); return; }
      else if (req.headers.origin && req.headers.origin !== `https://${req.headers.host.toLowerCase()}`) { plain(res, 403, 'Forbidden'); return; }
      res.writeHead(req.method === 'POST' ? 401 : 200, { 'Content-Type': 'text/html; charset=utf-8',
        'Cache-Control': 'no-store', 'Referrer-Policy': 'same-origin', 'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'" });
      res.end(page(next, req.method === 'POST')); return;
    }
    const session = authenticate(req);
    if (!session) {
      if (req.method === 'GET' && req.headers.accept?.includes('text/html') && !url.pathname.startsWith('/api/') && !url.pathname.startsWith('/v1/')) {
        res.writeHead(303, { Location: `/_dev/login?next=${encodeURIComponent(nextPath(req.url))}`, 'Cache-Control': 'no-store' }); res.end();
      } else plain(res, 401, 'Development sign-in required');
      return;
    }
    if (!browserAllowed(req, { requireOrigin: !['GET', 'HEAD', 'OPTIONS'].includes(req.method) })) { plain(res, 403, 'Forbidden'); return; }
    if (url.pathname === '/_dev/logout') {
      if (req.method !== 'POST') { plain(res, 405, 'Method not allowed'); return; }
      revoke(session.nonce);
      res.writeHead(303, { Location: '/_dev/login', 'Set-Cookie': cookie('', 0), 'Cache-Control': 'no-store' }); res.end(); return;
    }
    if (url.pathname.startsWith('/_dev/')) { plain(res, 404, 'Not found'); return; }
    if (!bankAllowed(req, url)) { plain(res, 401, 'Banking credentials required'); return; }
    attach(session, res);
    const trace = await traces(req, url);
    if (trace) {
      // Filesystem reads are admitted only after the same host, session,
      // Origin and deadline checks as all ordinary FLUJO requests. Recheck after
      // asynchronous I/O so logout or the deadline cannot complete a stale read.
      if (isExpired()) { if (!res.destroyed) plain(res, 410, 'Development access has expired'); return; }
      if (res.destroyed) return;
      if (authenticate(req) !== session) { plain(res, 401, 'Development sign-in required'); return; }
      res.writeHead(trace.status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY', 'Referrer-Policy': 'same-origin',
        'X-Flujo-Dev-Target': 'Live Fly development' });
      res.end(JSON.stringify(trace.body)); return;
    }
    const outgoing = http.request(options(req), incoming => {
      res.writeHead(incoming.statusCode || 502, responseHeaders(incoming)); incoming.pipe(res);
      incoming.on('error', () => res.destroy());
    });
    outgoing.on('error', () => { if (!res.headersSent) plain(res, 502, 'Private worker unavailable'); else res.destroy(); });
    req.on('aborted', () => outgoing.destroy());
    res.on('close', () => { if (!res.writableFinished) outgoing.destroy(); });
    req.pipe(outgoing);
  });
  server.on('upgrade', (req, socket, head) => {
    const parsed = route(req);
    if (parsed.status || parsed.url.pathname.startsWith('/_dev/')) { rejectSocket(socket, 403); return; }
    if (isExpired()) { rejectSocket(socket, 410); return; }
    const session = authenticate(req);
    if (!session) { rejectSocket(socket, 401); return; }
    if (!browserAllowed(req, { requireOrigin: true }) || !bankAllowed(req, parsed.url)
      || String(req.headers.upgrade).toLowerCase() !== 'websocket') { rejectSocket(socket, 403); return; }
    attach(session, socket);
    const outgoing = http.request(options(req, true));
    outgoing.on('upgrade', (incoming, upstream, upstreamHead) => {
      const lines = [`HTTP/${incoming.httpVersion} ${incoming.statusCode} ${incoming.statusMessage}`];
      for (const [name, value] of Object.entries(responseHeaders(incoming, true))) {
        for (const item of Array.isArray(value) ? value : [value]) if (item !== undefined) lines.push(`${name}: ${item}`);
      }
      socket.write(lines.join('\r\n') + '\r\n\r\n');
      if (upstreamHead.length) socket.write(upstreamHead);
      if (head.length) upstream.write(head);
      socket.pipe(upstream).pipe(socket);
      socket.on('error', () => upstream.destroy()); upstream.on('error', () => socket.destroy());
      socket.on('close', () => upstream.destroy()); upstream.on('close', () => socket.destroy());
    });
    outgoing.on('response', incoming => { incoming.resume(); rejectSocket(socket, incoming.statusCode === 401 ? 401 : 403); });
    outgoing.on('error', () => socket.destroy()); socket.on('error', () => outgoing.destroy());
    socket.on('close', () => outgoing.destroy()); outgoing.end();
  });
  server.revokeUserSessions = username => {
    for (const [nonce, session] of sessions) if (session.sub === username) revoke(nonce);
  };
  const sweep = setInterval(prune, 60_000); sweep.unref();
  let deadlineTimer;
  const armDeadline = () => {
    if (isExpired()) return;
    deadlineTimer = setTimeout(armDeadline, Math.min(Math.max(config.expiresAt - now(), 1), 2_147_483_647));
    deadlineTimer.unref();
  };
  armDeadline();
  server.once('close', () => { clearInterval(sweep); clearTimeout(deadlineTimer); for (const nonce of sessions.keys()) revoke(nonce); });
  server.requestTimeout = 30_000; server.headersTimeout = 15_000;
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const server = createDevGateway(readDevConfig());
    const shutdown = code => {
      for (const username of USERNAMES) server.revokeUserSessions(username);
      server.close(() => process.exit(code)); server.closeAllConnections();
      setTimeout(() => process.exit(code), 5000).unref();
    };
    server.on('error', () => { console.error('Live Fly development gateway failed to listen.'); shutdown(1); });
    server.listen(8081, '::', () => console.log('Live Fly development gateway listening on private port 8081.'));
    for (const signal of ['SIGTERM', 'SIGINT']) process.once(signal, () => shutdown(0));
  } catch {
    console.error('Live Fly development gateway configuration is unavailable.');
    process.exitCode = 1;
  }
}
