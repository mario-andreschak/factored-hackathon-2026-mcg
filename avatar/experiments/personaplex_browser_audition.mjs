/** One explicit native browser audition. The default plan never opens a browser or a lease. */
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const RATE = 24000;
export const LIMIT_MS = 45000;
const SOURCE_REVISION = '3428dfd95309a7f3c84fd93259ded0f810d1ff91';
const MODEL_REVISION = 'fdaf4090a61cb315c138a1faee287ffd6c716309';
const INPUT_SHA256 = '02ad05f7d5c8fc4a736d20a97e352f3615be2aaec2512b0191ed722272ff7a05';
const SOURCE = path.join(ROOT, '.local/personaplex-forced-result/20261001-024017');
const fail = code => { const error = new Error(code); error.code = code; throw error; };

export function loopbackUrl(value = 'http://127.0.0.1:43937') {
  let url; try { url = new URL(value); } catch { fail('invalid_loopback_origin'); }
  if (!['http:', 'https:'].includes(url.protocol) || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) ||
      url.username || url.password || url.search || url.hash || url.pathname !== '/') fail('invalid_loopback_origin');
  return url.origin;
}

export function parseWav(bytes) {
  if (!Buffer.isBuffer(bytes) || bytes.length > 3 * 1024 * 1024 || bytes.length < 44 ||
      bytes.toString('ascii', 0, 4) !== 'RIFF' || bytes.toString('ascii', 8, 12) !== 'WAVE' ||
      bytes.readUInt32LE(4) + 8 !== bytes.length) fail('invalid_public_audio');
  let format, pcm;
  for (let offset = 12; offset + 8 <= bytes.length;) {
    const kind = bytes.toString('ascii', offset, offset + 4), size = bytes.readUInt32LE(offset + 4), start = offset + 8;
    if (start + size > bytes.length) fail('invalid_public_audio');
    if (kind === 'fmt ') { if (format || size < 16) fail('invalid_public_audio'); format = bytes.subarray(start, start + size); }
    if (kind === 'data') { if (pcm) fail('invalid_public_audio'); pcm = bytes.subarray(start, start + size); }
    offset = start + size + (size % 2);
  }
  if (!format || !pcm?.length || pcm.length % 2 || format.readUInt16LE(0) !== 1 || format.readUInt16LE(2) !== 1 ||
      format.readUInt32LE(4) !== RATE || format.readUInt32LE(8) !== RATE * 2 || format.readUInt16LE(12) !== 2 ||
      format.readUInt16LE(14) !== 16) fail('invalid_public_audio');
  return pcm;
}

export function wav(pcm) {
  if (!Buffer.isBuffer(pcm) || pcm.length % 2 || pcm.length > RATE * 2 * 45) fail('invalid_recording');
  const header = Buffer.alloc(44);
  header.write('RIFF'); header.writeUInt32LE(36 + pcm.length, 4); header.write('WAVE', 8); header.write('fmt ', 12);
  header.writeUInt32LE(16, 16); header.writeUInt16LE(1, 20); header.writeUInt16LE(1, 22); header.writeUInt32LE(RATE, 24);
  header.writeUInt32LE(RATE * 2, 28); header.writeUInt16LE(2, 32); header.writeUInt16LE(16, 34);
  header.write('data', 36); header.writeUInt32LE(pcm.length, 40); return Buffer.concat([header, pcm]);
}

/** Only original public NVIDIA microphone bytes and silence. No forced assistant output. */
export function publicFixture(pcm, report) {
  if (report?.source_revision !== SOURCE_REVISION || report.model_revision !== MODEL_REVISION || report.banking_access !== false ||
      report.clock_frames !== 338 || report.continuation_start_frame !== 188 || pcm.length !== 338 * 1920 * 2) fail('unqualified_public_audio');
  const quiet = seconds => Buffer.alloc(seconds * RATE * 2);
  const fixture = Buffer.concat([quiet(4), pcm.subarray(0, 4 * RATE * 2), quiet(2),
    pcm.subarray(188 * 1920 * 2, (188 * 1920 + 8 * RATE) * 2),
    quiet(7.8)]);
  // Both actual auditions' sustained answers overlap this earlier candidate.
  // Replace only the quiet tail with exact public Hi bytes; keep the total loop.
  pcm.subarray(3.2 * RATE * 2, 4 * RATE * 2).copy(fixture, 16 * RATE * 2);
  return fixture;
}

