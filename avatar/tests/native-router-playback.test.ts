import assert from 'node:assert/strict';
import test from 'node:test';
import { NativeRouterPlayback, NativeTurnProtocol, nativeAudioBytes, readNativeTurn, type NativePlayed } from '../src/nativeRouterPlayback.ts';

class Timer {
  time = 0; serial = 0; jobs = new Map<number, { due: number; callback: () => void }>();
  now = () => this.time;
  schedule = (callback: () => void, milliseconds: number) => { const id = ++this.serial; this.jobs.set(id, { due: this.time + milliseconds, callback }); return id; };
  cancel = (handle: unknown) => { this.jobs.delete(handle as number); };
  advance(milliseconds: number) {
    const target = this.time + milliseconds;
    while (true) {
      const next = [...this.jobs].sort((a, b) => a[1].due - b[1].due)[0];
      if (!next || next[1].due > target) break;
      this.time = next[1].due; this.jobs.delete(next[0]); next[1].callback();
    }
    this.time = target;
  }
}
class Buffer {
  channel: Float32Array;
  constructor(readonly length: number, readonly sampleRate: number) { this.channel = new Float32Array(length); }
  get duration() { return this.length / this.sampleRate; }
  getChannelData() { return this.channel; }
}
class Source {
  buffer: Buffer | null = null; onended: (() => void) | null = null;
  startTime = Infinity; endTime = Infinity; stops = 0; disconnected = false; supplied?: Float32Array;
  connect() {} disconnect() { this.disconnected = true; }
  start(time: number) { this.startTime = time; this.endTime = time + this.buffer!.duration; this.supplied = this.buffer!.channel.slice(); }
  stop() { this.stops++; }
}
class Context {
  currentTime = 0; outputTime = 0; state = 'running'; closeCalls = 0; destination = {}; nodes: Source[] = [];
  analyser = { fftSize: 256, connect() {}, disconnect() {} };
  getOutputTimestamp() { return { contextTime: this.outputTime, performanceTime: 1 }; }
  createAnalyser() { return this.analyser; }
  createBuffer(_channels: number, samples: number, rate: number) { assert.equal(rate, 24000); return new Buffer(samples, rate); }
  createBufferSource() { const source = new Source(); this.nodes.push(source); return source; }
  async resume() {} async close() { this.closeCalls++; this.state = 'closed'; }
  setTime(rendered: number, output = rendered) { this.currentTime = rendered; this.outputTime = output; }
}
function fixture() {
  const context = new Context(), timer = new Timer(), receipts: NativePlayed[] = []; let errors = 0;
  const player = new NativeRouterPlayback({ createContext: () => context as unknown as AudioContext, timer,
    onPlayed: receipt => receipts.push(receipt), onError: () => errors++ });
  return { player, context, timer, receipts, errors: () => errors };
}
function pcm(samples: number, value = 8192) {
  const bytes = new Uint8Array(samples * 2), view = new DataView(bytes.buffer);
  for (let i = 0; i < samples; i++) view.setInt16(i * 2, value, true);
  return bytes;
}
const tick = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const signal = () => new AbortController();
const start = { type: 'start', turnId: 'turn-1', sampleRate: 24000, sampleRateQualification: 'assumed' };
const audio = { type: 'audio', turnId: 'turn-1', data: 'ACAAIA==' };
const complete = { type: 'complete', turnId: 'turn-1', samples: 2, text: 'Hola.', usage: {} };

test('partial hardware playback never publishes a cancellation receipt; explicit cancel publishes exactly once', async () => {
  const { player, context, receipts } = fixture(); const controller = signal(); player.begin('partial');
  await player.enqueue('partial', pcm(2400), controller.signal);
  context.setTime(.2, .075); assert.equal(player.player.cursor('partial')?.playedSamples, 1200);
  assert.deepEqual(receipts, []);
  // Enforce the adapter contract even if a future output ledger reports progress.
  const internal = player.player as unknown as { options: { onAck(value: { response_id: string }): void } };
  internal.options.onAck({ response_id: 'partial' }); assert.deepEqual(receipts, []);
  const lateEnded = context.nodes[0].onended!; player.cancel('partial'); player.cancel('partial'); lateEnded();
  assert.deepEqual(receipts, [{ turnId: 'partial', playedSamples: 1200, complete: false }]);
  assert.equal(context.nodes[0].stops, 1); assert.equal(player.queuedSamples, 0);
  await assert.rejects(player.enqueue('partial', pcm(1), controller.signal), { name: 'AbortError' });
  await player.close(); assert.equal(receipts.length, 1);
});

