/** One opt-in real initial-role audition. Import/default plan never dispatches anything. */
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { classifyMood } from '../server/mood.mjs';
import { RATE, loopbackUrl, wav, WireObservation, observeNativeAudio, scheduledRecording } from './personaplex_browser_audition.mjs';
import { qualifiedRiceFixture, riceRecognition } from './personaplex_observer_audition.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SOURCE = path.join(ROOT, '.local/personaplex-forced-result/20261001-024017');
export const LIMIT_MS = 60_000;
export const EXPECTED_TEXT = 'Prevent rice from becoming sticky when cooking on the stove.';
export const SOURCE_SHA256 = '02ad05f7d5c8fc4a736d20a97e352f3615be2aaec2512b0191ed722272ff7a05';
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const fail = code => { const error = new Error(code); error.code = code; throw error; };

/** Only the already qualified six-second rice excerpt, with enough quiet to avoid a second loop. */
export function initialFixture(source, report) {
  return Buffer.concat([qualifiedRiceFixture(source, report), Buffer.alloc(15 * RATE * 2)]);
}
function fixtureWav(pcm) {
  if (!Buffer.isBuffer(pcm) || pcm.length !== LIMIT_MS / 1000 * RATE * 2) fail('invalid_public_fixture');
  const header = wav(Buffer.alloc(0)); header.writeUInt32LE(36 + pcm.length, 4); header.writeUInt32LE(pcm.length, 40);
  return Buffer.concat([header, pcm]);
}

/** Strict actual Game input. No role, prompt, alternate rate or arbitrary recording source. */
export function initialPayload(value) {
  if (!value || Object.keys(value).sort().join(',') !== 'audio,format' || value.format !== 'wav' ||
      typeof value.audio !== 'string' || value.audio.length > 800_000 || !/^[A-Za-z0-9+/]+={0,2}$/.test(value.audio)) fail('invalid_initial_payload');
  const bytes = Buffer.from(value.audio, 'base64');
  if (bytes.toString('base64') !== value.audio || bytes.length < 44 ||
      bytes.toString('ascii', 0, 4) !== 'RIFF' || bytes.toString('ascii', 8, 12) !== 'WAVE' ||
      bytes.toString('ascii', 12, 16) !== 'fmt ' || bytes.readUInt32LE(16) !== 16 ||
      bytes.readUInt16LE(20) !== 1 || bytes.readUInt16LE(22) !== 1 || bytes.readUInt32LE(24) !== RATE ||
      bytes.readUInt32LE(28) !== RATE * 2 || bytes.readUInt16LE(32) !== 2 || bytes.readUInt16LE(34) !== 16 ||
      bytes.toString('ascii', 36, 40) !== 'data' || bytes.readUInt32LE(40) !== bytes.length - 44 ||
      bytes.readUInt32LE(4) + 8 !== bytes.length || (bytes.length - 44) % 2) fail('invalid_initial_payload');
  const pcm = bytes.subarray(44), seconds = pcm.length / (RATE * 2);
  if (seconds < 1 || seconds > 12) fail('invalid_initial_duration');
  return { bytes, pcm, seconds, wavSha256: hash(bytes), pcmSha256: hash(pcm) };
}

export function selectedResponse(body) {
  const verdict = riceRecognition(body?.transcript);
  if (body?.avatar !== classifyMood(body.transcript).avatar || body.avatar !== 'moss' ||
      body.initialContextDelivered !== false || !verdict.meaningfulRiceRequest) fail('initial_selection_mismatch');
  // Tickets/expiry are validated by the real hook, and deliberately absent from receipts.
  return { avatar: body.avatar, initialContextDelivered: false, expectedMeaningfullyEquivalent: true, ...verdict };
}

