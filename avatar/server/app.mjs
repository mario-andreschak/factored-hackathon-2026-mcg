import { createServer } from 'node:http';
import { randomBytes, createHash, timingSafeEqual } from 'node:crypto';
import { readFile, realpath, stat } from 'node:fs/promises';
import { resolve, relative, isAbsolute, extname } from 'node:path';
import { readConfig, isLoopback } from './config.mjs';
import { AVATARS, realtimeSession } from './realtime.mjs';
import { isLocale } from './locale.mjs';
import { PublicError, json, publicFailure, readBody, readResponse, operationSignal, parseJson, requireType } from './http.mjs';
import { BANK_COOKIE, cookieValue, bindBankToken, saviaRoute, proxySavia, delegateTask, verifyBankSession } from './savia.mjs';
import { validateTranscription, validateConversation, validateSpeech, transcribe, converse, speak } from './openrouter.mjs';
import { validateGeminiTokenRequest, provisionGeminiToken } from './gemini.mjs';
import { createPersonaplexRelay, validatePersonaplexRequest, rejectPersonaplexUpgrade } from './personaplex.mjs';
import { validateNativeTurn, streamNativeTurn } from './openrouter-native.mjs';
import { createNativeTurns } from './native-turns.mjs';

const SESSION_COOKIE = 'avatar_session';
const mime = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.webp': 'image/webp', '.avif': 'image/avif', '.woff2': 'font/woff2', '.ico': 'image/x-icon', '.mp3': 'audio/mpeg',
};

function sameOrigin(req, config, server, mutation) {
  let incoming;
  try { incoming = new URL(`http://${req.headers.host}`); } catch { throw new PublicError(403, 'invalid_host', 'This host is not allowed.'); }
  const port = server.address()?.port || config.port;
  const localHosts = new Set([`localhost:${port}`, `127.0.0.1:${port}`, `[::1]:${port}`]);
  if (!localHosts.has(incoming.host) && incoming.host !== (config.publicOrigin && new URL(config.publicOrigin).host)) {
    throw new PublicError(403, 'invalid_host', 'This host is not allowed.');
  }
  const origins = new Set(config.allowedOrigins);
  for (const host of localHosts) origins.add(`http://${host}`);
  const value = req.headers.origin;
  if (req.headers['sec-fetch-site'] === 'cross-site' || (value && !origins.has(value)) || (mutation && !value)) {
    throw new PublicError(403, 'invalid_origin', 'This request origin is not allowed.');
  }
}

function safeUrl(req) {
  const raw = String(req.url || '');
  if (!raw.startsWith('/') || raw.startsWith('//') || raw.length > 4096 || /[\\\u0000-\u001f]/.test(raw)) {
    throw new PublicError(400, 'invalid_path', 'The request path is invalid.');
  }
  let path;
  try { path = decodeURIComponent(raw.split('?')[0]); } catch { throw new PublicError(400, 'invalid_path', 'The request path is invalid.'); }
  if (path.split('/').some(part => part === '.' || part === '..') || /[\\\u0000-\u001f]/.test(path) ||
      /%(?:2f|5c|2e|00)/i.test(raw.split('?')[0])) throw new PublicError(400, 'invalid_path', 'The request path is invalid.');
  return new URL(raw, 'http://avatar.internal');
}

async function staticFile(req, res, url, config) {
  if (!['GET', 'HEAD'].includes(req.method)) throw new PublicError(405, 'method_not_allowed', 'This method is not allowed.');
  const decoded = decodeURIComponent(url.pathname);
  if (decoded.split('/').some(part => part.startsWith('.')) || extname(decoded).toLowerCase() === '.env') {
    throw new PublicError(404, 'not_found', 'This file is not available.');
  }
  const root = await realpath(config.staticDir).catch(() => null);
  if (!root) throw new PublicError(503, 'frontend_not_built', 'Build the avatar frontend before starting the production server.');
  let file = resolve(root, `.${decoded}`);
  let info = await stat(file).catch(() => null);
  if (!info?.isFile() && !extname(url.pathname)) { file = resolve(root, 'index.html'); info = await stat(file).catch(() => null); }
  if (!info?.isFile() || info.size > 64 * 1024 * 1024) throw new PublicError(404, 'not_found', 'This file is not available.');
  file = await realpath(file);
  const contained = relative(root, file);
  if (contained.startsWith('..') || isAbsolute(contained)) throw new PublicError(404, 'not_found', 'This file is not available.');
  res.writeHead(200, {
    'Content-Type': mime[extname(file)] || 'application/octet-stream', 'Content-Length': info.size,
    'Cache-Control': extname(file) === '.html' ? 'no-store' : 'public, max-age=3600',
  });
  res.end(req.method === 'HEAD' ? undefined : await readFile(file));
}

