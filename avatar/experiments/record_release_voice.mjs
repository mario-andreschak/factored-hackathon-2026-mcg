import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium, expect } from '@playwright/test';
import { captureReleaseAudio } from './capture_release_audio.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const appUrl = 'http://127.0.0.1:43941';
const portalUrl = 'http://127.0.0.1:43900';
const runtimePath = path.join(root, 'private/rc-runtime-20261004/measurement.json');
const args = process.argv.slice(2);
const valueOf = (flag, fallback) => {
  const index = args.indexOf(flag);
  if (index < 0) return fallback;
  const value = args[index + 1];
  if (!value || value.startsWith('--')) throw new Error(`missing_${flag.slice(2).replaceAll('-', '_')}`);
  return value;
};
const safeCode = error => typeof error?.code === 'string' && /^[a-z0-9_-]{1,50}$/i.test(error.code)
  ? error.code : 'capture_failed';
const usage = 'Usage: node avatar/experiments/record_release_voice.mjs --execute --output-dir private/<new-directory>';

if (!args.includes('--execute')) {
  console.log(usage);
  process.exit(0);
}

let outputDir;
try {
  const requestedOutput = valueOf('--output-dir');
  if (!requestedOutput) throw new Error('output_dir_required');
  outputDir = path.resolve(root, requestedOutput);
  const privateRoot = path.join(root, 'private') + path.sep;
  if (!outputDir.startsWith(privateRoot)) throw new Error('output_must_be_private');
  await mkdir(outputDir, { recursive: false });
} catch (error) {
  console.error(`Recorder stopped: ${safeCode(error)}. ${usage}`);
  process.exit(2);
}

const events = [];
const startedAt = performance.now();
const record = (type, details = {}) => events.push({
  at_ms: Math.round(performance.now() - startedAt), type, ...details,
});
const pathCounts = new Map();
const playedRequests = new WeakMap();
let bankPending = false;
let bankPostStartedAt = null;
let foregroundAudioStartedDuringRead = false;
let foregroundPlayedDuringRead = false;
let nativeResultStartedAt = null;
let nativeResultPlayed = false;
let audioFinalizer;
let context;
let browser;
let page;
let video;
let failure;

function requestPath(request) {
  try { return new URL(request.url()).pathname; } catch { return ''; }
}
function count(pathname) {
  const next = (pathCounts.get(pathname) ?? 0) + 1;
  pathCounts.set(pathname, next);
  return next;
}
const isRead = request => ['/savia/api/chat', '/savia/api/chat/messages'].includes(requestPath(request)) && request.method() === 'POST';
function watchTraffic(target) {
  target.on('request', request => {
    const pathname = requestPath(request);
    const method = request.method();
    if (isRead(request)) {
      bankPending = true;
      bankPostStartedAt = performance.now();
      record('savia_read_started', { ordinal: count(pathname) });
    } else if (['/api/avatar/native-turn', '/api/avatar/native-result'].includes(pathname) && method === 'POST') {
      const ordinal = count(pathname);
      if (pathname.endsWith('/native-result')) nativeResultStartedAt = performance.now();
      record(pathname.endsWith('/native-result') ? 'native_result_started' : 'native_turn_started', { ordinal });
    } else if (pathname.endsWith('/native-played') && method === 'POST') {
      let complete = false;
      try { complete = request.postDataJSON()?.complete === true; } catch { /* Only a completion boolean is retained. */ }
      playedRequests.set(request, { complete, duringRead: bankPending, resultStart: nativeResultStartedAt });
    }
  });
  target.on('response', response => {
    const pathname = requestPath(response.request());
    if (pathname.startsWith('/savia/api/') || pathname.startsWith('/api/avatar/'))
      record('http_response', { path: pathname, http_status: response.status() });
    const played = playedRequests.get(response.request());
    if (pathname.endsWith('/native-played') && response.ok() && played?.complete) {
      if (played.duringRead) foregroundPlayedDuringRead = true;
      if (!nativeResultPlayed && played.resultStart !== null) {
        nativeResultPlayed = true;
        record('native_result_played_once', { duringRead: played.duringRead, http_status: response.status(), after_result_start_ms: Math.round(performance.now() - played.resultStart) });
      } else record('native_output_played', { duringRead: played.duringRead, http_status: response.status() });
    }
    if (isRead(response.request())) {
      bankPending = false;
      record('savia_read_finished', {
        http_status: response.status(),
        latency_ms: bankPostStartedAt === null ? null : Math.round(performance.now() - bankPostStartedAt),
      });
    } else if (['/api/avatar/native-turn', '/api/avatar/native-result'].includes(pathname)) {
      record(pathname.endsWith('/native-result') ? 'native_result_response' : 'native_turn_response', { http_status: response.status() });
    }
  });
}

