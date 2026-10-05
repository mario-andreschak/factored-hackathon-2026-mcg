/** Separate native-audio audition. Default --plan does no I/O or network work. */
import { createHash } from 'node:crypto';
import { lstat, readFile, mkdir, writeFile } from 'node:fs/promises';
import { parseEnv } from 'node:util';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { validateWav } from './openrouter_native_audition.mjs';

const AVATAR = fileURLToPath(new URL('../', import.meta.url));
const ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions';
export const MODEL = 'openai/gpt-audio';
export const VOICE = 'coral';
export const RATE = 24_000;
export const LIMITS = Object.freeze({ calls: 2, outputTokens: 512, timeoutMs: 45_000, cleanupTimeoutMs: 100,
  audioBytes: RATE * 2 * 30, streamBytes: 4 * 1024 * 1024, diagnosticBytes: 8192,
  estimatedTotalUsdCeiling: .10 });
export const PRICES = Object.freeze({ textInputPerMillion: 2.5, textOutputPerMillion: 10,
  audioInputPerMillion: 32, audioOutputPerMillion: 64, reviewedDate: '2026-10-01',
  source: 'https://openrouter.ai/openai/gpt-audio' });
export const CASES = Object.freeze([
  Object.freeze({ id: 'es', locale: 'es-CO', bytes: 198614,
    sha256: '3956bc585e5bac204010593ea5ae37182ac47828d034ffcb36f8e8daca481d6c', seconds: 4.136875,
    instruction: 'Habla solo en español colombiano natural, sin exagerar el acento. Sé cálido y tranquilo. Responde a lo que escuchas con una frase breve de ocho a doce palabras.',
    question: '¿Qué le responderías a la persona que escuchas?' }),
  Object.freeze({ id: 'pt', locale: 'pt-BR', bytes: 240854,
    sha256: '1b9a1ce221bd44ce01f454dd5214415fa48b7d078dc92875b153f7baa96cf6ad', seconds: 5.016875,
    instruction: 'Fale só em português brasileiro natural, sem exagerar o sotaque. Seja acolhedor e calmo. Responda ao que escuta com uma frase curta de oito a doze palavras.',
    question: 'O que você responderia à pessoa que está ouvindo?' }),
]);
const FIXTURE_DIRECTORY = path.join(AVATAR, '.local', 'qwen-native', '20261001-084853-1790862533806878800');
const DIRECTORY = path.join(AVATAR, '.local', 'openrouter-s2s');
const sha = value => createHash('sha256').update(value).digest('hex');
export const REFERENCES = Object.freeze({
  protocol: 'https://openrouter.ai/docs/guides/overview/multimodal/audio',
  accounting: 'https://openrouter.ai/docs/cookbook/administration/usage-accounting',
  nativeModel: 'https://developers.openai.com/api/docs/guides/audio-chat-completions',
  voices: 'https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create',
  lifecycle: 'https://developers.openai.com/api/docs/deprecations',
});

export class AuditionError extends Error {
  constructor(code, diagnostic) { super(code); this.code = code; this.diagnostic = diagnostic; }
}
const fail = code => { throw new AuditionError(code); };

export function plan() {
  return { status: 'prepared_not_dispatched', namespace: 'openrouter_native_s2s_pcm16_v1', model: MODEL,
    provider: 'openai', voice: VOICE, input: 'exact two public synthetic native Qwen WAV fixtures',
    locales: CASES.map(c => c.locale), output: 'native model audio; SSE PCM16 converted to24k mono WAV',
    ...LIMITS, prices: PRICES, references: REFERENCES,
    modelShutdownScheduled: '2027-01-20; operator compatibility planning only',
    retries: 0, fallback: false, gpuCalls: 0, dedicatedTtsCalls: 0,
    asrCalls: 0, bankingAccess: false, physicalMicrophoneUsed: false, endpointedRequest: true,
    liveWebsocketQualified: false, bargeInQualified: false, humanVoiceQualityVerified: false,
    pcmPackagingRateHz: RATE, pcmPackagingRateQualified: false, providerHardSpendCap: false,
    worstOutputTokenChargeUsd: LIMITS.calls * LIMITS.outputTokens * PRICES.audioOutputPerMillion / 1_000_000,
    inputTokenBillingBoundQualified: false };
}

export function validateFixture(value, sample) {
  if (!CASES.includes(sample) || !Buffer.isBuffer(value) || value.length !== sample.bytes || sha(value) !== sample.sha256)
    fail('fixture_hash_mismatch');
  const profile = validateWav(value);
  if (profile.sampleRate !== RATE || profile.durationSeconds !== sample.seconds) fail('fixture_profile_mismatch');
  return profile;
}

