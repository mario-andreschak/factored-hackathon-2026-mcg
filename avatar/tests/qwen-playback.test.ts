import assert from 'node:assert/strict';
import test from 'node:test';
import {
  QwenPlayback, QWEN_PLAYBACK_RATE, QWEN_MAX_CHUNK_SAMPLES, QWEN_MAX_QUEUED_SAMPLES,
  QWEN_MAX_PENDING_SEGMENTS, QWEN_MAX_RESPONSE_IDS, QWEN_MAX_RESPONSE_SAMPLES,
  QWEN_OUTPUT_STALL_MS, type QwenPlaybackAck, type QwenPlaybackError,
} from '../src/qwenPlayback.ts';

class Timer {
  time = 0; serial = 0;
  jobs = new Map<number, { due: number; callback: () => void }>();
  callbacks: Array<() => void> = [];
  now = () => this.time;
  schedule = (callback: () => void, milliseconds: number) => {
    const id = ++this.serial;
    this.jobs.set(id, { callback, due: this.time + milliseconds }); this.callbacks.push(callback);
    return id;
  };
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
  readonly channel: Float32Array;
  constructor(readonly length: number, readonly sampleRate: number) { this.channel = new Float32Array(length); }
  get duration() { return this.length / this.sampleRate; }
  getChannelData(channel: number) { assert.equal(channel, 0); return this.channel; }
}
class Source {
  buffer: Buffer | null = null;
  onended: (() => void) | null = null;
  startTime = Infinity; endTime = Infinity;
  stops = 0; disconnected = false; ended = false;
  supplied?: Float32Array;
  connect() {}
  disconnect() { this.disconnected = true; }
  start(time: number) {
    assert.ok(this.buffer); this.startTime = time; this.endTime = time + this.buffer.duration;
    this.supplied = this.buffer.channel.slice();
  }
  stop() { this.stops++; this.ended = true; }
}
class Context {
  currentTime = 0; outputTime = 0; performanceTime = 1;
  baseLatency = 0; outputLatency = 0;
  state = 'running'; closeCalls = 0; resumeCalls = 0;
  destination = {}; nodes: Source[] = []; buffers: Buffer[] = [];
  analyser = { fftSize: 0, connected: false, disconnected: false,
    connect: () => { this.analyser.connected = true; }, disconnect: () => { this.analyser.disconnected = true; } };
  getOutputTimestamp: (() => { contextTime: number; performanceTime: number }) | undefined =
    () => ({ contextTime: this.outputTime, performanceTime: this.performanceTime });
  createAnalyser() { return this.analyser; }
  createBuffer(channels: number, samples: number, rate: number) {
    assert.equal(channels, 1); assert.equal(rate, 24_000);
    const buffer = new Buffer(samples, rate); this.buffers.push(buffer); return buffer;
  }
  createBufferSource() { const source = new Source(); this.nodes.push(source); return source; }
  async resume() { this.resumeCalls++; }
  async close() { this.closeCalls++; this.state = 'closed'; }
  setTime(rendered: number, output = rendered, ended = false) {
    this.currentTime = rendered; this.outputTime = output;
    if (ended) for (const source of this.nodes) if (!source.ended && source.endTime <= rendered) {
      source.ended = true; source.onended?.();
    }
  }
}
function fixture(onAck?: (ack: QwenPlaybackAck, player: QwenPlayback) => void) {
  const context = new Context(), timer = new Timer(), acks: QwenPlaybackAck[] = [], errors: QwenPlaybackError[] = [];
  const player = new QwenPlayback({ createContext: () => context as unknown as AudioContext, timer,
    onAck: ack => { acks.push(ack); onAck?.(ack, player); }, onError: error => errors.push(error) });
  return { context, timer, player, acks, errors };
}
function pcm(samples: number, value = 8192) {
  const bytes = new Uint8Array(samples * 2), view = new DataView(bytes.buffer);
  for (let i = 0; i < samples; i++) view.setInt16(i * 2, value, true);
  return bytes;
}
const expectedAck = (id: string, milliseconds: number): QwenPlaybackAck => ({
  type: 'playback.ack', response_id: id, item_id: `item_${id}`, played_ms: milliseconds, committed_ms: milliseconds,
});

