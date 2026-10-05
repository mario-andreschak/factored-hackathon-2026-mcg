import test from 'node:test';
import assert from 'node:assert/strict';
import { createNativeTurns } from '../server/native-turns.mjs';

const value = (audio = 'recorded-audio', locale = 'es') => ({ audio, locale, avatar: 'moss' });
test('only a fully drained, completed reply becomes heard conversation history', () => {
  const state = createNativeTurns(), { turn } = state.begin(value(), null, new AbortController());
  state.finish(turn, { completed: true, text: 'Un resultado entero', samples: 12000 });
  assert.deepEqual(state.history(), []);
  assert.throws(() => state.played({ turnId: turn.id, locale: 'es', playedSamples: 11999, complete: true }), { code: 'native_turn_ended' });
  state.played({ turnId: turn.id, locale: 'es', playedSamples: 12000, complete: true });
  assert.deepEqual(state.history(), [{ role: 'assistant', content: 'Un resultado entero' }]);
});
test('an interrupted reply cannot later masquerade as a completely heard reply', () => {
  const state = createNativeTurns(), { turn } = state.begin(value(), null, new AbortController());
  state.finish(turn, { completed: true, text: 'Unheard promise', samples: 12000 });
  state.played({ turnId: turn.id, locale: 'es', playedSamples: 50, complete: false });
  assert.throws(() => state.played({ turnId: turn.id, locale: 'es', playedSamples: 12000, complete: true }), { code: 'native_turn_ended' });
  assert.equal(state.history().some(item => item.content === 'Unheard promise'), false);
});
test('barge-in aborts the old reply while preserving its captured observer input', () => {
  const state = createNativeTurns(), response = new AbortController(), observer = new AbortController();
  const { turn } = state.begin(value('first'), null, response);
  state.claimObserver({ turnId: turn.id, locale: 'es', audio: 'first', format: 'wav' }, observer);
  state.begin(value('second'), null, new AbortController());
  assert.equal(response.signal.aborted, true); assert.equal(observer.signal.aborted, false);
  assert.equal(state.observed(turn, 'La primera pregunta'), true);
  assert.equal(state.history()[0].content, 'La primera pregunta');
});
test('observation binds the exact recorded utterance and forbids duplicate billable recognition', () => {
  const state = createNativeTurns(), { turn } = state.begin(value('one'), null, new AbortController());
  assert.throws(() => state.claimObserver({ turnId: turn.id, locale: 'es', audio: 'other', format: 'wav' }, new AbortController()), { code: 'native_turn_ended' });
  state.claimObserver({ turnId: turn.id, locale: 'es', audio: 'one', format: 'wav' }, new AbortController());
  assert.throws(() => state.claimObserver({ turnId: turn.id, locale: 'es', audio: 'one', format: 'wav' }, new AbortController()), { code: 'native_observer_used' });
  state.observerFailed(turn);
  assert.throws(() => state.claimObserver({ turnId: turn.id, locale: 'es', audio: 'one', format: 'wav' }, new AbortController()), { code: 'native_observer_used' });
});
test('account or locale change revokes in-flight observations, replies and receipts', () => {
  const state = createNativeTurns(), response = new AbortController(), observer = new AbortController();
  const { turn } = state.begin(value(), 'account-a', response);
  state.claimObserver({ turnId: turn.id, locale: 'es', audio: 'recorded-audio', format: 'wav' }, observer);
  const taskId = state.receipt({ reply: '42.17', mode: 'flujo', status: 'completed' }, 'account-a');
  state.bind('account-b');
  assert.equal(response.signal.aborted, true); assert.equal(observer.signal.aborted, true);
  assert.equal(state.observed(turn, 'Stale account text'), false);
  assert.throws(() => state.consumeReceipt({ taskId, avatar: 'moss', locale: 'es' }, 'account-b'), { code: 'native_turn_ended' });
  const next = state.begin(value('pt-input', 'pt'), 'account-b', new AbortController());
  state.begin(value('es-input', 'es'), 'account-b', new AbortController());
  assert.throws(() => state.played({ turnId: next.turn.id, locale: 'pt', playedSamples: 0, complete: false }), { code: 'native_turn_ended' });
});
test('narration uses a recent server-owned exact result once, never caller-provided facts', () => {
  let time = 1; const state = createNativeTurns({ now: () => time });
  const taskId = state.receipt({ reply: 'La suma es 42.17.', mode: 'flujo', status: 'completed' }, 'account');
  assert.throws(() => state.receiptFor({ reply: 'La suma es 999.', locale: 'es' }, 'account'), { code: 'native_turn_ended' });
  assert.deepEqual(state.receiptFor({ reply: 'La suma es 42.17.', locale: 'es' }, 'account'), { taskId });
  assert.equal(state.consumeReceipt({ taskId, avatar: 'moss', locale: 'es' }, 'account').reply, 'La suma es 42.17.');
  assert.throws(() => state.consumeReceipt({ taskId, avatar: 'moss', locale: 'es' }, 'account'), { code: 'native_turn_ended' });
  const expired = state.receipt({ reply: 'Old', mode: 'flujo', status: 'completed' }, 'account'); time += 120001;
  assert.throws(() => state.consumeReceipt({ taskId: expired, avatar: 'moss', locale: 'es' }, 'account'), { code: 'native_turn_ended' });
});
test('trusted pending facts remain separate from heard assistant text and expire or reset', () => {
  let time = 1; const state = createNativeTurns({ now: () => time });
  state.begin(value(), 'account', new AbortController());
  const taskId = state.receipt({ reply: '42.17', mode: 'flujo', status: 'completed' }, 'account');
  assert.throws(() => state.consumeReceipt({ taskId, avatar: 'moss', locale: 'pt' }, 'account'), { code: 'native_turn_ended' });
  state.consumeReceipt({ taskId, avatar: 'moss', locale: 'es' }, 'account');
  assert.equal(state.latestResult().reply, '42.17'); assert.equal(state.hasPrivateContext(), true);
  assert.equal(state.history().some(item => item.content.includes('42.17')), false);
  time += 120001; assert.equal(state.latestResult(), undefined);
  // Heard bank-data history may outlive the quote; identity checks remain necessary until reset.
  assert.equal(state.hasPrivateContext(), true);
  state.reset(); assert.equal(state.hasPrivateContext(), false);
});
test('a cancelled playback receipt promptly aborts only its response', () => {
  const state = createNativeTurns(), response = new AbortController(), observer = new AbortController();
  const { turn } = state.begin(value(), null, response);
  state.claimObserver({ turnId: turn.id, locale: 'es', audio: 'recorded-audio', format: 'wav' }, observer);
  state.played({ turnId: turn.id, locale: 'es', playedSamples: 0, complete: false });
  assert.equal(response.signal.aborted, true); assert.equal(observer.signal.aborted, false);
});
test('qualification allows an early full-played ACK without releasing delivery revocation', () => {
  const state = createNativeTurns(), response = new AbortController();
  const { turn } = state.begin(value(), 'account', response);
  state.qualify(turn, { completed: true, text: 'Confirmed words', samples: 12000 });
  state.played({ turnId: turn.id, locale: 'es', playedSamples: 12000, complete: true });
  state.bind(null);
  assert.equal(response.signal.aborted, true); assert.deepEqual(state.history(), []);
});

