export class PublicError extends Error {
  constructor(status, code, message) { super(message); this.status = status; this.code = code; }
}

export function json(res, status, value, headers = {}) {
  const body = JSON.stringify(value);
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Content-Length': Buffer.byteLength(body), 'Cache-Control': 'no-store', ...headers });
  res.end(body);
}

export function publicFailure(res, error) {
  if (res.writableEnded || res.destroyed) return;
  if (res.headersSent) { res.destroy(); return; }
  const known = error instanceof PublicError;
  json(res, known ? error.status : 502, { error: known ? error.message : 'The service could not complete the request.', code: known ? error.code : 'upstream_unavailable' });
}

export async function readBody(req, maximum) {
  if (Number(req.headers['content-length']) > maximum) {
    req.resume();
    throw new PublicError(413, 'body_too_large', 'The request is too large.');
  }
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > maximum) {
      req.resume();
      throw new PublicError(413, 'body_too_large', 'The request is too large.');
    }
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString('utf8');
}

export async function readResponse(response, maximum = 4 * 1024 * 1024) {
  if (Number(response.headers.get('content-length')) > maximum) {
    await response.body?.cancel();
    throw new PublicError(502, 'invalid_upstream_response', 'The service returned an invalid response.');
  }
  const reader = response.body?.getReader();
  if (!reader) return Buffer.alloc(0);
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > maximum) throw new PublicError(502, 'invalid_upstream_response', 'The service returned an invalid response.');
      chunks.push(Buffer.from(value));
    }
    return Buffer.concat(chunks);
  } catch (error) {
    await reader.cancel().catch(() => {});
    throw error;
  } finally { reader.releaseLock(); }
}

/** Timeout covers both response headers and the response body. Disconnects abort upstream work. */
export function operationSignal(req, res, timeoutMs, active) {
  const controller = new AbortController();
  active.add(controller);
  const timer = setTimeout(() => controller.abort(new Error('timeout')), timeoutMs);
  timer.unref();
  const disconnected = () => { if (!res.writableEnded) controller.abort(new Error('disconnected')); };
  res.once('close', disconnected);
  return { signal: controller.signal, release() { clearTimeout(timer); res.off('close', disconnected); active.delete(controller); } };
}

export function parseJson(text) {
  try {
    const value = JSON.parse(text);
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error();
    return value;
  } catch { throw new PublicError(400, 'invalid_json', 'A valid JSON object is required.'); }
}

export function requireType(req, type) {
  if (String(req.headers['content-type'] || '').split(';')[0].trim().toLowerCase() !== type) {
    throw new PublicError(415, 'unsupported_media_type', `Content-Type must be ${type}.`);
  }
}

export function upstreamFailure(status) {
  if (status === 401) return new PublicError(401, 'sign_in_required', 'Sign in on the Savia screen to continue.');
  if (status === 403) return new PublicError(403, 'access_denied', 'This operation is not available for the signed-in session.');
  if (status === 409) return new PublicError(409, 'task_active', 'A task is already running. Wait for its result before sending another.');
  if (status === 429) return new PublicError(429, 'rate_limited', 'Too many requests. Please wait a moment.');
  if (status >= 400 && status < 500) return new PublicError(status, 'request_rejected', 'The service could not accept this request.');
  return new PublicError(502, 'upstream_unavailable', 'The service is temporarily unavailable. Please try again.');
}