test('ACK waits beyond onended for the final sample to pass the actual output clock', async () => {
  const { player, context, timer, acks } = fixture();
  assert.equal(player.begin('resp-one'), true); assert.equal(player.enqueue('resp-one', pcm(2400)), true);
  assert.equal(player.done('resp-one'), true); assert.equal(acks.length, 0);
  context.setTime(.125, .075, true);
  assert.equal(context.nodes[0].disconnected, true); assert.equal(player.cursor('resp-one')?.playedSamples, 1200);
  assert.equal(acks.length, 0); assert.ok(timer.jobs.size);
  context.setTime(.2, .125 - 1 / QWEN_PLAYBACK_RATE); timer.advance(20);
  assert.equal(player.cursor('resp-one')?.playedSamples, 2399); assert.equal(acks.length, 0);
  context.setTime(.21, .125); timer.advance(20);
  assert.deepEqual(acks, [expectedAck('resp-one', 100)]); assert.equal(player.queuedSamples, 0);
  assert.equal(player.pendingSegments, 0); assert.equal(timer.jobs.size, 0);
  await player.close();
});

test('synchronous cancellation after generation.done counts only played samples and tombstones late audio', async () => {
  const { player, context, acks } = fixture();
  player.begin('old'); player.enqueue('old', pcm(2400)); player.enqueue('old', pcm(2400)); player.done('old');
  const oldEnded = context.nodes[0].onended!;
  context.setTime(.2, .1);
  assert.deepEqual(player.clear('old'), expectedAck('old', 75));
  assert.deepEqual(acks, [expectedAck('old', 75)]); assert.equal(player.queuedSamples, 0);
  assert.ok(context.nodes.every(node => node.stops === 1 && node.disconnected && node.buffer === null));
  assert.equal(player.isSuppressed('old'), true); assert.equal(player.begin('old'), false);
  assert.equal(player.enqueue('old', pcm(100)), false); assert.equal(player.done('old'), false);
  oldEnded(); assert.equal(acks.length, 1); assert.equal(player.clear('old'), undefined);
  assert.equal(player.begin('new'), true); player.enqueue('new', pcm(100));
  assert.equal(context.nodes.at(-1)?.startTime, .225);
  await player.close();
});

test('cancellation before playback acknowledges zero; cancellation before created adds no unknown-item ACK', async () => {
  const { player, acks, context } = fixture();
  player.begin('queued'); player.enqueue('queued', pcm(2400));
  assert.deepEqual(player.clear('queued'), expectedAck('queued', 0)); assert.equal(context.nodes[0].stops, 1);
  assert.equal(player.clear('future'), undefined); assert.equal(player.isSuppressed('future'), true);
  assert.equal(player.begin('future'), false); assert.equal(player.enqueue('future', pcm(2)), false);
  assert.deepEqual(acks, [expectedAck('queued', 0)]);
  await player.close();
});

test('clearing an old response preserves already scheduled new response audio and its immutable ACK identity', async () => {
  const { player, context, acks, timer } = fixture();
  player.begin('old'); player.enqueue('old', pcm(2400)); player.done('old');
  player.begin('new'); player.enqueue('new', pcm(2400)); player.done('new');
  context.setTime(.05, .025); player.clear('old');
  assert.equal(context.nodes[0].stops, 1); assert.equal(context.nodes[1].stops, 0);
  assert.equal(context.nodes[1].startTime, .125); assert.equal(player.queuedSamples, 2400);
  context.setTime(.25, .225); timer.advance(20);
  assert.deepEqual(acks, [expectedAck('old', 0), expectedAck('new', 100)]);
  assert.equal(player.begin('new'), false);
  await player.close();
});

test('separated PCM intervals exclude underrun silence from the played cursor', async () => {
  const { player, context, acks } = fixture();
  player.begin('gap'); player.enqueue('gap', pcm(1200));
  context.setTime(.1); assert.equal(player.cursor('gap')?.playedSamples, 1200);
  context.setTime(.5); player.enqueue('gap', pcm(1200)); player.done('gap');
  assert.equal(context.nodes[1].startTime, .525); assert.equal(acks.length, 0);
  context.setTime(.6, .575); player.cursor('gap');
  assert.deepEqual(acks, [expectedAck('gap', 100)]);
  assert.equal(player.cursor('gap')?.receivedSamples, 2400);
  await player.close();
});

