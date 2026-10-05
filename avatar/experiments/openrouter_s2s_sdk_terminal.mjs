/** Inert, separately admitted correction for the documented audio expiry terminal. */
import { createHash } from 'node:crypto';
import { lstat, readFile, mkdir, writeFile } from 'node:fs/promises';
import { parseEnv } from 'node:util';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { MODEL, VOICE, CASES, RATE, LIMITS, PRICES, REFERENCES, requestBody, validateFixture,
  pcmToWav, sanitizeError, forecastSecond } from './openrouter_s2s_audition.mjs';

const AVATAR = fileURLToPath(new URL('../', import.meta.url));
const ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions';
export const NAMESPACE = 'openrouter_s2s_sdk_expiry_terminal_v1';
export const PRIOR = Object.freeze({
  namespace: 'openrouter_native_s2s_pcm16_v1', costUsd: .006694,
  report: '2026-10-01T15-49-23-612Z/report.json',
  reportSha256: '8f774dd6ecd9439cf8456f26ac307ac4e949445bdb3a9584cfed15724303bcc8',
  inputAudioTokens: 41, promptTokens: 105, completionTokens: 101, totalTokens: 206, outputAudioTokens: 78,
});
const ORIGINAL = path.join(AVATAR, '.local', 'openrouter-s2s');
const DIRECTORY = path.join(AVATAR, '.local', 'openrouter-s2s-sdk-terminal');
const FIXTURES = path.join(AVATAR, '.local', 'qwen-native', '20261001-084853-1790862533806878800');
const sha = value => createHash('sha256').update(value).digest('hex');
const fail = code => { throw Object.assign(new Error(code), { code }); };
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const boundedString = value => typeof value === 'string' && value.length > 0 && value.length <= 256;
const finite = value => Number.isFinite(value) && value >= 0;
const safeReason = value => value === undefined ? 'absent' : value === null ? 'null' :
  ['stop', 'length', 'content_filter', 'tool_calls', 'function_call', 'error'].includes(value) ? value :
    typeof value === 'string' ? 'unknown_string' : 'invalid_type';
const increment = (target, key) => { target[key] = (target[key] ?? 0) + 1; };
const typeName = value => value === undefined ? 'absent' : value === null ? 'null' : Array.isArray(value) ? 'array' : typeof value;
const own = (value, key) => Object.hasOwn(value, key);
const payloadShape = (value, key) => !own(value, key) ? 'absent' : value[key] === null ? 'null' :
  value[key] === '' ? 'empty_string' : typeof value[key] === 'string' ? 'nonempty_string' : 'invalid_type';

/** Application compatibility inference; this is deliberately not the SDK's exact terminal. */
export function normalizedExpiryTerminal(delta, prior) {
  if (!object(delta) || !object(delta.audio) ||
      Object.keys(delta).some(key => !['audio', 'role', 'content'].includes(key)) ||
      Object.keys(delta.audio).some(key => !['id', 'expires_at', 'data', 'transcript'].includes(key))) return false;
  const audio = delta.audio;
  return Number.isFinite(audio.expires_at) && audio.expires_at > 0 &&
    (!own(delta, 'role') || delta.role === 'assistant') &&
    (!own(delta, 'content') || delta.content === null || delta.content === '') &&
    (!own(audio, 'data') || audio.data === null || audio.data === '') &&
    (!own(audio, 'transcript') || audio.transcript === null || audio.transcript === '') &&
    boundedString(prior?.audioId) && prior.audioBytes > 0 && prior.captionNonempty === true &&
    (!own(audio, 'id') || audio.id === prior.audioId);
}

/** A non-spoken application metadata tail; never a new expiry or payload. */
export function metadataOnlyTail(delta, observedAudioId) {
  if (!object(delta) || Object.keys(delta).some(key => !['audio', 'role', 'content'].includes(key)) ||
      own(delta, 'role') && delta.role !== 'assistant' ||
      own(delta, 'content') && delta.content !== null && delta.content !== '') return false;
  if (!own(delta, 'audio')) return true;
  return object(delta.audio) && Object.keys(delta.audio).length === 1 && own(delta.audio, 'id') &&
    boundedString(observedAudioId) && delta.audio.id === observedAudioId;
}

