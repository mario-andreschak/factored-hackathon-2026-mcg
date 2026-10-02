import assert from 'node:assert/strict';
import test from 'node:test';
import {
  InitialPcmReplay, INITIAL_REPLAY_RATE, INITIAL_FRAME_SAMPLES, INITIAL_FRAME_MS,
  MAX_INITIAL_SAMPLES, MAX_LIVE_PREROLL_SAMPLES, MAX_INITIAL_FRAME_GAP_MS,
} from '../src/audio/initialReplay.ts';
import { Pcm16Resampler } from '../src/audio.ts';
import { capturePacket, PCM_RATE, PCM_FRAME_SAMPLES } from '../src/experiments/personaplexProtocol.ts';

class Clock {
  time = 0;
  id = 0;
  pending = new Map();
  callbacks = [];
  now() { return this.time; }
  schedule(callback, delay) {
    assert.ok(delay > 0);
    const id = ++this.id;
    this.pending.set(id, { callback, due: this.time + delay });
    this.callbacks.push(callback);
    return id;
  }
  cancel(id) { this.pending.delete(id); }
  advance(ms) {
    const end = this.time + ms;
    while (true) {
      const next = [...this.pending.entries()].sort((a, b) => a[1].due - b[1].due)[0];
      if (!next || next[1].due > end) break;
      this.time = next[1].due; this.pending.delete(next[0]); next[1].callback();
    }
    this.time = end;
  }
  late(ms) {
    const next = [...this.pending.entries()].sort((a, b) => a[1].due - b[1].due)[0];
    assert.ok(next); this.time += ms; this.pending.delete(next[0]); next[1].callback();
  }
}

function fixture(samples, overrides = {}) {
  const clock = new Clock(), frames = [], live = [], errors = [];
  const replay = new InitialPcmReplay(samples, { clock,
    sendFrame: (frame, info) => { frames.push({ frame, info }); return true; },
    onLive: value => live.push(value), onError: code => errors.push(code), ...overrides });
  return { replay, clock, frames, live, errors };
}

test('normal replay uses actual native24k/1920 conventions and emits exactly one packet every80ms', () => {
  assert.equal(INITIAL_REPLAY_RATE, PCM_RATE); assert.equal(INITIAL_FRAME_SAMPLES, PCM_FRAME_SAMPLES);
  const clock = new Clock(), wire = [], handoffs = [], encoder = new Pcm16Resampler(PCM_RATE, PCM_RATE);
  const input = new Float32Array(PCM_FRAME_SAMPLES * 3).fill(.25);
  const replay = new InitialPcmReplay(input, { clock,
    sendFrame: (frame, info) => { wire.push({ packet: capturePacket(encoder.encode(frame)), info }); return true; },
    onLive: value => handoffs.push({ value, time: clock.now() }) });
  assert.equal(replay.start(), true); assert.equal(wire.length, 1);
  clock.advance(79); assert.equal(wire.length, 1);
  clock.advance(1); assert.equal(wire.length, 2);
  clock.advance(80); assert.equal(wire.length, 3);
  assert.equal(replay.state, 'replaying'); assert.equal(replay.retainedSamples, 0);
  clock.advance(79); assert.equal(handoffs.length, 0);
  clock.advance(1); assert.equal(replay.state, 'live'); assert.equal(handoffs[0].time, 240);
  assert.deepEqual(wire.map(value => value.info.sentAtMs), [0, 80, 160]);
  assert.deepEqual(wire.map(value => value.info.sampleOffset), [0, 1920, 3840]);
  for (const { packet, info } of wire) {
    assert.equal(packet.length, 3841); assert.equal(packet[0], 0x10);
    assert.equal(new DataView(packet.buffer).getInt16(1, true), 8191);
    assert.equal(info.paddedSamples, 0);
  }
  assert.equal(handoffs[0].value.reason, 'complete'); assert.equal(handoffs[0].value.preroll.length, 0);
  clock.advance(1000); assert.equal(wire.length, 3); assert.equal(handoffs.length, 1);
});

test('partial final frame preserves all captured samples and pads strictly less than80ms before draining', () => {
  const input = Float32Array.from({ length: INITIAL_FRAME_SAMPLES + 17 }, (_, index) => index / 3000);
  const { replay, clock, frames, live } = fixture(input);
  replay.start(); clock.advance(80);
  assert.equal(frames.length, 2);
  assert.deepEqual(frames[0].frame, input.subarray(0, 1920));
  assert.deepEqual(frames[1].frame.subarray(0, 17), input.subarray(1920));
  assert.ok(frames[1].frame.subarray(17).every(value => value === 0));
  assert.equal(frames[1].info.capturedSamples, 17); assert.equal(frames[1].info.paddedSamples, 1903);
  assert.ok(frames[1].info.paddedSamples / INITIAL_REPLAY_RATE < .08);
  assert.equal(replay.remainingSamples, 0); assert.equal(replay.retainedSamples, 0);
  assert.equal(live.length, 0); clock.advance(80);
  assert.equal(live[0].capturedSamplesSent, input.length); assert.equal(live[0].sentFrames, 2);
});

