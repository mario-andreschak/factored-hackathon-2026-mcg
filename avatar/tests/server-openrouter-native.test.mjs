import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { NATIVE_AUDIO, validateNativeTurn, streamNativeTurn } from '../server/openrouter-native.mjs';
import { PublicError } from '../server/http.mjs';

const usage = { prompt_tokens: 105, completion_tokens: 101, total_tokens: 206, cost: .006,
  prompt_tokens_details: { audio_tokens: 41 }, completion_tokens_details: { audio_tokens: 78 } };
const frame = delta => ({ id: 'stream-fixed', model: 'openai/gpt-audio', choices: [{ index: 0, delta, finish_reason: null }], usage: null });
const speech = () => frame({ audio: { id: 'audio-fixed', data: Buffer.from([1, 0, 2, 0]).toString('base64'), transcript: 'Estoy contigo.' } });
const expiry = () => frame({ role: 'assistant', content: '', audio: { expires_at: 2000000000 } });
const accounting = () => ({ ...frame({ role: 'assistant', content: '' }), usage });
const encode = value => `data: ${typeof value === 'string' ? value : JSON.stringify(value)}\r\n\r\n`;
function response(events, { fragment = false, suffix = '', bytes, cancel } = {}) {
  const data = bytes ?? new TextEncoder().encode(events.map(encode).join('') + suffix);
  return new Response(new ReadableStream({ start(controller) {
    if (fragment) for (const byte of data) controller.enqueue(Uint8Array.of(byte));
    else controller.enqueue(data);
    controller.close();
  }, ...(cancel ? { cancel } : {}) }), { headers: { 'Content-Type': 'text/event-stream' } });
}
class Sink extends EventEmitter {
  constructor({ blockAt = -1 } = {}) { super(); this.lines = []; this.blockAt = blockAt; this.destroyed = false; this.writableEnded = false; }
  writeHead(status, headers) { this.status = status; this.headers = headers; this.headersSent = true; }
  write(value) { this.lines.push(JSON.parse(value)); return this.lines.length !== this.blockAt; }
  end() { this.writableEnded = true; }
}
function wav(seconds = .1, rate = 24000) {
  const samples = Math.floor(seconds * rate), data = Buffer.alloc(44 + samples * 2);
  data.write('RIFF'); data.writeUInt32LE(data.length - 8, 4); data.write('WAVEfmt ', 8);
  data.writeUInt32LE(16, 16); data.writeUInt16LE(1, 20); data.writeUInt16LE(1, 22); data.writeUInt32LE(rate, 24);
  data.writeUInt32LE(rate * 2, 28); data.writeUInt16LE(2, 32); data.writeUInt16LE(16, 34); data.write('data', 36); data.writeUInt32LE(samples * 2, 40);
  return data.toString('base64');
}
const textTurn = { message: 'Necesito ayuda.', avatar: 'moss', locale: 'es' };
async function run(events, options = {}) {
  const sink = options.sink ?? new Sink(), controller = options.controller ?? new AbortController();
  const result = await streamNativeTurn(options.value ?? textTurn, { openrouterKey: 'fake-native-key' }, options.fetch ?? (() => response(events, options)), controller.signal, sink,
    { turnId: 'turn_1', ...options.context });
  return { sink, result };
}

test('native input accepts bounded mono WAV or text, rejects browser history/results and routing knobs', () => {
  assert.deepEqual(validateNativeTurn({ audio: wav(), format: 'wav', avatar: 'spark', locale: 'pt' }), { audio: wav(), format: 'wav', avatar: 'spark', locale: 'pt' });
  assert.deepEqual(validateNativeTurn({ message: ' Hola ', avatar: 'orbit' }), { message: 'Hola', avatar: 'orbit', locale: 'es' });
  for (const value of [
    { ...textTurn, history: [] }, { ...textTurn, backendResult: { reply: 'Inventado' } }, { ...textTurn, model: 'other' },
    { ...textTurn, audio: wav(), format: 'wav' }, { ...textTurn, locale: 'en' }, { ...textTurn, avatar: 'other' },
    { audio: wav(31), format: 'wav', avatar: 'moss' }, { audio: 'https://example.com/audio', format: 'wav', avatar: 'moss' },
    { ...textTurn, message: '\u0000' }, { ...textTurn, message: 'x'.repeat(4001) },
  ]) assert.throws(() => validateNativeTurn(value), PublicError);
});

