/** Production language-only derivation of native_dispute_qualification.ts on FLUJO 0ba622. */
import { createHash, randomUUID, timingSafeEqual } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { writeFileSync, readFileSync, renameSync, existsSync, openSync, fsyncSync,
  closeSync, appendFileSync, lstatSync } from 'node:fs';
import path from 'node:path';
import { NextRequest } from 'next/server';
import { runWithWorkspace } from '@/utils/workspace';
import { withWorkspaceMutation } from '@/backend/services/workspace/workspaceMutationGate';
import { createFlowExecutionSnapshot } from '@/backend/services/flow/executionSnapshot';
import { createExecutionExtensionContext, runWithExecutionInput, ExecutionExtensionError,
  type ExecutionExtensionAdapter } from '@/backend/execution/extensions';
import type { RestrictedCodexProfile } from '@/backend/services/model/adapters/codexRestrictedProfile';

const CONTROL = '/data/native-authority/control';
const WORKER = '/data/native-authority/worker';
const PROFILE = '/opt/native/native-profile.json';
const CATALOG = '/opt/native/model-catalog.json';
const WRAPPER = '/opt/native/codex-wrapper.mjs';
const CATALOG_SHA256 = '5a1ddcef609e52bd057b247d9487f2c8c4d9453d3d802745ba5325c2e10700e0';
type Admission = { token: string; stageToken: string; owner: string; conversation: string;
  runId: string; turnId: string; message: string; graphHash: string; flowId: string;
  server: string; expires: number; bindingFingerprint: string; mode: 'language_only'; signal?: AbortSignal };
type Ledger = { owners: Record<string, string> };
const shared = globalThis as typeof globalThis & { __flyDisputeAuthority?: { runs: WeakSet<object> } };
const { runs } = shared.__flyDisputeAuthority ??= { runs: new WeakSet<object>() };
const sha = (value: string) => createHash('sha256').update(value).digest('hex');
const fail = (code = 'dispute_native_denied'): never => { throw new ExecutionExtensionError(code); };
const equal = (a: string, b: string) => timingSafeEqual(Buffer.from(sha(a)), Buffer.from(sha(b)));
const ownerKey = (run: Admission) => sha(JSON.stringify([run.owner, run.bindingFingerprint]));
const ledgerPath = path.join(WORKER, 'authority-ledger.json');

