import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { parseWav, wav } from '../personaplex_browser_audition.mjs';
import { riceFixture, qualifiedRiceFixture, transcriptionPayload, riceRecognition, RequestScope, plan } from '../personaplex_observer_audition.mjs';

const RATE = 24000;
const report = { source_revision: '3428dfd95309a7f3c84fd93259ded0f810d1ff91', model_revision: 'fdaf4090a61cb315c138a1faee287ffd6c716309',
  banking_access: false, clock_frames: 338, continuation_start_frame: 188 };
const origin = 'http://127.0.0.1:43937';
function payload(seconds = 4) {
  const bytes = wav(Buffer.alloc(seconds * 16000 * 2));
  bytes.writeUInt32LE(16000, 24); bytes.writeUInt32LE(32000, 28);
  return { format: 'wav', audio: bytes.toString('base64') };
}

test('joined fixture preserves exact public rice bytes and excludes greeting and repeated speech', () => {
  const pcm = Buffer.alloc(338 * 1920 * 2);
  pcm.fill(7, 0, 4 * RATE * 2);
  pcm.fill(9, 188 * 1920 * 2, (188 * 1920 + 8 * RATE) * 2);
  const fixture = riceFixture(pcm, report);
  assert.equal(fixture.length, 45 * RATE * 2);
  assert.ok(fixture.subarray(0, 4 * RATE * 2).every(byte => byte === 0));
  assert.deepEqual(fixture.subarray(4 * RATE * 2, 10 * RATE * 2), pcm.subarray(188 * 1920 * 2, (188 * 1920 + 6 * RATE) * 2));
  assert.ok(fixture.subarray(10 * RATE * 2).every(byte => byte === 0));
  assert.ok(!fixture.includes(7));
  assert.throws(() => riceFixture(pcm, { ...report, banking_access: true }));
  assert.throws(() => riceFixture(pcm, { ...report, source_revision: 'unpinned' }));
  assert.throws(() => riceFixture(pcm.subarray(0, pcm.length - 2), report));
});

test('joined fixture additionally enforces the full ignored source WAV hash', async t => {
  let bytes;
  try { bytes = await readFile(new URL('../../.local/personaplex-forced-result/20261001-024017/input.wav', import.meta.url)); }
  catch (error) { if (error.code === 'ENOENT') { t.skip('Ignored public audition artifact is not present.'); return; } throw error; }
  const result = qualifiedRiceFixture(bytes, report), source = parseWav(bytes);
  assert.equal(result.length, 45 * RATE * 2);
  assert.deepEqual(result.subarray(4 * RATE * 2, 10 * RATE * 2), source.subarray(188 * 1920 * 2, (188 * 1920 + 6 * RATE) * 2));
  const changed = Buffer.from(bytes); changed[100] ^= 1;
  assert.throws(() => qualifiedRiceFixture(changed, report), { code: 'unqualified_public_audio' });
});

test('ASR evidence accepts the actual bounded canonical mono16k WAV profile', () => {
  const input = payload(), evidence = transcriptionPayload(input);
  assert.equal(evidence.durationSeconds, 4);
  assert.equal(evidence.sampleRate, 16000);
  assert.equal(evidence.bytes.length, 128044);
  assert.match(evidence.sha256, /^[a-f0-9]{64}$/);
  assert.equal(transcriptionPayload(payload(1)).durationSeconds, 1);
  assert.equal(transcriptionPayload(payload(12)).durationSeconds, 12);
});

test('ASR evidence rejects another codec, rate, channels, malformed encoding or oversized turn', () => {
  assert.throws(() => transcriptionPayload({ ...payload(), format: 'mp3' }));
  assert.throws(() => transcriptionPayload({ ...payload(), audio: payload().audio + '\n' }));
  assert.throws(() => transcriptionPayload(payload(.5)), { code: 'unexpected_public_asr_duration' });
  assert.throws(() => transcriptionPayload(payload(13)), { code: 'unexpected_public_asr_duration' });
  for (const mutate of [bytes => bytes.writeUInt32LE(24000, 24), bytes => bytes.writeUInt16LE(2, 22),
    bytes => bytes.writeUInt16LE(3, 20), bytes => bytes.writeUInt32LE(12, 16), bytes => bytes.writeUInt32LE(3, 40)]) {
    const bytes = Buffer.from(payload().audio, 'base64'); mutate(bytes);
    assert.throws(() => transcriptionPayload({ format: 'wav', audio: bytes.toString('base64') }), { code: 'unexpected_public_asr_payload' });
  }
  assert.throws(() => transcriptionPayload({ format: 'wav', audio: 'A'.repeat(1_100_001) }));
});

