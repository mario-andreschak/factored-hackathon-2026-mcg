import test from 'node:test';
import assert from 'node:assert/strict';
import { runtimeCommands, runtimeEnvironment } from './runtime.mjs';

const fixture = {
  FLUJO_FLY_MAIN_HOST: 'flujo-factored-2026.fly.dev',
  FLUJO_FLY_PASSWORD: 'main-gateway-fixture-password',
  FLUJO_SNAPSHOT_CONTROL_TOKEN: 'worker-control-fixture-token',
  FLUJO_WORKER_SNAPSHOT_KEY: 'snapshot-key-fixture',
  FLUJO_WORKER_SNAPSHOT_SHA256: 'a'.repeat(64),
  FLUJO_BANKING_CONFIG: '/private/policy.json',
  FLUJO_DEV_UI_MARIO_PASSWORD: 'mario-fixture-password-32-characters',
  FLUJO_DEV_UI_GLORIA_PASSWORD: 'gloria-fixture-password-32-characters',
  FLUJO_DEV_UI_UNEXPECTED_SECRET: 'unexpected-fixture-secret',
  FLUJO_DEV_UI_HOST: 'flujo-factored-dev-2026.fly.dev',
  FLUJO_DEV_UI_EXPIRES_AT: '2099-10-16T05:00:00.000Z',
  FLUJO_FLY_DEV_UI_ENABLED: '1',
  UNRELATED_SECRET: 'unrelated-fixture-secret',
};

test('development listener is absent unless the exact flag is enabled', () => {
  for (const flag of [undefined, '', '0', 'true', 'yes']) {
    const environment = runtimeEnvironment({ ...fixture, FLUJO_DEV_UI_ENABLED: flag });
    assert.equal(environment.dev, undefined);
    assert.equal(environment.gateway.FLUJO_FLY_DEV_UI_ENABLED, undefined);
    assert.equal(runtimeCommands(environment).length, 3);
  }
});

test('developer credentials reach only the authenticated development process', () => {
  const environment = runtimeEnvironment({ ...fixture, FLUJO_DEV_UI_ENABLED: '1' });
  assert.equal(runtimeCommands(environment).length, 4);
  assert.equal(environment.gateway.FLUJO_FLY_DEV_UI_ENABLED, undefined);
  assert.equal(environment.dev.FLUJO_DEV_UI_SAME_ORIGIN, undefined);
  assert.equal(environment.dev.FLUJO_DEV_UI_HOST, fixture.FLUJO_DEV_UI_HOST);
  assert.equal(environment.dev.FLUJO_DEV_UI_EXPIRES_AT, fixture.FLUJO_DEV_UI_EXPIRES_AT);
  assert.equal(environment.worker.FLUJO_FLY_DEV_UI_ENABLED, undefined);
  assert.equal(environment.frontend.FLUJO_FLY_DEV_UI_ENABLED, undefined);
  for (const name of ['worker', 'frontend', 'gateway']) {
    assert.deepEqual(Object.keys(environment[name]).filter(key => key.startsWith('FLUJO_DEV_UI_')), []);
  }
  assert.equal(environment.dev.FLUJO_DEV_UI_MARIO_PASSWORD, fixture.FLUJO_DEV_UI_MARIO_PASSWORD);
  assert.equal(environment.dev.FLUJO_DEV_UI_GLORIA_PASSWORD, fixture.FLUJO_DEV_UI_GLORIA_PASSWORD);
  assert.equal(environment.dev.FLUJO_SNAPSHOT_CONTROL_TOKEN, fixture.FLUJO_SNAPSHOT_CONTROL_TOKEN);
  for (const key of ['FLUJO_FLY_PASSWORD', 'FLUJO_WORKER_SNAPSHOT_KEY', 'FLUJO_WORKER_SNAPSHOT_SHA256',
    'FLUJO_BANKING_CONFIG', 'FLUJO_DEV_UI_UNEXPECTED_SECRET', 'UNRELATED_SECRET']) {
    assert.equal(Object.hasOwn(environment.dev, key), false);
  }
  assert.equal(environment.worker.FLUJO_EXPOSURE_MODE, 'localhost');
  assert.equal(environment.worker.FLUJO_WORKER_MODE, '1');
  assert.equal(environment.worker.FLUJO_BANKING_CONFIG, '/run/banking-runtime/policy.json');
  assert.equal(environment.frontend.FLUJO_SNAPSHOT_CONTROL_TOKEN, undefined);
  assert.equal(environment.worker.FLUJO_FLY_PASSWORD, undefined);
});

test('expired optional development access leaves all Savia services running', () => {
  const expired = { ...fixture, FLUJO_DEV_UI_ENABLED: '1',
    FLUJO_DEV_UI_EXPIRES_AT: '2026-10-16T05:00:00.000Z',
    FLUJO_DEV_UI_MARIO_PASSWORD: undefined, FLUJO_DEV_UI_GLORIA_PASSWORD: undefined };
  const environment = runtimeEnvironment(expired, { now: () => Date.parse(expired.FLUJO_DEV_UI_EXPIRES_AT) });
  assert.equal(environment.dev, undefined);
  assert.equal(runtimeCommands(environment).length, 3);
  assert.equal(environment.gateway.FLUJO_FLY_DEV_UI_ENABLED, undefined);
});

test('enabled development access requires its separate hostname and canonical deadline', () => {
  for (const host of [undefined, fixture.FLUJO_FLY_MAIN_HOST, 'attacker.fly.dev', 'flujo-factored-dev-2026.fly.dev:8443']) {
    assert.throws(() => runtimeEnvironment({ ...fixture, FLUJO_DEV_UI_ENABLED: '1', FLUJO_DEV_UI_HOST: host }), /separate development hostname/);
  }
  for (const expiry of [undefined, '', 'invalid', '2099-10-16T05:00:00Z', '2099-02-30T05:00:00.000Z']) {
    assert.throws(() => runtimeEnvironment({ ...fixture, FLUJO_DEV_UI_ENABLED: '1', FLUJO_DEV_UI_EXPIRES_AT: expiry }), /canonical development expiry/);
  }
  assert.equal(runtimeCommands(runtimeEnvironment({ ...fixture, FLUJO_DEV_UI_ENABLED: '0',
    FLUJO_DEV_UI_HOST: 'bad', FLUJO_DEV_UI_EXPIRES_AT: 'bad' })).length, 3);
});

test('enabled access refuses absent or short account passwords', () => {
  for (const key of ['FLUJO_DEV_UI_MARIO_PASSWORD', 'FLUJO_DEV_UI_GLORIA_PASSWORD']) {
    for (const value of [undefined, '', 'short']) {
      assert.throws(() => runtimeEnvironment({ ...fixture, FLUJO_DEV_UI_ENABLED: '1', [key]: value }),
        /credentials are missing or too short/);
    }
  }
});