export function initialForecast() {
  const audioTokens = Math.ceil(PRIOR.inputAudioTokens * 1.5) + 64;
  const textTokens = Math.ceil(Math.max(200, PRIOR.promptTokens - PRIOR.inputAudioTokens) * 1.5) + 128;
  const inputForecastUsd = (audioTokens * PRICES.audioInputPerMillion + textTokens * PRICES.textInputPerMillion) / 1e6;
  const outputReservationUsd = LIMITS.outputTokens * PRICES.audioOutputPerMillion / 1e6;
  return { allowed: PRIOR.costUsd + inputForecastUsd + outputReservationUsd <= LIMITS.estimatedTotalUsdCeiling,
    knownPriorCostUsd: PRIOR.costUsd, inputForecastUsd, outputReservationUsd, audioTokens, textTokens,
    forecastIncludingPriorUsd: PRIOR.costUsd + inputForecastUsd + outputReservationUsd, hardSpendGuarantee: false };
}

export function plan() {
  return { status: 'correction_prepared_not_dispatched', namespace: NAMESPACE, model: MODEL, voice: VOICE,
    provider: 'openai', ...LIMITS, priorFailure: PRIOR, firstRequestForecast: initialForecast(),
    references: { ...REFERENCES, sdkTerminal: 'https://github.com/openai/openai-node/pull/1991',
      sdkSource: 'https://raw.githubusercontent.com/openai/openai-node/main/src/lib/ChatCompletionStream.ts' },
    retries: 0, fallback: false, bodyChanged: false, providerHardSpendCap: false,
    oldAdmissionPreserved: true, dedicatedTtsCalls: 0, asrCalls: 0, gpuCalls: 0, bankingAccess: false,
    physicalMicrophoneUsed: false, liveWebsocketQualified: false, humanVoiceQualityVerified: false,
    pcmPackagingRateHz: RATE, pcmPackagingRateQualified: false, failedStreamAudioIsAcceptance: false };
}

export function validatePriorEvidence(reportBytes, admissionBytes) {
  if (!Buffer.isBuffer(reportBytes) || reportBytes.length > 16384 || sha(reportBytes) !== PRIOR.reportSha256)
    fail('prior_failure_hash_mismatch');
  if (!Buffer.isBuffer(admissionBytes) || admissionBytes.length > 8192) fail('prior_admission_invalid');
  let report, admission;
  try { report = JSON.parse(reportBytes); admission = JSON.parse(admissionBytes); } catch { fail('prior_evidence_invalid_json'); }
  const sample = report.samples?.[0], usage = sample?.diagnostic?.usage;
  if (report.namespace !== PRIOR.namespace || report.model !== MODEL || report.voice !== VOICE || report.status !== 'failed' ||
      report.upstreamCalls !== 1 || report.samples?.length !== 1 || sample.id !== 'es' || sample.status !== 'failed' ||
      sample.code !== 'incomplete_audio_stream' || sample.diagnostic.finishReason !== null ||
      !usage || Object.keys(PRIOR).filter(key => key.endsWith('Tokens') || key === 'costUsd').some(key => usage[key] !== PRIOR[key]) ||
      admission.namespace !== PRIOR.namespace || admission.status !== 'spent_before_dispatch' ||
      admission.model !== MODEL || admission.voice !== VOICE ||
      !CASES.every(sample => admission.fixtures?.some(value => value.id === sample.id && value.sha256 === sample.sha256)))
    fail('prior_failure_provenance_mismatch');
  return { reportSha256: sha(reportBytes), oldAdmissionSha256: sha(admissionBytes), knownPriorCostUsd: PRIOR.costUsd };
}

export async function consumeCorrectionAdmission(directory, proof) {
  if (proof?.reportSha256 !== PRIOR.reportSha256 || !/^[a-f0-9]{64}$/.test(proof.oldAdmissionSha256 ?? '') ||
      proof.knownPriorCostUsd !== PRIOR.costUsd) fail('prior_failure_proof_missing');
  await mkdir(directory, { recursive: true });
  const record = { status: 'spent_before_dispatch', namespace: NAMESPACE, priorFailure: proof,
    model: MODEL, voice: VOICE, calls: LIMITS.calls, outputTokens: LIMITS.outputTokens, forecast: initialForecast() };
  await writeFile(path.join(directory, 'sdk-terminal-correction-admitted.json'), JSON.stringify(record, null, 2) + '\n',
    { flag: 'wx', mode: 0o600 });
  return record;
}

function safeUsage(value) {
  if (!object(value)) return null;
  const count = value => Number.isInteger(value) && value >= 0 && value <= 1e6 ? value : null;
  return { promptTokens: count(value.prompt_tokens), completionTokens: count(value.completion_tokens),
    totalTokens: count(value.total_tokens), inputAudioTokens: count(value.prompt_tokens_details?.audio_tokens),
    outputAudioTokens: count(value.completion_tokens_details?.audio_tokens),
    costUsd: finite(value.cost) && value.cost <= 1 ? value.cost : null };
}

