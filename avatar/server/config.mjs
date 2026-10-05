import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
export const isLoopback = host => ['localhost', '127.0.0.1', '::1', '[::1]'].includes(host);

function integer(value, fallback, min, max, name) {
  const result = value === undefined || value === '' ? fallback : Number(value);
  if (!Number.isInteger(result) || result < min || result > max) throw new Error(`Invalid ${name}`);
  return result;
}

function origin(value, name, allowPrivateHttp = false) {
  let url;
  try { url = new URL(value); } catch { throw new Error(`Invalid ${name}`); }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password ||
      url.pathname !== '/' || url.search || url.hash ||
      (url.protocol !== 'https:' && !isLoopback(url.hostname) && !allowPrivateHttp)) {
    throw new Error(`Invalid ${name}`);
  }
  return url.origin;
}

/** Read only this component's configuration. Banking credentials stay in Savia. */
export function readConfig(env = process.env) {
  const host = env.AVATAR_HOST || '127.0.0.1';
  const port = integer(env.AVATAR_PORT, 4318, 1, 65535, 'AVATAR_PORT');
  const publicOrigin = env.AVATAR_PUBLIC_ORIGIN ? origin(env.AVATAR_PUBLIC_ORIGIN, 'AVATAR_PUBLIC_ORIGIN') : null;
  if (!isLoopback(host) && (env.AVATAR_ALLOW_PUBLIC_BIND !== 'true' || !publicOrigin)) {
    throw new Error('A non-loopback listener requires AVATAR_ALLOW_PUBLIC_BIND=true and AVATAR_PUBLIC_ORIGIN');
  }
  const publicAccess = Boolean(publicOrigin && !isLoopback(new URL(publicOrigin).hostname));
  const saviaUpstream = env.SAVIA_UPSTREAM ? origin(env.SAVIA_UPSTREAM, 'SAVIA_UPSTREAM', true) : null;
  // The value is trusted operator configuration, never a URL accepted from a request.
  const saviaOrigin = env.SAVIA_PUBLIC_ORIGIN ? origin(env.SAVIA_PUBLIC_ORIGIN, 'SAVIA_PUBLIC_ORIGIN', true) : saviaUpstream;
  if (saviaOrigin && !saviaUpstream) throw new Error('SAVIA_PUBLIC_ORIGIN requires SAVIA_UPSTREAM');
  const accessGateToken = env.AVATAR_ACCESS_GATE_TOKEN || '';
  if (publicAccess && (!/^[a-zA-Z0-9_-]{32,256}$/.test(accessGateToken))) {
    throw new Error('Public deployment requires a trusted reverse-proxy AVATAR_ACCESS_GATE_TOKEN');
  }
  const allowedOrigins = new Set((env.AVATAR_ALLOWED_ORIGINS || '').split(',').filter(Boolean).map(value => origin(value.trim(), 'AVATAR_ALLOWED_ORIGINS')));
  if (!publicAccess && [...allowedOrigins].some(value => !isLoopback(new URL(value).hostname))) {
    throw new Error('Remote origins require a configured public deployment');
  }
  if (!publicAccess && env.NODE_ENV !== 'production') {
    allowedOrigins.add('http://localhost:4317');
    allowedOrigins.add('http://127.0.0.1:4317');
  }
  if (publicOrigin) allowedOrigins.add(publicOrigin);
  const realtimeModel = env.OPENAI_REALTIME_MODEL || 'gpt-realtime-2.1';
  if (!/^[a-zA-Z0-9._-]{1,128}$/.test(realtimeModel)) throw new Error('Invalid OPENAI_REALTIME_MODEL');
  const openrouterKey = env.OPENROUTER_API_KEY || '';
  const geminiKey = env.GEMINI_API_KEY || env.GOOGLE_API_KEY || '';
  const geminiModel = env.GEMINI_LIVE_MODEL || 'gemini-3.8-live';
  if (!/^gemini-[a-zA-Z0-9._-]{1,100}$/.test(geminiModel)) throw new Error('Invalid GEMINI_LIVE_MODEL');
  // Native audio is the product default. A configured OpenRouter text/TTS key
  // never silently substitutes a chained voice experience for a Live session.
  const voiceProvider = env.AVATAR_VOICE_PROVIDER || (geminiKey ? 'gemini-live' : env.OPENAI_API_KEY ? 'openai-realtime' : 'none');
  if (!['gemini-live', 'openai-realtime', 'openrouter-native', 'openrouter', 'personaplex', 'none'].includes(voiceProvider)) throw new Error('Invalid AVATAR_VOICE_PROVIDER');
  const backgroundAsr = env.AVATAR_BACKGROUND_ASR || '';
  if (!['', 'openrouter'].includes(backgroundAsr)) throw new Error('Invalid AVATAR_BACKGROUND_ASR');
  const nativeReadBridge = env.AVATAR_NATIVE_READ_BRIDGE || '';
  if (!['', 'readonly'].includes(nativeReadBridge)) throw new Error('Invalid AVATAR_NATIVE_READ_BRIDGE');
  const personaplexLeaseFile = env.AVATAR_PERSONAPLEX_LEASE_FILE ? resolve(env.AVATAR_PERSONAPLEX_LEASE_FILE) : null;
  const initialRole = env.AVATAR_PERSONAPLEX_INITIAL_ROLE || '';
  if (!['', 'initial'].includes(initialRole)) throw new Error('Invalid AVATAR_PERSONAPLEX_INITIAL_ROLE');
  const personaplexInitialRole = initialRole === 'initial';
  if (personaplexInitialRole && (voiceProvider !== 'personaplex' || backgroundAsr !== 'openrouter' || !openrouterKey)) {
    throw new Error('Initial native character selection requires PersonaPlex and configured OpenRouter background ASR');
  }
  const geminiVoices = Object.fromEntries(Object.entries({ moss: 'Charon', orbit: 'Kore', spark: 'Puck' }).map(([avatar, fallback]) => {
    const value = env[`GEMINI_LIVE_VOICE_${avatar.toUpperCase()}`] || fallback;
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(value)) throw new Error('Invalid Gemini Live voice');
    return [avatar, value];
  }));
  const routerModel = (name, fallback) => {
    const value = env[name] || fallback;
    if (!/^[a-zA-Z0-9._:/-]{1,128}$/.test(value)) throw new Error(`Invalid ${name}`);
    return value;
  };
  const openrouterTtsModel = routerModel('OPENROUTER_TTS_MODEL', 'google/gemini-3.8-flash-lite-tts');
  const defaultVoices = openrouterTtsModel.startsWith('openai/') ? { moss: 'onyx', orbit: 'nova', spark: 'echo' } : { moss: 'Charon', orbit: 'Kore', spark: 'Puck' };
  const openrouterVoices = Object.fromEntries(Object.keys(defaultVoices).map(avatar => {
    const value = env[`OPENROUTER_TTS_VOICE_${avatar.toUpperCase()}`] || defaultVoices[avatar];
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(value)) throw new Error('Invalid OpenRouter speech voice');
    return [avatar, value];
  }));
  return {
    host, port, publicOrigin, publicAccess, allowedOrigins, accessGateToken,
    secureCookies: Boolean(publicOrigin?.startsWith('https:')),
    saviaUpstream, saviaOrigin,
    openaiKey: env.OPENAI_API_KEY || '', realtimeModel, openrouterKey, voiceProvider, backgroundAsr, nativeReadBridge,
    geminiKey, geminiModel, geminiVoices, personaplexLeaseFile, personaplexInitialRole,
    openrouterSttModel: routerModel('OPENROUTER_STT_MODEL', 'openai/whisper-large-v3'),
    openrouterChatModel: routerModel('OPENROUTER_CHAT_MODEL', 'google/gemini-3.1-flash-lite'),
    openrouterTtsModel, openrouterVoices,
    staticDir: resolve(here, '../dist'),
    upstreamTimeoutMs: integer(env.AVATAR_TASK_TIMEOUT_MS, 460_000, 1000, 600_000, 'AVATAR_TASK_TIMEOUT_MS'),
    realtimeTimeoutMs: 20_000,
    voiceTimeoutMs: 45_000,
    proxyTimeoutMs: 20_000,
    sessionSeconds: 1800,
    maxSessions: 256,
    maxRealtimeStarts: 8,
    maxTasks: 8,
    maxProxyRequests: 64,
    maxVoiceOperations: 8,
    rateLimit: 120,
    realtimeRateLimit: 6,
    voiceOperationRateLimit: 60,
  };
}