export function inspectOutput(payload) {
  if (!Buffer.isBuffer(payload) || payload[0] !== 0x11 || payload.length <= 13 || (payload.length - 13) % 2 ||
      payload.length - 13 > 1920 * 2 * 6) fail('invalid_native_packet');
  const clock = payload.readBigUInt64LE(5);
  if (clock > BigInt(Number.MAX_SAFE_INTEGER)) fail('invalid_native_clock');
  return { generation: payload.readUInt32LE(1), clock: Number(clock), samples: (payload.length - 13) / 2, pcm: payload.subarray(13) };
}

export class WireObservation {
  constructor() {
    this.ready = false; this.closed = false; this.generation = 0; this.minimumClock = 0; this.nextClock = undefined;
    this.inputPackets = 0; this.inputSamples = 0; this.outputPackets = 0; this.outputSamples = 0;
    this.records = []; this.interrupts = []; this.pending = new Map(); this.firstOutput = undefined;
    this.mute = undefined; this.mutedPackets = 0; this.mutedSamples = 0; this.mutedNonzero = 0; this.clockErrors = 0;
  }
  sent(payload, at, action = '') {
    if (typeof payload === 'string') {
      let value; try { value = JSON.parse(payload); } catch { fail('invalid_native_control'); }
      if (value.type !== 'interrupt' || typeof value.id !== 'string' || this.pending.has(value.id)) fail('invalid_native_control');
      const row = { sentMs: at, action, generation: this.generation }; this.pending.set(value.id, row); this.interrupts.push(row); return;
    }
    if (!Buffer.isBuffer(payload) || payload[0] !== 0x10 || payload.length <= 1 || (payload.length - 1) % 2 || payload.length > 23041) fail('invalid_capture_packet');
    const count = (payload.length - 1) / 2; this.inputPackets++; this.inputSamples += count;
    if (this.mute !== undefined && at >= this.mute + 150) {
      this.mutedPackets++; this.mutedSamples += count;
      for (let i = 1; i < payload.length; i += 2) if (payload.readInt16LE(i) !== 0) this.mutedNonzero++;
    }
  }
  received(payload, at) {
    if (typeof payload === 'string') {
      let value; try { value = JSON.parse(payload); } catch { fail('invalid_native_control'); }
      if (value.type === 'ready') {
        if (this.ready || value.protocol !== 'personaplex-pcm-v1' || value.sampleRate !== RATE || value.frameSamples !== 1920 || value.format !== 'pcm16le') fail('invalid_native_readiness');
        this.ready = true; this.readyMs = at;
      } else if (value.type === 'interrupted') {
        const row = this.pending.get(value.id);
        if (!row || value.generation !== row.generation + 1 || value.generation < this.generation) fail('invalid_interrupt_ack');
        row.ackMs = at; row.ackLatencyMs = at - row.sentMs; row.nextGeneration = value.generation;
        this.pending.delete(value.id); this.generation = value.generation; this.nextClock = undefined;
      } else if (value.type === 'error') fail('native_worker_error');
      else if (value.type !== 'transcript') fail('invalid_native_control');
      return;
    }
    if (!this.ready) fail('audio_before_readiness');
    const packet = inspectOutput(payload);
    if (packet.generation < this.generation) fail('stale_relay_audio');
    if (packet.generation > this.generation) { this.generation = packet.generation; this.nextClock = undefined; }
    if ((this.nextClock !== undefined && packet.clock !== this.nextClock) || packet.clock < this.minimumClock) { this.clockErrors++; fail('noncontiguous_native_clock'); }
    this.nextClock = packet.clock + packet.samples; this.minimumClock = this.nextClock;
    this.outputPackets++; this.outputSamples += packet.samples; this.firstOutput ??= at;
    if (this.outputSamples > RATE * 45) fail('recording_limit');
    this.records.push(Buffer.from(packet.pcm));
  }
}

