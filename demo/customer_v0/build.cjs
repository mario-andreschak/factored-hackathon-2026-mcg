#!/usr/bin/env node
'use strict';

// Source-only: no HTTP calls, private config, providers, MCP dispatch or installation.
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const vm = require('node:vm');
const ts = require('typescript');
const { v5: uuidv5 } = require('uuid');

const HERE = __dirname;
const PIN = '3037c1423f7d39ede4d4a9b50afae038e4dd7baa';
const READ_TOOLS = Object.freeze(['banking_status', 'list_my_transactions', 'get_my_transaction']);
const DEFAULT_BINDINGS = Object.freeze({ modelId: 'existing-model-id', bankServer: 'existing-banking-server' });
const PROCESS_PROMPT = 'Review one owned charge using the embedded Customer-v0-readonly/1.1.0 instructions. '
  + 'Use successful banking reads for facts. Return concise Spanish or Portuguese customer text. '
  + 'Leave consent, action execution and human-request status to the interface and host action results.';
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const jsonBytes = value => Buffer.from(JSON.stringify(value, null, 2) + '\n', 'utf8');
const git = (root, args) => execFileSync('git', ['-C', root, ...args], { maxBuffer: 16 * 1024 * 1024 });

function requireExactKeys(value, keys, label) {
  assert.deepEqual(Object.keys(value).sort(), [...keys].sort(), `${label}: unreviewed fields`);
}

function requireAllowedKeys(value, keys, label) {
  assert(Object.keys(value).every(key => keys.includes(key)), `${label}: unreviewed fields`);
}

