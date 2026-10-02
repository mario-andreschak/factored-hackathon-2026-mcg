import test from 'node:test';
import assert from 'node:assert/strict';
import { AVATARS, classifyMood, demoReply } from '../src/domain';

test('ordinary English and Spanish account questions reach the bank inquiry path', () => {
  for (const message of [
    'Explain my transactions',
    'Review these payments and transfers',
    'What are these charges?',
    'Explain my account balances',
    'Revisa mis movimientos',
    'Explícame estas transacciones',
    'Revisa los pagos, cobros y saldos',
    'What is this transaction?',
    'Explica esta transacción',
  ]) {
    assert.equal(classifyMood(message).intent, 'inquiry', message);
  }
});

test('mood and escalation remain independent of plural bank terms', () => {
  assert.deepEqual(
    ['I am worried about these payments', 'Quick, explain my transactions', 'Review my movements'].map(message => classifyMood(message).avatar),
    ['moss', 'spark', 'orbit'],
  );
  assert.equal(classifyMood('I do not recognize these transactions; I need a dispute').intent, 'dispute');
  assert.equal(classifyMood('My account was hacked and these payments are wrong').intent, 'human');
  assert.equal(classifyMood('My dance movements feel awkward').intent, 'other');
});
test('initial pace cues select an energetic character while distress still takes precedence', () => {
  assert.equal(classifyMood('I am ready to go! Let us do something fun and get moving.').avatar, 'spark');
  assert.equal(classifyMood('I am excited; let us go!').avatar, 'spark');
  assert.equal(classifyMood('I am anxious but ready to go fast.').avatar, 'moss');
  assert.equal(classifyMood('Let us make a clear business plan.').avatar, 'orbit');
});

test('Portuguese account nouns and accented dispute phrases classify presentation intent', () => {
  for (const message of [
    'Explique meu saldo', 'Quais são estes pagamentos?', 'Mostre minhas transações',
    'Fui cobrado ontem', 'Confira esta cobrança', 'Revisar meu extrato e as transferências',
    'Explique esta transação', 'Verifique minhas movimentações',
  ]) assert.equal(classifyMood(message).intent, 'inquiry', message);
  for (const message of [
    'Não reconheço esta cobrança', 'Quero contestar este pagamento',
    'Fui cobrado duas vezes', 'Esta cobrança duplicada está errada',
    'Qual é o status do reembolso?',
  ]) assert.equal(classifyMood(message).intent, 'dispute', message);
});

test('Portuguese distress takes precedence over urgent energy, without diagnosis or bank authorization', () => {
  for (const message of [
    'Estou com medo', 'Estou ansioso e preciso de ajuda rápido',
    'Estou sobrecarregada e zangada com os pagamentos', 'Estou exausto, é urgente',
  ]) assert.equal(classifyMood(message).avatar, 'moss', message);
  for (const message of ['Vamos nessa, bem rápido!', 'Estou zangado', 'É urgente', 'Estou empolgada, bora!']) {
    assert.equal(classifyMood(message).avatar, 'spark', message);
  }
  for (const message of ['Vamos montar um plano', 'Explique esta ideia', 'Organize meu orçamento']) {
    assert.equal(classifyMood(message).avatar, 'orbit', message);
  }
  const presentation = classifyMood('Minha conta foi invadida, estou com medo');
  assert.equal(presentation.intent, 'human'); assert.equal(presentation.avatar, 'moss');
  assert.deepEqual(Object.keys(presentation).sort(), ['avatar', 'intent', 'reason']);
  assert.equal(classifyMood('Minha coreografia tem movimentos rápidos').intent, 'other');
  assert.equal(classifyMood('Monte um orçamento para minha festa').intent, 'other');
});

test('typed companion replies follow the selected language while character names stay unchanged', () => {
  assert.match(demoReply('Hola', 'moss'), /^Hola/);
  assert.match(demoReply('Olá', 'moss', 'pt'), /^Olá/);
  assert.match(demoReply('Oi!', 'spark', 'pt'), /^Ei!/);
  assert.match(demoReply('Revisa mi saldo', 'orbit'), /tu cuenta/);
  assert.match(demoReply('Explique meu saldo', 'orbit', 'pt'), /sua conta/);
  assert.match(demoReply('Minha conta foi invadida', 'moss', 'pt'), /seu banco/);
  assert.match(demoReply('Me robaron la cuenta', 'moss'), /tu banco/);
  for (const id of ['moss', 'orbit', 'spark'] as const) assert.equal(AVATARS[id].name.toLowerCase(), id);
  assert.equal(AVATARS.moss.line, 'Un pequeño paso a la vez.');
});