/** Passive delegation: actual AudioContext, microphone, Worklet and socket remain unchanged. */
export function observeNativeAudio() {
  const contexts = new Set(), tracks = new Set(), sources = [], stops = [];
  let micCalls = 0, modules = 0, samples = 0;
  const originalGet = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia = async (...args) => {
    micCalls++; const stream = await originalGet(...args); stream.getTracks().forEach(track => tracks.add(track)); return stream;
  };
  const worklet = AudioWorklet.prototype.addModule;
  AudioWorklet.prototype.addModule = function (...args) { modules++; return worklet.apply(this, args); };
  const create = AudioContext.prototype.createBufferSource;
  AudioContext.prototype.createBufferSource = function (...args) {
    const source = create.apply(this, args), context = this;
    let native = false, row;
    const connect = source.connect.bind(source), start = source.start.bind(source), stop = source.stop.bind(source);
    source.connect = (...values) => { if (values[0] instanceof AnalyserNode) native = true; return connect(...values); };
    source.start = (...values) => {
      if (native && source.buffer?.sampleRate === 24000 && !source.loop) {
        contexts.add(context); samples += source.buffer.length;
        if (samples <= 24000 * 45) {
          const scheduled = Number(values[0] ?? context.currentTime);
          row = { context, start: scheduled, end: scheduled + source.buffer.duration,
            wallStart: Date.now() + (scheduled - context.currentTime) * 1000,
            rms: 0, stopped: false, ended: false, pcm: Array.from(source.buffer.getChannelData(0)) };
          let power = 0; for (const value of row.pcm) power += value * value;
          row.rms = Math.sqrt(power / row.pcm.length); sources.push(row);
          source.addEventListener('ended', () => { row.ended = true; });
        }
      }
      return start(...values);
    };
    source.stop = (...values) => {
      if (row && !row.stopped) {
        const now = context.currentTime;
        stops.push({ at: Date.now(), audible: row.rms > .008 && now >= row.start && now < row.end });
        row.end = Math.min(row.end, now); row.stopped = true;
      }
      return stop(...values);
    };
    return source;
  };
  window.__nativeAudition = {
    summary: () => ({ micCalls, modules, tracks: tracks.size, liveTracks: [...tracks].filter(track => track.readyState === 'live').length,
      nativeContexts: contexts.size, openNativeContexts: [...contexts].filter(context => context.state !== 'closed').length,
      scheduledSources: sources.length, liveSources: sources.filter(row => !row.ended && !row.stopped && row.context.state !== 'closed').length,
      audibleSources: sources.filter(row => row.rms > .008).length,
      audibleWindows: sources.filter(row => row.rms > .008 && row.end > row.start).map(row => ({ from: row.wallStart, to: row.wallStart + (row.end - row.start) * 1000 })), stops }),
    recording: () => sources.map(row => ({ start: row.start, end: row.end, pcm: row.pcm })),
  };
}

export function scheduledRecording(rows) {
  if (!Array.isArray(rows) || rows.length > 3000) fail('recording_limit');
  const origin = rows.length ? Math.min(...rows.map(row => row.start)) : 0;
  const end = Math.min(45, Math.max(0, ...rows.map(row => row.end - origin)));
  const values = new Float32Array(Math.ceil(end * RATE));
  for (const row of rows) {
    if (!Number.isFinite(row.start) || !Number.isFinite(row.end) || !Array.isArray(row.pcm) || row.pcm.length > 11520) fail('invalid_recording');
    const begin = Math.max(0, Math.round((row.start - origin) * RATE));
    const count = Math.min(row.pcm.length, Math.max(0, Math.floor((row.end - row.start) * RATE)), values.length - begin);
    for (let i = 0; i < count; i++) { if (!Number.isFinite(row.pcm[i])) fail('invalid_recording'); values[begin + i] += row.pcm[i]; }
  }
  const result = Buffer.alloc(values.length * 2);
  for (let i = 0; i < values.length; i++) result.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(values[i] * 32768))), i * 2);
  return result;
}

