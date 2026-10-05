import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { once } from 'node:events';
import { gzipSync } from 'node:zlib';
import { createDevTraces, projectTraceMessages } from './dev-traces.mjs';
import { createDevGateway } from './dev-gateway.mjs';

const HOST = 'flujo-factored-dev-2026.fly.dev', ORIGIN = `https://${HOST}`;
const NOW = Date.parse('2026-09-30T12:00:00.000Z'), DEADLINE = Date.parse('2026-10-16T05:00:00.000Z');
const MARIO = 'synthetic-mario-password-at-least-24', GLORIA = 'synthetic-gloria-password-at-least-24', TOKEN = 'synthetic-worker-control-token';
const url = route => new URL(route, ORIGIN);
const req = (headers = {}, method = 'GET') => ({ method, headers });

async function files(t) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'flujo-dev-trace-test-'));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const db = path.join(directory, 'db');
  await fs.mkdir(path.join(db, 'conversations'), { recursive: true });
  await fs.mkdir(path.join(db, 'conversation-logs'));
  const save = (id, state) => fs.writeFile(path.join(db, 'conversations', `${id}.json`), JSON.stringify({ conversationId: id, ...state }));
  const log = (id, events) => fs.writeFile(path.join(db, 'conversation-logs', `${id}.jsonl`), events.map(value => JSON.stringify(value)).join('\n') + '\n{truncated');
  return { directory, db, save, log, traces: createDevTraces({ dataDir: db, redactValues: [MARIO, GLORIA, TOKEN] }) };
}

test('durable history retains pruned messages, upserts tools and recovers nested/legacy messages', () => {
  const { messages, source } = projectTraceMessages([
    { type: 'message', message: { id: 's', role: 'system', content: 'plumbing' } },
    { type: 'message', message: { id: 'a', role: 'user', content: 'original' } },
    { type: 'message:removed', messageId: 'a' },
    { type: 'message', depth: 1, message: { id: 'b', role: 'assistant', content: 'partial', processNodeId: 'node' } },
    { type: 'message', depth: 1, message: { id: 'b', role: 'assistant', content: 'finished', processNodeId: 'node' } },
    { type: 'node:changed-files', node: { nodeId: 'node' }, changedFiles: [{ path: 'demo.txt', status: 'modified', extra: 'omitted' }] },
    { type: 'message', message: { id: 'stream_codex_item_0', role: 'assistant', content: 'one' } },
    { type: 'message', message: { id: 'stream_codex_item_0', role: 'assistant', content: 'two' } },
  ], [{ id: 'c', role: 'tool', content: 'snapshot-only', tool_call_id: 'tool' }]);
  assert.equal(source, 'durable-log');
  assert.deepEqual(messages.map(value => value.content), ['original', 'finished', 'one', 'two', 'snapshot-only']);
  assert.equal(messages[1].depth, 1);
  assert.deepEqual(messages[1].changedFiles, [{ path: 'demo.txt', status: 'modified' }]);
  assert.equal(messages[3].id, 'stream_codex_item_0_legacy_2');
});

test('normal sidebar, presence and stable pagination include execution-owned traces', async t => {
  const { traces, save } = await files(t);
  await save('one', { title: 'Older bank trace', updatedAt: 10, executionExtensionOwned: true, messages: [] });
  await save('two', { title: 'Recent bank trace', updatedAt: 20, messages: [] });
  await save('three', { title: 'Nested trace', updatedAt: 15, parentConversationId: 'two', rootConversationId: 'two', messages: [] });
  const all = await traces(req(), url('/v1/chat/conversations'));
  assert.equal(all.status, 200); assert.deepEqual(all.body.map(value => value.id), ['two', 'three', 'one']);
  assert.equal((await traces(req(), url('/v1/chat/conversations?presence=1'))).body.count, 3);
  const first = await traces(req(), url('/v1/chat/conversations?paged=1&limit=1&pinnedId=one'));
  assert.equal(first.body.total, 3); assert.equal(first.body.hasMore, true); assert.equal(first.body.pinnedItems[0].id, 'one');
  const second = await traces(req(), url(`/v1/chat/conversations?mode=page&limit=1&cursor=${first.body.nextCursor}`));
  assert.equal(second.body.items[0].id, 'three');
  assert.equal((await traces(req(), url('/v1/chat/conversations?search=Older'))).body[0].id, 'one');
  assert.equal((await traces(req(), url('/v1/chat/conversations?descendantsOf=two'))).body[0].id, 'three');
  assert.equal((await traces(req(), url('/v1/chat/conversations?paged=1&limit=999'))).status, 400);
  assert.equal((await traces(req(), url('/v1/chat/conversations?paged=1&cursor=invalid'))).status, 400);
});