test('mutable caller capture is copied once and replay is single-use through its drain and terminal state', () => {
  const input = new Float32Array(4000).fill(.25), { replay, clock, frames } = fixture(input);
  input.fill(.75); assert.equal(replay.start(), true);
  assert.equal(replay.start(), false); clock.advance(240);
  assert.equal(replay.start(), false); assert.equal(replay.cancel(), false);
  assert.ok(frames.every(({ frame, info }) => frame.subarray(0, info.capturedSamples).every(value => value === .25)));
  assert.equal(replay.retainedSamples, 0);
});

test('late timers drift at normal speed and never batch or accelerate old speech', () => {
  const { replay, clock, frames } = fixture(new Float32Array(1920 * 5));
  replay.start(); clock.late(350);
  assert.deepEqual(frames.map(({ info }) => info.sentAtMs), [0, 350]);
  assert.equal(clock.pending.size, 1); assert.equal([...clock.pending.values()][0].due, 430);
  clock.advance(79); assert.equal(frames.length, 2); clock.advance(1); assert.equal(frames.length, 3);
  assert.equal(frames[2].info.sentAtMs, 430);
});

test('an early or repeated stale timer cannot send a frame early or twice', () => {
  const { replay, clock, frames } = fixture(new Float32Array(1920 * 4));
  replay.start(); const old = clock.callbacks[0]; clock.pending.clear(); clock.time = 20; old();
  assert.equal(frames.length, 1); assert.equal([...clock.pending.values()][0].due, 80);
  clock.advance(60); assert.equal(frames.length, 2);
  old(); old(); assert.equal(frames.length, 2);
  clock.advance(80); assert.equal(frames.length, 3);
});

test('a480ms inter-frame gap is allowed, but481ms fails before sending old context or entering live', () => {
  const boundary = fixture(new Float32Array(1920 * 3)); boundary.replay.start(); boundary.clock.late(MAX_INITIAL_FRAME_GAP_MS);
  assert.equal(boundary.frames.length, 2); assert.equal(boundary.frames[1].info.sentAtMs, 480);
  assert.equal(boundary.replay.state, 'replaying'); assert.deepEqual(boundary.errors, []);
  for (const count of [17, 1920 * 3]) {
    const stalled = fixture(new Float32Array(count)); stalled.replay.start(); const stale = stalled.clock.callbacks[0];
    stalled.clock.late(MAX_INITIAL_FRAME_GAP_MS + 1);
    assert.equal(stalled.frames.length, 1); assert.equal(stalled.replay.state, 'cancelled');
    assert.equal(stalled.replay.retainedSamples, 0); assert.deepEqual(stalled.errors, ['timer-stalled']);
    assert.equal(stalled.live.length, 0); stale(); stalled.clock.advance(1000); assert.equal(stalled.frames.length, 1);
  }
});

test('a synchronous send which blocks longer than480ms cannot re-arm remaining replay', () => {
  const clock = new Clock(), sent = [], errors = [];
  const replay = new InitialPcmReplay(new Float32Array(4000), { clock,
    sendFrame: frame => { sent.push(frame); clock.time += 481; return true; },
    onLive: () => assert.fail('Stalled send must not complete'), onError: code => errors.push(code) });
  assert.equal(replay.start(), false); assert.equal(replay.state, 'cancelled'); assert.equal(sent.length, 1);
  assert.equal(clock.pending.size, 0); assert.equal(replay.retainedSamples, 0); assert.deepEqual(errors, ['timer-stalled']);
});

test('fresh speech immediately hands off with only the latest200ms and stale replay cannot resume', () => {
  const { replay, clock, frames, live } = fixture(new Float32Array(24_000 * 10));
  replay.start(); const stale = clock.callbacks[0]; clock.advance(25);
  const input = Float32Array.from({ length: 6000 }, (_, index) => index / 6000);
  assert.equal(replay.handoffToLive(input), true);
  assert.equal(replay.state, 'live'); assert.equal(replay.retainedSamples, 0);
  assert.deepEqual(live[0].preroll, input.subarray(1200));
  assert.equal(live[0].preroll.length, MAX_LIVE_PREROLL_SAMPLES);
  input.fill(0); assert.ok(live[0].preroll.at(-1) > .99);
  assert.equal(clock.pending.size, 0); stale(); clock.advance(10_000);
  assert.equal(frames.length, 1); assert.equal(live.length, 1);
  assert.equal(replay.start(), false); assert.equal(replay.handoffToLive(new Float32Array(1)), false);
});