test('full receipt waits for output timestamp after onended and emits one true receipt only', async () => {
  const { player, context, timer, receipts } = fixture(); player.begin('full'); const controller = signal();
  await player.enqueue('full', pcm(2400), controller.signal); let finished = false;
  const drain = player.drain('full', 2400, controller.signal).then(() => { finished = true; });
  context.setTime(.125, .075); context.nodes[0].onended?.(); timer.advance(20); await tick();
  assert.equal(finished, false); assert.deepEqual(receipts, []);
  context.setTime(.2, .125 - 1 / 24000); timer.advance(20); await tick(); assert.equal(finished, false);
  context.setTime(.21, .125); timer.advance(20); await drain;
  assert.deepEqual(receipts, [{ turnId: 'full', playedSamples: 2400, complete: true }]);
  player.cancel('full'); assert.equal(receipts.length, 1); await player.close();
});

test('cancelling a sealed but unplayed response wins over full completion and aborts drain', async () => {
  const { player, context, receipts } = fixture(); const controller = signal(); player.begin('cancel-drain');
  await player.enqueue('cancel-drain', pcm(2400), controller.signal);
  const drain = player.drain('cancel-drain', 2400, controller.signal); const rejected = assert.rejects(drain, { name: 'AbortError' });
  player.cancel('cancel-drain'); context.setTime(100); player.player.cursor('cancel-drain'); await rejected;
  assert.deepEqual(receipts, [{ turnId: 'cancel-drain', playedSamples: 0, complete: false }]); await player.close();
});

test('fast generation waits at five seconds and hardware consumption makes room without queue growth', async () => {
  const { player, context, timer, receipts } = fixture(); const controller = signal(); player.begin('fast');
  let written = false; const write = player.enqueue('fast', pcm(24000 * 6), controller.signal).then(() => { written = true; });
  await tick(); assert.equal(written, false); assert.equal(context.nodes.length, 5); assert.equal(player.queuedSamples, 120000);
  context.setTime(1.025); timer.advance(20); await write;
  assert.equal(context.nodes.length, 6); assert.equal(player.queuedSamples, 120000); assert.deepEqual(receipts, []);
  const drain = player.drain('fast', 144000, controller.signal); context.setTime(6.025); timer.advance(20); await drain;
  assert.deepEqual(receipts, [{ turnId: 'fast', playedSamples: 144000, complete: true }]); await player.close();
});

test('cancellation during backpressure stops scheduled output and never enqueues the remaining bytes', async () => {
  const { player, context, timer, receipts } = fixture(); const controller = signal(); player.begin('backpressure');
  const write = player.enqueue('backpressure', pcm(24000 * 7), controller.signal);
  const rejected = assert.rejects(write, { name: 'AbortError' }); await tick(); player.cancel('backpressure');
  timer.advance(500); await rejected;
  assert.equal(context.nodes.length, 5); assert.ok(context.nodes.every(node => node.stops === 1));
  assert.deepEqual(receipts, [{ turnId: 'backpressure', playedSamples: 0, complete: false }]); await player.close();
});

test('independently decoded odd delta bytes join into exact little-endian samples', async () => {
  const { player, context, timer, receipts } = fixture(); player.begin('odd'); const controller = signal();
  await player.enqueue('odd', nativeAudioBytes('AA=='), controller.signal); assert.equal(context.nodes.length, 0);
  await player.enqueue('odd', nativeAudioBytes('IADg'), controller.signal);
  assert.deepEqual([...context.nodes[0].supplied!], [.25, -.25]);
  const drain = player.drain('odd', 2, controller.signal); context.setTime(.1); timer.advance(20); await drain;
  assert.deepEqual(receipts, [{ turnId: 'odd', playedSamples: 2, complete: true }]); await player.close();
});

test('odd final sample and response duration beyond 31 seconds cannot become full heard receipts', async () => {
  const { player, receipts } = fixture(); player.begin('odd-final'); const controller = signal();
  await player.enqueue('odd-final', new Uint8Array([0]), controller.signal);
  await assert.rejects(player.drain('odd-final', 1, controller.signal), /invalid_native_stream/);
  player.begin('too-long'); await assert.rejects(player.enqueue('too-long', pcm(744001), controller.signal), /invalid_native_stream/);
  assert.deepEqual(receipts, []); await player.close();
});

