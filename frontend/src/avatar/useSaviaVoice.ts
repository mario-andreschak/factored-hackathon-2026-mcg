import { useCallback, useEffect, useRef, useState } from "react";
import { base64Bytes, Pcm16Stream, splitSpeechText, wavFromPcm } from "./audio";
import type { EyePhase } from "./Eyes";
import { UtteranceCollector } from "./utteranceObserver";

export type VoiceLanguage = "es" | "pt";
export type VoiceErrorCode =
  "browser" | "microphone" | "unrecognized" | "too_long" | "unavailable";

interface Options {
  language: VoiceLanguage;
  /** The chat is working: speech captured meanwhile is dropped, not queued. */
  paused: boolean;
  /** A recognized request. The caller sends it through the normal Savia chat. */
  onUtterance: (text: string) => void;
  onExpired?: () => void;
}

interface Session {
  abort: AbortController;
  context: AudioContext;
  analyser: AnalyserNode;
  output: GainNode;
  stream: MediaStream;
  collector: UtteranceCollector;
  noise: number;
  onset: number;
  capturing: boolean;
  inputLevel: number;
  transcribing: number;
  serial: number;
  speech?: AbortController;
  sources: Set<AudioBufferSourceNode>;
  playUntil: number;
  raf: number;
}

const WORKLET = "/avatar-audio-capture.js";
const UPLOAD_RATE = 16000;
const MAX_SPOKEN_CHUNKS = 2;

