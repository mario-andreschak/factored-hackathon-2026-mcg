import { randomBytes, createHash } from 'node:crypto';
import { open, lstat } from 'node:fs/promises';
import WebSocket, { WebSocketServer } from 'ws';
import { PublicError } from './http.mjs';
import { createPersonaplexInitialCoordinator, validatePersonaplexInitialLease, INITIAL_CLAIM_MS } from './personaplex-initial.mjs';

export const PERSONAPLEX_PROTOCOL = 'personaplex-pcm-v1';
export const SOURCE_REVISION = '3428dfd95309a7f3c84fd93259ded0f810d1ff91';
export const MODEL_REVISION = 'fdaf4090a61cb315c138a1faee287ffd6c716309';
export const MINIMUM_PERSONAPLEX_LEASE_MS = 120_000;
const FRAME = 1920, RATE = 24000, AUDIO_CAP = FRAME * 2 * 6;
const READY = { type: 'ready', protocol: PERSONAPLEX_PROTOCOL, sampleRate: RATE, frameSamples: FRAME, format: 'pcm16le' };
const object = value => value && typeof value === 'object' && !Array.isArray(value);
const only = (value, keys) => object(value) && Object.keys(value).every(key => keys.includes(key));
const unavailable = () => new PublicError(503, 'personaplex_unavailable', 'The bounded native voice audition is not ready. You can still type.');
const busy = () => new PublicError(409, 'voice_active', 'A native voice audition is already connected.');
const ticketError = () => new PublicError(401, 'invalid_voice_ticket', 'The voice ticket is invalid or expired. Start a new voice session.');

export function validatePersonaplexRequest(value) {
  if (!only(value, ['avatar']) || !['moss', 'orbit', 'spark'].includes(value.avatar)) {
    throw new PublicError(400, 'invalid_avatar', 'Send only a valid avatar choice.');
  }
  return value.avatar;
}

/** Local operator file only; never a path accepted from a browser. */
export async function readPersonaplexLease(path) {
  if (!path) throw unavailable();
  const info = await lstat(path);
  if (!info.isFile() || info.isSymbolicLink() || info.size > 16 * 1024 ||
      (process.platform !== 'win32' && (info.mode & 0o077))) throw unavailable();
  const handle = await open(path, 'r');
  try {
    const opened = await handle.stat();
    if (!opened.isFile() || opened.size > 16 * 1024) throw unavailable();
    const data = await handle.readFile({ encoding: 'utf8' });
    if (Buffer.byteLength(data) > 16 * 1024) throw unavailable();
    return JSON.parse(data);
  } finally { await handle.close(); }
}

export function validatePersonaplexLease(value, now, allowLocalWorker = false) {
  const created = Date.parse(value?.createdAt), expires = Date.parse(value?.expiresAt), updated = Date.parse(value?.updatedAt);
  let url;
  try { url = new URL(value?.baseUrl); } catch { throw unavailable(); }
  const local = allowLocalWorker && ['127.0.0.1', 'localhost'].includes(url.hostname) && url.protocol === 'http:';
  const remote = url.protocol === 'https:' && /^(?:[a-z0-9-]+\.)*(?:modal\.run|modal\.host)$/.test(url.hostname) && !url.port;
  if (!object(value) || value.version !== 1 || value.ready !== true || value.protocol !== PERSONAPLEX_PROTOCOL ||
      value.sourceRevision !== SOURCE_REVISION || value.modelRevision !== MODEL_REVISION ||
      !['moss', 'orbit', 'spark'].includes(value.avatar) || !/^[A-Za-z0-9_-]{32,128}$/.test(value.epoch) ||
      typeof value.connectToken !== 'string' || !/^[\x21-\x7e]{16,8192}$/.test(value.connectToken) ||
      ![created, expires, updated].every(Number.isFinite) || created > now || expires <= now ||
      expires - created > 600_000 || updated < created || updated > now + 1000 || now - updated > 6000 ||
      (!remote && !local) || url.username || url.password || url.search || url.hash || url.pathname !== '/') throw unavailable();
  return { ...value, baseUrl: url.origin, deadline: expires };
}

