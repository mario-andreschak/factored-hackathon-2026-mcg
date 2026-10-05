import { useCallback, useEffect, useRef, useState } from 'react';
import { base64Bytes, Pcm16Resampler, Pcm16Stream } from './audio';
import type { AvatarId, Phase } from './domain';
import type { TaskReply } from './useVoice';
import { normalizeLocale, type Locale } from './locale';
import { voiceCopy, voiceError, VoiceLocaleError, voicePersona, voiceResponseError } from './voiceLocale';

interface Options {
  avatar: AvatarId;
  locale?: Locale;
  onTranscript: (id: string, role: 'user' | 'assistant', text: string, done: boolean) => void;
  onWorld: (avatar: AvatarId, scene: number) => void;
  onTask: (message: string) => Promise<TaskReply>;
}
interface Caption { id: string; text: string; done: boolean; interim?: boolean; }
interface FunctionResponse {
  id: string; name: string; response: Record<string, unknown>; scheduling: 'WHEN_IDLE' | 'SILENT';
}
interface LiveSession {
  abort: AbortController; ready: boolean; muted: boolean; ws?: WebSocket;
  context?: AudioContext; stream?: MediaStream; input?: MediaStreamAudioSourceNode;
  capture?: AudioWorkletNode; gain?: GainNode; analyser?: AnalyserNode;
  setupTimer?: ReturnType<typeof setTimeout>; expiryTimer?: ReturnType<typeof setTimeout>;
  resultTimer?: ReturnType<typeof setTimeout>; raf?: number;
  decoder: Pcm16Stream; resampler?: Pcm16Resampler; playback: Set<AudioBufferSourceNode>;
  scheduled: number; outputGeneration: number; suppressOutput: boolean; modelBusy: boolean;
  userActive: boolean; nativeActivity: boolean; voiced: number; quiet: number; inputLevel: number;
  inputCaption?: Caption; outputCaption?: Caption; typedEcho?: string;
  calls: Set<string>; canceled: Set<string>; pending: FunctionResponse[];
  messages: Promise<void>;
}
interface ServerContent {
  interrupted?: boolean; turnComplete?: boolean; generationComplete?: boolean; waitingForInput?: boolean;
  interactionStatus?: string;
  inputTranscription?: { text?: string; finished?: boolean };
  interimInputTranscription?: { text?: string; finished?: boolean };
  outputTranscription?: { text?: string; finished?: boolean };
  modelTurn?: { parts?: { inlineData?: { data?: string; mimeType?: string }; text?: string; thought?: boolean }[] };
}
interface ServerMessage {
  setupComplete?: object; serverContent?: ServerContent;
  voiceActivity?: { voiceActivityType?: string };
  toolCall?: { functionCalls?: { id?: string; name?: string; args?: Record<string, unknown> }[] };
  toolCallCancellation?: { ids?: string[] };
  goAway?: { timeLeft?: string }; error?: unknown;
}

const LIVE_ENDPOINT = 'wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained';
const isAvatar = (value: unknown): value is AvatarId => value === 'moss' || value === 'orbit' || value === 'spark';

