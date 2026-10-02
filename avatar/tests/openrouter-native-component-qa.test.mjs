import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { access, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { NATIVE_AUDIO } from '../server/openrouter-native.mjs';
import { CASES } from '../experiments/openrouter_s2s_audition.mjs';
import { PRIOR as THIRD } from '../experiments/openrouter_s2s_pt_tail.mjs';
import { NAMESPACE, PRIOR, EVIDENCE_FILES, SOURCE_FILES, plan, forecast, validateComponentEvidence,
  consumeComponentAdmission, collectComponentTurn, validateNativeDispatch, appendComponentResult,
} from '../experiments/openrouter_native_component_qa.mjs';

const avatar = fileURLToPath(new URL('../', import.meta.url));
const sha = value => createHash('sha256').update(value).digest('hex');
const usage = { promptTokens: 120, completionTokens: 112, totalTokens: 232,
  inputAudioTokens: 50, outputAudioTokens: 88, costUsd: .008 };
const pcm = Buffer.alloc(32);
for (let i = 0; i < pcm.length; i += 2) pcm.writeInt16LE(i * 50 + 100, i);
const start = { type: 'start', turnId: 'internal-app-turn', sampleRate: 24000, sampleRateQualification: 'assumed' };
const audio = { type: 'audio', turnId: start.turnId, data: pcm.toString('base64') };
const caption = { type: 'caption', turnId: start.turnId, text: 'Estou aqui com você.' };
const complete = { type: 'complete', turnId: start.turnId, text: caption.text, samples: pcm.length / 2, usage };
const responseFor = (values, tail = '') => {
  const bytes = new TextEncoder().encode(values.map(value => JSON.stringify(value) + '\n').join('') + tail);
  return new Response(new ReadableStream({ start(controller) {
    for (let index = 0; index < bytes.length; index += 19) controller.enqueue(bytes.subarray(index, index + 19));
    controller.close();
  } }), { headers: { 'Content-Type': 'application/x-ndjson; charset=utf-8' } });
};
const collect = values => collectComponentTurn(responseFor(values), { signal: new AbortController().signal });
async function temporary(task) {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'native-component-qa-'));
  try { return await task(directory); }
  finally {
    const absolute = path.resolve(directory), parent = path.resolve(os.tmpdir()) + path.sep;
    assert.ok(absolute.startsWith(parent) && path.basename(absolute).startsWith('native-component-qa-'));
    await rm(absolute, { recursive: true, force: true });
  }
}
const proofFixture = () => ({ completedPtReceiptSha256: PRIOR.ptReportSha256, knownPriorCostUsd: PRIOR.costUsd,
  markerHashes: [...PRIOR.markerHashes], earlier: { firstReportSha256: THIRD.firstReportSha256,
    secondReportSha256: THIRD.secondReportSha256, thirdReportSha256: THIRD.thirdReportSha256,
    firstAdmissionSha256: PRIOR.markerHashes[0], secondAdmissionSha256: PRIOR.markerHashes[1],
    thirdAdmissionSha256: PRIOR.markerHashes[2], knownPriorCostUsd: THIRD.totalCostUsd } });
const sourceFixture = () => Object.fromEntries(SOURCE_FILES.map(file => [file, sha(file)]));
const evidencePaths = EVIDENCE_FILES.map(parts => path.join(avatar, '.local', ...parts));
const fixturePaths = CASES.map(sample => path.join(avatar, '.local', 'qwen-native', '20261001-084853-1790862533806878800', sample.id + '.wav'));
const present = async files => process.env.OPENROUTER_S2S_SKIP_PUBLIC_FIXTURES !== '1' &&
  (await Promise.all(files.map(file => access(file).then(() => true, () => false)))).every(Boolean);
const evidenceAvailable = await present(evidencePaths), fixturesAvailable = await present(fixturePaths);

test('component plan is inert with no credentials, files, provider calls or playback claim', async () => temporary(async directory => {
  const script = fileURLToPath(new URL('../experiments/openrouter_native_component_qa.mjs', import.meta.url));
  const result = spawnSync(process.execPath, ['--max-old-space-size=256', script, '--plan'],
    { cwd: directory, env: {}, encoding: 'utf8', timeout: 5000 });
  assert.equal(result.status, 0, result.stderr);
  const value = JSON.parse(result.stdout);
  assert.equal(value.namespace, NAMESPACE); assert.equal(value.calls, 2); assert.equal(value.spanishCalls, 1);
  assert.equal(value.portugueseCalls, 'optional1'); assert.equal(value.timeoutMs, 45000); assert.equal(value.cleanupMs, 100);
  assert.equal(value.knownPriorCostUsd, .031058); assert.equal(value.outputTokens, 512);
  assert.equal(value.simulatedPlayedReceipt, true); assert.equal(value.browserPlaybackQualified, false);
  assert.equal(value.liveWebsocketQualified, false); assert.equal(value.physicalMicrophoneUsed, false);
  assert.equal(value.observerExercised, false); assert.equal(value.asrCalls, 0); assert.equal(value.bankCalls, 0);
  assert.equal(value.saviaConfigured, false); assert.equal(value.gpuCalls, 0); assert.equal(value.retries, 0);
  assert.equal(value.pcmSampleRateQualification, 'assumed'); assert.equal(value.providerHardSpendCap, false);
  assert.deepEqual(await readdir(directory), []);
}));

