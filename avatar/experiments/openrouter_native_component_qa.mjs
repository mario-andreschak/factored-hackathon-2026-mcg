/** Source-only preparation. --plan is inert; only --execute-component-qa admits paid requests. */
import { createHash } from 'node:crypto';
import { lstat, readFile, mkdir, writeFile } from 'node:fs/promises';
import { parseEnv } from 'node:util';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { createAvatarServer } from '../server/app.mjs';
import { readConfig } from '../server/config.mjs';
import { NATIVE_AUDIO } from '../server/openrouter-native.mjs';
import { CASES, PRICES, validateFixture } from './openrouter_s2s_audition.mjs';
import { PRIOR as FIRST } from './openrouter_s2s_sdk_terminal.mjs';
import { PRIOR as SECOND } from './openrouter_s2s_normalized_terminal.mjs';
import { PRIOR as THIRD, NAMESPACE as TAIL_NAMESPACE, validateTailEvidence } from './openrouter_s2s_pt_tail.mjs';

const AVATAR = fileURLToPath(new URL('../', import.meta.url)), LOCAL = path.join(AVATAR, '.local');
const DESTINATION = path.join(LOCAL, 'openrouter-native-component-qa');
const FIXTURES = path.join(LOCAL, 'qwen-native', '20261001-084853-1790862533806878800');
export const NAMESPACE = 'openrouter_native_component_http_qa_v1';
export const PRIOR = Object.freeze({ costUsd: .031058, ptCostUsd: .009474,
  ptReport: '2026-10-01T16-44-50-910Z/report.json',
  ptReportSha256: '049a5e981d76a6c19c52348a235d3e8f6d982f11054972c8c48cd027cdd6c3fa',
  markerHashes: Object.freeze([
    'f22efcdd5b62bf9cb3a2ab382c17121b9a9a0ab92418306b67508040b5e31188',
    '1cc87ace5b8a1cfb7dffa4379b6c33bca226022d077744ea596bfdcac12df13b',
    '202df91b9a903916e44ce50922a231963790dccf91aedf9535a200d66aed0a87',
    '0bbe6a687d2df5e82fc421ff74b08930995874bcb7638fa6f3c06b3128a0d84c',
  ]) });
export const EVIDENCE_FILES = Object.freeze([
  ['openrouter-s2s', FIRST.report], ['openrouter-s2s', 'native-pcm16-admitted.json'],
  ['openrouter-s2s-sdk-terminal', SECOND.secondReport], ['openrouter-s2s-sdk-terminal', 'sdk-terminal-correction-admitted.json'],
  ['openrouter-s2s-normalized-terminal', THIRD.thirdReport], ['openrouter-s2s-normalized-terminal', 'application-terminal-admitted.json'],
  ['openrouter-s2s-pt-tail', PRIOR.ptReport], ['openrouter-s2s-pt-tail', 'pt-metadata-tail-admitted.json'],
]);
export const SOURCE_FILES = Object.freeze(['server/openrouter-native.mjs', 'server/native-turns.mjs', 'server/app.mjs',
  'server/savia.mjs', 'server/config.mjs', 'server/locale.mjs', 'src/useNativeRouterVoice.ts',
  'src/nativeRouterPlayback.ts', 'src/Game.tsx', 'experiments/openrouter_native_component_qa.mjs']);
const sha = value => createHash('sha256').update(value).digest('hex');
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const only = (value, fields) => object(value) && Object.keys(value).every(key => fields.includes(key));
const fail = code => { throw Object.assign(new Error(code), { code }); };
const SAFE_CODES = new Set(['invalid_native_audio_stream', 'native_audio_incomplete', 'voice_interrupted', 'voice_timeout',
  'voice_unavailable', 'voice_configuration_error', 'voice_quota_exhausted', 'rate_limited', 'capacity',
  'component_protocol_invalid', 'component_request_rejected', 'component_stream_incomplete', 'component_deadline',
  'component_played_receipt_rejected', 'production_dispatch_mismatch', 'unowned_upstream_endpoint',
  'source_changed', 'local_key_unconfigured', 'local_preparation_failed']);
const safeCode = error => SAFE_CODES.has(error?.code) ? error.code : 'local_preparation_failed';