test('teardown closes its context once and suppresses old output callbacks and receipts', async () => {
  const { player, context, timer, receipts } = fixture(); player.begin('closing'); const controller = signal();
  await player.enqueue('closing', pcm(2400), controller.signal); const ended = context.nodes[0].onended!;
  await player.close(); await player.close(); ended(); context.setTime(100); timer.advance(100);
  assert.equal(context.closeCalls, 1); assert.equal(context.nodes[0].stops, 1); assert.equal(timer.jobs.size, 0);
  assert.deepEqual(receipts, []); assert.equal(player.begin('late'), false);
});

test('wire validator binds one assumed-rate turn and requires exact PCM count and cumulative captions', () => {
  const parser = new NativeTurnProtocol(); parser.accept(start); parser.accept(audio);
  parser.accept({ type: 'caption', turnId: 'turn-1', text: 'Hola' }); parser.accept(complete); parser.finish();
  assert.throws(() => parser.accept(audio), /invalid_native_stream/);
  for (const value of [ { ...start, sampleRate: 16000 }, { ...start, sampleRateQualification: 'verified' }, { ...start, secret: 'extra' } ])
    assert.throws(() => new NativeTurnProtocol().accept(value), /invalid_native_stream/);
  const mismatch = new NativeTurnProtocol(); mismatch.accept(start); assert.throws(() => mismatch.accept({ ...audio, turnId: 'other' }), /invalid_native_stream/);
  const truncated = new NativeTurnProtocol(); truncated.accept(start); truncated.accept(audio); assert.throws(() => truncated.finish(), /invalid_native_stream/);
  assert.throws(() => truncated.accept({ ...complete, samples: 3 }), /invalid_native_stream/);
  const captions = new NativeTurnProtocol(); captions.accept(start); captions.accept({ type: 'caption', turnId: 'turn-1', text: 'Hola' });
  assert.throws(() => captions.accept({ type: 'caption', turnId: 'turn-1', text: 'Cambio' }), /invalid_native_stream/);
});

test('safe error envelope is accepted while malformed base64 and odd terminal byte counts fail', () => {
  const error = new NativeTurnProtocol(); error.accept(start);
  error.accept({ type: 'error', turnId: 'turn-1', code: 'upstream_failed', error: 'Mensaje seguro' }); error.finish();
  for (const data of ['Zg', 'Zh==', 'a===', 'AA==\n', '', '@@@@']) assert.throws(() => nativeAudioBytes(data), /invalid_native_stream/);
  const odd = new NativeTurnProtocol(); odd.accept(start); odd.accept({ ...audio, data: 'AA==' });
  assert.throws(() => odd.accept({ ...complete, samples: 1 }), /invalid_native_stream/);
});

test('NDJSON reader awaits downstream playback backpressure and requires clean terminal EOF', async () => {
  const bytes = new TextEncoder().encode([start, audio, complete].map(value => JSON.stringify(value)).join('\n') + '\n');
  const events: string[] = []; let release!: () => void; const blocked = new Promise<void>(resolve => { release = resolve; });
  const response = new Response(bytes, { headers: { 'Content-Type': 'application/x-ndjson' } });
  const read = readNativeTurn(response, signal().signal, async event => { events.push(event.type); if (event.type === 'audio') await blocked; });
  await tick(); assert.deepEqual(events, ['start', 'audio']); release(); await read; assert.deepEqual(events, ['start', 'audio', 'complete']);
  await assert.rejects(readNativeTurn(new Response(JSON.stringify(start) + '\n', { headers: { 'Content-Type': 'application/x-ndjson' } }), signal().signal, () => {}), /invalid_native_stream/);
});

test('abort cancels a stalled network reader and cannot deliver a stale subsequent audio event', async () => {
  let cancelled = false; const controller = signal();
  const body = new ReadableStream<Uint8Array>({ start(stream) { stream.enqueue(new TextEncoder().encode(JSON.stringify(start) + '\n')); }, cancel() { cancelled = true; } });
  const events: string[] = []; const read = readNativeTurn(new Response(body, { headers: { 'Content-Type': 'application/x-ndjson' } }), controller.signal, event => { events.push(event.type); });
  const rejected = assert.rejects(read, { name: 'AbortError' }); await tick(); controller.abort(); await rejected;
  assert.equal(cancelled, true); assert.deepEqual(events, ['start']);
});
