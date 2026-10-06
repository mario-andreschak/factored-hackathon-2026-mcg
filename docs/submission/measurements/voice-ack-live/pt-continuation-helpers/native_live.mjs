/** PREPARATION ONLY until an explicit root-approved immutable runtime binding.
 * No browser/network call occurs with --describe. Root may later run:
 * node savia-joined-native-live.mjs --execute PRIVATE_BINDING.json [FRESH_PRIVATE_CHILD]
 * Login credentials and storage state remain in memory in unrecorded contexts.
 * The two positive voice requests and their ACKs must originate in the product UI.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
import {performance} from 'node:perf_hooks';
import {captureBrowserCloneAudio} from './capture_savia_audio.mjs';
import {validateBinding} from './binding_gate.mjs';

const PRIVATE_BASE = 'C:/Users/Moe/.codex/tmp/savia-ack-pt-continuation-native-private-c44d416fcf1a';
const PLAYWRIGHT_PACKAGE = 'C:/Users/Moe/.codex/worktrees/savia-score-90/factored-hackathon-2026/frontend/package.json';
const SILENT_MIC = 'C:/Users/Moe/Documents/GitHub/factored-hackathon-2026/private/rc-deployed-acceptance-20261004/silent-microphone.wav';
const SILENT_SHA = 'fd967467076ec933370ff8a661819ee7b6390dc2d5975c71f1e2d3d72743400b';
const describe = {
  schema: 'savia-ack-pt-continuation-owned-card-guidance-native-live/v1', preparedOnly: true,
  executionGate: 'Fresh explicit root GO naming exact application source, image and verified served UI hashes',
  maximumDurationMs: 120000, maximumProviderEligibleResultRequests: 1,
  maximumNegativeTamperedResultRequests: 1, maximumUIFullPlaybackAcknowledgments: 1,
  cases: ['pt/colombia'], positiveVoiceInput: 'Actual typed-card-hint host reply registered by normal UI',
  cardEvidence: 'Existing owned blocked-card status and saved receipt, observed separately from guidance playback',
  prohibited: ['new block/prepare/confirm/cancel', 'inquiry creation/resolution', 'worker/model utterances',
    'ASR', 'microphone utterance input', 'analytics', 'fallback /voice/speak', 'injected positive reply or ACK'],
  input: 'Existing unchanged 90-second all-zero PCM16 mono 48k fake microphone fixture',
  output: 'Private WAV/NDJSON, private logged product responses, screenshots/video; no public publication',
  credentialRecording: false, persistedBrowserStorageState: false,
  physicalMicrophoneQualified: false, waveformTextAlignmentQualified: false,
  requiredBinding: {
    schema: 'savia-ack-pt-continuation-native-binding/v1',
    root_go: true, frozen_cohort_complete: true, generated_only: true, frozen_healthy: true, native_result_mode: 'native_exact',
    authorization: {approved_source_revision: '<40 hex>', approved_image_digest: 'sha256:<64 hex>'},
    runtime: {git_head: '<c44 exact 40 hex>', git_tree: '<fabf exact tree>', image_digest: '<same digest>',
      source_manifest_sha256: '<64 hex>', reverified_at_utc: '<UTC ISO date within 15 minutes>',
      served_ui: {'assets/index-<hash>.js': '<SHA256>', '<other files>': '<SHA256>'}},
    base_url: 'https://savia-rc-2026.fly.dev', code: '<private fictional login code>',
    gateway: {label: '<actual form label>', button: '<actual submit label>', code: '<private entry code>'},
    cases: [{language: 'pt', profile: 'colombia'}],
    expected_ui_runtime_sha256: '3d200c1f58957b3b3a032dbde642633e6c34eee70c7bee26734cdf0e1d137dd9',
    runtime_proof_path: '<fresh verified c44 runtime receipt>', runtime_proof_sha256: '<actual receipt SHA>',
    public_assets_proof_path: '<actual successful public guards>', public_assets_proof_sha256: '<actual receipt SHA>',
    native_harness_sha256: '<actual helper SHA>', capture_helper_sha256: '<actual passive capture SHA>',
    binding_gate_sha256: '<actual gate SHA>',
  },
};
const [mode, bindingPath, requestedOutput] = process.argv.slice(2);
if (mode === '--describe') console.log(JSON.stringify(describe, null, 2));
else if (mode === '--execute') await execute(bindingPath, requestedOutput);
else throw Error('Preparation uses --describe. Execution requires --execute and a new approved private binding.');

function sha(value) { return createHash('sha256').update(value).digest('hex'); }
function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(k => [k, stable(value[k])]));
  return value;
}
function hashObject(value) { return sha(JSON.stringify(stable(value))); }
function exactBlocked(result, reference) {
  return result?.state === 'card_block_verified' && result.product_reference === reference &&
    result.simulated === true && result.real_bank_action === false &&
    result.receipt?.schema === 'savia-simulated-card-block/v1' && result.receipt.status === 'blocked' &&
    result.receipt.simulated === true && result.receipt.real_bank_action === false;
}
function verifySilentWav(bytes) {
  if (sha(bytes) !== SILENT_SHA || bytes.toString('ascii', 0, 4) !== 'RIFF' || bytes.toString('ascii', 8, 12) !== 'WAVE')
    throw Error('The existing reviewed silent microphone fixture must remain unchanged.');
  let pcm, fmt;
  for (let off = 12; off + 8 <= bytes.length;) {
    const length = bytes.readUInt32LE(off + 4), kind = bytes.toString('ascii', off, off + 4);
    if (off + 8 + length > bytes.length) throw Error('Malformed existing silent fixture.');
    if (kind === 'fmt ') fmt = {codec: bytes.readUInt16LE(off + 8), channels: bytes.readUInt16LE(off + 10),
      rate: bytes.readUInt32LE(off + 12), bits: bytes.readUInt16LE(off + 22)};
    if (kind === 'data') pcm = bytes.subarray(off + 8, off + 8 + length);
    off += 8 + length + length % 2;
  }
  if (!pcm?.length || fmt?.codec !== 1 || fmt.channels !== 1 || fmt.rate !== 48000 || fmt.bits !== 16 ||
      pcm.some(b => b !== 0)) throw Error('Only unchanged all-zero mono PCM16 fake microphone input is permitted.');
}

async function execute(bindingPath, requestedOutput) {
  if (!bindingPath) throw Error('A newly approved private binding is required.');
  const {cfg} = await validateBinding(bindingPath);
  if (sha(await fs.readFile(new URL(import.meta.url))) !== cfg.native_harness_sha256 ||
      sha(await fs.readFile(new URL('./capture_savia_audio.mjs', import.meta.url))) !== cfg.capture_helper_sha256)
    throw Error('Approved successor harness/capture bytes changed.');
  const runtime = cfg.runtime, auth = cfg.authorization;
  if (cfg.root_go !== true || cfg.generated_only !== true || cfg.frozen_healthy !== true ||
      cfg.native_result_mode !== 'native_exact' || !/^[a-f0-9]{40}$/.test(runtime?.git_head || '') ||
      !/^sha256:[a-f0-9]{64}$/.test(runtime?.image_digest || '') ||
      !/^[a-f0-9]{64}$/.test(runtime?.source_manifest_sha256 || '') ||
      auth?.approved_source_revision !== runtime.git_head || auth?.approved_image_digest !== runtime.image_digest)
    throw Error('Execution is held until explicit root GO names the exact healthy native_exact source/image pin.');
  const verifiedTime = Date.parse(runtime.reverified_at_utc);
  if (!Number.isFinite(verifiedTime) || verifiedTime > Date.now() + 30000 || Date.now() - verifiedTime > 900000)
    throw Error('Root must reverify the runtime pin within 15 minutes before execution.');
  const origin = new URL(cfg.base_url).origin;
  if (cfg.base_url !== origin || origin !== 'https://savia-rc-2026.fly.dev' || !cfg.code || !runtime.served_ui ||
      !Object.keys(runtime.served_ui).some(x => /^assets\/index-.*\.js$/.test(x)))
    throw Error('Exact fictional RC origin, private form credentials and served UI hashes are required.');
  const specs = cfg.cases;
  if (!Array.isArray(specs) || specs.length < 1 || specs.length > 2 || specs.some(x =>
      !['es', 'pt'].includes(x.language) || !['mexico', 'colombia'].includes(x.profile)))
    throw Error('Only one or two approved ES/PT existing fictional customer cases are permitted.');
  const out = path.resolve(requestedOutput || path.join(PRIVATE_BASE, new Date().toISOString().replace(/[:.]/g, '-')));
  const base = path.resolve(PRIVATE_BASE), relative = path.relative(base, out);
  if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) throw Error('Output must be a fresh child of the designated private capture directory.');
  verifySilentWav(await fs.readFile(SILENT_MIC));
  await fs.mkdir(base, {recursive: true});
  await fs.mkdir(out, {recursive: false});
  const require = createRequire(PLAYWRIGHT_PACKAGE), playwright = require('playwright');
  const started = performance.now(), elapsed = () => Math.round(performance.now() - started);
  const report = {
    ...describe, preparedOnly: false, startedAt: new Date().toISOString(),
    runtime: {git_head: runtime.git_head, image_digest: runtime.image_digest,
      prior_es_attempt_sha256: cfg.prior_es_attempt_sha256,
      source_manifest_sha256: runtime.source_manifest_sha256, reverified_at_utc: runtime.reverified_at_utc,
      browser_source: runtime.browser_source, portal_source: runtime.portal_source,
      expected_ui_runtime_sha256: cfg.expected_ui_runtime_sha256},
    baseUrl: origin, harnessSha256: sha(await fs.readFile(new URL(import.meta.url))),
    observedProviderEligibleResultRequests: 0, observedNegativeResultRequests: 0,
    actualUIPlayedAcks: 0, cases: [], passed: false, unrecordedAuthObservations: [],
    qualificationLimits: ['Guidance playback and existing blocked-card receipt observations are separate facts.',
      'No new block/confirmation is performed or claimed to have been narrated.',
      'Browser emitted ACK follows the unchanged UI device-clock drain gate; physical hearing and waveform semantics remain unqualified.',
      'A strict transcript mismatch is reported as a failure, never relabeled canonical acceptance.',
      'No provider dollar-cost or broad production/fleet acceptance measurement.',
      'ACK failure recovery is covered by offline tests; this live workload injects no ACK error.',
      'PT-only continuation follows a separately preserved failed batch with successful ES case; original batch remains failed.'],
  };
  let browser, stopped = false, fatal = null;
  const fail = message => { fatal ||= message; };
  const ensure = () => { if (fatal) throw Error(fatal); if (stopped) throw Error('120-second capture budget ended.'); };
  const timer = setTimeout(() => { stopped = true; fail('Capture exceeded the total 120-second bound.'); void browser?.close().catch(() => {}); }, 120000);
  const waitUntil = async (test, milliseconds = 45000) => {
    const until = Math.min(performance.now() + milliseconds, started + 118000);
    while (!test()) { ensure(); if (performance.now() > until) throw Error('Bounded required observation expired.'); await new Promise(r => setTimeout(r, 50)); }
    ensure();
  };
  try {
    browser = await playwright.chromium.launch({headless: true, channel: 'msedge', timeout: 20000,
      args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
        `--use-file-for-fake-audio-capture=${SILENT_MIC}`]});
    for (const spec of specs) {
      ensure();
      const copy = spec.language === 'pt' ? {
        group: 'Escolha um perfil de demonstração', login: 'Entrar no meu banco',
        assistant: 'Assistente', title: 'Seu assistente Savia', start: 'Falar com a Savia', stop: 'Encerrar voz',
        message: 'Mensagem para o assistente', send: 'Enviar mensagem', typed: 'bloqueie meu cartão',
        cardLabel: 'Seu cartão', blocked: 'Bloqueado · estado verificado', caveat: 'Nenhum banco real será alterado.',
      } : {
        group: 'Elige un perfil de demostración', login: 'Entrar a mi banca',
        assistant: 'Asistente', title: 'Tu asistente Savia', start: 'Hablar con Savia', stop: 'Terminar voz',
        message: 'Mensaje para el asistente', send: 'Enviar mensaje', typed: 'bloquea mi tarjeta',
        cardLabel: 'Tu tarjeta', blocked: 'Bloqueada · estado verificado', caveat: 'No se modifica ningún banco real.',
      };
      let state;
      const entry = await browser.newContext({viewport: {width: 1360, height: 900}, locale: 'es-CO'});
      try {
        let loginPosts = 0, gatewayPosts = 0;
        await entry.route('**/*', async route => {
          const request = route.request(), url = new URL(request.url());
          if (url.origin !== origin) return route.abort();
          if (request.method() !== 'POST') return route.continue();
          if (url.pathname === '/_rc/enter' && ++gatewayPosts <= 1) return route.continue();
          if (url.pathname === '/api/auth/login' && ++loginPosts <= 1) return route.continue();
          fail('Unexpected write during unrecorded authentication.'); await route.abort();
        });
        const entryPage = await entry.newPage(); entryPage.setDefaultTimeout(30000);
        // Authentication stays unrecorded. Diagnostics contain route/status/timing only.
        entryPage.on('response', response => {
          const route = new URL(response.url()).pathname;
          if (['/', '/_rc/enter', '/api/auth/profiles', '/api/auth/login'].includes(route))
            report.unrecordedAuthObservations.push({profile: spec.profile, language: spec.language,
              path: route, method: response.request().method(), status: response.status(), atMs: elapsed()});
        });
        report.unrecordedAuthObservations.push({stage: 'profiles-response-wait-start', atMs: elapsed()});
        const profilesWait = entryPage.waitForResponse(r => new URL(r.url()).pathname === '/api/auth/profiles', {timeout: 30000});
        await entryPage.goto(origin, {waitUntil: 'domcontentloaded'});
        if (cfg.gateway && await entryPage.getByLabel(cfg.gateway.label, {exact: true}).count()) {
          await entryPage.getByLabel(cfg.gateway.label, {exact: true}).fill(cfg.gateway.code);
          await entryPage.getByRole('button', {name: cfg.gateway.button, exact: true}).click();
        }
        const profiles = await (await profilesWait).json(), profile = profiles.profiles?.find(p => p.id === spec.profile);
        report.unrecordedAuthObservations.push({stage: 'profiles-response-read', atMs: elapsed()});
        if (!profile) throw Error('Approved fictional profile is absent from the actual login form.');
        await entryPage.locator('.login-language select').selectOption(spec.language);
        await entryPage.getByRole('group', {name: copy.group, exact: true}).getByRole('button').filter({hasText: profile.alias}).click();
        await entryPage.locator('#login-code').fill(spec.code || cfg.code);
        report.unrecordedAuthObservations.push({stage: 'login-response-wait-start', atMs: elapsed()});
        const loginWait = entryPage.waitForResponse(r => new URL(r.url()).pathname === '/api/auth/login' && r.request().method() === 'POST', {timeout: 30000});
        await entryPage.getByRole('button', {name: copy.login, exact: true}).click();
        if ((await loginWait).status() !== 200) throw Error('Actual unrecorded customer form login failed.');
        report.unrecordedAuthObservations.push({stage: 'login-response-accepted', atMs: elapsed()});
        state = await entry.storageState(); // Kept in memory; never written to disk.
      } finally { await entry.close(); }
      const caseOut = path.join(out, spec.language); await fs.mkdir(caseOut);
      const item = {language: spec.language, fictionalProfile: spec.profile, typedMessage: copy.typed,
        events: [], servedAssets: [], optionalBackgroundVoiceRequestsBlocked: 0,
        uiGuidancePlayback: {}, existingCardProtection: {}, passed: false};
      report.cases.push(item);
      const pending = [], turnsById = new Map();
      let page, finalizeAudio, nativeCount = 0, chatCount = 0, ackCount = 0, cardReads = 0,
        negativeExpected = null, statusByReference = new Map(), observedOverview = null,
        authenticatedProductObserved = false;
      const context = await browser.newContext({viewport: {width: 1360, height: 900}, locale: 'es-CO',
        timezoneId: 'America/Bogota', storageState: state,
        recordVideo: {dir: caseOut, size: {width: 1360, height: 900}}});
      state = null;
      try {
        await context.grantPermissions(['microphone'], {origin});
        await context.route('**/*', async route => {
          const request = route.request(), url = new URL(request.url()), name = url.pathname;
          if (url.origin !== origin) { fail('Unexpected external browser request.'); return route.abort(); }
          if (name === '/api/assistant/voice-update') {
            item.optionalBackgroundVoiceRequestsBlocked++; return route.abort();
          }
          if (name.startsWith('/api/analytics')) {
            fail('Analytics calls are outside the bounded qualification.'); return route.abort();
          }
          if (request.method() !== 'POST') return route.continue();
          let body; try { body = request.postDataJSON(); } catch {}
          let permitted = false;
          if (name === '/api/chat/messages') {
            permitted = ++chatCount === 1 && body?.message === copy.typed && body.language === spec.language &&
              !body.transaction_reference && !body.query_scope_id;
          } else if (name === '/api/cards/block') {
            permitted = ++cardReads <= 6 && body?.operation === 'status' && !body.request_id && !body.confirmed;
          } else if (name === '/api/voice/turn') {
            const onlyResult = typeof body?.result === 'string' && !body.audio && !body.message && body.language === spec.language;
            if (onlyResult && !negativeExpected && !item.uiGuidancePlayback.actualHostReply)
              await waitUntil(() => item.uiGuidancePlayback.actualHostReply, 3000);
            if (onlyResult && negativeExpected && body.result === negativeExpected) {
              permitted = ++report.observedNegativeResultRequests <= specs.length;
              negativeExpected = null;
            } else if (onlyResult && body.result === item.uiGuidancePlayback.actualHostReply) {
              permitted = ++nativeCount === 1 && ++report.observedProviderEligibleResultRequests <= 1;
              if (permitted) item.uiGuidancePlayback.actualUIResultInputEqualToHostReply = true;
            }
          } else if (name === '/api/voice/played') {
            permitted = ++ackCount === 1 && body?.complete === true && Number.isInteger(body.played_samples);
          }
          if (!permitted) {
            item.events.push({kind: 'request-blocked-before-forwarding', path: name, method: request.method(), atMs: elapsed()});
            fail('Unexpected write, ASR/fallback/input turn, inquiry work, card action, or request budget exceeded.');
            await route.abort(); void browser.close().catch(() => {}); return;
          }
          await route.continue();
        });
        page = await context.newPage(); page.setDefaultTimeout(10000);
        page.on('response', response => {
          const name = new URL(response.url()).pathname, method = response.request().method();
          if (!name.startsWith('/api/') && !name.startsWith('/assets/')) return;
          item.events.push({path: name, method, status: response.status(), atMs: elapsed()});
          pending.push((async () => {
            if (name.startsWith('/assets/')) {
              const asset = {path: name.slice(1), sha256: sha(await response.body()), status: response.status()};
              item.servedAssets.push(asset);
              if (!runtime.served_ui[asset.path] || runtime.served_ui[asset.path] !== asset.sha256) fail('Unexpected or mismatched successor UI asset.');
            } else if (name === '/api/overview' && response.ok()) observedOverview = await response.json();
            else if (name === '/api/cards/block' && response.ok()) {
              const result = await response.json(); statusByReference.set(result.product_reference, result);
            } else if (name === '/api/chat/messages' && method === 'POST') {
              if (!response.ok()) throw Error('Typed card guidance request failed.');
              const result = await response.json();
              if (result.action_hint !== 'card_block' || typeof result.reply !== 'string' || !result.reply.includes(copy.caveat))
                throw Error('Actual typed request did not return the bounded card hint and its no-real-bank caveat.');
              item.uiGuidancePlayback.actualHostReply = result.reply;
              item.uiGuidancePlayback.actualHostReplySha256 = sha(result.reply);
            } else if (name === '/api/voice/played') {
              if (!response.ok()) throw Error('Actual UI playback ACK failed.');
              const body = response.request().postDataJSON();
              await waitUntil(() => turnsById.has(body.turn_id), 5000);
              const actual = turnsById.get(body.turn_id);
              const exact = body.complete === true && body.played_samples === actual.samples;
              if (!exact || item.uiGuidancePlayback.actualUIAck) throw Error('Actual UI ACK was inexact or duplicated.');
              item.uiGuidancePlayback.actualUIAck = {httpStatus: response.status(), complete: body.complete,
                playedSamples: body.played_samples, exactSamples: true, afterStreamCompletion: elapsed() >= actual.completedAtMs,
                emittedByProductUI: true, noHarnessAckInjection: true, atMs: elapsed()};
              report.actualUIPlayedAcks++;
            }
          })().catch(error => { item.observationError = error.message; fail(error.message); }));
        });
        page.on('pageerror', error => { item.events.push({kind: 'pageerror', name: error.name, message: error.message, atMs: elapsed()}); });
        finalizeAudio = await captureBrowserCloneAudio(page, path.join(caseOut, 'audio'), {
          onComplete: value => {
            turnsById.set(value.turnId, {...value, completedAtMs: elapsed()});
            item.uiGuidancePlayback.actualNativeCaption = value.transcript;
            item.uiGuidancePlayback.sampleRate = value.sampleRate;
            item.uiGuidancePlayback.samples = value.samples;
            item.uiGuidancePlayback.seconds = value.samples / value.sampleRate;
          },
          // The deliberately rejected tampered request is captured as HTTP409;
          // this helper reports its lack of audio as an expected capture error.
          onError: error => {
            if (item.negativeTamperedResult?.pending) item.negativeTamperedResult.captureRejectedAsExpected = true;
            else { item.nativeCaptureError = error.message; fail(error.message); }
          },
        });
        await page.goto(origin, {waitUntil: 'domcontentloaded'});
        await waitUntil(() => observedOverview && item.servedAssets.some(a => /^assets\/index-.*\.js$/.test(a.path) && runtime.served_ui[a.path] === a.sha256), 10000);
        authenticatedProductObserved = true;
        await page.locator('nav').getByRole('button').filter({hasText: copy.assistant}).click();
        const dialog = page.getByRole('dialog', {name: copy.title, exact: true});
        await dialog.locator('.assistant-eyes [data-avatar="moss"]').waitFor();
        const card = (observedOverview.products || []).find(p => p.status === 'Active' &&
          /tarjeta|cart[aã]o/i.test(p.type) && p.card_protection_status === 'blocked');
        if (!card) throw Error('No existing owned blocked card was observed; no new block is authorized.');
        const panel = dialog.locator('.card-block-panel');
        await panel.waitFor({state: 'visible'});
        if (!await panel.evaluate(node => node.open)) await panel.locator('summary').click();
        const cardSelect = panel.getByRole('combobox');
        await cardSelect.waitFor({state: 'visible'});
        await cardSelect.selectOption(card.reference);
        await waitUntil(() => exactBlocked(statusByReference.get(card.reference), card.reference), 10000);
        await panel.getByText(copy.blocked, {exact: true}).waitFor();
        const initialStatus = statusByReference.get(card.reference), priorReceiptHash = hashObject(initialStatus.receipt);
        item.existingCardProtection = {initialOwnedStatusVerified: true, state: initialStatus.state,
          receiptStatus: initialStatus.receipt.status, simulated: true, realBankAction: false,
          initialSavedReceiptSha256: priorReceiptHash, observedIndependentlyFromGuidancePlayback: true,
          newPrepareConfirmCancelRequests: 0};
        await page.screenshot({path: path.join(caseOut, '01-owned-existing-card-state.png')});
        await dialog.getByRole('button', {name: copy.start, exact: true}).click();
        await dialog.getByRole('button', {name: copy.stop, exact: true}).waitFor();
        // No microphone utterance is provided: only the existing zero PCM file.
        await dialog.getByLabel(copy.message, {exact: true}).fill(copy.typed);
        await dialog.getByRole('button', {name: copy.send, exact: true}).click();
        await waitUntil(() => item.uiGuidancePlayback.actualHostReply, 10000);
        await page.waitForFunction(reply => [...document.querySelectorAll('[data-savia-reply]')]
          .some(node => node.getAttribute('data-savia-reply') === reply), item.uiGuidancePlayback.actualHostReply, {timeout: 10000});
        item.uiGuidancePlayback.actualHostReplyVisibleInDOM = true;
        await dialog.locator('.assistant-eyes [data-avatar="moss"][data-phase="speaking"]').waitFor({timeout: 40000});
        item.uiGuidancePlayback.speakingPhaseObservedAtMs = elapsed();
        await page.screenshot({path: path.join(caseOut, '02-actual-guidance-speaking.png')});
        await waitUntil(() => item.uiGuidancePlayback.actualUIAck, 45000);
        item.uiGuidancePlayback.strictHostCaptionEquality = item.uiGuidancePlayback.actualNativeCaption === item.uiGuidancePlayback.actualHostReply;
        item.uiGuidancePlayback.caveatPresentInCaption = item.uiGuidancePlayback.actualNativeCaption?.includes(copy.caveat) === true;
        item.uiGuidancePlayback.transportProtocolAccepted = item.uiGuidancePlayback.sampleRate === 24000 &&
          item.uiGuidancePlayback.samples > 0 && item.uiGuidancePlayback.actualUIAck.exactSamples;
        await panel.getByText(copy.blocked, {exact: true}).waitFor();
        await page.screenshot({path: path.join(caseOut, '03-guidance-played-and-card-state.png')});
        await dialog.getByRole('button', {name: copy.stop, exact: true}).click();
        // Explicit read-only reread uses the reference selected in the actual UI;
        // it is never treated as a bank confirmation or a narrated card action.
        const reread = await page.evaluate(async ({reference, language}) => {
          const response = await fetch('/api/cards/block', {method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'}, body: JSON.stringify({product_reference: reference, operation: 'status', language})});
          return {status: response.status, body: await response.json()};
        }, {reference: card.reference, language: spec.language});
        if (reread.status !== 200 || !exactBlocked(reread.body, card.reference) || hashObject(reread.body.receipt) !== priorReceiptHash)
          throw Error('Read-only owned-card reread did not preserve the exact existing saved receipt.');
        item.existingCardProtection.rereadVerified = true;
        item.existingCardProtection.rereadSavedReceiptSha256 = hashObject(reread.body.receipt);
        item.existingCardProtection.savedReceiptUnchanged = true;
        item.negativeTamperedResult = {pending: true, expectedHTTPStatus: 409, providerEligible: false};
        negativeExpected = item.uiGuidancePlayback.actualHostReply + ' Reembolso real confirmado.';
        const denial = await page.evaluate(async ({result, language}) => {
          const response = await fetch('/api/voice/turn', {method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'}, body: JSON.stringify({result, language})});
          await response.text(); return response.status;
        }, {result: negativeExpected, language: spec.language});
        item.negativeTamperedResult.httpStatus = denial;
        if (denial !== 409) throw Error('Tampered result was not rejected before provider admission.');
        await waitUntil(() => item.negativeTamperedResult.captureRejectedAsExpected, 3000);
        item.negativeTamperedResult.pending = false;
        await Promise.allSettled(pending); ensure();
        item.passed = item.uiGuidancePlayback.strictHostCaptionEquality && item.uiGuidancePlayback.caveatPresentInCaption &&
          item.uiGuidancePlayback.transportProtocolAccepted && item.existingCardProtection.savedReceiptUnchanged;
        if (!item.passed) item.failure = 'Actual stream and playback completed, but strict host-script/caption acceptance failed.';
      } catch (error) { item.failure = error.message; fail(error.message); }
      finally {
        if (item.failure && authenticatedProductObserved && page && !page.isClosed()) {
          try {
            // Only the separately authenticated product context is eligible;
            // credentials, cookies, storage state and the entry form are never captured.
            const eligible = new URL(page.url()).origin === origin &&
              await page.locator('nav').count() > 0 && await page.locator('#login-code, .login-language').count() === 0;
            if (eligible) {
              const screenshot = path.join(caseOut, 'failure-authenticated-page.png');
              const dialogText = path.join(caseOut, 'failure-authenticated-dialog.txt');
              const productDialog = page.getByRole('dialog', {name: copy.title, exact: true});
              const text = await productDialog.count() ? await productDialog.innerText({timeout: 1000}) : '[No product dialog present]';
              await fs.writeFile(dialogText, text + '\n', {flag: 'wx'});
              await page.screenshot({path: screenshot, timeout: 2000});
              item.failureDiagnostics = {scope: 'private authenticated product page only', screenshot, dialogText};
            } else item.failureDiagnostics = {skipped: 'Authenticated product context could not be confirmed without entry fields.'};
          } catch (error) { item.failureDiagnostics = {diagnosticError: error.message}; }
        }
        await context.close().catch(() => {});
        if (finalizeAudio) item.privateActualAudioCapture = await finalizeAudio();
        if (item.privateActualAudioCapture?.turns.filter(t => t.completed).length !== 1) item.passed = false;
        await Promise.race([Promise.allSettled(pending), new Promise(r => setTimeout(r, 3000))]);
      }
      if (fatal) break;
    }
    report.passed = !fatal && report.cases.length === specs.length && report.cases.every(c => c.passed) &&
      report.observedProviderEligibleResultRequests === specs.length && report.actualUIPlayedAcks === specs.length;
  } catch (error) { fail(error.message); }
  finally {
    await browser?.close().catch(() => {}); clearTimeout(timer);
    report.finishedAt = new Date().toISOString(); report.durationMs = elapsed();
    report.failure = fatal; report.executionStayedWithinRequestBudget = report.observedProviderEligibleResultRequests <= 1;
    await fs.writeFile(path.join(out, 'receipt-private.json'), JSON.stringify(report, null, 2) + '\n', {flag: 'wx'});
    console.log(JSON.stringify({passed: report.passed, caseCount: report.cases.length,
      providerEligibleRequests: report.observedProviderEligibleResultRequests, actualUIPlayedAcks: report.actualUIPlayedAcks,
      receiptPrivate: path.join(out, 'receipt-private.json'), failure: fatal}));
    if (!report.passed) process.exitCode = 1;
  }
}
