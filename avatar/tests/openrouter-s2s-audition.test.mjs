import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFile, mkdtemp, rm, access } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { plan, CASES, MODEL, VOICE, RATE, LIMITS, requestBody, validateFixture, sanitizeError,
  collectPcm, audition, pcmToWav, forecastSecond, consumeAdmission } from '../experiments/openrouter_s2s_audition.mjs';

const fixtureDirectory = fileURLToPath(new URL('../.local/qwen-native/20261001-084853-1790862533806878800/', import.meta.url));
const fixturesAvailable = process.env.OPENROUTER_S2S_SKIP_PUBLIC_FIXTURES !== '1' &&
  await Promise.all(CASES.map(sample => access(path.join(fixtureDirectory, sample.id + '.wav')).then(() => true, () => false)))
    .then(values => values.every(Boolean));
const optionalFixtures = fixturesAvailable ? false : 'ignored public audition WAVs are absent (or explicitly omitted for clean-checkout verification)';
const usage = { prompt_tokens: 200, completion_tokens: 128, total_tokens: 328, cost: .015,
  prompt_tokens_details: { audio_tokens: 100 }, completion_tokens_details: { audio_tokens: 100 } };
const encode = value => `data: ${JSON.stringify(value)}\n\n`;
function stream(values) {
  const bytes = new TextEncoder().encode(values.join(''));
  return new ReadableStream({ start(controller) {
    for (let offset = 0; offset < bytes.length; offset += 17) controller.enqueue(bytes.subarray(offset, offset + 17));
    controller.close();
  } });
}
function successEvents(finish = 'stop', finalUsage = usage) {
  return [encode({ choices: [{ index: 0, delta: { audio: { data: Buffer.from([16]).toString('base64'), transcript: 'Estoy ' } } }] }),
    encode({ choices: [{ index: 0, delta: { audio: { data: Buffer.from([0]).toString('base64'), transcript: 'contigo.' } } }] }),
    encode({ choices: [{ index: 0, delta: {}, finish_reason: finish }] }),
    encode({ choices: [], ...(finalUsage ? { usage: finalUsage } : {}) }), 'data: [DONE]\n\n'];
}

test('default plan is inert, native request-based and bounded without touching old calls', () => {
  const script = fileURLToPath(new URL('../experiments/openrouter_s2s_audition.mjs', import.meta.url));
  const result = spawnSync(process.execPath, [script, '--plan'], { encoding: 'utf8', timeout: 5000, env: {} });
  assert.equal(result.status, 0);
  const value = JSON.parse(result.stdout);
  assert.equal(value.status, 'prepared_not_dispatched'); assert.equal(value.calls, 2);
  assert.equal(value.outputTokens, 512); assert.equal(value.timeoutMs, 45000);
  assert.equal(value.voice, 'coral'); assert.equal(value.dedicatedTtsCalls, 0); assert.equal(value.asrCalls, 0);
  assert.equal(value.liveWebsocketQualified, false); assert.equal(value.physicalMicrophoneUsed, false);
  assert.equal(value.providerHardSpendCap, false); assert.equal(value.pcmPackagingRateQualified, false);
  assert.equal(value.worstOutputTokenChargeUsd, .065536);
});

test('two exact public native input fixtures use fixed model/provider/coral and pcm16 output', { skip: optionalFixtures }, async () => {
  for (const sample of CASES) {
    const wav = await readFile(path.join(fixtureDirectory, sample.id + '.wav'));
    validateFixture(wav, sample);
    const request = requestBody(sample, wav);
    assert.equal(request.model, MODEL); assert.deepEqual(request.audio, { voice: VOICE, format: 'pcm16' });
    assert.deepEqual(request.provider, { only: ['openai'], order: ['openai'], allow_fallbacks: false });
    assert.deepEqual(request.modalities, ['text', 'audio']); assert.equal(request.stream, true);
    assert.equal(request.max_tokens, LIMITS.outputTokens);
    const input = request.messages[1].content[1];
    assert.equal(input.type, 'input_audio'); assert.equal(input.input_audio.format, 'wav');
    assert.deepEqual(Buffer.from(input.input_audio.data, 'base64'), wav);
    assert.throws(() => validateFixture(Buffer.concat([wav, Buffer.from([0])]), sample), /fixture_hash/);
  }
});