function assertDirectory(location: string, uid: number, mode: number) {
  const stat = lstatSync(location);
  if (!stat.isDirectory() || stat.isSymbolicLink() || stat.uid !== uid
    || (stat.mode & 0o7777) !== mode || (uid === 10001 && stat.gid !== 10002)) fail('dispute_native_permissions');
}
function assertControlDirectory() { assertDirectory(CONTROL, 10001, 0o2750); }
function assertWorkerDirectory() { assertDirectory(WORKER, 1000, 0o700); }
async function admissions(): Promise<Admission[]> {
  assertControlDirectory();
  const location = path.join(CONTROL, 'admissions.json'), before = lstatSync(location);
  if (!before.isFile() || before.isSymbolicLink() || before.uid !== 10001 || before.gid !== 10002
    || (before.mode & 0o7777) !== 0o640 || before.size > 2 * 1024 * 1024) fail('dispute_native_permissions');
  const bytes = await readFile(location, 'utf8'), after = lstatSync(location);
  if (before.ino !== after.ino || before.size !== after.size || before.mtimeMs !== after.mtimeMs) fail('dispute_native_control_changed');
  const records = JSON.parse(bytes);
  if (!Array.isArray(records) || records.length > 1000) fail('dispute_native_control_invalid');
  return records;
}
function ledger(): Ledger {
  assertWorkerDirectory();
  const value = existsSync(ledgerPath) ? JSON.parse(readFileSync(ledgerPath, 'utf8')) : { owners: {} };
  if (!value.owners || typeof value.owners !== 'object' || Array.isArray(value.owners)) fail();
  return value;
}
function persist(value: Ledger) {
  assertWorkerDirectory();
  const temporary = ledgerPath + '.' + randomUUID();
  writeFileSync(temporary, JSON.stringify(value), { mode: 0o600, flag: 'wx' });
  const descriptor = openSync(temporary, 'r'); try { fsyncSync(descriptor); } finally { closeSync(descriptor); }
  renameSync(temporary, ledgerPath);
  const directory = openSync(WORKER, 'r'); try { fsyncSync(directory); } finally { closeSync(directory); }
}
function own(conversation: string, run: Admission) {
  const value = ledger();
  if (value.owners[conversation] && value.owners[conversation] !== ownerKey(run)) fail('dispute_foreign_conversation_denied');
  value.owners[conversation] = ownerKey(run); persist(value);
}
function event(run: Admission, kind: string) {
  assertWorkerDirectory();
  appendFileSync(path.join(WORKER, 'events.jsonl'), JSON.stringify({ turn: run.turnId, kind }) + '\n', { mode: 0o600 });
}
function assertNotRevokedToken(token: string) {
  assertControlDirectory();
  const directory = path.join(CONTROL, 'revocations');
  try { assertDirectory(directory, 10001, 0o2750); } catch { fail('dispute_revocation_unavailable'); }
  try { lstatSync(path.join(directory, sha(token) + '.revoked')); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      try { assertDirectory(directory, 10001, 0o2750); } catch { fail('dispute_revocation_unavailable'); }
      return;
    }
    fail('dispute_revocation_unavailable');
  }
  fail('dispute_stage_revoked');
}
const assertNotRevoked = (run: Admission) => assertNotRevokedToken(run.stageToken);
function validRecord(run: Admission) {
  return run && run.mode === 'language_only' && /^[a-f0-9]{48}$/.test(run.token)
    && /^[a-f0-9]{48}$/.test(run.stageToken) && /^[a-f0-9]{64}$/.test(run.bindingFingerprint)
    && Number.isFinite(run.expires) && run.expires > Date.now() && run.expires <= Date.now() + 610000
    && ['owner', 'conversation', 'runId', 'turnId'].every(key => {
      const value = run[key as keyof Admission]; return typeof value === 'string' && value.length > 0 && value.length <= 512;
    }) && run.server === 'dispute-language-only';
}
async function current(value: object, expected?: { conversationId?: string; runId?: string; graphHash?: string }) {
  const run = value as Admission;
  assertNotRevoked(run);
  const active = (await admissions()).some(item => validRecord(item) && item.token === run.token
    && item.stageToken === run.stageToken && item.turnId === run.turnId && item.owner === run.owner
    && item.expires === run.expires && item.bindingFingerprint === run.bindingFingerprint);
  assertNotRevoked(run);
  if (!active || !runs.has(value) || run.signal?.aborted
    || (expected?.conversationId && expected.conversationId !== run.conversation)
    || (expected?.runId && expected.runId !== run.runId)
    || (expected?.graphHash && expected.graphHash !== run.graphHash)
    || ledger().owners[run.conversation] !== ownerKey(run)) fail();
}
function immutableFile(location: string) {
  const stat = lstatSync(location);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.uid !== 0 || (stat.mode & 0o022) !== 0) fail('dispute_native_profile_mutable');
}

