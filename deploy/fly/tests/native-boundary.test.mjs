import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import Module, { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { validateInvocation, buildBubblewrapArgs, SDK_HOME_PARENT, RAW_CLI_PATH, RAW_CLI_SHA256 } from '../native-codex-wrapper.mjs';

const home = SDK_HOME_PARENT + '/codex-private-aB123456';
function environment() {
  return { HOME: home, USERPROFILE: home, CODEX_HOME: home, PATH: '/untrusted/bin', BANK_CONFIG: 'SECRET',
    APPDATA: home + '/AppData/Roaming', LOCALAPPDATA: home + '/AppData/Local',
    XDG_CONFIG_HOME: home + '/.config', XDG_CACHE_HOME: home + '/.cache',
    XDG_DATA_HOME: home + '/.local/share', XDG_STATE_HOME: home + '/.local/state',
    XDG_RUNTIME_DIR: home + '/.runtime', TMPDIR: home + '/tmp', TMP: home + '/tmp', TEMP: home + '/tmp',
    CODEX_INTERNAL_ORIGINATOR_OVERRIDE: 'codex_sdk_ts' };
}
const argv = ['exec', '--experimental-json', '--sandbox', 'read-only', '--cd', home + '/workspace'];
function invocationIo(change = () => {}) {
  return { realpathSync: value => value, lstatSync: value => {
    const file = /\/(auth.json|config.toml|model-catalog.json)$/.test(value);
    const stat = { uid: 1000, mode: file ? 0o600 : 0o700, isDirectory: () => !file,
      isFile: () => file, isSymbolicLink: () => false };
    change(value, stat); return stat;
  } };
}
test('only the exact private SDK invocation home is admitted', () => {
  assert.deepEqual(validateInvocation(argv, environment(), invocationIo(), 1000), { home, cwd: home + '/workspace' });
  for (const altered of [SDK_HOME_PARENT, '/data/banking', home + '/..', home + '/other']) {
    const env = { ...environment(), HOME: altered, USERPROFILE: altered, CODEX_HOME: altered };
    assert.throws(() => validateInvocation(argv, env, invocationIo(), 1000));
  }
  assert.throws(() => validateInvocation(argv, environment(), invocationIo(), 0));
  assert.throws(() => validateInvocation([...argv, '--cd', '/data'], environment(), invocationIo(), 1000));
  assert.throws(() => validateInvocation(['exec', 'resume', ...argv.slice(1)], environment(), invocationIo(), 1000));
});
test('symlinks, changed owners, loose permissions and foreign tmp dirs deny admission', () => {
  for (const mutate of [stat => { stat.uid = 10001; }, stat => { stat.mode = 0o755; },
    stat => { stat.isSymbolicLink = () => true; }]) {
    assert.throws(() => validateInvocation(argv, environment(), invocationIo((value, stat) => {
      if (value === home) mutate(stat);
    }), 1000));
  }
  assert.throws(() => validateInvocation(argv, { ...environment(), TMPDIR: '/tmp' }, invocationIo(), 1000));
  const io = invocationIo(); io.realpathSync = value => value === home ? '/data' : value;
  assert.throws(() => validateInvocation(argv, environment(), io, 1000));
});
test('bubblewrap hides host data and process trees while retaining provider networking', () => {
  const args = buildBubblewrapArgs({ home, cwd: home + '/workspace' }, argv, environment(), () => true);
  const binds = args.flatMap((value, index) => ['--bind', '--ro-bind'].includes(value) ? [[value, args[index + 1], args[index + 2]]] : []);
  assert.deepEqual(binds.filter(([kind]) => kind === '--bind'), [['--bind', home, home]]);
  assert.deepEqual(binds.filter(([, source]) => source.startsWith('/data')), [['--bind', home, home]]);
  assert.ok(binds.every(([, source]) => source === home || source === RAW_CLI_PATH || source.startsWith('/etc/')));
  for (const flag of ['--unshare-user', '--unshare-pid', '--unshare-ipc', '--unshare-uts', '--clearenv', '--die-with-parent']) assert.ok(args.includes(flag));
  assert.ok(!args.includes('--unshare-net'));
  assert.ok(!args.includes('--share-user'));
  assert.ok(!args.includes('SECRET'));
  assert.ok(!args.includes('/untrusted/bin'));
  assert.deepEqual(args.slice(args.lastIndexOf('--') + 1), [RAW_CLI_PATH, ...argv]);
  assert.equal(RAW_CLI_SHA256, '3e2584f3f3829a43a0495011a1cecb2facbe64a2403e2b682351fd9c2983f970');
});

// Exercise the real adapter declarations with synthetic controls and actual Request/Response.
// Only FLUJO graph/runtime wiring and disk are substituted; no provider is executed.
const sourceFile = fileURLToPath(new URL('../native-execution.mts', import.meta.url));
function adapterFixture() {
  const flujoRoot = process.env.FLUJO_SOURCE_ROOT;
  assert.ok(flujoRoot, 'Set FLUJO_SOURCE_ROOT to the pinned FLUJO source with installed TypeScript.');
  const requirePackage = createRequire(path.join(flujoRoot, 'package.json'));
  const ts = requirePackage('typescript');
  const compiled = ts.transpileModule(fs.readFileSync(sourceFile, 'utf8'), { fileName: 'native-execution.ts',
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, esModuleInterop: true }, reportDiagnostics: true });
  assert.ok(!compiled.diagnostics?.some(d => d.category === ts.DiagnosticCategory.Error));
  const control = '/data/native-authority/control', worker = '/data/native-authority/worker';
  const record = { mode: 'language_only', token: 'a'.repeat(48), stageToken: 'b'.repeat(48), owner: 'synthetic-owner',
    conversation: 'synthetic-conversation', runId: 'synthetic-run', turnId: 'synthetic-turn', message: 'synthetic',
    graphHash: '', flowId: '', server: 'dispute-language-only', expires: Date.now() + 60000, bindingFingerprint: 'c'.repeat(64) };
  const files = new Map([[control + '/admissions.json', JSON.stringify([record])]]), writes = [];
  let currentInput, afterRead, permissions;
  const profile = { verifiedCliVersion: '0.157.1', verifiedCliPath: '/opt/native/codex-wrapper.mjs', verifiedCliSha256: 'd'.repeat(64),
    verifiedModelCatalogPath: '/opt/native/model-catalog.json', verifiedModelCatalogSha256: '5a1ddcef609e52bd057b247d9487f2c8c4d9453d3d802745ba5325c2e10700e0' };
  files.set('/opt/native/native-profile.json', JSON.stringify(profile));
  function stat(location) {
    if (location.endsWith('.revoked') && !files.has(location)) { const error = new Error('absent'); error.code = 'ENOENT'; throw error; }
    const directory = [control, control + '/revocations', worker, '/opt/native'].includes(location);
    const ownedControl = location.startsWith(control), immutable = location.startsWith('/opt/native');
    const value = { uid: immutable ? 0 : ownedControl ? 10001 : 1000, gid: ownedControl ? 10002 : 1000,
      mode: immutable ? directory ? 0o755 : 0o444 : ownedControl ? directory ? 0o2750 : 0o640 : directory ? 0o700 : 0o600,
      ino: 1, size: (files.get(location) ?? '').length, mtimeMs: 1,
      isDirectory: () => directory, isFile: () => !directory, isSymbolicLink: () => false };
    permissions?.(location, value); return value;
  }
  function write(location, bytes) { assert.ok(location.startsWith(worker + '/'), 'worker must never write controls'); writes.push(location); files.set(location, bytes); }
  const disk = { lstatSync: stat, existsSync: location => files.has(location), readFileSync: location => files.get(location),
    writeFileSync: write, appendFileSync: (location, bytes) => write(location, (files.get(location) ?? '') + bytes),
    renameSync: (from, to) => { write(to, files.get(from)); files.delete(from); }, openSync: () => 1, fsyncSync() {}, closeSync() {} };
  class ExecutionExtensionError extends Error { constructor(code, status = 403) { super(code); this.code = code; this.status = status; } }
  const overrides = {
    'node:path': path.posix, 'node:fs': disk, 'node:fs/promises': { readFile: async location => { const value = files.get(location); afterRead?.(location); return value; } },
    'next/server': { NextRequest: Request }, '@/utils/workspace': { runWithWorkspace: (_workspace, task) => task() },
    '@/backend/services/workspace/workspaceMutationGate': { withWorkspaceMutation: task => task() },
    '@/backend/services/flow/executionSnapshot': { createFlowExecutionSnapshot: (_workspace, flow) => ({ flow, contentHash: 'e'.repeat(64) }) },
    '@/backend/execution/extensions': { ExecutionExtensionError, createExecutionExtensionContext: (_adapter, value) => ({ value }),
      runWithExecutionInput: (input, task) => { currentInput = input; return task(); } },
  };
  const module = new Module(sourceFile); module.filename = sourceFile;
  module.require = name => Object.hasOwn(overrides, name) ? overrides[name] : requirePackage(name);
  module._compile(compiled.outputText, sourceFile);
  return { adapter: module.exports.configuredExecutionAdapter, record, files, writes, control,
    input: () => currentInput, setAfterRead: hook => { afterRead = hook; }, setPermissions: hook => { permissions = hook; } };
}
function stageRequest(record, overrides = {}) {
  return new Request('http://127.0.0.1:4200/v1/chat/completions', { method: 'POST',
    headers: { authorization: 'Bearer ' + record.stageToken }, body: JSON.stringify({ model: 'model-dispute-native-model',
      messages: [{ role: 'system', content: 'Synthetic JSON contract.' }, { role: 'user', content: 'Synthetic request.' }], stream: false, ...overrides }) });
}
test('real adapter admits only fresh tool-free graphs and writes only worker state', async () => {
  const f = adapterFixture(); let delegated;
  const response = await f.adapter.withRoute(stageRequest(f.record), async request => { delegated = request; return Response.json({ ok: true }); });
  assert.equal(response.status, 200);
  assert.equal(delegated.headers.get('authorization'), null);
  assert.equal(f.input().mode, 'ephemeral');
  assert.equal(f.input().debug, false);
  assert.equal(f.input().flowDefinition.nodes.length, 3);
  assert.ok(f.writes.length > 0 && f.writes.every(value => value.startsWith('/data/native-authority/worker/')));
  await f.adapter.assertRun(f.input().executionExtensionContext.value);
  await f.adapter.codexProfile(f.input().executionExtensionContext.value);
  await assert.rejects(f.adapter.assertModelTool({}, 'approved_read', { server: 'bank', tool: 'read' }));
  await assert.rejects(f.adapter.assertDispatch({}, 'bank', 'model'));
});
test('body substitution and wrong permissions fail before provider delegation', async () => {
  for (const mutate of [f => { f.record.expires = Date.now() - 1; f.files.set(f.control + '/admissions.json', JSON.stringify([f.record])); },
    f => f.setPermissions((location, stat) => { if (location.endsWith('admissions.json')) stat.mode = 0o660; })]) {
    const f = adapterFixture(); mutate(f); let called = false;
    const response = await f.adapter.withRoute(stageRequest(f.record), async () => { called = true; return Response.json({}); });
    assert.equal(response.status, 403); assert.equal(called, false);
  }
  const f = adapterFixture(); let called = false;
  const response = await f.adapter.withRoute(stageRequest(f.record, { tools: [{ name: 'read_bank' }] }), async () => { called = true; return Response.json({}); });
  assert.equal(response.status, 403); assert.equal(called, false);
});
test('revocation racing the async registry read blocks provider work', async () => {
  const f = adapterFixture();
  const { createHash } = await import('node:crypto');
  const marker = f.control + '/revocations/' + createHash('sha256').update(f.record.stageToken).digest('hex') + '.revoked';
  f.setAfterRead(location => { if (location.endsWith('admissions.json')) f.files.set(marker, 'revoked'); });
  let called = false;
  const response = await f.adapter.withRoute(stageRequest(f.record), async () => { called = true; return Response.json({}); });
  assert.equal(response.status, 403); assert.equal(called, false);
});
test('mutable profile and unbranded run cannot reach the native adapter', async () => {
  const f = adapterFixture();
  await f.adapter.withRoute(stageRequest(f.record), async () => Response.json({}));
  await assert.rejects(f.adapter.assertRun({ ...f.input().executionExtensionContext.value }));
  f.setPermissions((location, stat) => { if (location === '/opt/native/native-profile.json') stat.mode = 0o664; });
  await assert.rejects(f.adapter.codexProfile(f.input().executionExtensionContext.value));
});