export function requestBody(sample, wav) {
  validateFixture(wav, sample);
  return { model: MODEL, modalities: ['text', 'audio'], audio: { voice: VOICE, format: 'pcm16' },
    stream: true, max_tokens: LIMITS.outputTokens,
    provider: { only: ['openai'], order: ['openai'], allow_fallbacks: false },
    messages: [{ role: 'system', content: sample.instruction }, { role: 'user', content: [
      { type: 'text', text: sample.question },
      { type: 'input_audio', input_audio: { data: wav.toString('base64'), format: 'wav' } },
    ] }] };
}

const SAFE_CODES = new Set(['invalid_request_error', 'invalid_value', 'unsupported_value', 'unsupported_parameter',
  'missing_required_parameter', 'invalid_api_key', 'insufficient_quota', 'credit_balance_exhausted',
  'rate_limit_exceeded', 'context_length_exceeded', 'model_not_found', 'content_filter', 'server_error']);
const SAFE_TYPES = new Set(['invalid_request_error', 'authentication_error', 'permission_error',
  'rate_limit_error', 'insufficient_quota', 'server_error', 'invalid_error']);
const SAFE_PARAMS = new Set(['audio.format', 'audio.voice', 'audio', 'modalities', 'stream', 'stream_options',
  'max_tokens', 'model', 'messages', 'input_audio', 'input_audio.format', 'input_audio.data']);

/** Inspect bounded provider strings only to emit fixed diagnostic enums, never their raw values. */
export function sanitizeError(value, status, truncated = false) {
  const root = value?.error && typeof value.error === 'object' ? value.error : {};
  let upstream = root;
  if (typeof root.metadata?.raw === 'string' && root.metadata.raw.length <= LIMITS.diagnosticBytes) {
    try { const parsed = JSON.parse(root.metadata.raw); if (parsed?.error && typeof parsed.error === 'object') upstream = parsed.error; } catch {}
  }
  const messages = [root.message, upstream.message].filter(v => typeof v === 'string').join(' ').slice(0, LIMITS.diagnosticBytes).toLowerCase();
  const param = typeof upstream.param === 'string' ? upstream.param : typeof root.param === 'string' ? root.param : '';
  const normalized = param.replace(/^messages\[[0-9]+\]\.content\[[0-9]+\]\./, '');
  const hints = [
    ['audio_format', /(?:audio[._ ]?format|pcm16|wav|unsupported format)/],
    ['voice', /(?:audio[._ ]?voice|unsupported voice|invalid voice)/],
    ['streaming', /stream(?:ing)?/], ['audio_input', /input_audio|audio input/],
    ['modalities', /modalit/], ['token_bound', /max_tokens|token limit|context length/],
    ['quota', /quota|credit|balance/], ['authentication', /authentication|api key|unauthorized/],
    ['rate_limit', /rate limit/], ['model', /model not found|unknown model/],
  ].filter(([, expression]) => expression.test(messages + ' ' + param.toLowerCase())).map(([name]) => name);
  return { httpStatus: Number.isInteger(status) ? status : null,
    routerCode: Number.isInteger(root.code) && root.code >= 100 && root.code <= 599 ? root.code : SAFE_CODES.has(root.code) ? root.code : null,
    upstreamCode: SAFE_CODES.has(upstream.code) ? upstream.code : null,
    upstreamType: SAFE_TYPES.has(upstream.type) ? upstream.type : null,
    parameter: SAFE_PARAMS.has(normalized) ? normalized : null,
    provider: root.metadata?.provider_name === 'OpenAI' ? 'OpenAI' : null,
    reasonHints: hints, bodyTruncated: truncated, validJson: value !== null,
    rawProviderBodyStored: false };
}

function abortable(promise, signal) {
  if (signal.aborted) return Promise.reject(new AuditionError('request_deadline'));
  return new Promise((resolve, reject) => {
    const aborted = () => { cleanup(); reject(new AuditionError('request_deadline')); };
    const cleanup = () => signal.removeEventListener('abort', aborted);
    signal.addEventListener('abort', aborted, { once: true });
    Promise.resolve(promise).then(value => { cleanup(); resolve(value); }, error => { cleanup(); reject(error); });
  });
}

/** Cancellation is attempted once; a broken transport cannot hold the audition open. */
async function boundedCancel(target) {
  if (typeof target?.cancel !== 'function') return;
  let timer;
  try {
    await Promise.race([
      Promise.resolve().then(() => target.cancel()).catch(() => {}),
      new Promise(resolve => { timer = setTimeout(resolve, LIMITS.cleanupTimeoutMs); }),
    ]);
  } finally { clearTimeout(timer); }
}

