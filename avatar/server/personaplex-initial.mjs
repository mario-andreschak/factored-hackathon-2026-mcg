import { createHash, randomBytes } from 'node:crypto';
import { PublicError, readResponse } from './http.mjs';
import { classifyMood } from './mood.mjs';
import { transcribe, validateTranscription } from './openrouter.mjs';
import { MODEL_REVISION, PERSONAPLEX_PROTOCOL, readPersonaplexLease, SOURCE_REVISION } from './personaplex.mjs';

// Exact UTF-8 hashes of the three static production worker prompts. Browser
// text, role descriptions and task results never become a system prompt.
export const INITIAL_ROLE_HASHES = Object.freeze({
  moss: '43615c1e5e82d31ef5fea9ea480346a2e43faf35bd533c881def728eca884d8d',
  orbit: '5ed63480109b8598a26363504c6f3436c32c3845a3f3970d1b8d9eee2dba77b9',
  spark: '1e37888693a78e1e5646a68c48d5aa16944cc3fe3bbe10ae11a8820560e2790c',
});
export const INITIAL_RESERVATION_MS = 195_000;
export const INITIAL_CAPABILITY_MS = 207_000;
export const INITIAL_CLAIM_MS = 140_000; // 12s replay + 8s handshake/READY + 120s native use.
export const INITIAL_AUDIO_SECONDS = 12;
export const INITIAL_BODY_BYTES = 800_000;
const ASR_MS = 45_000, PRIME_MS = 15_000, PROMOTION_MS = 3000, READ_MS = 3000;
const VOICE = 'NATM1.pt';
const healthKeys = ['ready', 'protocol', 'avatar', 'sourceRevision', 'modelRevision', 'selection', 'phase', 'voice', 'promptHash', 'selectionId'];
const leaseKeys = [...healthKeys, 'version', 'epoch', 'baseUrl', 'connectToken', 'createdAt', 'expiresAt', 'updatedAt'];
const object = value => value && typeof value === 'object' && !Array.isArray(value);
const exact = (value, keys) => object(value) && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
const unavailable = () => new PublicError(503, 'initial_voice_unavailable', 'The initial native voice selection is unavailable. You can still type.');
const cancelled = () => new PublicError(409, 'initial_selection_cancelled', 'This voice selection ended. Its worker reservation cannot be reused.');
const failed = () => new PublicError(502, 'initial_selection_failed', 'The initial voice selection could not be confirmed. Its worker reservation cannot be reused.');
const timeout = () => new PublicError(504, 'initial_selection_timeout', 'The initial voice selection timed out. Its worker reservation cannot be reused.');

function validateHealth(value) {
  if (!exact(value, healthKeys) || value.protocol !== PERSONAPLEX_PROTOCOL || value.sourceRevision !== SOURCE_REVISION ||
      value.modelRevision !== MODEL_REVISION || value.selection !== 'initial' || value.voice !== VOICE ||
      typeof value.ready !== 'boolean' || !['warm', 'priming', 'primed', 'streaming', 'closed'].includes(value.phase)) throw unavailable();
  const unselected = value.avatar === null && value.selectionId === null && value.promptHash === null;
  const selected = Object.hasOwn(INITIAL_ROLE_HASHES, value.avatar) && typeof value.selectionId === 'string' &&
    /^[A-Za-z0-9_-]{1,128}$/.test(value.selectionId);
  if (value.phase === 'warm' && (!unselected || value.ready) ||
      value.phase === 'priming' && (!selected || value.promptHash !== null || value.ready) ||
      ['primed', 'streaming'].includes(value.phase) && (!selected || value.promptHash !== INITIAL_ROLE_HASHES[value.avatar]) ||
      value.phase === 'streaming' && !value.ready ||
      value.phase === 'closed' && (value.ready || (!unselected && (!selected ||
        value.promptHash !== null && value.promptHash !== INITIAL_ROLE_HASHES[value.avatar])))) throw unavailable();
  return value;
}

