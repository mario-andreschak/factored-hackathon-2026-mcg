const test = require('node:test');
const assert = require('node:assert/strict');
const Engine = require('../web/dev-history/replay-engine.js');

test('large time gaps and high playback speed still expose every record in order', () => {
  const player = new Engine(1000, 850);
  const observed = [player.index];
  let state;
  do {
    state = player.advance(10000, 64);
    if (state.changed) observed.push(state.index);
  } while (!state.finished);
  assert.deepEqual(observed, Array.from({length:1000},(_,i)=>i));
  assert.equal(state.visited,1000);
  assert.equal(state.skippedByPlayback,0);
});
test('a record stays visible for its dwell and end includes the final record', () => {
  const player = new Engine(3,1000);
  assert.equal(player.advance(999).index,0);
  assert.equal(player.advance(1).index,1);
  assert.equal(player.advance(1000).index,2);
  assert.equal(player.advance(999).finished,false);
  assert.equal(player.advance(1).finished,true);
});
test('manual seeking is explicit and subsequent playback is consecutive', () => {
  const player = new Engine(100,850);
  assert.equal(player.seek(80).seeks,1);
  assert.equal(player.advance(850).index,81);
  assert.equal(player.snapshot(false).skippedByPlayback,0);
});