test('detail/debug preserve trace and tool fields, hydrate durable history, and redact private authority', async t => {
  const { traces, save, log } = await files(t);
  await save('bank', { title: 'Bank run', status: 'completed', flowId: 'flow', messages: [{ id: 'tail', role: 'assistant', content: 'newest' }],
    executionAuthority: { key: 'private' }, executionExtensionContext: { secret: 'private' },
    nodeStates: { step: { status: 'completed', output: { tool_calls: [{ id: 'tool', function: { name: 'transactions', arguments: '{}' } }],
      Authorization: 'leak', apiKey: 'leak', content: `ordinary ${TOKEN} Bearer hidden-token`, nested: { signer: '/data/private/key.pem' } } } },
    configFile: '/run/banking-runtime/policy.json', debugSteps: [{ nodeId: 'step', input: { messages: [{ role: 'user', content: 'question' }] } }] });
  await log('bank', [{ type: 'message', message: { id: 'old', role: 'user', content: 'history' } },
    { type: 'message:removed', messageId: 'old' }, { type: 'message', message: { id: 'tool', role: 'tool', content: 'transactions', tool_call_id: 'call' } }]);
  const detail = await traces(req(), url('/v1/chat/conversations/bank?messageLimit=2'));
  assert.equal(detail.status, 200); assert.equal(detail.body.messages[0].role, 'tool');
  assert.deepEqual(JSON.parse(JSON.stringify(detail.body.transcriptWindow)), { truncated: true, loadedCount: 2, totalCount: 3, source: 'durable-log' });
  const debug = await traces(req(), url('/v1/chat/conversations/bank/debug/state'));
  assert.equal(debug.status, 200); assert.equal(debug.body.debugState.messages.length, 3);
  assert.equal(debug.body.debugState.nodeStates.step.output.tool_calls[0].function.name, 'transactions');
  const body = JSON.stringify(debug.body);
  for (const privateValue of [TOKEN, 'hidden-token', 'executionAuthority', 'executionExtensionContext', 'Authorization', 'apiKey', '/run/banking-runtime', '/data/private']) assert.ok(!body.includes(privateValue));
  assert.equal(debug.body.debugState.debugSteps[0].nodeId, 'step');
});

test('scope never intercepts writes, explicit credentials, other workspaces, or nontrace routes', async t => {
  const { traces } = await files(t);
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE', 'HEAD']) assert.equal(await traces(req({}, method), url('/v1/chat/conversations')), undefined);
  for (const authorization of ['', 'Basic invalid', 'Bearer invalid', 'Bearer scoped']) assert.equal(await traces(req({ authorization }), url('/v1/chat/conversations')), undefined);
  for (const route of ['/api/flow', '/v1/chat/completions', '/v1/chat/conversations/bank/cancel', '/v1/chat/conversations?workspace=other']) assert.equal(await traces(req(), url(route)), undefined);
  assert.equal((await traces(req(), url('/v1/chat/conversations/bad%2Fid'))).status, 400);
  assert.equal((await traces(req(), url('/v1/chat/conversations/not-found'))).status, 404);
});

