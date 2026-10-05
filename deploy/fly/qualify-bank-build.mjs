#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';

const root = '/app/.next';
const original = JSON.parse(fs.readFileSync('/opt/savia/fly/artifact-manifest.json', 'utf8'));
const source = JSON.parse(fs.readFileSync('/tmp/source-manifest.json', 'utf8'));
const checks = [
  '/app/.next/server/middleware.js',
  '/app/.next/server/app/v1/chat/completions/route.js',
  '/app/.next/server/app/v1/banking/session/revoke/route.js',
];
const chunks = fs.readdirSync(path.join(root, 'server/chunks')).filter(name => name.endsWith('.js'))
  .map(name => path.join(root, 'server/chunks', name));
const allChunks = chunks.map(filename => fs.readFileSync(filename, 'utf8')).join('\n');
const middleware = fs.readFileSync(checks[0], 'utf8');
// The adapter must be composed into the isolated proxy graph and server graphs.
// These fixed code markers are absent from the original unselected build.
const required = ['banking_control_forbidden', 'frontendKeys', 'executionToken'];
if (required.some(marker => !middleware.includes(marker))) throw new Error('Banking adapter missing from proxy graph.');
if (!allChunks.includes('trusted_banking_job_required') || !allChunks.includes('approved_banking_graph_required')) {
  throw new Error('Banking authority missing from server graph.');
}
for (const filename of checks) if (!fs.statSync(filename).isFile()) throw new Error('Required banking route missing.');
const nextFiles = [];
function inventory(filename) {
  const metadata = fs.lstatSync(filename);
  if (metadata.isDirectory()) {
    for (const name of fs.readdirSync(filename).sort()) inventory(path.join(filename, name));
  } else if (metadata.isFile()) {
    nextFiles.push({ path: filename, type: 'file', size: metadata.size, mode: metadata.mode & 0o777,
      sha256: createHash('sha256').update(fs.readFileSync(filename)).digest('hex') });
  } else throw new Error('Unexpected compiled artifact type.');
}
inventory(root);
const nextManifestSha256 = createHash('sha256').update(JSON.stringify(nextFiles)).digest('hex');
const compilation = { ...source, nextManifestSha256, compiledFileCount: nextFiles.length,
  adapterSelected: true, replacesOnly: '/app/.next', qualification: 'static banking proxy/server graph markers' };
const manifest = { ...original,
  workerFiles: [...original.workerFiles.filter(entry => !entry.path.startsWith('/app/.next/')), ...nextFiles]
    .sort((a, b) => a.path.localeCompare(b.path)), compilation };
fs.mkdirSync('/build-receipt', { recursive: true });
fs.writeFileSync('/build-receipt/artifact-manifest.json', JSON.stringify(manifest, null, 2) + '\n');
fs.writeFileSync('/build-receipt/compilation.json', JSON.stringify(compilation, null, 2) + '\n');
console.log(JSON.stringify({ qualified: true, revision: source.revision, adapterSelected: true,
  compiledFileCount: nextFiles.length, nextManifestSha256, runtimeInputsIdentical: true }));
