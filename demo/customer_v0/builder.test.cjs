'use strict';
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test, before } = require('node:test');
const { build, loadFlujo, assertCustomerBoundary, DEFAULT_BINDINGS } = require('./build.cjs');

const root = process.env.FLUJO_SOURCE_ROOT;
assert(root, 'Set FLUJO_SOURCE_ROOT to the checkout at the pinned commit; tests must not silently skip');
let result;
before(() => { result = build(root); });
const node = (flow, kind) => flow.nodes.find(item => item.data.type === kind);
const policy = flow => ({ flowId: flow.id, graphHash: result.flujo.hashFlowExecutionSnapshot(flow), bankServerName: DEFAULT_BINDINGS.bankServer });

test('actual compiler produces identical bytes on repeated runs and matches committed artifacts', () => {
  const repeated = build(root);
  for (const [filename, bytes] of Object.entries(result.files)) {
    assert(bytes.equals(repeated.files[filename]), filename);
    assert(bytes.equals(fs.readFileSync(path.join(__dirname, 'generated', filename))), filename);
  }
  assert.equal(result.manifest.exampleBindings, true);
  assert.match(result.manifest.bindingEvidence, /declared public inputs/);
  assert.equal(result.manifest.compileIssues.length, 0);
  assert.equal(result.manifest.validationIssues.length, 0);
});

test('source-loaded snapshot function reproduces the published execution hash', () => {
  const snapshot = result.flujo.createFlowExecutionSnapshot('source-only-workspace', result.flow);
  assert.equal(snapshot.contentHash, result.manifest.sha256.compiledExecutionSnapshot);
  assert.equal(snapshot.versionId, result.manifest.snapshotVersion);
  snapshot.flow.nodes[0].data.properties.promptTemplate = 'changed';
  assert.notEqual(result.flujo.hashFlowExecutionSnapshot(snapshot.flow), snapshot.contentHash);
  assert.equal(result.flow.nodes[0].data.properties.promptTemplate, result.inputs.prompt);
});

test('canonical customer prompt is the only source and its bytes are embedded unchanged', () => {
  const canonical = path.resolve(__dirname, '../../resources/prompts/customer_v0.md');
  assert.equal(result.inputs.provenance.canonicalPrompt, 'resources/prompts/customer_v0.md');
  assert.equal(fs.existsSync(path.join(__dirname, 'prompt.md')), false, 'duplicate customer prompt must not return');
  assert(fs.readFileSync(canonical).equals(result.inputs.promptBytes));
  assert.equal(node(result.flow, 'start').data.properties.promptTemplate, fs.readFileSync(canonical, 'utf8'));
});

test('save metadata, configured model and registered server change the execution hash', () => {
  const saved = structuredClone(result.flow);
  saved.createdAt = Date.UTC(2026, 8, 29);
  saved.updatedAt = saved.createdAt;
  const firstSavedHash = assertCustomerBoundary(result.flujo.FlowSnapshotSchema.parse(saved), result.inputs, result.flujo).hash;
  assert.notEqual(firstSavedHash, result.manifest.sha256.compiledExecutionSnapshot);
  saved.updatedAt += 1000;
  assert.notEqual(assertCustomerBoundary(result.flujo.FlowSnapshotSchema.parse(saved), result.inputs, result.flujo).hash, firstSavedHash);
  assert.throws(() => result.flujo.FlowSnapshotSchema.parse({ ...saved, createdAt: '2026-09-29T00:00:00.000Z' }));
  const rebound = build(root, { modelId: 'configured-model-123', bankServer: 'registered-bank-123' });
  assert.equal(rebound.manifest.exampleBindings, false);
  assert.notEqual(rebound.manifest.sha256.compiledExecutionSnapshot, result.manifest.sha256.compiledExecutionSnapshot);
});

test('customer boundary requires explicit empty capabilities; omission cannot enable defaults', async t => {
  for (const key of ['enabledResources', 'enabledPrompts', 'enabledSkills']) {
    await t.test(`${key} omitted`, () => {
      const flow = structuredClone(result.flow);
      delete node(flow, 'mcp').data.properties[key];
      assert.throws(() => assertCustomerBoundary(flow, result.inputs, result.flujo), /MCP properties/);
    });
    await t.test(`${key} nonempty`, () => {
      const flow = structuredClone(result.flow);
      node(flow, 'mcp').data.properties[key] = ['unreviewed'];
      assert.throws(() => assertCustomerBoundary(flow, result.inputs, result.flujo));
      // Re-hash after tampering: exercise the actual feature check, not just hash mismatch.
      assert.throws(() => result.flujo.assertBankingGraph(flow, policy(flow)), /banking_graph_feature_forbidden/);
    });
  }
});

