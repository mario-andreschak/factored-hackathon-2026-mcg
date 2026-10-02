import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFile, mkdtemp, mkdir, writeFile, rm, access } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { CASES, RATE } from '../experiments/openrouter_s2s_audition.mjs';
import { plan, PRIOR, NAMESPACE, NativeStreamEvidence, collectCorrected, consumeCorrectionAdmission,
  validatePriorEvidence, saveDiagnosticAudio } from '../experiments/openrouter_s2s_sdk_terminal.mjs';

const usage = { prompt_tokens: 105, completion_tokens: 101, total_tokens: 206, cost: .006694,
  prompt_tokens_details: { audio_tokens: 41 }, completion_tokens_details: { audio_tokens: 78 } };
const chunk = (delta = {}, extra = {}) => ({ id: 'public-test-stream', model: 'gpt-audio',
  choices: [{ index: 0, delta, finish_reason: null, native_finish_reason: null, ...extra }] });
const audio = chunk({ role: 'assistant', audio: { id: 'public-test-audio', data: 'EAA=', transcript: 'Estoy contigo.' } });
const terminal = chunk({ audio: { expires_at: 2000000000 } });
const accounting = { ...chunk({ role: 'assistant', content: '' }), usage };
const encode = value => `data: ${typeof value === 'string' ? value : JSON.stringify(value)}\n\n`;
function stream(values, options = {}) {
  const bytes = new TextEncoder().encode(values.map(encode).join(''));
  return new ReadableStream({ start(controller) {
    for (let i = 0; i < bytes.length; i += 13) controller.enqueue(bytes.subarray(i, i + 13));
    if (!options.stall) controller.close();
  }, ...(options.stall ? { pull() { return new Promise(() => {}); }, cancel() { return new Promise(() => {}); } } : {}) });
}
const collect = values => collectCorrected(stream(values), { signal: new AbortController().signal });
const oldDirectory = fileURLToPath(new URL('../.local/openrouter-s2s/', import.meta.url));
const priorFilesAvailable = process.env.OPENROUTER_S2S_SKIP_PUBLIC_FIXTURES !== '1' &&
  await Promise.all([PRIOR.report, 'native-pcm16-admitted.json'].map(file => access(path.join(oldDirectory, file)).then(() => true, () => false)))
    .then(values => values.every(Boolean));

test('default correction plan is inert and includes known first cost with no body or provider change', () => {
  const script = fileURLToPath(new URL('../experiments/openrouter_s2s_sdk_terminal.mjs', import.meta.url));
  const output = spawnSync(process.execPath, [script, '--plan'], { encoding: 'utf8', timeout: 5000, env: {} });
  assert.equal(output.status, 0);
  const value = JSON.parse(output.stdout);
  assert.equal(value.namespace, NAMESPACE); assert.equal(value.status, 'correction_prepared_not_dispatched');
  assert.equal(value.calls, 2); assert.equal(value.outputTokens, 512); assert.equal(value.timeoutMs, 45000);
  assert.equal(value.bodyChanged, false); assert.equal(value.fallback, false);
  assert.equal(value.providerHardSpendCap, false); assert.equal(value.priorFailure.costUsd, .006694);
  assert.equal(value.firstRequestForecast.knownPriorCostUsd, .006694);
  assert.ok(value.firstRequestForecast.forecastIncludingPriorUsd < .05);
  assert.equal(value.pcmPackagingRateQualified, false); assert.equal(value.failedStreamAudioIsAcceptance, false);
});

test('SDK expiry-only terminal permits following documented accounting-only usage metadata', async () => {
  const value = await collect([audio, terminal, accounting, '[DONE]']);
  assert.equal(value.status, 'completed'); assert.equal(value.strictCompletionPassed, true);
  assert.equal(value.completionSource, 'sdk_expiry_only_terminal');
  assert.equal(value.usage.costUsd, .006694); assert.deepEqual(value.rawPcm, Buffer.from([16, 0]));
  assert.equal(value.wav.readUInt32LE(24), RATE);
  assert.equal(value.diagnostic.expiryOnlyDeltaCount, 1);
  assert.equal(value.diagnostic.audioIdTypes.string, 1); assert.equal(value.diagnostic.audioExpiryTypes.number, 1);
  assert.equal(value.diagnostic.accountingOnlyChoiceCount, 1);
  assert.equal(value.diagnostic.meaningfulAfterTerminalCount, 0);
  assert.equal(value.diagnostic.cleanEof, true); assert.equal(value.diagnostic.doneCount, 1);
  assert.match(value.diagnostic.audioIdSha256, /^[a-f0-9]{64}$/);
  assert.doesNotMatch(JSON.stringify(value.diagnostic), /public-test-(?:stream|audio)/);
});