test('recognition requires meaningful rice-request content instead of greeting or accidental keywords', () => {
  for (const text of ['What ratio of water to rice should I use?', 'Could you tell me how to cook rice?',
    'Prevent rice from becoming sticky when cooking on the stove.']) {
    const result = riceRecognition(text);
    assert.equal(result.meaningfulRiceRequest, true); assert.ok(result.wordCount >= 6);
    assert.match(result.sha256, /^[a-f0-9]{64}$/); assert.equal('text' in result, false);
  }
  for (const text of ['Hi.', 'Rice.', 'Rice and water.', 'I cooked some rice with water on the stove.',
    'Prevent a refund when cooking rice on the stove.', 'What is the balance in my rice cooking account?']) {
    assert.equal(riceRecognition(text).meaningfulRiceRequest, false);
  }
  assert.throws(() => riceRecognition(''), { code: 'invalid_public_recognition' });
  assert.throws(() => riceRecognition('a'.repeat(8001)), { code: 'invalid_public_recognition' });
});

test('actual request gate permits one native admission and one public transcription only', () => {
  const scope = new RequestScope(origin);
  assert.equal(scope.admit(origin + '/assets/world.webp', 'GET'), '/assets/world.webp');
  assert.equal(scope.admit(origin + '/api/avatar/config', 'GET'), '/api/avatar/config');
  assert.equal(scope.admit(origin + '/api/avatar/personaplex-session', 'POST'), '/api/avatar/personaplex-session');
  assert.equal(scope.admit(origin + '/api/avatar/transcribe', 'POST'), '/api/avatar/transcribe');
  assert.throws(() => scope.admit(origin + '/api/avatar/transcribe', 'POST'), { code: 'duplicate_public_transcription' });
  assert.throws(() => scope.admit(origin + '/api/avatar/personaplex-session', 'POST'), { code: 'duplicate_native_admission' });
});

test('actual request gate blocks bank, external, unknown API and chained provider paths before dispatch', () => {
  const scope = new RequestScope(origin);
  for (const [pathname, method] of [['/savia', 'GET'], ['/savia/api/auth/me', 'GET'], ['/api/avatar/task', 'POST'],
    ['/api/avatar/conversation', 'POST'], ['/api/avatar/speech', 'POST'], ['/api/avatar/gemini-token', 'POST'],
    ['/api/avatar/future-provider', 'POST'], ['/api/avatar/transcribe', 'GET'], ['/login', 'POST']]) {
    assert.throws(() => scope.admit(origin + pathname, method), { code: 'unexpected_request_scope' });
  }
  assert.throws(() => scope.admit('https://example.com/audio', 'GET'), { code: 'unexpected_request_scope' });
  assert.equal(scope.admissions, 0); assert.equal(scope.transcriptions, 0); assert.equal(scope.prohibited, 10);
});

test('inert CLI works away from the repo without reading assets, opening a browser or calling providers', () => {
  const script = fileURLToPath(new URL('../personaplex_observer_audition.mjs', import.meta.url));
  const result = JSON.parse(execFileSync(process.execPath, [script], { cwd: tmpdir(), encoding: 'utf8', timeout: 2000 }));
  assert.deepEqual(result, plan()); assert.equal(result.status, 'prepared_not_executed');
  assert.equal(result.durationLimitSeconds, 45);
  assert.match(result.mute, /after completed recognition/);
  const invalid = spawnSync(process.execPath, [script, '--plan', '--url', 'https://example.com'], { encoding: 'utf8', timeout: 2000 });
  assert.equal(invalid.status, 1); assert.equal(invalid.stdout, '');
  assert.equal(JSON.parse(invalid.stderr).status, 'failed');
});