test('ordinary model-turn timeline and archived model input preserve full trace with bounded safe reads', async t => {
  const { traces, save, log, db } = await files(t);
  await save('bank', { messages: [], status: 'completed' });
  const turn = { id: 'dispatch', conversationId: 'bank', timestamp: 10, node: { nodeId: 'model' }, modelName: 'fixture', outcome: 'running' };
  await log('bank', [{ type: 'model:dispatch', timestamp: 20, turn }, { type: 'model:dispatch-result', dispatchId: 'dispatch', outcome: 'completed' }]);
  await fs.mkdir(path.join(db, 'model-turns', 'bank'), { recursive: true });
  await fs.writeFile(path.join(db, 'model-turns', 'bank', 'dispatch.json.gz'), gzipSync(JSON.stringify({ version: 1, entry: turn,
    canonicalMessages: [{ id: 'message', role: 'tool', content: 'stored result' }], genericWire: [{ role: 'user', content: 'prompt' }],
    sdkRequest: { model: 'fixture', apiKey: 'private', headers: { authorization: 'private' }, messages: [{ role: 'user', content: `trace ${TOKEN}` }] } })));
  const index = await traces(req(), url('/v1/chat/conversations/bank/model-turns'));
  assert.equal(index.status, 200); assert.equal(index.body.conversationId, 'bank'); assert.equal(index.body.turns[0].outcome, 'completed'); assert.equal(index.body.turns[0].timestamp, 20);
  const detail = await traces(req(), url('/v1/chat/conversations/bank/model-turns/dispatch'));
  assert.equal(detail.status, 200); assert.equal(detail.body.sdkRequest.model, 'fixture'); assert.equal(detail.body.canonicalMessages[0].content, 'stored result');
  for (const value of [TOKEN, 'apiKey', 'authorization']) assert.ok(!JSON.stringify(detail.body).includes(value));
  assert.equal((await traces(req(), url('/v1/chat/conversations/bank/model-turns/missing'))).status, 404);
  assert.equal((await traces(req(), url('/v1/chat/conversations/bank/model-turns/bad%2Fid'))).status, 400);
  assert.equal(await traces(req({ authorization: '' }), url('/v1/chat/conversations/bank/model-turns/dispatch')), undefined);
  assert.equal(await traces(req(), url('/v1/chat/conversations/bank/model-turns/dispatch/media/fixture')), undefined);
});

test('symlinked files, directories and hardlinked snapshots cannot escape the fixed store', async t => {
  const { traces, db, directory, save } = await files(t);
  await save('good', { messages: [] });
  const outside = path.join(directory, 'outside.json'); await fs.writeFile(outside, '{"messages":[]}');
  await fs.link(outside, path.join(db, 'conversations', 'hard.json'));
  assert.equal((await traces(req(), url('/v1/chat/conversations/hard'))).status, 403);
  await fs.unlink(path.join(db, 'conversations', 'hard.json'));
  try { await fs.symlink(outside, path.join(db, 'conversations', 'link.json')); }
  catch (error) { if (error.code === 'EPERM') { t.diagnostic('Windows symlink privilege unavailable; hardlink confinement verified.'); return; } throw error; }
  assert.equal((await traces(req(), url('/v1/chat/conversations/link'))).status, 403);
  await fs.unlink(path.join(db, 'conversations', 'link.json'));
  await fs.rename(path.join(db, 'conversations'), path.join(db, 'original-conversations'));
  await fs.symlink(path.join(db, 'original-conversations'), path.join(db, 'conversations'), 'junction');
  assert.equal((await traces(req(), url('/v1/chat/conversations/good'))).status, 403);
});

async function listen(server) { server.listen(0, '127.0.0.1'); await once(server, 'listening'); return server.address().port; }
function request(port, route, { method = 'GET', headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const outgoing = http.request({ hostname: '127.0.0.1', port, path: route, method, headers: { host: HOST, ...headers } }, incoming => {
      const chunks = []; incoming.on('data', chunk => chunks.push(chunk)); incoming.on('end', () => resolve({ status: incoming.statusCode, headers: incoming.headers, body: Buffer.concat(chunks).toString() }));
    }); outgoing.on('error', reject); outgoing.end(body);
  });
}