/** Dependency injection is trusted server/test code only, never request data. */
export function createAvatarServer({ config = readConfig(), fetchImpl = fetch, now = Date.now, personaplexOptions = {} } = {}) {
  const sessions = new Map();
  const rates = new Map();
  const active = new Set();
  const taskOwners = new Set();
  const counters = { realtime: 0, tasks: 0, proxy: 0, voice: 0 };
  const personaplex = createPersonaplexRelay({ ...personaplexOptions, config, now, fetchImpl });
  const sweep = () => {
    const time = now();
    for (const [id, session] of sessions) if (session.expires <= time) { session.native?.reset(); sessions.delete(id); }
    for (const [key, bucket] of rates) if (bucket.reset <= time) rates.delete(key);
  };
  const sweepTimer = setInterval(sweep, 60_000);
  sweepTimer.unref();

  function rate(req, category) {
    const key = `${req.socket.remoteAddress}:${category}`;
    const time = now();
    let bucket = rates.get(key);
    if (!bucket || bucket.reset <= time) {
      if (rates.size >= 1024) sweep();
      if (rates.size >= 1024) throw new PublicError(503, 'capacity', 'The service is busy. Please try again.');
      bucket = { reset: time + 60_000, count: 0 }; rates.set(key, bucket);
    }
    const maximum = category === 'realtime' ? config.realtimeRateLimit : category === 'voice' ? config.voiceOperationRateLimit : config.rateLimit;
    if (++bucket.count > maximum) {
      throw new PublicError(429, 'rate_limited', 'Too many requests. Please wait a moment.');
    }
  }

  function sessionFor(req, res, create = false) {
    const id = cookieValue(req.headers.cookie, SESSION_COOKIE);
    let session = id && sessions.get(id);
    if (session?.expires <= now()) { session.native?.reset(); sessions.delete(id); session = null; }
    if (!session && create) {
      if (sessions.size >= config.maxSessions) sweep();
      if (sessions.size >= config.maxSessions) throw new PublicError(503, 'capacity', 'The service is busy. Please try again.');
      const next = randomBytes(32).toString('base64url');
      session = { id: next, expires: now() + config.sessionSeconds * 1000, bankToken: null, native: createNativeTurns({ now }) };
      sessions.set(next, session);
      res.setHeader('Set-Cookie', [`${SESSION_COOKIE}=${next}; Path=/; Max-Age=${config.sessionSeconds}; HttpOnly; SameSite=Strict${config.secureCookies ? '; Secure' : ''}`]);
    }
    if (!session) throw new PublicError(401, 'session_required', 'Refresh the avatar screen to start a session.');
    return session;
  }

  function admission(category, maximum) {
    if (counters[category] >= maximum) throw new PublicError(503, 'capacity', 'The service is busy. Please try again.');
    counters[category]++;
    return () => counters[category]--;
  }

  function claimTask(session) {
    if (!session.bankToken) return () => {};
    const owner = createHash('sha256').update(session.bankToken).digest('hex');
    if (taskOwners.has(owner)) throw new PublicError(409, 'task_active', 'A task is already running. Wait for its result before sending another.');
    taskOwners.add(owner);
    return () => taskOwners.delete(owner);
  }

  const server = createServer({ maxHeaderSize: 16 * 1024 }, async (req, res) => {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'same-origin');
    res.setHeader('X-Frame-Options', 'SAMEORIGIN');
    res.setHeader('Permissions-Policy', 'microphone=(self), camera=(), geolocation=()');
    res.setHeader('Content-Security-Policy', "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self' wss://generativelanguage.googleapis.com; font-src 'self'; media-src 'self' blob:; frame-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'");
    try {
      const url = safeUrl(req);
      const mutation = !['GET', 'HEAD'].includes(req.method);
      sameOrigin(req, config, server, mutation);
      if (req.headers['content-encoding'] && req.headers['content-encoding'] !== 'identity') {
        throw new PublicError(415, 'unsupported_encoding', 'Compressed request bodies are not supported.');
      }
      if (url.pathname === '/healthz' && req.method === 'GET') {
        json(res, 200, { status: 'ok', service: 'savia-avatar' }); return;
      }
      if (config.publicAccess) {
        const supplied = Buffer.from(String(req.headers['x-avatar-gateway-token'] || ''));
        const expected = Buffer.from(config.accessGateToken);
        if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) {
          throw new PublicError(401, 'access_gate_required', 'Sign in through the application access gate to continue.');
        }
      }
      if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/savia')) rate(req, 'general');
      if (url.pathname === '/api/avatar/config' && req.method === 'GET') {
        sessionFor(req, res, true);
        const nativeProfile = config.voiceProvider === 'personaplex' ? await personaplex.profile() : null;
        const initialVoiceAvailable = config.voiceProvider === 'personaplex' && await personaplex.initialAvailable();
        const backgroundAsrAvailable = Boolean(config.openrouterKey) && (config.voiceProvider === 'openrouter-native' || config.voiceProvider === 'personaplex' && config.backgroundAsr === 'openrouter');
        json(res, 200, {
          voiceAvailable: config.voiceProvider === 'personaplex' ? Boolean(nativeProfile?.available) : config.voiceProvider === 'gemini-live' ? Boolean(config.geminiKey) : ['openrouter', 'openrouter-native'].includes(config.voiceProvider) ? Boolean(config.openrouterKey) : config.voiceProvider === 'openai-realtime' ? Boolean(config.openaiKey) : false,
          ...(config.voiceProvider === 'personaplex' ? { voiceAvatar: nativeProfile?.avatar || null } : {}),
          ...(config.personaplexInitialRole ? { initialVoiceAvailable } : {}),
          voiceProvider: config.voiceProvider,
          backgroundAsrAvailable,
          nativeReadBridgeAvailable: config.nativeReadBridge === 'readonly' && backgroundAsrAvailable && Boolean(config.saviaUpstream),
          backendAvailable: Boolean(config.saviaUpstream),
          saviaUrl: config.saviaUpstream ? '/savia/' : '',
          mode: config.saviaUpstream ? 'connected' : 'demo', realtimeModel: config.realtimeModel, geminiModel: config.geminiModel,
        }); return;
      }
      if (['/api/avatar/native-turn', '/api/avatar/native-result', '/api/avatar/native-observe',
        '/api/avatar/native-played', '/api/avatar/native-reset', '/api/avatar/native-result-receipt'].includes(url.pathname) && req.method === 'POST') {
        const session = sessionFor(req, res);
        rate(req, 'voice'); requireType(req, 'application/json');
        if (url.search) throw new PublicError(400, 'invalid_voice_request', 'Send native voice options in the JSON body.');
        if (config.voiceProvider !== 'openrouter-native' || !config.openrouterKey)
          throw new PublicError(503, 'voice_unconfigured', 'Native OpenRouter audio is not enabled. You can still type.');
        session.native.bind(session.bankToken);
        const audioRequest = ['/api/avatar/native-turn', '/api/avatar/native-observe'].includes(url.pathname);
        const payload = parseJson(await readBody(req, audioRequest ? 8 * 1024 * 1024 : 40 * 1024));
        if (url.pathname.endsWith('/native-reset')) {
          if (Object.keys(payload).length) throw new PublicError(400, 'invalid_voice_request', 'Reset does not accept voice options.');
          session.native.reset(); json(res, 200, { accepted: true }); return;
        }
        if (url.pathname.endsWith('/native-played')) { json(res, 200, session.native.played(payload)); return; }
        if (url.pathname.endsWith('/native-result-receipt')) {
          json(res, 200, session.native.receiptFor(payload, session.bankToken)); return;
        }
        const release = admission('voice', config.maxVoiceOperations);
        const operation = operationSignal(req, res, config.voiceTimeoutMs, active);
        const owned = new AbortController();
        const signal = AbortSignal.any([operation.signal, owned.signal]);
        let turn;
        try {
          if (url.pathname.endsWith('/native-observe')) {
            const audio = validateTranscription({ audio: payload.audio, format: payload.format, locale: payload.locale, language: payload.locale });
            turn = session.native.claimObserver(payload, owned);
            const result = await transcribe(audio, config, fetchImpl, signal);
            if (signal.aborted || !session.native.observed(turn, result.text))
              throw new PublicError(409, 'native_turn_ended', 'This recorded request is no longer current.');
            json(res, 200, result);
          } else {
            const resultTurn = url.pathname.endsWith('/native-result');
            const value = validateNativeTurn(resultTurn ? { avatar: payload.avatar, locale: payload.locale,
              message: payload.locale === 'pt' ? 'Resuma o resultado confirmado com precisão.' : 'Resume el resultado confirmado con precisión.' } : payload);
            let backendResult;
            if (resultTurn || session.native.hasPrivateContext()) {
              // A fresh Savia identity check precedes consuming a single-use, server-held receipt.
              const owner = session.bankToken;
              await verifyBankSession(config, session, fetchImpl, signal);
              if (signal.aborted || session.bankToken !== owner) throw new PublicError(409, 'native_turn_ended', 'The account changed.');
              if (resultTurn) backendResult = session.native.consumeReceipt(payload, owner);
            }
            const started = session.native.begin(resultTurn ? { ...value, message: '' } : value, session.bankToken, owned);
            turn = started.turn;
            backendResult ??= session.native.latestResult();
            const result = await streamNativeTurn(value, config, fetchImpl, signal, res,
              { turnId: turn.id, history: started.history, onQualifiedResult: result => session.native.qualify(turn, result),
                ...(backendResult ? { backendResult } : {}) });
            session.native.finish(turn, result);
          }
        } catch (error) {
          if (turn) {
            if (url.pathname.endsWith('/native-observe')) session.native.observerFailed(turn);
            else session.native.finish(turn, null);
          }
          if (operation.signal.aborted && !res.headersSent)
            throw new PublicError(504, 'voice_timeout', 'The voice turn took too long. You can continue speaking or type.');
          throw error;
        } finally { operation.release(); release(); }
        return;
      }
      if (url.pathname === '/api/avatar/personaplex-initial' && req.method === 'POST') {
        const session = sessionFor(req, res);
        rate(req, 'realtime'); rate(req, 'voice'); requireType(req, 'application/json');
        if (!config.personaplexInitialRole) throw new PublicError(503, 'initial_voice_unavailable', 'Initial character selection is not enabled. You can still type.');
        if (url.search) throw new PublicError(400, 'invalid_initial_audio', 'Send only the first recorded request.');
        const payload = parseJson(await readBody(req, 800000));
        const release = admission('voice', config.maxVoiceOperations);
        const operation = operationSignal(req, res, 65000, active);
        let binding;
        try {
          const selection = await personaplex.selectInitial(payload, session, { signal: operation.signal,
            isSessionCurrent: candidate => sessions.get(candidate.id) === candidate && candidate.expires > now() });
          binding = selection.binding;
          const ticket = await personaplex.issueInitial(binding, session);
          if (operation.signal.aborted || res.destroyed || sessions.get(session.id) !== session || session.expires <= now()) throw new Error('Initial voice owner ended.');
          await new Promise((resolve, reject) => {
            const cleanup = () => { res.off('finish', finished); res.off('close', disconnected); };
            const finished = () => {
              cleanup();
              try { personaplex.acknowledgeInitial(binding, session); resolve(); } catch (error) { reject(error); }
            };
            const disconnected = () => { cleanup(); personaplex.cancelInitial(binding); reject(new Error('Initial voice delivery ended.')); };
            res.once('finish', finished); res.once('close', disconnected);
            try { json(res, 200, { ...ticket, ...selection.publicResult }); }
            catch (error) { cleanup(); reject(error); }
          });
        } catch (error) { if (binding) personaplex.cancelInitial(binding); throw error; }
        finally { operation.release(); release(); }
        return;
      }
      if (url.pathname === '/api/avatar/personaplex-session' && req.method === 'POST') {
        const session = sessionFor(req, res);
        rate(req, 'realtime'); requireType(req, 'application/json');
        if (url.search) throw new PublicError(400, 'invalid_avatar', 'Send only a valid avatar choice.');
        const avatar = validatePersonaplexRequest(parseJson(await readBody(req, 1024)));
        json(res, 200, await personaplex.issue(avatar, session)); return;
      }
      if (url.pathname === '/api/avatar/gemini-token' && req.method === 'POST') {
        sessionFor(req, res);
        rate(req, 'realtime');
        requireType(req, 'application/json');
        if (url.search) throw new PublicError(400, 'invalid_avatar', 'Choose a valid avatar.');
        const tokenRequest = parseJson(await readBody(req, 1024));
        const avatar = validateGeminiTokenRequest(tokenRequest);
        if (config.voiceProvider !== 'gemini-live' || !config.geminiKey) {
          throw new PublicError(503, 'voice_unconfigured', 'Native Gemini Live voice is not configured. You can still type.');
        }
        const release = admission('realtime', config.maxRealtimeStarts);
        const operation = operationSignal(req, res, config.realtimeTimeoutMs, active);
        try { json(res, 200, await provisionGeminiToken(avatar, config, fetchImpl, operation.signal, now(), tokenRequest.locale)); }
        catch (error) {
          if (operation.signal.aborted) throw new PublicError(504, 'voice_timeout', 'Gemini Live took too long to connect. You can still type.');
          throw error;
        } finally { operation.release(); release(); }
        return;
      }
      if (['/api/avatar/transcribe', '/api/avatar/conversation', '/api/avatar/speech'].includes(url.pathname) && req.method === 'POST') {
        const session = sessionFor(req, res);
        rate(req, 'voice');
        requireType(req, 'application/json');
        if (url.search) throw new PublicError(400, 'invalid_voice_request', 'Voice request options belong in the documented JSON body.');
        const transcription = url.pathname.endsWith('/transcribe');
        const observer = transcription && config.voiceProvider === 'personaplex' && config.backgroundAsr === 'openrouter';
        if ((!observer && config.voiceProvider !== 'openrouter') || !config.openrouterKey) throw new PublicError(503, 'voice_unconfigured', 'The optional OpenRouter voice pipeline is not enabled. Native Live voice and text use their own transport.');
        const observerSignal = observer ? personaplex.observerSignal(session) : null;
        if (observer && !observerSignal) throw new PublicError(409, 'background_asr_session_required', 'Recognition needs your connected native voice session.');
        const payload = parseJson(await readBody(req, transcription ? 8 * 1024 * 1024 : 64 * 1024));
        const value = transcription ? validateTranscription(payload) : url.pathname.endsWith('/conversation') ? validateConversation(payload) : validateSpeech(payload);
        const release = admission('voice', config.maxVoiceOperations);
        const operation = operationSignal(req, res, config.voiceTimeoutMs, active);
        const signal = observerSignal ? AbortSignal.any([operation.signal, observerSignal]) : operation.signal;
        const observerEnded = () => observerSignal && personaplex.observerSignal(session) !== observerSignal;
        try {
          if (signal.aborted || observerEnded()) throw new Error('Recognition ended.');
          if (transcription) {
            const result = await transcribe(value, config, fetchImpl, signal);
            if (signal.aborted || observerEnded()) throw new Error('Recognition ended.');
            json(res, 200, result);
          }
          else if (url.pathname.endsWith('/conversation')) await converse(value, config, fetchImpl, operation.signal, res);
          else await speak(value, config, fetchImpl, operation.signal, res);
        } catch (error) {
          if (observerEnded() && !res.headersSent) throw new PublicError(409, 'background_asr_session_ended', 'The native voice session ended before recognition finished.');
          if (operation.signal.aborted && !res.headersSent) throw new PublicError(504, 'voice_timeout', 'The voice turn took too long. You can continue speaking or type.');
          throw error;
        } finally { operation.release(); release(); }
        return;
      }
      if (url.pathname === '/api/avatar/realtime' && req.method === 'POST') {
        rate(req, 'realtime');
        const session = sessionFor(req, res);
        if (config.voiceProvider !== 'openai-realtime' || !config.openaiKey) throw new PublicError(503, 'voice_unconfigured', 'Native OpenAI Realtime voice is not enabled. You can still type.');
        requireType(req, 'application/sdp');
        if ([...url.searchParams.keys()].some(key => !['avatar', 'locale'].includes(key)) || url.searchParams.getAll('avatar').length > 1 || url.searchParams.getAll('locale').length > 1) {
          throw new PublicError(400, 'invalid_avatar', 'Choose a valid avatar.');
        }
        const avatar = url.searchParams.get('avatar') || 'moss';
        if (!AVATARS.includes(avatar)) throw new PublicError(400, 'invalid_avatar', 'Choose a valid avatar.');
        const locale = url.searchParams.get('locale') ?? 'es';
        if (!isLocale(locale)) throw new PublicError(400, 'invalid_locale', 'Choose Spanish or Portuguese.');
        const offer = await readBody(req, 64 * 1024);
        if (!offer.startsWith('v=0') || !offer.includes('m=audio') || offer.includes('\0')) {
          throw new PublicError(400, 'invalid_sdp', 'A valid audio SDP offer is required.');
        }
        const release = admission('realtime', config.maxRealtimeStarts);
        const operation = operationSignal(req, res, config.realtimeTimeoutMs, active);
        try {
          const body = new FormData();
          body.set('sdp', offer); body.set('session', JSON.stringify(realtimeSession(avatar, config.realtimeModel, locale)));
          const response = await fetchImpl('https://api.openai.com/v1/realtime/calls', {
            method: 'POST', redirect: 'manual', signal: operation.signal,
            headers: { Authorization: `Bearer ${config.openaiKey}` }, body,
          });
          if (!response.ok) {
            let quotaUnavailable = false;
            // Inspect only a fixed provider error classification. Never pass its
            // message, arbitrary code, request metadata or credentials to the UI.
            try {
              const details = JSON.parse((await readResponse(response, 64 * 1024)).toString('utf8'));
              quotaUnavailable = details?.error?.code === 'insufficient_quota' ||
                details?.error?.code === 'credit_balance_exhausted' || details?.error?.type === 'insufficient_quota';
            } catch { /* Keep the fixed public error if the provider body is malformed. */ }
            if (quotaUnavailable) throw new PublicError(503, 'voice_quota_exhausted', 'Live voice is unavailable because the provider account has exhausted its quota or credit. Text and Savia still work; the operator needs to restore provider quota.');
            throw new PublicError(response.status === 429 ? 429 : 502, response.status === 429 ? 'rate_limited' : 'voice_unavailable', 'Live voice could not connect. Please try again.');
          }
          const answer = (await readResponse(response, 64 * 1024)).toString('utf8');
          if (!answer.startsWith('v=0') || !answer.includes('m=audio')) throw new PublicError(502, 'invalid_upstream_response', 'Live voice returned an invalid response.');
          res.writeHead(201, { 'Content-Type': 'application/sdp', 'Cache-Control': 'no-store', 'Content-Length': Buffer.byteLength(answer) });
          res.end(answer);
        } catch (error) {
          if (operation.signal.aborted) throw new PublicError(504, 'voice_timeout', 'Live voice took too long to connect. Please try again.');
          throw error;
        } finally { operation.release(); release(); }
        return;
      }
      if (url.pathname === '/api/avatar/task' && req.method === 'POST') {
        const session = sessionFor(req, res);
        requireType(req, 'application/json');
        const payload = parseJson(await readBody(req, 24 * 1024));
        if (Object.keys(payload).some(key => key !== 'message') || typeof payload.message !== 'string' ||
            !payload.message.trim() || payload.message.length > 4000) {
          throw new PublicError(400, 'invalid_task', 'Send only a message of 1 to 4000 characters.');
        }
        const unclaim = claimTask(session);
        const release = (() => { try { return admission('tasks', config.maxTasks); } catch (error) { unclaim(); throw error; } })();
        const operation = operationSignal(req, res, config.upstreamTimeoutMs, active);
        try {
          const owner = session.bankToken;
          const result = await delegateTask(payload.message.trim(), config, session, fetchImpl, operation.signal);
          if (session.bankToken !== owner) throw new PublicError(409, 'bank_session_changed', 'The account changed before this response was delivered.');
          if (!operation.signal.aborted && session.bankToken === owner) session.native.receipt(result, owner);
          json(res, 200, result);
        }
        catch (error) {
          if (operation.signal.aborted) throw new PublicError(504, 'task_timeout', 'The task is still unresolved. Check Savia history before retrying; this timeout does not prove cancellation.');
          throw error;
        } finally { operation.release(); release(); unclaim(); }
        return;
      }
      if (url.pathname === '/savia' || url.pathname.startsWith('/savia/')) {
        const route = saviaRoute(url.pathname, req.method);
        if (!route) throw new PublicError(404, 'not_found', 'This route is not available.');
        const session = sessionFor(req, res, true);
        const bankToken = cookieValue(req.headers.cookie, BANK_COOKIE);
        bindBankToken(session, bankToken);
        session.native.bind(session.bankToken);
        const chat = ['/api/chat', '/api/chat/messages'].includes(route.path) && req.method === 'POST';
        const unclaim = chat ? claimTask(session) : () => {};
        const releaseTask = (() => { try { return chat ? admission('tasks', config.maxTasks) : () => {}; } catch (error) { unclaim(); throw error; } })();
        const release = (() => { try { return admission('proxy', config.maxProxyRequests); } catch (error) { releaseTask(); unclaim(); throw error; } })();
        const operation = operationSignal(req, res, chat ? config.upstreamTimeoutMs : config.proxyTimeoutMs, active);
        try { await proxySavia(req, res, url, config, session, fetchImpl, operation.signal,
          { onTaskResult: (result, owner) => session.native.receipt(result, owner) }); }
        catch (error) {
          if (operation.signal.aborted) throw new PublicError(504, 'upstream_timeout', chat ? 'The task is still unresolved. Check Savia history before retrying.' : 'Savia took too long to respond. Please try again.');
          throw error;
        } finally { session.native.bind(session.bankToken); operation.release(); release(); releaseTask(); unclaim(); }
        return;
      }
      if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/savia')) throw new PublicError(404, 'not_found', 'This route is not available.');
      await staticFile(req, res, url, config);
    } catch (error) { publicFailure(res, error); }
  });
  server.requestTimeout = 30_000;
  server.on('upgrade', async (req, socket, head) => {
    socket.on('error', () => {});
    try {
      const url = safeUrl(req);
      sameOrigin(req, config, server, true);
      if (url.pathname !== '/api/avatar/personaplex') throw new PublicError(404, 'not_found', 'This route is not available.');
      if (config.publicAccess) {
        const supplied = Buffer.from(String(req.headers['x-avatar-gateway-token'] || ''));
        const expected = Buffer.from(config.accessGateToken);
        if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) throw new PublicError(401, 'access_gate_required', 'Sign in through the application access gate to continue.');
      }
      rate(req, 'general');
      const session = sessionFor(req, null);
      await personaplex.upgrade(req, socket, head, url, session);
    } catch (error) { rejectPersonaplexUpgrade(socket, error); }
  });
  server.headersTimeout = 15_000;
  server.keepAliveTimeout = 5000;
  server.maxRequestsPerSocket = 100;
  server.once('close', () => {
    personaplex.close();
    clearInterval(sweepTimer);
    for (const controller of active) controller.abort();
    for (const session of sessions.values()) session.native.reset();
    active.clear(); sessions.clear(); rates.clear(); taskOwners.clear();
  });
  const close = server.close.bind(server);
  server.close = callback => { personaplex.close(); return close(callback); };
  return server;
}
