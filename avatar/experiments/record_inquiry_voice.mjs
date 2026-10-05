import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium, expect } from '@playwright/test';
import { captureReleaseAudio } from './capture_release_audio.mjs';

if (!process.argv.includes('--execute')) throw Error('Pass --execute for one actual informational inquiry team and native voice capture.');
const root = path.resolve(new URL('../..', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const requested = process.argv[process.argv.indexOf('--output-dir') + 1];
if (!process.argv.includes('--output-dir') || !requested) throw Error('A fresh private output directory is required.');
const dir = path.resolve(root, requested);
if (!dir.startsWith(path.join(root, 'private') + path.sep)) throw Error('Output must stay in private.');
await fs.mkdir(dir, { recursive: false });
await fs.writeFile(path.join(dir, 'started.json'), JSON.stringify({ at: new Date().toISOString(), max_case_creations: 1 }), { flag: 'wx' });
const base = 'http://127.0.0.1:43941', start = performance.now(), events = [], counts = {};
const record = (type, data = {}) => events.push({ at_ms: Math.round(performance.now() - start), type, ...data });
const routeOf = request => new URL(request.url()).pathname;
const hostUpdates = new Map(), taskUpdates = new Map(), turnUpdates = new Map();
const tasks = [];
let browser, context, page, video, finishAudio, audioReport, completedTeam = null, heardTeam = null, failed = null;
try {
  const binding = JSON.parse(await fs.readFile(path.join(root, 'private/rc-runtime-20261004/measurement.json'), 'utf8'));
  if (binding.generated_only !== true || binding.runtime?.real_bank_actions !== false) throw Error('Fictional runtime required.');
  const pcm = Buffer.alloc(48000 * 90 * 2), h = Buffer.alloc(44);
  h.write('RIFF'); h.writeUInt32LE(pcm.length + 36, 4); h.write('WAVEfmt ', 8);
  h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20); h.writeUInt16LE(1, 22); h.writeUInt32LE(48000, 24);
  h.writeUInt32LE(96000, 28); h.writeUInt16LE(2, 32); h.writeUInt16LE(16, 34); h.write('data', 36); h.writeUInt32LE(pcm.length, 40);
  const mic = path.join(dir, 'silent-microphone.wav'); await fs.writeFile(mic, Buffer.concat([h, pcm]), { flag: 'wx' });
  browser = await chromium.launch({ channel: 'msedge', headless: true, args: ['--use-fake-device-for-media-stream', `--use-file-for-fake-audio-capture=${mic}`] });
  context = await browser.newContext({ viewport: { width: 1440, height: 900 }, recordVideo: { dir, size: { width: 1440, height: 900 } } });
  await context.grantPermissions(['microphone'], { origin: base });
  const config = await context.request.get(base + '/api/avatar/config');
  if (!config.ok() || (await config.json()).voiceProvider !== 'openrouter-native') throw Error('Native provider unavailable.');
  const login = await context.request.post(base + '/savia/api/auth/login', { headers: { Origin: base }, data: { profile: binding.profile, code: binding.code } });
  if (!login.ok()) throw Error('Fictional login failed.');
  const preflight = await context.request.get(base + '/savia/api/assistant/cases?language=es');
  if (!preflight.ok()) throw Error('Inquiry API unavailable.');
  // Login and all secrets precede the recorded page. No model/bank input is logged.
  page = await context.newPage(); video = page.video();
  await page.exposeFunction('inquiryVoiceMilestone', item => {
    if (typeof item?.event === 'string' && item.event !== 'voice-audio') record('browser_voice_milestone', { event: item.event });
  });
  await page.addInitScript(() => window.addEventListener('savia:voice-milestone', event => void window.inquiryVoiceMilestone({ event: event.detail?.event })));
  page.on('request', request => {
    const route = routeOf(request);
    if (request.method() === 'POST' && ['/api/avatar/native-turn', '/api/avatar/native-result', '/savia/api/assistant/cases', '/savia/api/chat', '/savia/api/chat/messages'].includes(route)) {
      counts[route] = (counts[route] ?? 0) + 1; record('request', { route, ordinal: counts[route] });
      if (route.endsWith('/native-result')) {
        const update = taskUpdates.get(request.postDataJSON()?.taskId);
        if (update) record('team_voice_started', { state: update.state, event_id: update.event_id });
      }
    }
  });
  page.on('response', response => {
    tasks.push((async () => {
      const request = response.request(), route = routeOf(request);
      if (!response.ok()) { if (route.startsWith('/savia/api/') || route.startsWith('/api/avatar/')) record('http_failure', { route, status: response.status() }); return; }
      if (route === '/savia/api/assistant/voice-update' && response.status() === 200) {
        const body = await response.json();
        hostUpdates.set(body.reply, { state: body.inquiry_state, event_id: body.event_id });
        record('verified_host_update', { state: body.inquiry_state, event_id: body.event_id, bank_authority: body.bank_authority });
      } else if (route === '/api/avatar/native-result-receipt') {
        const body = await response.json(), update = hostUpdates.get(request.postDataJSON()?.reply);
        if (update) { taskUpdates.set(body.taskId, update); record('owned_receipt', { state: update.state, event_id: update.event_id, status: response.status() }); }
      } else if (route === '/api/avatar/native-result') {
        const update = taskUpdates.get(request.postDataJSON()?.taskId);
        const lines = (await response.body()).toString('utf8').trim().split('\n').map(line => JSON.parse(line));
        if (update && lines[0]?.type === 'start') turnUpdates.set(lines[0].turnId, update);
      } else if (route === '/api/avatar/native-played' && request.postDataJSON()?.complete === true) {
        const update = turnUpdates.get(request.postDataJSON()?.turnId);
        record('completed_playback_ack', { status: response.status(), state: update?.state ?? 'foreground' });
        if (update?.state === 'team_completed') heardTeam = { ...update, at_ms: Math.round(performance.now() - start) };
      } else if (route === '/savia/api/assistant/cases') {
        const body = await response.json();
        const item = body.items?.find(item => item.state === 'team_completed');
        if (item && item.workers?.filter(worker => worker.state === 'completed').length === 2) {
          completedTeam = { state: item.state, completed_workers: 2, suggestions: item.workers.map(worker => worker.suggestion), next_check_at: item.next_check_at, events: item.events.map(event => ({ kind: event.kind, at: event.at, role: event.role ?? null })) };
          record('actual_team_completed', { completed_workers: 2 });
        }
      }
    })().catch(() => record('response_capture_incomplete', { route: routeOf(response.request()) })));
  });
  finishAudio = await captureReleaseAudio(page, dir);
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'Despertar el mundo' }).click();
  await expect(page.getByRole('status')).toHaveText('Te escucho', { timeout: 20000 });
  await page.keyboard.press('t');
  await page.getByLabel('Escribe a tu compañero').fill('Estoy inquieto, hablemos con calma.');
  await page.getByRole('button', { name: 'Enviar mensaje', exact: true }).click();
  await page.getByRole('button', { name: 'Mirar el estanque' }).click();
  const frame = page.frameLocator('iframe');
  await frame.getByRole('button', { name: 'Movimientos', exact: true }).click();
  await frame.locator('.transaction-row').filter({ hasText: 'Nébula Market' }).first().click();
  await frame.getByRole('button', { name: 'Revisar este cargo', exact: true }).click();
  await expect(frame.getByText('Ayuda con tu consulta', { exact: true })).toBeVisible();
  const input = frame.getByLabel('¿Qué necesitas aclarar?');
  if (!await input.isVisible()) await frame.getByText('Pedir ayuda a un equipo', { exact: true }).click();
  await input.fill('Ayúdame a comparar este comercio con mis recibos y a preparar el próximo paso mientras espero.');
  await frame.getByRole('button', { name: 'Enviar consulta', exact: true }).click();
  record('inquiry_submitted');
  const deadline = Date.now() + 120000;
  while (Date.now() < deadline && !heardTeam) await page.waitForTimeout(100);
  if (!heardTeam || !completedTeam) throw Error('Actual completed team playback not qualified.');
  if (counts['/savia/api/assistant/cases'] !== 1 || counts['/savia/api/chat'] || counts['/savia/api/chat/messages']) throw Error('Unexpected repeated inquiry or banking query.');
  await page.screenshot({ path: path.join(dir, 'team-voice-complete.png') });
  record('capture_complete', { one_inquiry_created: true, useful_team_update_heard: true });
} catch (error) {
  failed = error; record('capture_failed', { reason: 'joined_capture_incomplete' });
  if (page && !page.isClosed()) await page.screenshot({ path: path.join(dir, 'failure.png') }).catch(() => {});
} finally {
  if (finishAudio) audioReport = await finishAudio();
  await Promise.allSettled(tasks);
  if (page && !page.isClosed()) await page.close();
  if (video) await video.saveAs(path.join(dir, 'team-voice.webm'));
  if (context) await context.close(); if (browser) await browser.close();
  await fs.writeFile(path.join(dir, 'receipt.json'), JSON.stringify({ schema: 'savia-actual-team-voice/v1', at: new Date().toISOString(), status: failed ? 'failed' : 'complete',
    fictional: true, actual_native_provider: 'OpenRouter / openai/gpt-audio', actual_team_provider: 'direct OpenRouter / google/gemini-3.1-flash-lite',
    typed_input: true, file_backed_silent_microphone: true, physical_microphone_qualified: false, bank_authority: false, bank_resolution: false, counts,
    completed_team: completedTeam, heard_team: heardTeam, events, audio: audioReport,
  }, null, 2) + '\n', { flag: 'wx' });
}
if (failed) { console.error('Joined actual team voice capture incomplete; inspect its private receipt.'); process.exitCode = 1; }
else console.log('Actual useful inquiry-team voice update completed once with a played receipt.');