/** Markdown and references are for the screen; the voice reads plain sentences. */
export function spokenText(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/\b(?:txn|q)_[a-f0-9]{16,}\b/g, " ")
    .replace(/[*_`#>|]+/g, " ")
    .replace(/^\s*[-•]\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Microphone in, Savia's own reply out. Recognition and speech are transport:
 * every request still goes through the authenticated chat, and only text the
 * chat actually returned is read aloud.
 */
export function useSaviaVoice(options: Options) {
  const opts = useRef(options);
  opts.current = options;
  const session = useRef<Session | null>(null);
  const [active, setActive] = useState(false),
    [connecting, setConnecting] = useState(false),
    [phase, setPhase] = useState<EyePhase>("idle"),
    [level, setLevel] = useState(0),
    [error, setError] = useState<VoiceErrorCode | null>(null);

  const current = useCallback(
    (s: Session) => session.current === s && !s.abort.signal.aborted,
    [],
  );
  const speaking = (s: Session) =>
    s.sources.size > 0 || Boolean(s.speech && !s.speech.signal.aborted);
  const refresh = useCallback(
    (s: Session) => {
      if (!current(s)) return;
      setPhase(
        s.capturing
          ? "listening"
          : s.transcribing || opts.current.paused
            ? "thinking"
            : speaking(s)
              ? "speaking"
              : "listening",
      );
    },
    [current],
  );
  const silence = useCallback((s: Session) => {
    s.speech?.abort();
    s.speech = undefined;
    for (const source of s.sources) {
      source.onended = null;
      try {
        source.stop();
      } catch {
        // A source that never started has nothing to stop.
      }
    }
    s.sources.clear();
    s.playUntil = 0;
  }, []);

  const stop = useCallback(() => {
    const s = session.current;
    session.current = null;
    if (s) {
      s.abort.abort();
      silence(s);
      cancelAnimationFrame(s.raf);
      s.collector.reset();
      s.stream.getTracks().forEach((track) => track.stop());
      void s.context.close().catch(() => {});
    }
    setActive(false);
    setConnecting(false);
    setPhase("idle");
    setLevel(0);
  }, [silence]);

  const post = useCallback(
    async (s: Session, path: string, body: object, signal: AbortSignal) => {
      const response = await fetch(path, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: AbortSignal.any([signal, s.abort.signal]),
      });
      if (response.status === 401 && current(s)) {
        stop();
        opts.current.onExpired?.();
      }
      return response;
    },
    [current, stop],
  );

  const transcribe = useCallback(
    async (s: Session, audio: string, serial: number) => {
      s.transcribing++;
      refresh(s);
      try {
        const response = await post(
          s,
          "/api/voice/transcribe",
          { audio, language: opts.current.language },
          AbortSignal.timeout(45_000),
        );
        if (!response.ok) throw new Error("unavailable");
        const body: unknown = await response.json();
        const text =
          body && typeof body === "object" && "text" in body
            ? String(body.text).trim()
            : "";
        // A newer utterance, or a chat that started meanwhile, wins.
        if (!current(s) || serial !== s.serial || opts.current.paused) return;
        if (text) opts.current.onUtterance(text.slice(0, 2000));
        else setError("unrecognized");
      } catch (e) {
        if (
          current(s) &&
          !(e instanceof DOMException && e.name === "AbortError")
        )
          setError("unavailable");
      } finally {
        s.transcribing--;
        refresh(s);
      }
    },
    [current, post, refresh],
  );

  const start = useCallback(async () => {
    if (session.current || connecting) return;
    setConnecting(true);
    setError(null);
    let context: AudioContext | undefined, stream: MediaStream | undefined;
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode)
        throw new Error("browser");
      context = new AudioContext();
      await context.resume();
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      await context.audioWorklet.addModule(WORKLET);
      const analyser = context.createAnalyser(),
        output = context.createGain();
      analyser.fftSize = 1024;
      output.connect(analyser).connect(context.destination);
      const s: Session = {
        abort: new AbortController(),
        context,
        analyser,
        output,
        stream,
        collector: new UtteranceCollector(context.sampleRate, 25),
        noise: 0.002,
        onset: 0,
        capturing: false,
        inputLevel: 0,
        transcribing: 0,
        serial: 0,
        sources: new Set(),
        playUntil: 0,
        raf: 0,
      };
      const capture = new AudioWorkletNode(context, "voice-capture"),
        muted = context.createGain();
      muted.gain.value = 0;
      context
        .createMediaStreamSource(stream)
        .connect(capture)
        .connect(muted)
        .connect(context.destination);
      const rate = context.sampleRate;
      capture.port.onmessage = (event) => {
        if (!current(s)) return;
        const pcm = event.data as Float32Array;
        if (!(pcm instanceof Float32Array) || !pcm.length || pcm.length > rate)
          return;
        let power = 0;
        for (const sample of pcm) power += sample * sample;
        const rms = Math.sqrt(power / pcm.length),
          seconds = pcm.length / rate,
          playing = speaking(s);
        s.inputLevel = Math.min(1, rms * 5);
        if (s.transcribing || opts.current.paused) {
          // Savia is working on the previous request.
          if (s.capturing) s.collector.reset();
          s.capturing = false;
          s.onset = 0;
          return;
        }
        // While Savia speaks, residual echo must not count as an interruption.
        const voiced = rms > Math.max(0.012, s.noise * 3.5) * (playing ? 2 : 1);
        if (!s.capturing && !voiced)
          s.noise = Math.min(0.015, s.noise * 0.98 + rms * 0.02);
        if (!s.capturing) {
          s.onset = voiced ? s.onset + seconds : 0;
          if (s.onset >= (playing ? 0.25 : 0.12)) {
            s.capturing = true;
            s.serial++;
            silence(s);
            setError(null);
          }
        }
        const utterance = s.collector.push(pcm, voiced);
        if (utterance) {
          s.capturing = false;
          s.onset = 0;
          if (utterance.capped) setError("too_long");
          else {
            const audio = base64Bytes(
              wavFromPcm(utterance.chunks, rate, UPLOAD_RATE),
            );
            void transcribe(s, audio, s.serial);
          }
          utterance.chunks.forEach((chunk) => chunk.fill(0));
        }
        refresh(s);
      };
      const meter = new Float32Array(analyser.fftSize);
      let last = 0;
      const measure = (now: number) => {
        if (!current(s)) return;
        if (now - last >= 50) {
          last = now;
          if (s.sources.size && !s.capturing) {
            analyser.getFloatTimeDomainData(meter);
            let power = 0;
            for (const sample of meter) power += sample * sample;
            setLevel(Math.min(1, Math.sqrt(power / meter.length) * 5));
          } else setLevel(s.capturing ? s.inputLevel : 0);
          refresh(s);
        }
        s.raf = requestAnimationFrame(measure);
      };
      session.current = s;
      s.raf = requestAnimationFrame(measure);
      setActive(true);
      setConnecting(false);
      refresh(s);
    } catch (e) {
      stream?.getTracks().forEach((track) => track.stop());
      void context?.close().catch(() => {});
      setConnecting(false);
      setError(
        e instanceof DOMException &&
          (e.name === "NotAllowedError" || e.name === "NotFoundError")
          ? "microphone"
          : e instanceof Error && e.message === "browser"
            ? "browser"
            : "unavailable",
      );
    }
  }, [connecting, current, refresh, silence, transcribe]);

  const speak = useCallback(
    async (text: string) => {
      const s = session.current;
      if (!s || !current(s)) return;
      const chunks = splitSpeechText(spokenText(text)).slice(
        0,
        MAX_SPOKEN_CHUNKS,
      );
      if (!chunks.length) return;
      silence(s);
      const speech = new AbortController();
      s.speech = speech;
      refresh(s);
      try {
        for (const chunk of chunks) {
          const response = await post(
            s,
            "/api/voice/speak",
            { text: chunk, language: opts.current.language },
            speech.signal,
          );
          if (!response.ok || !response.body) throw new Error("unavailable");
          const rate = Number(response.headers.get("X-Audio-Sample-Rate"));
          if (!Number.isInteger(rate) || rate < 8000 || rate > 48000)
            throw new Error("unavailable");
          const reader = response.body.getReader(),
            pcm = new Pcm16Stream();
          while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            if (speech.signal.aborted || !current(s)) {
              await reader.cancel().catch(() => {});
              return;
            }
            const samples = pcm.decode(value);
            if (!samples.length) continue;
            const buffer = s.context.createBuffer(1, samples.length, rate);
            buffer.getChannelData(0).set(samples);
            const source = s.context.createBufferSource();
            source.buffer = buffer;
            source.connect(s.output);
            const at = Math.max(s.context.currentTime + 0.05, s.playUntil);
            s.playUntil = at + buffer.duration;
            s.sources.add(source);
            source.onended = () => {
              s.sources.delete(source);
              refresh(s);
            };
            source.start(at);
            refresh(s);
          }
        }
      } catch (e) {
        if (
          current(s) &&
          !speech.signal.aborted &&
          !(e instanceof DOMException && e.name === "AbortError")
        )
          setError("unavailable");
      } finally {
        if (s.speech === speech) s.speech = undefined;
        refresh(s);
      }
    },
    [current, post, refresh, silence],
  );

  const interrupt = useCallback(() => {
    const s = session.current;
    if (s) {
      silence(s);
      refresh(s);
    }
  }, [refresh, silence]);

  useEffect(() => {
    const s = session.current;
    if (s) refresh(s);
  }, [options.paused, refresh]);
  useEffect(() => () => stop(), [stop]);
  return {
    active,
    connecting,
    phase,
    level,
    error,
    start,
    stop,
    speak,
    interrupt,
    clearError: () => setError(null),
  };
}