/** Load pure FLUJO modules from exact Git blob bytes, never from modified working files. */
function loadFlujo(root) {
  root = path.resolve(root);
  assert.equal(git(root, ['rev-parse', 'HEAD']).toString().trim(), PIN, 'FLUJO checkout must be at the pinned commit');
  const tracked = new Set(git(root, ['ls-tree', '-r', '--name-only', PIN, '--', 'src']).toString().trim().split('\n'));
  const cache = new Map();
  const blobs = new Map();
  const fileHashes = new Map();
  const external = new Set(['uuid', 'zod']);
  function blob(relative) {
    if (!blobs.has(relative)) {
      const bytes = git(root, ['show', `${PIN}:${relative}`]);
      blobs.set(relative, bytes);
      fileHashes.set(relative, sha256(bytes));
    }
    return blobs.get(relative).toString('utf8');
  }
  function resolveSource(request, parent) {
    const base = request.startsWith('@/') ? 'src/' + request.slice(2)
      : path.posix.normalize(path.posix.join(path.posix.dirname(parent), request));
    const relative = [base, base + '.ts', base + '/index.ts'].find(candidate => tracked.has(candidate));
    assert(relative && relative.startsWith('src/') && relative.endsWith('.ts'), `Source import unavailable: ${request}`);
    return relative;
  }
  function load(relative) {
    if (cache.has(relative)) return cache.get(relative).exports;
    const filename = path.join(root, ...relative.split('/'));
    const mod = new Module(filename);
    cache.set(relative, mod);
    mod.filename = filename;
    mod.require = request => {
      if (request.startsWith('@/') || request.startsWith('.')) return load(resolveSource(request, relative));
      if (request === 'crypto' || request === 'node:crypto') return require('node:crypto');
      assert(external.has(request), `Non-source dependency forbidden: ${request}`);
      return require(request);
    };
    const output = ts.transpileModule(blob(relative), { fileName: filename, compilerOptions: {
      esModuleInterop: true, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
      moduleResolution: ts.ModuleResolutionKind.Node10,
    } });
    mod._compile(output.outputText, filename);
    return mod.exports;
  }
  const compiler = load('src/utils/shared/flowSpecCompiler.ts');
  const schemas = load('src/shared/types/enduringAgent/schemas.ts');
  const validator = load('src/utils/shared/flowValidation.ts');
  const snapshots = load('src/backend/services/flow/executionSnapshot.ts');
  const adapterPath = 'src/integrations/hackathon-banking/configuredAdapter.ts';
  assert(/if\s*\(\s*parsed\.model\s*!==\s*'flow-'\s*\+\s*flow\.name\s*\)/.test(blob(adapterPath)), 'Pinned ingress flow-name rule changed');

  // Execute the unchanged graph function in isolation: production authority imports
  // private workspace/policy/storage/process modules, which this builder must not load.
  const declaration = (relative, name, predicate) => {
    const source = ts.createSourceFile(relative, blob(relative), ts.ScriptTarget.Latest, true);
    const matches = source.statements.filter(node => predicate(node) && node.name?.text === name);
    assert.equal(matches.length, 1, `Expected one ${name} declaration`);
    return { text: matches[0].getText(source), node: matches[0], source };
  };
  const graph = declaration('src/integrations/hackathon-banking/graph.ts', 'assertBankingGraph', ts.isFunctionDeclaration);
  const error = declaration('src/integrations/hackathon-banking/errors.ts', 'BankingError', ts.isClassDeclaration);
  const authoritySource = ts.createSourceFile('authority.ts', blob('src/integrations/hackathon-banking/authority.ts'), ts.ScriptTarget.Latest, true);
  const declarations = authoritySource.statements.filter(ts.isVariableStatement).flatMap(node => node.declarationList.declarations);
  const toolSchemas = declarations.find(node => node.name.getText(authoritySource) === 'toolSchemas');
  const toolNames = declarations.find(node => node.name.getText(authoritySource) === 'bankingToolNames');
  assert(toolSchemas && ts.isObjectLiteralExpression(toolSchemas.initializer), 'Expected actual toolSchemas object');
  const names = toolSchemas.initializer.properties.map(property => {
    assert(ts.isPropertyAssignment(property) && ts.isIdentifier(property.name), 'Unreviewed banking tool declaration');
    return property.name.text;
  });
  assert.deepEqual(names, READ_TOOLS, 'Pinned banking read tool names changed');
  assert.equal(toolNames?.initializer?.getText(authoritySource).replace(/\s/g, ''), 'Object.freeze(Object.keys(toolSchemas))');
  const isolatedCode = ts.transpileModule(error.text + '\n' + graph.text, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  } }).outputText;
  const isolated = { exports: {}, hashFlowExecutionSnapshot: snapshots.hashFlowExecutionSnapshot, bankingToolNames: Object.freeze(names) };
  vm.runInNewContext(isolatedCode, isolated, { filename: 'pinned-isolated-banking-graph.cjs', timeout: 1000 });
  return { ...compiler, ...schemas, ...validator, ...snapshots,
    assertBankingGraph: isolated.exports.assertBankingGraph,
    sourceFiles: () => Object.fromEntries([...fileHashes.entries()].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)),
    graphCheck: { method: 'isolated execution of unchanged graph function; production authority imports omitted',
      functionSha256: sha256(graph.text), errorClassSha256: sha256(error.text),
      toolNamesDerivation: 'actual authority.ts toolSchemas keys; checked exported freeze/keys initializer' },
    lockBytes: git(root, ['show', `${PIN}:package-lock.json`]),
  };
}

