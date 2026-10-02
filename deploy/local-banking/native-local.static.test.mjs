import assert from 'node:assert/strict';
import { admittedRequest } from './local-proxy.mjs';
import { localCommands } from './native-local.mjs';

// Pure boundary checks only: no listeners, DATA, credentials, provider or ledger.
const same = { host: 'localhost:43800', origin: 'http://localhost:43800' };
assert.equal(admittedRequest('POST', '/api/action/confirm', same), true);
assert.equal(admittedRequest('GET', '/api/action/status', { host: same.host }), true);
for (const [method, url, headers] of [
  ['POST', '/api/action/confirm', { host: same.host }],
  ['POST', '/api/action/confirm', { ...same, origin: 'http://localhost:43420' }],
  ['GET', '/', { ...same, host: 'attacker.example' }],
  ['GET', '//attacker.example/', same],
  ['GET', '/v1/chat/completions', same],
  ['GET', '/mcp', same],
  ['GET', '/', { ...same, 'sec-fetch-site': 'cross-site' }],
]) assert.equal(admittedRequest(method, url, headers), false);
const commands = localCommands('boundary-test-only-value'.padEnd(32, 'x'));
assert.equal(commands.length, 3);
assert.equal(commands[0].env.FLUJO_DATA_DIR, '/data/native-flujo');
assert.equal(commands[1].env.BANKING_PUBLIC_ORIGIN, 'http://localhost:43800');
assert.equal(commands[1].env.BANKING_COOKIE_SECURE, '0');
assert.equal(commands[1].args.includes('--source-root'), false);
assert.equal(commands[1].args.includes('--transition-receipt'), true);
assert.equal(commands.filter(command => command.args.includes('/opt/joined/scripts/run_dispute.py')).length, 1);
for (const command of commands) {
  assert.equal(command.env.AWS_SECRET_ACCESS_KEY, undefined);
  assert.equal(command.env.FLUJO_WORKER_SNAPSHOT_KEY, undefined);
  assert.equal(command.env.FLUJO_BANKING_CONFIG, undefined);
}
assert.equal(commands[1].env.FLUJO_SNAPSHOT_CONTROL_TOKEN, undefined);
assert.equal(commands[2].env.FLUJO_SNAPSHOT_CONTROL_TOKEN, undefined);
console.log('PASS: local proxy admission and child environment boundaries (pure static checks).');
