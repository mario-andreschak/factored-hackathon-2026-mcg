#!/usr/bin/env node
/** Execute the installed adapter's exact authority fences without a provider. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';

const [sourcePath, dependencyRoot] = process.argv.slice(2);
assert(sourcePath && dependencyRoot, 'Expected adapter source and dependency root');
const source = fs.readFileSync(sourcePath, 'utf8');
const ts = createRequire(path.join(path.resolve(dependencyRoot), 'package.json'))('typescript');
const tree = ts.createSourceFile(sourcePath, source, ts.ScriptTarget.ES2022, true);
const names = new Set(['admissions', 'assertNotRevokedToken', 'assertNotRevoked', 'current']);
const selected = tree.statements.filter(node => names.has(node.name?.text)
  || ts.isVariableStatement(node) && node.declarationList.declarations.some(item => names.has(item.name?.text)));
assert.equal(selected.length, names.size, 'Authority fence declarations missing');
const compiled = ts.transpileModule(selected.map(node => node.getText(tree)).join('\n'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS }, reportDiagnostics: true });
assert(!compiled.diagnostics?.some(item => item.category === ts.DiagnosticCategory.Error));
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'gloria-revocation-probe-'));
const assertScratchRoot = () => {
  assert.equal(path.dirname(path.resolve(root)), path.resolve(os.tmpdir()));
  assert.equal(fs.realpathSync(root), path.resolve(root));
  assert(path.basename(root).startsWith('gloria-revocation-probe-'));
};
assertScratchRoot();
fs.mkdirSync(path.join(root, 'revocations'));
const sha = value => createHash('sha256').update(value).digest('hex');
const marker = token => path.join(root, 'revocations', sha(token) + '.revoked');
const writeMarker = token => fs.writeFileSync(marker(token), 'revoked\n', { mode: 0o600 });
class ExecutionExtensionError extends Error { constructor(code) { super(code); this.code = code; } }
const run = { token: 'synthetic-transport', stageToken: 'synthetic-stage', owner: 'synthetic-owner',
  turnId: 'synthetic-turn', conversation: 'synthetic-conversation', expires: Date.now() + 60000,
  bindingFingerprint: 'synthetic-binding' };
const runs = new WeakSet([run]);
let onRead, reads = 0, stat = fs.lstatSync;
const sandbox = { ROOT: root, path, sha, runs, ExecutionExtensionError,
  fail: (code = 'gloria_qualification_denied') => { throw new ExecutionExtensionError(code); },
  ledger: () => ({ owners: { [run.conversation]: 'owner-key' } }), ownerKey: () => 'owner-key',
  lstatSync: (...args) => stat(...args), readFile: async () => { reads++; if (onRead) await onRead(); return JSON.stringify([run]); } };
vm.createContext(sandbox); new vm.Script(compiled.outputText).runInContext(sandbox);
const cases = [];
async function denied(name, action, expected) {
  let code; try { await action(); } catch (error) { code = error.code; }
  cases.push({ case: name, pass: code === expected, provider_calls: 0 });
  assert.equal(code, expected, name);
}
try {
  writeMarker(run.stageToken);
  await denied('initial_revocation_blocks_registry_read', () => sandbox.current(run), 'gloria_stage_revoked');
  assert.equal(reads, 0);
  fs.unlinkSync(marker(run.stageToken));
  onRead = async () => { writeMarker(run.stageToken); };
  await denied('revocation_after_registry_await', () => sandbox.current(run), 'gloria_stage_revoked');
  fs.unlinkSync(marker(run.stageToken)); onRead = undefined;
  writeMarker('foreign-synthetic-stage');
  await sandbox.current(run);
  cases.push({ case: 'foreign_marker_preserves_sibling', pass: true, provider_calls: 0 });
  stat = location => { if (location === marker(run.stageToken)) throw Object.assign(new Error('synthetic IO'), { code: 'EACCES' }); return fs.lstatSync(location); };
  await denied('unexpected_marker_io_denied', () => sandbox.current(run), 'gloria_revocation_unavailable');
  stat = fs.lstatSync;
  const revocations = path.resolve(root, 'revocations');
  assertScratchRoot();
  assert.equal(path.dirname(revocations), path.resolve(root));
  assert.equal(fs.realpathSync(revocations), revocations);
  fs.rmSync(revocations, { recursive: true });
  await denied('unavailable_authority_directory_denied', () => sandbox.current(run), 'gloria_revocation_unavailable');
  console.log(JSON.stringify({ pass: cases.every(item => item.pass), cases,
    adapterSourceSha256: sha(source), fixtureSha256: sha(fs.readFileSync(new URL(import.meta.url))),
    scope: 'Exact installed adapter declarations, deferred registry read, zero provider execution' }));
} finally {
  assertScratchRoot();
  fs.rmSync(root, { recursive: true, force: true });
}