test('native request pins provider/model/voice and supplies real audio plus server-only bounded context', async () => {
  const audio = wav();
  const { result, sink } = await run([speech(), expiry(), accounting(), '[DONE]'], {
    value: { audio, format: 'wav', avatar: 'orbit', locale: 'pt' },
    context: { history: [{ role: 'assistant', content: 'Ouvi você.' }], backendResult: { reply: 'Nenhuma ação foi tomada.', mode: 'flujo', status: 'completed' } },
    fetch: (url, options) => {
      assert.equal(url, NATIVE_AUDIO.endpoint); assert.equal(options.redirect, 'error');
      assert.equal(options.headers.Authorization, 'Bearer fake-native-key');
      const body = JSON.parse(options.body);
      assert.equal(body.model, 'openai/gpt-audio'); assert.deepEqual(body.audio, { voice: 'coral', format: 'pcm16' });
      assert.equal(body.max_tokens, 512); assert.equal(body.stream, true); assert.equal(body.tools, undefined);
      assert.deepEqual(body.provider, { only: ['openai'], order: ['openai'], allow_fallbacks: false });
      assert.match(body.messages[0].content, /Converse sempre em português do Brasil/);
      assert.deepEqual(body.messages[2], { role: 'user', content: [{ type: 'input_audio', input_audio: { data: audio, format: 'wav' } }] });
      assert.match(body.messages.at(-1).content, /Nenhuma ação foi tomada/);
      return response([speech(), expiry(), accounting(), '[DONE]']);
    },
  });
  assert.equal(result.completed, true); assert.equal(result.text, 'Estoy contigo.');
  assert.equal(sink.lines.at(-1).type, 'complete');
});

test('observed expiry and bare metadata tail qualify only after DONE and EOF, projecting bounded public fields', async () => {
  const { sink, result } = await run([speech(), expiry(), frame({ role: 'assistant', content: '' }), accounting(), '[DONE]'], { fragment: true });
  assert.equal(result.completed, true); assert.equal(result.text, 'Estoy contigo.'); assert.equal(result.samples, 2);
  assert.equal(result.completionSource, 'application_normalized_expiry_terminal_with_metadata_tail');
  assert.equal(sink.writableEnded, true); assert.equal(sink.status, 200);
  assert.deepEqual(sink.lines[0], { type: 'start', turnId: 'turn_1', sampleRate: 24000, sampleRateQualification: 'assumed' });
  assert.deepEqual(sink.lines.at(-1), { type: 'complete', turnId: 'turn_1', text: 'Estoy contigo.', samples: 2, usage: result.usage });
  const publicOutput = JSON.stringify(sink.lines);
  assert.ok(!publicOutput.includes('audio-fixed') && !publicOutput.includes('stream-fixed') && !publicOutput.includes('fake-native-key'));
});

test('trusted qualification callback precedes visible completion and never runs for failed output', async () => {
  const sink = new Sink(); let qualified = 0;
  const { result } = await run([speech(), expiry(), accounting(), '[DONE]'], { sink, context: { onQualifiedResult: result => {
    qualified++; assert.equal(result.completed, true); assert.equal(result.samples, 2);
    assert.ok(!sink.writableEnded && !sink.lines.some(item => item.type === 'complete'));
  } } });
  assert.equal(qualified, 1); assert.equal(result.completed, true); assert.equal(sink.lines.at(-1).type, 'complete');
  const failed = await run([speech(), expiry(), accounting()], { context: { onQualifiedResult: () => { qualified++; } } });
  assert.equal(failed.result.completed, false); assert.equal(qualified, 1);
});

test('trusted qualification callback failure withholds complete and never exposes internal exception details', async () => {
  const { result, sink } = await run([speech(), expiry(), accounting(), '[DONE]'], { context: { onQualifiedResult: () => {
    throw new Error('private ledger owner sentinel');
  } } });
  assert.equal(result.completed, false); assert.equal(sink.lines.at(-1).type, 'error');
  assert.ok(!sink.lines.some(item => item.type === 'complete') && !JSON.stringify(sink.lines).includes('sentinel'));
});

test('independent padded base64 chunks preserve exact PCM across odd byte boundaries', async () => {
  const chunks = [Buffer.from([17]), Buffer.from([0, 42]), Buffer.from([0])];
  const events = chunks.map((data, index) => frame({ audio: { ...(index === 0 ? { id: 'audio-fixed', transcript: 'Hola.' } : {}), data: data.toString('base64') } }));
  const { sink, result } = await run([...events, expiry(), accounting(), '[DONE]']);
  assert.equal(result.completed, true); assert.equal(result.samples, 2);
  assert.deepEqual(Buffer.concat(sink.lines.filter(item => item.type === 'audio').map(item => Buffer.from(item.data, 'base64'))), Buffer.from([17, 0, 42, 0]));
});