test('PCM decoding preserves signed little-endian values and copies an offset caller view', async () => {
  const { player, context } = fixture();
  const bytes = new Uint8Array(12), view = new DataView(bytes.buffer);
  [-32768, -1, 0, 32767].forEach((value, i) => view.setInt16(2 + i * 2, value, true));
  player.begin('copy'); player.enqueue('copy', bytes.subarray(2, 10)); bytes.fill(0);
  assert.deepEqual([...context.nodes[0].supplied!], [-1, -1 / 32768, 0, 32767 / 32768]);
  assert.equal(context.buffers[0].sampleRate, QWEN_PLAYBACK_RATE);
  assert.equal(context.analyser.connected, true);
  await player.close();
});

test('latency fallback remains conservative when output timestamps are unavailable or throw', async () => {
  for (const throwing of [false, true]) {
    const { player, context, acks } = fixture();
    context.getOutputTimestamp = throwing ? () => { throw new Error('not implemented'); } : undefined;
    context.baseLatency = .05; context.outputLatency = .1;
    player.begin('fallback'); player.enqueue('fallback', pcm(2400)); player.done('fallback');
    context.setTime(.2); assert.equal(player.cursor('fallback')?.playedSamples, 600); assert.equal(acks.length, 0);
    context.setTime(.275); player.cursor('fallback'); assert.deepEqual(acks, [expectedAck('fallback', 100)]);
    await player.close();
  }
});

test('a stalled or suspended output clock fails closed at the finite boundary without claiming playback', async () => {
  const { player, context, timer, errors, acks } = fixture();
  context.state = 'suspended'; player.begin('stalled'); player.enqueue('stalled', pcm(2400)); player.done('stalled');
  timer.advance(QWEN_OUTPUT_STALL_MS - 1); assert.equal(player.isClosed, false); assert.equal(acks.length, 0);
  timer.advance(1); await player.close();
  assert.equal(player.isClosed, true); assert.deepEqual(errors, ['output_stalled']); assert.equal(acks.length, 0);
  assert.equal(context.closeCalls, 1); assert.equal(timer.jobs.size, 0); assert.equal(player.pendingSegments, 0);
});

test('close is idempotent and stale source/timer callbacks cannot ACK or affect a replacement session', async () => {
  const { player, context, timer, acks } = fixture();
  player.begin('closing'); player.enqueue('closing', pcm(2400)); player.done('closing');
  const oldEnded = context.nodes[0].onended!, oldPoll = timer.callbacks[0];
  const first = player.close(), second = player.close(); assert.equal(first, second); await first;
  assert.equal(context.closeCalls, 1); assert.equal(context.analyser.disconnected, true);
  assert.equal(context.nodes[0].stops, 1); assert.equal(timer.jobs.size, 0);
  oldEnded(); oldPoll(); context.setTime(100); assert.equal(acks.length, 0);
  assert.equal(player.begin('late'), false); assert.equal(player.enqueue('closing', pcm(1)), false);
  assert.equal(await player.resume(), false); assert.equal(player.cursor('closing'), undefined);
});

test('queue capacity accepts the exact sample bound and refuses overflow before further allocation', async () => {
  const { player, context, errors, acks } = fixture();
  player.begin('limit'); player.enqueue('limit', pcm(QWEN_MAX_CHUNK_SAMPLES));
  player.enqueue('limit', pcm(QWEN_MAX_QUEUED_SAMPLES - QWEN_MAX_CHUNK_SAMPLES));
  assert.equal(player.queuedSamples, QWEN_MAX_QUEUED_SAMPLES); assert.equal(context.nodes.length, 2);
  assert.equal(player.enqueue('limit', pcm(1)), false); await player.close();
  assert.deepEqual(errors, ['playback_capacity']); assert.equal(context.nodes.length, 2); assert.equal(acks.length, 0);
  assert.ok(context.nodes.every(node => node.stops === 1));
});

test('tiny deltas cannot grow source/metadata queues past the independent segment limit', async () => {
  const { player, context, errors } = fixture(); player.begin('tiny');
  for (let i = 0; i < QWEN_MAX_PENDING_SEGMENTS; i++) assert.equal(player.enqueue('tiny', pcm(1)), true);
  assert.equal(player.pendingSegments, QWEN_MAX_PENDING_SEGMENTS);
  assert.equal(player.enqueue('tiny', pcm(1)), false); await player.close();
  assert.equal(context.nodes.length, QWEN_MAX_PENDING_SEGMENTS); assert.deepEqual(errors, ['playback_capacity']);
});

