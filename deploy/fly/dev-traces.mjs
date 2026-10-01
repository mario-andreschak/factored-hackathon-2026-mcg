import fs from 'node:fs/promises';
import { constants } from 'node:fs';
import path from 'node:path';
import { gunzipSync } from 'node:zlib';

// The temporary authenticated leaf uses the existing default workspace. HTTP
// inputs never select a filesystem root, ledger, policy, or credentials file.
const DEFAULT_DB = '/data/native-flujo/workspaces/default-workspace/db';
const ID = /^[A-Za-z0-9_-]{1,64}$/;
const MAX_BYTES = 64 * 1024 * 1024;
const PRIVATE_FIELD = /authorization|cookie|password|secret|credential|assertion|signer|private.?key|api.?key|access.?token|refresh.?token|control.?token|bearer|snapshot.?key|executionAuthority|executionExtensionContext|bankingRunContext|privateLedger|configFile|policyFile/i;
const PRIVATE_PATH = /\/(?:data\/(?:private|banking-state|native-authority)|run\/(?:banking(?:-runtime)?|frontend|secrets|dispute|native-login)|bootstrap\/worker\.snapshot)(?:[^\s"'<>]*)/g;

function redact(value, secrets, depth = 0) {
  if (depth > 60) return '[omitted]';
  if (typeof value === 'string') {
    if (/-----BEGIN [A-Z ]*PRIVATE KEY-----/.test(value)) return '[redacted]';
    let text = value.replace(PRIVATE_PATH, '[private runtime path]')
      .replace(/\bBearer\s+[^\s"'<>]+/gi, 'Bearer [redacted]')
      .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, '[redacted assertion]');
    for (const secret of secrets) text = text.replaceAll(secret, '[redacted]');
    return text;
  }
  if (Array.isArray(value)) return value.map(item => redact(item, secrets, depth + 1));
  if (value && typeof value === 'object') {
    const result = Object.create(null);
    for (const [key, item] of Object.entries(value)) {
      if (!PRIVATE_FIELD.test(key) && !['__proto__', 'constructor', 'prototype'].includes(key)) result[key] = redact(item, secrets, depth + 1);
    }
    return result;
  }
  return value;
}

// Use the same durable Chat fold as FLUJO: message upserts retain position,
// subflow depth is kept, and model-context removals never erase history.
export function projectTraceMessages(events, snapshot = []) {
  const messages = [], positions = new Map(), legacy = new Map();
  for (const event of events) {
    if (event?.type === 'message' && event.message?.id && event.message.role !== 'system') {
      let id = event.message.id;
      if (positions.has(id) && /^stream_codex_item_/.test(id)) {
        const occurrence = (legacy.get(id) ?? 1) + 1; legacy.set(id, occurrence); id = `${id}_legacy_${occurrence}`;
      } else if (!legacy.has(id)) legacy.set(id, 1);
      const message = { ...event.message, id, ...(event.depth > 0 ? { depth: event.depth } : {}) };
      if (positions.has(id)) messages[positions.get(id)] = message;
      else { positions.set(id, messages.length); messages.push(message); }
    } else if (event?.type === 'node:changed-files' && event.node?.nodeId && Array.isArray(event.changedFiles)) {
      for (let i = messages.length - 1; i >= 0; i--) if (messages[i].processNodeId === event.node.nodeId) {
        messages[i].changedFiles = event.changedFiles.map(({ path: filename, status }) => ({ path: filename, status })); break;
      }
    }
  }
  for (const [i, message] of snapshot.entries()) if (message?.role !== 'system' && !positions.has(message.id)) {
    const id = message.id || `snapshot_message_${i}`;
    positions.set(id, messages.length); messages.push({ ...message, id });
  }
  return { messages, source: events.some(event => event?.type === 'message' && event.message?.role !== 'system') ? 'durable-log' : 'snapshot' };
}

function failure(status) { const error = new Error('Stored trace unavailable.'); error.status = status; return error; }
async function safeDirectory(directory) {
  const resolved = path.resolve(directory);
  const parsed = path.parse(resolved);
  let current = parsed.root;
  for (const part of resolved.slice(parsed.root.length).split(path.sep).filter(Boolean)) {
    current = path.join(current, part);
    const metadata = await fs.lstat(current);
    if (!metadata.isDirectory() || metadata.isSymbolicLink()) throw failure(403);
  }
  if (await fs.realpath(resolved) !== resolved) throw failure(403);
}
async function safeRead(directory, filename, optional = false, encoding = 'utf8') {
  let handle;
  try {
    await safeDirectory(directory);
    const target = path.join(directory, filename);
    const before = await fs.lstat(target);
    if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1 || before.size > MAX_BYTES) throw failure(403);
    handle = await fs.open(target, constants.O_RDONLY | (constants.O_NOFOLLOW || 0));
    const opened = await handle.stat();
    if (opened.ino !== before.ino || opened.dev !== before.dev || !opened.isFile() || opened.nlink !== 1
      || opened.size > MAX_BYTES || await fs.realpath(target) !== target) throw failure(403);
    const bytes = await handle.readFile(encoding);
    if (Buffer.byteLength(bytes) > MAX_BYTES) throw failure(413);
    return bytes;
  } catch (error) {
    if (error.code === 'ENOENT' && optional) return undefined;
    if (error.code === 'ENOENT') throw failure(404);
    if (error.code === 'ELOOP') throw failure(403);
    throw error;
  } finally { await handle?.close(); }
}

const activity = value => value.lastUserMessageAt ?? value.updatedAt ?? 0;
const compare = (a, b) => activity(b) - activity(a) || a.id.localeCompare(b.id);
function summary(id, state) {
  return { id, title: state.title || 'Untitled Conversation', flowId: state.flowId || null,
    status: state.status, createdAt: state.createdAt || 0, updatedAt: state.updatedAt || 0,
    lastUserMessageAt: state.lastUserMessageAt ?? null, source: state.source ?? null,
    plannedExecutionId: state.plannedExecutionId ?? null, parentConversationId: state.parentConversationId ?? null,
    rootConversationId: state.rootConversationId ?? null, sessionKey: state.subflowLane?.sessionKey,
    sessionIdentity: state.subflowLane?.sessionIdentity, recovery: state.recovery, lastError: state.lastError,
    ...(state.personaArchived ? { personaArchived: true } : {}) };
}
function page(items, url) {
  const rawLimit = url.searchParams.get('limit');
  const limit = rawLimit === null ? 50 : Number(rawLimit);
  if (!Number.isInteger(limit) || limit < 1 || limit > 200) throw failure(400);
  const rawCursor = url.searchParams.get('cursor');
  let after = items;
  if (rawCursor) {
    let cursor;
    try { if (rawCursor.length > 512) throw new Error(); cursor = JSON.parse(Buffer.from(rawCursor, 'base64url').toString('utf8')); }
    catch { throw failure(400); }
    if (cursor.v !== 1 || !Number.isFinite(cursor.activityAt) || !ID.test(cursor.id)) throw failure(400);
    after = items.filter(item => activity(item) < cursor.activityAt || (activity(item) === cursor.activityAt && item.id.localeCompare(cursor.id) > 0));
  }
  const rows = after.slice(0, limit), hasMore = after.length > rows.length, last = rows.at(-1);
  const pinnedIds = url.searchParams.getAll('pinnedId');
  if (pinnedIds.some(id => !ID.test(id))) throw failure(400);
  return { items: rows, total: items.length, hasMore,
    ...(hasMore ? { nextCursor: Buffer.from(JSON.stringify({ v: 1, activityAt: activity(last), id: last.id })).toString('base64url') } : {}),
    ...(pinnedIds.length ? { pinnedItems: items.filter(item => pinnedIds.includes(item.id) || pinnedIds.includes(item.rootConversationId)) } : {}) };
}

/** dataDir overrides are local test fixtures; the executable uses DEFAULT_DB. */
export function createDevTraces({ dataDir = DEFAULT_DB, redactValues = [] } = {}) {
  const root = path.resolve(dataDir), secrets = redactValues.filter(value => typeof value === 'string' && value.length > 0);
  const snapshots = path.join(root, 'conversations'), logs = path.join(root, 'conversation-logs');
  async function state(id) {
    const parsed = JSON.parse(await safeRead(snapshots, `${id}.json`));
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed) || (parsed.conversationId && parsed.conversationId !== id)) throw failure(503);
    return parsed;
  }
  async function events(id) {
    const raw = await safeRead(logs, `${id}.jsonl`, true);
    return (raw || '').split('\n').flatMap(line => { try { return line.trim() ? [JSON.parse(line)] : []; } catch { return []; } });
  }
  async function transcript(id, snapshot) {
    return projectTraceMessages(await events(id), Array.isArray(snapshot.messages) ? snapshot.messages : []);
  }
  return async function devTraceRequest(req, url) {
    if (req.method !== 'GET' || Object.hasOwn(req.headers, 'authorization')) return undefined;
    const workspace = url.searchParams.get('workspace');
    if (workspace && workspace !== 'default-workspace') return undefined;
    const list = url.pathname === '/v1/chat/conversations';
    const match = /^\/v1\/chat\/conversations\/([^/]+)(?:\/(debug\/state|model-turns)(?:\/([^/]+))?)?$/.exec(url.pathname);
    if (!list && !match) return undefined;
    if (match?.[2] === 'debug/state' && match[3]) return undefined;
    try {
      let body;
      if (list) {
        let files;
        try { await safeDirectory(snapshots); files = await fs.readdir(snapshots); }
        catch (error) { if (error.code === 'ENOENT') files = []; else throw error; }
        const records = [];
        for (const filename of files) if (filename.endsWith('.json') && ID.test(filename.slice(0, -5))) {
          const id = filename.slice(0, -5), snapshot = await state(id);
          records.push({ item: summary(id, snapshot), snapshot });
        }
        const search = (url.searchParams.get('search') || '').trim().toLocaleLowerCase();
        if (search.length > 2000) throw failure(400);
        let items = records.filter(({ item, snapshot }) => !search || (url.searchParams.get('dimension') === 'content'
          ? JSON.stringify(snapshot.messages || []).toLocaleLowerCase().includes(search)
          : `${item.title} ${item.flowId || ''}`.toLocaleLowerCase().includes(search))).map(record => record.item);
        const origin = url.searchParams.get('origin');
        if (origin && !['chat', 'schedule', 'subflow', 'meeting'].includes(origin)) throw failure(400);
        if (origin) items = items.filter(item => (item.parentConversationId ? 'subflow' : item.source === 'schedule' ? 'schedule' : item.source === 'meeting' ? 'meeting' : 'chat') === origin);
        const sessionKey = url.searchParams.get('sessionKey');
        if (sessionKey) items = items.filter(item => item.sessionKey === sessionKey);
        const ancestor = url.searchParams.get('descendantsOf');
        if (ancestor) {
          if (!ID.test(ancestor)) throw failure(400);
          const included = new Set([ancestor]); let changed = true;
          while (changed) { changed = false; for (const item of items) if (included.has(item.parentConversationId) && !included.has(item.id)) { included.add(item.id); changed = true; } }
          items = items.filter(item => item.id !== ancestor && included.has(item.id));
        }
        items.sort(compare);
        body = url.searchParams.get('presence') === '1' ? { count: items.length }
          : url.searchParams.get('paged') === '1' || url.searchParams.get('mode') === 'page' ? page(items, url) : items;
      } else {
        let id; try { id = decodeURIComponent(match[1]); } catch { throw failure(400); }
        if (!ID.test(id)) throw failure(400);
        const snapshot = await state(id);
        if (match[2] === 'model-turns') {
          if (match[3]) {
            let dispatch; try { dispatch = decodeURIComponent(match[3]); } catch { throw failure(400); }
            if (!ID.test(dispatch)) throw failure(400);
            const compressed = await safeRead(path.join(root, 'model-turns', id), `${dispatch}.json.gz`, false, null);
            const archived = JSON.parse(gunzipSync(compressed, { maxOutputLength: MAX_BYTES }).toString('utf8'));
            if (archived?.entry?.conversationId !== id || archived.entry.id !== dispatch) throw failure(404);
            body = archived;
          } else {
            const turns = [], positions = new Map();
            for (const event of await events(id)) {
              if (event?.type === 'model:dispatch' && event.turn?.id && ID.test(event.turn.id)) {
                positions.set(event.turn.id, turns.length);
                turns.push({ ...event.turn, timestamp: event.timestamp || event.turn.timestamp });
              } else if (event?.type === 'model:dispatch-result' && positions.has(event.dispatchId)) {
                turns[positions.get(event.dispatchId)].outcome = event.outcome;
              }
            }
            body = { conversationId: id, turns };
          }
          return { status: 200, body: redact(body, secrets) };
        }
        const recovered = await transcript(id, snapshot);
        if (match[2] === 'debug/state') body = { status: snapshot.status ?? 'completed', breakpoints: snapshot.breakpoints ?? [],
          debugState: { ...snapshot, messages: recovered.messages } };
        else {
          const rawLimit = url.searchParams.get('messageLimit'), limit = rawLimit === null ? undefined : Number(rawLimit);
          if (limit !== undefined && (!Number.isInteger(limit) || limit < 1 || limit > 500)) throw failure(400);
          const messages = limit === undefined ? recovered.messages : recovered.messages.slice(-limit);
          body = { ...summary(id, snapshot), messages, requireApproval: snapshot.requireApproval ?? false,
            currentNodeId: snapshot.currentNodeId, usage: snapshot.usage, mcpAppContexts: snapshot.mcpAppContexts,
            transcriptWindow: { truncated: recovered.messages.length > messages.length, loadedCount: messages.length,
              totalCount: recovered.messages.length, source: recovered.source },
            ...(recovered.source === 'durable-log' ? { messageProvenanceVersion: 1 } : {}) };
        }
      }
      return { status: 200, body: redact(body, secrets) };
    } catch (error) { return { status: error.status || 503, body: { error: 'Stored conversation trace unavailable.' } }; }
  };
}