/** Records bounded schema summaries and audio, never raw event envelopes or identifier values. */
export class NativeStreamEvidence {
  constructor({ now = () => performance.now(), started = now(), terminalMode = 'sdk' } = {}) {
    if (!['sdk', 'application-normalized', 'application-metadata-tail'].includes(terminalMode)) fail('invalid_terminal_mode');
    this.terminalMode = terminalMode; this.terminalSource = null;
    this.now = now; this.started = started; this.parts = []; this.caption = ''; this.audioId = null;
    this.streamId = null; this.model = null; this.terminal = false; this.wireStop = false; this.invalid = null;
    this.usage = null; this.bytes = 0; this.firstAudioMs = null; this.lastAudioMs = null;
    this.summary = { events: 0, choices: 0, doneCount: 0, doneSeen: false, cleanEof: false,
      finishReasons: {}, nativeFinishReasons: {}, choiceIndices: {}, audioDeltaCount: 0,
      audioIdStringCount: 0, audioExpiresNumericCount: 0, expiryOnlyDeltaCount: 0,
      audioIdTypes: {}, audioExpiryTypes: {}, messageAudioIdTypes: {}, messageAudioExpiryTypes: {},
      messageAudioCount: 0, unknownDeltaFieldCount: 0, meaningfulAfterTerminalCount: 0,
      accountingOnlyChoiceCount: 0, usageEventCount: 0, topErrorCount: 0, choiceErrorCount: 0,
      expiryEventShapes: [], expiryEventShapesTruncated: false,
      choiceEventShapes: [], choiceEventShapesTruncated: false, metadataOnlyTailCount: 0,
      terminalEventIndex: null, identifierValuesStored: false, rawEventsStored: false };
  }
  reject(code) { this.invalid ??= code; }
  recordChoiceShape(choice, value, previouslyTerminated) {
    if (this.summary.choiceEventShapes.length >= 256) {
      this.summary.choiceEventShapesTruncated = true;
      if (this.terminalMode === 'application-metadata-tail') this.reject('choice_shape_bound');
      return;
    }
    const delta = object(choice.delta) ? choice.delta : {}, audio = object(delta.audio) ? delta.audio : {};
    let decoded = null;
    if (typeof audio.data === 'string' && /^[A-Za-z0-9+/]*={0,2}$/.test(audio.data) && audio.data.length % 4 === 0) {
      const bytes = Buffer.from(audio.data, 'base64'); if (bytes.toString('base64') === audio.data) decoded = bytes;
    }
    const accountingOnly = object(value.usage) && object(choice.delta) &&
      Object.keys(delta).every(key => ['role', 'content'].includes(key)) &&
      (delta.role === undefined || delta.role === 'assistant') && (delta.content === undefined || delta.content === '');
    this.summary.choiceEventShapes.push({
      eventIndex: this.summary.events, choiceOrdinal: this.summary.choices, choiceIndex: choice.index === 0 ? 0 : null,
      afterCompletion: previouslyTerminated, doneSeenBeforeChoice: this.summary.doneSeen,
      finishReason: safeReason(choice.finish_reason), nativeFinishReason: safeReason(choice.native_finish_reason),
      usagePresent: object(value.usage), accountingOnly, deltaType: typeName(choice.delta),
      deltaKnownKeys: ['audio', 'role', 'content', 'refusal', 'function_call', 'tool_calls'].filter(key => own(delta, key)),
      unknownDeltaKeyCount: Object.keys(delta).filter(key => !['audio', 'role', 'content', 'refusal', 'function_call', 'tool_calls'].includes(key)).length,
      audioType: typeName(delta.audio), audioKnownKeys: ['id', 'expires_at', 'data', 'transcript'].filter(key => own(audio, key)),
      unknownAudioKeyCount: Object.keys(audio).filter(key => !['id', 'expires_at', 'data', 'transcript'].includes(key)).length,
      idType: typeName(audio.id), idSha256: boundedString(audio.id) ? sha(audio.id) : null,
      priorIdObserved: this.audioId !== null, idMatchesPrior: own(audio, 'id') && this.audioId !== null && audio.id === this.audioId,
      expiryType: typeName(audio.expires_at), expiryPositiveFinite: Number.isFinite(audio.expires_at) && audio.expires_at > 0,
      dataShape: payloadShape(audio, 'data'), decodedAudioBytes: decoded?.length ?? null,
      audioPayloadPresent: typeof audio.data === 'string' && audio.data.length > 0,
      decodedAudioSha256: decoded ? sha(decoded) : null, decodedByteOffsetBefore: this.bytes,
      decodedByteOffsetAfter: this.bytes + (decoded?.length ?? 0),
      transcriptShape: payloadShape(audio, 'transcript'), transcriptChars: typeof audio.transcript === 'string' ? audio.transcript.length : null,
      transcriptPayloadPresent: typeof audio.transcript === 'string' && audio.transcript.length > 0,
      transcriptSha256: typeof audio.transcript === 'string' ? sha(audio.transcript) : null,
      roleShape: !own(delta, 'role') ? 'absent' : delta.role === 'assistant' ? 'assistant' : delta.role === null ? 'null' : 'other',
      contentShape: payloadShape(delta, 'content'),
      contentPayloadPresent: typeof delta.content === 'string' && delta.content.length > 0,
      messagePresent: choice.message !== undefined && choice.message !== null, messageType: typeName(choice.message),
      messageAudioPresent: object(choice.message) && own(choice.message, 'audio'),
      refusalFieldPresent: own(delta, 'refusal'), toolFieldPresent: own(delta, 'function_call') || own(delta, 'tool_calls'),
      applicationMetadataTail: this.terminal && metadataOnlyTail(delta, this.audioId),
    });
  }
  event(content) {
    if (content === '[DONE]') {
      this.summary.doneCount++; this.summary.doneSeen = true;
      if (this.summary.doneCount !== 1) this.reject('duplicate_done');
      return;
    }
    if (this.summary.doneSeen) this.reject('data_after_done');
    let value; try { value = JSON.parse(content); } catch { this.reject('invalid_stream_json'); return; }
    if (!object(value)) { this.reject('invalid_stream_envelope'); return; }
    this.summary.events++;
    for (const key of ['id', 'model']) {
      if (value[key] === undefined) continue;
      const property = key === 'id' ? 'streamId' : 'model';
      if (!boundedString(value[key])) this.reject('invalid_stream_identity');
      else if (this[property] !== null && this[property] !== value[key]) this.reject('changed_stream_identity');
      else this[property] = value[key];
    }
    if (value.error) {
      this.summary.topErrorCount++; this.summary.error = sanitizeError(value, 200); this.reject('provider_stream_error');
    }
    if (value.usage !== undefined) { this.summary.usageEventCount++; this.usage = safeUsage(value.usage); }
    if (!Array.isArray(value.choices)) { this.reject('invalid_choices'); return; }
    if (value.choices.length > 1) this.reject('multiple_choices');
    for (const choice of value.choices) {
      if (!object(choice)) { this.reject('invalid_choice'); continue; }
      this.summary.choices++;
      const previouslyTerminated = this.terminal || this.wireStop;
      this.recordChoiceShape(choice, value, previouslyTerminated);
      increment(this.summary.choiceIndices, choice.index === 0 ? 'zero' : choice.index === undefined ? 'missing' : 'nonzero_or_invalid');
      if (choice.index !== 0) this.reject('unexpected_choice_index');
      for (const [field, target] of [['finish_reason', this.summary.finishReasons], ['native_finish_reason', this.summary.nativeFinishReasons]]) {
        const reason = safeReason(choice[field]); increment(target, reason);
        if (!['absent', 'null', 'stop'].includes(reason)) this.reject('non_stop_finish');
        if (field === 'finish_reason' && reason === 'stop') this.wireStop = true;
        if (reason === 'unknown_string' && typeof choice[field] === 'string') this.summary[field + 'UnknownSha256'] = sha(choice[field]);
      }
      if (choice.error) { this.summary.choiceErrorCount++; this.reject('provider_choice_error'); }
      // This is a delta-only streaming contract. A full message must never bypass
      // terminal continuation checks through an accounting-only delta.
      if (choice.message !== undefined && choice.message !== null) this.reject('unexpected_message_envelope');
      if (object(choice.message?.audio)) {
        this.summary.messageAudioCount++;
        increment(this.summary.messageAudioIdTypes, typeName(choice.message.audio.id));
        increment(this.summary.messageAudioExpiryTypes, typeName(choice.message.audio.expires_at));
      }
      const delta = choice.delta;
      if (delta === undefined || delta === null) continue;
      if (!object(delta)) { this.reject('invalid_delta'); continue; }
      // OpenRouter's final accounting choice repeats harmless assistant/empty-content fields.
      const accountingOnly = object(value.usage) && Object.keys(delta).every(key => ['role', 'content'].includes(key)) &&
        (delta.role === undefined || delta.role === 'assistant') && (delta.content === undefined || delta.content === '');
      if (accountingOnly) { this.summary.accountingOnlyChoiceCount++; continue; }
      const expiryOnly = Object.keys(delta).length === 1 && object(delta.audio) && Object.keys(delta.audio).length === 1 &&
        Number.isFinite(delta.audio.expires_at) && delta.audio.expires_at > 0;
      const normalizedExpiry = this.terminalMode !== 'sdk' && normalizedExpiryTerminal(delta,
        { audioId: this.audioId, audioBytes: this.bytes, captionNonempty: this.caption.trim().length > 0 });
      const meaningful = Object.entries(delta).some(([key, value]) => value !== null && value !== undefined &&
        !(key === 'content' && value === '') && !(key === 'audio' && object(value) && Object.keys(value).length === 0));
      const metadataTail = this.terminalMode === 'application-metadata-tail' && this.terminal && metadataOnlyTail(delta, this.audioId);
      if (metadataTail) this.summary.metadataOnlyTailCount++;
      if (previouslyTerminated && meaningful && !metadataTail) { this.summary.meaningfulAfterTerminalCount++; this.reject('content_after_audio_terminal'); }
      if (this.terminalMode === 'application-metadata-tail' && this.terminal && !metadataTail && !accountingOnly)
        this.reject('invalid_post_terminal_tail');
      const unknown = Object.keys(delta).filter(key => !['audio', 'role', 'content', 'refusal', 'function_call', 'tool_calls'].includes(key));
      this.summary.unknownDeltaFieldCount += unknown.length;
      if (unknown.length) this.reject('unknown_delta_field');
      if (delta.refusal !== undefined && delta.refusal !== null && delta.refusal !== '' ||
          delta.function_call !== undefined && delta.function_call !== null || delta.tool_calls !== undefined && delta.tool_calls !== null)
        this.reject('refusal_or_tool_delta');
      if (delta.role !== undefined && delta.role !== null && delta.role !== 'assistant') this.reject('invalid_role');
      if (delta.content !== undefined && delta.content !== null && typeof delta.content !== 'string') this.reject('invalid_content');
      const audio = delta.audio;
      if (audio === undefined || audio === null) continue;
      if (!object(audio)) { this.reject('invalid_audio_delta'); continue; }
      increment(this.summary.audioIdTypes, typeName(audio.id));
      increment(this.summary.audioExpiryTypes, typeName(audio.expires_at));
      if (own(audio, 'expires_at')) {
        if (this.summary.expiryEventShapes.length < 64) this.summary.expiryEventShapes.push({
          eventIndex: this.summary.events, choiceIndex: choice.index === 0 ? 0 : null,
          deltaKnownKeys: ['audio', 'role', 'content', 'refusal', 'function_call', 'tool_calls'].filter(key => own(delta, key)),
          audioKnownKeys: ['id', 'expires_at', 'data', 'transcript'].filter(key => own(audio, key)),
          unknownDeltaKeyCount: Object.keys(delta).filter(key => !['audio', 'role', 'content', 'refusal', 'function_call', 'tool_calls'].includes(key)).length,
          unknownAudioKeyCount: Object.keys(audio).filter(key => !['id', 'expires_at', 'data', 'transcript'].includes(key)).length,
          expiryType: typeName(audio.expires_at), expiryPositiveFinite: Number.isFinite(audio.expires_at) && audio.expires_at > 0,
          idType: typeName(audio.id), priorIdObserved: this.audioId !== null,
          repeatedIdMatchesPrior: own(audio, 'id') && this.audioId !== null && audio.id === this.audioId,
          dataShape: payloadShape(audio, 'data'), transcriptShape: payloadShape(audio, 'transcript'),
          roleShape: !own(delta, 'role') ? 'absent' : delta.role === 'assistant' ? 'assistant' : typeName(delta.role) === 'null' ? 'null' : 'other',
          contentShape: payloadShape(delta, 'content'), sdkExactTerminal: expiryOnly,
          applicationNormalizedTerminal: normalizedExpiry,
        }); else this.summary.expiryEventShapesTruncated = true;
      }
      if (Object.keys(audio).some(key => !['id', 'data', 'transcript', 'expires_at'].includes(key))) this.reject('unknown_audio_field');
      if (audio.id !== undefined && audio.id !== null) {
        if (!boundedString(audio.id)) this.reject('invalid_audio_identity');
        else { this.summary.audioIdStringCount++;
          if (this.audioId !== null && audio.id !== this.audioId) this.reject('changed_audio_identity');
          else this.audioId = audio.id;
        }
      }
      if (audio.expires_at !== undefined && audio.expires_at !== null) {
        if (!Number.isFinite(audio.expires_at) || audio.expires_at <= 0) this.reject('invalid_audio_expiry');
        else { this.summary.audioExpiresNumericCount++; this.expiry = audio.expires_at; }
      }
      if (audio.transcript !== undefined && audio.transcript !== null) {
        if (typeof audio.transcript !== 'string') this.reject('invalid_audio_caption');
        else { this.caption += audio.transcript; if (this.caption.length > 4000) fail('caption_bound'); }
      }
      if (audio.data !== undefined && audio.data !== null) {
        if (typeof audio.data !== 'string' || !/^[A-Za-z0-9+/]*={0,2}$/.test(audio.data) || audio.data.length % 4) {
          this.reject('invalid_audio_base64'); continue;
        }
        const bytes = Buffer.from(audio.data, 'base64');
        if (bytes.toString('base64') !== audio.data) { this.reject('invalid_audio_base64'); continue; }
        if (this.bytes + bytes.length > LIMITS.audioBytes) fail('audio_byte_bound');
        if (bytes.length) { this.parts.push(bytes); this.bytes += bytes.length; this.summary.audioDeltaCount++;
          this.firstAudioMs ??= this.now() - this.started; this.lastAudioMs = this.now() - this.started; }
      }
      if (expiryOnly) this.summary.expiryOnlyDeltaCount++;
      if (expiryOnly || normalizedExpiry) { this.terminal = true;
        this.terminalSource = this.terminalMode === 'application-metadata-tail' ? 'application_normalized_expiry_terminal_with_metadata_tail' :
          expiryOnly ? 'sdk_expiry_only_terminal' : 'application_normalized_expiry_terminal';
        this.summary.terminalEventIndex = this.summary.events; }
    }
  }
  result({ cleanEof = false, failureCode = null } = {}) {
    this.summary.cleanEof = cleanEof;
    const rawPcm = Buffer.concat(this.parts);
    if (failureCode) this.reject(failureCode);
    if (!cleanEof || !this.summary.doneSeen || this.summary.doneCount !== 1) this.reject('incomplete_stream_transport');
    const completeAudio = this.audioId !== null && rawPcm.length > 0 && this.caption.trim().length > 0 && finite(this.expiry) && this.expiry > 0;
    if (!this.wireStop && !(this.terminal && completeAudio)) this.reject('incomplete_audio_stream');
    if (!rawPcm.length || rawPcm.length % 2) this.reject('invalid_native_pcm');
    if (!finite(this.usage?.costUsd)) this.reject('missing_usage_cost');
    if (/https?:\/\/|Bearer\s|sk-[A-Za-z0-9_-]+/i.test(this.caption) || /[\u0000-\u0008\u000B\u000C\u000E-\u001F]/.test(this.caption))
      this.reject('unsafe_caption');
    let wav = null; try { if (rawPcm.length) wav = pcmToWav(rawPcm); } catch { this.reject('invalid_native_pcm'); }
    return { status: this.invalid ? 'failed' : 'completed', code: this.invalid,
      strictCompletionPassed: !this.invalid, completionSource: this.wireStop ? 'explicit_wire_stop' : this.terminal ? this.terminalSource : null,
      rawPcm, wav, usage: this.usage, ...(this.invalid ? {} : { caption: this.caption }),
      diagnostic: { ...this.summary, streamIdSha256: this.streamId ? sha(this.streamId) : null,
        modelSha256: this.model ? sha(this.model) : null, audioIdSha256: this.audioId ? sha(this.audioId) : null,
        captionChars: this.caption.length, captionSha256: sha(this.caption), audioBytes: rawPcm.length,
        audioSha256: sha(rawPcm), audioByteParity: rawPcm.length % 2, firstAudioMs: this.firstAudioMs,
        lastAudioMs: this.lastAudioMs, elapsedMs: this.now() - this.started,
        pcmSampleRateAssumed: RATE, pcmPackagingRateQualified: false, failedAudioIsAcceptance: false } };
  }
}