export function forecast(knownCostUsd, sample = CASES[0], reference = { inputAudioTokens: 41, seconds: CASES[0].seconds }) {
  if (!CASES.includes(sample) || !Number.isFinite(knownCostUsd) || knownCostUsd < PRIOR.costUsd ||
      !Number.isInteger(reference?.inputAudioTokens) || reference.inputAudioTokens <= 0 || reference.inputAudioTokens > 1e6 ||
      !Number.isFinite(reference.seconds) || reference.seconds <= 0) return { allowed: false, code: 'usage_unknown' };
  const inputAudioTokens = Math.ceil(reference.inputAudioTokens * sample.seconds / reference.seconds * 1.5) + 64;
  const inputAudioReservationUsd = inputAudioTokens * PRICES.audioInputPerMillion / 1e6;
  const outputReservationUsd = 512 * PRICES.audioOutputPerMillion / 1e6;
  const textAndContextMarginUsd = .005;
  const forecastIncludingPriorUsd = knownCostUsd + inputAudioReservationUsd + outputReservationUsd + textAndContextMarginUsd;
  return { allowed: forecastIncludingPriorUsd <= .10, knownCostUsd, inputAudioTokens, inputAudioReservationUsd,
    outputReservationUsd, textAndContextMarginUsd, forecastIncludingPriorUsd, ceilingUsd: .10, hardSpendGuarantee: false };
}
export function plan() {
  return { status: 'source_prepared_not_dispatched', namespace: NAMESPACE, calls: 2, spanishCalls: 1, portugueseCalls: 'optional1',
    model: 'openai/gpt-audio', provider: 'openai', voice: 'coral', outputTokens: 512, timeoutMs: 45000, cleanupMs: 100,
    locales: ['es', 'pt'], originalFixtures: CASES.map(({ id, sha256, bytes, seconds }) => ({ id, sha256, bytes, seconds })),
    knownPriorCostUsd: PRIOR.costUsd, completedPtReceiptSha256: PRIOR.ptReportSha256, priorMarkerHashes: PRIOR.markerHashes,
    firstForecast: forecast(PRIOR.costUsd), sourceFiles: SOURCE_FILES, retries: 0, fallback: false,
    actualProductionServerApi: true, listener: 'ephemeral127.0.0.1', observerExercised: false, asrCalls: 0,
    saviaConfigured: false, bankCalls: 0, gpuCalls: 0, dedicatedTtsCalls: 0, physicalMicrophoneUsed: false,
    simulatedPlayedReceipt: true, browserPlaybackQualified: false, bargeInQualified: false, liveWebsocketQualified: false,
    humanVoiceQualityQualified: false, nativeInputSemanticQualified: false,
    pcmSampleRate: 24000, pcmSampleRateQualification: 'assumed', providerHardSpendCap: false,
    earlierFailedReceiptsRemainFailed: true, rawSseStored: false, credentialReadDuringPlan: false };
}

