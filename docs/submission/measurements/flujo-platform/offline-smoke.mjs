// Real pinned retry policy module, no provider/MCP server or mocked imports.
// Tested on Node 22.13.1 with --experimental-strip-types.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import {
  parseRetryAfterMs,
  planAutomaticRetry,
  resolveAutomaticRetryDelayMs,
  waitForRetryWindow,
  MAX_AUTOMATIC_MODEL_RETRIES,
} from './source/src/backend/execution/flow/retryAfter.ts';

const checks = [];
async function check(name, task) { await task(); checks.push({ name, passed: true }); }
await check('delta seconds and HTTP-date use explicit clock', () => {
  assert.equal(parseRetryAfterMs('2'), 2000);
  assert.equal(parseRetryAfterMs('Thu, 01 Jan 1970 00:00:03 GMT', 1000), 2000);
});
await check('invalid, negative, nonfinite and expired waits are rejected', () => {
  for (const value of [null, undefined, -1, Infinity, '-1', '+1', 'garbage']) assert.equal(parseRetryAfterMs(value, 1000), undefined);
  assert.equal(parseRetryAfterMs('Thu, 01 Jan 1970 00:00:00 GMT', 1000), undefined);
});
await check('automatic retry delay is bounded to fifteen minutes', () => {
  assert.equal(resolveAutomaticRetryDelayMs('900'), 900000);
  assert.equal(resolveAutomaticRetryDelayMs('901'), undefined);
  assert.equal(MAX_AUTOMATIC_MODEL_RETRIES, 3);
});
await check('rate limit needs usable retry timing', () => {
  assert.equal(planAutomaticRetry({ message: 'Too many requests', details: { status: 429 } }), undefined);
  const plan = planAutomaticRetry({ message: 'Too many requests', details: { status: 429, retryAfter: 2 } }, { now: 1000 });
  assert.deepEqual(plan, { delayMs: 2000, retryAt: 3000, reason: 'session_limit', status: 429, code: undefined });
  assert.equal(planAutomaticRetry({ message: 'socket closed', details: { status: 502, retryAfter: 2 } }), undefined);
});
await check('aborted or zero-delay wait ends without a provider call', async () => {
  const controller = new AbortController(); controller.abort();
  assert.equal(await waitForRetryWindow(60000, { signal: controller.signal }), 'aborted');
  assert.equal(await waitForRetryWindow(0), 'ready');
});
const root = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(path.join(root, 'source/src/backend/execution/flow/retryAfter.ts'));
const result = {
  schemaVersion: 1, observedAt: new Date().toISOString(), commit: '0be972ac7b748703d09e407ef96beba45ab17b2a',
  runtime: { node: process.version, platform: process.platform, architecture: process.arch },
  source: { path: 'src/backend/execution/flow/retryAfter.ts', sha256: crypto.createHash('sha256').update(source).digest('hex') },
  command: 'node --experimental-strip-types --require ./offline-preload.cjs ./offline-smoke.mjs',
  kind: 'Narrow local checks against one copied unmodified upstream module', checks,
};
if (process.argv.includes('--write-receipt')) fs.writeFileSync(path.join(root, 'offline-smoke-results.json'), JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify(result));