export function plan(url = undefined) {
  loopbackUrl(url);
  return { status: 'prepared_not_executed', experiment: 'native_game_browser_audition', durationLimitSeconds: LIMIT_MS / 1000,
    source: 'Pinned public NVIDIA Hi and rice-question excerpts plus silence', microphone: 'Edge fake file device only',
    nativeProvider: 'personaplex-pcm-v1', calls: 'One admitted stream; no retries, bank requests or provider substitutes',
    evidence: 'Real Game, AudioWorklet, PCM clock, interruption ACK, native playback, mute zeros and resource teardown',
    scope: 'General conversation only. No bank narration or tool qualification.' };
}

export async function execute(urlValue) {
  const url = loopbackUrl(urlValue), directory = path.join(ROOT, '.local/personaplex-browser', new Date().toISOString().replace(/[:.]/g, '-'));
  const source = await readFile(path.join(SOURCE, 'input.wav'));
  if (createHash('sha256').update(source).digest('hex') !== INPUT_SHA256) fail('unqualified_public_audio');
  const sourceReport = JSON.parse(await readFile(path.join(SOURCE, 'report.json'), 'utf8'));
  const fixture = publicFixture(parseWav(source), sourceReport);
  await mkdir(directory, { recursive: true }); const fixturePath = path.join(directory, 'public-microphone.wav'); await writeFile(fixturePath, wav(fixture));
  const { chromium } = await import('@playwright/test');
  const wire = new WireObservation(), started = Date.now();
  let browser, context, page, action = '', failure = '', socketCount = 0, admissionCount = 0, prohibitedRequests = 0, observationError = '';
  let audioSummary = {}, recording = Buffer.alloc(0), connected = false, muteStart, muteEnd, cleaned = false;
  const ms = () => Date.now() - started;
  // Reserve the final three seconds for unconditional native/browser teardown.
  const watchdog = setTimeout(() => { failure ||= 'audition_deadline'; void browser?.close().catch(() => {}); }, LIMIT_MS - 3000);
  const check = () => { if (failure || observationError) fail(failure || observationError); };
  const wait = async (predicate, budget, code) => {
    const until = Math.min(started + LIMIT_MS - 4000, Date.now() + budget);
    while (Date.now() < until) { check(); if (await predicate()) return; await new Promise(resolve => setTimeout(resolve, 100)); }
    fail(code);
  };
  try {
    browser = await chromium.launch({ channel: 'msedge', headless: true, timeout: 8000, args: [
      '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', `--use-file-for-fake-audio-capture=${fixturePath}`] });
    context = await browser.newContext({ viewport: { width: 1440, height: 900 }, permissions: ['microphone'] });
    await context.addInitScript(observeNativeAudio); page = await context.newPage(); page.setDefaultTimeout(5000);
    page.on('request', request => {
      const pathname = new URL(request.url()).pathname;
      if (pathname === '/api/avatar/personaplex-session') admissionCount++;
      if (pathname.startsWith('/savia/') || pathname === '/api/avatar/task' || ['/api/avatar/transcribe', '/api/avatar/conversation', '/api/avatar/speech', '/api/avatar/gemini-token', '/api/avatar/session'].includes(pathname)) prohibitedRequests++;
    });
    page.on('websocket', socket => {
      if (new URL(socket.url()).pathname !== '/api/avatar/personaplex') return;
      socketCount++;
      socket.on('framesent', event => { try { wire.sent(event.payload, ms(), action); } catch (error) { observationError ||= error.code || 'wire_observation_failed'; } });
      socket.on('framereceived', event => { try { wire.received(event.payload, ms()); } catch (error) { observationError ||= error.code || 'wire_observation_failed'; } });
      socket.on('close', () => { wire.closed = true; });
    });
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 8000 });
    const config = await page.evaluate(async () => { const response = await fetch('/api/avatar/config'); const body = await response.json(); return { provider: body.voiceProvider, available: body.voiceAvailable, backend: body.backendAvailable }; });
    if (config.provider !== 'personaplex' || !config.available || config.backend) fail('isolated_native_provider_not_ready');
    await page.getByRole('button', { name: 'Wake the world', exact: true }).click();
    await wait(() => wire.ready, 15000, 'native_readiness_missing'); connected = true;
    await wait(() => page.getByRole('button', { name: 'Pause story', exact: true }).count(), 16000, 'real_user_utterance_missing');
    // Wait through both public speech bursts. No synthetic interrupt is substituted for VAD evidence.
    await wait(async () => {
      const stats = await page.evaluate(() => window.__nativeAudition.summary());
      return wire.interrupts.some(row => !row.action && row.ackMs !== undefined && stats.stops.some(stop => stop.audible && Math.abs(stop.at - (started + row.sentMs)) < 200));
    }, 16000, 'audible_vad_barge_in_not_observed');
    // A new scheduled audible source proves the held stream resumed after real input quieted.
    const before = await page.evaluate(() => window.__nativeAudition.summary().audibleSources);
    await wait(async () => (await page.evaluate(() => window.__nativeAudition.summary().audibleSources)) > before, 10000, 'native_playback_resume_missing');
    action = 'manual_pause'; await page.getByRole('button', { name: 'Pause story', exact: true }).click();
    action = 'mute'; await page.getByRole('button', { name: 'Mute microphone', exact: true }).click(); muteStart = ms(); wire.mute = muteStart;
    await wait(() => wire.mutedSamples >= RATE * 1.5, 3000, 'mute_clock_missing');
    if (wire.mutedNonzero) fail('mute_contains_microphone_audio');
    await page.getByRole('button', { name: 'Unmute microphone', exact: true }).click(); muteEnd = ms(); wire.mute = undefined;
    action = 'teardown'; await page.getByRole('button', { name: 'End voice', exact: true }).click();
    await wait(async () => { const stats = await page.evaluate(() => window.__nativeAudition.summary()); return wire.closed && stats.liveTracks === 0 && stats.openNativeContexts === 0 && stats.liveSources === 0; }, 2000, 'native_cleanup_missing');
    cleaned = true;
    audioSummary = await page.evaluate(() => window.__nativeAudition.summary());
    recording = scheduledRecording(await page.evaluate(() => window.__nativeAudition.recording()));
    if (socketCount !== 1 || admissionCount !== 1 || audioSummary.micCalls !== 1 || audioSummary.modules !== 1 || prohibitedRequests || !wire.outputPackets || !audioSummary.audibleSources || wire.pending.size) fail('native_scope_or_evidence_failed');
    await page.getByRole('button', { name: 'Return to the world', exact: true }).click();
    await page.screenshot({ path: path.join(directory, 'world.png'), timeout: 1000 });
  } catch (error) { failure ||= error?.code || 'browser_audition_failed'; }
  finally {
    // Close the page even when the native app failed, which triggers the real hook's effect cleanup.
    if (page && !page.isClosed()) {
      try {
        action = 'teardown';
        const end = page.getByRole('button', { name: 'End voice', exact: true });
        if (!await end.count()) {
          const pause = page.getByRole('button', { name: 'Pause story', exact: true });
          if (await pause.count()) await pause.click({ timeout: 500 });
        }
        if (await end.count()) await end.click({ timeout: 500 });
        await new Promise(resolve => setTimeout(resolve, 100));
        audioSummary = await page.evaluate(() => window.__nativeAudition?.summary() || {});
        cleaned ||= wire.closed && audioSummary.liveTracks === 0 && audioSummary.openNativeContexts === 0 && audioSummary.liveSources === 0;
        if (!recording.length) recording = scheduledRecording(await page.evaluate(() => window.__nativeAudition?.recording() || []));
      } catch { /* Best effort; context closure is unconditional. */ }
    }
    const close = async () => { await context?.close().catch(() => {}); await browser?.close().catch(() => {}); };
    let closeTimer;
    await Promise.race([close(), new Promise(resolve => { closeTimer = setTimeout(resolve, Math.max(1, started + LIMIT_MS - Date.now())); })]);
    clearTimeout(closeTimer);
    clearTimeout(watchdog);
  }
  const browserClosed = !browser?.isConnected();
  if (!browserClosed) failure ||= 'browser_cleanup_missing';
  const bargeIns = wire.interrupts.filter(row => !row.action && row.ackMs !== undefined && audioSummary.stops?.some(stop => stop.audible && Math.abs(stop.at - (started + row.sentMs)) < 200)).length;
  const audibleWindows = [];
  for (const window of audioSummary.audibleWindows || []) {
    const from = Math.round(window.from - started), to = Math.round(window.to - started);
    const previous = audibleWindows.at(-1);
    if (previous && from <= previous.toMs + 80) previous.toMs = Math.max(previous.toMs, to);
    else audibleWindows.push({ fromMs: from, toMs: to });
  }
  const report = { status: failure ? 'failed' : 'completed', experiment: 'native_game_browser_audition', failure: failure || undefined,
    elapsedMs: ms(), maximumSeconds: LIMIT_MS / 1000, protocol: 'personaplex-pcm-v1', sourceRevision: SOURCE_REVISION, modelRevision: MODEL_REVISION,
    syntheticPublicMic: true, bankRequests: prohibitedRequests, sockets: socketCount, admissions: admissionCount, connected,
    readyMs: wire.readyMs, firstOutputMs: wire.firstOutput, inputPackets: wire.inputPackets, inputSamples: wire.inputSamples,
    outputPackets: wire.outputPackets, outputSamples: wire.outputSamples, clockErrors: wire.clockErrors, audibleVadBargeIns: bargeIns,
    fixture: { durationSeconds: fixture.length / (RATE * 2), repeatedPublicHiAtSeconds: 16, repeatSeconds: .8 },
    interruptions: wire.interrupts.map(row => ({ action: row.action || 'microphone_vad', sentMs: row.sentMs, ackLatencyMs: row.ackLatencyMs, generation: row.nextGeneration })),
    mute: { startMs: muteStart, endMs: muteEnd, packets: wire.mutedPackets, samples: wire.mutedSamples, nonzeroSamples: wire.mutedNonzero },
    audio: { ...audioSummary, stops: undefined, audibleWindows: undefined, scheduledAudibleWindows: audibleWindows }, cleanupProvedInPage: cleaned, browserClosed,
    recordings: { wire: 'native-wire-output.wav includes every received PCM packet, including held audio', playback: 'native-scheduled-output.wav contains actually scheduled decoded buffers, trimmed at stop; not a hardware loopback recording' },
    limits: 'General voice conversation only; no bank tools, names, truthfulness or forced result speech qualification.' };
  await writeFile(path.join(directory, 'report.json'), JSON.stringify(report, null, 2) + '\n');
  await writeFile(path.join(directory, 'native-wire-output.wav'), wav(Buffer.concat(wire.records)));
  await writeFile(path.join(directory, 'native-scheduled-output.wav'), wav(recording));
  // Only our fixed redacted report and a local path are printed. No browser/provider exception, URL, ticket, text or credential.
  process.stdout.write(JSON.stringify({ ...report, outputDirectory: directory }, null, 2) + '\n');
  if (failure) process.exitCode = 1;
  return report;
}

async function main() {
  const args = process.argv.slice(2); let executeFlag = false, url;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--execute') executeFlag = true;
    else if (args[i] === '--plan') { /* Default. */ }
    else if (args[i] === '--url' && args[i + 1]) url = args[++i];
    else fail('invalid_arguments');
  }
  if (executeFlag) await execute(url); else process.stdout.write(JSON.stringify(plan(url), null, 2) + '\n');
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => { process.stderr.write(JSON.stringify({ status: 'failed', failure: error?.code || 'browser_audition_failed' }) + '\n'); process.exitCode = 1; });
}
