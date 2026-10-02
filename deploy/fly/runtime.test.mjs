import test from 'node:test';
import assert from 'node:assert/strict';
import { runtimeCommands, runtimeEnvironment, supervise, transitionEvidenceFiles } from './runtime.mjs';
const fixture = { FLUJO_FLY_PASSWORD: 'main-private-password-123456', FLUJO_SNAPSHOT_CONTROL_TOKEN: 'private-control-token',
  FLUJO_WORKER_SNAPSHOT_KEY: 'forbidden-worker-snapshot-secret', FLUJO_BANKING_CONFIG: 'forbidden-policy',
  AWS_SECRET_ACCESS_KEY: 'forbidden-aws-key', BANKING_SERVICE_TOKEN: 'forbidden-bank-token',
  FLUJO_DEV_UI_ENABLED: '1', FLUJO_DEV_UI_HOST: 'flujo-factored-dev-2026.fly.dev',
  FLUJO_DEV_UI_EXPIRES_AT: '2026-10-16T05:00:00.000Z', FLUJO_DEV_UI_MARIO_PASSWORD: 'mario-private-password-123456',
  FLUJO_DEV_UI_GLORIA_PASSWORD: 'gloria-private-password-123456' };
test('runtime grants each child only its approved credentials and UID', () => {
  const env = runtimeEnvironment(fixture, Date.parse('2026-10-01T23:00:00Z'));
  for (const child of Object.values(env)) {
    assert.equal(child.AWS_SECRET_ACCESS_KEY, undefined); assert.equal(child.BANKING_SERVICE_TOKEN, undefined);
    assert.equal(child.FLUJO_WORKER_SNAPSHOT_KEY, undefined); assert.equal(child.FLUJO_BANKING_CONFIG, undefined);
  }
  assert.equal(env.worker.FLUJO_FLY_PASSWORD, undefined);
  assert.equal(env.frontend.FLUJO_SNAPSHOT_CONTROL_TOKEN, undefined);
  assert.equal(env.gateway.FLUJO_DEV_UI_MARIO_PASSWORD, undefined);
  assert.equal(env.worker.FLUJO_DEV_UI_GLORIA_PASSWORD, undefined);
  assert.equal(env.dev.FLUJO_FLY_PASSWORD, undefined);
  assert.equal(env.worker.FLUJO_DATA_DIR, '/data/native-flujo');
  assert.equal(env.worker.FLUJO_WORKER_SNAPSHOT, undefined);
  const commands = runtimeCommands(env);
  assert.equal(commands[0].args[0], 'node'); assert.equal(commands[1].args[0], 'banking');
  assert.equal(commands.filter(item => item.name.includes('banking')).length, 1);
  const bankArgs = commands[1].args;
  assert.equal(bankArgs[bankArgs.indexOf('--application-source-root') + 1], '/opt/joined');
  assert.equal(bankArgs.includes('--source-root'), false);
  assert.equal(commands.some(item => item.args.join(' ').includes('banking_mcp stdio')), false);
});
test('development access expires without interrupting primary children', () => {
  const env = runtimeEnvironment(fixture, Date.parse(fixture.FLUJO_DEV_UI_EXPIRES_AT));
  assert.equal(env.dev, undefined); assert.equal(runtimeCommands(env).length, 3);
});
test('retained transition proofs stay in bank-only storage with pinned archive paths', () => {
  const root = '/data/native-transition-evidence';
  const saved = { archive_path: '/data/banking-state/legacy-bank-before-native.sqlite3', operator_proof: {
    path: root + '/operator.json', coverage_proof_path: root + '/coverage.json',
    lease_artifact: { path: root + '/lease.json' }, authority_artifact: { path: root + '/authority.json' },
    obligation_artifacts: [{ path: root + '/revoke.json' }],
    archives: { frontend: { path: root + '/frontend.tar' }, worker: { path: root + '/worker.tar' } },
  } };
  assert.equal(transitionEvidenceFiles(saved).length, 8);
  for (const unsafe of ['/data/private/operator.json', root + '/../operator.json', root + '/./operator.json',
    '/data/native-authority/control/operator.json', null]) {
    const changed = structuredClone(saved); changed.operator_proof.path = unsafe;
    assert.throws(() => transitionEvidenceFiles(changed), /bank-only/);
  }
  const moved = structuredClone(saved); moved.archive_path = root + '/bank.sqlite3';
  assert.throws(() => transitionEvidenceFiles(moved), /Incomplete/);
});
test('a failed service terminates its sibling process group', { skip: process.platform === 'win32' }, async () => {
  const started = Date.now();
  const result = await supervise({ graceMs: 1000, commands: [
    { name: 'failure', command: process.execPath, args: ['-e', 'setTimeout(()=>process.exit(7),100)'], env: process.env },
    { name: 'sibling', command: process.execPath, args: ['-e', 'setInterval(()=>{},10000)'], env: process.env },
  ] });
  assert.equal(result, 7); assert(Date.now() - started < 3000);
});