function readInputs(bindings = DEFAULT_BINDINGS) {
  requireExactKeys(bindings, ['modelId', 'bankServer'], 'bindings');
  for (const value of Object.values(bindings)) assert(typeof value === 'string' && /^[^\u0000-\u001f\u007f]{1,128}$/.test(value)
    && value.trim() === value, 'Expected a nonempty public model ID/server name without control characters');
  const promptPath = path.resolve(HERE, '../../resources/prompts/customer_v0.md');
  const promptBytes = fs.readFileSync(promptPath);
  assert(!promptBytes.includes(13), 'Prompt must use LF line endings');
  const prompt = promptBytes.toString('utf8');
  const provenanceBytes = fs.readFileSync(path.join(HERE, 'provenance.json'));
  const provenance = JSON.parse(provenanceBytes);
  assert.equal(provenance.flujoCommit, PIN);
  assert.equal(provenance.fragment, 'customer-v0-readonly');
  assert.equal(provenance.version, '1.1.0');
  assert.equal(provenance.canonicalPrompt, 'resources/prompts/customer_v0.md');
  assert.equal(sha256(promptBytes), provenance.promptSha256, 'Immutable prompt digest mismatch');
  assert(prompt.startsWith('Customer-v0-readonly/1.1.0\n\n'), 'Prompt/version mismatch');
  const spec = { name: 'banking_customer_v0', description: 'Customer-v0-readonly/1.1.0: one owned charge, ES/PT, three banking reads.',
    nodes: [
      { key: 'start', type: 'start', prompt },
      { key: 'customer', type: 'process', label: 'Customer inquiry', model: bindings.modelId,
        prompt: PROCESS_PROMPT, excludeModelPrompt: true, inputMode: 'full-history', outputMode: 'latest-message', maxTurns: 8,
        servers: [{ name: bindings.bankServer, tools: [...READ_TOOLS] }] },
      { key: 'finish', type: 'finish' },
    ], edges: [{ from: 'start', to: 'customer' }, { from: 'customer', to: 'finish' }] };
  const catalog = { models: [{ id: bindings.modelId }], servers: [{ name: bindings.bankServer }], serverTools: { [bindings.bankServer]: [...READ_TOOLS] } };
  return { promptBytes, prompt, provenanceBytes, provenance, spec, catalog, bindings };
}

function assertCustomerBoundary(flow, inputs, flujo) {
  requireAllowedKeys(flow, ['id', 'name', 'description', 'nodes', 'edges', 'createdAt', 'updatedAt', 'folder', 'favorite'], 'Flow');
  assert.equal(new Set(flow.nodes.map(node => node.id)).size, 4, 'Four unique node IDs required');
  for (const node of flow.nodes) assert.equal(node.type, node.data.type, 'Conflicting node types');
  const kinds = flow.nodes.map(node => node.data.type).sort();
  assert.deepEqual(kinds, ['finish', 'mcp', 'process', 'start'], 'Exactly one Start/Process/MCP/Finish is required');
  assert.equal(flow.behaviorRules, undefined, 'No runtime behavior attachments');
  assert.equal(flow.permissionRules, undefined, 'No runtime permission attachments');
  const byType = Object.fromEntries(flow.nodes.map(node => [node.data.type, node]));
  const start = byType.start.data.properties;
  const process = byType.process.data.properties;
  const mcp = byType.mcp.data.properties;
  requireExactKeys(start, ['promptTemplate'], 'Start properties');
  assert.equal(start.promptTemplate, inputs.prompt, 'Embedded prompt differs from reviewed fragment');
  requireExactKeys(process, ['promptTemplate', 'boundModel', 'excludeModelPrompt', 'inputMode', 'maxTurns', 'outputMode'], 'Process properties');
  assert.equal(process.promptTemplate, PROCESS_PROMPT);
  assert.equal(process.boundModel, inputs.bindings.modelId);
  assert.equal(process.excludeModelPrompt, true);
  assert.equal(process.inputMode, 'full-history');
  assert.equal(process.outputMode, 'latest-message');
  assert.equal(process.maxTurns, 8);
  requireExactKeys(mcp, ['boundServer', 'enabledTools', 'enabledResources', 'enabledPrompts', 'enabledSkills'], 'MCP properties');
  assert.equal(mcp.boundServer, inputs.bindings.bankServer);
  assert.deepEqual(mcp.enabledTools, READ_TOOLS, 'Only the three banking reads may be exposed');
  for (const key of ['enabledResources', 'enabledPrompts', 'enabledSkills']) assert.deepEqual(mcp[key], []);
  requireExactKeys(byType.finish.data.properties, [], 'Finish properties');
  const signatures = flow.edges.map(edge => `${edge.source}:${edge.sourceHandle}->${edge.target}:${edge.targetHandle}`).sort();
  assert.deepEqual(signatures, [
    `${byType.start.id}:start-bottom->${byType.process.id}:process-top`,
    `${byType.process.id}:process-bottom->${byType.finish.id}:finish-top`,
    `${byType.process.id}:process-right-mcp->${byType.mcp.id}:mcp-left`,
  ].sort(), 'Unreviewed graph wiring');
  for (const edge of flow.edges) {
    requireExactKeys(edge.data, ['edgeType'], 'Edge data');
    const isMcp = edge.target === byType.mcp.id;
    assert.equal(edge.data.edgeType, isMcp ? 'mcp' : 'standard');
    assert.equal(edge.type, isMcp ? 'mcpEdge' : 'custom');
  }
  const validation = flujo.validateFlow(flow, inputs.catalog);
  assert.equal(validation.errorCount, 0, JSON.stringify(validation.issues));
  assert.equal(validation.warningCount, 0, JSON.stringify(validation.issues));
  const hash = flujo.hashFlowExecutionSnapshot(flow);
  flujo.assertBankingGraph(flow, { flowId: flow.id, graphHash: hash, bankServerName: inputs.bindings.bankServer });
  return { hash, validation };
}

