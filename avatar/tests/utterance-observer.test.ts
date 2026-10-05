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

test('a thinking pause keeps both speech segments in one utterance and restarts the final silence window', () => {
  const collector = new UtteranceCollector(16000, 25, 2);
  for (let i = 0; i < 6; i++) assert.equal(collector.push(block(.2), true), undefined);
  for (let i = 0; i < 12; i++) assert.equal(collector.push(block(0), false), undefined);
  for (let i = 0; i < 5; i++) assert.equal(collector.push(block(.4), true), undefined);
  // Earlier silence cannot contribute to the deadline after speech resumes.
  for (let i = 0; i < 19; i++) assert.equal(collector.push(block(0), false), undefined);
  const result = collector.push(block(0), false);
  assert.ok(result); assert.equal(result.capped, false);
  assert.equal(result.chunks.filter(chunk => chunk[0] > .19 && chunk[0] < .21).length, 6);
  assert.equal(result.chunks.filter(chunk => chunk[0] > .39 && chunk[0] < .41).length, 5);
  assert.equal(result.chunks.filter(chunk => chunk[0] === 0).length, 32);
  for (let i = 0; i < 25; i++) assert.equal(collector.push(block(0), false), undefined);
  // Once submitted, the next deliberate utterance is independent.
  collector.push(block(.6), true); collector.push(block(.6), true);
  let next: Utterance | undefined;
  for (let i = 0; i < 20; i++) next = collector.push(block(0), false) ?? next;
  assert.ok(next); assert.ok(next.chunks.every(chunk => chunk[0] === 0 || chunk[0] > .59));
});

test('patient endpointing still clears partial speech on reset and rejects capped speech', () => {
  const collector = new UtteranceCollector(16000, 25, 2);
  collector.push(block(), true); collector.push(block(), true); collector.reset();
  for (let i = 0; i < 25; i++) assert.equal(collector.push(block(0), false), undefined);
  let result: Utterance | undefined;
  for (let i = 0; i < 260; i++) result = collector.push(block(), true) ?? result;
  assert.ok(result?.capped);
  assert.equal(result.chunks.reduce((sum, chunk) => sum + chunk.length, 0), 400000);
  for (const invalid of [NaN, Infinity, 0, .1, 6]) assert.throws(() => new UtteranceCollector(16000, 25, invalid), RangeError);
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

test('capped speech drains across a thinking pause and resumes only after the configured continuous quiet', () => {
  for (const quietAtCap of [0, 6]) {
    const collector = new UtteranceCollector(16000, 3, 2);
    let capped: Utterance | undefined;
    for (let i = 0; i < 30 - quietAtCap; i++) capped = collector.push(block(.2), true) ?? capped;
    for (let i = 0; i < quietAtCap; i++) capped = collector.push(block(0), false) ?? capped;
    assert.ok(capped?.capped);
    // A pause shorter than two seconds must not release the capped turn.
    for (let i = quietAtCap; i < 10; i++) assert.equal(collector.push(block(0), false), undefined);
    for (let i = 0; i < 6; i++) assert.equal(collector.push(block(.4), true), undefined);
    for (let i = 0; i < 20; i++) assert.equal(collector.push(block(0), false), undefined);
    collector.push(block(.6), true); collector.push(block(.6), true);
    let next: Utterance | undefined;
    for (let i = 0; i < 20; i++) next = collector.push(block(0), false) ?? next;
    assert.ok(next); assert.equal(next.capped, false);
    assert.ok(next.chunks.every(chunk => chunk[0] === 0 || chunk[0] > .59));
  }
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