async function rejection(response, signal) {
  if (!response.body?.getReader) return sanitizeError(null, response.status);
  const reader = response.body.getReader(); const parts = []; let bytes = 0, truncated = false;
  try {
    while (true) {
      const result = await abortable(reader.read(), signal); if (result.done) break;
      const remaining = LIMITS.diagnosticBytes - bytes;
      parts.push(Buffer.from(result.value).subarray(0, remaining)); bytes += Math.min(remaining, result.value.byteLength);
      if (result.value.byteLength > remaining || bytes === LIMITS.diagnosticBytes) { truncated = true; break; }
    }
    let value = null; try { value = JSON.parse(Buffer.concat(parts).toString('utf8')); } catch {}
    return sanitizeError(value, response.status, truncated);
  } finally { await boundedCancel(reader); try { reader.releaseLock(); } catch {} }
}

export function pcmToWav(pcm) {
  if (!Buffer.isBuffer(pcm) || !pcm.length || pcm.length % 2 || pcm.length > LIMITS.audioBytes ||
      pcm.subarray(0, 4).toString('ascii') === 'RIFF') fail('invalid_native_pcm');
  const header = Buffer.alloc(44);
  header.write('RIFF', 0); header.writeUInt32LE(36 + pcm.length, 4); header.write('WAVEfmt ', 8);
  header.writeUInt32LE(16, 16); header.writeUInt16LE(1, 20); header.writeUInt16LE(1, 22);
  header.writeUInt32LE(RATE, 24); header.writeUInt32LE(RATE * 2, 28);
  header.writeUInt16LE(2, 32); header.writeUInt16LE(16, 34); header.write('data', 36); header.writeUInt32LE(pcm.length, 40);
  return Buffer.concat([header, pcm]);
}

function safeUsage(value) {
  if (!value || typeof value !== 'object') return null;
  const number = (key, max = 1_000_000) => Number.isFinite(value[key]) && value[key] >= 0 && value[key] <= max ? value[key] : null;
  const audioNumber = candidate => Number.isInteger(candidate) && candidate >= 0 && candidate <= 1_000_000 ? candidate : null;
  return { promptTokens: number('prompt_tokens'), completionTokens: number('completion_tokens'), totalTokens: number('total_tokens'),
    costUsd: number('cost', 1),
    inputAudioTokens: audioNumber(value.prompt_tokens_details?.audio_tokens),
    outputAudioTokens: audioNumber(value.completion_tokens_details?.audio_tokens) };
}

/** Actual first-call usage anchors an explicitly conservative second-input forecast; no hard provider budget is claimed. */
export function forecastSecond(usage) {
  if (!Number.isFinite(usage?.costUsd) || usage.costUsd < 0 || !Number.isInteger(usage.inputAudioTokens) ||
      usage.inputAudioTokens <= 0 || !Number.isInteger(usage.promptTokens) || usage.promptTokens < usage.inputAudioTokens ||
      !Number.isInteger(usage.outputAudioTokens) || !Number.isInteger(usage.totalTokens))
    return { allowed: false, code: 'missing_audio_usage_forecast' };
  const forecastAudioTokens = Math.ceil(usage.inputAudioTokens * CASES[1].seconds / CASES[0].seconds * 1.5) + 64;
  const forecastTextTokens = Math.ceil(Math.max(200, usage.promptTokens - usage.inputAudioTokens) * 1.5) + 128;
  const inputForecastUsd = (forecastAudioTokens * PRICES.audioInputPerMillion + forecastTextTokens * PRICES.textInputPerMillion) / 1_000_000;
  const outputReservationUsd = LIMITS.outputTokens * PRICES.audioOutputPerMillion / 1_000_000;
  const remainingUsd = LIMITS.estimatedTotalUsdCeiling - usage.costUsd;
  return { allowed: remainingUsd >= inputForecastUsd + outputReservationUsd,
    code: remainingUsd >= inputForecastUsd + outputReservationUsd ? 'forecast_within_budget' : 'remaining_budget_forecast_insufficient',
    remainingUsd, inputForecastUsd, outputReservationUsd, forecastAudioTokens, forecastTextTokens,
    audioDurationRatio: CASES[1].seconds / CASES[0].seconds, tokenMargin: 1.5, hardSpendGuarantee: false };
}