function build(flujoRoot, bindings = DEFAULT_BINDINGS) {
  const flujo = loadFlujo(flujoRoot);
  const inputs = readInputs(bindings);
  const result = flujo.compileFlowSpec(inputs.spec, inputs.catalog, { maxDepth: 0, maxFlows: 1 });
  assert.equal(result.errorCount, 0, JSON.stringify(result.issues));
  assert.equal(result.warningCount, 0, JSON.stringify(result.issues));
  assert.equal(result.flows.length, 1);
  assert(result.flow);
  const flow = structuredClone(result.flow);
  const id = label => uuidv5(`customer-v0-readonly/1.1.0/${label}`, uuidv5.URL);
  flow.id = id('flow');
  const remap = new Map(flow.nodes.map(node => [node.id, id(node.data.type)]));
  for (const node of flow.nodes) {
    node.id = remap.get(node.id);
    if (node.data.type === 'mcp') Object.assign(node.data.properties, { enabledResources: [], enabledPrompts: [], enabledSkills: [] });
  }
  for (const edge of flow.edges) {
    edge.source = remap.get(edge.source); edge.target = remap.get(edge.target);
    edge.id = `${edge.source}:${edge.sourceHandle}->${edge.target}:${edge.targetHandle}`;
  }
  const parsed = flujo.FlowSnapshotSchema.parse(flow);
  const { hash, validation } = assertCustomerBoundary(parsed, inputs, flujo);
  const specBytes = jsonBytes(inputs.spec);
  const flowBytes = jsonBytes(parsed);
  const manifest = {
    schema: 'banking-customer-v0-source-artifact/v1', scope: 'source-only; not installed or evaluated with a model',
    fragment: inputs.provenance.fragment, fragmentVersion: inputs.provenance.version,
    canonicalPrompt: inputs.provenance.canonicalPrompt,
    flujoCommit: PIN, bindings, ingressModel: 'flow-' + parsed.name,
    bindingEvidence: 'declared public inputs; no configured-model or MCP readiness observation',
    exampleBindings: bindings.modelId === DEFAULT_BINDINGS.modelId || bindings.bankServer === DEFAULT_BINDINGS.bankServer,
    modelBankingTools: [...READ_TOOLS], internalRouting: 'FLUJO also exposes the internal Finish routing control tool',
    sha256: { prompt: sha256(inputs.promptBytes), provenance: sha256(inputs.provenanceBytes),
      builder: sha256(fs.readFileSync(__filename)), toolchainLock: sha256(fs.readFileSync(path.join(HERE, 'package-lock.json'))),
      flujoPackageLock: sha256(flujo.lockBytes), flowSpec: sha256(specBytes), compiledFlowBytes: sha256(flowBytes),
      compiledExecutionSnapshot: hash },
    snapshotVersion: `sha256:${hash}`, compileIssues: result.issues, validationIssues: validation.issues,
    schemaCheck: 'actual FLUJO FlowSnapshotSchema.parse', graphCheck: flujo.graphCheck,
    flujoSourceFiles: flujo.sourceFiles(), promptSources: inputs.provenance.sources,
    installation: 'Saving changes metadata and hash. Hash and approve the final saved authoritative Flow separately.',
  };
  return { files: { 'flow-spec.json': specBytes, 'compiled-flow.json': flowBytes, 'manifest.json': jsonBytes(manifest) },
    flow: parsed, manifest, inputs, flujo };
}

