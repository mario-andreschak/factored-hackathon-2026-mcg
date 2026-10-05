import { useCallback, useEffect, useRef, useState } from 'react';
import { base64Bytes, pcm16FromFloat32, Pcm16Resampler, Pcm16Stream, wavFromPcm } from '../audio';
import type { AvatarId, Phase } from '../domain';
import { capturePacket, outputPacket, PCM_RATE, PERSONAPLEX_PROTOCOL } from './personaplexProtocol';
import { UtteranceCollector, UtteranceObserver } from './utteranceObserver';
import { InitialPcmReplay } from '../audio/initialReplay';

interface Options {
  avatar: AvatarId;
  onTranscript: (id: string, role: 'user' | 'assistant', text: string, done: boolean) => void;
  onUserUtterance?: () => void;
  backgroundAsr?: boolean;
  observerPaused?: boolean;
  onObservedTranscript?: (id: string, text: string) => void;
  onObserverError?: () => void;
  initialRole?: boolean;
  onInitialSelection?: (avatar: AvatarId) => void;
  onInitialTranscript?: (id: string, text: string) => void;
}
interface Session {
  abort: AbortController; ready: boolean; muted: boolean; ws?: WebSocket;
  context?: AudioContext; stream?: MediaStream; input?: MediaStreamAudioSourceNode;
  capture?: AudioWorkletNode; silentGain?: GainNode; analyser?: AnalyserNode;
  timer?: ReturnType<typeof setTimeout>; expiry?: ReturnType<typeof setTimeout>; interruptTimer?: ReturnType<typeof setTimeout>; raf?: number;
  resampler?: Pcm16Resampler; sources: Set<AudioBufferSourceNode>; scheduled: number;
  generation: number; nextSample?: number; playbackEpoch: number;
  held: boolean; manualStop: boolean; interruptId?: string; interruptGeneration?: number;
  userActive: boolean; voiced: number; quiet: number; inputLevel: number;
  messages: Promise<void>; captions: Map<string, { role: 'user' | 'assistant'; done: boolean }>;
  collector?: UtteranceCollector; observer?: UtteranceObserver;
  turn: number;
  taskHold?: { owner: symbol; stage: 'working' | 'awaiting-user'; afterTurn: number; eligibleTurn?: number };
  initial?: {
    stage: 'capture' | 'preparing' | 'replay' | 'live'; collector: UtteranceCollector;
    captured?: Float32Array; text?: string; transcriptId: string; delivered: boolean;
    complete?: (wav: Uint8Array) => void; replay?: InitialPcmReplay;
    pre: Float32Array[]; preSamples: number;
  };
}