test('five host action tools are rejected by both customer boundary and actual graph function', async t => {
  for (const tool of ['prepare_unrecognized_charge', 'confirm_simulated_intake', 'read_intake_receipt', 'create_verified_handoff', 'read_verified_handoff']) {
    await t.test(tool, () => {
      const flow = structuredClone(result.flow);
      node(flow, 'mcp').data.properties.enabledTools.push(tool);
      assert.throws(() => assertCustomerBoundary(flow, result.inputs, result.flujo), /three banking reads/);
      assert.throws(() => result.flujo.assertBankingGraph(flow, policy(flow)), /banking_graph_server_forbidden/);
    });
  }
});

test('unreviewed runtime references, authority presets, servers and subflows are rejected', async t => {
  const mutations = [
    ['mutable prompt', flow => { node(flow, 'start').data.properties.promptTemplate = 'changed'; }],
    ['shared reference', flow => { node(flow, 'process').data.properties.promptTemplate = '${resource:shared}'; }, /shared_data_reference_forbidden/],
    ['authority preset', flow => { node(flow, 'mcp').data.properties.toolPresets = { list_my_transactions: { _meta: { assertion: 'untrusted' } } }; }, /banking_graph_authority_field_forbidden/],
    ['foreign MCP server', flow => { node(flow, 'mcp').data.properties.boundServer = 'another-server'; }, /banking_graph_server_forbidden/],
    ['subflow', flow => { node(flow, 'process').data.properties.subflowId = 'unreviewed'; }, /banking_graph_feature_forbidden/],
    ['extra node', flow => { flow.nodes.push({ ...structuredClone(node(flow, 'process')), id: 'other' }); }],
    ['input override', flow => { flow.input = { prompt: 'unreviewed' }; }],
    ['edge condition', flow => { flow.edges[0].data.condition = { kind: 'always' }; }],
    ['conflicting node type', flow => { node(flow, 'process').type = 'static'; }],
  ];
  for (const [label, mutate, actualError] of mutations) {
    await t.test(label, () => {
      const flow = structuredClone(result.flow); mutate(flow);
      assert.throws(() => assertCustomerBoundary(flow, result.inputs, result.flujo));
      if (actualError) assert.throws(() => result.flujo.assertBankingGraph(flow, policy(flow)), actualError);
    });
  }
});

test('actual graph function rejects a stale approved hash', () => {
  const approved = policy(result.flow);
  const flow = structuredClone(result.flow);
  flow.updatedAt = Date.UTC(2026, 8, 29);
  assert.throws(() => result.flujo.assertBankingGraph(result.flujo.FlowSnapshotSchema.parse(flow), approved), /approved_banking_graph_required/);
});

test('wrong source revision is refused before any compiler execution', () => {
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

test('saved-flow CLI checks a supplied file without writing it or claiming a live read', () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'customer-v0-saved-file-'));
  try {
    const saved = structuredClone(result.flow);
    saved.createdAt = Date.UTC(2026, 8, 29);
    saved.updatedAt = saved.createdAt + 1000;
    const parsed = result.flujo.FlowSnapshotSchema.parse(saved);
    const savedPath = path.join(temporary, 'saved-flow.json');
    const bytes = Buffer.from(JSON.stringify(parsed) + '\n');
    fs.writeFileSync(savedPath, bytes);
    const output = execFileSync(process.execPath, ['build.cjs', '--flujo-root', root, '--saved-flow', savedPath,
      '--model-id', DEFAULT_BINDINGS.modelId, '--bank-server', DEFAULT_BINDINGS.bankServer], { cwd: __dirname, encoding: 'utf8' });
    const check = JSON.parse(output);
    assert.match(check.scope, /not a live read-back/);
    assert.equal(check.graphHash, result.flujo.hashFlowExecutionSnapshot(parsed));
    assert.equal(check.ingressModel, 'flow-' + parsed.name);
    assert.notEqual(check.graphHash, result.manifest.sha256.compiledExecutionSnapshot);
    assert(bytes.equals(fs.readFileSync(savedPath)));
  } finally {
    assert(path.resolve(temporary).startsWith(path.resolve(os.tmpdir()) + path.sep + 'customer-v0-saved-file-'));
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});