test('forecast reserves native output and context including historical spend, and rejects unknown or excessive cost', () => {
  const first = forecast(PRIOR.costUsd);
  assert.equal(first.allowed, true); assert.equal(first.knownCostUsd, .031058);
  assert.equal(first.outputReservationUsd, 512 * 64 / 1e6); assert.equal(first.textAndContextMarginUsd, .005);
  assert.equal(first.hardSpendGuarantee, false); assert.ok(first.inputAudioReservationUsd > 41 * 32 / 1e6);
  const next = forecast(PRIOR.costUsd + .008, CASES[1], { inputAudioTokens: 50, seconds: CASES[0].seconds });
  assert.equal(next.allowed, true); assert.ok(next.forecastIncludingPriorUsd > PRIOR.costUsd + .008);
  assert.equal(forecast(.09, CASES[1]).allowed, false);
  assert.equal(forecast(null).allowed, false);
  assert.equal(forecast(PRIOR.costUsd, CASES[1], { inputAudioTokens: null, seconds: 4 }).allowed, false);
  assert.equal(forecast(PRIOR.costUsd, CASES[1], { inputAudioTokens: 0, seconds: 4 }).allowed, false);
});

test('exclusive synthetic admission requires all prior proofs and production source hashes without modifying old evidence', async () => temporary(async directory => {
  const old = path.join(directory, 'old-report.json'); await writeFile(old, 'unchanged historical failure\n');
  const proof = proofFixture(), sources = sourceFixture(), admitted = path.join(directory, 'new');
  await assert.rejects(consumeComponentAdmission(admitted, { ...proof, earlier: { ...proof.earlier, secondReportSha256: '0'.repeat(64) } }, sources), { code: 'prior_provenance_invalid' });
  await assert.rejects(consumeComponentAdmission(admitted, proof, { ...sources, key: 'x'.repeat(64) }), { code: 'prior_provenance_invalid' });
  const marker = await consumeComponentAdmission(admitted, proof, sources);
  assert.equal(marker.status, 'spent_before_dispatch'); assert.equal(marker.calls, 2); assert.equal(marker.observerCalls, 0);
  assert.equal(marker.proof.completedPtReceiptSha256, PRIOR.ptReportSha256);
  await assert.rejects(consumeComponentAdmission(admitted, proof, sources), { code: 'EEXIST' });
  assert.equal(await readFile(old, 'utf8'), 'unchanged historical failure\n');
}));