test('large provider audio is rechunked into bounded half-second NDJSON packets without changing samples', async () => {
  const pcm = Buffer.alloc(72_004); for (let offset = 0; offset < pcm.length; offset += 2) pcm.writeInt16LE((offset % 1024) - 512, offset);
  const { sink, result } = await run([frame({ audio: { id: 'audio-fixed', data: pcm.toString('base64'), transcript: 'Hola.' } }), expiry(), accounting(), '[DONE]']);
  const packets = sink.lines.filter(item => item.type === 'audio');
  assert.equal(result.completed, true); assert.equal(result.samples, pcm.length / 2); assert.equal(packets.length, 4);
  assert.ok(packets.every(item => Buffer.from(item.data, 'base64').length <= 24000 && JSON.stringify(item).length < 33_000));
  assert.deepEqual(Buffer.concat(packets.map(item => Buffer.from(item.data, 'base64'))), pcm);
});

test('native audio input requires positive reported input audio tokens before history qualification', async () => {
  const value = { audio: wav(), format: 'wav', avatar: 'moss', locale: 'es' };
  for (const audioTokens of [undefined, 0]) {
    const account = accounting(); account.usage = { ...usage, prompt_tokens_details: { audio_tokens: audioTokens } };
    const { result, sink } = await run([speech(), expiry(), account, '[DONE]'], { value });
    assert.equal(result.completed, false); assert.ok(!sink.lines.some(item => item.type === 'complete'));
  }
  assert.equal((await run([speech(), expiry(), accounting(), '[DONE]'], { value })).result.completed, true);
});

test('same already-observed ID metadata is allowed but changed ID, new expiry or late speech fails', async () => {
  const allowed = await run([speech(), expiry(), frame({ audio: { id: 'audio-fixed' }, role: 'assistant', content: null }), accounting(), '[DONE]']);
  assert.equal(allowed.result.completed, true);
  for (const delta of [
    { audio: { id: 'other' } }, { audio: { expires_at: 2000000001 } }, { audio: { data: 'AQA=' } },
    { audio: { transcript: 'Más.' } }, { audio: { id: 'audio-fixed', unknown: null } },
    { role: 'assistant', content: 'Más.' }, { refusal: null }, { tool_calls: null },
  ]) {
    const { result, sink } = await run([speech(), expiry(), frame(delta), accounting(), '[DONE]']);
    assert.equal(result.completed, false); assert.equal(sink.lines.at(-1).type, 'error');
    assert.ok(!sink.lines.some(item => item.type === 'complete'));
  }
});

test('a terminal marker requires identity, audio and caption observed earlier', async () => {
  for (const first of [frame({ audio: { id: 'audio-fixed', transcript: 'Hola.' } }), frame({ audio: { id: 'audio-fixed', data: 'AQA=' } }),
    frame({ audio: { data: 'AQA=', transcript: 'Hola.' } })]) {
    const { result } = await run([first, expiry(), accounting(), '[DONE]']);
    assert.equal(result.completed, false);
  }
});

test('explicit stop can finish a payload, but length/filter/native failure remains terminal failure', async () => {
  const stopped = speech(); stopped.choices[0].finish_reason = 'stop';
  assert.equal((await run([stopped, accounting(), '[DONE]'])).result.completed, true);
  for (const field of ['finish_reason', 'native_finish_reason']) for (const reason of ['length', 'content_filter', 'error', 'tool_calls', 'unknown']) {
    const bad = frame({}); bad.choices[0][field] = reason;
    const { result } = await run([speech(), bad, expiry(), accounting(), '[DONE]']);
    assert.equal(result.completed, false);
  }
  assert.equal((await run([stopped, frame({ audio: { transcript: 'Después.' } }), accounting(), '[DONE]'])).result.completed, false);
});

