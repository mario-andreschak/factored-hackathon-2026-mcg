'use strict';
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test, before } = require('node:test');
const { build, loadFlujo, readInputs, assertCustomerBoundary, DEFAULT_BINDINGS, PIN } = require('./build.cjs');

const root = process.env.FLUJO_SOURCE_ROOT;
assert(root, 'Set FLUJO_SOURCE_ROOT to the restored pinned checkout; tests must not silently skip');
let result;
before(() => { result = build(root); });
const node = (flow, kind) => flow.nodes.find(item => item.data.type === kind);
function rejectChangedFlow(mutate) {
  const flow = structuredClone(result.flow);
  mutate(flow);
  // A fresh hash does not make an added capability an approved language graph.
  const changedHash = result.flujo.hashFlowExecutionSnapshot(flow);
  assert.notEqual(changedHash, result.manifest.sha256.compiledExecutionSnapshot);
  assert.throws(() => assertCustomerBoundary(flow, result.inputs, result.flujo));
}

test('actual compiler is deterministic and matches the committed language-only artifacts', () => {
  const repeated = build(root);
  for (const [filename, bytes] of Object.entries(result.files)) {
    assert(bytes.equals(repeated.files[filename]), filename);
    assert(bytes.equals(fs.readFileSync(path.join(__dirname, 'generated', filename))), filename);
  }
  assert.equal(result.manifest.flujoCommit, PIN);
  assert.equal(result.manifest.exampleBindings, true);
  assert.equal(result.manifest.compileIssues.length, 0);
  assert.equal(result.manifest.validationIssues.length, 0);
  assert.equal(result.flow.nodes.length, 3);
  assert.deepEqual(result.flow.nodes.map(item => item.type).sort(), ['finish', 'process', 'start']);
  assert.deepEqual(result.manifest.bindings, { modelId: 'existing-model-id' });
  assert.deepEqual(result.manifest.modelBankingTools, []);
});