export function validateComponentEvidence(values) {
  if (!Array.isArray(values) || values.length !== 8) fail('prior_provenance_invalid');
  const earlier = validateTailEvidence(...values.slice(0, 6));
  for (let index = 0; index < 4; index++) if (!Buffer.isBuffer(values[index * 2 + 1]) || sha(values[index * 2 + 1]) !== PRIOR.markerHashes[index]) fail('prior_marker_hash_mismatch');
  if (!Buffer.isBuffer(values[6]) || values[6].length > 128 * 1024 || sha(values[6]) !== PRIOR.ptReportSha256) fail('prior_pt_hash_mismatch');
  let report, marker;
  try { report = JSON.parse(values[6]); marker = JSON.parse(values[7]); } catch { fail('prior_provenance_invalid'); }
  const sample = report.samples?.[0];
  if (report.namespace !== TAIL_NAMESPACE || report.model !== NATIVE_AUDIO.model || report.voice !== NATIVE_AUDIO.voice ||
      report.status !== 'completed' || report.upstreamCalls !== 1 || report.samples?.length !== 1 || sample.id !== 'pt' ||
      sample.status !== 'completed' || sample.strictCompletionPassed !== true || sample.usage?.costUsd !== PRIOR.ptCostUsd ||
      report.correctionCostUsd !== PRIOR.ptCostUsd || report.totalObservedCostIncludingPriorUsd !== PRIOR.costUsd ||
      marker.namespace !== TAIL_NAMESPACE || marker.status !== 'spent_before_dispatch' || marker.calls !== 1 ||
      marker.model !== NATIVE_AUDIO.model || marker.voice !== NATIVE_AUDIO.voice ||
      marker.priorFailures?.thirdReportSha256 !== earlier.thirdReportSha256) fail('prior_provenance_invalid');
  return { earlier, completedPtReceiptSha256: PRIOR.ptReportSha256, markerHashes: [...PRIOR.markerHashes], knownPriorCostUsd: PRIOR.costUsd };
}
export async function consumeComponentAdmission(directory, proof, sourceHashes) {
  if (proof?.completedPtReceiptSha256 !== PRIOR.ptReportSha256 || proof.knownPriorCostUsd !== PRIOR.costUsd ||
      JSON.stringify(proof.markerHashes) !== JSON.stringify(PRIOR.markerHashes) ||
      proof.earlier?.firstReportSha256 !== THIRD.firstReportSha256 ||
      proof.earlier?.secondReportSha256 !== THIRD.secondReportSha256 ||
      proof.earlier?.thirdReportSha256 !== THIRD.thirdReportSha256 ||
      proof.earlier?.knownPriorCostUsd !== THIRD.totalCostUsd ||
      !['firstAdmissionSha256', 'secondAdmissionSha256', 'thirdAdmissionSha256'].every((key, index) =>
        proof.earlier?.[key] === PRIOR.markerHashes[index]) ||
      !only(sourceHashes, SOURCE_FILES) || Object.keys(sourceHashes).length !== SOURCE_FILES.length ||
      !SOURCE_FILES.every(file => /^[a-f0-9]{64}$/.test(sourceHashes[file] ?? ''))) fail('prior_provenance_invalid');
  await mkdir(directory, { recursive: true });
  const record = { status: 'spent_before_dispatch', namespace: NAMESPACE, proof, sourceHashes,
    model: NATIVE_AUDIO.model, voice: NATIVE_AUDIO.voice, calls: 2, observerCalls: 0, forecast: plan().firstForecast };
  await writeFile(path.join(directory, 'component-http-admitted.json'), JSON.stringify(record, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
  return record;
}
async function boundedFile(file, maximum) {
  const info = await lstat(file);
  if (!info.isFile() || info.isSymbolicLink() || info.size > maximum) fail('local_preparation_failed');
  return readFile(file);
}
async function sourceSnapshot() {
  const hashes = {};
  for (const file of SOURCE_FILES) hashes[file] = sha(await boundedFile(path.join(AVATAR, file), 1024 * 1024));
  return hashes;
}
function abortable(promise, signal) {
  if (signal.aborted) { void Promise.resolve(promise).catch(() => {}); return Promise.reject(Object.assign(new Error(), { code: 'component_deadline' })); }
  return new Promise((resolve, reject) => {
    const cleanup = () => signal.removeEventListener('abort', abort);
    const abort = () => { cleanup(); reject(Object.assign(new Error(), { code: 'component_deadline' })); };
    signal.addEventListener('abort', abort, { once: true });
    Promise.resolve(promise).then(value => { cleanup(); resolve(value); }, error => { cleanup(); reject(error); });
  });
}
async function boundedCancel(target) {
  if (typeof target?.cancel !== 'function') return;
  let timer;
  try { await Promise.race([Promise.resolve().then(() => target.cancel()).catch(() => {}), new Promise(resolve => { timer = setTimeout(resolve, 100); })]); }
  finally { clearTimeout(timer); }
}
const identifier = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value);
function safeUsage(value) {
  const count = value => Number.isInteger(value) && value >= 0 && value <= 1e6;
  if (!only(value, ['promptTokens', 'completionTokens', 'totalTokens', 'inputAudioTokens', 'outputAudioTokens', 'costUsd']) ||
      !['promptTokens', 'completionTokens', 'totalTokens', 'inputAudioTokens', 'outputAudioTokens'].every(key => count(value[key])) ||
      value.inputAudioTokens <= 0 || value.outputAudioTokens <= 0 || !Number.isFinite(value.costUsd) || value.costUsd < 0 || value.costUsd > 1) fail('component_protocol_invalid');
  return { ...value };
}

/** Actual local NDJSON contract; complete + clean EOF, never a claim of audible playback. */
export async function collectComponentTurn(response, { signal, started = performance.now(), now = () => performance.now() } = {}) {
  const parts = []; let reader, pending = '', bytes = 0, audioBytes = 0, turnId = null, caption = '', complete = null,
    cleanEof = false, code = null, firstAudioMs = null, lastAudioMs = null, completeEventMs = null, audioPackets = 0;
  try {
    if (response.status !== 200 || !/^application\/x-ndjson\b/.test(response.headers.get('content-type') ?? '') || !response.body?.getReader) fail('component_request_rejected');
    reader = response.body.getReader(); const decoder = new TextDecoder('utf-8', { fatal: true });
    const line = raw => {
      if (!raw.trim()) return;
      if (raw.length > 65536 || complete) fail('component_protocol_invalid');
      let value; try { value = JSON.parse(raw); } catch { fail('component_protocol_invalid'); }
      const fields = { start: ['type', 'turnId', 'sampleRate', 'sampleRateQualification'], audio: ['type', 'turnId', 'data'],
        caption: ['type', 'turnId', 'text'], complete: ['type', 'turnId', 'text', 'samples', 'usage'], error: ['type', 'turnId', 'code', 'error'] };
      if (!object(value) || !fields[value.type] || !only(value, fields[value.type]) || !identifier(value.turnId)) fail('component_protocol_invalid');
      if (value.type === 'start') {
        if (turnId || value.sampleRate !== 24000 || value.sampleRateQualification !== 'assumed') fail('component_protocol_invalid');
        turnId = value.turnId; return;
      }
      if (!turnId || value.turnId !== turnId) fail('component_protocol_invalid');
      if (value.type === 'error') fail(SAFE_CODES.has(value.code) ? value.code : 'component_request_rejected');
      if (value.type === 'audio') {
        if (typeof value.data !== 'string' || !value.data || value.data.length % 4 || !/^[A-Za-z0-9+/]+={0,2}$/.test(value.data)) fail('component_protocol_invalid');
        const data = Buffer.from(value.data, 'base64');
        if (data.toString('base64') !== value.data || !data.length || data.length % 2 || data.length > 24000 || audioBytes + data.length > NATIVE_AUDIO.audioBytes) fail('component_protocol_invalid');
        parts.push(data); audioBytes += data.length; audioPackets++; firstAudioMs ??= now() - started; lastAudioMs = now() - started; return;
      }
      if (typeof value.text !== 'string' || value.text.length > 4000 || !value.text.startsWith(caption) ||
          /[\u0000-\u0008\u000B\u000C\u000E-\u001F]|Bearer\s|sk-[A-Za-z0-9_-]+/i.test(value.text)) fail('component_protocol_invalid');
      caption = value.text;
      if (value.type === 'complete') {
        if (!caption.trim() || !Number.isInteger(value.samples) || value.samples <= 0 || value.samples !== audioBytes / 2) fail('component_protocol_invalid');
        complete = { text: caption, samples: value.samples, usage: safeUsage(value.usage) }; completeEventMs = now() - started;
      }
    };
    while (true) {
      const next = await abortable(reader.read(), signal);
      if (next.done) { cleanEof = true; break; }
      bytes += next.value.byteLength; if (bytes > NATIVE_AUDIO.streamBytes) fail('component_protocol_invalid');
      pending += decoder.decode(next.value, { stream: true });
      let end;
      while ((end = pending.indexOf('\n')) !== -1) { line(pending.slice(0, end)); pending = pending.slice(end + 1); }
      if (pending.length > 65536) fail('component_protocol_invalid');
    }
    pending += decoder.decode(); if (pending.trim()) fail('component_stream_incomplete');
    if (!complete || !audioBytes || !cleanEof) fail('component_stream_incomplete');
  } catch (error) { code = signal?.aborted ? 'component_deadline' : safeCode(error); }
  finally { await boundedCancel(reader ?? response.body); try { reader?.releaseLock(); } catch {} }
  const pcm = Buffer.concat(parts); let power = 0;
  for (let offset = 0; offset + 1 < pcm.length; offset += 2) power += (pcm.readInt16LE(offset) / 32768) ** 2;
  const rms = pcm.length ? Math.sqrt(power / (pcm.length / 2)) : 0;
  if (!code && !(rms > 0)) code = 'component_protocol_invalid';
  return { status: code ? 'failed' : 'completed', code, strictComplete: !code, turnId, rawPcm: pcm,
    caption, samples: complete?.samples ?? null, usage: complete?.usage ?? null,
    metrics: { firstAudioMs, lastAudioMs, completeEventMs, elapsedMs: now() - started, wireBytes: bytes, audioBytes,
      audioPackets, pcmRms: rms, cleanEof, turnIdSha256: turnId ? sha(turnId) : null, pcmSha256: sha(pcm),
      captionSha256: sha(caption), captionChars: caption.length, rawSseStored: false, rawProviderIdentifiersStored: false } };
}
export function validateNativeDispatch(url, options, sample, wav) {
  if (url !== NATIVE_AUDIO.endpoint || options.method !== 'POST' || options.redirect !== 'error') fail('unowned_upstream_endpoint');
  let body; try { body = JSON.parse(options.body); } catch { fail('production_dispatch_mismatch'); }
  if (!only(body, ['model', 'modalities', 'audio', 'messages', 'stream', 'max_tokens', 'provider']) || body.model !== 'openai/gpt-audio' ||
      body.stream !== true || body.max_tokens !== 512 || JSON.stringify(body.modalities) !== JSON.stringify(['text', 'audio']) ||
      JSON.stringify(body.audio) !== JSON.stringify({ voice: 'coral', format: 'pcm16' }) ||
      JSON.stringify(body.provider) !== JSON.stringify({ only: ['openai'], order: ['openai'], allow_fallbacks: false }) ||
      !Array.isArray(body.messages) || body.messages.length !== 2 || body.messages[0].role !== 'system' ||
      typeof body.messages[0].content !== 'string' || body.messages[1].role !== 'user' ||
      JSON.stringify(body.messages[1].content) !== JSON.stringify([{ type: 'input_audio', input_audio: { data: wav.toString('base64'), format: 'wav' } }])) fail('production_dispatch_mismatch');
  validateFixture(wav, sample);
  if (!body.messages[0].content.includes(sample.id === 'pt' ? 'Converse sempre em português do Brasil' : 'Conversa siempre en español latinoamericano')) fail('production_dispatch_mismatch');
  return { providerRequestSha256: sha(options.body), nativeAudioInputSha256: sha(wav), historyMessages: 0,
    model: body.model, voice: body.audio.voice, outputTokens: body.max_tokens };
}

/** Preserve paid accounting before any local preview or simulated receipt can fail. */
export function appendComponentResult(report, sample, result, dispatch) {
  const { rawPcm, turnId, ...publicResult } = result;
  const record = { id: sample.id, locale: sample.locale, inputSha256: sample.sha256, dispatch,
    ...publicResult, rawPcmFile: null, previewFile: null, simulatedPlayedReceiptAccepted: false, actualPlaybackQualified: false };
  report.samples.push(record);
  report.newCostUsd = report.samples.every(item => Number.isFinite(item.usage?.costUsd))
    ? report.samples.reduce((total, item) => total + item.usage.costUsd, 0) : null;
  report.totalObservedCostIncludingPriorUsd = report.newCostUsd === null ? null : PRIOR.costUsd + report.newCostUsd;
  return record;
}
function previewWav(pcm) {
  if (!Buffer.isBuffer(pcm) || !pcm.length || pcm.length % 2 || pcm.length > NATIVE_AUDIO.audioBytes) fail('component_protocol_invalid');
  const header = Buffer.alloc(44); header.write('RIFF'); header.writeUInt32LE(pcm.length + 36, 4); header.write('WAVEfmt ', 8);
  header.writeUInt32LE(16, 16); header.writeUInt16LE(1, 20); header.writeUInt16LE(1, 22); header.writeUInt32LE(24000, 24);
  header.writeUInt32LE(48000, 28); header.writeUInt16LE(2, 32); header.writeUInt16LE(16, 34); header.write('data', 36); header.writeUInt32LE(pcm.length, 40);
  return Buffer.concat([header, pcm]);
}
async function smallJson(response) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 5000);
  const reader = response.body?.getReader(), parts = []; let bytes = 0;
  try {
    if (!reader) fail('component_request_rejected');
    while (true) { const next = await abortable(reader.read(), controller.signal); if (next.done) break;
      bytes += next.value.length; if (bytes > 8192) fail('component_request_rejected'); parts.push(Buffer.from(next.value)); }
    let value; try { value = JSON.parse(Buffer.concat(parts).toString('utf8')); } catch { fail('component_request_rejected'); }
    if (!response.ok) fail(SAFE_CODES.has(value.code) ? value.code : 'component_request_rejected');
    return value;
  } finally { clearTimeout(timer); await boundedCancel(reader); try { reader?.releaseLock(); } catch {} }
}
async function closeOwnedServer(server) {
  let timer;
  try {
    const closed = new Promise(resolve => server.close(() => resolve(true)));
    server.closeAllConnections();
    return await Promise.race([closed, new Promise(resolve => { timer = setTimeout(() => resolve(false), 1000); })]);
  } finally { clearTimeout(timer); }
}