test('incomplete transport, full-message bypass, odd PCM and invalid UTF-8 cannot qualify history', async () => {
  const message = accounting(); message.choices[0].message = { audio: { data: 'AQA=' } };
  const cases = [
    [speech(), expiry(), accounting()], [speech(), expiry(), accounting(), '[DONE]', '[DONE]'],
    [speech(), expiry(), message, '[DONE]'], [speech(), expiry(), '[DONE]'],
    [frame({ audio: { id: 'audio-fixed', data: 'AQ==', transcript: 'Hola.' } }), expiry(), accounting(), '[DONE]'],
  ];
  for (const events of cases) assert.equal((await run(events)).result.completed, false);
  assert.equal((await run([], { bytes: Uint8Array.from([0xff, 0xfe]) })).result.completed, false);
  assert.equal((await run([speech(), expiry(), accounting(), '[DONE]'], { suffix: 'data: {}' })).result.completed, false);
});

test('oversized provider chunk or transcript and noncanonical base64 fail without raw provider error', async () => {
  for (const events of [
    [frame({ audio: { id: 'audio-fixed', data: 'AB==', transcript: 'Hola.' } }), expiry(), accounting(), '[DONE]'],
    [frame({ audio: { id: 'audio-fixed', data: 'AQA=', transcript: 'x'.repeat(4001) } }), expiry(), accounting(), '[DONE]'],
    [{ error: { message: 'raw-provider-secret-sentinel' }, choices: [] }],
  ]) {
    const { result, sink } = await run(events);
    assert.equal(result.completed, false); assert.ok(!JSON.stringify(sink.lines).includes('sentinel'));
  }
  assert.equal((await run([], { bytes: Buffer.alloc(NATIVE_AUDIO.chunkBytes + 1) })).result.completed, false);
});

test('cumulative captions cannot amplify a small provider stream beyond the client byte budget', async () => {
  const events = [speech(), ...Array.from({ length: 3000 }, () => frame({ audio: { transcript: 'a' } })), expiry(), accounting(), '[DONE]'];
  const { result, sink } = await run(events, { fetch: () => new Response(new ReadableStream({ start(controller) {
    for (const event of events) controller.enqueue(new TextEncoder().encode(encode(event)));
    controller.close();
  } }), { headers: { 'Content-Type': 'text/event-stream' } }) });
  assert.equal(result.completed, false); assert.equal(sink.lines.at(-1).type, 'error');
  assert.ok(sink.lines.reduce((total, value) => total + Buffer.byteLength(JSON.stringify(value) + '\n'), 0) <= 4 * 1024 * 1024);
  assert.ok(!sink.lines.some(item => item.type === 'complete'));
});

test('consumer backpressure blocks further upstream reads until drain', async () => {
  let reads = 0;
  const parts = [encode(speech()), encode(expiry()) + encode(accounting()) + encode('[DONE]')];
  const body = { getReader: () => ({ read: async () => { reads++; return parts.length ? { value: new TextEncoder().encode(parts.shift()), done: false } : { done: true }; }, cancel: async () => {}, releaseLock() {} }) };
  const sink = new Sink({ blockAt: 2 });
  const pending = run([], { sink, fetch: () => ({ ok: true, headers: new Headers({ 'content-type': 'text/event-stream' }), body }) });
  await new Promise(resolve => setTimeout(resolve, 15));
  assert.equal(reads, 1); assert.equal(sink.lines.length, 2); assert.equal(sink.listenerCount('drain'), 1);
  sink.emit('drain');
  const { result } = await pending;
  assert.equal(result.completed, true); assert.equal(reads, 3); assert.equal(sink.listenerCount('drain'), 0);
});

test('abort during backpressure stops upstream and removes listeners without completing history', async () => {
  const controller = new AbortController(), sink = new Sink({ blockAt: 1 });
  let canceled = 0, reads = 0;
  const body = { getReader: () => ({ read: async () => { reads++; return new Promise(() => {}); }, cancel: async () => { canceled++; }, releaseLock() {} }) };
  const pending = run([], { sink, controller, fetch: () => ({ ok: true, headers: new Headers({ 'content-type': 'text/event-stream' }), body }) });
  await new Promise(resolve => setTimeout(resolve, 5)); controller.abort();
  const { result } = await pending;
  assert.equal(result.completed, false); assert.equal(result.code, 'voice_interrupted'); assert.equal(reads, 0); assert.equal(canceled, 1);
  assert.equal(sink.listenerCount('drain'), 0); assert.equal(sink.listenerCount('close'), 0);
});

