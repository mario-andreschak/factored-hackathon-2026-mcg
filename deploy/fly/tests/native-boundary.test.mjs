import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import Module, { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { pinnedEngineFixture, FLUJO_PIN } from './pinned-native-engine.mjs';
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
function adapterFixture(extensionRuntime) {
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
  let currentInput, afterRead, permissions, runValue;
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
  class FixtureExtensionError extends Error { constructor(code, status = 403) { super(code); this.code = code; this.status = status; } }
  const extensionBridge = extensionRuntime ? {
    ...extensionRuntime,
    createExecutionExtensionContext: (adapter, value) => {
      runValue = value; return extensionRuntime.createExecutionExtensionContext(adapter, value);
    },
    runWithExecutionInput: (input, task) => {
      currentInput = input; return extensionRuntime.runWithExecutionInput(input, task);
    },
  } : {
    ExecutionExtensionError: FixtureExtensionError,
    createExecutionExtensionContext: (_adapter, value) => ({ value }),
    runWithExecutionInput: (input, task) => { currentInput = input; return task(); },
  };
  const overrides = {
    'node:path': path.posix, 'node:fs': disk, 'node:fs/promises': { readFile: async location => { const value = files.get(location); afterRead?.(location); return value; } },
    'next/server': { NextRequest: Request }, '@/utils/workspace': { runWithWorkspace: (_workspace, task) => task() },
    '@/backend/services/workspace/workspaceMutationGate': { withWorkspaceMutation: task => task() },
    '@/backend/services/flow/executionSnapshot': { createFlowExecutionSnapshot: (_workspace, flow) => ({ flow, contentHash: 'e'.repeat(64) }) },
    '@/backend/execution/extensions': extensionBridge,
  };
  const module = new Module(sourceFile); module.filename = sourceFile;
  module.require = name => Object.hasOwn(overrides, name) ? overrides[name] : requirePackage(name);
  module._compile(compiled.outputText, sourceFile);
  return { adapter: module.exports.configuredExecutionAdapter, record, files, writes, control,
    input: () => currentInput, runValue: () => runValue,
    setAfterRead: hook => { afterRead = hook; }, setPermissions: hook => { permissions = hook; } };
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
  assert.equal(f.input().flowDefinition.nodes.length, 2);
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

// Targeted engine routing proof: no ProcessNode.execCore or provider is executed.
// The exact pinned engine converts/prepares the actual adapter graph, and its post
// method receives a visibly synthetic success value only to verify leaf routing.
async function admittedEngineFixture() {
  const engine = pinnedEngineFixture();
  const f = adapterFixture(engine.extensions);
  const handoffNames = [];
  const denyHandoffs = f.adapter.authorizeHandoffs;
  f.adapter.authorizeHandoffs = function (value, names) {
    handoffNames.push([...names]); return denyHandoffs.call(this, value, names);
  };
  const unregister = engine.extensions.registerExecutionExtension(f.adapter);
  try {
    const response = await f.adapter.withRoute(stageRequest(f.record), () => Response.json({ fixture: true }));
    assert.equal(response.status, 200);
    const input = f.input();
    assert.ok(input.executionExtensionContext);
    await engine.extensions.assertExecutionExtensionCurrent(input.executionExtensionContext);
    return { engine, f, input, handoffNames, unregister };
  } catch (error) { unregister(); throw error; }
}
function engineState(input, graph = input.flowDefinition) {
  return { flowId: graph.id, flowSnapshot: graph, conversationId: input.conversationId,
    logicalRunId: input.runId, executionExtensionContext: input.executionExtensionContext,
    ephemeral: true, debugMode: false, requireApproval: false, onApprovalRequired: 'fail',
    trackingInfo: { nodeExecutionTracker: [] },
    messages: [{ id: 'synthetic-user', role: 'user', content: 'Synthetic request.', timestamp: 1 }] };
}
async function preparedProcess(engine, state, graph) {
  const flow = engine.FlowConverter.convert(graph);
  const start = await flow.getStartNode();
  assert.ok(start instanceof engine.StartNode);
  const startResult = await start.run(state);
  assert.equal(startResult.action, 'start-process');
  const process = start.getSuccessor(startResult.action);
  assert.ok(process instanceof engine.ProcessNode);
  return process;
}
test('pinned FLUJO converts the real restricted graph to a tool-free Process leaf and retains its final response', async () => {
  const fixture = await admittedEngineFixture();
  const { engine, input, handoffNames } = fixture;
  try {
    assert.equal(engine.pin, FLUJO_PIN);
    assert.deepEqual(input.flowDefinition.nodes.map(node => node.type), ['start', 'process']);
    assert.deepEqual(input.flowDefinition.edges.map(edge => edge.id), ['start-process']);
    const state = engineState(input);
    const process = await preparedProcess(engine, state, input.flowDefinition);
    assert.equal(process.successors.size, 0);
    const prep = await process.prep(state, process.node_params);
    assert.deepEqual(prep.availableTools, []);
    assert.deepEqual(handoffNames, [[]]);
    assert.deepEqual(state.toolNameMap, {});
    assert.equal(state.currentMCPNodes, undefined);
    assert.equal(prep.executionExtensionContext, input.executionExtensionContext);
    const syntheticResult = { success: true, content: 'TEST_ONLY_SYNTHETIC_ENGINE_RESULT', toolCalls: [],
      effectiveMaxTurns: 1, messages: [{ id: 'synthetic-engine-output', role: 'assistant',
        content: 'TEST_ONLY_SYNTHETIC_ENGINE_RESULT', timestamp: 2 }] };
    const action = await process.post(prep, syntheticResult, state, process.node_params);
    assert.equal(action, engine.FINAL_RESPONSE_ACTION);
    assert.equal(process.getSuccessor(action), undefined);
    assert.equal(state.lastResponse, syntheticResult.content);
    assert.ok(state.messages.some(message => message.id === 'synthetic-engine-output'
      && message.content === syntheticResult.content));
    assert.equal(engine.providerCalls(), 0);
    assert.equal(engine.unexpectedCapabilityCalls(), 0);
  } finally { fixture.unregister(); }
});
test('pinned FLUJO reproduces the old Finish handoff denial before any provider execution', async () => {
  const fixture = await admittedEngineFixture();
  const { engine, input, handoffNames, f } = fixture;
  try {
    const graph = structuredClone(input.flowDefinition);
    graph.nodes.push({ id: 'finish', type: 'finish', position: { x: 0, y: 400 },
      data: { type: 'finish', label: 'Finish', properties: {} } });
    graph.edges.push({ id: 'process-finish', source: 'process', target: 'finish',
      sourceHandle: 'process-bottom', targetHandle: 'finish-top', type: 'custom', data: { edgeType: 'standard' } });
    const state = engineState(input, graph);
    const process = await preparedProcess(engine, state, graph);
    assert.equal(process.successors.size, 1);
    await assert.rejects(process.prep(state, process.node_params), error =>
      error instanceof engine.extensions.ExecutionExtensionError && error.code === 'dispute_native_tools_forbidden');
    assert.deepEqual(handoffNames, [['handoff_to_finish']]);
    assert.equal(engine.providerCalls(), 0);
    assert.equal(engine.unexpectedCapabilityCalls(), 0);
    assert.throws(() => f.adapter.authorizeHandoffs(f.runValue(), ['handoff_to_finish']));
    await assert.rejects(f.adapter.assertModelTool(f.runValue(), 'bank_read', { server: 'bank', tool: 'read' }));
    await assert.rejects(f.adapter.assertDispatch(f.runValue(), 'bank', 'model'));
    assert.throws(() => f.adapter.normalizeArguments(f.runValue(), 'bank_read', {}));
    await assert.rejects(f.adapter.requestMeta(f.runValue(), 'bank', 'read', {}));
    assert.throws(() => f.adapter.validateResult(f.runValue(), 'bank_read', {}));
  } finally { fixture.unregister(); }
});