test('bounded HTTP diagnostics retain parameter/code categories while dropping raw secrets and URLs', async t => {
  const value = { error: { code: 400, message: 'private-key https://private.invalid streaming audio',
    metadata: { provider_name: 'OpenAI', raw: JSON.stringify({ error: { type: 'invalid_request_error',
      code: 'unsupported_value', param: 'audio.format', message: 'wav is unsupported for streaming; private-key' } }) } } };
  const safe = sanitizeError(value, 400);
  assert.equal(safe.parameter, 'audio.format'); assert.equal(safe.upstreamCode, 'unsupported_value');
  assert.equal(safe.provider, 'OpenAI'); assert.ok(safe.reasonHints.includes('streaming'));
  assert.equal(safe.rawProviderBodyStored, false);
  assert.doesNotMatch(JSON.stringify(safe), /private|https:/);
  await t.test('HTTP rejection calls the fixed transport once', { skip: optionalFixtures }, async () => {
    const wav = await readFile(path.join(fixtureDirectory, 'es.wav'));
    let calls = 0;
    await assert.rejects(audition(async () => { calls++; return new Response(JSON.stringify(value), { status: 400 }); },
      'synthetic-test-key', CASES[0], wav), error => {
        assert.equal(error.code, 'provider_request_rejected'); assert.equal(error.diagnostic.parameter, 'audio.format');
        return true;
      });
    assert.equal(calls, 1);
  });
});

test('fragmented SSE independently decodes padded deltas and requires stop plus actual cost', async () => {
  const controller = new AbortController();
  const result = await collectPcm(stream(successEvents()), { signal: controller.signal });
  assert.deepEqual(result.rawPcm, Buffer.from([16, 0])); assert.equal(result.wav.readUInt32LE(24), RATE);
  assert.equal(result.caption, 'Estoy contigo.'); assert.equal(result.finishReason, 'stop');
  assert.equal(result.usage.costUsd, .015); assert.equal(result.usage.inputAudioTokens, 100);
  assert.equal(result.pcm.pitchRateQualified, false); assert.equal(result.audio.packagingRateQualified, false);
  await assert.rejects(collectPcm(stream(successEvents('length')), { signal: controller.signal }), /incomplete_audio_stream/);
  await assert.rejects(collectPcm(stream(successEvents('stop', null)), { signal: controller.signal }), /missing_usage_cost/);
  assert.throws(() => pcmToWav(Buffer.from([1])), /invalid_native_pcm/);
});

test('reader deadline and never-resolving cancellation stay bounded without a fixture', async t => {
  const stalled = new ReadableStream({ pull() { return new Promise(() => {}); }, cancel() { return new Promise(() => {}); } });
  const controller = new AbortController();
  const began = performance.now(), timer = setTimeout(() => controller.abort(), 10);
  try { await assert.rejects(collectPcm(stalled, { signal: controller.signal }), /request_deadline/); }
  finally { clearTimeout(timer); }
  assert.ok(performance.now() - began < 1000);
  await t.test('fetch and rejection-body deadlines do not retry', { skip: optionalFixtures }, async () => {
    const wav = await readFile(path.join(fixtureDirectory, 'es.wav'));
    let calls = 0;
    await assert.rejects(audition(() => { calls++; return new Promise(() => {}); }, 'synthetic-test-key', CASES[0], wav,
      { timeoutMs: 10 }), /request_deadline/);
    assert.equal(calls, 1);
    for (const contentType of ['text/event-stream', 'application/json', 'text/plain']) {
      const body = new ReadableStream({ pull() { return new Promise(() => {}); }, cancel() { return new Promise(() => {}); } });
      const response = new Response(body, { status: contentType === 'application/json' ? 400 : 200,
        headers: { 'Content-Type': contentType } });
      const started = performance.now();
      await assert.rejects(audition(async () => response, 'synthetic-test-key', CASES[0], wav, { timeoutMs: 10 }),
        /request_deadline|unexpected_content_type/);
      assert.ok(performance.now() - started < 1000);
    }
  });
});

test('second native request requires actual input-audio usage and conservative remaining-cost headroom', () => {
  const first = { costUsd: .015, inputAudioTokens: 100, outputAudioTokens: 100, promptTokens: 200, totalTokens: 328 };
  const forecast = forecastSecond(first);
  assert.equal(forecast.allowed, true); assert.equal(forecast.hardSpendGuarantee, false);
  assert.equal(forecast.outputReservationUsd, .032768); assert.equal(forecast.tokenMargin, 1.5);
  assert.ok(forecast.inputForecastUsd > 0);
  assert.equal(forecastSecond({ ...first, inputAudioTokens: null }).allowed, false);
  assert.equal(forecastSecond({ ...first, costUsd: .099 }).allowed, false);
});

test('a distinct exclusive admission preserves earlier native/WAV evidence and prevents a second attempt', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'openrouter-s2s-test-'));
  try {
    const value = { namespace: plan().namespace, status: 'spent_before_dispatch' };
    await consumeAdmission(directory, value);
    await assert.rejects(consumeAdmission(directory, value), { code: 'EEXIST' });
    assert.deepEqual(JSON.parse(await readFile(path.join(directory, 'native-pcm16-admitted.json'), 'utf8')), value);
  } finally { await rm(directory, { recursive: true, force: true }); }
});