test('nonsettling reader cancellation is independently bounded and raw transport errors stay private', async () => {
  const body = { getReader: () => ({ read: async () => { throw new Error('raw transport password sentinel'); }, cancel: () => new Promise(() => {}), releaseLock() {} }) };
  const began = performance.now();
  const { result, sink } = await run([], { fetch: () => ({ ok: true, headers: new Headers({ 'content-type': 'text/event-stream' }), body }) });
  assert.equal(result.completed, false); assert.ok(performance.now() - began < 750);
  assert.ok(!JSON.stringify(sink.lines).includes('sentinel')); assert.equal(sink.writableEnded, true);
});

test('abort during a pending reader discards late output and bounded cleanup still completes', async () => {
  const controller = new AbortController(), sink = new Sink();
  let finishRead, canceled = 0, released = 0;
  const body = { getReader: () => ({ read: () => new Promise(resolve => { finishRead = resolve; }),
    cancel: async () => { canceled++; }, releaseLock() { released++; } }) };
  const pending = run([], { sink, controller, fetch: () => ({ ok: true, headers: new Headers({ 'content-type': 'text/event-stream' }), body }) });
  await new Promise(resolve => setTimeout(resolve, 5)); controller.abort();
  const { result } = await pending;
  finishRead({ done: false, value: new TextEncoder().encode(encode(speech())) });
  await Promise.resolve();
  assert.equal(result.completed, false); assert.equal(canceled, 1); assert.equal(released, 1);
  assert.deepEqual(sink.lines.map(item => item.type), ['start']);
});

test('a reader that aborts synchronously before returning a rejected promise cannot leak an unhandled rejection', async () => {
  const controller = new AbortController(); let canceled = 0;
  const body = { getReader: () => ({ read() { controller.abort(); return Promise.reject(new Error('private rejected reader sentinel')); },
    cancel: async () => { canceled++; }, releaseLock() {} }) };
  const { result, sink } = await run([], { controller, fetch: () => ({ ok: true, headers: new Headers({ 'content-type': 'text/event-stream' }), body }) });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(result.completed, false); assert.equal(result.code, 'voice_interrupted'); assert.equal(canceled, 1);
  assert.deepEqual(sink.lines.map(item => item.type), ['start']);
});

test('already aborted input never dispatches and a fetch ignoring later abort has its late body canceled', async () => {
  const already = new AbortController(); already.abort(); let calls = 0;
  await assert.rejects(run([], { controller: already, fetch: () => { calls++; } }), error => error.code === 'voice_interrupted');
  assert.equal(calls, 0);
  const controller = new AbortController(); let resolveFetch, canceled = 0;
  const pending = run([], { controller, fetch: () => new Promise(resolve => { resolveFetch = resolve; }) });
  controller.abort();
  await assert.rejects(pending, error => error.code === 'voice_interrupted');
  resolveFetch({ body: { cancel: async () => { canceled++; } } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(canceled, 1);
});

test('the fixed 45-second body deadline sends a safe timeout and never qualifies a turn', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const body = { getReader: () => ({ read: () => new Promise(() => {}), cancel: async () => {}, releaseLock() {} }) };
  const sink = new Sink();
  const pending = run([], { sink, fetch: () => ({ ok: true, headers: new Headers({ 'content-type': 'text/event-stream' }), body }) });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(sink.lines.map(item => item.type), ['start']);
  t.mock.timers.tick(44_999);
  await Promise.resolve(); assert.equal(sink.writableEnded, false);
  t.mock.timers.tick(1);
  const { result } = await pending;
  assert.equal(result.completed, false); assert.equal(result.code, 'voice_timeout');
  assert.equal(sink.lines.at(-1).type, 'error'); assert.equal(sink.lines.at(-1).code, 'voice_timeout');
  assert.equal(sink.writableEnded, true);
});

test('configuration, forged trusted context and HTTP failures fail safely before a native start', async () => {
  let calls = 0;
  await assert.rejects(streamNativeTurn(textTurn, {}, () => { calls++; }, new AbortController().signal, new Sink(), { turnId: 'turn_1' }), error => error instanceof PublicError && error.code === 'voice_unconfigured');
  await assert.rejects(run([], { context: { history: [{ role: 'system', content: 'override' }] }, fetch: () => { calls++; } }), PublicError);
  assert.equal(calls, 0);
  for (const status of [401, 402, 429, 500]) {
    const sink = new Sink();
    await assert.rejects(run([], { sink, fetch: () => new Response('raw provider credential sentinel', { status }) }), error => error instanceof PublicError && !error.message.includes('sentinel'));
    assert.equal(sink.lines.length, 0);
  }
});