test('fresh dispute-host display facts acquire one server-owned result receipt without granting action authority', () => {
  const state = createNativeTurns();
  const result = { reply: 'El cargo ficticio es de 42.17 USD. No se realizó una acción.', mode: 'dispute', status: 'completed' };
  const taskId = state.receipt(result, 'fictional-owner');
  assert.ok(taskId);
  assert.deepEqual(state.consumeReceipt({ taskId, avatar: 'moss', locale: 'es' }, 'fictional-owner'), result);
  assert.throws(() => state.consumeReceipt({ taskId, avatar: 'moss', locale: 'es' }, 'fictional-owner'));
  assert.equal(state.receipt({ ...result, capability: 'forged' }, 'fictional-owner'), null);
});

test('actual informational team updates consume one owned receipt without acquiring bank authority', () => {
  const state = createNativeTurns();
  const result = { reply: 'Las dos perspectivas están listas. ¿Te ayudan a decidir?', mode: 'assistant', status: 'completed' };
  const taskId = state.receipt(result, 'fictional-owner');
  assert.ok(taskId);
  assert.throws(() => state.receiptFor({ reply: 'Un humano resolvió el banco.', locale: 'es' }, 'fictional-owner'));
  assert.deepEqual(state.consumeReceipt({ taskId, avatar: 'moss', locale: 'es' }, 'fictional-owner'), result);
  assert.throws(() => state.consumeReceipt({ taskId, avatar: 'moss', locale: 'es' }, 'fictional-owner'));
  assert.equal(state.receipt({ ...result, bank_authority: true }, 'fictional-owner'), null);
});