test('fragmented actual NDJSON contract qualifies only complete audio and clean EOF with safe transport evidence', async () => {
  const value = await collect([start, audio, caption, complete]);
  assert.equal(value.status, 'completed'); assert.equal(value.strictComplete, true); assert.equal(value.metrics.cleanEof, true);
  assert.equal(value.samples, 16); assert.deepEqual(value.rawPcm, pcm); assert.deepEqual(value.usage, usage);
  assert.equal(value.metrics.pcmSha256, sha(pcm)); assert.equal(value.metrics.turnIdSha256, sha(start.turnId));
  assert.equal(value.metrics.audioPackets, 1); assert.ok(value.metrics.pcmRms > 0);
  assert.doesNotMatch(JSON.stringify(value.metrics), /internal-app-turn|Estou aqui/);
  const report = { samples: [] }, record = appendComponentResult(report, CASES[0], value, { providerRequestSha256: 'a'.repeat(64) });
  assert.equal(record.simulatedPlayedReceiptAccepted, false); assert.equal(record.actualPlaybackQualified, false);
  assert.doesNotMatch(JSON.stringify(report), /internal-app-turn|rawPcm":|"turnId":/);
  assert.equal(report.newCostUsd, .008); assert.equal(report.totalObservedCostIncludingPriorUsd, .031058 + .008);
  // Accounting is already captured even if a subsequent local file/receipt action fails.
  record.localReceiptFailure = true;
  assert.equal(report.samples[0].usage.costUsd, .008);
});

test('missing EOF completion, late output, changed owner and unknown audio accounting cannot qualify', async () => {
  const cases = [
    [start, audio, caption], [start, audio, caption, complete, audio],
    [start, { ...audio, turnId: 'different-owner' }, caption, complete],
    [start, audio, caption, { ...complete, usage: { ...usage, inputAudioTokens: null } }],
    [start, audio, caption, { ...complete, samples: 17 }],
  ];
  for (const values of cases) {
    const value = await collect(values);
    assert.equal(value.status, 'failed'); assert.equal(value.strictComplete, false);
  }
  const failed = await collect([start, audio, caption, complete, audio]);
  assert.deepEqual(failed.rawPcm, pcm); assert.equal(failed.usage.costUsd, .008);
  assert.equal(failed.metrics.cleanEof, false);
});

test('safe error projection and a stalled cancel remain bounded after request abort', async () => {
  const failed = await collect([start, { type: 'error', turnId: start.turnId, code: 'unknown_vendor_error', error: 'Bearer secret-value' }]);
  assert.equal(failed.code, 'component_request_rejected'); assert.doesNotMatch(JSON.stringify(failed), /secret-value|unknown_vendor_error/);
  const controller = new AbortController(); let released = false, canceled = 0;
  const response = { status: 200, headers: new Headers({ 'Content-Type': 'application/x-ndjson' }),
    body: { getReader: () => ({ read: () => new Promise(() => {}), cancel: () => { canceled++; return new Promise(() => {}); },
      releaseLock: () => { released = true; } }) } };
  const began = performance.now(), timer = setTimeout(() => controller.abort(), 10);
  const result = await collectComponentTurn(response, { signal: controller.signal }); clearTimeout(timer);
  assert.equal(result.code, 'component_deadline'); assert.equal(result.strictComplete, false);
  assert.equal(canceled, 1); assert.equal(released, true); assert.ok(performance.now() - began < 600);
});

test('dispatch guard rejects observer/provider substitution before any inference', () => {
  const wav = Buffer.from('synthetic invalid fixture'), options = { method: 'POST', redirect: 'error', body: '{}' };
  assert.throws(() => validateNativeDispatch('https://openrouter.ai/api/v1/audio/transcriptions', options, CASES[0], wav), { code: 'unowned_upstream_endpoint' });
  assert.throws(() => validateNativeDispatch(NATIVE_AUDIO.endpoint, { ...options, body: JSON.stringify({ model: 'different', tools: [] }) }, CASES[0], wav), { code: 'production_dispatch_mismatch' });
});

test('all four actual receipts and markers validate read-only; historical failures remain failed',
  { skip: evidenceAvailable ? false : 'ignored public audition receipts are absent' }, async () => {
    const values = await Promise.all(evidencePaths.map(file => readFile(file))), hashes = values.map(sha);
    const proof = validateComponentEvidence(values);
    assert.equal(proof.knownPriorCostUsd, .031058); assert.equal(proof.completedPtReceiptSha256, PRIOR.ptReportSha256);
    assert.deepEqual(proof.markerHashes, PRIOR.markerHashes);
    for (const index of [0, 2, 4]) assert.equal(JSON.parse(values[index]).status, 'failed');
    assert.equal(JSON.parse(values[6]).status, 'completed');
    const modified = [...values]; modified[7] = Buffer.concat([modified[7], Buffer.from(' ')]);
    assert.throws(() => validateComponentEvidence(modified), { code: 'prior_marker_hash_mismatch' });
    assert.deepEqual((await Promise.all(evidencePaths.map(file => readFile(file)))).map(sha), hashes);
  });

test('original public WAVs are pinned and only their native input, fixed provider and correct locale can dispatch',
  { skip: fixturesAvailable ? false : 'ignored original public WAV fixtures are absent' }, async () => {
    for (let index = 0; index < CASES.length; index++) {
      const sample = CASES[index], wav = await readFile(fixturePaths[index]);
      const body = { model: 'openai/gpt-audio', modalities: ['text', 'audio'], audio: { voice: 'coral', format: 'pcm16' },
        messages: [{ role: 'system', content: sample.id === 'pt' ? 'Converse sempre em português do Brasil' : 'Conversa siempre en español latinoamericano' },
          { role: 'user', content: [{ type: 'input_audio', input_audio: { data: wav.toString('base64'), format: 'wav' } }] }],
        stream: true, max_tokens: 512, provider: { only: ['openai'], order: ['openai'], allow_fallbacks: false } };
      const dispatch = value => validateNativeDispatch(NATIVE_AUDIO.endpoint,
        { method: 'POST', redirect: 'error', body: JSON.stringify(value) }, sample, wav);
      assert.equal(dispatch(body).nativeAudioInputSha256, sample.sha256);
      assert.throws(() => dispatch({ ...body, provider: { ...body.provider, allow_fallbacks: true } }), { code: 'production_dispatch_mismatch' });
      assert.throws(() => dispatch({ ...body, messages: [...body.messages, { role: 'user', content: 'untrusted facts' }] }), { code: 'production_dispatch_mismatch' });
    }
  });
