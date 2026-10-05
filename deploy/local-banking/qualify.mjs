import fs from 'node:fs';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';

const archive = '/tmp/qualified-banking-next.tar';
const expected = process.argv[2];
const actual = crypto.createHash('sha256').update(fs.readFileSync(archive)).digest('hex');
if (!/^[a-f0-9]{64}$/.test(expected ?? '') || actual !== expected) {
  throw new Error('Qualified banking build archive digest mismatch.');
}
const entries = execFileSync('tar', ['-tf', archive], { encoding: 'utf8' }).trim().split('\n');
if (!entries.length || entries.some(name =>
  !/^\.next(?:\/|$)/.test(name) || name.split('/').includes('..'))) {
  throw new Error('Qualified archive must contain only the application .next tree.');
}
fs.rmSync('/app/.next', { recursive: true, force: true });
execFileSync('tar', ['-xf', archive, '-C', '/app']);
const middleware = fs.readFileSync('/app/.next/server/middleware.js', 'utf8');
if (['banking_control_forbidden', 'frontendKeys', 'executionToken'].some(marker =>
  !middleware.includes(marker))) {
  throw new Error('Compiled banking adapter is missing from middleware.');
}
for (const route of ['chat/completions', 'banking/session/revoke']) {
  if (!fs.statSync(`/app/.next/server/app/v1/${route}/route.js`).isFile()) {
    throw new Error('Required banking route is missing.');
  }
}
console.log(JSON.stringify({ qualified: true, archiveSha256: actual, bankingAdapterSelected: true }));