/** Private operator v2 only. The existing fixed-role v1 validator is untouched. */
export function validatePersonaplexInitialLease(value, now, allowLocalWorker = false) {
  if (!exact(value, leaseKeys) || value.version !== 2) throw unavailable();
  validateHealth(Object.fromEntries(healthKeys.map(key => [key, value[key]])));
  const created = Date.parse(value.createdAt), expires = Date.parse(value.expiresAt), updated = Date.parse(value.updatedAt);
  let url;
  try { url = new URL(value.baseUrl); } catch { throw unavailable(); }
  const local = allowLocalWorker && ['127.0.0.1', 'localhost'].includes(url.hostname) && url.protocol === 'http:';
  const remote = url.protocol === 'https:' && /^(?:[a-z0-9-]+\.)*(?:modal\.run|modal\.host)$/.test(url.hostname) && !url.port;
  if (typeof value.epoch !== 'string' || !/^[A-Za-z0-9_-]{32,128}$/.test(value.epoch) ||
      typeof value.connectToken !== 'string' || !/^[\x21-\x7e]{16,8192}$/.test(value.connectToken) ||
      ![created, expires, updated].every(Number.isFinite) || created > now || expires <= now || expires - created > 600_000 ||
      updated < created || updated > now + 1000 || now - updated > 6000 || (!remote && !local) ||
      url.username || url.password || url.search || url.hash || url.pathname !== '/') throw unavailable();
  return Object.freeze({ ...value, baseUrl: url.origin, deadline: expires });
}

/** Canonical, bounded first utterance only; no client role, prompt or provider URL. */
export function validateInitialAudio(payload) {
  const checked = validateTranscription(payload);
  const audio = Buffer.from(checked.audio, 'base64');
  // Exactly wavFromPcm's 44-byte header and one contiguous native-rate payload.
  // The browser replays these exact bytes; alternate rates/chunks are rejected.
  if (audio.toString('ascii', 12, 16) !== 'fmt ' || audio.readUInt32LE(16) !== 16 ||
      audio.readUInt32LE(24) !== 24000 || audio.toString('ascii', 36, 40) !== 'data' ||
      audio.readUInt32LE(40) !== audio.length - 44) {
    throw new PublicError(400, 'invalid_initial_audio', 'Send a canonical 24 kHz mono PCM WAV recording.');
  }
  const duration = (audio.length - 44) / 48000;
  if (duration > INITIAL_AUDIO_SECONDS) throw new PublicError(400, 'invalid_initial_audio', 'Record at most twelve seconds for the initial voice selection.');
  return Object.freeze({ payload: checked, duration, audioHash: createHash('sha256').update(audio).digest('hex') });
}

async function delay(ms, signal) {
  if (signal.aborted) throw cancelled();
  await new Promise((resolve, reject) => {
    const onAbort = () => { clearTimeout(timer); reject(cancelled()); };
    const timer = setTimeout(() => { signal.removeEventListener('abort', onAbort); resolve(); }, ms);
    signal.addEventListener('abort', onAbort, { once: true });
  });
}

// Race even dependencies which ignore cancellation; no late result may prime or
// grant a worker. The real provider and private HTTP calls also receive signal.
async function bounded(work, ms, parentSignal, timers) {
  if (parentSignal?.aborted) throw cancelled();
  const controller = new AbortController();
  let rejectAbort;
  const aborted = new Promise((_, reject) => { rejectAbort = reject; });
  const onAbort = () => { controller.abort(); rejectAbort(cancelled()); };
  parentSignal?.addEventListener('abort', onAbort, { once: true });
  const timer = timers.setTimeout(() => { controller.abort(); rejectAbort(timeout()); }, ms);
  try { return await Promise.race([Promise.resolve().then(() => {
    if (controller.signal.aborted) throw cancelled();
    return work(controller.signal);
  }), aborted]); }
  finally { timers.clearTimeout(timer); parentSignal?.removeEventListener('abort', onAbort); controller.abort(); }
}