/** Trusted dependency injection permits deterministic local worker tests only. */
export function createPersonaplexRelay({ config, now = Date.now, readLeaseImpl = readPersonaplexLease,
  allowLocalWorker = false, fetchImpl = fetch, initialOptions = {}, connectImpl = (url, options) => new WebSocket(url, options) }) {
  const tickets = new Map(), usedEpochs = new Set();
  const sockets = new Set();
  let current = null, closed = false;
  const initial = createPersonaplexInitialCoordinator({ config, now, readLeaseImpl, allowLocalWorker, fetchImpl, ...initialOptions });
  const wss = new WebSocketServer({ noServer: true, perMessageDeflate: false, maxPayload: AUDIO_CAP + 13,
    clientTracking: false, handleProtocols: () => false });
  const enabled = () => config.voiceProvider === 'personaplex' && Boolean(config.personaplexLeaseFile) && !closed;
  const checkedLease = async (grant = null) => {
    if (!enabled()) throw unavailable();
    try {
      if (grant && (!config.personaplexInitialRole || !grant.isValid())) throw unavailable();
      const value = await readLeaseImpl(config.personaplexLeaseFile);
      if (!grant) return validatePersonaplexLease(value, now(), allowLocalWorker);
      const lease = validatePersonaplexInitialLease(value, now(), allowLocalWorker);
      if (!grant.isValid() || !lease.ready || !['primed', 'streaming'].includes(lease.phase) ||
          ['epoch', 'baseUrl', 'connectToken', 'createdAt', 'expiresAt', 'sourceRevision', 'modelRevision', 'voice', 'protocol']
            .some(key => lease[key] !== grant.lease[key]) || lease.avatar !== grant.avatar ||
          lease.selectionId !== grant.selectionId || lease.promptHash !== grant.promptHash) throw unavailable();
      return lease;
    }
    catch { throw unavailable(); }
  };
  const checkedAdmissionLease = async (grant = null) => {
    const lease = await checkedLease(grant);
    if (lease.deadline - now() < (grant ? INITIAL_CLAIM_MS : MINIMUM_PERSONAPLEX_LEASE_MS) || grant && lease.phase !== 'primed') throw unavailable();
    return lease;
  };
  function sweep() {
    for (const [key, value] of tickets) if (value.expires <= now()) forgetTicket(key, value, true);
  }
  function forgetTicket(key, value, invalidate = false) {
    tickets.delete(key); clearTimeout(value.timer);
    if (invalidate && value.binding) initial.invalidate(value.binding);
  }
  function issueTicket(lease, avatar, session, extra = {}) {
    sweep();
    for (const [key, value] of tickets) if (value.sessionId === session.id) forgetTicket(key, value, true);
    if (tickets.size >= 256) throw new PublicError(503, 'capacity', 'The voice service is busy.');
    const ticket = randomBytes(32).toString('base64url');
    const key = createHash('sha256').update(ticket).digest('hex');
    const expires = Math.min(now() + 15_000, lease.deadline, session.expires);
    const entry = { sessionId: session.id, avatar, epoch: lease.epoch, expires, ...extra };
    entry.timer = setTimeout(() => { if (tickets.get(key) === entry) forgetTicket(key, entry, true); }, Math.max(1, expires - now()));
    entry.timer.unref(); tickets.set(key, entry);
    return { ticket, expiresAt: new Date(expires).toISOString(), streamPath: '/api/avatar/personaplex',
      inputSampleRate: RATE, outputSampleRate: RATE, protocol: PERSONAPLEX_PROTOCOL };
  }
  return {
    async initialAvailable() { return enabled() && !current && await initial.available(); },
    async selectInitial(payload, session, options) {
      if (!enabled() || current) throw unavailable();
      return initial.select(payload, session, options);
    },
    async issueInitial(binding, session) {
      try {
        if (!enabled() || current) throw unavailable();
        const grant = await initial.claim(binding, session);
        const lease = await checkedAdmissionLease(grant);
        if (current || usedEpochs.has(lease.epoch)) throw unavailable();
        return issueTicket(lease, grant.avatar, session, { binding, grant });
      } catch (error) { initial.invalidate(binding); throw error; }
    },
    acknowledgeInitial(binding, session) { initial.acknowledgeDelivery(binding, session); },
    cancelInitial(binding) { initial.invalidate(binding); },
    observerSignal(session) {
      if (!enabled() || !current?.ready || current.sessionId !== session.id || current.abort.signal.aborted ||
          current.deadline <= now() || session.expires <= now()) return null;
      return current.abort.signal;
    },
    async profile() {
      try { const lease = await checkedLease(); return { avatar: lease.avatar,
        available: lease.deadline - now() >= MINIMUM_PERSONAPLEX_LEASE_MS && !current && !usedEpochs.has(lease.epoch) }; }
      catch { return null; }
    },
    async available() {
      try { const lease = await checkedAdmissionLease(); return !current && !usedEpochs.has(lease.epoch); }
      catch { return false; }
    },
    async issue(avatar, session) {
      const lease = await checkedAdmissionLease();
      if (lease.avatar !== avatar || usedEpochs.has(lease.epoch)) throw unavailable();
      if (current) throw busy();
      return issueTicket(lease, avatar, session);
    },
    async upgrade(req, socket, head, url, session) {
      if (req.method !== 'GET' || req.headers['sec-websocket-protocol'] ||
          String(req.headers.upgrade || '').toLowerCase() !== 'websocket' || req.headers['sec-websocket-version'] !== '13' ||
          !/^[+/0-9A-Za-z]{22}==$/.test(String(req.headers['sec-websocket-key'] || '')) ||
          [...url.searchParams.keys()].some(key => key !== 'ticket') || url.searchParams.getAll('ticket').length !== 1) throw ticketError();
      const ticket = url.searchParams.get('ticket');
      if (!/^[A-Za-z0-9_-]{43}$/.test(ticket)) throw ticketError();
      const key = createHash('sha256').update(ticket).digest('hex');
      const entry = tickets.get(key);
      if (!entry || entry.expires <= now() || entry.sessionId !== session.id) {
        if (entry?.expires <= now()) forgetTicket(key, entry, true);
        throw ticketError();
      }
      // Consume before any asynchronous worker read/dial. Concurrent replays fail.
      forgetTicket(key, entry);
      if (current) throw busy();
      const reservation = { stop: () => socket.destroy(), sessionId: session.id, ready: false,
        deadline: 0, abort: new AbortController() };
      current = reservation;
      socket.once('close', () => { reservation.abort.abort(); if (entry.binding) initial.invalidate(entry.binding); if (current === reservation) current = null; });
      let lease;
      try {
        lease = await checkedAdmissionLease(entry.grant);
        if (lease.epoch !== entry.epoch || lease.avatar !== entry.avatar || usedEpochs.has(lease.epoch) ||
            session.expires <= now() || entry.expires <= now() || socket.destroyed) throw ticketError();
      } catch (error) { reservation.abort.abort(); if (entry.binding) initial.invalidate(entry.binding); if (current === reservation) current = null; throw error; }
      try {
        wss.handleUpgrade(req, socket, head, client => {
          usedEpochs.add(lease.epoch);
          if (usedEpochs.size > 128) usedEpochs.delete(usedEpochs.values().next().value);
          const deadline = Math.min(lease.deadline, session.expires, now() + 600_000);
          reservation.deadline = deadline;
          const workerUrl = new URL('/api/chat', lease.baseUrl); workerUrl.protocol = workerUrl.protocol === 'https:' ? 'wss:' : 'ws:';
          let worker;
          try { worker = connectImpl(workerUrl.href, { headers: { Authorization: `Bearer ${lease.connectToken}` },
            perMessageDeflate: false, maxPayload: AUDIO_CAP + 13, handshakeTimeout: 5000, followRedirects: false,
            rejectUnauthorized: true }); }
          catch { reservation.abort.abort(); client.terminate(); if (current === reservation) current = null; return; }
          let stopped = false, ready = false, generation = 0, nextSample = 0n, minimumSample = 0n;
          let lastAudio = now(), lastClientPong = now(), lastWorkerPong = now();
          let inputWindow = now(), inputBytes = 0, inputPackets = 0, controlWindow = now(), controls = 0;
          let interrupt = null, monitoring = false;
          const timers = [];
          sockets.add(client); sockets.add(worker);
          const stop = (code = 'voice_ended') => {
            if (stopped) return;
            stopped = true;
            reservation.ready = false; reservation.abort.abort();
            if (entry.binding) initial.invalidate(entry.binding);
            for (const timer of timers) { clearTimeout(timer); clearInterval(timer); }
            sockets.delete(client); sockets.delete(worker);
            if (current === reservation) current = null;
            worker.terminate();
            if (client.readyState === WebSocket.OPEN) {
              client.send(JSON.stringify({ type: 'error', code, message: 'The native voice audition ended. You can still type.' }), () => {
                if (client.readyState === WebSocket.OPEN) client.close(1000, 'Voice session ended.');
              });
              const force = setTimeout(() => client.terminate(), 250); force.unref();
            } else client.terminate();
          };
          if (entry.grant) {
            entry.grant.ownerSignal.addEventListener('abort', () => stop('voice_expired'), { once: true });
            if (!entry.grant.isValid()) { stop('voice_expired'); return; }
          }
          reservation.stop = stop;
          const timer = setTimeout(() => stop('voice_expired'), Math.max(1, deadline - now())); timer.unref(); timers.push(timer);
          const setupTimer = setTimeout(() => { if (!ready) stop('voice_unavailable'); }, 10_000); setupTimer.unref(); timers.push(setupTimer);
          const send = (target, data, binary) => {
            if (target.readyState !== WebSocket.OPEN || target.bufferedAmount + data.length > AUDIO_CAP + 16 * 1024) {
              stop('voice_backpressure'); return false;
            }
            target.send(data, { binary }, error => { if (error) stop('voice_unavailable'); }); return true;
          };
          client.on('pong', () => { lastClientPong = now(); });
          worker.on('pong', () => { lastWorkerPong = now(); });
          client.on('error', () => stop('voice_unavailable'));
          worker.on('error', () => stop('voice_unavailable'));
          worker.on('unexpected-response', (_request, response) => { response.resume(); stop('voice_unavailable'); });
          client.on('close', () => stop()); worker.on('close', () => stop());
          client.on('message', (data, binary) => {
            if (stopped) return;
            if (!ready) { stop('invalid_audio'); return; }
            if (binary) {
              if (data[0] !== 0x10 || data.length < 3 || (data.length - 1) % 2 || data.length - 1 > AUDIO_CAP) { stop('invalid_audio'); return; }
              if (now() - inputWindow >= 1000) { inputWindow = now(); inputBytes = 0; inputPackets = 0; }
              inputBytes += data.length - 1;
              if (++inputPackets > 128 || inputBytes > RATE * 2 + AUDIO_CAP) { stop('invalid_audio'); return; }
              lastAudio = now(); send(worker, data, true);
            } else {
              let value; try { value = JSON.parse(data.toString('utf8')); } catch { stop('invalid_audio'); return; }
              if (data.length > 16 * 1024 || !only(value, ['type', 'id']) || value.type !== 'interrupt' ||
                  !/^[A-Za-z0-9_-]{1,128}$/.test(value.id) || interrupt) { stop('invalid_audio'); return; }
              if (now() - controlWindow >= 1000) { controlWindow = now(); controls = 0; }
              if (++controls > 8) { stop('invalid_audio'); return; }
              interrupt = { id: value.id, deadline: now() + 3000 };
              send(worker, Buffer.from(JSON.stringify(value)), false);
            }
          });
          worker.on('message', (data, binary) => {
            if (stopped) return;
            if (binary) {
              if (!ready || data.length < 15 || data[0] !== 0x11 || (data.length - 13) % 2 || data.length - 13 > AUDIO_CAP) { stop('invalid_audio'); return; }
              const packetGeneration = data.readUInt32LE(1), sample = data.readBigUInt64LE(5);
              if (packetGeneration < generation || interrupt) return;
              if (packetGeneration !== generation || (nextSample !== null && sample !== nextSample) || sample < minimumSample ||
                  sample > 600n * BigInt(RATE)) { stop('invalid_audio'); return; }
              nextSample = sample + BigInt((data.length - 13) / 2); minimumSample = nextSample;
              send(client, data, true);
            } else {
              let value; try { value = JSON.parse(data.toString('utf8')); } catch { stop('invalid_audio'); return; }
              if (data.length > 16 * 1024 || !object(value)) { stop('invalid_audio'); return; }
              if (value.type === 'ready') {
                if (ready || Object.keys(READY).some(key => value[key] !== READY[key]) || Object.keys(value).length !== Object.keys(READY).length) { stop('invalid_audio'); return; }
                if (entry.grant && !entry.grant.isValid() || deadline - now() < (entry.grant ? MINIMUM_PERSONAPLEX_LEASE_MS + 12_000 : MINIMUM_PERSONAPLEX_LEASE_MS)) { stop('voice_expired'); return; }
                ready = true; reservation.ready = true; lastAudio = now(); clearTimeout(setupTimer); send(client, Buffer.from(JSON.stringify(READY)), false);
              } else if (value.type === 'interrupted') {
                if (!only(value, ['type', 'id', 'generation']) || !interrupt || value.id !== interrupt.id || value.generation !== generation + 1) { stop('invalid_audio'); return; }
                // The worker clock is global. Output discarded during a pending
                // interrupt can create a gap, so anchor at its first new frame.
                generation = value.generation; nextSample = null; interrupt = null; send(client, Buffer.from(JSON.stringify(value)), false);
              } else if (value.type === 'transcript') {
                if (!ready || !only(value, ['type', 'id', 'role', 'text', 'done', 'generation']) || value.role !== 'assistant' ||
                    !/^[A-Za-z0-9_-]{1,128}$/.test(value.id) || typeof value.text !== 'string' || value.text.length > 8000 || typeof value.done !== 'boolean') { stop('invalid_audio'); return; }
                if (!Number.isInteger(value.generation) || value.generation < 0 || value.generation > generation) { stop('invalid_audio'); return; }
                if (!interrupt && value.generation === generation) send(client, Buffer.from(JSON.stringify(value)), false);
              } else { stop('voice_unavailable'); }
            }
          });
          const monitor = setInterval(async () => {
            if (stopped || monitoring) return;
            monitoring = true;
            try {
              const fresh = await checkedLease(entry.grant);
              if (fresh.epoch !== lease.epoch || fresh.avatar !== lease.avatar || fresh.connectToken !== lease.connectToken || fresh.deadline !== lease.deadline ||
                  deadline <= now() || session.expires <= now()) { stop('voice_expired'); return; }
              if (ready && now() - lastAudio > 3000) { stop('voice_audio_timeout'); return; }
              if (interrupt?.deadline <= now()) { stop('voice_unavailable'); return; }
              if (now() - lastClientPong > 40_000 || now() - lastWorkerPong > 40_000) { stop('voice_unavailable'); return; }
              if (client.readyState === WebSocket.OPEN) client.ping();
              if (worker.readyState === WebSocket.OPEN) worker.ping();
            } catch { stop('voice_expired'); }
            finally { monitoring = false; }
          }, 1000); monitor.unref(); timers.push(monitor);
        });
      } catch (error) { reservation.abort.abort(); if (current === reservation) current = null; throw error; }
    },
    close() {
      closed = true; initial.close(); for (const [key, value] of tickets) forgetTicket(key, value, true); usedEpochs.clear(); current?.stop(); current = null;
      for (const socket of sockets) socket.terminate(); sockets.clear(); wss.close();
    },
  };
}

export function rejectPersonaplexUpgrade(socket, error) {
  const known = error instanceof PublicError;
  const status = known ? error.status : 503;
  const body = JSON.stringify({ code: known ? error.code : 'voice_unavailable',
    error: known ? error.message : 'The native voice audition is unavailable.' });
  socket.end(`HTTP/1.1 ${status} Voice request rejected\r\nConnection: close\r\nContent-Type: application/json\r\nCache-Control: no-store\r\nContent-Length: ${Buffer.byteLength(body)}\r\n\r\n${body}`);
}
