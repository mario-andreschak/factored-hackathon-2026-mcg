import { createHash } from 'node:crypto';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { parseEnv } from 'node:util';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const AVATAR = fileURLToPath(new URL('../', import.meta.url));
const CATALOG = 'https://openrouter.ai/api/v1/models';
const ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions';
export const LIMITS = Object.freeze({ calls: 2, tokens: 128, timeoutMs: 45_000, audioBytes: 2 * 1024 * 1024, streamBytes: 4 * 1024 * 1024 });
export const CASES = Object.freeze([
  Object.freeze({ id: 'es', locale: 'es-CO', instruction: 'Habla solamente en español colombiano natural, sin exagerar el acento. Tu voz es cálida, tranquila y cercana. Contesta con una sola frase de ocho a doce palabras, sin explicar estas instrucciones.', message: 'Me siento un poco nervioso. ¿Puedes acompañarme?' }),
  Object.freeze({ id: 'pt', locale: 'pt-BR', instruction: 'Fale somente em português brasileiro natural, sem exagerar o sotaque. Sua voz é acolhedora, calma e próxima. Responda com uma única frase de oito a doze palavras, sem explicar estas instruções.', message: 'Estou um pouco nervoso. Você pode me acompanhar?' }),
]);

class AuditionError extends Error {
  constructor(code, status) { super(code); this.code = code; if (Number.isInteger(status)) this.status = status; }
}
const fail = code => { throw new AuditionError(code); };
const hash = bytes => createHash('sha256').update(bytes).digest('hex');

export function chooseModel(models) {
  const supported = id => models.find(model => model.id === id && model.architecture?.input_modalities?.includes('text') && model.architecture?.output_modalities?.includes('audio'));
  const selected = supported('openai/gpt-audio-1.5') ?? supported('openai/gpt-audio');
  if (!selected) fail('native_audio_model_unavailable');
  return selected.id;
}

export function requestBody(model, sample) {
  if (!['openai/gpt-audio', 'openai/gpt-audio-1.5'].includes(model) || !CASES.includes(sample)) fail('invalid_fixed_case');
  return { model, modalities: ['text', 'audio'], audio: { voice: 'alloy', format: 'wav' }, stream: true,
    max_tokens: LIMITS.tokens, provider: { allow_fallbacks: false },
    messages: [{ role: 'system', content: sample.instruction }, { role: 'user', content: sample.message }] };
}

/** Declared WAV metadata is authoritative; no PCM sample-rate assumption. */
export function validateWav(data) {
  if (!Buffer.isBuffer(data) || data.length < 44 || data.length > LIMITS.audioBytes ||
      data.toString('ascii', 0, 4) !== 'RIFF' || data.toString('ascii', 8, 12) !== 'WAVE' || data.readUInt32LE(4) + 8 !== data.length) fail('invalid_wav');
  let offset = 12, format, samples;
  while (offset + 8 <= data.length) {
    const kind = data.toString('ascii', offset, offset + 4), size = data.readUInt32LE(offset + 4);
    offset += 8;
    if (offset + size > data.length) fail('invalid_wav');
    if (kind === 'fmt ') {
      if (size < 16 || format) fail('invalid_wav');
      format = { codec: data.readUInt16LE(offset), channels: data.readUInt16LE(offset + 2), sampleRate: data.readUInt32LE(offset + 4),
        byteRate: data.readUInt32LE(offset + 8), alignment: data.readUInt16LE(offset + 12), bits: data.readUInt16LE(offset + 14) };
    }
    if (kind === 'data') { if (samples || !size) fail('invalid_wav'); samples = data.subarray(offset, offset + size); }
    offset += size + size % 2;
  }
  if (offset !== data.length || !format || !samples || format.codec !== 1 || format.channels !== 1 || format.bits !== 16 ||
      format.sampleRate < 8_000 || format.sampleRate > 48_000 || format.alignment !== 2 || format.byteRate !== 2 * format.sampleRate || samples.length % 2) fail('invalid_wav');
  const durationSeconds = samples.length / format.byteRate;
  if (durationSeconds > 30) fail('audio_duration_bound');
  return { sampleRate: format.sampleRate, channels: format.channels, bits: format.bits, durationSeconds, bytes: data.length, sha256: hash(data) };
}

