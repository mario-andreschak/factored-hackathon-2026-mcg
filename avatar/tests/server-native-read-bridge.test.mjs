import test from 'node:test';
import assert from 'node:assert/strict';
import { readConfig } from '../server/config.mjs';
import { createAvatarServer } from '../server/app.mjs';

const configured = { NODE_ENV: 'test', AVATAR_VOICE_PROVIDER: 'personaplex',
  AVATAR_BACKGROUND_ASR: 'openrouter', OPENROUTER_API_KEY: 'private-test-observer-key',
  AVATAR_NATIVE_READ_BRIDGE: 'readonly', SAVIA_UPSTREAM: 'http://127.0.0.1:1' };

async function fixture(t, env) {
  let calls = 0;
  const server = createAvatarServer({ config: readConfig(env), fetchImpl: async () => {
    calls++; throw new Error('No provider or banking dispatch is authorized by this config fixture.');
  } });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const base = `http://127.0.0.1:${server.address().port}`;
  const response = await fetch(base + '/api/avatar/config');
  const cookie = response.headers.getSetCookie()[0].split(';')[0];
  const config = await response.json();
  const request = (path, body) => fetch(base + path, { method: 'POST',
    headers: { Origin: base, Cookie: cookie, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return { config, request, get calls() { return calls; } };
}

test('native read bridge is off by default and accepts only the exact read-only operator flag', () => {
  assert.equal(readConfig({}).nativeReadBridge, '');
  assert.equal(readConfig(configured).nativeReadBridge, 'readonly');
  for (const value of ['true', 'false', 'readwrite', 'READONLY', 'readonly ', 'https://attacker.example']) {
    assert.throws(() => readConfig({ AVATAR_NATIVE_READ_BRIDGE: value }), /Invalid AVATAR_NATIVE_READ_BRIDGE/);
  }
});

test('read capability stays false when any native recognition or Savia prerequisite is absent', async t => {
  for (const absent of ['AVATAR_NATIVE_READ_BRIDGE', 'AVATAR_BACKGROUND_ASR', 'OPENROUTER_API_KEY', 'SAVIA_UPSTREAM']) {
    const env = { ...configured }; delete env[absent];
    const f = await fixture(t, env);
    assert.equal(f.config.nativeReadBridgeAvailable, false, `${absent} must be configured`);
    assert.equal(f.calls, 0);
  }
  for (const provider of ['none', 'gemini-live', 'openai-realtime', 'openrouter']) {
    const f = await fixture(t, { ...configured, AVATAR_VOICE_PROVIDER: provider });
    assert.equal(f.config.nativeReadBridgeAvailable, false);
    assert.equal(f.calls, 0);
  }
});

test('configured bridge advertises only a boolean capability without granting bank auth or voice admission', async t => {
  const f = await fixture(t, configured);
  assert.equal(f.config.voiceProvider, 'personaplex');
  assert.equal(f.config.backgroundAsrAvailable, true);
  assert.equal(f.config.nativeReadBridgeAvailable, true);
  assert.equal(f.config.voiceAvailable, false); // No worker is launched by capability discovery.
  assert.ok(!JSON.stringify(f.config).includes(configured.OPENROUTER_API_KEY));
  assert.equal((await f.request('/api/avatar/personaplex-session', { avatar: 'moss' })).status, 503);
  assert.equal((await f.request('/api/avatar/transcribe', { audio: 'not admitted', format: 'wav' })).status, 409);
  assert.equal((await f.request('/api/avatar/task', { message: 'Check my balance.' })).status, 401);
  assert.equal((await f.request('/api/avatar/conversation', { message: 'hello', avatar: 'moss' })).status, 503);
  assert.equal((await f.request('/api/avatar/speech', { text: 'hello', avatar: 'moss' })).status, 503);
  assert.equal(f.calls, 0);
});