async function saveEvents(status) {
  const report = {
    schema: 'savia-release-voice-recording/v1',
    status,
    generated_only_runtime: true,
    input: { kind: 'file-backed-silent-microphone', sample_rate_hz: 48000, bits_per_sample: 16, physical_microphone_qualified: false },
    counts: Object.fromEntries(pathCounts),
    overlap: {
      foreground_native_audio_started_during_savia_read: foregroundAudioStartedDuringRead,
      foreground_playback_completed_during_savia_read: foregroundPlayedDuringRead,
    },
    events,
  };
  await writeFile(path.join(outputDir, 'events.json'), `${JSON.stringify(report, null, 2)}\n`, { flag: 'wx', mode: 0o600 });
}

try {
  const runtimeConfig = JSON.parse(await readFile(runtimePath, 'utf8'));
  if (runtimeConfig.generated_only !== true || runtimeConfig.runtime?.real_bank_actions !== false ||
      typeof runtimeConfig.profile !== 'string' || typeof runtimeConfig.code !== 'string' || !runtimeConfig.code) {
    throw Object.assign(new Error('unsafe_runtime_config'), { code: 'unsafe_runtime_config' });
  }

  const sampleRate = 48000;
  const durationSeconds = 45;
  const pcm = Buffer.alloc(sampleRate * durationSeconds * 2);
  const header = Buffer.alloc(44);
  header.write('RIFF'); header.writeUInt32LE(pcm.length + 36, 4); header.write('WAVEfmt ', 8);
  header.writeUInt32LE(16, 16); header.writeUInt16LE(1, 20); header.writeUInt16LE(1, 22);
  header.writeUInt32LE(sampleRate, 24); header.writeUInt32LE(sampleRate * 2, 28);
  header.writeUInt16LE(2, 32); header.writeUInt16LE(16, 34); header.write('data', 36); header.writeUInt32LE(pcm.length, 40);
  await writeFile(path.join(outputDir, 'microphone-silence-48k.wav'), Buffer.concat([header, pcm]), { flag: 'wx', mode: 0o600 });

  browser = await chromium.launch({ channel: 'msedge', headless: true, args: [
    '--use-fake-device-for-media-stream',
    `--use-file-for-fake-audio-capture=${path.join(outputDir, 'microphone-silence-48k.wav')}`,
  ] });
  context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    recordVideo: { dir: outputDir, size: { width: 1440, height: 900 } },
  });
  await context.grantPermissions(['microphone'], { origin: appUrl });

  // Establish the application session, then sign the fictional account in via
  // the fixed Savia login endpoint. The profile and code stay in memory only.
  const configResponse = await context.request.get(`${appUrl}/api/avatar/config`, { timeout: 10000 });
  const config = configResponse.ok() ? await configResponse.json() : {};
  if (!configResponse.ok() || config.voiceProvider !== 'openrouter-native' || config.voiceAvailable !== true ||
      config.backgroundAsrAvailable !== true || config.nativeReadBridgeAvailable !== true || config.backendAvailable !== true) {
    throw Object.assign(new Error('release_voice_config_unavailable'), { code: 'release_voice_config_unavailable' });
  }
  record('avatar_config_ready', { http_status: configResponse.status(), provider: 'openrouter-native' });
  const loginResponse = await context.request.post(`${appUrl}/savia/api/auth/login`, {
    headers: { Origin: appUrl },
    data: { profile: runtimeConfig.profile, code: runtimeConfig.code }, timeout: 15000,
  });
  record('fictional_login', { http_status: loginResponse.status() });
  if (!loginResponse.ok()) throw Object.assign(new Error('fictional_login_failed'), { code: 'fictional_login_failed' });
  const sessionResponse = await context.request.get(`${appUrl}/savia/api/auth/me`, { timeout: 10000 });
  let authenticated = false;
  try { authenticated = (await sessionResponse.json()).authenticated === true; } catch { /* Status is recorded without the body. */ }
  if (!sessionResponse.ok() || !authenticated) throw Object.assign(new Error('fictional_session_unverified'), { code: 'fictional_session_unverified' });
  record('fictional_session_verified', { http_status: sessionResponse.status() });

  page = await context.newPage();
  await page.exposeFunction('recordVoiceMilestone', milestone => {
    if (!milestone || typeof milestone.event !== 'string') return;
    if (milestone.event === 'voice-audio' && bankPending) foregroundAudioStartedDuringRead = true;
    // Keep timing milestones only; no utterance or account data enters this log.
    if (milestone.event !== 'voice-audio' || bankPending) record('browser_voice_milestone', { event: milestone.event, during_read: bankPending });
  });
  await page.addInitScript(() => window.addEventListener('savia:voice-milestone', event => {
    void window.recordVoiceMilestone({ event: event.detail?.event });
  }));
  video = page.video();
  watchTraffic(page);
  audioFinalizer = await captureReleaseAudio(page, outputDir);
  await page.goto(appUrl, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.audio-provider-notice')).toContainText('OpenRouter / OpenAI', { timeout: 15000 });
  await page.getByRole('button', { name: 'Despertar el mundo' }).click();
  await expect(page.getByRole('status')).toHaveText('Te escucho', { timeout: 20000 });
  record('native_voice_ready', { physical_microphone_qualified: false });

  let resolveReadRequest;
  let resolveReadResponse;
  const readRequest = new Promise(resolve => { resolveReadRequest = resolve; });
  const readResponse = new Promise(resolve => { resolveReadResponse = resolve; });
  const requestListener = request => {
    if (isRead(request)) resolveReadRequest(request);
  };
  const responseListener = response => {
    if (isRead(response.request())) resolveReadResponse(response);
  };
  page.on('request', requestListener);
  page.on('response', responseListener);

  const readPrompt = 'Consulta mis pagos recientes.';
  await page.keyboard.press('t');
  await page.getByLabel('Escribe a tu compañero').fill(readPrompt);
  await page.getByRole('button', { name: 'Enviar mensaje', exact: true }).click();
  await Promise.race([readRequest, page.waitForTimeout(60000).then(() => { throw Object.assign(new Error('read_request_not_admitted'), {code:'read_request_not_admitted'}); })]);
  record('read_request_seen');

  // Continue with a non-banking question while the one Savia read is pending.
  // If it has already returned, the event log preserves that fact instead of
  // adding delay or retrying the account request.
  await page.getByRole('button', { name: 'Pausar la historia' }).click();
  await page.getByRole('button', { name: 'Usar el teclado' }).click();
  const foregroundPrompt = 'Mientras revisas, ¿qué información debo guardar?';
  await page.getByLabel('Escribe a tu compañero').fill(foregroundPrompt);
  await page.getByRole('button', { name: 'Enviar mensaje', exact: true }).click();
  record('foreground_prompt_submitted', { savia_read_was_pending_after_submit: bankPending });
  const response = await Promise.race([readResponse, page.waitForTimeout(90000).then(() => { throw Object.assign(new Error('read_response_not_observed'), {code:'read_response_not_observed'}); })]);

  const deadline = Date.now() + 45000;
  while (Date.now() < deadline && !nativeResultPlayed) await page.waitForTimeout(100);
  if (!nativeResultPlayed) throw Object.assign(new Error('native_result_playback_not_confirmed'), { code: 'native_result_playback_not_confirmed' });
  if (['/savia/api/chat', '/savia/api/chat/messages'].reduce((sum, route) => sum + (pathCounts.get(route) ?? 0), 0) !== 1 || (pathCounts.get('/api/avatar/native-result') ?? 0) !== 1)
    throw Object.assign(new Error('unexpected_read_or_result_count'), { code: 'unexpected_read_or_result_count' });

  record('capture_complete', { one_savia_read: true, one_native_result: true });
} catch (error) {
  failure = error;
  record('capture_failed', { code: safeCode(error) });
  if (page && !page.isClosed()) {
    await page.screenshot({path:path.join(outputDir, 'failure.png')}).catch(() => {});
    record('visible_failure', {notice:await page.locator('.game-notice').allTextContents().catch(() => [])});
  }
} finally {
  try {
    if (audioFinalizer) await audioFinalizer();
    if (page && !page.isClosed()) await page.close();
    if (video) await video.saveAs(path.join(outputDir, 'release-voice.webm'));
    if (context) await context.close();
    if (browser) await browser.close();
    await saveEvents(failure ? 'failed' : 'complete');
  } catch (error) {
    failure ??= error;
    console.error(`Recorder finalization failed: ${safeCode(error)}`);
  }
}

if (failure) {
  console.error(`Recorder stopped with ${safeCode(failure)}; inspect the private output directory for the actual partial capture.`);
  process.exitCode = 1;
} else {
  console.log(`Voice capture completed in ${path.relative(root, outputDir)}.`);
}
