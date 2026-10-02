import test from 'node:test';
import assert from 'node:assert/strict';
import { UtteranceCollector, UtteranceObserver, type Utterance } from '../src/experiments/utteranceObserver';

const tick = () => new Promise(resolve => setImmediate(resolve));
const block = (value = 1) => new Float32Array(1600).fill(value);
const utterance = (value = 1, capped = false): Utterance => ({ chunks: [block(value)], sampleRate: 16000, capped });

test('observer retains onset/pre-roll, completes on silence and copies mutable worklet blocks', () => {
  const collector = new UtteranceCollector(16000), shared = block(.2);
  collector.push(block(0), false); collector.push(shared, true); shared.fill(.9);
  assert.equal(collector.push(block(.3), true), undefined);
  let result: Utterance | undefined;
  for (let i = 0; i < 5; i++) result = collector.push(block(0), false) ?? result;
  assert.ok(result); assert.equal(result.capped, false);
  assert.equal(result.chunks.reduce((sum, chunk) => sum + chunk.length, 0), 12800);
  assert.ok(result.chunks[1][0] < .21);
  assert.equal(collector.push(block(0), false), undefined);
});

test('observer ignores brief clicks, bounds long speech and waits for quiet before a new utterance', () => {
  const collector = new UtteranceCollector(16000);
  collector.push(block(), true);
  for (let i = 0; i < 6; i++) assert.equal(collector.push(block(0), false), undefined);
  let result: Utterance | undefined;
  for (let i = 0; i < 300; i++) result = collector.push(block(), true) ?? result;
  assert.ok(result?.capped); assert.equal(result.chunks.reduce((sum, chunk) => sum + chunk.length, 0), 400000);
  for (let i = 0; i < 5; i++) assert.equal(collector.push(block(0), false), undefined);
  collector.push(block(), true); collector.push(block(), true);
  for (let i = 0; i < 5; i++) result = collector.push(block(0), false) ?? result;
  assert.equal(result?.capped, false);
});

test('observer reset erases speech captured before mute, privacy pause or identity change', () => {
  const collector = new UtteranceCollector(16000);
  collector.push(block(), true); collector.push(block(), true); collector.reset();
  for (let i = 0; i < 6; i++) assert.equal(collector.push(block(0), false), undefined);
});

test('initial intake rejects a still-active twelve-second utterance without treating a truncated problem as complete', () => {
  const collector = new UtteranceCollector(16000, 12);
  let result: Utterance | undefined;
  for (let i = 0; i < 130; i++) result = collector.push(block(), true) ?? result;
  assert.ok(result?.capped);
  assert.equal(result.chunks.reduce((sum, chunk) => sum + chunk.length, 0), 192000);
  const delivered: string[] = [];
  const observer = new UtteranceObserver(async () => 'a truncated request', text => delivered.push(text));
  observer.offer(result);
  assert.deepEqual(delivered, []);
  observer.dispose();
  assert.throws(() => new UtteranceCollector(16000, 26), RangeError);
});

test('observer keeps one request and only the latest queued utterance, and refuses capped speech', async () => {
  const pending: ((text: string) => void)[] = [], values: number[] = [], results: string[] = [];
  const observer = new UtteranceObserver(u => { values.push(u.chunks[0][0]); return new Promise(resolve => pending.push(resolve)); }, t => results.push(t));
  observer.offer(utterance(1)); observer.offer(utterance(2)); observer.offer(utterance(3)); observer.offer(utterance(4, true));
  await tick(); assert.deepEqual(values, [1]); pending.shift()!(' first '); await tick();
  assert.deepEqual(values, [1, 3]); pending.shift()!('last'); await tick();
  assert.deepEqual(results, ['first', 'last']); observer.dispose();
});

test('identity invalidation aborts pending request and rejects its late result and queued speech', async () => {
  let finish!: (text: string) => void, signal!: AbortSignal; const results: string[] = [];
  const observer = new UtteranceObserver((_u, s) => { signal = s; return new Promise(resolve => { finish = resolve; }); }, t => results.push(t));
  observer.offer(utterance()); observer.offer(utterance(2)); await tick(); observer.invalidate();
  assert.equal(signal.aborted, true); finish('prior account'); await tick(); assert.deepEqual(results, []);
  observer.dispose(); observer.offer(utterance(3)); await tick(); assert.deepEqual(results, []);
});

test('an invalidated request cannot clear or deliver a new epoch request', async () => {
  const pending: ((text: string) => void)[] = [], results: string[] = [];
  const observer = new UtteranceObserver(() => new Promise(resolve => pending.push(resolve)), t => results.push(t));
  observer.offer(utterance()); await tick(); observer.invalidate(); observer.offer(utterance(2)); await tick();
  pending[0]('old'); await tick(); pending[1]('new'); await tick(); assert.deepEqual(results, ['new']); observer.dispose();
});
