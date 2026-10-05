import { useCallback, useEffect, useRef, useState } from 'react';
import type { AvatarId, Phase } from './domain';
import type { TaskReply } from './useVoice';
import { base64Bytes, boundedVoiceHistory, Pcm16Stream, readNdjson, speechSentences, splitSpeechText, wavFromPcm } from './audio';
import { normalizeLocale, type Locale } from './locale';
import { voiceCopy, voiceError, VoiceLocaleError, voiceResponseError } from './voiceLocale';

interface Options {
  avatar: AvatarId;
  locale?: Locale;
  onTranscript: (id: string, role: 'user' | 'assistant', text: string, done: boolean) => void;
  onWorld: (avatar: AvatarId, scene: number) => void;
  onTask: (message: string) => Promise<TaskReply>;
}
interface SpeechResources {
  context?: AudioContext; stream?: MediaStream; capture?: AudioWorkletNode; gain?: GainNode; analyser?: AnalyserNode;
  playback: Set<AudioBufferSourceNode>; aborts: Set<AbortController>; muted: boolean;
}
type HistoryItem = { role: 'user' | 'assistant'; content: string };
export function useRouterVoice(options: Options) {
  const opts = useRef(options); opts.current = options;
  const [connected, setConnected] = useState(false), [connecting, setConnecting] = useState(false);
  const [phase, setPhase] = useState<Phase>('idle'), [muted, setMuted] = useState(false), [error, setError] = useState(''), [audioLevel, setAudioLevel] = useState(0);
  const life = useRef(0), turn = useRef(0);
  const r = useRef<SpeechResources>({ playback: new Set(), aborts: new Set(), muted: false });
  const history = useRef<HistoryItem[]>([]);
  const activeTasks = useRef(new Set<string>());
  const speaking = useRef(false);
  const capturing = useRef(false);
  const conversations = useRef(new Set<AbortController>());
  const transcriptions = useRef(new Set<AbortController>());
  const finalizing = useRef(new Set<symbol>());
  const pendingResults = useRef<{ gen: number; reply: TaskReply }[]>([]);
  const drainResults = useRef<() => void>(() => {});
  const resetRef = useRef<() => void>(() => {});
  const interrupt = useCallback(() => {
    turn.current++; speaking.current = false;
    for (const source of r.current.playback) { try { source.stop(); } catch { /* already finished */ } }
    r.current.playback.clear();
    for (const abort of r.current.aborts) abort.abort(); r.current.aborts.clear();
    setPhase(r.current.stream ? 'listening' : 'idle'); setAudioLevel(0);
  }, []);
  const disconnect = useCallback(() => {
    life.current++; interrupt(); resetRef.current();
    const old = r.current; r.current = { playback: new Set(), aborts: new Set(), muted: false };
    old.stream?.getTracks().forEach(track => track.stop()); old.capture?.disconnect(); void old.context?.close();
    history.current = []; activeTasks.current.clear();
    conversations.current.clear(); transcriptions.current.clear(); finalizing.current.clear(); pendingResults.current = []; capturing.current = false;
    setConnected(false); setConnecting(false); setMuted(false); setPhase('idle'); setAudioLevel(0);
  }, [interrupt]);
  const request = useCallback(async (path: string, body: object, signal: AbortSignal) => {
    const response = await fetch(`/api/avatar/${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...body, locale: normalizeLocale(opts.current.locale) }), signal });
    if (!response.ok) throw await voiceResponseError(response);
    return response;
  }, []);
  const speak = useCallback(async (text: string, gen: number, currentTurn: number, avatar: AvatarId) => {
    if (!text.trim() || gen !== life.current || currentTurn !== turn.current) return;
    const resources = r.current;
    const context = resources.context, analyser = resources.analyser; if (!context || !analyser) return;
    const abort = new AbortController(); resources.aborts.add(abort);
    let meter = 0;
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    let completed = false;
    const sources = new Set<AudioBufferSourceNode>();
    try {
      const response = await request('speech', { text, avatar }, abort.signal);
      if (gen !== life.current || currentTurn !== turn.current) { await response.body?.cancel(); return; }
      const sampleRate = Number(response.headers.get('X-Audio-Sample-Rate'));
      if (sampleRate !== 24000 || !response.body) throw new VoiceLocaleError('unsupportedAudio');
      reader = response.body.getReader(); const decoder = new Pcm16Stream(); let scheduled = context.currentTime + .08, samples = 0;
      speaking.current = true; setPhase('speaking');
      const meterPcm = new Float32Array(analyser.fftSize);
      const measure = () => {
        if (gen !== life.current || currentTurn !== turn.current) return;
        analyser.getFloatTimeDomainData(meterPcm);
        let power = 0; for (const sample of meterPcm) power += sample * sample;
        setAudioLevel(Math.min(1, Math.sqrt(power / meterPcm.length) * 5));
        meter = requestAnimationFrame(measure);
      };
      meter = requestAnimationFrame(measure);
      while (true) {
        const { value, done } = await reader.read();
        if (gen !== life.current || currentTurn !== turn.current) { await reader.cancel(); break; }
        if (value) {
          const pcm = decoder.decode(value);
          if (pcm.length) {
            samples += pcm.length;
            const buffer = context.createBuffer(1, pcm.length, sampleRate); buffer.getChannelData(0).set(pcm);
            const source = context.createBufferSource(); source.buffer = buffer; source.connect(analyser);
            scheduled = Math.max(scheduled, context.currentTime + .015); source.start(scheduled); scheduled += buffer.duration;
            resources.playback.add(source); sources.add(source); source.onended = () => { resources.playback.delete(source); sources.delete(source); source.disconnect(); };
          }
        }
        if (done) { decoder.finish(); if (!samples) throw new VoiceLocaleError('emptyAudio'); completed = true; break; }
      }
      while (context.currentTime < scheduled && gen === life.current && currentTurn === turn.current) await new Promise(resolve => setTimeout(resolve, 40));
    } finally {
      cancelAnimationFrame(meter);
      if (reader) { if (!completed) await reader.cancel().catch(() => {}); reader.releaseLock(); }
      if (!completed) for (const source of sources) { try { source.stop(); } catch { /* already finished */ } resources.playback.delete(source); source.disconnect(); }
      resources.aborts.delete(abort);
      if (gen === life.current && currentTurn === turn.current) { speaking.current = false; setPhase('listening'); setAudioLevel(0); }
    }
  }, [request]);

  const converse = useCallback(async (message: string, backendResult?: TaskReply, internal = false) => {
    const gen = life.current; if (!r.current.stream) return;
    if (!message.trim() || message.length > 4000) { if(!internal) interrupt(); setError(voiceCopy(opts.current.locale).messageTooLong); setPhase('listening'); return; }
    if (!internal) interrupt();
    const currentTurn = turn.current;
    const abort = new AbortController(); r.current.aborts.add(abort);
    conversations.current.add(abort);
    const id = crypto.randomUUID(); let text = '', speechPending = ''; let speechQueue = Promise.resolve();
    let turnAvatar=opts.current.avatar;
    const toolCalls: {name: string; args: Record<string, unknown>; id: string}[] = [];
    const previousHistory = boundedVoiceHistory(history.current);
    if (!internal) { opts.current.onTranscript(crypto.randomUUID(), 'user', message, true); history.current.push({ role: 'user', content: message }); }
    setPhase('thinking');
    const enqueueSpeech = (sentence: string) => {
      const speaker=turnAvatar;
      for(const chunk of splitSpeechText(sentence)) speechQueue = speechQueue.then(() => speak(chunk, gen, currentTurn, speaker));
      // Handle promptly so a stream still arriving cannot produce unhandled rejection.
      void speechQueue.catch(() => {});
    };
    try {
      const publicResult = backendResult ? {
        reply: backendResult.reply.slice(0,8000),
        ...(backendResult.mode==='flujo' ? {mode:'flujo'} : {}),
        ...(['completed','waiting_for_input'].includes(backendResult.status ?? '') ? {status:backendResult.status} : {}),
      } : undefined;
      const response = await request('conversation', { message, avatar: opts.current.avatar, history: previousHistory, ...(publicResult ? { backendResult: publicResult } : {}) }, abort.signal);
      await readNdjson(response, event => {
        if (gen !== life.current || currentTurn !== turn.current) return;
        if (event.type === 'error') throw new VoiceLocaleError('conversationEnded');
        if (event.type === 'text' && typeof event.delta === 'string') {
          text += event.delta; speechPending += event.delta; opts.current.onTranscript(id, 'assistant', text, false);
          const sentences = speechSentences(speechPending);
          for (const sentence of sentences.ready) enqueueSpeech(sentence);
          speechPending = sentences.pending;
        }
        if (event.type === 'tool' && typeof event.name === 'string' && event.args && typeof event.args === 'object') {
          const args=event.args as Record<string,unknown>;
          if(event.name==='set_world') {
            if(['moss','orbit','spark'].includes(String(args.avatar)) && Number.isInteger(args.sceneIndex) && Number(args.sceneIndex)>=0 && Number(args.sceneIndex)<=9) {
              turnAvatar=args.avatar as AvatarId; opts.current.onWorld(turnAvatar,Number(args.sceneIndex));
            }
          } else toolCalls.push({ name: event.name, args, id: typeof event.id==='string' ? event.id : crypto.randomUUID() });
        }
      });
      if (gen !== life.current || currentTurn !== turn.current) return;
      if (speechPending.trim()) enqueueSpeech(speechPending);
      if (text.trim()) { history.current.push({ role: 'assistant', content: text }); history.current = boundedVoiceHistory(history.current); opts.current.onTranscript(id, 'assistant', text, true); }
      for (const tool of toolCalls) {
        if (tool.name === 'delegate_task' && !backendResult && typeof tool.args.message === 'string' && tool.args.message.length <= 2000 && !activeTasks.current.has(`${gen}:${tool.id}`)) {
          const taskId=`${gen}:${tool.id}`; activeTasks.current.add(taskId);
          // An admitted read is never aborted by interruption of the voice stream.
          void opts.current.onTask(tool.args.message).then(result => {
            if (gen === life.current) { pendingResults.current.push({ gen, reply: result }); drainResults.current(); }
          }).catch(e => { if (gen === life.current) setError(voiceError(opts.current.locale, e, 'taskFailed')); }).finally(() => activeTasks.current.delete(taskId));
        }
      }
      await speechQueue;
      if (gen === life.current && currentTurn === turn.current && !speaking.current) setPhase('listening');
    } catch (e) {
      if (gen === life.current && currentTurn === turn.current && !abort.signal.aborted) { setError(voiceError(opts.current.locale, e)); setPhase('listening'); }
    } finally { r.current.aborts.delete(abort); conversations.current.delete(abort); drainResults.current(); }
  }, [interrupt, request, speak]);
  const converseResult = useRef(converse); converseResult.current = converse;
  drainResults.current = () => {
    if (!r.current.stream || conversations.current.size || transcriptions.current.size || finalizing.current.size || capturing.current || speaking.current) return;
    const result = pendingResults.current.shift();
    if (result?.gen === life.current) void converseResult.current(voiceCopy(opts.current.locale).resultInstruction, result.reply, true);
  };

  const connect = useCallback(async () => {
    if (r.current.stream) return;
    disconnect(); const gen = life.current; setConnecting(true); setError('');
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) throw new VoiceLocaleError('browserRequired');
      const context = new AudioContext(); r.current.context = context; await context.resume();
      const analyser = context.createAnalyser(); analyser.fftSize = 256; analyser.smoothingTimeConstant = .2; analyser.connect(context.destination); r.current.analyser = analyser;
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      if (gen !== life.current) { stream.getTracks().forEach(t => t.stop()); return; }
      r.current.stream = stream;
      await context.audioWorklet.addModule('/audio-capture.js');
      if (gen !== life.current) return;
      const capture = new AudioWorkletNode(context, 'voice-capture'); r.current.capture = capture;
      const silent = context.createGain(); silent.gain.value = 0; r.current.gain = silent;
      context.createMediaStreamSource(stream).connect(capture).connect(silent).connect(context.destination);
      let preRoll: Float32Array[] = [], utterance: Float32Array[] = [], segmentRequests: Promise<string>[] = [];
      let started = false, voiced = 0, silence = 0, speechFrames = 0, noise = .002, utteranceSamples = 0, captureTurn = 0;
      resetRef.current = () => { utterance = []; preRoll = []; segmentRequests = []; started = false; capturing.current = false; voiced = 0; silence = 0; speechFrames = 0; utteranceSamples = 0; };
      const transcribeSegment = (chunks: Float32Array[]) => {
        const abort = new AbortController(); r.current.aborts.add(abort); transcriptions.current.add(abort);
        const job = request('transcribe', { audio: base64Bytes(wavFromPcm(chunks, context.sampleRate)), format: 'wav', language: normalizeLocale(opts.current.locale) }, abort.signal)
          .then(response=>response.json()).then(body=>typeof body.text==='string' ? body.text.trim() : '')
          .finally(()=>{ r.current.aborts.delete(abort); transcriptions.current.delete(abort); drainResults.current(); });
        // A long recording can still be arriving when an earlier segment fails.
        void job.catch(()=>{}); return job;
      };
      const finish = () => {
        const chunks = utterance, duration = voiced, requests = [...segmentRequests], currentTurn = captureTurn;
        const marker=Symbol('utterance'); finalizing.current.add(marker);
        resetRef.current();
        if(duration>=.16 || (requests.length>0 && duration>0)) requests.push(transcribeSegment(chunks));
        if(!requests.length) { finalizing.current.delete(marker); drainResults.current(); return; }
        setPhase('thinking');
        void Promise.all(requests).then(parts=>{
          const transcript=parts.filter(Boolean).join(' ');
          if(gen===life.current && currentTurn===turn.current) {
            if(transcript) void converseResult.current(transcript);
            else setPhase('listening');
          }
        }).catch(e=>{
          if(gen===life.current && currentTurn===turn.current && !(e instanceof DOMException && e.name==='AbortError')) {
            setError(voiceError(opts.current.locale, e, 'speechUnrecognized')); setPhase('listening');
          }
        }).finally(()=>{finalizing.current.delete(marker); drainResults.current();});
      };
      capture.port.onmessage = e => {
        if (gen !== life.current || r.current.muted) return;
        const pcm = e.data as Float32Array; const seconds = pcm.length / context.sampleRate;
        let power = 0; for (const sample of pcm) power += sample * sample; const rms = Math.sqrt(power / pcm.length);
        if (!started && !speaking.current) noise = Math.min(.015, noise * .98 + rms * .02);
        const detected = rms > Math.max(.012, noise * 3.5);
        if (!speaking.current) setAudioLevel(Math.min(1, rms * 5));
        preRoll.push(pcm); if (preRoll.length > 6) preRoll.shift();
        speechFrames = detected ? speechFrames + seconds : 0;
        if (!started && speechFrames > .12) { interrupt(); started = true; capturing.current = true; captureTurn=turn.current; utterance = [...preRoll]; utteranceSamples=utterance.reduce((sum,chunk)=>sum+chunk.length,0); voiced = speechFrames; setPhase('listening'); }
        else if (started) { utterance.push(pcm); utteranceSamples+=pcm.length; if (detected) { voiced += seconds; silence = 0; } else silence += seconds; }
        if(started && silence>.48) finish();
        else if(started && utteranceSamples/context.sampleRate>25) {
          segmentRequests.push(transcribeSegment(utterance)); utterance=[]; utteranceSamples=0; voiced=0;
        }
      };
      setConnected(true); setConnecting(false); setPhase('listening');
    } catch (e) { if (gen === life.current) { disconnect(); setError(e instanceof DOMException && e.name === 'NotAllowedError' ? voiceCopy(opts.current.locale).microphoneDenied : voiceError(opts.current.locale, e)); } }
  }, [disconnect, interrupt, request]);
  const toggleMute = useCallback(() => {
    r.current.muted = !r.current.muted; r.current.stream?.getAudioTracks().forEach(t => { t.enabled = !r.current.muted; });
    resetRef.current(); setMuted(r.current.muted);
    if (!speaking.current) setAudioLevel(0);
    drainResults.current();
  }, []);
  const sendText = useCallback((text: string) => { if (!r.current.stream) return false; resetRef.current(); void converse(text); return true; }, [converse]);
  useEffect(() => () => disconnect(), [disconnect]);
  return { connected, connecting, phase, muted, error, audioLevel, connect, disconnect, interrupt, toggleMute, sendText, setPersona: (_avatar: AvatarId) => {}, clearError: () => setError('') };
}
