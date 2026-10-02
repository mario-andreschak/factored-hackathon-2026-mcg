import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFile, access, mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { PRIOR as FIRST_FAILURE, collectCorrected } from '../experiments/openrouter_s2s_sdk_terminal.mjs';
import { plan, PRIOR, NAMESPACE, validateNormalizationEvidence, consumeNormalizationAdmission }
  from '../experiments/openrouter_s2s_normalized_terminal.mjs';

const usage = { prompt_tokens: 105, completion_tokens: 112, total_tokens: 217, cost: .007344,
  prompt_tokens_details: { audio_tokens: 41 }, completion_tokens_details: { audio_tokens: 88 } };
const chunk = (delta = {}, extra = {}) => ({ id: 'test-stream', model: 'gpt-audio',
  choices: [{ index: 0, delta, finish_reason: null, native_finish_reason: null, ...extra }] });
const audio = chunk({ audio: { id: 'observed-audio', data: 'EAA=', transcript: 'Estoy contigo.' } });
const normalized = chunk({ role: 'assistant', content: null,
  audio: { id: 'observed-audio', expires_at: 2000000000, data: null, transcript: '' } });
const accounting = { ...chunk({ role: 'assistant', content: '' }), usage };
function stream(values) {
  const bytes = new TextEncoder().encode(values.map(value => `data: ${typeof value === 'string' ? value : JSON.stringify(value)}\n\n`).join(''));
  return new ReadableStream({ start(controller) {
    for (let index = 0; index < bytes.length; index += 19) controller.enqueue(bytes.subarray(index, index + 19));
    controller.close();
  } });
}
const collect = (values, terminalMode = 'application-normalized') => collectCorrected(stream(values),
  { signal: new AbortController().signal, terminalMode });
const firstDirectory = fileURLToPath(new URL('../.local/openrouter-s2s/', import.meta.url));
const secondDirectory = fileURLToPath(new URL('../.local/openrouter-s2s-sdk-terminal/', import.meta.url));
const available = process.env.OPENROUTER_S2S_SKIP_PUBLIC_FIXTURES !== '1' &&
  await Promise.all([[firstDirectory, FIRST_FAILURE.report], [firstDirectory, 'native-pcm16-admitted.json'],
    [secondDirectory, PRIOR.secondReport], [secondDirectory, 'sdk-terminal-correction-admitted.json']]
    .map(([directory, name]) => access(path.join(directory, name)).then(() => true, () => false))).then(values => values.every(Boolean));

test('application correction plan is inert, distinct, bounded and includes both failures and known spend', () => {
  const script = fileURLToPath(new URL('../experiments/openrouter_s2s_normalized_terminal.mjs', import.meta.url));
  const result = spawnSync(process.execPath, [script, '--plan'], { env: {}, encoding: 'utf8', timeout: 5000 });
  assert.equal(result.status, 0);
  const value = JSON.parse(result.stdout);
  assert.equal(value.namespace, NAMESPACE); assert.equal(value.sdkDefaultChanged, false);
  assert.equal(value.calls, 2); assert.equal(value.outputTokens, 512); assert.equal(value.retries, 0);
  assert.equal(value.bodyChanged, false); assert.equal(value.fallback, false);
  assert.equal(value.normalizationIsApplicationCompatibilityInference, true);
  assert.equal(value.normalizationIsExactSdkContract, false);
  assert.equal(value.priorFailures.totalCostUsd, .014038);
  assert.equal(value.firstRequestForecast.knownPriorCostUsd, .014038);
  assert.ok(value.firstRequestForecast.forecastIncludingPriorUsd < .10);
  assert.equal(value.providerHardSpendCap, false); assert.equal(value.pcmPackagingRateQualified, false);
});

test('the SDK default still fails a normalized marker that the explicit application mode admits', async () => {
  const old = await collect([audio, normalized, accounting, '[DONE]'], 'sdk');
  assert.equal(old.status, 'failed'); assert.equal(old.code, 'incomplete_audio_stream');
  assert.equal(old.diagnostic.expiryOnlyDeltaCount, 0);
  const corrected = await collect([audio, normalized, accounting, '[DONE]']);
  assert.equal(corrected.status, 'completed'); assert.equal(corrected.strictCompletionPassed, true);
  assert.equal(corrected.completionSource, 'application_normalized_expiry_terminal');
  assert.equal(corrected.diagnostic.expiryOnlyDeltaCount, 0);
  const shape = corrected.diagnostic.expiryEventShapes[0];
  assert.deepEqual(shape.deltaKnownKeys, ['audio', 'role', 'content']);
  assert.deepEqual(shape.audioKnownKeys, ['id', 'expires_at', 'data', 'transcript']);
  assert.equal(shape.repeatedIdMatchesPrior, true); assert.equal(shape.priorIdObserved, true);
  assert.equal(shape.dataShape, 'null'); assert.equal(shape.transcriptShape, 'empty_string');
  assert.equal(shape.roleShape, 'assistant'); assert.equal(shape.contentShape, 'null');
  assert.equal(shape.sdkExactTerminal, false); assert.equal(shape.applicationNormalizedTerminal, true);
  assert.doesNotMatch(JSON.stringify(corrected.diagnostic), /observed-audio|Estoy contigo/);
});