test('fully played chunks release their metadata while total response duration stays bounded', async () => {
  const { player, context, errors } = fixture(); player.begin('long');
  let supplied = 0;
  while (supplied < QWEN_MAX_RESPONSE_SAMPLES) {
    const count = Math.min(QWEN_MAX_CHUNK_SAMPLES, QWEN_MAX_RESPONSE_SAMPLES - supplied);
    assert.equal(player.enqueue('long', pcm(count)), true); supplied += count;
    context.setTime(context.nodes.at(-1)!.endTime); player.cursor('long');
    assert.equal(player.queuedSamples, 0); assert.equal(player.pendingSegments, 0);
  }
  assert.equal(player.cursor('long')?.playedSamples, QWEN_MAX_RESPONSE_SAMPLES);
  assert.equal(player.enqueue('long', pcm(1)), false); await player.close();
  assert.deepEqual(errors, ['playback_capacity']);
});

test('response IDs and tombstones stay bounded across completely drained responses', async () => {
  const { player, errors } = fixture();
  for (let i = 0; i < QWEN_MAX_RESPONSE_IDS; i++) { assert.equal(player.begin(`r-${i}`), true); player.done(`r-${i}`); }
  assert.equal(player.begin('r-0'), false); assert.equal(player.begin('overflow'), false);
  await player.close(); assert.deepEqual(errors, ['playback_capacity']);
});

test('malformed PCM, unbound audio and audio after done fail without creating another source', async () => {
  const invalid: Array<[string, (player: QwenPlayback) => void, QwenPlaybackError]> = [
    ['odd bytes', player => { player.begin('bad'); player.enqueue('bad', new Uint8Array(3)); }, 'invalid_pcm'],
    ['empty delta', player => { player.begin('bad'); player.enqueue('bad', new Uint8Array()); }, 'invalid_pcm'],
    ['oversized chunk', player => { player.begin('bad'); player.enqueue('bad', pcm(QWEN_MAX_CHUNK_SAMPLES + 1)); }, 'invalid_pcm'],
    ['unknown response', player => { player.enqueue('bad', pcm(1)); }, 'response_not_started'],
    ['sealed response', player => { player.begin('bad'); player.done('bad'); player.enqueue('bad', pcm(1)); }, 'audio_after_done'],
    ['invalid ID', player => { player.begin('arbitrary\nID'); }, 'invalid_response'],
  ];
  for (const [label, operation, expected] of invalid) {
    const { player, context, errors } = fixture(); operation(player); await player.close();
    assert.deepEqual(errors, [expected], label); assert.equal(context.nodes.length, 0, label);
  }
});

test('output clock regression fails rather than estimating played samples from wall time', async () => {
  const { player, context, errors, acks } = fixture();
  player.begin('clock'); player.enqueue('clock', pcm(2400));
  context.setTime(.05); player.cursor('clock'); context.setTime(.04); player.cursor('clock');
  await player.close(); assert.deepEqual(errors, ['output_clock']); assert.equal(acks.length, 0);
});

test('a completed ACK callback can synchronously close the player without a subsequent queued source', async () => {
  const { player, context, acks } = fixture((_ack, owner) => { void owner.close(); });
  player.begin('finishing'); player.enqueue('finishing', pcm(2400)); player.done('finishing');
  player.begin('next'); context.setTime(.125);
  assert.equal(player.enqueue('next', pcm(2400)), false); await player.close();
  assert.deepEqual(acks, [expectedAck('finishing', 100)]); assert.equal(context.nodes.length, 1);
});

test('a completed response emits one full ACK and a later clear does not duplicate it', async () => {
  const { player, context, acks } = fixture();
  player.begin('complete'); player.enqueue('complete', pcm(2400)); player.done('complete');
  context.setTime(.125); player.cursor('complete'); player.done('complete');
  assert.deepEqual(player.clear('complete'), expectedAck('complete', 100));
  assert.deepEqual(acks, [expectedAck('complete', 100)]); assert.equal(player.isSuppressed('complete'), true);
  await player.close();
});