export async function collectPcm(body, { signal, now = () => performance.now(), started = now() } = {}) {
  if (!body?.getReader || !signal) fail('missing_stream');
  const reader = body.getReader(), decoder = new TextDecoder(); const audio = [];
  let pending = '', streamed = 0, bytes = 0, caption = '', firstAudioMs = null, deltas = 0,
    done = false, finishReason = null, usage = null;
  function event(raw) {
    const content = raw.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
    if (!content) return;
    if (content === '[DONE]') { done = true; return; }
    if (done) fail('data_after_done');
    let value; try { value = JSON.parse(content); } catch { fail('invalid_stream_json'); }
    if (value?.error) throw new AuditionError('provider_stream_error', sanitizeError(value, 200));
    if (value?.usage) usage = safeUsage(value.usage);
    for (const choice of value.choices ?? []) {
      if (choice.index !== undefined && choice.index !== 0) fail('unexpected_choice');
      if (choice.finish_reason) finishReason = ['stop', 'length'].includes(choice.finish_reason) ? choice.finish_reason : 'other';
      const delta = choice.delta?.audio;
      if (typeof delta?.transcript === 'string') { caption += delta.transcript; if (caption.length > 4000) fail('caption_bound'); }
      if (typeof delta?.data !== 'string') continue;
      if (!/^[A-Za-z0-9+/]*={0,2}$/.test(delta.data) || delta.data.length % 4) fail('invalid_audio_base64');
      const chunk = Buffer.from(delta.data, 'base64'); if (chunk.toString('base64') !== delta.data) fail('invalid_audio_base64');
      bytes += chunk.length; if (bytes > LIMITS.audioBytes) fail('audio_byte_bound');
      if (chunk.length) { audio.push(chunk); firstAudioMs ??= now() - started; deltas++; }
    }
  }
  try {
    while (true) {
      const result = await abortable(reader.read(), signal); if (result.done) break;
      streamed += result.value.byteLength; if (streamed > LIMITS.streamBytes) fail('stream_byte_bound');
      pending += decoder.decode(result.value, { stream: true });
      let split;
      while ((split = /\r?\n\r?\n/.exec(pending))) { event(pending.slice(0, split.index)); pending = pending.slice(split.index + split[0].length); }
      if (pending.length > 512 * 1024) fail('stream_event_bound');
    }
    pending += decoder.decode(); if (pending.trim()) event(pending);
    if (!done || finishReason !== 'stop' || !bytes)
      throw new AuditionError('incomplete_audio_stream', { finishReason, usage });
    if (usage?.costUsd === null || usage?.costUsd === undefined) fail('missing_usage_cost');
    if (/https?:\/\/|Bearer\s|sk-[A-Za-z0-9_-]+/i.test(caption) || /[\u0000-\u0008\u000B\u000C\u000E-\u001F]/.test(caption)) fail('unsafe_caption');
    const rawPcm = Buffer.concat(audio), wav = pcmToWav(rawPcm);
    return { wav, rawPcm, pcm: { bytes: rawPcm.length, sha256: sha(rawPcm), format: 'raw PCM16',
      sampleRateAssumed: RATE, channelsAssumed: 1, endiannessAssumed: 'little', pitchRateQualified: false },
      audio: { ...validateWav(wav), packagingRateQualified: false, packagingRateSource: 'explicit24k audition assumption; Chat PCM rate not primary-documented' },
      caption, firstAudioMs, deltas, finishReason, usage, elapsedMs: now() - started };
  } finally { await boundedCancel(reader); try { reader.releaseLock(); } catch {} }
}

