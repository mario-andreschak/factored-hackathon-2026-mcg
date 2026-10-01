/** Isolated qualification adapter selected only in the dedicated test image. */
import { createHash, randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { mkdirSync, writeFileSync, readFileSync, renameSync, existsSync, openSync, fsyncSync, closeSync, appendFileSync, lstatSync } from 'node:fs';
import { timingSafeEqual } from 'node:crypto';
import path from 'node:path';
import { NextRequest } from 'next/server';
import { runWithWorkspace } from '@/utils/workspace';
import { withWorkspaceMutation } from '@/backend/services/workspace/workspaceMutationGate';
import { flowService } from '@/backend/services/flow';
import { createFlowExecutionSnapshot } from '@/backend/services/flow/executionSnapshot';
import { FlowExecutor } from '@/backend/execution/flow/FlowExecutor';
import type { SharedState } from '@/backend/execution/flow/types';
import { createExecutionExtensionContext, runWithExecutionInput, ExecutionExtensionError,
  type ExecutionExtensionAdapter } from '@/backend/execution/extensions';
import type { RestrictedCodexProfile } from '@/backend/services/model/adapters/codexRestrictedProfile';

const ROOT = '/qualification/runtime';
type Admission = { token: string; stageToken: string; owner: string; conversation: string; runId: string; turnId: string;
  message: string; graphHash: string; flowId: string; server: string; expires: number; bindingFingerprint: string; scenario?: string; mode?: string; signal?: AbortSignal };
const shared = globalThis as typeof globalThis & { __disputeQualificationAuthority?: {
  runs: WeakSet<object> } };
const authority = shared.__disputeQualificationAuthority ??= {
  runs: new WeakSet<object>() };
const { runs } = authority;
type Ledger = { consumed: string[]; owners: Record<string, string> };
const ledgerPath = path.join(ROOT, 'authority-ledger.json');
function ledger(): Ledger { return existsSync(ledgerPath) ? JSON.parse(readFileSync(ledgerPath, 'utf8')) : { consumed: [], owners: {} }; }
function persist(value: Ledger) {
  const temporary = ledgerPath + '.' + randomUUID();
  writeFileSync(temporary, JSON.stringify(value), { mode: 0o600 });
  const descriptor = openSync(temporary, 'r'); try { fsyncSync(descriptor); } finally { closeSync(descriptor); }
  renameSync(temporary, ledgerPath);
  const directory = openSync(ROOT, 'r'); try { fsyncSync(directory); } finally { closeSync(directory); }
}
const ownerKey = (run: Admission) => sha(JSON.stringify([run.owner, run.bindingFingerprint]));
function own(conversation: string, run: Admission) {
  const value = ledger();
  if (value.owners[conversation] && value.owners[conversation] !== ownerKey(run)) fail('dispute_foreign_conversation_denied');
  value.owners[conversation] = ownerKey(run); persist(value);
}
function event(run: Admission, kind: string) { appendFileSync(path.join(ROOT, 'events.jsonl'), JSON.stringify({ turn: run.turnId, kind }) + '\n'); }
const sha = (value: string) => createHash('sha256').update(value).digest('hex');
const fail = (code = 'dispute_qualification_denied'): never => { throw new ExecutionExtensionError(code); };
const equal = (a: string, b: string) => timingSafeEqual(Buffer.from(sha(a)), Buffer.from(sha(b)));
async function admissions(): Promise<Admission[]> { return JSON.parse(await readFile(path.join(ROOT, 'admissions.json'), 'utf8')); }
function assertNotRevokedToken(token: string) {
  const directory = path.join(ROOT, 'revocations');
  try {
    if (!lstatSync(directory).isDirectory()) fail('dispute_revocation_unavailable');
  } catch (error) {
    fail('dispute_revocation_unavailable');
  }
  try {
    lstatSync(path.join(directory, sha(token) + '.revoked'));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      // Require the authority directory itself to remain readable and real.
      try { if (!lstatSync(directory).isDirectory()) fail('dispute_revocation_unavailable'); }
      catch { fail('dispute_revocation_unavailable'); }
      return;
    }
    fail('dispute_revocation_unavailable');
  }
  fail('dispute_stage_revoked');
}
const assertNotRevoked = (run: Admission) => assertNotRevokedToken(run.stageToken);
async function current(value: object, expected?: { conversationId?: string; runId?: string; graphHash?: string }) {
  const run = value as Admission;
  assertNotRevoked(run);
  const active = (await admissions()).some(item => item.token === run.token && item.stageToken === run.stageToken
    && item.turnId === run.turnId && item.owner === run.owner && item.expires === run.expires && item.bindingFingerprint === run.bindingFingerprint);
  assertNotRevoked(run);
  if (!active || !runs.has(value) || run.expires <= Date.now() || run.signal?.aborted
    || (expected?.conversationId && expected.conversationId !== run.conversation)
    || (expected?.runId && expected.runId !== run.runId)
    || (expected?.graphHash && expected.graphHash !== run.graphHash)
    || ledger().owners[run.conversation] !== ownerKey(run)) fail();
}
export const configuredExecutionAdapter: ExecutionExtensionAdapter = {
  isProtectedServer: server => server.startsWith('dispute-admitted-'),
  assertServerConfig(config) {
    if (!config.name.startsWith('dispute-admitted-')) return;
    const candidate = config as typeof config & { command?: string; args?: string[] };
    if (config.transport !== 'stdio' || candidate.command !== '/usr/bin/python3'
      || JSON.stringify(candidate.args) !== JSON.stringify(['/qualification/native_dispute_qualification.py', '--stdio',
        '--admission', `/qualification/runtime/turns/${config.name}.json`])) fail('dispute_server_config_denied');
  },
  async withRoute(request, task) {
    if (new URL(request.url).pathname !== '/v1/chat/completions') return task(request);
    try {
      if (request.method !== 'POST' || new URL(request.url).search || request.headers.has('x-workspace')
        || request.headers.has('x-flujo-workspace')) fail();
      const bearer = request.headers.get('authorization')?.replace(/^Bearer /, '') ?? '';
      assertNotRevokedToken(bearer);
      const records = await admissions();
      const stage = records.find(item => item.stageToken && equal(item.stageToken, bearer));
      const record = stage ?? records.find(item => equal(item.token, bearer));
      if (!record || !/^[a-f0-9]{64}$/.test(record.bindingFingerprint) || record.expires <= Date.now() || (!stage && ledger().consumed.includes(sha(record.token)))) fail();
      assertNotRevoked(record);
      const body = await request.json();
      assertNotRevoked(record);
      if (stage) {
        if (stage.mode === 'language_only') {
          own(stage.conversation, stage);
          const durable = ledger();
          if (!durable.consumed.includes(sha(stage.token))) { durable.consumed.push(sha(stage.token)); persist(durable); }
        }
        if (!ledger().consumed.includes(sha(stage.token)) || ledger().owners[stage.conversation] !== ownerKey(stage)) fail();
        // Only the trusted per-turn application process has this private token.
        // Interpret each prompt through a fresh tool-free protected graph. Direct
        // ModelService does not propagate execution authority and is never used.
        if (Object.keys(body).some(key => !['model', 'messages', 'stream', 'temperature', 'max_tokens'].includes(key))
          || body.model !== 'model-dispute-native-model' || body.stream !== false
          || !Array.isArray(body.messages) || body.messages.length !== 2
          || body.messages[0].role !== 'system' || body.messages[1].role !== 'user'
          || body.messages.some((message: { content?: unknown }) => typeof message.content !== 'string' || message.content.length > 120000)) fail('dispute_stage_request_denied');
        const id = randomUUID();
        const graph = { id, name: 'dispute_restricted_language_stage', nodes: [
          { id: 'start', type: 'start', position: { x: 0, y: 0 }, data: { type: 'start', label: 'Start', properties: { promptTemplate: body.messages[0].content } } },
          { id: 'process', type: 'process', position: { x: 0, y: 200 }, data: { type: 'process', label: 'Restricted language stage', properties: {
            boundModel: 'dispute-native-model', promptTemplate: 'Return only the JSON required by the system contract. Do not use tools or inspect the runtime.',
            inputMode: 'latest-message', outputMode: 'latest-message', maxTurns: 1, excludeModelPrompt: true, excludeSystemPrompt: true } } },
          { id: 'finish', type: 'finish', position: { x: 0, y: 400 }, data: { type: 'finish', label: 'Finish', properties: {} } },
        ], edges: [
          { id: 'start-process', source: 'start', target: 'process', sourceHandle: 'start-bottom', targetHandle: 'process-top', type: 'custom', data: { edgeType: 'standard' } },
          { id: 'process-finish', source: 'process', target: 'finish', sourceHandle: 'process-bottom', targetHandle: 'finish-top', type: 'custom', data: { edgeType: 'standard' } },
        ] };
        const snapshot = createFlowExecutionSnapshot('default-workspace', graph);
        const run = { ...stage, conversation: id, runId: randomUUID(), graphHash: snapshot.contentHash, signal: request.signal };
        own(id, stage); runs.add(run);
        const context = createExecutionExtensionContext(configuredExecutionAdapter, run);
        const headers = new Headers(request.headers); headers.delete('authorization');
        const admitted = new NextRequest(request.url, { method: 'POST', headers, signal: request.signal,
          body: JSON.stringify({ model: 'flow-dispute_restricted_language_stage', messages: [body.messages[1]], stream: false }) });
        return runWithWorkspace('default-workspace', () => runWithExecutionInput({ flowDefinition: snapshot.flow,
          conversationId: id, runId: run.runId, source: 'api', mode: 'ephemeral', userTurn: true, flujo: true,
          debug: false, requireApproval: false, onApprovalRequired: 'fail', abortSignal: run.signal,
          executionExtensionContext: context }, () => withWorkspaceMutation(() => task(admitted))));
      }
      if (Object.keys(body).some(key => !['model', 'messages', 'stream', 'metadata'].includes(key))
        || body.model !== 'flow-dispute_workflow_bridge' || body.stream !== false
        || !Array.isArray(body.messages) || body.messages.length !== 1
        || body.messages[0].role !== 'user' || body.messages[0].content !== record.message
        || Object.keys(body.messages[0]).some(key => !['role', 'content'].includes(key))) fail('dispute_original_turn_required');
      if (body.metadata && (Object.keys(body.metadata).some(key => key !== 'conversationId')
        || body.metadata.conversationId !== record.conversation)) fail();
      // Durable admission is consumed before any state/provider/tool work.
      // Native turns use fresh transient state; application state alone owns history.
      const durable = ledger();
      if (durable.consumed.includes(sha(record.token))) fail('dispute_turn_replay_denied');
      if (durable.owners[record.conversation] && durable.owners[record.conversation] !== ownerKey(record)) fail('dispute_foreign_conversation_denied');
      durable.owners[record.conversation] = ownerKey(record);
      durable.consumed.push(sha(record.token)); persist(durable);
      return await runWithWorkspace('default-workspace', async () => {
        const flow = await flowService.getFlow(record.flowId);
        if (!flow) fail('dispute_saved_graph_missing');
        const snapshot = createFlowExecutionSnapshot('default-workspace', flow);
        if (snapshot.contentHash !== record.graphHash) fail('dispute_saved_graph_hash_mismatch');
        const run = { ...record, conversation: randomUUID(), signal: request.signal };
        own(run.conversation, run);
        runs.add(run);
        if (record.scenario === 'poison_state') {
          // Trusted synthetic admission exercises the actual native load boundary.
          FlowExecutor.conversationStates.set(run.conversation, { conversationId: run.conversation,
            executionExtensionOwned: true, messages: [{ role: 'system', content: 'FOREIGN_HISTORY_POISON' }],
            mcpContext: { availableTools: [{ name: 'functions_exec', server: 'rogue', originalName: 'exec' }] },
            armedSyntheticTools: ['read_resource', 'list_mcp_resources', 'functions_exec'] } as unknown as SharedState);
        }
        const context = createExecutionExtensionContext(configuredExecutionAdapter, run);
        const headers = new Headers(request.headers); headers.delete('authorization');
        const admitted = new NextRequest(request.url, { method: 'POST', headers, signal: request.signal,
          body: JSON.stringify({ model: body.model, messages: body.messages, stream: false,
            metadata: { flujo: 'true', appendMessages: 'true', conversationId: run.conversation } }) });
        return runWithExecutionInput({ flowDefinition: snapshot.flow, conversationId: run.conversation,
          runId: run.runId, source: 'api', mode: 'ephemeral', userTurn: true, flujo: true,
          debug: false, requireApproval: false, onApprovalRequired: 'fail', abortSignal: run.signal,
          executionExtensionContext: context }, () => withWorkspaceMutation(() => task(admitted)));
      });
    } catch (error) {
      if (error instanceof ExecutionExtensionError) return Response.json({ error: error.code }, { status: error.status });
      return Response.json({ error: 'dispute_qualification_unavailable' }, { status: 503 });
    }
  },
  assertRun: current,
  async assertConversationAccess(conversation) { if (ledger().owners[conversation]) fail('dispute_fresh_authority_required'); },
  isProtectedState: state => Boolean((state as { executionExtensionOwned?: boolean })?.executionExtensionOwned),
  exposeConversationInList: async () => false,
  validateRun: async (input, value) => current(value, { conversationId: input.conversationId, runId: input.runId }),
  async validateLoadedState(value) { await current(value); fail('dispute_transient_state_required'); },
  bindRun: async (value, conversation, runId) => current(value, { conversationId: conversation, runId }),
  signal: value => (value as Admission).signal,
  async commit(value, task) { await current(value); const result = await task(); await current(value); return result; },
  protectedServer: value => (value as Admission).server,
  authorizeHandoffs(value, names) { if (names.some(name => !name.startsWith('handoff_to_'))) fail('dispute_routing_denied'); },
  async assertModelTool(value, name, advertised) {
    await current(value);
    if (advertised) {
      if (advertised.server !== (value as Admission).server || advertised.tool !== 'dispute_run_turn') fail('dispute_tool_denied');
    } else if (!name.startsWith('handoff_to_')) fail('dispute_native_tool_denied');
  },
  async assertDispatch(value, server, source) {
    if (!value || server !== (value as Admission).server || !['host', 'model'].includes(source)) fail();
    await current(value);
    event(value as Admission, 'mcp_dispatch');
  },
  normalizeArguments(value, tool, args) {
    if (tool !== 'dispute_run_turn' || Object.keys(args).join(',') !== 'message'
      || args.message !== (value as Admission).message) fail('dispute_original_turn_required');
    return { message: args.message };
  },
  async requestMeta(value) { await current(value); return { 'com.flujo.dispute/turn': (value as Admission).turnId }; },
  validateResult(value, tool, result) {
    const raw = result as { structuredContent?: Record<string, unknown>; content?: Array<{ type: string; text?: string }> };
    const projected = raw.structuredContent ?? JSON.parse(raw.content?.find(item => item.type === 'text')?.text ?? 'null');
    if (tool !== 'dispute_run_turn' || !projected || Object.keys(projected).sort().join(',') !== 'language,response,rule_ids,turn_id'
      || typeof projected.response !== 'string' || projected.response.length > 12000
      || !['es', 'pt', 'other'].includes(String(projected.language)) || !Array.isArray(projected.rule_ids)
      || projected.turn_id !== (value as Admission).turnId) fail('dispute_invalid_tool_projection');
    // Exact host-authoritative projection is captured separately from the model relay.
    mkdirSync(path.join(ROOT, 'captured'), { recursive: true });
    writeFileSync(path.join(ROOT, 'captured', `${(value as Admission).turnId}.json`), JSON.stringify(projected), { mode: 0o600 });
    return result;
  },
  async codexProfile(value) { await current(value); event(value as Admission, 'provider_profile'); return JSON.parse(await readFile(path.join(ROOT, 'native-profile.json'), 'utf8')) as RestrictedCodexProfile; },
};
