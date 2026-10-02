import test from 'node:test';
import assert from 'node:assert/strict';
import { audition, CASES, chooseModel, collectAudio, LIMITS, requestBody, validateWav } from '../openrouter_native_audition.mjs';

function wav(rate = 24_000) {
  const result = Buffer.alloc(48); result.write('RIFF'); result.writeUInt32LE(40, 4); result.write('WAVE', 8); result.write('fmt ', 12);
  result.writeUInt32LE(16, 16); result.writeUInt16LE(1, 20); result.writeUInt16LE(1, 22); result.writeUInt32LE(rate, 24);
  result.writeUInt32LE(rate * 2, 28); result.writeUInt16LE(2, 32); result.writeUInt16LE(16, 34); result.write('data', 36); result.writeUInt32LE(4, 40); return result;
}
function stream(parts) { return new ReadableStream({ start(controller) { for (const part of parts) controller.enqueue(Buffer.from(part)); controller.close(); } }); }
const frame = value => `data: ${JSON.stringify(value)}\r\n\r\n`;
function validStream(audio = wav()) { return frame({ choices: [{ index: 0, delta: { audio: { data: audio.toString('base64'), transcript: 'Hola, aquí estoy.' } } }] }) + frame({ choices: [{ delta: {}, finish_reason: 'stop' }] }) + 'data: [DONE]\n\n'; }

test('fixed requests remain native audio chat, bounded two-language text fixtures, no TTS/tools/input audio', () => {
  assert.equal(CASES.length, LIMITS.calls);
  for (const sample of CASES) {
    const body = requestBody('openai/gpt-audio', sample);
    assert.equal(body.max_tokens, 128); assert.equal(body.stream, true); assert.equal(body.audio.format, 'wav');
    assert.deepEqual(body.modalities, ['text', 'audio']); assert.deepEqual(body.provider, { allow_fallbacks: false });
    assert.equal(body.messages.length, 2); assert.equal(body.tools, undefined); assert.equal(body.input_audio, undefined);
  }
  assert.throws(() => requestBody('other/model', CASES[0]));
});

test('catalog chooses audio-capable 1.5 only if actually present, otherwise exact gpt-audio', () => {
  const model = id => ({ id, architecture: { input_modalities: ['text'], output_modalities: ['text', 'audio'] } });
  assert.equal(chooseModel([model('openai/gpt-audio')]), 'openai/gpt-audio');
  assert.equal(chooseModel([model('openai/gpt-audio'), model('openai/gpt-audio-1.5')]), 'openai/gpt-audio-1.5');
  assert.throws(() => chooseModel([{ ...model('openai/gpt-audio'), architecture: { output_modalities: ['text'] } }]));
});

test('WAV declared rate is validated rather than assumed; headerless PCM/truncation/stereo rejected', () => {
  assert.equal(validateWav(wav(16_000)).sampleRate, 16_000);
  assert.equal(validateWav(wav()).sampleRate, 24_000);
  assert.throws(() => validateWav(Buffer.alloc(48)));
  assert.throws(() => validateWav(wav().subarray(0, 47)));
  const stereo = wav(); stereo.writeUInt16LE(2, 22); assert.throws(() => validateWav(stereo));
});

test('SSE fragments decode native audio and provider caption without relying on chunk boundaries', async () => {
  const text = validStream(wav(16_000)), pieces = [];
  for (let i = 0; i < text.length; i += 3) pieces.push(text.slice(i, i + 3));
  const result = await collectAudio(stream(pieces));
  assert.equal(result.metadata.sampleRate, 16_000); assert.equal(result.caption, 'Hola, aquí estoy.'); assert.equal(result.finishReason, 'stop');
});

test('incomplete/error/base64/rawPCM streams fail closed without raw provider messages', async () => {
  await assert.rejects(collectAudio(stream([validStream().replace('data: [DONE]\n\n', '')])), /incomplete_audio_stream/);
  await assert.rejects(collectAudio(stream([frame({ error: { message: 'secret raw diagnostic' } })])), error => error.code === 'provider_stream_error' && !error.message.includes('secret'));
  await assert.rejects(collectAudio(stream([validStream(Buffer.alloc(48))])), /invalid_wav/);
  await assert.rejects(collectAudio(stream([frame({ choices: [{ delta: { audio: { data: 'bad=' } } }] })])), /invalid_audio_base64/);
});

test('upstream rejection makes one request, cancels body, never retries, never exposes diagnostic', async () => {
  let calls = 0, cancelled = false;
  await assert.rejects(audition(async (_url, options) => {
    calls++; assert.equal(options.redirect, 'error'); assert.equal(JSON.parse(options.body).audio.format, 'wav');
    return { ok: false, status: 400, body: { async cancel() { cancelled = true; } } };
  }, 'inert-test-secret', 'openai/gpt-audio', CASES[0]), error => error.code === 'provider_request_rejected' && error.status === 400);
  assert.equal(calls, 1); assert.equal(cancelled, true);
});