function auditProvenance(repoRoot) {
  const { provenance } = readInputs();
  for (const source of provenance.sources) {
    const bytes = git(repoRoot, ['show', `${source.commit}:${source.path}`]);
    assert.equal(sha256(bytes), source.sha256, `Provenance mismatch: ${source.commit}:${source.path}`);
  }
  return provenance.sources.length;
}

function main(args) {
  const options = {};
  const flags = new Set(['--check', '--audit-provenance']);
  const values = new Set(['--flujo-root', '--model-id', '--bank-server', '--out', '--saved-flow']);
  for (let i = 0; i < args.length; i++) {
    const key = args[i];
    assert(flags.has(key) || values.has(key), `Unknown option: ${key}`);
    assert(!(key in options), `Duplicate option: ${key}`);
    if (flags.has(key)) options[key] = true;
    else { assert(args[i + 1] && !args[i + 1].startsWith('--'), `Missing value: ${key}`); options[key] = args[++i]; }
  }
  if (options['--audit-provenance']) {
    assert.equal(args.length, 1, 'Use --audit-provenance separately');
    process.stdout.write(`Verified ${auditProvenance(path.resolve(HERE, '../..'))} source blobs.\n`);
    return;
  }
  assert(options['--flujo-root'], 'Required: --flujo-root <checkout at pinned FLUJO commit>');
  const bindings = { modelId: options['--model-id'] ?? DEFAULT_BINDINGS.modelId, bankServer: options['--bank-server'] ?? DEFAULT_BINDINGS.bankServer };
  if (options['--saved-flow']) {
    assert(options['--model-id'] && options['--bank-server'], 'Saved-flow checking requires actual public binding IDs');
    assert(!options['--out'] && !options['--check'], 'Saved-flow checking does not generate or write files');
    const flujo = loadFlujo(options['--flujo-root']);
    const raw = JSON.parse(fs.readFileSync(options['--saved-flow'], 'utf8'));
    const flow = flujo.FlowSnapshotSchema.parse(raw);
    const { hash } = assertCustomerBoundary(flow, readInputs(bindings), flujo);
    process.stdout.write(JSON.stringify({ scope: 'source-only validation of supplied saved Flow; not a live read-back',
      flowId: flow.id, graphHash: hash, versionId: `sha256:${hash}`, ingressModel: 'flow-' + flow.name }) + '\n');
    return;
  }
  if (options['--model-id'] || options['--bank-server']) {
    assert(options['--model-id'] && options['--bank-server'] && options['--out'], 'Set both actual binding IDs and a separate --out directory');
    assert.notEqual(path.resolve(options['--out']), path.join(HERE, 'generated'), 'Do not overwrite the committed example with installation bindings');
  }
  const result = build(options['--flujo-root'], bindings);
  const out = path.resolve(options['--out'] ?? path.join(HERE, 'generated'));
  if (!options['--check']) fs.mkdirSync(out, { recursive: true });
  for (const [filename, bytes] of Object.entries(result.files)) {
    const target = path.join(out, filename);
    if (options['--check']) assert(fs.readFileSync(target).equals(bytes), `${filename} differs; regenerate and review`);
    else fs.writeFileSync(target, bytes);
  }
  process.stdout.write(`${options['--check'] ? 'Checked' : 'Generated'} source artifact; execution hash ${result.manifest.sha256.compiledExecutionSnapshot}\n`);
}

module.exports = { build, loadFlujo, readInputs, assertCustomerBoundary, auditProvenance, DEFAULT_BINDINGS, READ_TOOLS, PIN, main };
if (require.main === module) {
  try { main(process.argv.slice(2)); } catch (error) { process.stderr.write(error.message + '\n'); process.exitCode = 1; }
}