test('cancel before start, while replaying or during final drain erases capture and suppresses every late callback', () => {
  for (const at of ['pending', 'replaying', 'draining']) {
    const { replay, clock, frames, live } = fixture(new Float32Array(at === 'draining' ? 17 : 4000));
    if (at !== 'pending') replay.start();
    const count = frames.length, stale = [...clock.callbacks];
    assert.equal(replay.cancel(), true); assert.equal(replay.cancel(), false);
    assert.equal(replay.state, 'cancelled'); assert.equal(replay.remainingSamples, 0); assert.equal(replay.retainedSamples, 0);
    stale.forEach(callback => callback()); clock.advance(2000);
    assert.equal(frames.length, count); assert.equal(live.length, 0); assert.equal(clock.pending.size, 0);
    assert.equal(replay.start(), false); assert.equal(replay.handoffToLive(new Float32Array()), false);
  }
});

test('canceling during send or handing off reentrantly never creates another timer or old frame', () => {
  for (const action of ['cancel', 'handoff']) {
    const clock = new Clock(), sent = [], live = [];
    let replay;
    replay = new InitialPcmReplay(new Float32Array(4000), { clock,
      sendFrame: frame => { sent.push(frame); if (action === 'cancel') replay.cancel(); else replay.handoffToLive(new Float32Array(80)); return true; },
      onLive: value => live.push(value) });
    replay.start(); assert.equal(clock.pending.size, 0); clock.advance(1000);
    assert.equal(sent.length, 1); assert.equal(replay.retainedSamples, 0);
    assert.equal(live.length, action === 'handoff' ? 1 : 0);
  }
});

test('exact12second bound sends150 frames once, while empty, excessive or invalid captures are rejected', () => {
  const { replay, clock, frames, live } = fixture(new Float32Array(MAX_INITIAL_SAMPLES));
  replay.start(); clock.advance(12_000);
  assert.equal(frames.length, 150); assert.equal(live.length, 1); assert.equal(replay.retainedSamples, 0);
  assert.equal(frames.at(-1).info.sentAtMs, 11_920); assert.equal(frames.at(-1).info.paddedSamples, 0);
  for (const input of [new Float32Array(), new Float32Array(MAX_INITIAL_SAMPLES + 1), new Float32Array([NaN]), new Float32Array([Infinity]), new Uint8Array(10)]) {
    assert.throws(() => fixture(input), RangeError);
  }
});

test('rejected, thrown or asynchronous sends terminate without retrying or entering live', () => {
  for (const send of [() => false, () => { throw new Error('private exception'); }, () => Promise.resolve(true)]) {
    const { replay, clock, live, errors } = fixture(new Float32Array(4000), { sendFrame: send });
    assert.equal(replay.start(), false); assert.equal(replay.state, 'cancelled'); assert.equal(replay.retainedSamples, 0);
    assert.equal(clock.pending.size, 0); assert.equal(live.length, 0); assert.equal(errors.length, 1);
    assert.equal(replay.start(), false); assert.ok(!errors[0].includes('private'));
  }
});

test('a broken monotonic clock or scheduler fails closed without leaking remaining replay', () => {
  const invalid = fixture(new Float32Array(4000)); invalid.clock.time = NaN;
  assert.equal(invalid.replay.start(), false); assert.deepEqual(invalid.errors, ['clock-invalid']);
  const backwards = fixture(new Float32Array(4000)); backwards.replay.start();
  backwards.clock.time = -1; backwards.clock.callbacks[0]();
  assert.equal(backwards.replay.state, 'cancelled'); assert.equal(backwards.frames.length, 1);
  assert.equal(backwards.replay.retainedSamples, 0);
  const clock = new Clock(); clock.schedule = () => { throw new Error('timer unavailable'); };
  const broken = fixture(new Float32Array(4000), { clock });
  assert.equal(broken.replay.start(), false); assert.deepEqual(broken.errors, ['scheduler-failed']);
  assert.equal(broken.replay.retainedSamples, 0);
});

test('invalid new-speech pre-roll stops replay rather than continuing original speech', () => {
  const { replay, clock, frames, live, errors } = fixture(new Float32Array(4000)); replay.start();
  assert.equal(replay.handoffToLive(new Float32Array([NaN])), false);
  assert.equal(replay.state, 'cancelled'); clock.advance(1000);
  assert.equal(frames.length, 1); assert.equal(live.length, 0); assert.deepEqual(errors, ['invalid-preroll']);
});
