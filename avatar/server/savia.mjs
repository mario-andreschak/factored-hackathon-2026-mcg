import { PublicError, json, parseJson, readBody, readResponse, requireType, upstreamFailure } from './http.mjs';

export const BANK_COOKIE = 'flujo_bank_session';
export const SAVIA_API_ROUTES = Object.freeze({
  '/api/auth/profiles': ['GET'],
  '/api/auth/login': ['POST'],
  '/api/auth/invite': ['POST'],
  '/api/auth/me': ['GET'],
  '/api/auth/logout': ['POST'],
  '/api/overview': ['GET'],
  '/api/transactions': ['GET'],
  '/api/chat/status': ['GET'],
  '/api/chat/history': ['GET'],
  '/api/chat': ['POST'],
  '/api/chat/messages': ['POST'],
  '/api/action/status': ['GET'],
  '/api/followups': ['GET', 'POST'],
  '/api/followups/check': ['POST'],
  '/api/assistant/cases': ['GET', 'POST'],
  '/api/assistant/voice-update': ['GET'],
});

export function cookieValue(header, name) {
  const matches = String(header || '').split(';').map(value => value.trim()).filter(value => value.startsWith(`${name}=`));
  if (matches.length !== 1) return null;
  const token = matches[0].slice(name.length + 1);
  return /^[a-zA-Z0-9_-]{20,256}$/.test(token) ? token : null;
}

export function bindBankToken(session, token) {
  if (token && token !== session.blockedBankToken) { session.bankToken = token; session.native?.bind(token); }
  return token && token !== session.blockedBankToken ? token : null;
}

export function saviaRoute(pathname, method) {
  const path = pathname.slice('/savia'.length) || '/';
  const methods = SAVIA_API_ROUTES[path];
  if (methods) return methods.includes(method) ? { path, api: true } : null;
  if (/^\/api\/assistant\/cases\/i_[a-f0-9]{32}\/resolve$/.test(path))
    return method === 'POST' ? { path, api: true } : null;
  if (method !== 'GET' && method !== 'HEAD') return null;
  if (path === '/' || path === '/index.html' || path === '/favicon.svg' ||
      /^\/assets\/[a-zA-Z0-9._/-]+\.(?:js|css|svg|png|jpe?g|webp|avif|woff2?)$/.test(path) &&
      !path.split('/').some(part => part.startsWith('.') || part === '..')) {
    return { path, api: false };
  }
  return null;
}