export function nativeContextEvidence(text) {
  if (typeof text !== 'string' || !text.trim() || text.length > 80_000) fail('invalid_native_caption');
  const lower = text.toLowerCase(), words = lower.match(/[a-z]+/g) || [];
  const cooking = /\b(rice|cook\w*|stove|starch|grains?)\b/.test(lower);
  const detail = /\b(rinse|water|heat|simmer|boil|drain|steam|pot|sticky|fluffy|stir|soak)\b/.test(lower);
  const bank = /\b(account|payment|balance|dispute|refund|chargeback|merchant)\b/.test(lower);
  return { relevantCookingResponse: cooking && detail && words.length >= 8 && !bank,
    cooking, detail, wordCount: words.length, unexpectedBankTopic: bank, sha256: hash(Buffer.from(text.trim())) };
}

/** One actual endpoint, no fallback, regular observer, bank call or retry. */
export class InitialRequestScope {
  initialPosts = 0; prohibited = 0;
  constructor(origin) { this.origin = loopbackUrl(origin); }
  admit(value, method) {
    const url = new URL(value), p = url.pathname;
    const permitted = p === '/api/avatar/config' && method === 'GET' || p === '/api/avatar/personaplex-initial' && method === 'POST';
    if (url.origin !== this.origin || p === '/savia' || p.startsWith('/savia/') ||
        p.startsWith('/api/') && (!permitted || url.search) || !p.startsWith('/api/') && method !== 'GET') {
      this.prohibited++; fail('unexpected_request_scope');
    }
    if (p === '/api/avatar/personaplex-initial' && ++this.initialPosts > 1) fail('duplicate_initial_admission');
    return p;
  }
}

/** Byte-exact finite prefix, including final zero padding; live samples never repair a mismatch. */
export class ReplayObservation {
  constructor(pcm) {
    if (!Buffer.isBuffer(pcm) || !pcm.length || pcm.length % 2 || pcm.length > 12 * RATE * 2) fail('invalid_replay_input');
    this.pcm = Buffer.from(pcm); this.frames = Math.ceil(pcm.length / 3840); this.packets = []; this.times = [];
  }
  sent(packet, at, readyAt) {
    if (this.packets.length >= this.frames) return false;
    if (readyAt === undefined || at < readyAt || !Buffer.isBuffer(packet) || packet[0] !== 0x10 || packet.length !== 3841) fail('replay_before_ready_or_interleaved');
    const expected = Buffer.alloc(3840), offset = this.packets.length * 3840;
    this.pcm.copy(expected, 0, offset, Math.min(offset + 3840, this.pcm.length));
    if (!packet.subarray(1).equals(expected)) fail('initial_pcm_replay_mismatch');
    this.packets.push(Buffer.from(packet.subarray(1))); this.times.push(at); return true;
  }
  get complete() { return this.packets.length === this.frames; }
  report(browserTimes = this.times) {
    if (!this.complete || browserTimes.length < this.frames) fail('initial_replay_incomplete');
    const times = browserTimes.slice(0, this.frames), gaps = times.slice(1).map((t, i) => t - times[i]);
    if (times.some(t => !Number.isFinite(t)) || gaps.some(gap => gap < 65 || gap > 500) ||
        times.at(-1) - times[0] < (this.frames - 1) * 75) fail('initial_replay_pacing_failed');
    const padded = Buffer.concat(this.packets), original = padded.subarray(0, this.pcm.length);
    return { frames: this.frames, capturedSamples: this.pcm.length / 2, paddedSamples: padded.length / 2 - this.pcm.length / 2,
      capturedPcmSha256: hash(this.pcm), replayPcmSha256: hash(original), paddedPcmSha256: hash(padded),
      byteExact: original.equals(this.pcm), firstSentMs: this.times[0], lastSentMs: this.times.at(-1),
      browserMinimumGapMs: Math.min(...gaps), browserMaximumGapMs: Math.max(...gaps), elapsedMs: times.at(-1) - times[0] };
  }
}