test('explicit wire stop remains accepted and cannot erase a non-stop native finish', async () => {
  const good = await collect([audio, chunk({}, { finish_reason: 'stop' }), accounting, '[DONE]']);
  assert.equal(good.status, 'completed'); assert.equal(good.completionSource, 'explicit_wire_stop');
  const bad = await collect([audio, chunk({}, { finish_reason: 'stop', native_finish_reason: 'length' }), terminal, accounting, '[DONE]']);
  assert.equal(bad.status, 'failed'); assert.equal(bad.code, 'non_stop_finish');
  const continued = await collect([audio, chunk({}, { finish_reason: 'stop' }), chunk({ audio: { data: 'EAA=' } }), accounting, '[DONE]']);
  assert.equal(continued.status, 'failed'); assert.equal(continued.code, 'content_after_audio_terminal');
  assert.equal(continued.diagnostic.meaningfulAfterTerminalCount, 1);
  const empty = await collect([audio, chunk({}, { finish_reason: 'stop' }), chunk({}), accounting, '[DONE]']);
  assert.equal(empty.status, 'completed');
});

test('unexpected message envelopes cannot bypass either terminal through usage-only deltas', async () => {
  for (const ending of [terminal, chunk({}, { finish_reason: 'stop' })]) {
    for (const message of [{ content: 'Unallowed continuation' }, { audio: { data: 'EAA=', id: 'foreign' } }, {}]) {
      const finalAccounting = { ...accounting, choices: [{ ...accounting.choices[0], message }] };
      const result = await collect([audio, ending, finalAccounting, '[DONE]']);
      assert.equal(result.status, 'failed'); assert.equal(result.code, 'unexpected_message_envelope');
      assert.equal(result.strictCompletionPassed, false);
      assert.equal(result.diagnostic.messageAudioCount, message.audio ? 1 : 0);
      assert.doesNotMatch(JSON.stringify(result.diagnostic), /Unallowed continuation|foreign/);
    }
  }
  const nullMessage = { ...accounting, choices: [{ ...accounting.choices[0], message: null }] };
  assert.equal((await collect([audio, terminal, nullMessage, '[DONE]'])).status, 'completed');
});

test('absent fields, unknown/truncated completion and post-terminal content fail closed while retaining bounded PCM', async () => {
  const cases = [
    [chunk({ audio: { data: 'EAA=', transcript: 'Hola' } }), terminal, accounting, '[DONE]'],
    [chunk({ audio: { id: 'a', data: 'EAA=' } }), terminal, accounting, '[DONE]'],
    [chunk({ audio: { id: 'a', transcript: 'Hola' } }), terminal, accounting, '[DONE]'],
    [audio, chunk({}, { finish_reason: 'length' }), terminal, accounting, '[DONE]'],
    [audio, chunk({}, { native_finish_reason: 'unrecognized-private-reason' }), terminal, accounting, '[DONE]'],
    [audio, terminal, chunk({ audio: { data: 'EAA=' } }), accounting, '[DONE]'],
    [audio, terminal, chunk({ content: 'More content' }), accounting, '[DONE]'],
    [audio, terminal, chunk({ refusal: 'Cannot do that' }), accounting, '[DONE]'],
    [audio, chunk({ audio: { expires_at: 2000000000 }, role: 'assistant' }), accounting, '[DONE]'],
    [audio, terminal, accounting],
    [audio, terminal, accounting, '[DONE]', '[DONE]'],
    [audio, terminal, accounting, '[DONE]', chunk({})],
    [audio, chunk({ audio: { id: 'changed', data: 'EAA=' } }), terminal, accounting, '[DONE]'],
  ];
  for (const values of cases) {
    const result = await collect(values);
    assert.equal(result.status, 'failed'); assert.equal(result.strictCompletionPassed, false);
    assert.equal(result.diagnostic.failedAudioIsAcceptance, false);
    assert.doesNotMatch(JSON.stringify(result.diagnostic), /unrecognized-private-reason|More content|Cannot do that/);
  }
  const missingTerminal = await collect([audio, accounting, '[DONE]']);
  assert.equal(missingTerminal.status, 'failed'); assert.deepEqual(missingTerminal.rawPcm, Buffer.from([16, 0]));
  assert.ok(missingTerminal.wav); assert.equal(missingTerminal.usage.costUsd, .006694);
});