test('only generic pure FLUJO source modules supply compilation and snapshot evidence', () => {
  const sourceFiles = Object.keys(result.manifest.flujoSourceFiles);
  assert(sourceFiles.includes('src/utils/shared/flowSpecCompiler.ts'));
  assert(sourceFiles.includes('src/shared/types/enduringAgent/schemas.ts'));
  assert(sourceFiles.includes('src/backend/services/flow/executionSnapshot.ts'));
  assert(sourceFiles.every(filename => !/integrations|execution\/extensions|services\/mcp\//.test(filename)));
  assert.equal(result.flujo.assertBankingGraph, undefined);
  assert.match(result.manifest.scope, /source-only; not installed or evaluated/);
});

test('canonical prompt embeds the exact agreed enum contract and grants no bank authority', () => {
  const canonical = path.resolve(__dirname, '../../resources/prompts/customer_v0.md');
  assert.equal(result.inputs.provenance.canonicalPrompt, 'resources/prompts/customer_v0.md');
  assert.equal(fs.existsSync(path.join(__dirname, 'prompt.md')), false);
  assert(fs.readFileSync(canonical).equals(result.inputs.promptBytes));
  assert.equal(node(result.flow, 'start').data.properties.promptTemplate, fs.readFileSync(canonical, 'utf8'));
  assert.equal(result.manifest.languageInput.schema, 'host-language-request/v1');
  assert.deepEqual(result.manifest.languageInput.displayFactFields,
    ['event_date', 'amount', 'currency', 'merchant', 'recorded_status']);
  assert.deepEqual(result.manifest.languageOutput.fields, ['schema', 'language', 'guidance']);
  assert.deepEqual(result.manifest.languageOutput.guidance,
    ['explain_selected', 'ask_date_or_amount', 'ask_selection', 'suggest_human', 'unavailable']);
  assert.equal(result.manifest.languageOutput.bankingAuthority, false);
  assert.equal(result.manifest.languageOutput.prose, false);
  assert.equal(result.manifest.languageOutput.extraFields, false);
  for (const schema of ['host-language-request/v1', 'host-language-guidance/v1']) assert(result.inputs.prompt.includes(schema));
  assert(!/banking_status|list_my_transactions|get_my_transaction|com\.flujo\.bank|FLUJO_BANKING_CONFIG/.test(result.inputs.prompt));
});

test('actual generic snapshot function reproduces the source execution hash', () => {
  const snapshot = result.flujo.createFlowExecutionSnapshot('source-only-workspace', result.flow);
  assert.equal(snapshot.contentHash, result.manifest.sha256.compiledExecutionSnapshot);
  assert.equal(snapshot.versionId, result.manifest.snapshotVersion);
  snapshot.flow.nodes[0].data.properties.promptTemplate = 'changed';
  assert.notEqual(result.flujo.hashFlowExecutionSnapshot(snapshot.flow), snapshot.contentHash);
  assert.equal(result.flow.nodes[0].data.properties.promptTemplate, result.inputs.prompt);
});

test('saved metadata and a different configured model change the execution hash', () => {
  const saved = structuredClone(result.flow);
  saved.createdAt = Date.UTC(2026, 8, 29);
  saved.updatedAt = saved.createdAt;
  const firstHash = assertCustomerBoundary(result.flujo.FlowSnapshotSchema.parse(saved), result.inputs, result.flujo).hash;
  assert.notEqual(firstHash, result.manifest.sha256.compiledExecutionSnapshot);
  saved.updatedAt += 1000;
  assert.notEqual(assertCustomerBoundary(result.flujo.FlowSnapshotSchema.parse(saved), result.inputs, result.flujo).hash, firstHash);
  assert.throws(() => result.flujo.FlowSnapshotSchema.parse({ ...saved, createdAt: '2026-09-29T00:00:00.000Z' }));
  const rebound = build(root, { modelId: 'configured-model-123' });
  assert.equal(rebound.manifest.exampleBindings, false);
  assert.notEqual(rebound.manifest.sha256.compiledExecutionSnapshot, result.manifest.sha256.compiledExecutionSnapshot);
});

test('bank server, private identity and authority cannot be supplied as graph bindings', async t => {
  for (const key of ['bankServer', 'customer_id', 'conversation_id', 'selection_handle', '_meta', 'signingKey']) {
    await t.test(key, () => assert.throws(() => readInputs({ ...DEFAULT_BINDINGS, [key]: 'unreviewed' }), /bindings/));
  }
});

test('replacement and additional executable nodes are rejected even after rehashing', async t => {
  for (const kind of ['mcp', 'static', 'bash', 'subflow']) {
    await t.test(kind, () => rejectChangedFlow(flow => {
      const item = node(flow, 'process');
      item.type = item.data.type = kind;
    }));
  }
  await t.test('additional MCP node', () => rejectChangedFlow(flow => {
    flow.nodes.push({ id: 'unreviewed', type: 'mcp', position: { x: 1, y: 1 },
      data: { type: 'mcp', label: 'unreviewed', properties: { boundServer: 'Banking MCP', enabledTools: ['confirm_simulated_intake'] } } });
  }));
});

test('capability and authority fields are rejected on the language Process', async t => {
  for (const key of ['boundServer', 'enabledTools', 'mcpNodes', 'toolParameterPresets', 'enabledResources',
    'enabledPrompts', 'enabledSkills', 'subflowId', 'code', 'customer_id', 'conversation_id',
    'selection_handle', '_meta', 'bankSigningKeyFile']) {
    await t.test(key, () => rejectChangedFlow(flow => { node(flow, 'process').data.properties[key] = 'unreviewed'; }));
  }
});

test('alternate prompt, flow attachments and conditional wiring cannot evade the source boundary', async t => {
  const mutations = [
    ['mutable prompt', flow => { node(flow, 'start').data.properties.promptTemplate = 'changed'; }],
    ['shared reference', flow => { node(flow, 'process').data.properties.promptTemplate = '${resource:shared}'; }],
    ['hidden node authority', flow => { node(flow, 'process').data._meta = { authority: 'unreviewed' }; }],
    ['input override', flow => { flow.input = { prompt: 'unreviewed' }; }],
    ['behavior attachment', flow => { flow.behaviorRules = { unreviewed: true }; }],
    ['permission attachment', flow => { flow.permissionRules = { unreviewed: true }; }],
    ['edge condition', flow => { flow.edges[0].data.condition = { kind: 'always' }; }],
    ['alternate edge', flow => { flow.edges[0].target = node(flow, 'finish').id; }],
    ['conflicting node type', flow => { node(flow, 'process').type = 'static'; }],
    ['duplicate node id', flow => { node(flow, 'finish').id = node(flow, 'process').id; }],
  ];
  for (const [label, mutate] of mutations) await t.test(label, () => rejectChangedFlow(mutate));
});

test('wrong source revision is refused before compiler execution', () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'customer-v0-source-pin-'));
  try {
    execFileSync('git', ['init', '-q', temporary]);
    execFileSync('git', ['-C', temporary, '-c', 'user.name=Source test', '-c', 'user.email=source@example.invalid', 'commit', '--allow-empty', '-qm', 'different source']);
    assert.throws(() => loadFlujo(temporary), /pinned commit/);
  } finally {
    assert(path.resolve(temporary).startsWith(path.resolve(os.tmpdir()) + path.sep + 'customer-v0-source-pin-'));
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});

