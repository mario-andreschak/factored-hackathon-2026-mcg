import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { classifyMood } from '../server/mood.mjs';
import { RATE, wav } from './personaplex_browser_audition.mjs';
import { EXPECTED_TEXT, initialFixture, initialPayload, selectedResponse, nativeContextEvidence,
  InitialRequestScope, ReplayObservation, plan } from './personaplex_initial_audition.mjs';

const origin = 'http://127.0.0.1:43938';
const sourceReport = { source_revision: '3428dfd95309a7f3c84fd93259ded0f810d1ff91', model_revision: 'fdaf4090a61cb315c138a1faee287ffd6c716309',
  banking_access: false, clock_frames: 338, continuation_start_frame: 188 };
const payload = (seconds = 2) => ({ audio: wav(Buffer.alloc(Math.round(seconds * RATE) * 2)).toString('base64'), format: 'wav' });
function frame(pcm, index) { const result = Buffer.alloc(3841); result[0] = 0x10; pcm.copy(result, 1, index * 3840, Math.min((index + 1) * 3840, pcm.length)); return result; }
const script = fileURLToPath(new URL('./personaplex_initial_audition.mjs', import.meta.url));

test('initial audition default/plan remains inert away from workspace and rejects contradictory or arbitrary input flags', () => {
  const output = execFileSync(process.execPath, [script], { cwd: tmpdir(), encoding: 'utf8', timeout: 2000 });
  assert.deepEqual(JSON.parse(output), plan()); assert.equal(plan(origin).durationLimitSeconds, 60);
  assert.equal(plan().status, 'prepared_not_executed');
  for (const args of [['--plan', '--url', 'https://example.com'], ['--plan', '--input', 'private.wav'], ['--plan', '--execute']]) {
    const result = spawnSync(process.execPath, [script, ...args], { cwd: tmpdir(), encoding: 'utf8', timeout: 2000 });
    assert.equal(result.status, 1); assert.equal(result.stdout, ''); assert.equal(JSON.parse(result.stderr).status, 'failed');
  }
});

test('initial fixture retains only the pinned rice excerpt and pads quiet through the whole sixty-second bound', async t => {
  let source;
  try { source = await readFile(new URL('../.local/personaplex-forced-result/20261001-024017/input.wav', import.meta.url)); }
  catch (error) { if (error.code === 'ENOENT') { t.skip('Ignored pinned public fixture is absent.'); return; } throw error; }
  const fixture = initialFixture(source, sourceReport);
  assert.equal(fixture.length, 60 * RATE * 2);
  assert.ok(fixture.subarray(0, 4 * RATE * 2).every(x => x === 0));
  assert.ok(fixture.subarray(10 * RATE * 2).every(x => x === 0));
  const changed = Buffer.from(source); changed[200] ^= 1;
  assert.throws(() => initialFixture(changed, sourceReport), { code: 'unqualified_public_audio' });
  assert.throws(() => initialFixture(source, { ...sourceReport, banking_access: true }));
});

test('initial capture oracle accepts canonical24k and exact twelve seconds, exposing only hashes/counts', () => {
  const checked = initialPayload(payload(12));
  assert.equal(checked.seconds, 12); assert.equal(checked.pcm.length, 12 * RATE * 2);
  assert.match(checked.wavSha256, /^[a-f0-9]{64}$/); assert.match(checked.pcmSha256, /^[a-f0-9]{64}$/);
  assert.throws(() => initialPayload(payload(12.001)), { code: 'invalid_initial_duration' });
  assert.throws(() => initialPayload(payload(.5)), { code: 'invalid_initial_duration' });
});

test('initial capture rejects alternate PCM profiles, malformed base64 and browser-supplied role/context', () => {
  for (const mutate of [bytes => bytes.writeUInt32LE(16000, 24), bytes => bytes.writeUInt16LE(2, 22),
    bytes => bytes.writeUInt16LE(3, 20), bytes => bytes.writeUInt32LE(12, 16), bytes => bytes.writeUInt32LE(3, 40)]) {
    const bytes = Buffer.from(payload().audio, 'base64'); mutate(bytes);
    assert.throws(() => initialPayload({ format: 'wav', audio: bytes.toString('base64') }), { code: 'invalid_initial_payload' });
  }
  for (const extra of [{ avatar: 'moss' }, { transcript: EXPECTED_TEXT }, { url: origin }, { language: 'en' }]) assert.throws(() => initialPayload({ ...payload(), ...extra }));
  assert.throws(() => initialPayload({ ...payload(), audio: payload().audio + '\n' }));
});