test('failed stream PCM and preview are stored only under explicit diagnostic filenames', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 's2s-failed-audio-'));
  try {
    const result = await collect([audio, accounting, '[DONE]']);
    const files = await saveDiagnosticAudio(directory, CASES[0], result);
    assert.equal(files.rawPcmFile, 'es.failed-diagnostic.pcm'); assert.equal(files.previewFile, 'es.failed-diagnostic.wav');
    assert.equal(files.failedAudioIsAcceptance, false); assert.equal(files.pcmPackagingRateQualified, false);
    assert.deepEqual(await readFile(path.join(directory, files.rawPcmFile)), Buffer.from([16, 0]));
    assert.deepEqual(await readFile(path.join(directory, files.previewFile)), result.wav);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test('deadline retains partial PCM even when stream cancellation never resolves', async () => {
  const controller = new AbortController(), started = performance.now();
  const timer = setTimeout(() => controller.abort(), 10);
  const result = await collectCorrected(stream([audio], { stall: true }), { signal: controller.signal });
  clearTimeout(timer);
  assert.equal(result.status, 'failed'); assert.equal(result.code, 'request_deadline');
  assert.deepEqual(result.rawPcm, Buffer.from([16, 0])); assert.equal(result.diagnostic.cleanEof, false);
  assert.ok(performance.now() - started < 1000);
});

test('new one-use correction marker binds failure hash and preserves old marker and failure bytes', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 's2s-correction-admit-'));
  try {
    const old = path.join(directory, 'old'), corrected = path.join(directory, 'corrected');
    await mkdir(old);
    const oldMarker = Buffer.from('old admitted evidence\n'), oldReceipt = Buffer.from('old failed evidence\n');
    await writeFile(path.join(old, 'native-pcm16-admitted.json'), oldMarker);
    await writeFile(path.join(old, 'report.json'), oldReceipt);
    const proof = { reportSha256: PRIOR.reportSha256, oldAdmissionSha256: createHash('sha256').update(oldMarker).digest('hex'), knownPriorCostUsd: PRIOR.costUsd };
    const record = await consumeCorrectionAdmission(corrected, proof);
    assert.equal(record.priorFailure.reportSha256, PRIOR.reportSha256);
    await assert.rejects(consumeCorrectionAdmission(corrected, proof), { code: 'EEXIST' });
    assert.deepEqual(await readFile(path.join(old, 'native-pcm16-admitted.json')), oldMarker);
    assert.deepEqual(await readFile(path.join(old, 'report.json')), oldReceipt);
    assert.throws(() => validatePriorEvidence(oldReceipt, oldMarker), /prior_failure_hash_mismatch/);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test('diagnostic counters never persist raw errors, identifiers or caption values', () => {
  const evidence = new NativeStreamEvidence();
  evidence.event(JSON.stringify({ error: { code: 400, message: 'private-secret https://private.invalid',
    metadata: { raw: JSON.stringify({ error: { code: 'unsupported_value', type: 'invalid_request_error', param: 'audio.format' } }) } }, choices: [] }));
  const value = evidence.result({ cleanEof: true });
  assert.equal(value.status, 'failed'); assert.equal(value.diagnostic.topErrorCount, 1);
  assert.equal(value.diagnostic.error.parameter, 'audio.format');
  assert.doesNotMatch(JSON.stringify(value.diagnostic), /private|https:/);
});

test('exact existing first failure validates by hash without changing its receipt or admission',
  { skip: priorFilesAvailable ? false : 'ignored original audition receipt is absent' }, async () => {
    const report = await readFile(path.join(oldDirectory, PRIOR.report));
    const admission = await readFile(path.join(oldDirectory, 'native-pcm16-admitted.json'));
    const proof = validatePriorEvidence(report, admission);
    assert.equal(proof.reportSha256, PRIOR.reportSha256); assert.equal(proof.knownPriorCostUsd, .006694);
    assert.deepEqual(await readFile(path.join(oldDirectory, PRIOR.report)), report);
    assert.deepEqual(await readFile(path.join(oldDirectory, 'native-pcm16-admitted.json')), admission);
  });