export async function audition(fetcher, key, sample, wav, { timeoutMs = LIMITS.timeoutMs } = {}) {
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > LIMITS.timeoutMs) fail('invalid_deadline');
  const body = requestBody(sample, wav), controller = new AbortController(), started = performance.now();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await abortable(fetcher(ENDPOINT, { method: 'POST', signal: controller.signal, redirect: 'error',
      headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' }, body: JSON.stringify(body) }), controller.signal);
    if (!response.ok) throw new AuditionError('provider_request_rejected', await rejection(response, controller.signal));
    if (!/^text\/event-stream\b/i.test(response.headers.get('content-type') ?? '')) {
      await boundedCancel(response.body); fail('unexpected_content_type');
    }
    return await collectPcm(response.body, { signal: controller.signal, started });
  } catch (error) {
    if (controller.signal.aborted) throw new AuditionError('request_deadline');
    if (error instanceof AuditionError) throw error;
    throw new AuditionError('transport_failed');
  } finally { clearTimeout(timeout); controller.abort(); }
}

export async function consumeAdmission(directory, value) {
  await mkdir(directory, { recursive: true });
  await writeFile(path.join(directory, 'native-pcm16-admitted.json'), JSON.stringify(value, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
}

export async function main(args = process.argv.slice(2)) {
  if (args.length > 1 || args.length && !['--plan', '--execute'].includes(args[0])) fail('invalid_arguments');
  if (args[0] !== '--execute') { console.log(JSON.stringify(plan())); return; }
  const files = new Map();
  for (const sample of CASES) {
    const file = path.join(FIXTURE_DIRECTORY, sample.id + '.wav'), info = await lstat(file);
    if (info.isSymbolicLink() || !info.isFile() || info.size !== sample.bytes) fail('fixture_missing');
    const value = await readFile(file); validateFixture(value, sample); files.set(sample.id, value);
  }
  await consumeAdmission(DIRECTORY, { status: 'spent_before_dispatch', model: MODEL, voice: VOICE,
    namespace: plan().namespace, fixtures: CASES.map(({ id, sha256 }) => ({ id, sha256 })), limits: LIMITS });
  const destination = path.join(DIRECTORY, new Date().toISOString().replace(/[:.]/g, '-'));
  await mkdir(destination, { recursive: false });
  const report = { ...plan(), status: 'started', upstreamCalls: 0, observedCostUsd: 0,
    knownReportedCostUsd: 0, callsWithReportedCost: 0, samples: [] };
  const save = () => writeFile(path.join(destination, 'report.json'), JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
  await save();
  try {
    const env = parseEnv(await readFile(path.join(AVATAR, 'openrouter.env'), 'utf8'));
    const key = env.OPENROUTER_API_KEY; if (!key?.trim()) fail('local_key_unconfigured');
    for (const sample of CASES) {
      if (report.upstreamCalls >= LIMITS.calls) break;
      if (sample.id === 'pt') {
        report.secondRequestForecast = forecastSecond(report.samples[0]?.usage);
        if (!report.secondRequestForecast.allowed) { report.code = report.secondRequestForecast.code; break; }
      }
      report.upstreamCalls++; await save();
      try {
        const result = await audition(fetch, key, sample, files.get(sample.id));
        await writeFile(path.join(destination, sample.id + '.wav'), result.wav, { flag: 'wx', mode: 0o600 });
        await writeFile(path.join(destination, sample.id + '.pcm'), result.rawPcm, { flag: 'wx', mode: 0o600 });
        const { wav, rawPcm, ...details } = result;
        report.knownReportedCostUsd += details.usage.costUsd; report.callsWithReportedCost++;
        report.observedCostUsd = report.callsWithReportedCost === report.upstreamCalls ? report.knownReportedCostUsd : null;
        report.samples.push({ id: sample.id, locale: sample.locale, status: 'completed', inputSha256: sample.sha256,
          file: sample.id + '.wav', captionSource: 'native model assistant transcript, not independent ASR',
          rawPcmFile: sample.id + '.pcm', audioInputSupplied: true, audioInputUnderstandingVerified: false, ...details });
      } catch (error) {
        const errorUsage = error.diagnostic?.usage;
        if (Number.isFinite(errorUsage?.costUsd)) {
          report.knownReportedCostUsd += errorUsage.costUsd; report.callsWithReportedCost++;
        }
        report.observedCostUsd = report.callsWithReportedCost === report.upstreamCalls ? report.knownReportedCostUsd : null;
        report.samples.push({ id: sample.id, locale: sample.locale, status: 'failed',
          code: error instanceof AuditionError ? error.code : 'audition_failed',
          ...(error instanceof AuditionError && error.diagnostic ? { diagnostic: error.diagnostic } : {}) });
        // The other locale is not used to repeat a rejected format/key/configuration.
        await save(); break;
      }
      await save();
    }
    report.status = report.samples.length === CASES.length && report.samples.every(v => v.status === 'completed') &&
      report.observedCostUsd <= LIMITS.estimatedTotalUsdCeiling ? 'completed' : 'failed';
  } catch (error) { report.status = 'failed'; report.code = error instanceof AuditionError ? error.code : 'local_preparation_failed'; }
  await save();
  console.log(JSON.stringify({ status: report.status, model: MODEL, upstreamCalls: report.upstreamCalls,
    observedCostUsd: report.observedCostUsd, outputDirectory: destination,
    samples: report.samples.map(({ id, locale, status, code, diagnostic, audio, firstAudioMs, elapsedMs }) =>
      ({ id, locale, status, code, diagnostic, audio, firstAudioMs, elapsedMs })),
    liveWebsocketQualified: false, humanVoiceQualityVerified: false }));
  if (report.status !== 'completed') process.exitCode = 1;
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url)
  main().catch(error => { console.log(JSON.stringify({ status: 'failed', code: error instanceof AuditionError ? error.code : 'local_preparation_failed' })); process.exitCode = 1; });