test('saved-flow CLI checks supplied bytes without writing or claiming live provenance', () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'customer-v0-saved-file-'));
  try {
    const saved = structuredClone(result.flow);
    saved.createdAt = Date.UTC(2026, 8, 29);
    saved.updatedAt = saved.createdAt + 1000;
    const parsed = result.flujo.FlowSnapshotSchema.parse(saved);
    const savedPath = path.join(temporary, 'saved-flow.json');
    const bytes = Buffer.from(JSON.stringify(parsed) + '\n');
    fs.writeFileSync(savedPath, bytes);
    const args = ['build.cjs', '--flujo-root', root, '--saved-flow', savedPath, '--model-id', DEFAULT_BINDINGS.modelId];
    const check = JSON.parse(execFileSync(process.execPath, args, { cwd: __dirname, encoding: 'utf8' }));
    assert.match(check.scope, /not a live read-back/);
    assert.equal(check.graphHash, result.flujo.hashFlowExecutionSnapshot(parsed));
    assert(bytes.equals(fs.readFileSync(savedPath)));
    const modified = { ...parsed, _meta: { authority: 'unreviewed' } };
    fs.writeFileSync(savedPath, JSON.stringify(modified));
    assert.throws(() => execFileSync(process.execPath, args, { cwd: __dirname, stdio: 'pipe' }));
    assert.deepEqual(JSON.parse(fs.readFileSync(savedPath)), modified);
  } finally {
    assert(path.resolve(temporary).startsWith(path.resolve(os.tmpdir()) + path.sep + 'customer-v0-saved-file-'));
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});

test('legacy bank-server CLI input is refused and source CI selects restored FLUJO', () => {
  assert.throws(() => execFileSync(process.execPath, ['build.cjs', '--bank-server', 'Banking MCP'], { cwd: __dirname, stdio: 'pipe' }));
  const workflow = fs.readFileSync(path.resolve(__dirname, '../../.github/workflows/tests.yml'), 'utf8');
  const job = workflow.split('  customer-flow-source:')[1].split('\n  test:')[0];
  assert(job.includes('ref: ' + PIN));
  assert(!/3037c142|51ff39fc|FLUJO_EXECUTION_ADAPTER|FLUJO_BANKING_CONFIG|dispatch_observer/.test(job));
});