export async function main(args = process.argv.slice(2)) {
  if (args.length > 1 || args.length && !['--plan', '--execute-component-qa'].includes(args[0])) fail('invalid_arguments');
  if (args[0] !== '--execute-component-qa') { console.log(JSON.stringify(plan())); return; }
  if (NATIVE_AUDIO.model !== 'openai/gpt-audio' || NATIVE_AUDIO.voice !== 'coral' || NATIVE_AUDIO.outputTokens !== 512 || NATIVE_AUDIO.timeoutMs !== 45000) fail('production_dispatch_mismatch');
  const evidence = []; for (const [directory, file] of EVIDENCE_FILES) evidence.push(await boundedFile(path.join(LOCAL, directory, file), 128 * 1024));
  const proof = validateComponentEvidence(evidence), fixtures = [];
  for (const sample of CASES) { const bytes = await boundedFile(path.join(FIXTURES, sample.id + '.wav'), sample.bytes); validateFixture(bytes, sample); fixtures.push(bytes); }
  const sources = await sourceSnapshot();
  if (!plan().firstForecast.allowed) fail('cost_forecast_insufficient');
  await consumeComponentAdmission(DESTINATION, proof, sources);
  const destination = path.join(DESTINATION, new Date().toISOString().replace(/[:.]/g, '-'));
  await mkdir(destination, { recursive: false });
  const report = { ...plan(), status: 'started', proof, sourceHashes: sources, upstreamCalls: 0, dispatches: [], samples: [],
    newCostUsd: 0, totalObservedCostIncludingPriorUsd: PRIOR.costUsd, simulatedPlayedReceipts: 0, serverClosed: false };
  const save = () => writeFile(path.join(destination, 'report.json'), JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
  await save(); let server, activeCase;
  try {
    const key = parseEnv((await boundedFile(path.join(AVATAR, 'openrouter.env'), 64 * 1024)).toString('utf8').replace(/^\uFEFF/, '')).OPENROUTER_API_KEY;
    if (!key?.trim()) fail('local_key_unconfigured');
    const config = readConfig({ NODE_ENV: 'test', OPENROUTER_API_KEY: key, AVATAR_VOICE_PROVIDER: 'openrouter-native' });
    // Two slots permit bounded cleanup of the previous completed request; the
    // client remains sequential and the dispatch guard permits only two calls.
    server = createAvatarServer({ config: { ...config, maxVoiceOperations: 2 }, fetchImpl: async (url, options) => {
      if (!activeCase || report.upstreamCalls >= 2) fail('unowned_upstream_endpoint');
      activeCase.dispatch = validateNativeDispatch(url, options, activeCase.sample, activeCase.wav);
      report.dispatches.push({ id: activeCase.sample.id, ...activeCase.dispatch });
      report.upstreamCalls++; await save(); return fetch(url, options);
    } });
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
    const base = `http://127.0.0.1:${server.address().port}`;
    const configured = await fetch(`${base}/api/avatar/config`, { signal: AbortSignal.timeout(5000) });
    const cookie = configured.headers.getSetCookie()[0]?.split(';')[0], profile = await smallJson(configured);
    if (!cookie || profile.voiceProvider !== 'openrouter-native' || !profile.voiceAvailable || profile.backendAvailable || profile.nativeReadBridgeAvailable || profile.mode !== 'demo') fail('component_protocol_invalid');
    report.config = { voiceProvider: profile.voiceProvider, voiceAvailable: true, backendAvailable: false,
      nativeReadBridgeAvailable: false, backgroundAsrAvailable: profile.backgroundAsrAvailable, observerExercised: false };
    const post = (route, body, signal = AbortSignal.timeout(5000)) => fetch(`${base}/api/avatar/${route}`, {
      method: 'POST', headers: { Origin: base, Cookie: cookie, 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });
    for (let index = 0; index < CASES.length; index++) {
      const sample = CASES[index];
      if (index) {
        if (JSON.stringify(await sourceSnapshot()) !== JSON.stringify(sources)) fail('source_changed');
        const first = report.samples[0];
        report.secondForecast = forecast(report.totalObservedCostIncludingPriorUsd, sample,
          { inputAudioTokens: first?.usage?.inputAudioTokens, seconds: CASES[0].seconds });
        if (!first?.strictComplete || !report.secondForecast.allowed) { report.secondSkipped = 'incomplete_or_cost_forecast'; break; }
        const reset = await smallJson(await post('native-reset', {})); if (reset.accepted !== true) fail('component_protocol_invalid');
      }
      activeCase = { sample, wav: fixtures[index], dispatch: null };
      const started = performance.now(), controller = new AbortController(), timer = setTimeout(() => controller.abort(), 45000);
      let result;
      try {
        const response = await abortable(post('native-turn', { audio: activeCase.wav.toString('base64'), format: 'wav', avatar: 'moss', locale: sample.id }, controller.signal), controller.signal);
        result = await collectComponentTurn(response, { signal: controller.signal, started });
      } catch (error) { result = { status: 'failed', code: controller.signal.aborted ? 'component_deadline' : safeCode(error), strictComplete: false,
        rawPcm: Buffer.alloc(0), turnId: null, usage: null, caption: '', samples: null }; }
      finally { clearTimeout(timer); controller.abort(); }
      const { rawPcm, turnId } = result;
      const record = appendComponentResult(report, sample, result, activeCase.dispatch);
      await save();
      if (rawPcm.length) {
        const stem = sample.id + (result.strictComplete ? '.component' : '.failed-diagnostic');
        record.rawPcmFile = stem + '.pcm'; await writeFile(path.join(destination, record.rawPcmFile), rawPcm, { flag: 'wx', mode: 0o600 });
        record.previewFile = stem + '.wav'; await writeFile(path.join(destination, record.previewFile), previewWav(rawPcm), { flag: 'wx', mode: 0o600 });
      }
      if (result.strictComplete) {
        const played = await smallJson(await post('native-played', { turnId, locale: sample.id, playedSamples: result.samples, complete: true }));
        if (played.accepted !== true) fail('component_played_receipt_rejected');
        record.simulatedPlayedReceiptAccepted = true; report.simulatedPlayedReceipts++;
      }
      await save();
      if (!result.strictComplete || report.totalObservedCostIncludingPriorUsd === null || report.totalObservedCostIncludingPriorUsd > .10) break;
    }
    report.sourcesUnchanged = JSON.stringify(await sourceSnapshot()) === JSON.stringify(sources);
    if (!report.sourcesUnchanged) fail('source_changed');
    report.status = report.samples.length && report.samples.every(item => item.strictComplete && item.simulatedPlayedReceiptAccepted) &&
      report.totalObservedCostIncludingPriorUsd !== null && report.totalObservedCostIncludingPriorUsd <= .10
      ? report.samples.length === 2 ? 'completed' : 'completed_es_only' : 'failed';
  } catch (error) { report.status = 'failed'; report.code = safeCode(error); }
  finally { if (server) report.serverClosed = await closeOwnedServer(server); }
  if (server && !report.serverClosed) { report.status = 'failed'; report.code = 'local_preparation_failed'; }
  await save();
  console.log(JSON.stringify({ status: report.status, namespace: NAMESPACE, upstreamCalls: report.upstreamCalls,
    totalObservedCostIncludingPriorUsd: report.totalObservedCostIncludingPriorUsd, outputDirectory: destination,
    simulatedPlayedReceipts: report.simulatedPlayedReceipts, serverClosed: report.serverClosed,
    samples: report.samples.map(({ id, status, code, strictComplete, previewFile }) => ({ id, status, code, strictComplete, previewFile })),
    browserPlaybackQualified: false, liveWebsocketQualified: false, pcmSampleRateQualification: 'assumed', observerExercised: false }));
  if (!['completed', 'completed_es_only'].includes(report.status)) process.exitCode = 1;
}
if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url)
  main().catch(error => { console.log(JSON.stringify({ status: 'failed', code: error.code === 'EEXIST' ? 'component_admission_already_spent' :
    ['invalid_arguments', 'prior_marker_hash_mismatch', 'prior_pt_hash_mismatch', 'prior_provenance_invalid', 'fixture_hash_mismatch',
      'fixture_profile_mismatch', 'cost_forecast_insufficient'].includes(error.code) ? error.code : safeCode(error) })); process.exitCode = 1; });
