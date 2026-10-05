import test from 'node:test';
import assert from 'node:assert/strict';
import { voiceCopy, voiceError, VoiceLocaleError, voicePersona, voiceResponseError, voiceSessionInstructions } from '../src/voiceLocale';
import type { Locale } from '../src/locale';

test('raw provider and browser diagnostics cannot become public voice copy', async () => {
  const diagnostic = 'Provider failed at https://private.invalid/?token=fake-secret with internal customer identifier';
  for (const locale of ['es', 'pt'] as const) {
    const browserError = voiceError(locale, new Error(diagnostic));
    assert.equal(browserError, voiceCopy(locale).connectionFailed);
    assert.equal(browserError.includes('fake-secret'), false);
    const responseError = await voiceResponseError(new Response(JSON.stringify({ error: diagnostic, code: diagnostic }), { status: 502 }));
    assert.equal(voiceError(locale, responseError), voiceCopy(locale).providerFailed);
    const malformed = await voiceResponseError(new Response('<private-error>fake-secret</private-error>', { status: 503 }));
    assert.equal(voiceError(locale, malformed), voiceCopy(locale).providerUnavailable);
  }
});

test('structured quota errors preserve the actual recovery category in both locales', async () => {
  const error = await voiceResponseError(new Response(JSON.stringify({ code: 'voice_quota_exhausted', error: 'discard this provider prose' }), { status: 503 }));
  for (const locale of ['es', 'pt'] as const) assert.equal(voiceError(locale, error), voiceCopy(locale).quotaExceeded);
  assert.equal(voiceError('pt', new VoiceLocaleError('microphoneDenied')), voiceCopy('pt').microphoneDenied);
  assert.equal(voiceError('es', null, 'taskFailed'), voiceCopy('es').taskFailed);
});

test('all public voice failure categories have both translations and safe Spanish fallback', () => {
  const es = voiceCopy('es'), pt = voiceCopy('pt');
  assert.deepEqual(Object.keys(pt).sort(), Object.keys(es).sort());
  for (const key of Object.keys(es) as (keyof typeof es)[]) {
    assert.ok(es[key].trim(), key);
    assert.ok(pt[key].trim(), key);
    assert.notEqual(es[key], pt[key], key);
  }
  assert.deepEqual(voiceCopy(), es);
  assert.deepEqual(voiceCopy('en' as Locale), es);
  assert.equal(voiceError(undefined, new Error('Failed to fetch')), es.connectionFailed);
});

test('persona changes retain the selected language and the read-only evidence boundary', () => {
  for (const avatar of ['moss', 'orbit', 'spark'] as const) {
    const es = voiceSessionInstructions(avatar, 'es'), pt = voiceSessionInstructions(avatar, 'pt');
    assert.match(es, /español latinoamericano/);
    assert.match(pt, /português do Brasil/);
    assert.match(es, /nunca pidas contraseñas por voz/);
    assert.match(pt, /nunca peça senhas por voz/);
    assert.match(es, /no se presentan disputas/);
    assert.match(pt, /contestações não são abertas/);
    assert.match(es, /sin confirmación del sistema/);
    assert.match(pt, /sem confirmação do sistema/);
    assert.match(voicePersona(avatar, 'pt'), new RegExp(avatar === 'moss' ? 'Moss' : avatar === 'orbit' ? 'Orbit' : 'Spark'));
  }
});