/** Native duplex transport; initial role selection remains an opt-in qualification candidate. */
export function usePersonaPlex(options: Options) {
  const opts = useRef(options); opts.current = options;
  const session = useRef<Session | null>(null);
  const fail = useRef<(message: string) => void>(() => {});
  const [connected, setConnected] = useState(false), [connecting, setConnecting] = useState(false);
  const [phase, setPhase] = useState<Phase>('idle'), [muted, setMuted] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0), [error, setError] = useState('');
  const [initialListening, setInitialListening] = useState(false);
  const [voiceAvatar, setVoiceAvatar] = useState<AvatarId | null>(null);
  const current = useCallback((s: Session) => session.current === s && !s.abort.signal.aborted, []);
  const resumeAfterHold = useCallback((s: Session) => {
    const hold = s.taskHold;
    if (hold?.stage === 'awaiting-user' && hold.eligibleTurn !== undefined && !s.userActive &&
        !s.interruptId && !s.muted && !opts.current.observerPaused) s.taskHold = undefined;
    if (!s.taskHold && !s.manualStop && !s.userActive && !s.interruptId) s.held = false;
  }, []);
  const clearPlayback = useCallback((s: Session) => {
    s.playbackEpoch++;
    for (const source of s.sources) { source.onended = null; try { source.stop(); } catch { /* ended */ } source.disconnect(); }
    s.sources.clear(); s.scheduled = 0;
  }, []);
  const disconnect = useCallback(() => {
    const s = session.current; session.current = null;
    if (s) {
      s.abort.abort(); clearTimeout(s.timer); clearTimeout(s.expiry); clearTimeout(s.interruptTimer);
      s.collector?.reset(); s.observer?.dispose();
      if (s.initial) { s.initial.collector.reset(); s.initial.replay?.cancel(); s.initial.captured?.fill(0); s.initial.captured = undefined; s.initial.text = undefined; s.initial.complete = undefined; s.initial.pre.forEach(chunk => chunk.fill(0)); s.initial.pre = []; }
      if (s.raf !== undefined) cancelAnimationFrame(s.raf);
      clearPlayback(s); s.captions.clear(); s.taskHold = undefined;
      if (s.ws) { s.ws.onopen = null; s.ws.onmessage = null; s.ws.onerror = null; s.ws.onclose = null; try { s.ws.close(1000); } catch { /* opening */ } }
      if (s.capture) { s.capture.port.onmessage = null; s.capture.disconnect(); }
      s.input?.disconnect(); s.silentGain?.disconnect(); s.analyser?.disconnect();
      s.stream?.getTracks().forEach(track => track.stop()); void s.context?.close().catch(() => {});
    }
    setConnected(false); setConnecting(false); setMuted(false); setPhase('idle'); setAudioLevel(0); setInitialListening(false); setVoiceAvatar(null);
  }, [clearPlayback]);
  fail.current = message => { disconnect(); setError(message); };
  const send = useCallback((s: Session, value: object | Uint8Array) => {
    if (!current(s) || !s.ready || s.ws?.readyState !== WebSocket.OPEN) return false;
    // Half a second of native microphone audio is already too old for this route.
    if (s.ws.bufferedAmount > 24000) { fail.current('The voice connection fell behind. Reconnect to keep talking.'); return false; }
    try { s.ws.send(value instanceof Uint8Array ? value : JSON.stringify(value)); return true; }
    catch { fail.current('The voice connection ended. Reconnect to keep talking.'); return false; }
  }, [current]);
  const stopSpeech = useCallback((s: Session, manual: boolean) => {
    clearPlayback(s); s.held = true; s.manualStop = manual;
    if (s.interruptId) { setAudioLevel(0); setPhase('listening'); return; }
    clearTimeout(s.interruptTimer); s.interruptId = crypto.randomUUID(); s.interruptGeneration = s.generation;
    send(s, { type: 'interrupt', id: s.interruptId });
    if (!current(s)) return;
    const id = s.interruptId;
    s.interruptTimer = setTimeout(() => { if (current(s) && s.interruptId === id) fail.current('The voice worker did not acknowledge interruption. Reconnect to continue.'); }, 4000);
    setAudioLevel(0); setPhase('listening');
  }, [clearPlayback, current, send]);
  const handleAudio = useCallback((s: Session, data: ArrayBuffer) => {
    const packet = outputPacket(data);
    if (packet.generation < s.generation) return;
    if (packet.generation > s.generation) { clearPlayback(s); s.generation = packet.generation; s.nextSample = undefined; }
    if (s.nextSample !== undefined && packet.sampleIndex !== s.nextSample) throw new Error('clock');
    s.nextSample = packet.sampleIndex + packet.samples.length;
    if (s.taskHold || s.held || s.userActive || !s.context || !s.analyser) return;
    const context = s.context, buffer = context.createBuffer(1, packet.samples.length, PCM_RATE);
    buffer.getChannelData(0).set(packet.samples);
    if (Math.max(0, s.scheduled - context.currentTime) + buffer.duration > .48) throw new Error('backlog');
    const source = context.createBufferSource(), epoch = s.playbackEpoch;
    source.buffer = buffer; source.connect(s.analyser); s.sources.add(source);
    s.scheduled = Math.max(s.scheduled, context.currentTime + .04); source.start(s.scheduled); s.scheduled += buffer.duration;
    source.onended = () => { source.disconnect(); if (current(s) && epoch === s.playbackEpoch) s.sources.delete(source); };
  }, [clearPlayback, current]);
  const handleControl = useCallback((s: Session, event: Record<string, unknown>) => {
    if (!s.ready && event.type !== 'ready' && event.type !== 'error') throw new Error('control before readiness');
    if (event.type === 'ready') {
      if (s.ready) throw new Error('duplicate readiness');
      if (event.protocol !== PERSONAPLEX_PROTOCOL || event.sampleRate !== PCM_RATE || event.frameSamples !== 1920 || event.format !== 'pcm16le') throw new Error('protocol');
      s.ready = true; clearTimeout(s.timer); setConnected(true); setConnecting(false); setPhase('listening');
      if (s.initial) {
        const initial = s.initial;
        if (!initial.captured?.length || !initial.text || initial.stage !== 'preparing') throw new Error('initial context');
        initial.stage = 'replay'; initial.collector.reset(); s.collector?.reset(); s.resampler?.reset();
        s.voiced = 0; s.quiet = 0; s.userActive = false; initial.pre = []; initial.preSamples = 0;
        initial.replay = new InitialPcmReplay(initial.captured, {
          clock: { now: () => performance.now(), schedule: (callback, milliseconds) => setTimeout(callback, milliseconds), cancel: timer => clearTimeout(timer as ReturnType<typeof setTimeout>) },
          sendFrame: frame => send(s, capturePacket(pcm16FromFloat32(frame))),
          onLive: ({ reason, preroll }) => {
            if (!current(s)) return;
            const onset = reason === 'complete' && s.voiced > 0;
            const fresh = onset || reason === 'new-speech' && preroll.length > 0;
            const livePreroll = onset && s.context ? new Pcm16Stream().decode(wavFromPcm(initial.pre, s.context.sampleRate, PCM_RATE).subarray(44)) : preroll;
            initial.stage = 'live';
            s.resampler?.reset(); s.collector?.reset(); s.observer?.invalidate();
            if (!fresh) { s.voiced = 0; s.quiet = 0; s.userActive = false; }
            if (fresh && s.collector && s.observer && s.taskHold?.stage !== 'working' && opts.current.backgroundAsr && !s.muted && !opts.current.observerPaused) {
              for (const chunk of initial.pre) {
                let power = 0; for (const sample of chunk) power += sample * sample;
                s.collector.push(chunk, Math.sqrt(power / chunk.length) * 5 > .065);
              }
            }
            if (livePreroll.length) send(s, capturePacket(pcm16FromFloat32(livePreroll)));
            livePreroll.fill(0);
            initial.pre.forEach(chunk => chunk.fill(0)); initial.pre = []; initial.preSamples = 0;
          },
          onError: () => { if (current(s)) fail.current('The first voice request could not stay in time. Reconnect to continue.'); },
        });
        initial.captured.fill(0); initial.captured = undefined;
        initial.replay.start();
      }
    } else if (event.type === 'interrupted') {
      if (event.id !== s.interruptId) return;
      if (!Number.isInteger(event.generation) || Number(event.generation) <= (s.interruptGeneration ?? s.generation) || Number(event.generation) < s.generation || Number(event.generation) > 0xffffffff) throw new Error('generation');
      clearTimeout(s.interruptTimer);
      clearPlayback(s); s.generation = Number(event.generation); s.nextSample = undefined; s.interruptId = undefined; s.interruptGeneration = undefined;
      resumeAfterHold(s);
    } else if (event.type === 'transcript') {
      if ((event.role !== 'assistant' && event.role !== 'user') || typeof event.id !== 'string' || !event.id || event.id.length > 128 || typeof event.text !== 'string' || event.text.length > 8000 || typeof event.done !== 'boolean') throw new Error('caption');
      if (event.role === 'assistant') {
        if (!Number.isInteger(event.generation) || Number(event.generation) < 0 || Number(event.generation) > 0xffffffff) throw new Error('caption generation');
        if (s.taskHold || s.held || s.userActive || Number(event.generation) < s.generation) return;
      }
      const previous = s.captions.get(event.id);
      if (previous?.done) return;
      if (previous && previous.role !== event.role) throw new Error('caption identity');
      if (s.captions.size >= 512 && !previous) throw new Error('caption limit');
      s.captions.set(event.id, { role: event.role, done: event.done });
      if (event.text.trim()) opts.current.onTranscript(event.id, event.role, event.text, event.done);
    } else if (event.type === 'error') {
      // Arbitrary upstream messages/credentials are never reflected in the UI.
      fail.current('The native voice worker could not continue. Reconnect to try again.');
    } else throw new Error('unsupported control');
  }, [clearPlayback, current, resumeAfterHold, send]);
  const connect = useCallback(async (avatar: AvatarId = opts.current.avatar, backgroundAsr = Boolean(opts.current.backgroundAsr), initialRole = Boolean(opts.current.initialRole)) => {
    if (session.current) return;
    setConnecting(true); setError('');
    const s: Session = { abort: new AbortController(), ready: false, muted: false, sources: new Set(), scheduled: 0,
      generation: 0, playbackEpoch: 0, held: false, manualStop: false, userActive: false, turn: 0,
      voiced: 0, quiet: 0, inputLevel: 0, messages: Promise.resolve(), captions: new Map() };
    session.current = s;
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) throw new Error('Voice needs microphone access on HTTPS or localhost.');
      const context = new AudioContext(); s.context = context; await context.resume(); if (!current(s)) return;
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      if (!current(s)) { stream.getTracks().forEach(track => track.stop()); return; } s.stream = stream;
      await context.audioWorklet.addModule(`${import.meta.env.BASE_URL}audio-capture.js`); if (!current(s)) return;
      const analyser = context.createAnalyser(); analyser.fftSize = 256; analyser.smoothingTimeConstant = .2; analyser.connect(context.destination); s.analyser = analyser;
      const input = context.createMediaStreamSource(stream), capture = new AudioWorkletNode(context, 'voice-capture'), gain = context.createGain();
      gain.gain.value = 0; input.connect(capture); capture.connect(gain); gain.connect(context.destination);
      s.input = input; s.capture = capture; s.silentGain = gain; s.resampler = new Pcm16Resampler(context.sampleRate, PCM_RATE);
      if (initialRole) s.initial = { stage: 'capture', collector: new UtteranceCollector(context.sampleRate, 12), transcriptId: `initial-${crypto.randomUUID()}`, delivered: false, pre: [], preSamples: 0 };
      if (backgroundAsr) {
        s.collector = new UtteranceCollector(context.sampleRate);
        s.observer = new UtteranceObserver(async (utterance, signal) => {
          const response = await fetch('/api/avatar/transcribe', {
            method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
            signal: AbortSignal.any([signal, s.abort.signal, AbortSignal.timeout(45000)]),
            body: JSON.stringify({ audio: base64Bytes(wavFromPcm(utterance.chunks, utterance.sampleRate)), format: 'wav' }),
          });
          if (!response.ok) { await response.body?.cancel().catch(() => {}); throw new Error('Background observation unavailable.'); }
          const body = await response.json();
          if (typeof body?.text !== 'string' || body.text.length > 8000) throw new Error('Invalid background observation.');
          return body.text;
        }, text => {
          if (current(s) && s.taskHold?.stage !== 'working' && !s.muted && !opts.current.observerPaused) opts.current.onObservedTranscript?.(`observed-${crypto.randomUUID()}`, text);
        }, () => { if (current(s) && s.taskHold?.stage !== 'working' && !s.muted && !opts.current.observerPaused) opts.current.onObserverError?.(); });
      }
      capture.port.onmessage = (event: MessageEvent<Float32Array>) => {
        if (!current(s) || !(event.data instanceof Float32Array) || !s.ready && !s.initial) return;
        // The model clock must continue when the microphone is muted.
        const pcm = s.muted ? new Float32Array(event.data.length) : event.data, duration = pcm.length / context.sampleRate;
        let power = 0; for (const sample of pcm) power += sample * sample;
        s.inputLevel = Math.min(1, Math.sqrt(power / Math.max(1, pcm.length)) * 5);
        const initial = s.initial;
        if (initial?.stage === 'capture') {
          const utterance = initial.collector.push(pcm, s.inputLevel > .065);
          if (utterance) {
            if (utterance.capped) { fail.current('Start with one shorter thought, then we can keep talking.'); return; }
            const wav = wavFromPcm(utterance.chunks, utterance.sampleRate, PCM_RATE);
            utterance.chunks.forEach(chunk => chunk.fill(0));
            initial.captured = new Pcm16Stream().decode(wav.subarray(44)); initial.stage = 'preparing';
            initial.collector.reset(); setInitialListening(false); setPhase('thinking');
            initial.complete?.(wav); initial.complete = undefined;
          }
          return;
        }
        if (initial && initial.stage !== 'live') {
          initial.pre.push(pcm.slice()); initial.preSamples += pcm.length;
          const maximum = Math.ceil(context.sampleRate * .2);
          while (initial.preSamples > maximum) {
            const first = initial.pre[0], excess = initial.preSamples - maximum;
            if (first.length <= excess) { initial.pre.shift(); initial.preSamples -= first.length; }
            else { initial.pre[0] = first.slice(excess); initial.preSamples -= excess; }
          }
        }
        if (s.inputLevel > .065) {
          s.voiced += duration; s.quiet = 0;
          if (!s.userActive && s.voiced >= .08) {
            if (initial?.stage === 'preparing') { fail.current('The first request was interrupted while connecting. Start voice again when you are ready.'); return; }
            s.userActive = true; s.turn++;
            const hold = s.taskHold;
            if (!hold) stopSpeech(s, false);
            else if (hold.stage === 'awaiting-user' && s.turn > hold.afterTurn && !opts.current.observerPaused) {
              hold.eligibleTurn = s.turn;
              stopSpeech(s, false);
            }
            // During work/sign-in, input keeps clocking without redundant interrupts.
            if (initial?.stage === 'replay') {
              const wav = wavFromPcm(initial.pre, context.sampleRate, PCM_RATE);
              initial.replay?.handoffToLive(new Pcm16Stream().decode(wav.subarray(44)));
              return; // The handoff already sent this onset in its bounded preroll.
            }
          }
        } else {
          s.voiced = 0; s.quiet += duration;
          if (s.userActive && s.quiet >= .5) {
            s.userActive = false; resumeAfterHold(s);
            opts.current.onUserUtterance?.();
          }
        }
        if (!s.ready || initial?.stage === 'replay') return;
        const pcmBytes = s.resampler!.encode(pcm); if (pcmBytes.length) send(s, capturePacket(pcmBytes));
        if (current(s) && s.taskHold?.stage !== 'working' && s.collector && s.observer && opts.current.backgroundAsr && !s.muted && !opts.current.observerPaused) {
          const utterance = s.collector.push(pcm, s.inputLevel > .065);
          if (utterance) s.observer.offer(utterance);
        }
      };
      const meter = new Float32Array(analyser.fftSize); let sampledAt = 0;
      const measure = (time: number) => {
        if (!current(s)) return;
        if (time - sampledAt >= 50) {
          analyser.getFloatTimeDomainData(meter); let power = 0; for (const value of meter) power += value * value;
          const outputLevel = s.taskHold || s.held || s.userActive ? 0 : Math.min(1, Math.sqrt(power / meter.length) * 5);
          setPhase(s.ready ? outputLevel > .045 ? 'speaking' : 'listening' : s.initial?.stage === 'capture' ? 'listening' : s.initial?.stage === 'preparing' ? 'thinking' : 'idle'); setAudioLevel(outputLevel || (s.muted ? 0 : s.inputLevel)); sampledAt = time;
        }
        s.raf = requestAnimationFrame(measure);
      };
      s.raf = requestAnimationFrame(measure);
      let admissionBody: object = { avatar };
      if (s.initial) {
        setInitialListening(true);
        const wav = await new Promise<Uint8Array>((resolve, reject) => {
          s.initial!.complete = resolve;
          s.abort.signal.addEventListener('abort', () => reject(new DOMException('Stopped', 'AbortError')), { once: true });
          s.timer = setTimeout(() => { if (current(s)) fail.current('The listening window ended. Start voice again when you are ready.'); }, 30000);
        });
        if (!current(s)) return;
        clearTimeout(s.timer); admissionBody = { audio: base64Bytes(wav), format: 'wav' }; wav.fill(0);
      }
      const response = await fetch(initialRole ? '/api/avatar/personaplex-initial' : '/api/avatar/personaplex-session', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(admissionBody), signal: AbortSignal.any([s.abort.signal, AbortSignal.timeout(initialRole ? 65000 : 15000)]) });
      admissionBody = {};
      if (!current(s)) return;
      if (!response.ok) throw new Error('The native voice worker is not ready. Use the world preview while it warms up.');
      const body = await response.json().catch(() => { throw new Error('Invalid native voice admission.'); }); if (!current(s)) return;
      if (s.initial) {
        if (!['moss', 'orbit', 'spark'].includes(body.avatar) || typeof body.transcript !== 'string' || !body.transcript.trim() || body.transcript.length > 8000 || body.initialContextDelivered !== false) throw new Error('Invalid initial character selection.');
      }
      const expires = Date.parse(body.expiresAt);
      if (body.protocol !== PERSONAPLEX_PROTOCOL || body.streamPath !== '/api/avatar/personaplex' || body.inputSampleRate !== PCM_RATE || body.outputSampleRate !== PCM_RATE || typeof body.ticket !== 'string' || !/^[A-Za-z0-9_-]{32,128}$/.test(body.ticket) || !Number.isFinite(expires) || expires <= Date.now() || expires > Date.now() + 30000) throw new Error('Invalid native voice admission.');
      if (s.initial) { s.initial.text = body.transcript; setVoiceAvatar(body.avatar); opts.current.onInitialSelection?.(body.avatar); }
      else setVoiceAvatar(avatar);
      const url = new URL('/api/avatar/personaplex', window.location.href); url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'; url.searchParams.set('ticket', body.ticket);
      const ws = new WebSocket(url); s.ws = ws; ws.binaryType = 'arraybuffer';
      s.timer = setTimeout(() => { if (current(s) && !s.ready) fail.current('The native voice worker did not finish connecting. Reconnect to try again.'); }, Math.max(1, expires - Date.now()));
      s.expiry = setTimeout(() => { if (current(s)) fail.current('The native voice session reached its time limit. Reconnect to continue.'); }, 600000);
      ws.onmessage = event => {
        s.messages = s.messages.then(async () => {
          if (!current(s)) return;
          const value = event.data instanceof Blob ? await event.data.arrayBuffer() : event.data;
          if (!current(s)) return;
          if (value instanceof ArrayBuffer) { if (!s.ready) throw new Error('audio before readiness'); handleAudio(s, value); }
          else if (typeof value === 'string' && value.length <= 12000) {
            const parsed = JSON.parse(value); if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('control'); handleControl(s, parsed);
          } else throw new Error('message');
        }).catch(() => { if (current(s)) fail.current('The native voice stream could not continue. Reconnect to try again.'); });
      };
      ws.onerror = () => { if (current(s)) fail.current('The native voice worker could not connect.'); };
      ws.onclose = () => { if (current(s)) fail.current('The native voice session ended. Reconnect to continue.'); };
    } catch (e) {
      if (current(s)) fail.current(e instanceof DOMException && e.name === 'NotAllowedError' ? 'Microphone permission was declined. Allow access and reconnect, or use the silent preview.' : e instanceof Error ? e.message : 'The native voice worker could not connect.');
    }
  }, [current, handleAudio, handleControl, resumeAfterHold, send, stopSpeech]);
  const interrupt = useCallback(() => {
    const s = session.current;
    if (s?.initial && s.initial.stage !== 'live') {
      if (!s.ready) { disconnect(); return; }
      s.initial.replay?.handoffToLive(new Float32Array());
    }
    if (s?.ready) stopSpeech(s, true);
  }, [disconnect, stopSpeech]);
  const resetObserver = useCallback(() => {
    const s = session.current; s?.collector?.reset(); s?.observer?.invalidate();
    if (s?.initial && s.initial.stage !== 'live') disconnect();
  }, [disconnect]);
  const beginTaskHold = useCallback(() => {
    const s = session.current; if (!s?.ready || s.taskHold?.stage === 'working') return undefined;
    const owner = Symbol('native-task-hold');
    s.taskHold = { owner, stage: 'working', afterTurn: s.turn };
    s.collector?.reset(); s.observer?.invalidate();
    stopSpeech(s, s.manualStop);
    if (!current(s)) return undefined;
    return () => {
      const hold = s.taskHold;
      if (!current(s) || hold?.owner !== owner || hold.stage !== 'working') return;
      hold.stage = 'awaiting-user'; hold.afterTurn = s.turn; hold.eligibleTurn = undefined;
      s.held = true; clearPlayback(s);
      // Completion never releases output or counts an already-active user turn.
    };
  }, [clearPlayback, current, stopSpeech]);
  const toggleMute = useCallback(() => {
    const s = session.current; if (!s) return;
    if (!s.ready) { disconnect(); return; }
    s.muted = !s.muted; s.stream?.getAudioTracks().forEach(track => { track.enabled = !s.muted; });
    if (s.muted && s.initial?.stage === 'replay') s.initial.replay?.handoffToLive(new Float32Array());
    s.collector?.reset(); s.observer?.invalidate();
    if (s.taskHold) s.taskHold.eligibleTurn = undefined;
    s.inputLevel = 0; s.voiced = 0; s.quiet = 0; s.userActive = false; setMuted(s.muted);
    if (!s.taskHold && !s.interruptId && !s.manualStop) s.held = false;
  }, [disconnect]);
  useEffect(() => {
    if (options.observerPaused || !options.backgroundAsr) resetObserver();
    if (options.observerPaused && session.current?.taskHold) session.current.taskHold.eligibleTurn = undefined;
  }, [options.observerPaused, options.backgroundAsr, resetObserver]);
  useEffect(() => {
    const s = session.current, initial = s?.initial;
    if (connected && s && current(s) && initial?.text && !initial.delivered) {
      initial.delivered = true;
      opts.current.onInitialTranscript?.(initial.transcriptId, initial.text);
      initial.text = undefined;
    }
  }, [connected, current]);
  useEffect(() => () => disconnect(), [disconnect]);
  return { connected, connecting, phase, muted, audioLevel, error, initialListening, voiceAvatar, connect, disconnect, interrupt, toggleMute, resetObserver, beginTaskHold,
    // Stock native model has no text-input or live-persona API. Keep typed fallback honest.
    sendText: (_text: string) => false, setPersona: (_avatar: AvatarId) => false, clearError: () => setError('') };
}