function abortable(promise, signal) {
  if (signal.aborted) return Promise.reject(Object.assign(new Error('request_deadline'), { code: 'request_deadline' }));
  return new Promise((resolve, reject) => {
    const cleanup = () => signal.removeEventListener('abort', aborted);
    const aborted = () => { cleanup(); reject(Object.assign(new Error('request_deadline'), { code: 'request_deadline' })); };
    signal.addEventListener('abort', aborted, { once: true });
    Promise.resolve(promise).then(value => { cleanup(); resolve(value); }, error => { cleanup(); reject(error); });
  });
}
async function cancel(target) {
  if (typeof target?.cancel !== 'function') return;
  let timer;
  try { await Promise.race([Promise.resolve().then(() => target.cancel()).catch(() => {}),
    new Promise(resolve => { timer = setTimeout(resolve, LIMITS.cleanupTimeoutMs); })]); }
  finally { clearTimeout(timer); }
}

export async function collectCorrected(body, { signal, now, started, terminalMode = 'sdk' } = {}) {
  const evidence = new NativeStreamEvidence({ now, started, terminalMode });
  if (!body?.getReader || !signal) return evidence.result({ failureCode: 'missing_stream' });
  const reader = body.getReader(), decoder = new TextDecoder();
  let pending = '', bytes = 0, cleanEof = false, failureCode = null;
  const parse = raw => {
    const content = raw.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
    if (content) evidence.event(content);
  };
  try {
    while (true) {
      const result = await abortable(reader.read(), signal);
      if (result.done) { cleanEof = true; break; }
      bytes += result.value.byteLength; if (bytes > LIMITS.streamBytes) fail('stream_byte_bound');
      pending += decoder.decode(result.value, { stream: true });
      let split;
      while ((split = /\r?\n\r?\n/.exec(pending))) { parse(pending.slice(0, split.index)); pending = pending.slice(split.index + split[0].length); }
      if (pending.length > 512 * 1024) fail('stream_event_bound');
    }
    pending += decoder.decode(); if (pending.trim()) parse(pending);
  } catch (error) { failureCode = signal.aborted ? 'request_deadline' : ['stream_byte_bound', 'stream_event_bound', 'audio_byte_bound', 'caption_bound'].includes(error.code) ? error.code : 'stream_read_failed'; }
  finally { await cancel(reader); try { reader.releaseLock(); } catch {} }
  const result = evidence.result({ cleanEof, failureCode }); result.diagnostic.streamBytes = bytes;
  return result;
}

