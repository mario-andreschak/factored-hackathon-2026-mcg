import assert from 'node:assert/strict';
import path from 'node:path';
import Module, { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';

export const FLUJO_PIN = '0ba62296520a505e6d71eddf5aa650691f3dc311';

// Exact Git blobs, never the mutable FLUJO checkout. The installed checkout
// supplies TypeScript/lodash only. No install, provider, network or disk service.
const FLOW = 'src/backend/execution/flow/';
const EXTENSIONS = 'src/backend/execution/extensions/index.ts';
const PINNED_MODULES = new Set([
  FLOW + 'FlowConverter.ts', FLOW + 'pocketflow.ts', FLOW + 'types.ts',
  FLOW + 'nodes/StartNode.ts', FLOW + 'nodes/ProcessNode.ts', FLOW + 'nodes/FinishNode.ts',
  FLOW + 'systemPromptDrift.ts', FLOW + 'conversationMessages.ts',
  'src/shared/utils/handoffNaming.ts', 'src/utils/shared/edgeConditions.ts', EXTENSIONS,
]);

export function pinnedEngineFixture() {
  const root = process.env.FLUJO_SOURCE_ROOT;
  assert.ok(root, 'Set FLUJO_SOURCE_ROOT to a local FLUJO Git clone with pinned commit and installed TypeScript/lodash.');
  const requirePackage = createRequire(path.join(root, 'package.json'));
  const ts = requirePackage('typescript');
  const verifiedPin = execFileSync('git', ['-C', root, 'rev-parse', FLUJO_PIN + '^{commit}'],
    { encoding: 'utf8', windowsHide: true, maxBuffer: 1024 }).trim();
  assert.equal(verifiedPin, FLUJO_PIN);
  let providerCalls = 0, capabilityCalls = 0;
  const failCapability = label => () => {
    capabilityCalls++; throw new Error('Unexpected capability in provider-free fixture: ' + label);
  };
  const failProvider = () => { providerCalls++; throw new Error('Provider execution is forbidden in this engine regression.'); };
  const noProvider = new Proxy({}, { get: () => failProvider });
  const noCapability = label => new Proxy({}, { get: (_target, key) => failCapability(label + '.' + String(key)) });
  const emptyDefinitions = value => { assert.ok(value == null || (Array.isArray(value) && value.length === 0)); return []; };
  const noop = () => {};
  const logger = { debug: noop, info: noop, warn: noop, error: noop, verbose: noop };
  const substitutes = new Map([
    ['src/utils/logger', { createLogger: () => logger }],
    ['src/config/features', { FEATURES: { ENABLE_EXECUTION_TRACKER: false } }],
    ['src/backend/execution/extensions/configuredAdapter', { configuredExecutionAdapter: undefined }],
    ['src/backend/utils/PromptRenderer', { promptRenderer: {
      async renderPrompt(flowId, nodeId, options) {
        assert.equal(options.flowSnapshot.id, flowId);
        return options.flowSnapshot.nodes.find(node => node.id === nodeId).data.properties.promptTemplate;
      }, resolveChatMessageReferences: failCapability('chat references'),
    } }],
    [FLOW + 'handlers/ToolHandler', { ToolHandler: noCapability('ToolHandler') }],
    [FLOW + 'handlers/ModelHandler', { ModelHandler: noProvider }],
    [FLOW + 'handlers/ResourceHandler', { ResourceHandler: noCapability('ResourceHandler') }],
    [FLOW + 'handlers/runResourceTools', { buildRunResourceTools: emptyDefinitions,
      buildReadResourceTool: failCapability('read_resource'), READ_RESOURCE_TOOL_NAME: 'read_resource', WRITE_RESOURCE_TOOL_NAME: 'write_resource' }],
    [FLOW + 'handlers/runQuestionTool', { buildQuestionTool: failCapability('question'), QUESTION_TOOL_NAME: 'question' }],
    [FLOW + 'handlers/todoTool', { buildTodoTool: failCapability('todo'), formatTodoBlock: failCapability('todo block'), TODO_TOOL_NAME: 'todo' }],
    [FLOW + 'handlers/meetingTools', { appendMeetingParticipantProtocol: failCapability('meeting protocol'),
      buildMeetingTools: failCapability('meeting tools'), isMeetingToolName: failCapability('meeting name'), isSilentMeetingControlRequest: failCapability('meeting control') }],
    [FLOW + 'handlers/mcpResourceTools', { buildListMCPResourcesTool: failCapability('MCP resources'), LIST_MCP_RESOURCES_TOOL_NAME: 'list_mcp_resources' }],
    ['src/shared/types/runResources', { RUN_RESOURCE_SCHEME: 'flujo://run/' }],
    // Pure materialization is outside this targeted routing test. The actual
    // prep method still performs handoff generation/authorization before this.
    [FLOW + 'materializeModelInput', {
      prepareModelInputMaterialization: ({ canonicalMessages, systemMessage }) => {
        const threaded = [structuredClone(systemMessage), ...structuredClone(canonicalMessages).filter(message => message.role !== 'system')];
        return { threaded, folded: threaded };
      },
      finalizeModelInputMaterialization: ({ threaded, folded }) => ({ threaded, folded,
        scoped: folded, wireChanged: false, snapshot: { fixture: 'SYNTHETIC_MATERIALIZATION_ONLY' } }),
    }],
    [FLOW + 'buildHandoffDescription', { buildHandoffDescription: async () => 'Synthetic target description for routing regression only.' }],
    [FLOW + 'handlers/subflowToolInvocation', { buildSubflowTool: failCapability('subflow tool') }],
    [FLOW + 'handlers/behaviorToolInvocation', { buildBehaviorToolDefinitions: emptyDefinitions }],
    [FLOW + 'handlers/personaTools', { buildPersonaTools: failCapability('persona tools') }],
    [FLOW + 'handlers/subflowDetachedInvocation', { buildDetachedSubflowTool: failCapability('detached subflow'), SUBFLOW_DETACHED_TOOL_PREFIX: 'start_subflow_' }],
    [FLOW + 'subflowCommunication', { buildSubflowCommunicationTools: failCapability('subflow communication') }],
    ['src/backend/services/flow/index', { flowService: noCapability('mutable flow service') }],
    ['src/backend/services/model', { modelService: noProvider }],
    ['src/utils/shared/resolveRunVars', { resolveRunVars: failCapability('variables') }],
    ['src/backend/utils/resolveDynamicReferences', { resolvePromptDynamicReferences: failCapability('dynamic references') }],
    [FLOW + 'resolveRunResourceRefs', { resolveRunResourceRefs: failCapability('run resources') }],
    [FLOW + 'resolveKvNodeRefs', { resolveKvNodeRefs: failCapability('kv reads'), captureKvValue: failCapability('kv writes') }],
    ['src/backend/services/mcp/skillModelContext', { loadApprovedMcpSkillSelections: async (_conversation, selections) => {
      assert.equal(selections, undefined); return [];
    } }],
    [FLOW + 'executionAuthority', { assertFlowExecutionCurrent: failCapability('execution authority'),
      rethrowFlowExecutionAuthorityError: error => { throw error; } }],
  ]);
  const cache = new Map();
  function normalize(owner, name) {
    if (name.startsWith('@/')) return 'src/' + name.slice(2);
    if (name.startsWith('.')) return path.posix.normalize(path.posix.join(path.posix.dirname(owner), name));
    return name;
  }
  function load(file) {
    if (cache.has(file)) return cache.get(file).exports;
    assert.ok(PINNED_MODULES.has(file), 'Unreviewed pinned module: ' + file);
    const source = execFileSync('git', ['-C', root, 'show', FLUJO_PIN + ':' + file],
      { encoding: 'utf8', windowsHide: true, maxBuffer: 2 * 1024 * 1024 });
    const compiled = ts.transpileModule(source, { fileName: file,
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, esModuleInterop: true }, reportDiagnostics: true });
    assert.ok(!compiled.diagnostics?.some(diagnostic => diagnostic.category === ts.DiagnosticCategory.Error));
    const loaded = new Module(file); loaded.filename = file; cache.set(file, loaded);
    loaded.require = name => {
      if (name === 'node:async_hooks') return requirePackage(name);
      if (name === 'lodash/cloneDeep') return requirePackage(name);
      if (name === 'uuid') return { v4: randomUUID };
      const resolved = normalize(file, name);
      if (substitutes.has(resolved)) return substitutes.get(resolved);
      if (resolved === FLOW + 'nodes') {
        class UnsupportedNode { constructor() { failCapability('unsupported node')(); } }
        return { StartNode: load(FLOW + 'nodes/StartNode.ts').StartNode,
          ProcessNode: load(FLOW + 'nodes/ProcessNode.ts').ProcessNode,
          FinishNode: load(FLOW + 'nodes/FinishNode.ts').FinishNode,
          MCPNode: UnsupportedNode, SubflowNode: UnsupportedNode, ResourceNode: UnsupportedNode,
          SignalNode: UnsupportedNode, StaticNode: UnsupportedNode };
      }
      return load(resolved === 'src/backend/execution/extensions' ? EXTENSIONS : resolved + '.ts');
    };
    loaded._compile(compiled.outputText, file);
    return loaded.exports;
  }
  const extensions = load(EXTENSIONS);
  return { pin: verifiedPin, extensions,
    FlowConverter: load(FLOW + 'FlowConverter.ts').FlowConverter,
    StartNode: load(FLOW + 'nodes/StartNode.ts').StartNode,
    ProcessNode: load(FLOW + 'nodes/ProcessNode.ts').ProcessNode,
    FINAL_RESPONSE_ACTION: load(FLOW + 'types.ts').FINAL_RESPONSE_ACTION,
    providerCalls: () => providerCalls, unexpectedCapabilityCalls: () => capabilityCalls,
  };
}