/** Bounded OpenRouter SSE parser. Never retain or print provider diagnostics. */
export async function collectAudio(body, { now = () => performance.now(), started = now() } = {}) {
  if (!body?.getReader) fail('missing_stream');
  const reader = body.getReader(), decoder = new TextDecoder(), audio = [];
  let pending = '', streamedBytes = 0, audioBytes = 0, caption = '', done = false, finishReason = null, firstAudioMs = null, deltas = 0;
  function event(raw) {
    const content = raw.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
    if (!content) return;
    if (content === '[DONE]') { done = true; return; }
    if (done) fail('data_after_done');
    let value; try { value = JSON.parse(content); } catch { fail('invalid_stream_json'); }
    if (value?.error) fail('provider_stream_error');
    for (const choice of value?.choices ?? []) {
      if (choice.index !== undefined && choice.index !== 0) fail('unexpected_choice');
      if (choice.finish_reason) finishReason = ['stop', 'length'].includes(choice.finish_reason) ? choice.finish_reason : 'other';
      const delta = choice.delta?.audio;
      if (typeof delta?.transcript === 'string') { caption += delta.transcript; if (caption.length > 4_000) fail('caption_bound'); }
      if (typeof delta?.data !== 'string') continue;
      if (!/^[A-Za-z0-9+/]*={0,2}$/.test(delta.data) || delta.data.length % 4) fail('invalid_audio_base64');
      const chunk = Buffer.from(delta.data, 'base64');
      if (chunk.toString('base64') !== delta.data) fail('invalid_audio_base64');
      audioBytes += chunk.length; if (audioBytes > LIMITS.audioBytes) fail('audio_byte_bound');
      if (chunk.length) { firstAudioMs ??= now() - started; audio.push(chunk); deltas++; }
    }
  }
  try {
    while (true) {
      const result = await reader.read(); if (result.done) break;
      streamedBytes += result.value.byteLength; if (streamedBytes > LIMITS.streamBytes) fail('stream_byte_bound');
      pending += decoder.decode(result.value, { stream: true });
      let match;
      while ((match = /\r?\n\r?\n/.exec(pending))) { event(pending.slice(0, match.index)); pending = pending.slice(match.index + match[0].length); }
      if (pending.length > 512 * 1024) fail('stream_event_bound');
    }
    pending += decoder.decode(); if (pending.trim()) event(pending);
    if (!done || !finishReason || !audioBytes) fail('incomplete_audio_stream');
    if (/https?:\/\/|Bearer\s|sk-[A-Za-z0-9_-]+/i.test(caption) || /[\u0000-\u0008\u000B\u000C\u000E-\u001F]/.test(caption)) fail('unsafe_caption');
    const wav = Buffer.concat(audio), metadata = validateWav(wav);
    return { wav, metadata, caption, firstAudioMs, deltas, finishReason, elapsedMs: now() - started };
  } finally { try { await reader.cancel(); } catch {} reader.releaseLock(); }
}

export async function audition(fetcher, key, model, sample) {
  const controller = new AbortController(), started = performance.now();
  const timeout = setTimeout(() => controller.abort(), LIMITS.timeoutMs);
  try {
    const response = await fetcher(ENDPOINT, { method: 'POST', signal: controller.signal, redirect: 'error',
      headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' }, body: JSON.stringify(requestBody(model, sample)) });
    if (!response.ok) { try { await response.body?.cancel(); } catch {} throw new AuditionError('provider_request_rejected', response.status); }
    if (!/^text\/event-stream\b/i.test(response.headers.get('content-type') ?? '')) { try { await response.body?.cancel(); } catch {} fail('unexpected_content_type'); }
    return await collectAudio(response.body, { started });
  } catch (error) {
    if (controller.signal.aborted) throw new AuditionError('request_deadline');
    if (error instanceof AuditionError) throw error;
    throw new AuditionError('transport_failed');
  } finally { clearTimeout(timeout); controller.abort(); }
}

export async function main(args = process.argv.slice(2)) {
  if (args.length > 1 || (args.length && !['--execute', '--plan'].includes(args[0]))) fail('invalid_arguments');
  if (args[0] !== '--execute') {
    console.log(JSON.stringify({ status: 'prepared', nativeModel: true, input: 'two fixed synthetic text questions', output: 'streamed WAV with declared format validation', voice: 'alloy', locales: CASES.map(c => c.locale), ...LIMITS, retries: 0, dedicatedTtsCalls: 0, liveTransportQualified: false }));
    return;
  }
  const directory = path.join(AVATAR, '.local', 'openrouter-native', new Date().toISOString().replace(/[:.]/g, '-'));
  await mkdir(directory, { recursive: true });
  const report = { status: 'started', nativeModel: true, audioInputQualified: false, liveTransportQualified: false, physicalMicrophoneUsed: false, dedicatedTtsCalls: 0, upstreamCalls: 0, retries: 0, voice: 'alloy', maxOutputTokens: LIMITS.tokens, timeoutMs: LIMITS.timeoutMs, samples: [] };
  const receipt = () => writeFile(path.join(directory, 'report.json'), JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
  await receipt();
  try {
    const env = parseEnv(await readFile(path.join(AVATAR, 'openrouter.env'), 'utf8'));
    const key = env.OPENROUTER_API_KEY;
    if (!key?.trim()) fail('local_key_unconfigured');
    const response = await fetch(CATALOG, { signal: AbortSignal.timeout(15_000), redirect: 'error' });
    if (!response.ok) fail('catalog_unavailable');
    const catalog = await response.json(); report.model = chooseModel(catalog.data ?? []);
    for (const sample of CASES) {
      report.upstreamCalls++; await receipt();
      try {
        const result = await audition(fetch, key, report.model, sample);
        await writeFile(path.join(directory, `${sample.id}.wav`), result.wav, { flag: 'wx', mode: 0o600 });
        const { wav, ...details } = result;
        report.samples.push({ locale: sample.locale, file: `${sample.id}.wav`, status: 'completed', ...details, captionSource: 'provider transcript; independent ASR/human accent check pending' });
      } catch (error) {
        report.samples.push({ locale: sample.locale, status: 'failed', code: error instanceof AuditionError ? error.code : 'audition_failed', ...(Number.isInteger(error.status) ? { httpStatus: error.status } : {}) });
      }
      await receipt();
    }
    report.status = report.samples.every(sample => sample.status === 'completed') ? 'completed' : 'failed';
  } catch (error) { report.status = 'failed'; report.code = error instanceof AuditionError ? error.code : 'preflight_failed'; }
  await receipt();
  console.log(JSON.stringify({ status: report.status, model: report.model ?? null, upstreamCalls: report.upstreamCalls, samples: report.samples.map(({ locale, status, code, httpStatus, metadata, firstAudioMs, elapsedMs, finishReason }) => ({ locale, status, code, httpStatus, metadata, firstAudioMs, elapsedMs, finishReason })), outputDirectory: directory }));
  if (report.status !== 'completed') process.exitCode = 1;
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  main().catch(() => { console.log(JSON.stringify({ status: 'failed', code: 'local_preparation_failed' })); process.exitCode = 1; });
}