test('leaf authentication/origin/deadline precede all trace reads and explicit credentials stay on worker', async t => {
  const { traces, save } = await files(t); await save('bank', { messages: [], status: 'completed' });
  let reads = 0, now = NOW;
  const upstream = http.createServer((incoming, response) => { response.writeHead(401); response.end('worker preserved'); });
  const upstreamPort = await listen(upstream);
  const server = createDevGateway({ host: HOST, expiresAt: DEADLINE, users: { mario: MARIO, gloria: GLORIA }, workerToken: TOKEN },
    { upstreamPort, now: () => now, traceHandler: async (...args) => { if (args[0].method === 'GET' && !Object.hasOwn(args[0].headers, 'authorization')) reads++; return traces(...args); } });
  const port = await listen(server);
  t.after(async () => { for (const item of [server, upstream]) await new Promise(resolve => { item.close(resolve); item.closeAllConnections(); }); });
  assert.equal((await request(port, '/v1/chat/conversations')).status, 401); assert.equal(reads, 0);
  const login = await request(port, '/_dev/login', { method: 'POST', headers: { origin: ORIGIN, 'content-type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ username: 'mario', password: MARIO }).toString() });
  const cookie = login.headers['set-cookie'][0].split(';')[0];
  assert.equal((await request(port, '/v1/chat/conversations', { headers: { cookie, origin: 'https://flujo-factored-2026.fly.dev' } })).status, 403); assert.equal(reads, 0);
  assert.equal((await request(port, '/v1/chat/conversations', { headers: { cookie, host: 'evil.fly.dev' } })).status, 421); assert.equal(reads, 0);
  assert.equal((await request(port, '/v1/chat/conversations', { headers: { cookie } })).status, 200); assert.equal(reads, 1);
  for (const authorization of ['', 'Basic invalid', 'Bearer invalid']) assert.equal((await request(port, '/v1/chat/conversations', { headers: { cookie, authorization } })).status, 401);
  assert.equal(reads, 1);
  assert.equal((await request(port, '/v1/chat/conversations', { method: 'DELETE', headers: { cookie, origin: ORIGIN } })).status, 401); assert.equal(reads, 1);
  now = DEADLINE;
  assert.equal((await request(port, '/v1/chat/conversations', { headers: { cookie } })).status, 410); assert.equal(reads, 1);
});

test('a delayed trace read releases no private data after logout, deadline, or twelve-hour session expiry', async t => {
  for (const kind of ['logout', 'deadline', 'sessionExpiry']) await t.test(kind, async subtest => {
    let now = NOW, release, started;
    const ready = new Promise(resolve => { started = resolve; });
    const waiting = new Promise(resolve => { release = resolve; });
    const server = createDevGateway({ host: HOST, expiresAt: DEADLINE, users: { mario: MARIO, gloria: GLORIA }, workerToken: TOKEN },
      { now: () => now, traceHandler: async () => { started(); await waiting; return { status: 200, body: { messages: ['private-stored-history'] } }; } });
    const port = await listen(server);
    subtest.after(() => new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }));
    const login = await request(port, '/_dev/login', { method: 'POST', headers: { origin: ORIGIN, 'content-type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ username: 'mario', password: MARIO }).toString() });
    const cookie = login.headers['set-cookie'][0].split(';')[0];
    const pending = request(port, '/v1/chat/conversations', { headers: { cookie } }).catch(() => ({ closed: true, body: '' }));
    await ready;
    if (kind === 'logout') assert.equal((await request(port, '/_dev/logout', { method: 'POST', headers: { cookie, origin: ORIGIN } })).status, 303);
    else now = kind === 'deadline' ? DEADLINE : NOW + 12 * 60 * 60 * 1000 + 1;
    release();
    const outcome = await pending;
    assert.ok(outcome.closed || [401, 410].includes(outcome.status));
    assert.ok(!outcome.body.includes('private-stored-history'));
  });
});