test('actual selected response must match known rice request and shared Moss classification without a spoken-name gate', () => {
  assert.equal(classifyMood(EXPECTED_TEXT).avatar, 'moss');
  const response = { avatar: 'moss', transcript: EXPECTED_TEXT, initialContextDelivered: false, ticket: 'private-ticket-must-not-be-reported' };
  const result = selectedResponse(response); assert.equal(result.avatar, 'moss'); assert.equal(result.wordCount, 10);
  assert.equal(result.meaningfulRiceRequest, true); assert.equal(JSON.stringify(result).includes('ticket'), false);
  const variation = selectedResponse({ ...response, transcript: 'How should I cook rice with water on the stove?' });
  assert.equal(variation.expectedMeaningfullyEquivalent, true); assert.notEqual(variation.sha256, result.sha256);
  for (const changed of [{ avatar: 'orbit' }, { initialContextDelivered: true }, { transcript: 'Hi.' },
    { transcript: 'What is the balance in my rice cooking account?' }]) assert.throws(() => selectedResponse({ ...response, ...changed }), { code: 'initial_selection_mismatch' });
});

test('request gate permits only actual config/static reads and one initial POST', () => {
  const scope = new InitialRequestScope(origin);
  assert.equal(scope.admit(origin + '/assets/world.webp', 'GET'), '/assets/world.webp');
  assert.equal(scope.admit(origin + '/api/avatar/config', 'GET'), '/api/avatar/config');
  assert.equal(scope.admit(origin + '/api/avatar/personaplex-initial', 'POST'), '/api/avatar/personaplex-initial');
  assert.throws(() => scope.admit(origin + '/api/avatar/personaplex-initial', 'POST'), { code: 'duplicate_initial_admission' });
});

test('request gate blocks bank, observer, fixed admission, fallback and unknown destinations before dispatch', () => {
  const scope = new InitialRequestScope(origin);
  for (const pathname of ['/savia', '/savia/api/auth/me', '/api/avatar/personaplex-session', '/api/avatar/transcribe',
    '/api/avatar/conversation', '/api/avatar/speech', '/api/avatar/task', '/api/avatar/gemini-token', '/api/avatar/unknown', '/api/avatar/personaplex-initial?avatar=moss']) {
    assert.throws(() => scope.admit(origin + pathname, 'POST'), { code: 'unexpected_request_scope' });
  }
  assert.throws(() => scope.admit('https://example.com/audio', 'GET'), { code: 'unexpected_request_scope' });
  assert.equal(scope.initialPosts, 0); assert.equal(scope.prohibited, 11);
});

test('replay oracle reconstructs exact captured samples plus padding at normal1x with no second capture', () => {
  const pcm = Buffer.alloc(3840 * 2 + 6); pcm.writeInt16LE(12345, 0); pcm.writeInt16LE(-23456, 2); pcm.writeInt16LE(8191, pcm.length - 2);
  const replay = new ReplayObservation(pcm);
  for (let i = 0; i < replay.frames; i++) assert.equal(replay.sent(frame(pcm, i), 100 + i * 80, 90), true);
  const result = replay.report([10, 90, 170]);
  assert.equal(result.frames, 3); assert.equal(result.byteExact, true); assert.equal(result.paddedSamples, 1917);
  assert.equal(result.capturedPcmSha256, result.replayPcmSha256);
  assert.equal(replay.sent(frame(pcm, 0), 400, 90), false);
});

test('replay oracle fails on one-LSB re-encoding, partial live interleaving or input before READY', () => {
  const pcm = Buffer.alloc(4000); pcm.writeInt16LE(8191, 0);
  const changed = frame(pcm, 0); changed.writeInt16LE(8190, 1);
  assert.throws(() => new ReplayObservation(pcm).sent(changed, 100, 90), { code: 'initial_pcm_replay_mismatch' });
  assert.throws(() => new ReplayObservation(pcm).sent(frame(pcm, 0), 100, undefined), { code: 'replay_before_ready_or_interleaved' });
  assert.throws(() => new ReplayObservation(pcm).sent(frame(pcm, 0).subarray(0, 2049), 100, 90), { code: 'replay_before_ready_or_interleaved' });
});

test('replay oracle refuses incomplete prefixes and accelerated/catch-up bursts', () => {
  const pcm = Buffer.alloc(8000), replay = new ReplayObservation(pcm);
  assert.throws(() => replay.report([]), { code: 'initial_replay_incomplete' });
  for (let i = 0; i < replay.frames; i++) replay.sent(frame(pcm, i), 100 + i * 80, 90);
  assert.throws(() => replay.report([0, 49, 98]), { code: 'initial_replay_pacing_failed' });
  assert.throws(() => replay.report([0, 80, 81]), { code: 'initial_replay_pacing_failed' });
  assert.throws(() => replay.report([0, 80, 800]), { code: 'initial_replay_pacing_failed' });
});

test('native caption oracle requires cooking context/detail and never mistakes a self-name or bank topic for qualification', () => {
  assert.equal(nativeContextEvidence('To cook fluffy rice, rinse the grains and use measured water.').relevantCookingResponse, true);
  for (const text of ['I am Moss and I am here to help you.', 'Hello. What would you like to talk about today?',
    'Your rice account balance and payment dispute will be refunded with water.']) assert.equal(nativeContextEvidence(text).relevantCookingResponse, false);
  assert.throws(() => nativeContextEvidence(''), { code: 'invalid_native_caption' });
});