function transformStatic(buffer, type) {
  if (type.includes('text/html')) {
    return Buffer.from(buffer.toString('utf8').replace(/((?:src|href)=["'])\/(assets\/|favicon\.svg)/g, '$1/savia/$2'));
  }
  if (type.includes('javascript')) {
    // Savia's audited bundle uses absolute API paths, including template strings.
    // Transform only string roots; no inline execution is injected and CSP stays self-only.
    return Buffer.from(buffer.toString('utf8').replace(/(["'`])\/api\//g, '$1/savia/api/').replace(/(["'`])\/assets\//g, '$1/savia/assets/'));
  }
  if (type.includes('text/css')) return Buffer.from(buffer.toString('utf8').replace(/url\((['"]?)\/assets\//g, 'url($1/savia/assets/'));
  return buffer;
}

export function upstreamHeaders(config, session, incomingBankToken) {
  const token = incomingBankToken || session.bankToken;
  return {
    Accept: 'application/json, text/html;q=0.9, */*;q=0.8',
    Origin: config.saviaOrigin,
    'Sec-Fetch-Site': 'same-origin',
    ...(token ? { Cookie: `${BANK_COOKIE}=${token}` } : {}),
  };
}

export async function verifyBankSession(config, session, fetchImpl, signal) {
  if (!config.saviaUpstream || !session.bankToken) throw upstreamFailure(401);
  const response = await fetchImpl(`${config.saviaUpstream}/api/auth/me`, {
    headers: upstreamHeaders(config, session), redirect: 'manual', signal,
  });
  if (!response.ok) {
    if (response.status === 401) { session.blockedBankToken = session.bankToken; session.bankToken = null; session.native?.bind(null); }
    await response.body?.cancel(); throw upstreamFailure(response.status);
  }
  let result;
  try { result = JSON.parse((await readResponse(response, 64 * 1024)).toString('utf8')); }
  catch { throw new PublicError(502, 'invalid_upstream_response', 'The sign-in service returned an invalid response.'); }
  if (result.authenticated !== true) throw upstreamFailure(401);
}

/** Restricted fixed-upstream proxy. No arbitrary worker routes or browser headers are forwarded. */
export async function proxySavia(req, res, url, config, session, fetchImpl, signal, { onTaskResult } = {}) {
  if (!config.saviaUpstream) throw new PublicError(503, 'backend_unconfigured', 'Savia is not connected in this installation.');
  const route = saviaRoute(url.pathname, req.method);
  if (!route) throw new PublicError(404, 'not_found', 'This route is not available.');
  if (route.path === '/api/assistant/voice-update') {
    const query = url.searchParams;
    if ([...query.keys()].some(key => !['case_id', 'after_event_id', 'language'].includes(key) || query.getAll(key).length !== 1) ||
        !/^i_[a-f0-9]{32}$/.test(query.get('case_id') || '') ||
        !/^(?:0|[1-9][0-9]{0,12})$/.test(query.get('after_event_id') || '0') ||
        !['es', 'pt'].includes(query.get('language') || 'es'))
      throw new PublicError(400, 'invalid_task', 'Send only a public inquiry reference, event cursor and supported language.');
  }
  const incomingToken = bindBankToken(session, cookieValue(req.headers.cookie, BANK_COOKIE));
  const requestBankToken = session.bankToken;
  let body;
  if (req.method === 'POST') {
    requireType(req, 'application/json');
    body = await readBody(req, 24 * 1024);
    if (['/api/chat', '/api/chat/messages'].includes(route.path)) {
      const payload = parseJson(body);
      if (Object.keys(payload).some(key => !['message', 'transaction_reference', 'language', 'query_scope_id'].includes(key)) ||
          typeof payload.message !== 'string' || !payload.message.trim() || payload.message.length > 4000 ||
          (payload.language !== undefined && !['es', 'pt'].includes(payload.language)) ||
          (payload.query_scope_id !== undefined && (typeof payload.query_scope_id !== 'string' || !/^q_[a-f0-9]{32}$/.test(payload.query_scope_id))) ||
          (payload.transaction_reference !== undefined && (typeof payload.transaction_reference !== 'string' || !/^txn_[a-f0-9]{24}$/.test(payload.transaction_reference)))) {
        throw new PublicError(400, 'invalid_task', 'Send a message of 1 to 4000 characters and only an optional Savia transaction reference.');
      }
    }
    if (['/api/followups', '/api/followups/check'].includes(route.path)) {
      const payload = parseJson(body);
      if (Object.keys(payload).some(key => key !== 'language') || !['es', 'pt'].includes(payload.language))
        throw new PublicError(400, 'invalid_task', 'Send only a supported follow-up language.');
    }
    if (route.path === '/api/assistant/cases') {
      const payload = parseJson(body);
      if (Object.keys(payload).some(key => !['message', 'language', 'transaction_reference'].includes(key)) ||
          typeof payload.message !== 'string' || !payload.message.trim() || payload.message.length > 1000 ||
          (payload.language !== undefined && !['es', 'pt'].includes(payload.language)) ||
          (payload.transaction_reference !== undefined && (typeof payload.transaction_reference !== 'string' || !/^txn_[a-f0-9]{24}$/.test(payload.transaction_reference))))
        throw new PublicError(400, 'invalid_task', 'Send only a bounded inquiry, language and optional selected movement reference.');
    }
    if (route.path.endsWith('/resolve')) {
      const payload = parseJson(body);
      if (url.search || Object.keys(payload).length !== 1 || payload.resolved !== true)
        throw new PublicError(400, 'invalid_task', 'Confirm only that the informational inquiry helped.');
    }
    // Login codes are passed only to the existing, fixed Savia login endpoint.
    // The avatar never accepts them in its own task or Realtime configuration.
  }
  const headers = upstreamHeaders(config, session, incomingToken);
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (route.path === '/api/auth/logout') {
    // Invalidate local delegation even if upstream revocation times out. Forward
    // the original cookie to Savia, which owns durable worker revocation.
    session.blockedBankToken = session.bankToken;
    session.bankToken = null;
    session.native?.bind(null);
    res.setHeader('Set-Cookie', [...(res.getHeader('Set-Cookie') || []), `${BANK_COOKIE}=; Path=/savia; Max-Age=0; HttpOnly; SameSite=Strict${config.secureCookies ? '; Secure' : ''}`]);
  }
  const response = await fetchImpl(`${config.saviaUpstream}${route.path}${url.search}`, {
    method: req.method, headers, body, signal, redirect: 'manual',
  });
  const cookies = [];
  for (const raw of response.headers.getSetCookie()) {
    const parts = raw.split(';').map(value => value.trim());
    if (!parts[0].startsWith(`${BANK_COOKIE}=`)) continue;
    const value = parts[0].slice(BANK_COOKIE.length + 1);
    if (!value || value === '""') { session.bankToken = null; session.native?.bind(null); }
    else if (/^[a-zA-Z0-9_-]{20,256}$/.test(value)) { session.bankToken = value; session.blockedBankToken = null; session.native?.bind(value); }
    else continue;
    // Host-only, scoped bank cookie; never strip Secure or relax SameSite.
    const attributes = parts.slice(1).filter(part => !/^(?:path|domain|httponly|samesite)=?/i.test(part));
    cookies.push([parts[0], ...attributes, 'Path=/savia', 'HttpOnly', 'SameSite=Strict'].join('; '));
  }
  if (route.path === '/api/auth/logout') { session.bankToken = null; session.native?.bind(null); }
  const responseHeaders = {
    'Cache-Control': 'no-store',
    'Content-Type': response.headers.get('content-type') || 'application/octet-stream',
    'X-Frame-Options': 'SAMEORIGIN',
    'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; font-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'",
    ...(cookies.length ? { 'Set-Cookie': [...(res.getHeader('Set-Cookie') || []), ...cookies] } : {}),
  };
  const revoke = response.headers.get('x-banking-revoke');
  if (revoke && /^[a-z_]{1,40}$/.test(revoke)) responseHeaders['X-Banking-Revoke'] = revoke;
  if (response.status >= 300 && response.status < 400) {
    await response.body?.cancel();
    throw new PublicError(502, 'unexpected_redirect', 'The upstream returned an unexpected redirect.');
  }
  if (!response.ok) {
    if (response.status === 401) { session.blockedBankToken = session.bankToken; session.bankToken = null; session.native?.bind(null); }
    await response.body?.cancel();
    const error = upstreamFailure(response.status);
    json(res, error.status, { error: error.message, detail: error.message, code: error.code }, responseHeaders);
    return;
  }
  if (response.status === 204) { res.writeHead(204, responseHeaders); res.end(); return; }
  let result = await readResponse(response, route.api ? 4 * 1024 * 1024 : 12 * 1024 * 1024);
  if ((req.method === 'POST' && ['/api/chat', '/api/chat/messages'].includes(route.path) || route.path === '/api/assistant/voice-update') && session.bankToken !== requestBankToken)
    throw new PublicError(409, 'bank_session_changed', 'The account changed before this response was delivered.');
  if (req.method === 'POST' && ['/api/chat', '/api/chat/messages'].includes(route.path) &&
      requestBankToken && session.bankToken === requestBankToken && !signal.aborted && onTaskResult) {
    try {
      const parsed = JSON.parse(result.toString('utf8'));
      if (typeof parsed.reply === 'string' && parsed.reply.length <= 8000 && ['flujo', 'dispute'].includes(parsed.mode) &&
          ['completed', 'waiting_for_input'].includes(parsed.status))
        onTaskResult({ reply: parsed.reply, mode: parsed.mode, status: parsed.status }, requestBankToken);
    } catch { /* An unrecognized upstream shape never becomes trusted narration. */ }
  }
  if (route.path === '/api/assistant/voice-update' && requestBankToken && session.bankToken === requestBankToken &&
      !signal.aborted && onTaskResult) {
    try {
      const parsed = JSON.parse(result.toString('utf8'));
      if (parsed.mode === 'assistant' && parsed.status === 'completed' && parsed.bank_authority === false &&
          Number.isSafeInteger(parsed.event_id) && parsed.event_id > 0 && typeof parsed.reply === 'string' &&
          parsed.reply.trim() && parsed.reply.length <= 8000 &&
          ['queued', 'team_working', 'team_completed', 'awaiting_customer', 'needs_attention', 'informational_resolved', 'human_working'].includes(parsed.inquiry_state))
        onTaskResult({ reply: parsed.reply, mode: 'assistant', status: 'completed' }, requestBankToken);
    } catch { /* Only an actual, bounded host status can become spoken context. */ }
  }
  if (!route.api) result = transformStatic(result, responseHeaders['Content-Type']);
  responseHeaders['Content-Length'] = result.length;
  res.writeHead(response.status, responseHeaders);
  res.end(req.method === 'HEAD' ? undefined : result);
}

export async function delegateTask(message, config, session, fetchImpl, signal) {
  if (!config.saviaUpstream) throw new PublicError(503, 'backend_unconfigured', 'Savia is not connected in this installation.');
  if (!session.bankToken) throw upstreamFailure(401);
  const response = await fetchImpl(`${config.saviaUpstream}/api/chat`, {
    method: 'POST', redirect: 'manual', signal,
    headers: { ...upstreamHeaders(config, session), 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  });
  if (!response.ok) {
    await response.body?.cancel();
    if (response.status === 401) { session.bankToken = null; session.native?.bind(null); }
    throw upstreamFailure(response.status);
  }
  let result;
  try { result = JSON.parse((await readResponse(response)).toString('utf8')); }
  catch { throw new PublicError(502, 'invalid_upstream_response', 'Savia returned an invalid response.'); }
  if (typeof result.reply !== 'string' || result.reply.length < 1 || result.reply.length > 100_000 ||
      !['flujo', 'dispute'].includes(result.mode) || !['completed', 'waiting_for_input'].includes(result.status)) {
    throw new PublicError(502, 'invalid_upstream_response', 'Savia returned an invalid response.');
  }
  // Explicit projection excludes worker metadata and upstream conversation/customer IDs.
  return { reply: result.reply, mode: result.mode, status: result.status };
}