/** Passive wrappers delegate every real operation; no fabricated mic, socket, timer or output. */
export function observeInitialResources() {
  const native = window.AudioContext, contexts = new Set(), shortTimers = new Map(), binaryTimes = [];
  let playbackChecks = 0, playbackViolations = 0;
  class ObservedContext extends native { constructor(...args) { super(...args); contexts.add(this); } }
  window.AudioContext = ObservedContext;
  const send = WebSocket.prototype.send;
  WebSocket.prototype.send = function (data) { if (data instanceof Uint8Array && data[0] === 0x10) binaryTimes.push(performance.now()); return send.call(this, data); };
  const create = native.prototype.createBufferSource;
  native.prototype.createBufferSource = function (...args) {
    const source = create.apply(this, args), connect = source.connect.bind(source), start = source.start.bind(source); let isNative = false;
    source.connect = (...args) => { if (args[0] instanceof AnalyserNode) isNative = true; return connect(...args); };
    source.start = (...args) => { if (isNative && source.buffer?.sampleRate === 24000) {
      playbackChecks++; if (source.playbackRate.value !== 1 || source.detune.value !== 0 || source.loop) playbackViolations++;
    } return start(...args); }; return source;
  };
  const schedule = window.setTimeout.bind(window), cancel = window.clearTimeout.bind(window);
  window.setTimeout = (callback, delay, ...args) => {
    if (typeof callback !== 'function' || !(Number(delay) >= 0 && Number(delay) <= 80)) return schedule(callback, delay, ...args);
    let id; id = schedule((...values) => { shortTimers.delete(id); return callback.apply(window, values); }, delay, ...args);
    shortTimers.set(id, Number(delay)); return id;
  };
  window.clearTimeout = id => { shortTimers.delete(id); return cancel(id); };
  window.__initialAudition = { summary: () => ({ contextsCreated: contexts.size, openContexts: [...contexts].filter(c => c.state !== 'closed').length,
    shortTimers: shortTimers.size, playbackChecks, playbackViolations, binaryTimes: binaryTimes.slice() }) };
}

export function plan(url) {
  loopbackUrl(url);
  return { status: 'prepared_not_executed', experiment: 'native_initial_role_public_audition', durationLimitSeconds: 60,
    microphone: 'Installed Edge fake-file microphone; existing SHA-pinned public rice request plus silence only',
    selection: 'Actual initial endpoint chooses Moss using the shared classifier; no spoken-name gate',
    calls: 'One initial POST and native WebSocket; implicit server ASR only, no retries or regular observer calls',
    prerequisites: 'Isolated opt-in warm v2 lease; initialVoiceAvailable true; Savia/read bridge disabled',
    evidence: 'Actual Game history/form, READY, byte-exact finite normal1x replay, relevant native cooking caption, playback/mute/cleanup',
    limits: 'Source readiness only until executed and reviewed; no physical microphone, bank, narration or mid-session role proof' };
}

