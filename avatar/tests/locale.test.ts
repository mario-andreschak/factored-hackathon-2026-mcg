import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_LOCALE, LOCALE_STORAGE_KEY, getInitialLocale, persistLocale,
  getMessages, formatMessage, localeTag, type LocaleStorage, type Locale,
} from '../src/locale';
import { isLocale, localeFromLanguage, nativeLanguageInstruction, normalizeLocale } from '../server/locale.mjs';

function storage(saved: string | null = null) {
  const calls: Array<[string, string]> = [];
  let value = saved;
  const api: LocaleStorage = { getItem: key => { assert.equal(key, LOCALE_STORAGE_KEY); return value; },
    setItem: (key, next) => { calls.push([key, next]); value = next; } };
  return { api, calls };
}

test('first visits default to neutral LATAM Spanish, except preferred Portuguese', () => {
  assert.equal(DEFAULT_LOCALE, 'es');
  for (const language of ['es', 'es-CO', 'es-MX', 'en-US', 'fr', '', 'ptx']) {
    assert.equal(getInitialLocale({ storage: null, language }), 'es', language);
  }
  for (const language of ['pt', 'pt-BR', 'pt-PT', 'PT-br']) {
    assert.equal(getInitialLocale({ storage: null, language }), 'pt', language);
  }
  assert.equal(getInitialLocale({ storage: null, languages: ['es-CO', 'pt-BR'] }), 'es');
  assert.equal(getInitialLocale({ storage: null, languages: ['pt-BR', 'es-CO'] }), 'pt');
  assert.equal(getInitialLocale({ storage: null, languages: [], language: 'pt-BR' }), 'pt');
});

test('only a deliberately persisted supported choice overrides browser preference', () => {
  assert.equal(getInitialLocale({ storage: storage('es').api, language: 'pt-BR' }), 'es');
  assert.equal(getInitialLocale({ storage: storage('pt').api, language: 'es-CO' }), 'pt');
  for (const malformed of ['en', 'pt-BR', 'ES', 'undefined', '{"locale":"pt"}']) {
    assert.equal(getInitialLocale({ storage: storage(malformed).api, language: 'pt-BR' }), 'pt');
  }
  const first = storage(); assert.equal(getInitialLocale({ storage: first.api, language: 'pt-BR' }), 'pt');
  assert.deepEqual(first.calls, []); // An inferred language does not become a saved user choice.
});

test('denied browser storage is safe; deliberate persistence is bounded to es or pt', () => {
  const denied: LocaleStorage = { getItem: () => { throw new DOMException('denied', 'SecurityError'); },
    setItem: () => { throw new DOMException('full', 'QuotaExceededError'); } };
  assert.equal(getInitialLocale({ storage: denied, language: 'pt-BR' }), 'pt');
  assert.equal(persistLocale('pt', denied), false); assert.equal(persistLocale('es', null), false);
  const selected = storage(); assert.equal(persistLocale('pt', selected.api), true);
  assert.equal(getInitialLocale({ storage: selected.api, language: 'es' }), 'pt');
  assert.equal(persistLocale('en' as Locale, selected.api), false);
  assert.deepEqual(selected.calls, [[LOCALE_STORAGE_KEY, 'pt']]);
});

test('a throwing window.localStorage getter cannot prevent language selection or safe rendering', () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'window');
  const deniedWindow = Object.defineProperty({}, 'localStorage', { get: () => { throw new DOMException('denied', 'SecurityError'); } });
  Object.defineProperty(globalThis, 'window', { configurable: true, value: deniedWindow });
  try {
    assert.equal(getInitialLocale({ language: 'pt-BR' }), 'pt');
    assert.equal(getInitialLocale({ language: 'en-US' }), 'es');
    assert.equal(persistLocale('es'), false);
  } finally {
    if (previous) Object.defineProperty(globalThis, 'window', previous);
    else Reflect.deleteProperty(globalThis, 'window');
  }
});

test('server and browser use identical supported regional policy and language instructions', () => {
  assert.equal(localeTag('es'), 'es-CO'); assert.equal(localeTag('pt'), 'pt-BR');
  for (const value of [null, undefined, '', 'en', 'pt-BR', {}, 1]) {
    assert.equal(isLocale(value), false); assert.equal(normalizeLocale(value), 'es');
  }
  assert.equal(isLocale('es'), true); assert.equal(isLocale('pt'), true);
  assert.equal(localeFromLanguage('pt-BR'), 'pt');
  assert.match(nativeLanguageInstruction('es'), /español latinoamericano/);
  assert.match(nativeLanguageInstruction('pt'), /português do Brasil/);
});

test('every Spanish catalog leaf has a Portuguese equivalent with matching placeholders and stable names', () => {
  const es = getMessages('es'), pt = getMessages('pt');
  let leaves = 0;
  function compare(a: unknown, b: unknown, path = '') {
    if (typeof a === 'string') {
      assert.equal(typeof b, 'string', path); assert.ok((b as string).trim(), path);
      assert.deepEqual(a.match(/\{\w+\}/g) ?? [], (b as string).match(/\{\w+\}/g) ?? [], path); leaves++; return;
    }
    assert.deepEqual(Object.keys(a as object), Object.keys(b as object), path);
    for (const key of Object.keys(a as object)) compare((a as Record<string, unknown>)[key], (b as Record<string, unknown>)[key], path + '.' + key);
  }
  compare(es, pt); assert.ok(leaves > 80);
  for (const avatar of ['moss', 'orbit', 'spark'] as const) {
    assert.equal(es.characters[avatar].name, pt.characters[avatar].name);
    assert.equal(es.characters[avatar].name.toLowerCase(), avatar);
    assert.equal(es.characters[avatar].color, pt.characters[avatar].color);
  }
  assert.equal(es.ui.sendMessage, 'Enviar mensaje'); assert.equal(pt.ui.sendMessage, 'Enviar mensagem');
  assert.equal(es.status.listening, 'Te escucho'); assert.equal(pt.status.listening, 'Estou ouvindo');
});

test('plain-text catalog interpolation preserves missing fields and literal replacement characters', () => {
  assert.equal(formatMessage(getMessages('es').ui.talkTo, { name: 'Moss' }), 'Hablar con Moss');
  assert.equal(formatMessage(getMessages('pt').ui.travelTo, { place: 'Lago' }), 'Viajar para Lago');
  assert.equal(formatMessage('{name}: {count}; {missing}', { name: '$& {count}', count: 3 }), '$& {count}: 3; {missing}');
  assert.equal(formatMessage('{toString}', {}), '{toString}');
});
