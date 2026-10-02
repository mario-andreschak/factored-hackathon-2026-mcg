/** One joined native/public-ASR audition. Preparation never opens a browser or calls a provider. */
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { RATE, LIMIT_MS, loopbackUrl, parseWav, wav, publicFixture, WireObservation,
  observeNativeAudio, scheduledRecording } from './personaplex_browser_audition.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SOURCE = path.join(ROOT, '.local/personaplex-forced-result/20261001-024017');
const INPUT_SHA256 = '02ad05f7d5c8fc4a736d20a97e352f3615be2aaec2512b0191ed722272ff7a05';
const fail = code => { const error = new Error(code); error.code = code; throw error; };
const hash = bytes => createHash('sha256').update(bytes).digest('hex');

/** Preserve only the verified public rice-cooking request, with no earlier Hi. */
export function riceFixture(pcm, report) {
  publicFixture(pcm, report); // Reuse the existing pin/frame/profile validation unchanged.
  return Buffer.concat([Buffer.alloc(4 * RATE * 2),
    pcm.subarray(188 * 1920 * 2, (188 * 1920 + 6 * RATE) * 2), Buffer.alloc(35 * RATE * 2)]);
}

export function qualifiedRiceFixture(source, report) {
  if (!Buffer.isBuffer(source) || hash(source) !== INPUT_SHA256) fail('unqualified_public_audio');
  return riceFixture(parseWav(source), report);
}

/** Actual hook payload: canonical bounded 16k mono PCM WAV, never arbitrary audio. */
export function transcriptionPayload(value) {
  if (!value || value.format !== 'wav' || typeof value.audio !== 'string' ||
      value.audio.length > 1_100_000 || !/^[A-Za-z0-9+/]+={0,2}$/.test(value.audio)) fail('unexpected_public_asr_payload');
  const bytes = Buffer.from(value.audio, 'base64');
  if (bytes.toString('base64') !== value.audio || bytes.length < 44 || bytes.length > 800044 ||
      bytes.toString('ascii', 0, 4) !== 'RIFF' || bytes.toString('ascii', 8, 12) !== 'WAVE' ||
      bytes.toString('ascii', 12, 16) !== 'fmt ' || bytes.toString('ascii', 36, 40) !== 'data' ||
      bytes.readUInt32LE(4) + 8 !== bytes.length || bytes.readUInt32LE(16) !== 16 ||
      bytes.readUInt16LE(20) !== 1 || bytes.readUInt16LE(22) !== 1 || bytes.readUInt32LE(24) !== 16000 ||
      bytes.readUInt32LE(28) !== 32000 || bytes.readUInt16LE(32) !== 2 || bytes.readUInt16LE(34) !== 16 ||
      bytes.readUInt32LE(40) !== bytes.length - 44 || (bytes.length - 44) % 2) fail('unexpected_public_asr_payload');
  const seconds = (bytes.length - 44) / 32000;
  if (seconds < 1 || seconds > 12) fail('unexpected_public_asr_duration');
  return { bytes, durationSeconds: seconds, sampleRate: 16000, sha256: hash(bytes) };
}