export const configuredExecutionAdapter: ExecutionExtensionAdapter = {
  isProtectedServer: server => server === 'dispute-language-only' || server.startsWith('dispute-admitted-'),
  assertServerConfig(config) {
    if (config.name === 'dispute-language-only' || config.name.startsWith('dispute-admitted-')) fail('dispute_native_tools_forbidden');
  },
  async withRoute(request, task) {
    if (new URL(request.url).pathname !== '/v1/chat/completions') return task(request);
    try {
      if (request.method !== 'POST' || new URL(request.url).search || request.headers.has('x-workspace')
        || request.headers.has('x-flujo-workspace')) fail();
      const bearer = request.headers.get('authorization')?.replace(/^Bearer /, '') ?? '';
      if (!/^[a-f0-9]{48}$/.test(bearer)) fail();
      assertNotRevokedToken(bearer);
      const stage = (await admissions()).find(item => validRecord(item) && equal(item.stageToken, bearer));
      if (!stage) fail();
      assertNotRevoked(stage);
      const text = await request.text();
      if (Buffer.byteLength(text, 'utf8') > 1024 * 1024) fail('dispute_stage_request_denied');
      const body = JSON.parse(text);
      assertNotRevoked(stage);
      if (!body || typeof body !== 'object' || Array.isArray(body)
        || Object.keys(body).some(key => !['model', 'messages', 'stream', 'temperature', 'max_tokens'].includes(key))
        || body.model !== 'model-dispute-native-model' || body.stream !== false
        || !Array.isArray(body.messages) || body.messages.length !== 2
        || body.messages[0]?.role !== 'system' || body.messages[1]?.role !== 'user'
        || body.messages.some((message: { content?: unknown }) => !message
          || Object.keys(message).some(key => !['role', 'content'].includes(key))
          || typeof message.content !== 'string' || message.content.length > 120000)) fail('dispute_stage_request_denied');
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
      own(id, run); runs.add(run);
      const context = createExecutionExtensionContext(configuredExecutionAdapter, run);
      const headers = new Headers(request.headers); headers.delete('authorization');
      const admitted = new NextRequest(request.url, { method: 'POST', headers, signal: request.signal,
        body: JSON.stringify({ model: 'flow-dispute_restricted_language_stage', messages: [body.messages[1]], stream: false }) });
      return await runWithWorkspace('default-workspace', () => runWithExecutionInput({ flowDefinition: snapshot.flow,
        conversationId: id, runId: run.runId, source: 'api', mode: 'ephemeral', userTurn: true, flujo: true,
        debug: false, requireApproval: false, onApprovalRequired: 'fail', abortSignal: run.signal,
        executionExtensionContext: context }, () => withWorkspaceMutation(() => task(admitted))));
    } catch (error) {
      if (error instanceof ExecutionExtensionError) return Response.json({ error: error.code }, { status: error.status });
      return Response.json({ error: 'dispute_native_unavailable' }, { status: 503 });
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
  protectedServer: () => 'dispute-language-only',
  authorizeHandoffs(_value, names) { if (names.length) fail('dispute_native_tools_forbidden'); },
  async assertModelTool() { fail('dispute_native_tools_forbidden'); },
  async assertDispatch() { fail('dispute_native_tools_forbidden'); },
  normalizeArguments() { return fail('dispute_native_tools_forbidden'); },
  async requestMeta() { return fail('dispute_native_tools_forbidden'); },
  validateResult() { return fail('dispute_native_tools_forbidden'); },
  async codexProfile(value) {
    await current(value);
    for (const location of [PROFILE, CATALOG, WRAPPER]) immutableFile(location);
    const directory = lstatSync('/opt/native');
    if (!directory.isDirectory() || directory.isSymbolicLink() || directory.uid !== 0
      || (directory.mode & 0o022) !== 0) fail('dispute_native_profile_mutable');
    const profile = JSON.parse(await readFile(PROFILE, 'utf8')) as RestrictedCodexProfile;
    if (profile.verifiedCliVersion !== '0.157.1' || profile.verifiedCliPath !== WRAPPER
      || !/^[a-f0-9]{64}$/.test(profile.verifiedCliSha256)
      || profile.verifiedModelCatalogPath !== CATALOG
      || profile.verifiedModelCatalogSha256 !== CATALOG_SHA256) fail('dispute_native_profile_invalid');
    await current(value); event(value as Admission, 'provider_profile'); return profile;
  },
};