export async function correctedAudition(fetcher, key, sample, wav, { timeoutMs = LIMITS.timeoutMs, terminalMode = 'sdk' } = {}) {
  if (!['sdk', 'application-normalized', 'application-metadata-tail'].includes(terminalMode)) fail('invalid_terminal_mode');
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > LIMITS.timeoutMs) fail('invalid_deadline');
  const body = requestBody(sample, wav), controller = new AbortController(), started = performance.now();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await abortable(fetcher(ENDPOINT, { method: 'POST', redirect: 'error', signal: controller.signal,
      headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' }, body: JSON.stringify(body) }), controller.signal);
    const contentType = response.headers.get('content-type') ?? '';
    if (!response.ok) {
      const reader = response.body?.getReader(); let value = null, bytes = 0, truncated = false; const parts = [];
      if (reader) try {
        while (true) {
          const next = await abortable(reader.read(), controller.signal); if (next.done) break;
          const remaining = LIMITS.diagnosticBytes - bytes;
          parts.push(Buffer.from(next.value).subarray(0, remaining)); bytes += Math.min(remaining, next.value.byteLength);
          if (bytes >= LIMITS.diagnosticBytes) { truncated = true; break; }
        }
        try { value = JSON.parse(Buffer.concat(parts).toString('utf8')); } catch {}
      } finally { await cancel(reader); try { reader.releaseLock(); } catch {} }
      return { status: 'failed', code: 'provider_request_rejected', strictCompletionPassed: false, rawPcm: Buffer.alloc(0), wav: null,
        usage: null, diagnostic: sanitizeError(value, response.status, truncated) };
    }
    if (!/^text\/event-stream\b/i.test(contentType)) {
      await cancel(response.body); fail('unexpected_content_type');
    }
    const result = await collectCorrected(response.body, { signal: controller.signal, started, terminalMode });
    result.diagnostic.httpStatus = response.status;
    result.diagnostic.contentTypeEventStream = true;
    const generationId = response.headers.get('x-generation-id');
    result.diagnostic.generationIdSha256 = boundedString(generationId) ? sha(generationId) : null;
    return result;
  } catch (error) {
    return { status: 'failed', code: controller.signal.aborted ? 'request_deadline' : error.code === 'unexpected_content_type' ? error.code : 'transport_failed',
      strictCompletionPassed: false, rawPcm: Buffer.alloc(0), wav: null, usage: null,
      diagnostic: { httpStatus: response?.status ?? null, rawEventsStored: false } };
  } finally { clearTimeout(timer); controller.abort(); }
}

export async function saveDiagnosticAudio(destination, sample, result) {
  if (!CASES.includes(sample)) fail('invalid_sample');
  const stem = sample.id + (result.status === 'failed' ? '.failed-diagnostic' : '.diagnostic');
  const files = { rawPcmFile: null, previewFile: null, failedAudioIsAcceptance: false, pcmPackagingRateQualified: false };
  if (result.rawPcm?.length) {
    files.rawPcmFile = stem + '.pcm';
    await writeFile(path.join(destination, files.rawPcmFile), result.rawPcm, { flag: 'wx', mode: 0o600 });
  }
  if (result.wav) {
    files.previewFile = stem + '.wav';
    await writeFile(path.join(destination, files.previewFile), result.wav, { flag: 'wx', mode: 0o600 });
  }
  return files;
}

export async function main(args = process.argv.slice(2)) {
  if (args.length > 1 || args.length && !['--plan', '--execute-sdk-terminal-fix'].includes(args[0])) fail('invalid_arguments');
  if (args[0] !== '--execute-sdk-terminal-fix') { console.log(JSON.stringify(plan())); return; }
  const proof = validatePriorEvidence(await readFile(path.join(ORIGINAL, PRIOR.report)),
    await readFile(path.join(ORIGINAL, 'native-pcm16-admitted.json')));
  const inputs = new Map();
  for (const sample of CASES) {
    const file = path.join(FIXTURES, sample.id + '.wav'), info = await lstat(file);
    if (!info.isFile() || info.isSymbolicLink() || info.size !== sample.bytes) fail('fixture_missing');
    const wav = await readFile(file); validateFixture(wav, sample); inputs.set(sample.id, wav);
  }
  if (!initialForecast().allowed) fail('first_cost_forecast_insufficient');
  await consumeCorrectionAdmission(DIRECTORY, proof);
  const destination = path.join(DIRECTORY, new Date().toISOString().replace(/[:.]/g, '-'));
  await mkdir(destination, { recursive: false });
  const report = { ...plan(), status: 'started', upstreamCalls: 0, knownPriorCostUsd: PRIOR.costUsd,
    correctionCostUsd: 0, totalObservedCostIncludingPriorUsd: PRIOR.costUsd, samples: [], humanVoiceQualityVerified: false };
  const save = () => writeFile(path.join(destination, 'report.json'), JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
  await save();
  try {
    const key = parseEnv(await readFile(path.join(AVATAR, 'openrouter.env'), 'utf8')).OPENROUTER_API_KEY;
    if (!key?.trim()) fail('local_key_unconfigured');
    for (const sample of CASES) {
      if (report.upstreamCalls >= LIMITS.calls) break;
      if (sample.id === 'pt') {
        const first = report.samples[0]?.usage;
        report.secondRequestForecast = forecastSecond(first && { ...first, costUsd: first.costUsd + PRIOR.costUsd });
        if (!report.secondRequestForecast.allowed) { report.code = report.secondRequestForecast.code; break; }
      }
      report.upstreamCalls++; await save();
      const result = await correctedAudition(fetch, key, sample, inputs.get(sample.id));
      const files = await saveDiagnosticAudio(destination, sample, result);
      const { rawPcm, wav, ...details } = result;
      if (finite(result.usage?.costUsd) && report.correctionCostUsd !== null) report.correctionCostUsd += result.usage.costUsd;
      else report.correctionCostUsd = null;
      report.totalObservedCostIncludingPriorUsd = report.correctionCostUsd === null ? null : report.correctionCostUsd + PRIOR.costUsd;
      report.samples.push({ id: sample.id, locale: sample.locale, inputSha256: sample.sha256, ...details, ...files });
      await save(); if (result.status !== 'completed') break;
    }
    report.status = report.samples.length === CASES.length && report.samples.every(sample => sample.strictCompletionPassed) &&
      report.totalObservedCostIncludingPriorUsd !== null && report.totalObservedCostIncludingPriorUsd <= LIMITS.estimatedTotalUsdCeiling ? 'completed' : 'failed';
  } catch (error) { report.status = 'failed'; report.code = error.code === 'local_key_unconfigured' ? error.code : 'local_preparation_failed'; }
  await save();
  console.log(JSON.stringify({ status: report.status, namespace: NAMESPACE, upstreamCalls: report.upstreamCalls,
    totalObservedCostIncludingPriorUsd: report.totalObservedCostIncludingPriorUsd, outputDirectory: destination,
    samples: report.samples.map(({ id, status, code, completionSource, strictCompletionPassed, previewFile }) =>
      ({ id, status, code, completionSource, strictCompletionPassed, previewFile })), humanVoiceQualityVerified: false }));
  if (report.status !== 'completed') process.exitCode = 1;
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url)
  main().catch(error => { console.log(JSON.stringify({ status: 'failed', code: ['invalid_arguments', 'prior_failure_hash_mismatch',
    'prior_admission_invalid', 'prior_evidence_invalid_json', 'prior_failure_provenance_mismatch', 'fixture_missing',
    'fixture_hash_mismatch', 'fixture_profile_mismatch', 'prior_failure_proof_missing', 'first_cost_forecast_insufficient'].includes(error.code) ? error.code :
    error.code === 'EEXIST' ? 'correction_admission_already_spent' : 'local_preparation_failed' })); process.exitCode = 1; });