test('normalization admits only empty metadata around positive expiry and an already observed complete audio', async () => {
  const legal = [
    { audio: { expires_at: 2000000000 } },
    { audio: { id: 'observed-audio', expires_at: 2000000000 } },
    { audio: { expires_at: 2000000000, data: '', transcript: null }, role: 'assistant', content: '' },
  ];
  for (const delta of legal) assert.equal((await collect([audio, chunk(delta), accounting, '[DONE]'])).status, 'completed');
  const illegal = [
    { audio: { id: 'changed', expires_at: 2000000000 } },
    { audio: { id: null, expires_at: 2000000000 } },
    { audio: { expires_at: 2000000000, data: 'EAA=' } },
    { audio: { expires_at: 2000000000, transcript: 'Additional word' } },
    { audio: { expires_at: 2000000000, unexpected: null } },
    { audio: { expires_at: 2000000000 }, content: 'Additional text' },
    { audio: { expires_at: 2000000000 }, role: 'user' },
    { audio: { expires_at: 2000000000 }, role: null },
    { audio: { expires_at: 2000000000 }, refusal: null },
    { audio: { expires_at: 2000000000 }, tool_calls: [] },
    { audio: { expires_at: 0, id: 'observed-audio' } },
    { audio: { expires_at: '2000000000', id: 'observed-audio' } },
  ];
  for (const delta of illegal) assert.equal((await collect([audio, chunk(delta), accounting, '[DONE]'])).status, 'failed');
  const missingPriorId = chunk({ audio: { data: 'EAA=', transcript: 'Hello' } });
  assert.equal((await collect([missingPriorId, normalized, accounting, '[DONE]'])).status, 'failed');
  const missingCaption = chunk({ audio: { id: 'observed-audio', data: 'EAA=' } });
  assert.equal((await collect([missingCaption, normalized, accounting, '[DONE]'])).status, 'failed');
  const missingData = chunk({ audio: { id: 'observed-audio', transcript: 'Hello' } });
  assert.equal((await collect([missingData, normalized, accounting, '[DONE]'])).status, 'failed');
});

test('non-stop finishes, message envelopes, later payload and incomplete transport remain rejected', async () => {
  const bad = [
    [audio, chunk({}, { finish_reason: 'length' }), normalized, accounting, '[DONE]'],
    [audio, chunk({}, { native_finish_reason: 'error' }), normalized, accounting, '[DONE]'],
    [audio, normalized, chunk({ audio: { data: 'EAA=' } }), accounting, '[DONE]'],
    [audio, normalized, chunk({ audio: { transcript: 'Extra' } }), accounting, '[DONE]'],
    [audio, normalized, { ...accounting, choices: [{ ...accounting.choices[0], message: {} }] }, '[DONE]'],
    [audio, normalized, accounting],
    [audio, normalized, '[DONE]'],
  ];
  for (const values of bad) {
    const result = await collect(values); assert.equal(result.status, 'failed');
    assert.equal(result.strictCompletionPassed, false); assert.ok(result.rawPcm.length);
  }
});

test('expiry shape summaries have a fixed bound and omit unknown names and values', async () => {
  const unknown = chunk({ audio: { expires_at: 2000000000, 'private-field-name': 'private-value' } });
  const values = [audio, ...Array.from({ length: 65 }, () => unknown), accounting, '[DONE]'];
  const result = await collect(values);
  assert.equal(result.status, 'failed'); assert.equal(result.diagnostic.expiryEventShapes.length, 64);
  assert.equal(result.diagnostic.expiryEventShapesTruncated, true);
  assert.equal(result.diagnostic.expiryEventShapes[0].unknownAudioKeyCount, 1);
  assert.doesNotMatch(JSON.stringify(result.diagnostic), /private-field-name|private-value/);
});

test('a third exclusive marker binds both failures and never replaces prior evidence', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 's2s-normalized-marker-'));
  try {
    const old = path.join(directory, 'prior'); await mkdir(old);
    const names = ['first-marker', 'first-report', 'second-marker', 'second-report'];
    for (const name of names) await writeFile(path.join(old, name), name + '\n');
    const proof = { firstReportSha256: PRIOR.firstReportSha256, secondReportSha256: PRIOR.secondReportSha256,
      firstAdmissionSha256: 'a'.repeat(64), secondAdmissionSha256: 'b'.repeat(64), knownPriorCostUsd: PRIOR.totalCostUsd };
    const corrected = path.join(directory, 'third');
    const marker = await consumeNormalizationAdmission(corrected, proof);
    assert.equal(marker.priorFailures.knownPriorCostUsd, .014038);
    await assert.rejects(consumeNormalizationAdmission(corrected, proof), { code: 'EEXIST' });
    for (const name of names) assert.equal(await readFile(path.join(old, name), 'utf8'), name + '\n');
    await assert.rejects(consumeNormalizationAdmission(path.join(directory, 'bad'), { ...proof, secondReportSha256: 'c'.repeat(64) }), /prior_failure_proof_missing/);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test('both exact previous failures validate read-only before any new admission',
  { skip: available ? false : 'ignored prior public audition receipts are absent' }, async () => {
    const files = [path.join(firstDirectory, FIRST_FAILURE.report), path.join(firstDirectory, 'native-pcm16-admitted.json'),
      path.join(secondDirectory, PRIOR.secondReport), path.join(secondDirectory, 'sdk-terminal-correction-admitted.json')];
    const values = await Promise.all(files.map(file => readFile(file)));
    const proof = validateNormalizationEvidence(...values);
    assert.equal(proof.firstReportSha256, PRIOR.firstReportSha256); assert.equal(proof.secondReportSha256, PRIOR.secondReportSha256);
    assert.equal(proof.knownPriorCostUsd, .014038);
    const afterwards = await Promise.all(files.map(file => readFile(file)));
    assert.deepEqual(afterwards, values);
  });