/** Accept questions and explicit requests; a greeting or topic mention is insufficient. */
export function riceRecognition(text) {
  if (typeof text !== 'string' || !text.trim() || text.length > 8000) fail('invalid_public_recognition');
  const normalized = text.trim().toLowerCase(), words = normalized.match(/[a-z]+(?:'[a-z]+)?/g) || [];
  const rice = /\brice\b/.test(normalized);
  const cooking = /\b(water|cook\w*|ratio|cups?|measure\w*|boil\w*)\b/.test(normalized);
  const question = /\b(how|what|which|should|can|could|ratio)\b/.test(normalized);
  const request = question || /\b(prevent|avoid|explain|help|tell|show)\b/.test(normalized);
  const unexpectedBankTopic = /\b(account|payment|balance|dispute|refund|chargeback|merchant)\b/.test(normalized);
  return { meaningfulRiceRequest: rice && cooking && request && words.length >= 6 && !unexpectedBankTopic,
    rice, cooking, question, request, wordCount: words.length, unexpectedBankTopic, sha256: hash(Buffer.from(text.trim())) };
}

/** Fail closed before a second provider call or any banking/fallback request. */
export class RequestScope {
  admissions = 0; transcriptions = 0; prohibited = 0;
  constructor(origin) { this.origin = loopbackUrl(origin); }
  admit(value, method) {
    const url = new URL(value), pathname = url.pathname;
    const permittedApi = pathname === '/api/avatar/config' && method === 'GET' ||
      pathname === '/api/avatar/personaplex-session' && method === 'POST' ||
      pathname === '/api/avatar/transcribe' && method === 'POST';
    if (url.origin !== this.origin || pathname === '/savia' || pathname.startsWith('/savia/') ||
        pathname.startsWith('/api/') && !permittedApi || !pathname.startsWith('/api/') && method !== 'GET') {
      this.prohibited++; fail('unexpected_request_scope');
    }
    if (pathname === '/api/avatar/personaplex-session' && ++this.admissions > 1) fail('duplicate_native_admission');
    if (pathname === '/api/avatar/transcribe' && ++this.transcriptions > 1) fail('duplicate_public_transcription');
    return pathname;
  }
}

export function plan(url) {
  loopbackUrl(url);
  return { status: 'prepared_not_executed', experiment: 'native_public_background_asr_audition', durationLimitSeconds: 45,
    source: 'SHA-256-pinned public NVIDIA rice-cooking request only; four leading and thirty-five trailing quiet seconds',
    microphone: 'Installed Edge fake file device only; no physical microphone or arbitrary input path',
    calls: 'One native admission/WebSocket and exactly one public transcription; unexpected calls are aborted',
    mute: 'Immediately after completed recognition is visible in actual Game; mute intentionally invalidates pending recognition',
    prerequisites: 'Ready PersonaPlex plus opted background ASR; Savia and native read bridge disabled',
    evidence: 'Real Game/hooks/AudioWorklet, meaningful rice request, continuous native PCM, mute zeros, playback and teardown',
    scope: 'No banking, native bank narration, adaptive role, tool, fallback or new provider deployment qualification' };
}

export async function execute(urlValue) {
  const origin = loopbackUrl(urlValue), directory = path.join(ROOT, '.local/personaplex-observer-browser', new Date().toISOString().replace(/[:.]/g, '-'));
  const source = await readFile(path.join(SOURCE, 'input.wav'));
  const sourceReport = JSON.parse(await readFile(path.join(SOURCE, 'report.json'), 'utf8'));
  const fixture = qualifiedRiceFixture(source, sourceReport);
  await mkdir(directory, { recursive: true });
  const fixturePath = path.join(directory, 'public-microphone.wav'); await writeFile(fixturePath, wav(fixture));
  const { chromium } = await import('@playwright/test');
  const wire = new WireObservation(), started = Date.now(), ms = () => Date.now() - started;
  let browser, context, page, failure = '', action = '', observationError = '';
  const scope = new RequestScope(origin);
  let sockets = 0, connected = false, cleaned = false;
  let requestEvidence, responseEvidence, uiRecognition, asrAudio, audio = {}, recording = Buffer.alloc(0), muteStart, muteEnd;
  const watchdog = setTimeout(() => { failure ||= 'audition_deadline'; void browser?.close().catch(() => {}); }, LIMIT_MS - 3000);
  const check = () => { if (failure || observationError) fail(failure || observationError); };
  const wait = async (predicate, budget, code) => {
    const until = Math.min(started + LIMIT_MS - 4000, Date.now() + budget);
    while (Date.now() < until) { check(); if (await predicate()) return; await new Promise(resolve => setTimeout(resolve, 50)); }
    fail(code);
  };
  try {
    browser = await chromium.launch({ channel: 'msedge', headless: true, timeout: 8000, args: [
      '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', `--use-file-for-fake-audio-capture=${fixturePath}`] });
    context = await browser.newContext({ viewport: { width: 1440, height: 900 }, permissions: ['microphone'] });
    await context.addInitScript(observeNativeAudio);
    page = await context.newPage(); page.setDefaultTimeout(4000);
    // Continue genuine permitted calls unchanged. These guards cannot fabricate a provider result.
    await page.route('**/*', async route => {
      const request = route.request(); let pathname;
      try { pathname = scope.admit(request.url(), request.method()); }
      catch (error) { failure ||= error?.code || 'unexpected_request_scope'; await route.abort('blockedbyclient'); return; }
      if (pathname === '/api/avatar/transcribe') {
        try {
          const payload = transcriptionPayload(request.postDataJSON()); asrAudio = payload.bytes;
          requestEvidence = { atMs: ms(), durationSeconds: payload.durationSeconds, sampleRate: payload.sampleRate,
            sha256: payload.sha256, inputPackets: wire.inputPackets, outputPackets: wire.outputPackets };
        } catch { failure ||= 'unexpected_public_asr_payload'; await route.abort('blockedbyclient'); return; }
      }
      await route.continue();
    });
    page.on('response', response => {
      if (new URL(response.url()).pathname !== '/api/avatar/transcribe') return;
      void (async () => {
        try {
          if (response.status() !== 200) fail('public_asr_failed');
          const body = await response.json(), verdict = riceRecognition(body.text);
          responseEvidence = { atMs: ms(), status: response.status(), inputPackets: wire.inputPackets,
            outputPackets: wire.outputPackets, ...verdict };
          if (!verdict.meaningfulRiceRequest) failure ||= 'meaningful_public_rice_request_missing';
        } catch (error) { failure ||= error?.code || 'public_asr_failed'; }
      })();
    });
    page.on('websocket', socket => {
      const url = new URL(socket.url());
      const expected = new URL(origin); expected.protocol = expected.protocol === 'https:' ? 'wss:' : 'ws:';
      if (url.origin !== expected.origin || url.pathname !== '/api/avatar/personaplex') { failure ||= 'unexpected_websocket_scope'; return; }
      sockets++; if (sockets > 1) failure ||= 'duplicate_native_socket';
      socket.on('framesent', event => { try { wire.sent(event.payload, ms(), action); } catch (error) { observationError ||= error?.code || 'wire_observation_failed'; } });
      socket.on('framereceived', event => { try { wire.received(event.payload, ms()); } catch (error) { observationError ||= error?.code || 'wire_observation_failed'; } });
      socket.on('close', () => { wire.closed = true; });
    });
    await page.goto(origin, { waitUntil: 'domcontentloaded', timeout: 8000 });
    const config = await page.evaluate(async () => {
      const response = await fetch('/api/avatar/config'), body = await response.json();
      return { provider: body.voiceProvider, ready: body.voiceAvailable, observer: body.backgroundAsrAvailable,
        backend: body.backendAvailable, bridge: body.nativeReadBridgeAvailable, computer: Boolean(body.saviaUrl) };
    });
    if (config.provider !== 'personaplex' || !config.ready || !config.observer || config.backend || config.bridge || config.computer) fail('isolated_native_observer_not_ready');
    await page.getByRole('button', { name: 'Wake the world', exact: true }).click();
    await wait(() => wire.ready, 15000, 'native_readiness_missing'); connected = true;
    await wait(() => scope.transcriptions === 1, 18000, 'public_transcription_missing');
    await wait(() => page.getByRole('button', { name: 'Pause story', exact: true }).count(), 3000, 'real_user_utterance_missing');
    // Open the genuine history UI so recognition delivery, not only provider JSON, is proved.
    action = 'manual_pause'; await page.getByRole('button', { name: 'Pause story', exact: true }).click();
    await page.getByRole('button', { name: 'Words along the way', exact: true }).click();
    await wait(async () => {
      if (!responseEvidence) return false;
      const text = await page.locator('.history-user p').allTextContents();
      if (text.length !== 1) return false;
      const verdict = riceRecognition(text[0]);
      if (!verdict.meaningfulRiceRequest || verdict.sha256 !== responseEvidence.sha256) fail('public_recognition_delivery_mismatch');
      uiRecognition = { atMs: ms(), ...verdict }; return true;
    }, 25000, 'public_recognition_delivery_missing');
    // Muting earlier would intentionally abort the observer and suppress its pending result.
    await page.getByRole('button', { name: 'Close transcript', exact: true }).click();
    action = 'manual_pause'; await page.getByRole('button', { name: 'Pause story', exact: true }).click();
    action = 'mute'; await page.getByRole('button', { name: 'Mute microphone', exact: true }).click();
    muteStart = ms(); wire.mute = muteStart;
    if (muteStart - uiRecognition.atMs > 1000) fail('recognition_mute_delay');
    await wait(() => wire.mutedSamples >= RATE * 1.5, 3000, 'mute_clock_missing');
    if (wire.mutedNonzero) fail('mute_contains_microphone_audio');
    muteEnd = ms();
    action = 'teardown'; await page.getByRole('button', { name: 'End voice', exact: true }).click(); wire.mute = undefined;
    await wait(async () => { const stats = await page.evaluate(() => window.__nativeAudition.summary());
      return wire.closed && stats.liveTracks === 0 && stats.openNativeContexts === 0 && stats.liveSources === 0;
    }, 2000, 'native_cleanup_missing'); cleaned = true;
    audio = await page.evaluate(() => window.__nativeAudition.summary());
    recording = scheduledRecording(await page.evaluate(() => window.__nativeAudition.recording()));
    if (scope.admissions !== 1 || sockets !== 1 || scope.transcriptions !== 1 || scope.prohibited || audio.micCalls !== 1 || audio.modules !== 1 ||
        !audio.audibleSources || wire.clockErrors || wire.pending.size ||
        responseEvidence.inputPackets <= requestEvidence.inputPackets || responseEvidence.outputPackets <= requestEvidence.outputPackets) fail('joined_scope_or_native_continuity_failed');
  } catch (error) { failure ||= error?.code || 'observer_browser_audition_failed'; }
  finally {
    if (page && !page.isClosed()) {
      try {
        action = 'teardown';
        const end = page.getByRole('button', { name: 'End voice', exact: true });
        if (!await end.count()) {
          const close = page.getByRole('button', { name: 'Close transcript', exact: true }); if (await close.count()) await close.click({ timeout: 500 });
          const pause = page.getByRole('button', { name: 'Pause story', exact: true }); if (await pause.count()) await pause.click({ timeout: 500 });
        }
        if (await end.count()) await end.click({ timeout: 500 });
        await new Promise(resolve => setTimeout(resolve, 100));
        audio = await page.evaluate(() => window.__nativeAudition?.summary() || {});
        cleaned ||= wire.closed && audio.liveTracks === 0 && audio.openNativeContexts === 0 && audio.liveSources === 0;
        if (!recording.length) recording = scheduledRecording(await page.evaluate(() => window.__nativeAudition?.recording() || []));
      } catch { /* Context/browser teardown remains unconditional. */ }
    }
    const close = async () => { await context?.close().catch(() => {}); await browser?.close().catch(() => {}); };
    let closeTimer;
    await Promise.race([close(), new Promise(resolve => { closeTimer = setTimeout(resolve, Math.max(1, started + LIMIT_MS - Date.now())); })]);
    clearTimeout(closeTimer); clearTimeout(watchdog);
  }
  const browserClosed = !browser?.isConnected(); if (!browserClosed) failure ||= 'browser_cleanup_missing';
  const report = { status: failure ? 'failed' : 'completed', experiment: 'native_public_background_asr_audition', failure: failure || undefined,
    elapsedMs: ms(), maximumSeconds: 45, protocol: 'personaplex-pcm-v1', sourceRevision: sourceReport.source_revision, modelRevision: sourceReport.model_revision,
    syntheticPublicMic: true, fixture: { sourceSha256: INPUT_SHA256, seconds: fixture.length / (RATE * 2), publicExcerptSeconds: 6, speechStartsAtSeconds: 4 },
    admissions: scope.admissions, sockets, transcriptions: scope.transcriptions, prohibitedRequests: scope.prohibited, connected,
    readyMs: wire.readyMs, firstOutputMs: wire.firstOutput,
    inputPackets: wire.inputPackets, inputSamples: wire.inputSamples, outputPackets: wire.outputPackets, outputSamples: wire.outputSamples, clockErrors: wire.clockErrors,
    recognition: { request: requestEvidence, response: responseEvidence, delivered: uiRecognition,
      nativeInputPacketsWhilePending: responseEvidence && requestEvidence ? responseEvidence.inputPackets - requestEvidence.inputPackets : undefined,
      nativeOutputPacketsWhilePending: responseEvidence && requestEvidence ? responseEvidence.outputPackets - requestEvidence.outputPackets : undefined },
    interruptions: wire.interrupts.map(row => ({ action: row.action || 'microphone_vad', sentMs: row.sentMs, ackLatencyMs: row.ackLatencyMs, generation: row.nextGeneration })),
    mute: { startMs: muteStart, endMs: muteEnd, afterDeliveredMs: uiRecognition && muteStart !== undefined ? muteStart - uiRecognition.atMs : undefined,
      packets: wire.mutedPackets, samples: wire.mutedSamples, nonzeroSamples: wire.mutedNonzero },
    audio: { ...audio, stops: undefined, audibleWindows: undefined }, cleanupProvedInPage: cleaned, browserClosed,
    limits: 'Public background recognition only; no banking, tool, narration, adaptive role or physical microphone qualification. Scheduled buffers are not hardware loopback.' };
  await writeFile(path.join(directory, 'report.json'), JSON.stringify(report, null, 2) + '\n');
  await writeFile(path.join(directory, 'native-wire-output.wav'), wav(Buffer.concat(wire.records)));
  await writeFile(path.join(directory, 'native-scheduled-output.wav'), wav(recording));
  if (asrAudio) await writeFile(path.join(directory, 'actual-public-asr-input.wav'), asrAudio);
  process.stdout.write(JSON.stringify({ ...report, outputDirectory: directory }, null, 2) + '\n');
  if (failure) process.exitCode = 1;
  return report;
}

async function main() {
  const args = process.argv.slice(2); let executeFlag = false, url;
  for (let index = 0; index < args.length; index++) {
    if (args[index] === '--execute') executeFlag = true;
    else if (args[index] === '--plan') { /* Inert default. */ }
    else if (args[index] === '--url' && args[index + 1]) url = args[++index];
    else fail('invalid_arguments');
  }
  if (executeFlag) await execute(url); else process.stdout.write(JSON.stringify(plan(url), null, 2) + '\n');
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => { process.stderr.write(JSON.stringify({ status: 'failed', failure: error?.code || 'observer_browser_audition_failed' }) + '\n'); process.exitCode = 1; });
}
