import { useCallback, useEffect, useRef, useState } from 'react';
import type { AvatarId, Phase } from './domain';
import { normalizeLocale, type Locale } from './locale';
import { voiceCopy, voiceError, VoiceLocaleError, voiceResponseError, voiceSessionInstructions } from './voiceLocale';

export interface TaskReply { reply: string; mode?: string; status?: string; }
interface VoiceOptions {
  avatar: AvatarId;
  locale?: Locale;
  onTranscript: (id: string, role: 'user' | 'assistant', text: string, done: boolean) => void;
  onWorld: (avatar: AvatarId, scene: number) => void;
  onTask: (message: string) => Promise<TaskReply>;
}
export function useVoice(options: VoiceOptions) {
  const opts = useRef(options); opts.current = options;
  const [phase, setPhase] = useState<Phase>('idle');
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [muted, setMuted] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [error, setError] = useState('');
  const resources = useRef<{ pc?: RTCPeerConnection; channel?: RTCDataChannel; stream?: MediaStream; audio?: HTMLAudioElement; context?: AudioContext; raf?: number; abort?: AbortController }>({});
  const generation = useRef(0);
  const responseActive = useRef(false);
  const userSpeaking = useRef(false);
  const needsResponse = useRef(false);
  const called = useRef(new Set<string>());
  const captions = useRef(new Map<string, string>());

  const send = useCallback((event: object) => {
    const channel = resources.current.channel;
    if (channel?.readyState === 'open') { channel.send(JSON.stringify(event)); return true; }
    return false;
  }, []);
  const disconnect = useCallback(() => {
    generation.current++;
    const r = resources.current; resources.current = {};
    r.abort?.abort();
    if (r.raf) cancelAnimationFrame(r.raf);
    r.channel?.close(); r.pc?.close(); r.stream?.getTracks().forEach(t => t.stop());
    if (r.audio) { r.audio.pause(); r.audio.srcObject = null; r.audio.remove(); }
    void r.context?.close();
    responseActive.current = false; needsResponse.current = false; userSpeaking.current = false;
    called.current.clear(); captions.current.clear();
    setConnected(false); setConnecting(false); setPhase('idle'); setAudioLevel(0); setMuted(false);
  }, []);
  const respondWhenReady = useCallback(() => {
    if (needsResponse.current && !responseActive.current && !userSpeaking.current) {
      needsResponse.current = false;
      send({ type: 'response.create' });
    }
  }, [send]);
  const interrupt = useCallback(() => {
    needsResponse.current = false;
    if (responseActive.current) send({ type: 'response.cancel' });
    send({ type: 'output_audio_buffer.clear' });
    setPhase(resources.current.stream ? 'listening' : 'idle');
  }, [send]);
  const handleTool = useCallback(async (item: { name: string; call_id: string; arguments: string }, gen: number) => {
    if (!item.call_id || called.current.has(item.call_id)) return;
    called.current.add(item.call_id);
    let result: object;
    try {
      const args = JSON.parse(item.arguments);
      if (item.name === 'set_world') {
        if (!['moss', 'orbit', 'spark'].includes(args.avatar) || !Number.isInteger(args.sceneIndex) || args.sceneIndex < 0 || args.sceneIndex > 9) throw new VoiceLocaleError('invalidWorld');
        opts.current.onWorld(args.avatar, args.sceneIndex);
        result = { applied: true, avatar: args.avatar, sceneIndex: args.sceneIndex };
      } else if (item.name === 'delegate_task') {
        if (typeof args.message !== 'string' || !args.message.trim() || args.message.length > 2000) throw new VoiceLocaleError('invalidTask');
        // Voice cancellation deliberately does not cancel an admitted banking read.
        result = await opts.current.onTask(args.message);
      } else result = { error: voiceCopy(opts.current.locale).unknownTool };
    } catch (e) { result = { error: voiceError(opts.current.locale, e, 'taskFailed') }; }
    if (gen !== generation.current) return;
    send({ type: 'conversation.item.create', item: { type: 'function_call_output', call_id: item.call_id, output: JSON.stringify(result) } });
    needsResponse.current = true; respondWhenReady();
  }, [send, respondWhenReady]);

  const connect = useCallback(async () => {
    if (resources.current.pc) return;
    if (!navigator.mediaDevices?.getUserMedia || !window.RTCPeerConnection) {
      setError(voiceCopy(opts.current.locale).browserRequired); return;
    }
    disconnect(); setError(''); setConnecting(true);
    const gen = generation.current;
    const r = resources.current;
    r.abort = new AbortController();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      if (gen !== generation.current) { stream.getTracks().forEach(t => t.stop()); return; }
      r.stream = stream;
      const pc = new RTCPeerConnection(); r.pc = pc;
      const audio = document.createElement('audio'); audio.autoplay = true; r.audio = audio;
      const context = new AudioContext(); r.context = context;
      const inputAnalyser = context.createAnalyser(); inputAnalyser.fftSize = 256;
      context.createMediaStreamSource(stream).connect(inputAnalyser);
      let outputAnalyser: AnalyserNode | undefined;
      pc.ontrack = e => {
        const remote = e.streams[0] ?? new MediaStream([e.track]); audio.srcObject = remote;
        outputAnalyser = context.createAnalyser(); outputAnalyser.fftSize = 256;
        context.createMediaStreamSource(remote).connect(outputAnalyser);
        void audio.play().catch(() => { if (gen === generation.current) setError(voiceCopy(opts.current.locale).playbackBlocked); });
      };
      stream.getTracks().forEach(t => pc.addTrack(t, stream));
      const channel = pc.createDataChannel('oai-events'); r.channel = channel;
      const data = new Uint8Array(256);
      let lastSample = 0;
      const sample = (time: number) => {
        if (gen !== generation.current) return;
        if (time - lastSample > 50) {
          (outputAnalyser && !userSpeaking.current ? outputAnalyser : inputAnalyser).getByteTimeDomainData(data);
          let power = 0; for (const n of data) power += ((n - 128) / 128) ** 2;
          setAudioLevel(Math.min(1, Math.sqrt(power / data.length) * 4)); lastSample = time;
        }
        r.raf = requestAnimationFrame(sample);
      };
      r.raf = requestAnimationFrame(sample);
      channel.onopen = () => { if (gen === generation.current) { setConnected(true); setConnecting(false); setPhase('listening'); } };
      channel.onmessage = e => {
        if (gen !== generation.current) return;
        let event; try { event = JSON.parse(e.data); } catch { return; }
        const id = event.item_id ?? event.response_id ?? 'caption';
        switch (event.type) {
          case 'input_audio_buffer.speech_started':
            userSpeaking.current = true; needsResponse.current = false; setPhase('listening'); break;
          case 'input_audio_buffer.speech_stopped':
            userSpeaking.current = false; setPhase('thinking'); break;
          case 'conversation.item.input_audio_transcription.completed':
            opts.current.onTranscript(id, 'user', event.transcript ?? '', true); break;
          case 'response.created': responseActive.current = true; setPhase('thinking'); break;
          case 'output_audio_buffer.started': setPhase('speaking'); break;
          case 'output_audio_buffer.stopped': case 'output_audio_buffer.cleared':
            setPhase('listening'); break;
          case 'response.output_audio_transcript.delta': {
            const text = (captions.current.get(id) ?? '') + (event.delta ?? '');
            captions.current.set(id, text); opts.current.onTranscript(id, 'assistant', text, false); break;
          }
          case 'response.output_audio_transcript.done':
            opts.current.onTranscript(id, 'assistant', event.transcript ?? captions.current.get(id) ?? '', true); captions.current.delete(id); break;
          case 'response.done':
            responseActive.current = false;
            for (const item of event.response?.output ?? []) if (item.type === 'function_call') void handleTool(item, gen);
            respondWhenReady(); break;
          case 'error':
            if (!['response_cancel_not_active', 'response_already_in_progress'].includes(event.error?.code)) setError(voiceCopy(opts.current.locale).providerFailed);
            break;
        }
      };
      pc.onconnectionstatechange = () => {
        if (gen === generation.current && ['failed', 'closed', 'disconnected'].includes(pc.connectionState)) { disconnect(); setError(voiceCopy(opts.current.locale).connectionEnded); }
      };
      const offer = await pc.createOffer(); await pc.setLocalDescription(offer);
      const response = await fetch(`/api/avatar/realtime?avatar=${opts.current.avatar}&locale=${normalizeLocale(opts.current.locale)}`, {
        method: 'POST', headers: { 'Content-Type': 'application/sdp' }, body: offer.sdp,
        signal: AbortSignal.any([r.abort.signal, AbortSignal.timeout(30_000)]),
      });
      if (!response.ok) {
        throw await voiceResponseError(response);
      }
      const answer = await response.text();
      if (gen !== generation.current) return;
      await pc.setRemoteDescription({ type: 'answer', sdp: answer });
      void context.resume();
    } catch (e) {
      if (gen !== generation.current) return;
      disconnect();
      setError(e instanceof DOMException && e.name === 'NotAllowedError' ? voiceCopy(opts.current.locale).microphoneDenied : voiceError(opts.current.locale, e));
    }
  }, [disconnect, handleTool, respondWhenReady]);

  const toggleMute = useCallback(() => {
    const track = resources.current.stream?.getAudioTracks()[0];
    if (track) { track.enabled = !track.enabled; setMuted(!track.enabled); }
  }, []);
  const sendText = useCallback((text: string) => {
    if (!connected) return false;
    interrupt();
    send({ type: 'conversation.item.create', item: { type: 'message', role: 'user', content: [{ type: 'input_text', text }] } });
    send({ type: 'response.create' }); return true;
  }, [connected, interrupt, send]);
  const setPersona = useCallback((avatar: AvatarId) => {
    send({ type: 'session.update', session: { type: 'realtime', instructions: voiceSessionInstructions(avatar, opts.current.locale) } });
  }, [send]);
  useEffect(() => () => disconnect(), [disconnect]);
  return { phase, connected, connecting, muted, audioLevel, error, connect, disconnect, interrupt, toggleMute, sendText, setPersona, clearError: () => setError('') };
}