/** Native full-duplex audio. The permanent API key never enters the browser. */
export function useGeminiLive(options: Options) {
  const opts = useRef(options); opts.current = options;
  const session = useRef<LiveSession | null>(null);
  const [connected, setConnected] = useState(false), [connecting, setConnecting] = useState(false);
  const [phase, setPhase] = useState<Phase>('idle'), [muted, setMuted] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0), [error, setError] = useState('');
  const fail = useRef<(message: string) => void>(() => {});
  const drain = useRef<(s: LiveSession) => void>(() => {});
  const current = useCallback((s: LiveSession) => session.current === s && !s.abort.signal.aborted, []);

  const completeCaption = useCallback((s: LiveSession, role: 'user' | 'assistant') => {
    if (!current(s)) return;
    const caption = role === 'user' ? s.inputCaption : s.outputCaption;
    if (caption && !caption.done && caption.text.trim()) {
      caption.done = true; opts.current.onTranscript(caption.id, role, caption.text, true);
    }
  }, [current]);
  const stopOutput = useCallback((s: LiveSession) => {
    s.outputGeneration++;
    for (const source of s.playback) {
      source.onended = null; try { source.stop(); } catch { /* already ended */ } source.disconnect();
    }
    s.playback.clear(); s.decoder = new Pcm16Stream(); s.scheduled = 0;
    completeCaption(s, 'assistant'); setAudioLevel(0);
  }, [completeCaption]);
  const disconnect = useCallback(() => {
    const old = session.current; session.current = null;
    if (old) {
      old.abort.abort(); clearTimeout(old.setupTimer); clearTimeout(old.expiryTimer); clearTimeout(old.resultTimer);
      if (old.raf !== undefined) cancelAnimationFrame(old.raf);
      stopOutput(old);
      if (old.ws) {
        old.ws.onopen = null; old.ws.onmessage = null; old.ws.onerror = null; old.ws.onclose = null;
        try { old.ws.close(1000); } catch { /* opening socket */ }
      }
      if (old.capture) { old.capture.port.onmessage = null; old.capture.disconnect(); }
      old.input?.disconnect(); old.gain?.disconnect(); old.analyser?.disconnect();
      old.stream?.getTracks().forEach(track => track.stop());
      void old.context?.close().catch(() => {});
      old.pending = []; old.calls.clear(); old.canceled.clear();
    }
    setConnected(false); setConnecting(false); setMuted(false); setAudioLevel(0); setPhase('idle');
  }, [stopOutput]);
  fail.current = (message: string) => { disconnect(); setError(message); };

  const send = useCallback((s: LiveSession, event: object, requireReady = true) => {
    if (!current(s) || (requireReady && !s.ready) || s.ws?.readyState !== WebSocket.OPEN) return false;
    // Never upload seconds-old microphone audio after a network stall.
    if (s.ws.bufferedAmount > 256_000) { fail.current(voiceCopy(opts.current.locale).connectionBehind); return false; }
    try { s.ws.send(JSON.stringify(event)); return true; }
    catch { fail.current(voiceCopy(opts.current.locale).connectionEnded); return false; }
  }, [current]);
  drain.current = s => {
    if (!current(s) || !s.ready || s.userActive || s.playback.size || !s.pending.length) return;
    const responses = s.pending.splice(0).filter(response => !s.canceled.has(response.id));
    if (responses.length && send(s, { toolResponse: { functionResponses: responses } })) {
      s.modelBusy = true; setPhase('thinking');
    }
  };
  const refreshPhase = useCallback((s: LiveSession) => {
    if (!current(s) || !s.ready) return;
    setPhase(s.userActive ? 'listening' : s.playback.size ? 'speaking' : s.modelBusy ? 'thinking' : 'listening');
  }, [current]);
  const beginUser = useCallback((s: LiveSession) => {
    if (s.userActive) return;
    s.userActive = true; s.modelBusy = false; s.typedEcho = undefined;
    if (s.inputCaption?.done) s.inputCaption = undefined;
    if (s.playback.size) { stopOutput(s); s.suppressOutput = true; }
    refreshPhase(s);
  }, [refreshPhase, stopOutput]);
  const caption = useCallback((s: LiveSession, role: 'user' | 'assistant', text: string, finished = false, interim = false) => {
    if (!text && !finished) return;
    if (role === 'user' && s.typedEcho === text.trim()) { s.typedEcho = undefined; return; }
    let value = role === 'user' ? s.inputCaption : s.outputCaption;
    if (!value || value.done) {
      value = { id: crypto.randomUUID(), text: '', done: false };
      if (role === 'user') s.inputCaption = value; else s.outputCaption = value;
    }
    // Interim hypotheses replace each other. Final/native transcript deltas accumulate.
    value.text = (interim || value.interim ? text : value.text + text).slice(-8000);
    value.interim = interim;
    value.done ||= finished;
    opts.current.onTranscript(value.id, role, value.text, value.done);
  }, []);

  const play = useCallback((s: LiveSession, data: string, mimeType: string) => {
    if (!current(s) || s.suppressOutput || !s.context || !s.analyser) return;
    if (!/^audio\/pcm(?:;|$)/i.test(mimeType) || !/(?:^|;)\s*rate=24000(?:;|$)/i.test(mimeType)) throw new Error('format');
    if (data.length > 2_000_000) throw new Error('limit');
    const binary = atob(data), bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index++) bytes[index] = binary.charCodeAt(index);
    const pcm = s.decoder.decode(bytes); if (!pcm.length) return;
    const context = s.context;
    const buffer = context.createBuffer(1, pcm.length, 24000); buffer.getChannelData(0).set(pcm);
    if (s.scheduled - context.currentTime + buffer.duration > 30) throw new Error('limit');
    const source = context.createBufferSource(), outputGeneration = s.outputGeneration;
    source.buffer = buffer; source.connect(s.analyser);
    s.scheduled = Math.max(s.scheduled, context.currentTime + .025);
    s.playback.add(source); source.start(s.scheduled); s.scheduled += buffer.duration;
    source.onended = () => {
      source.disconnect();
      if (!current(s) || outputGeneration !== s.outputGeneration) return;
      s.playback.delete(source); refreshPhase(s); drain.current(s);
    };
    s.modelBusy = true; refreshPhase(s);
  }, [current, refreshPhase]);

  const tools = useCallback((s: LiveSession, calls: NonNullable<ServerMessage['toolCall']>['functionCalls']) => {
    for (const call of calls ?? []) {
      if (typeof call.id !== 'string' || !call.id || call.id.length > 256 || typeof call.name !== 'string' || s.calls.has(call.id) || s.canceled.has(call.id)) continue;
      const { id, name } = call; s.calls.add(id);
      const args = call.args && typeof call.args === 'object' && !Array.isArray(call.args) ? call.args : {};
      if (name === 'set_world') {
        let response: Record<string, unknown>;
        if (isAvatar(args.avatar) && Number.isInteger(args.sceneIndex) && Number(args.sceneIndex) >= 0 && Number(args.sceneIndex) < 10) {
          opts.current.onWorld(args.avatar, Number(args.sceneIndex)); response = { applied: true, avatar: args.avatar, sceneIndex: args.sceneIndex };
        } else response = { error: voiceCopy(opts.current.locale).invalidWorld };
        send(s, { toolResponse: { functionResponses: [{ id, name, response, scheduling: 'SILENT' }] } });
        continue;
      }
      if (name !== 'delegate_task' || typeof args.message !== 'string' || !args.message.trim() || args.message.length > 2000) {
        send(s, { toolResponse: { functionResponses: [{ id, name, response: { error: voiceCopy(opts.current.locale).invalidTask }, scheduling: 'WHEN_IDLE' }] } }); continue;
      }
      // Once admitted, this read belongs to the task UI, independently of live speech.
      const message = args.message;
      const taskHandler = opts.current.onTask;
      let admitted: Promise<TaskReply>;
      try { admitted = Promise.resolve(taskHandler(message)); } catch (e) { admitted = Promise.reject(e); }
      void admitted.then(reply => ({
        reply: String(reply.reply ?? '').slice(0, 8000),
        ...(reply.mode === 'flujo' ? { mode: 'flujo' } : {}),
        ...(['completed', 'waiting_for_input'].includes(reply.status ?? '') ? { status: reply.status } : {}),
      })).catch(() => ({ error: voiceCopy(opts.current.locale).taskFailed })).then(response => {
        // Cancellation prevents a stale tool response, but never cancels the admitted read.
        if (!current(s) || s.canceled.has(id)) return;
        s.pending.push({ id, name, response, scheduling: 'WHEN_IDLE' }); drain.current(s);
      });
    }
  }, [current, send]);

  const handleMessage = useCallback((s: LiveSession, event: ServerMessage) => {
    if (!current(s)) return;
    if (event.error) { fail.current(voiceCopy(opts.current.locale).providerFailed); return; }
    if (event.setupComplete) {
      if (s.ready) return;
      clearTimeout(s.setupTimer); s.ready = true;
      setConnected(true); setConnecting(false); setPhase('listening');
    }
    if (event.goAway) { fail.current(voiceCopy(opts.current.locale).sessionEnding); return; }
    for (const id of event.toolCallCancellation?.ids ?? []) {
      s.canceled.add(id); s.pending = s.pending.filter(response => response.id !== id);
    }
    if (event.voiceActivity?.voiceActivityType === 'ACTIVITY_START') {
      s.nativeActivity = true; beginUser(s);
    } else if (event.voiceActivity?.voiceActivityType === 'ACTIVITY_END') {
      s.nativeActivity = false; s.userActive = false; s.modelBusy = true; refreshPhase(s);
    }
    const content = event.serverContent;
    if (content) {
      if (content.interrupted) {
        stopOutput(s); s.suppressOutput = false; s.modelBusy = false; refreshPhase(s);
      }
      if (content.interimInputTranscription && !content.inputTranscription) {
        const input = content.interimInputTranscription;
        caption(s, 'user', input.text ?? '', input.finished, true);
      }
      if (content.inputTranscription) {
        const input = content.inputTranscription;
        caption(s, 'user', input.text ?? '', input.finished);
        if (input.finished) { s.userActive = false; s.nativeActivity = false; s.modelBusy = true; }
      }
      if (content.outputTranscription && !s.suppressOutput) {
        caption(s, 'assistant', content.outputTranscription.text ?? '', content.outputTranscription.finished);
      }
      if (content.modelTurn?.parts?.length) {
        completeCaption(s, 'user');
        for (const part of content.modelTurn.parts) if (part.inlineData?.data) play(s, part.inlineData.data, part.inlineData.mimeType ?? '');
      }
      if (content.generationComplete) { s.decoder.finish(); completeCaption(s, 'assistant'); }
      if (content.turnComplete) {
        s.decoder.finish(); s.suppressOutput = false;
        s.modelBusy = content.interactionStatus === 'IN_PROGRESS';
        completeCaption(s, 'user'); completeCaption(s, 'assistant');
      }
      if (content.waitingForInput) s.modelBusy = false;
      refreshPhase(s);
    }
    if (event.toolCall) tools(s, event.toolCall.functionCalls);
    drain.current(s);
  }, [beginUser, caption, completeCaption, current, play, refreshPhase, stopOutput, tools]);

  const connect = useCallback(async () => {
    if (session.current) return;
    setConnecting(true); setError('');
    const s: LiveSession = {
      abort: new AbortController(), ready: false, muted: false, decoder: new Pcm16Stream(), playback: new Set(),
      scheduled: 0, outputGeneration: 0, suppressOutput: false, modelBusy: false, userActive: false,
      nativeActivity: false, voiced: 0, quiet: 0, inputLevel: 0, calls: new Set(), canceled: new Set(), pending: [], messages: Promise.resolve(),
    };
    session.current = s;
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode || !window.WebSocket) throw new VoiceLocaleError('browserRequired');
      const context = new AudioContext(); s.context = context; await context.resume();
      if (!current(s)) return;
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      if (!current(s)) { stream.getTracks().forEach(track => track.stop()); return; }
      s.stream = stream;
      await context.audioWorklet.addModule(`${import.meta.env.BASE_URL}audio-capture.js`);
      if (!current(s)) return;
      const analyser = context.createAnalyser(); analyser.fftSize = 256; analyser.smoothingTimeConstant = .2;
      analyser.connect(context.destination); s.analyser = analyser;
      const input = context.createMediaStreamSource(stream), capture = new AudioWorkletNode(context, 'voice-capture');
      const gain = context.createGain(); gain.gain.value = 0;
      input.connect(capture); capture.connect(gain); gain.connect(context.destination);
      s.input = input; s.capture = capture; s.gain = gain; s.resampler = new Pcm16Resampler(context.sampleRate);
      capture.port.onmessage = (event: MessageEvent<Float32Array>) => {
        if (!current(s) || !s.ready || s.muted || !(event.data instanceof Float32Array)) return;
        const pcm = event.data, duration = pcm.length / context.sampleRate;
        let power = 0; for (const sample of pcm) power += sample * sample;
        s.inputLevel = Math.min(1, Math.sqrt(power / Math.max(1, pcm.length)) * 5);
        // This local envelope only drives presentation/result timing. Gemini owns VAD.
        if (s.inputLevel > .065) {
          s.voiced += duration; s.quiet = 0;
          if (s.voiced >= .08) beginUser(s);
        } else {
          s.voiced = 0; s.quiet += duration;
          if (s.userActive && !s.nativeActivity && s.quiet >= .5) {
            s.userActive = false; s.modelBusy = true; refreshPhase(s); drain.current(s);
          }
        }
        const bytes = s.resampler!.encode(pcm);
        if (bytes.length) send(s, { realtimeInput: { audio: { data: base64Bytes(bytes), mimeType: 'audio/pcm;rate=16000' } } });
      };
      // Mint only after microphone permission, so the one-use token cannot expire in its prompt.
      const response = await fetch('/api/avatar/gemini-token', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ avatar: opts.current.avatar, locale: normalizeLocale(opts.current.locale) }),
        signal: AbortSignal.any([s.abort.signal, AbortSignal.timeout(20_000)]),
      });
      if (!current(s)) return;
      if (!response.ok) {
        throw await voiceResponseError(response);
      }
      const body = await response.json(); if (!current(s)) return;
      if (typeof body.token !== 'string' || !body.token || body.token.length > 16384 || typeof body.model !== 'string' || !/^gemini-[A-Za-z0-9._-]{1,100}$/.test(body.model) || body.setup?.model !== `models/${body.model}`) throw new VoiceLocaleError('configurationInvalid');
      const newSessionExpiry = Date.parse(body.newSessionExpiresAt);
      if (Number.isFinite(newSessionExpiry) && newSessionExpiry <= Date.now()) throw new VoiceLocaleError('tokenExpired');
      // The token is permitted to go only to Google's fixed, constrained endpoint.
      const ws = new WebSocket(`${LIVE_ENDPOINT}?access_token=${encodeURIComponent(body.token)}`); s.ws = ws; ws.binaryType = 'arraybuffer';
      s.setupTimer = setTimeout(() => { if (current(s) && !s.ready) fail.current(voiceCopy(opts.current.locale).setupTimeout); }, 20_000);
      const expiry = Date.parse(body.expiresAt);
      if (Number.isFinite(expiry)) s.expiryTimer = setTimeout(() => { if (current(s)) fail.current(voiceCopy(opts.current.locale).sessionExpired); }, Math.max(0, expiry - Date.now()));
      ws.onopen = () => { send(s, { setup: { model: body.setup.model } }, false); };
      ws.onmessage = event => {
        // Blob decoding is async: serialize messages to preserve interruption ordering.
        s.messages = s.messages.then(async () => {
          if (!current(s)) return;
          const raw = typeof event.data === 'string' ? event.data : event.data instanceof Blob ? await event.data.text() : event.data instanceof ArrayBuffer ? new TextDecoder('utf-8', { fatal: true }).decode(event.data) : '';
          if (!current(s)) return;
          if (!raw || raw.length > 2_500_000) throw new Error('message');
          const message: unknown = JSON.parse(raw);
          if (!message || typeof message !== 'object' || Array.isArray(message)) throw new Error('message');
          handleMessage(s, message as ServerMessage);
        }).catch(() => { if (current(s)) fail.current(voiceCopy(opts.current.locale).streamFailed); });
      };
      ws.onerror = () => { if (current(s)) fail.current(voiceCopy(opts.current.locale).connectionFailed); };
      ws.onclose = () => { if (current(s)) fail.current(voiceCopy(opts.current.locale).connectionEnded); };
      const meter = new Float32Array(analyser.fftSize); let lastSample = 0;
      const measure = (time: number) => {
        if (!current(s)) return;
        if (time - lastSample >= 50) {
          if (s.playback.size && !s.userActive) {
            analyser.getFloatTimeDomainData(meter);
            let power = 0; for (const value of meter) power += value * value;
            setAudioLevel(Math.min(1, Math.sqrt(power / meter.length) * 5));
          } else setAudioLevel(s.muted ? 0 : s.inputLevel);
          lastSample = time;
        }
        s.raf = requestAnimationFrame(measure);
      };
      s.raf = requestAnimationFrame(measure);
    } catch (e) {
      if (!current(s)) return;
      const message = e instanceof DOMException && e.name === 'NotAllowedError'
        ? voiceCopy(opts.current.locale).microphoneDenied
        : voiceError(opts.current.locale, e);
      fail.current(message);
    }
  }, [beginUser, current, handleMessage, refreshPhase, send]);

  const interrupt = useCallback(() => {
    const s = session.current; if (!s?.ready) return;
    stopOutput(s); s.suppressOutput = true; s.modelBusy = false;
    // clientContent interrupts generation; automatic VAD forbids activityStart/End.
    send(s, { clientContent: { turnComplete: false } }); refreshPhase(s);
  }, [refreshPhase, send, stopOutput]);
  const toggleMute = useCallback(() => {
    const s = session.current; if (!s?.ready) return;
    s.muted = !s.muted; s.stream?.getAudioTracks().forEach(track => { track.enabled = !s.muted; });
    s.resampler?.reset(); s.inputLevel = 0; s.voiced = 0; s.quiet = 0;
    if (s.muted) {
      send(s, { realtimeInput: { audioStreamEnd: true } });
      s.nativeActivity = false; s.userActive = false; drain.current(s);
    }
    setMuted(s.muted); refreshPhase(s);
  }, [refreshPhase, send]);
  const sendText = useCallback((text: string) => {
    const s = session.current; if (!s?.ready) return false;
    const value = text.trim();
    if (!value || value.length > 4000) { setError(voiceCopy(opts.current.locale).messageTooLong); return false; }
    stopOutput(s); s.suppressOutput = false; s.userActive = false; s.nativeActivity = false; s.modelBusy = true;
    s.inputCaption = { id: crypto.randomUUID(), text: value, done: true }; s.typedEcho = value;
    opts.current.onTranscript(s.inputCaption.id, 'user', value, true);
    const sent = send(s, { realtimeInput: { text: value } }); refreshPhase(s); return sent;
  }, [refreshPhase, send, stopOutput]);
  const setPersona = useCallback((avatar: AvatarId) => {
    const s = session.current;
    // Delivery is a live conversational preference; the pinned voice remains unchanged.
    if (s?.ready && isAvatar(avatar)) send(s, { realtimeInput: { text: voicePersona(avatar, opts.current.locale) } });
  }, [send]);
  useEffect(() => () => disconnect(), [disconnect]);
  return { phase, connected, connecting, muted, audioLevel, error, connect, disconnect, interrupt, toggleMute, sendText, setPersona, clearError: () => setError('') };
}
