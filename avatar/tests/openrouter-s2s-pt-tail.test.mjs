import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { readFile, access, mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { PRIOR as FIRST, collectCorrected } from '../experiments/openrouter_s2s_sdk_terminal.mjs';
import { PRIOR as SECOND } from '../experiments/openrouter_s2s_normalized_terminal.mjs';
import { plan, PRIOR, NAMESPACE, validateTailEvidence, consumeTailAdmission } from '../experiments/openrouter_s2s_pt_tail.mjs';

const usage = { prompt_tokens: 120, completion_tokens: 112, total_tokens: 232, cost: .008,
  prompt_tokens_details: { audio_tokens: 50 }, completion_tokens_details: { audio_tokens: 88 } };
const chunk = (delta = {}, extra = {}) => ({ id: 'test-stream', model: 'gpt-audio',
  choices: [{ index: 0, delta, finish_reason: null, native_finish_reason: null, ...extra }] });
const audio = chunk({ audio: { id: 'observed-audio', data: 'EAA=', transcript: 'Estou aqui.' } });
const expiry = chunk({ role: 'assistant', content: '', audio: { expires_at: 2000000000 } });
const tail = chunk({ role: 'assistant', content: '', audio: { id: 'observed-audio' } });
const accounting = { ...chunk({ role: 'assistant', content: '' }), usage };
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const collect = async (values, terminalMode = 'application-metadata-tail') => {
  const bytes = new TextEncoder().encode(values.map(value => `data: ${typeof value === 'string' ? value : JSON.stringify(value)}\n\n`).join(''));
  const stream = new ReadableStream({ start(controller) {
    for (let i = 0; i < bytes.length; i += 23) controller.enqueue(bytes.subarray(i, i + 23));
    controller.close();
  } });
  return collectCorrected(stream, { signal: new AbortController().signal, terminalMode });
};
const local = fileURLToPath(new URL('../.local/', import.meta.url));
const evidenceFiles = [path.join(local, 'openrouter-s2s', FIRST.report), path.join(local, 'openrouter-s2s', 'native-pcm16-admitted.json'),
  path.join(local, 'openrouter-s2s-sdk-terminal', SECOND.secondReport), path.join(local, 'openrouter-s2s-sdk-terminal', 'sdk-terminal-correction-admitted.json'),
  path.join(local, 'openrouter-s2s-normalized-terminal', PRIOR.thirdReport), path.join(local, 'openrouter-s2s-normalized-terminal', 'application-terminal-admitted.json')];
const available = process.env.OPENROUTER_S2S_SKIP_PUBLIC_FIXTURES !== '1' &&
  await Promise.all(evidenceFiles.map(file => access(file).then(() => true, () => false))).then(values => values.every(Boolean));

test('Portuguese-only plan is inert with one call, three failure hashes and cumulative forecast', () => {
  const script = fileURLToPath(new URL('../experiments/openrouter_s2s_pt_tail.mjs', import.meta.url));
  const result = spawnSync(process.execPath, [script, '--plan'], { env: {}, encoding: 'utf8', timeout: 5000 });
  assert.equal(result.status, 0);
  const value = JSON.parse(result.stdout);
  assert.equal(value.namespace, NAMESPACE); assert.equal(value.calls, 1); assert.equal(value.spanishCalls, 0);
  assert.deepEqual(value.locales, ['pt-BR']); assert.equal(value.outputTokens, 512); assert.equal(value.timeoutMs, 45000);
  assert.equal(value.knownPriorCostUsd, .021584); assert.equal(value.firstRequestForecast.knownPriorCostUsd, .021584);
  assert.equal(value.orderedChoiceShapeLimit, 256); assert.ok(value.firstRequestForecast.forecastIncludingPriorUsd < .10);
  assert.equal(value.normalizationIsApplicationCompatibilityInference, true); assert.equal(value.providerHardSpendCap, false);
  assert.equal(value.retries, 0); assert.equal(value.fallback, false);
});

test('same-ID metadata tail and bare assistant metadata require explicit new mode', async () => {
  const values = [audio, expiry, tail, chunk({ role: 'assistant', content: '' }), accounting, '[DONE]'];
  const good = await collect(values);
  assert.equal(good.status, 'completed'); assert.equal(good.strictCompletionPassed, true);
  assert.equal(good.completionSource, 'application_normalized_expiry_terminal_with_metadata_tail');
  assert.equal(good.diagnostic.metadataOnlyTailCount, 2);
  assert.equal(good.diagnostic.meaningfulAfterTerminalCount, 0);
  assert.equal((await collect(values, 'application-normalized')).status, 'failed');
  const strictExpiry = chunk({ audio: { expires_at: 2000000000 } });
  assert.equal((await collect([audio, strictExpiry, tail, accounting, '[DONE]'], 'sdk')).status, 'failed');
});

test('ordered safe shapes bind every decoded chunk to retained PCM offsets and hashes', async () => {
  const secondAudio = chunk({ audio: { data: 'IAA=', transcript: ' Com você.' } });
  const result = await collect([audio, secondAudio, expiry, tail, accounting, '[DONE]']);
  assert.equal(result.status, 'completed'); assert.equal(result.diagnostic.choiceEventShapes.length, 5);
  const shapes = result.diagnostic.choiceEventShapes;
  assert.deepEqual(shapes.map(value => value.eventIndex), [1, 2, 3, 4, 5]);
  for (const shape of shapes.filter(value => value.decodedAudioBytes > 0)) {
    const bytes = result.rawPcm.subarray(shape.decodedByteOffsetBefore, shape.decodedByteOffsetAfter);
    assert.equal(bytes.length, shape.decodedAudioBytes); assert.equal(sha(bytes), shape.decodedAudioSha256);
    assert.equal(shape.audioPayloadPresent, true);
  }
  assert.equal(shapes[3].afterCompletion, true); assert.equal(shapes[3].idMatchesPrior, true);
  assert.equal(shapes[3].applicationMetadataTail, true); assert.equal(shapes[3].audioPayloadPresent, false);
  assert.equal(shapes[4].accountingOnly, true); assert.equal(shapes[4].usagePresent, true);
  assert.doesNotMatch(JSON.stringify(shapes), /observed-audio|Estou aqui|Com você/);
});

test('payload, unknowns, changed IDs, expiry, message, tool/refusal and non-stop tails fail closed', async () => {
  const illegal = [
    chunk({ audio: { data: 'EAA=' } }), chunk({ audio: { data: null } }), chunk({ audio: { transcript: '' } }),
    chunk({ audio: { transcript: 'Extra words' } }), chunk({ audio: { id: 'changed' } }),
    chunk({ audio: { id: 'observed-audio', expires_at: 2000000000 } }),
    chunk({ audio: { id: 'observed-audio', unknown: null } }), chunk({ content: 'More spoken text' }),
    chunk({ role: 'user', content: '' }), chunk({ role: null, content: '' }),
    chunk({ role: 'assistant', content: '', unknown: null }), chunk({ refusal: null }), chunk({ tool_calls: [] }),
    chunk({}, { message: {} }), chunk({}, { finish_reason: 'length' }), chunk({}, { native_finish_reason: 'error' }),
  ];
  for (const bad of illegal) {
    const value = await collect([audio, expiry, bad, accounting, '[DONE]']);
    assert.equal(value.status, 'failed'); assert.equal(value.strictCompletionPassed, false);
    assert.ok(value.rawPcm.length); assert.equal(value.diagnostic.choiceEventShapes.length, 4);
  }
});

test('full shape bound is explicit and prevents accepting an incomplete diagnostic record', async () => {
  const values = [audio, expiry, ...Array.from({ length: 255 }, () => chunk({ role: 'assistant', content: '' })), accounting, '[DONE]'];
  const result = await collect(values);
  assert.equal(result.status, 'failed'); assert.equal(result.code, 'choice_shape_bound');
  assert.equal(result.diagnostic.choiceEventShapes.length, 256); assert.equal(result.diagnostic.choiceEventShapesTruncated, true);
});

test('one Portuguese admission pins three failures and cannot rewrite historical files', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 's2s-pt-tail-'));
  try {
    const old = path.join(directory, 'old'); await mkdir(old);
    for (let i = 1; i <= 3; i++) await writeFile(path.join(old, `report${i}`), `unchanged${i}\n`);
    const proof = { firstReportSha256: PRIOR.firstReportSha256, secondReportSha256: PRIOR.secondReportSha256,
      thirdReportSha256: PRIOR.thirdReportSha256, firstAdmissionSha256: 'a'.repeat(64), secondAdmissionSha256: 'b'.repeat(64),
      thirdAdmissionSha256: 'c'.repeat(64), knownPriorCostUsd: .021584 };
    const admitted = path.join(directory, 'new'); const marker = await consumeTailAdmission(admitted, proof);
    assert.equal(marker.calls, 1); assert.equal(marker.locale, 'pt-BR'); assert.equal(marker.priorFailures.knownPriorCostUsd, .021584);
    await assert.rejects(consumeTailAdmission(admitted, proof), { code: 'EEXIST' });
    for (let i = 1; i <= 3; i++) assert.equal(await readFile(path.join(old, `report${i}`), 'utf8'), `unchanged${i}\n`);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test('all three exact actual failures validate read-only without consuming new admission',
  { skip: available ? false : 'ignored previous public audition receipts are absent' }, async () => {
    const values = await Promise.all(evidenceFiles.map(file => readFile(file)));
    const proof = validateTailEvidence(...values);
    assert.equal(proof.thirdReportSha256, PRIOR.thirdReportSha256); assert.equal(proof.knownPriorCostUsd, .021584);
    assert.deepEqual(await Promise.all(evidenceFiles.map(file => readFile(file))), values);
  });