async function privatePrime(lease, body, signal, fetchImpl) {
  const response = await fetchImpl(`${lease.baseUrl}/api/prime`, {
    method: 'POST', redirect: 'manual', signal,
    headers: { Authorization: `Bearer ${lease.connectToken}`, 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (response.status !== 200) { await response.body?.cancel(); throw failed(); }
  try { return JSON.parse((await readResponse(response, 4096)).toString('utf8')); }
  catch { throw failed(); }
}

function sameWorker(before, after) {
  return ['epoch', 'baseUrl', 'connectToken', 'createdAt', 'expiresAt', 'sourceRevision', 'modelRevision', 'voice', 'protocol']
    .every(key => before[key] === after[key]);
}

/**
 * Source-only admission coordinator. The future HTTP route MUST first enforce
 * origin/CSRF, public gateway access, session lookup, content type, body size,
 * ASR configuration and rate/concurrency limits. Its authenticated session
 * object and map-identity predicate are trusted inputs, never browser fields.
 * This module neither starts a provider nor writes the launcher's lease.
 */
export function createPersonaplexInitialCoordinator({ config, enabled = config?.personaplexInitialRole === true, now = Date.now,
  readLeaseImpl = readPersonaplexLease, fetchImpl = fetch, allowLocalWorker = false,
  transcribeImpl = (payload, signal) => transcribe(payload, config, fetchImpl, signal),
  primeImpl = (lease, body, signal) => privatePrime(lease, body, signal, fetchImpl),
  classifyImpl = classifyMood, waitImpl = delay, timers = { setTimeout, clearTimeout } } = {}) {
  const records = new WeakMap(), owners = new Set(), spentEpochs = new Set();
  let current = null, closed = false;
  const configured = () => enabled === true && !closed && config?.voiceProvider === 'personaplex' &&
    config.backgroundAsr === 'openrouter' && Boolean(config.personaplexLeaseFile && config.openrouterKey);
  const bound = (work, ms, signal) => bounded(work, ms, signal, timers);
  const checkedLease = signal => bound(async () => {
    if (!configured()) throw unavailable();
    try { return validatePersonaplexInitialLease(await readLeaseImpl(config.personaplexLeaseFile), now(), allowLocalWorker); }
    catch { throw unavailable(); }
  }, READ_MS, signal);
  function invalidate(record) {
    if (!record || record.stage === 'invalid') return;
    record.stage = 'invalid'; record.abort.abort(); timers.clearTimeout(record.expiryTimer);
    record.requestSignal.removeEventListener('abort', record.onRequestAbort);
    owners.delete(record); if (current === record) current = null;
  }
  function owner(record, session = record?.session) {
    let valid = false;
    try { valid = Boolean(configured() && record && session === record.session && session.id === record.sessionId &&
      session.expires > now() && record.sessionDeadline > now() && record.lease.deadline > now() &&
      record.isSessionCurrent(session) === true && !record.abort.signal.aborted && record.stage !== 'invalid'); } catch { /* No session details escape. */ }
    if (!valid) { invalidate(record); throw cancelled(); }
    return record;
  }
  function matching(record, lease, primed = false) {
    if (!sameWorker(record.lease, lease) || lease.phase === 'closed' || lease.phase === 'streaming') throw failed();
    if (lease.phase !== 'warm' && (lease.avatar !== record.avatar || lease.selectionId !== record.selectionId ||
      lease.promptHash !== (lease.phase === 'priming' ? null : record.promptHash))) throw failed();
    if (primed && (lease.phase !== 'primed' || !lease.ready)) throw failed();
  }
  const api = {
    async available() {
      if (!configured() || current || spentEpochs.size >= 256) return false;
      try { const lease = await checkedLease(); return configured() && lease.phase === 'warm' &&
        lease.deadline - now() >= INITIAL_CAPABILITY_MS && !spentEpochs.has(lease.epoch); } catch { return false; }
    },
    async select(payload, session, { signal, isSessionCurrent } = {}) {
      if (!configured()) throw unavailable();
      if (!signal || typeof signal.addEventListener !== 'function' || typeof isSessionCurrent !== 'function' ||
          !session || typeof session.id !== 'string' || !Number.isFinite(session.expires)) throw cancelled();
      const audio = validateInitialAudio(payload);
      const lease = await checkedLease(signal);
      if (!configured()) throw unavailable();
      let authenticated = false;
      try { authenticated = isSessionCurrent(session) === true; } catch { /* Fixed public cancellation only. */ }
      if (signal.aborted || session.expires <= now() || !authenticated) throw cancelled();
      if (lease.phase !== 'warm' || lease.deadline - now() < INITIAL_RESERVATION_MS || spentEpochs.has(lease.epoch)) throw unavailable();
      if (current) throw new PublicError(409, 'initial_selection_active', 'An initial voice selection is already in progress.');
      if (spentEpochs.size >= 256) throw unavailable();
      // Atomic after the lease read, before any paid ASR/private prime await.
      spentEpochs.add(lease.epoch);
      const binding = Object.freeze(Object.create(null));
      const record = { lease, session, sessionId: session.id, sessionDeadline: session.expires, isSessionCurrent,
        requestSignal: signal, abort: new AbortController(), selectionId: randomBytes(32).toString('base64url'),
        audioHash: audio.audioHash, duration: audio.duration, avatar: null, promptHash: null, stage: 'asr', binding };
      record.onRequestAbort = () => invalidate(record);
      signal.addEventListener('abort', record.onRequestAbort, { once: true });
      record.expiryTimer = timers.setTimeout(() => invalidate(record), Math.max(1, Math.min(lease.deadline, session.expires) - now()));
      record.expiryTimer?.unref?.(); records.set(binding, record); owners.add(record); current = record;
      try {
        owner(record);
        const asr = await bound(child => transcribeImpl(audio.payload, child), ASR_MS, record.abort.signal);
        owner(record);
        if (!object(asr) || typeof asr.text !== 'string' || !asr.text.trim() || asr.text.length > 4000) throw failed();
        const classification = classifyImpl(asr.text.trim());
        if (!object(classification) || !Object.hasOwn(INITIAL_ROLE_HASHES, classification.avatar)) throw failed();
        record.avatar = classification.avatar; record.promptHash = INITIAL_ROLE_HASHES[record.avatar];
        const beforePrime = await checkedLease(record.abort.signal); owner(record); matching(record, beforePrime);
        if (beforePrime.phase !== 'warm' || beforePrime.deadline - now() < INITIAL_CLAIM_MS + PRIME_MS + PROMOTION_MS) throw unavailable();
        record.stage = 'priming';
        const receipt = await bound(child => primeImpl(beforePrime,
          Object.freeze({ selectionId: record.selectionId, avatar: record.avatar }), child), PRIME_MS, record.abort.signal);
        owner(record); validateHealth(receipt);
        if (receipt.phase !== 'primed' || !receipt.ready || receipt.avatar !== record.avatar ||
            receipt.selectionId !== record.selectionId || receipt.promptHash !== record.promptHash) throw failed();
        record.stage = 'promotion';
        await bound(async child => {
          const end = now() + PROMOTION_MS;
          while (true) {
            owner(record);
            const promoted = await checkedLease(child); owner(record); matching(record, promoted);
            if (promoted.phase === 'primed' && promoted.ready) { record.promoted = promoted; break; }
            if (now() >= end) throw timeout();
            await waitImpl(Math.min(100, end - now()), child);
          }
        }, PROMOTION_MS, record.abort.signal);
        owner(record);
        if (record.promoted.deadline - now() < INITIAL_CLAIM_MS) throw unavailable();
        record.stage = 'selected';
        return { publicResult: Object.freeze({ avatar: record.avatar, transcript: asr.text.trim(), initialContextDelivered: false }), binding };
      } catch (error) {
        invalidate(record);
        throw error instanceof PublicError ? error : failed();
      }
    },
    /** Private relay handoff only. A second claim cannot race the first lease read. */
    async claim(binding, session) {
      const record = records.get(binding); owner(record, session);
      if (record.stage !== 'selected') throw cancelled();
      record.stage = 'claiming';
      try {
        const lease = await checkedLease(record.abort.signal); owner(record, session); matching(record, lease, true);
        if (lease.deadline - now() < INITIAL_CLAIM_MS) throw unavailable();
        record.stage = 'claimed'; if (current === record) current = null;
        const grant = Object.create(null);
        // Accidental JSON/spread cannot leak the private endpoint or credential.
        for (const [key, value] of Object.entries({ lease, avatar: record.avatar, sessionId: record.sessionId,
          selectionId: record.selectionId, audioHash: record.audioHash, promptHash: record.promptHash,
          audioSeconds: record.duration, ownerSignal: record.abort.signal,
          isValid: () => { try { owner(record, session); return record.stage === 'claimed'; } catch { return false; } } })) {
          Object.defineProperty(grant, key, { value, enumerable: false });
        }
        return Object.freeze(grant);
      } catch (error) { invalidate(record); throw error instanceof PublicError ? error : failed(); }
    },
    /** Call only on confirmed HTTP response finish, never merely res.end(). */
    acknowledgeDelivery(binding, session) {
      const record = records.get(binding); owner(record, session);
      if (record.stage !== 'claimed') throw cancelled();
      record.requestSignal.removeEventListener('abort', record.onRequestAbort);
    },
    invalidate(binding) { invalidate(records.get(binding)); },
    invalidateSession(session) { for (const record of owners) if (record.session === session) invalidate(record); },
    close() { closed = true; for (const record of owners) invalidate(record); },
  };
  return Object.freeze(api);
}