export async function execute(urlValue) {
  const origin = loopbackUrl(urlValue), directory = path.join(ROOT, '.local/personaplex-initial-browser', new Date().toISOString().replace(/[:.]/g, '-'));
  const source = await readFile(path.join(SOURCE, 'input.wav')), sourceReport = JSON.parse(await readFile(path.join(SOURCE, 'report.json'), 'utf8'));
  const fixture = initialFixture(source, sourceReport);
  await mkdir(directory, { recursive: true }); const fixturePath = path.join(directory, 'public-microphone.wav'); await writeFile(fixturePath, fixtureWav(fixture));
  const { chromium } = await import('@playwright/test');
  const scope = new InitialRequestScope(origin), wire = new WireObservation(), started = Date.now(), ms = () => Date.now() - started;
  let browser, context, page, failure = '', action = '', sockets = 0, cleaned = false, requestEvidence, responseEvidence, delivered, nativeEvidence;
  let replay, responseAt, responseText, captured, audio = {}, resources = {}, recording = Buffer.alloc(0), muteStart, muteEnd;
  const captions = new Map();
  const watchdog = setTimeout(() => { failure ||= 'audition_deadline'; void browser?.close().catch(() => {}); }, LIMIT_MS - 3000);
  const check = () => { if (failure) fail(failure); };
  const wait = async (predicate, budget, code) => {
    const until = Math.min(started + LIMIT_MS - 4000, Date.now() + budget);
    while (Date.now() < until) { check(); if (await predicate()) return; await new Promise(resolve => setTimeout(resolve, 50)); }
    fail(code);
  };
  try {
    browser = await chromium.launch({ channel: 'msedge', headless: true, timeout: 8000, args: ['--use-fake-device-for-media-stream',
      '--use-fake-ui-for-media-stream', `--use-file-for-fake-audio-capture=${fixturePath}`] });
    context = await browser.newContext({ viewport: { width: 1440, height: 900 }, permissions: ['microphone'] });
    await context.addInitScript(observeNativeAudio); await context.addInitScript(observeInitialResources);
    page = await context.newPage(); page.setDefaultTimeout(3000);
    await page.route('**/*', async route => {
      const request = route.request(); let p;
      try { p = scope.admit(request.url(), request.method()); }
      catch (error) { failure ||= error.code; await route.abort('blockedbyclient'); return; }
      if (p === '/api/avatar/personaplex-initial') {
        try { if (sockets || wire.inputPackets) fail('native_before_initial_selection');
          const checked = initialPayload(request.postDataJSON()); captured = checked.bytes; replay = new ReplayObservation(checked.pcm);
          requestEvidence = { atMs: ms(), durationSeconds: checked.seconds, sampleRate: RATE, wavSha256: checked.wavSha256, pcmSha256: checked.pcmSha256 };
        } catch (error) { failure ||= error.code || 'invalid_initial_payload'; await route.abort('blockedbyclient'); return; }
      }
      await route.continue(); // Genuine calls only; no response fulfillment or mocked transport.
    });
    page.on('response', response => {
      if (new URL(response.url()).pathname !== '/api/avatar/personaplex-initial') return;
      responseAt = ms();
      void (async () => { try {
        if (response.status() !== 200) fail('initial_endpoint_failed');
        const body = await response.json();
        responseEvidence = { atMs: responseAt, status: 200, ...selectedResponse(body) }; responseText = body.transcript.trim();
      } catch (error) { failure ||= error.code || 'initial_endpoint_failed'; } })();
    });
    page.on('websocket', socket => {
      const url = new URL(socket.url()), expected = new URL(origin); expected.protocol = expected.protocol === 'https:' ? 'wss:' : 'ws:';
      if (url.origin !== expected.origin || url.pathname !== '/api/avatar/personaplex' || ++sockets !== 1 || responseAt === undefined) {
        failure ||= 'unexpected_or_early_native_socket'; return;
      }
      socket.on('framesent', event => { try {
        if (!wire.ready) fail('pcm_before_native_ready');
        if (Buffer.isBuffer(event.payload)) replay.sent(event.payload, ms(), wire.readyMs);
        wire.sent(event.payload, ms(), action);
      } catch (error) { failure ||= error.code || 'native_input_failed'; } });
      socket.on('framereceived', event => { try {
        wire.received(event.payload, ms());
        if (typeof event.payload === 'string') { const value = JSON.parse(event.payload);
          if (value.type === 'transcript' && value.role === 'assistant') captions.set(value.id, value.text);
        }
      } catch (error) { failure ||= error.code || 'native_output_failed'; } });
      socket.on('close', () => { wire.closed = true; });
    });
    await page.goto(origin, { waitUntil: 'domcontentloaded', timeout: 8000 });
    const config = await page.evaluate(async () => {
      const body = await (await fetch('/api/avatar/config')).json();
      return { provider: body.voiceProvider, initial: body.initialVoiceAvailable, fixed: body.voiceAvailable,
        observer: body.backgroundAsrAvailable, bank: body.backendAvailable, bridge: body.nativeReadBridgeAvailable, computer: Boolean(body.saviaUrl) };
    });
    if (config.provider !== 'personaplex' || config.initial !== true || config.fixed || config.observer !== true || config.bank || config.bridge || config.computer) fail('isolated_initial_role_not_ready');
    await page.getByRole('button', { name: 'Wake the world', exact: true }).click();
    await wait(() => scope.initialPosts === 1, 18000, 'first_capture_missing');
    await wait(() => wire.ready && responseEvidence, 35000, 'initial_native_readiness_missing');
    await wait(() => replay.complete, 14000, 'initial_replay_incomplete');
    await wait(() => wire.inputPackets > replay.frames, 1000, 'replay_live_handoff_missing');
    resources = await page.evaluate(() => window.__initialAudition.summary());
    replay.report(resources.binaryTimes);
    await wait(() => {
      const text = [...captions.values()].join(' '); if (!text) return false;
      const verdict = nativeContextEvidence(text); if (!verdict.relevantCookingResponse) return false;
      nativeEvidence = { atMs: ms(), ...verdict }; return true;
    }, 10000, 'native_first_problem_response_missing');
    // Actual Game form and history, not only the JSON response, must agree.
    if (!await page.locator('.game.story-moss .world--moss').count()) fail('selected_game_form_mismatch');
    action = 'manual_pause'; await page.getByRole('button', { name: 'Pause story', exact: true }).click();
    await wait(() => wire.interrupts.some(row => row.action === 'manual_pause' && row.ackMs !== undefined), 3000, 'actual_interrupt_ack_missing');
    await page.getByRole('button', { name: 'Words along the way', exact: true }).click();
    const history = await page.locator('.history-user p').allTextContents();
    if (history.length !== 1 || history[0].trim() !== responseText) fail('initial_game_history_mismatch');
    delivered = { atMs: ms(), count: history.length, sha256: hash(Buffer.from(history[0].trim())) };
    await page.getByRole('button', { name: 'Close transcript', exact: true }).click();
    action = 'manual_pause'; await page.getByRole('button', { name: 'Pause story', exact: true }).click();
    action = 'mute'; await page.getByRole('button', { name: 'Mute microphone', exact: true }).click(); muteStart = ms(); wire.mute = muteStart;
    await wait(() => wire.mutedSamples >= RATE * 1.5, 3000, 'mute_clock_missing');
    if (wire.mutedNonzero) fail('muted_input_nonzero'); muteEnd = ms();
    action = 'teardown'; await page.getByRole('button', { name: 'End voice', exact: true }).click(); wire.mute = undefined;
    await wait(async () => { audio = await page.evaluate(() => window.__nativeAudition.summary()); resources = await page.evaluate(() => window.__initialAudition.summary());
      return wire.closed && audio.liveTracks === 0 && audio.liveSources === 0 && resources.openContexts === 0 && resources.shortTimers === 0;
    }, 2000, 'initial_resources_not_cleaned'); cleaned = true;
    recording = scheduledRecording(await page.evaluate(() => window.__nativeAudition.recording()));
    if (scope.initialPosts !== 1 || scope.prohibited || sockets !== 1 || wire.clockErrors || wire.pending.size || audio.micCalls !== 1 ||
        audio.modules !== 1 || !audio.audibleSources || resources.contextsCreated !== 1 || !resources.playbackChecks || resources.playbackViolations) fail('initial_scope_or_playback_failed');
  } catch (error) { failure ||= error?.code || 'initial_browser_audition_failed'; }
  finally {
    if (page && !page.isClosed()) {
      try {
        action = 'teardown'; const close = page.getByRole('button', { name: 'Close transcript', exact: true }); if (await close.count()) await close.click({ timeout: 500 });
        const end = page.getByRole('button', { name: 'End voice', exact: true });
        if (!await end.count()) { const pause = page.getByRole('button', { name: 'Pause story', exact: true }); if (await pause.count()) await pause.click({ timeout: 500 }); }
        if (await end.count()) await end.click({ timeout: 500 });
        await new Promise(resolve => setTimeout(resolve, 100));
        audio = await page.evaluate(() => window.__nativeAudition?.summary() || {});
        resources = await page.evaluate(() => window.__initialAudition?.summary() || {});
        cleaned ||= wire.closed && audio.liveTracks === 0 && audio.liveSources === 0 && resources.openContexts === 0 && resources.shortTimers === 0;
        if (!recording.length) recording = scheduledRecording(await page.evaluate(() => window.__nativeAudition?.recording() || []));
      } catch { /* Browser/context closure still happens on every failure. */ }
    }
    let closeTimer;
    await Promise.race([(async () => { await context?.close().catch(() => {}); await browser?.close().catch(() => {}); })(),
      new Promise(resolve => { closeTimer = setTimeout(resolve, Math.max(1, started + LIMIT_MS - Date.now())); })]);
    clearTimeout(closeTimer); clearTimeout(watchdog);
  }
  const browserClosed = !browser?.isConnected(); if (!browserClosed) failure ||= 'browser_cleanup_missing';
  let replayEvidence; try { replayEvidence = replay?.report(resources.binaryTimes); } catch (error) { failure ||= error.code; }
  const report = { status: failure ? 'failed' : 'completed', experiment: 'native_initial_role_public_audition', failure: failure || undefined,
    elapsedMs: ms(), maximumSeconds: 60, protocol: 'personaplex-pcm-v1', sourceRevision: sourceReport.source_revision,
    modelRevision: sourceReport.model_revision, syntheticPublicMic: true, fixture: { sourceSha256: SOURCE_SHA256, durationSeconds: 60, publicExcerptSeconds: 6 },
    initialEndpointPosts: scope.initialPosts, sockets, prohibitedRequests: scope.prohibited,
    serverAsr: 'Implicit initial-coordinator admission; browser cannot independently count upstream requests',
    selection: { request: requestEvidence, response: responseEvidence, delivered }, readyMs: wire.readyMs, firstOutputMs: wire.firstOutput,
    replay: replayEvidence, nativeContext: nativeEvidence, inputPackets: wire.inputPackets, outputPackets: wire.outputPackets, clockErrors: wire.clockErrors,
    interruptions: wire.interrupts.map(row => ({ action: row.action || 'microphone_vad', sentMs: row.sentMs, ackLatencyMs: row.ackLatencyMs, generation: row.nextGeneration })),
    mute: { startMs: muteStart, endMs: muteEnd, packets: wire.mutedPackets, samples: wire.mutedSamples, nonzeroSamples: wire.mutedNonzero },
    audio: { ...audio, stops: undefined, audibleWindows: undefined }, resources: { ...resources, binaryTimes: undefined },
    cleanupProvedInPage: cleaned, browserClosed,
    limits: 'Public initial-context caption evidence only; human listening still required. No physical microphone, banking, native bank narration, tool or mid-session role qualification.' };
  await writeFile(path.join(directory, 'report.json'), JSON.stringify(report, null, 2) + '\n');
  await writeFile(path.join(directory, 'native-wire-output.wav'), wav(Buffer.concat(wire.records)));
  await writeFile(path.join(directory, 'native-scheduled-output.wav'), wav(recording));
  await writeFile(path.join(directory, 'native-captions.json'), JSON.stringify([...captions.values()], null, 2) + '\n');
  if (captured) await writeFile(path.join(directory, 'actual-initial-capture.wav'), captured);
  process.stdout.write(JSON.stringify({ ...report, outputDirectory: directory }, null, 2) + '\n');
  if (failure) process.exitCode = 1;
  return report;
}

async function main() {
  let mode, url; const args = process.argv.slice(2);
  for (let index = 0; index < args.length; index++) {
    if (args[index] === '--execute' || args[index] === '--plan') { if (mode) fail('invalid_arguments'); mode = args[index]; }
    else if (args[index] === '--url' && args[index + 1]) url = args[++index];
    else fail('invalid_arguments');
  }
  if (mode === '--execute') await execute(url); else process.stdout.write(JSON.stringify(plan(url), null, 2) + '\n');
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => { process.stderr.write(JSON.stringify({ status: 'failed', failure: error?.code || 'initial_browser_audition_failed' }) + '\n'); process.exitCode = 1; });
}
