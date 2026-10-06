import { useCallback, useEffect, useRef, useState } from "react";
import {
  base64Bytes,
  Pcm16Stream,
  readNdjson,
  splitSpeechText,
  wavFromPcm,
} from "./audio";
import type { EyePhase } from "./Eyes";
import { UtteranceCollector } from "./utteranceObserver";

export type VoiceLanguage = "es" | "pt";
export type VoiceErrorCode =
  "browser" | "microphone" | "unrecognized" | "too_long" | "unavailable";

interface Options {
  language: VoiceLanguage;
  /** The Savia chat is working on a request. */
  paused: boolean;
  /** The server offers the conversational voice; otherwise speech is only dictation. */
  conversation: boolean;
  /** Dictation only: a recognized request for the normal Savia chat. */
  onUtterance: (text: string) => void;
  /** What the person is saying, as it is recognized. `final` closes that utterance. */
  onHeard?: (id: string, text: string, final: boolean) => void;
  /** What the voice is saying in its own conversational turn. */
  onCaption?: (id: string, text: string, final: boolean) => void;
  /** The voice hands a request to Savia. The caller sends it through the chat. */
  onDelegate?: (request: string) => void;
  onExpired?: () => void;
}

interface Session {
  owner: symbol;
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
  turn?: AbortController;
  turns: number;
  pendingResults: string[];
  resultIds: Set<string>;
  ackBarrier: Promise<void>;
  partialBusy: boolean;
  partialAt: number;
  finalId: string;
  sources: Set<AudioBufferSourceNode>;
  playUntil: number;
  raf: number;
}

const WORKLET = "/avatar-audio-capture.js";
const UPLOAD_RATE = 16000;
const MAX_SPOKEN_CHUNKS = 4;
const PARTIAL_EVERY_MS = 1000;
let sessions = 0;

function pcmSamples(data: string): Float32Array {
  const binary = atob(data),
    samples = new Float32Array(binary.length >> 1);
  for (let i = 0; i < samples.length; i++) {
    const value =
      binary.charCodeAt(2 * i) | (binary.charCodeAt(2 * i + 1) << 8);
    samples[i] = (value >= 0x8000 ? value - 0x10000 : value) / 32768;
  }
  return samples;
}

/** Markdown and references are for the screen; the voice reads plain sentences. */
export function spokenText(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/\b(?:txn|q|i)_[a-f0-9]{16,}\b/g, " ")
    .replace(/[*_`#>|]+/g, " ")
    .replace(/^\s*[-•]\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * A spoken conversation in front of the Savia chat. The voice model hears the
 * recording, answers in its own voice and hands bank requests to the caller,
 * which sends them through the authenticated chat; `narrate` gives the chat's
 * verified reply back to be told. Without the conversational voice this falls
 * back to dictation: recognize, send, read the reply aloud.
 */
export function useSaviaVoice(options: Options) {
  const opts = useRef(options);
  opts.current = options;
  const session = useRef<Session | null>(null);
  const startEpoch = useRef(0);
  const [active, setActive] = useState(false),
    [connecting, setConnecting] = useState(false),
    [phase, setPhase] = useState<EyePhase>("idle"),
    [level, setLevel] = useState(0),
    [error, setError] = useState<VoiceErrorCode | null>(null);

  const current = useCallback(
    (s: Session) => session.current === s && !s.abort.signal.aborted,
    [],
  );
  const speaking = (s: Session) => s.sources.size > 0;
  const waiting = (s: Session) =>
    Boolean(
      (s.speech && !s.speech.signal.aborted) ||
      (s.turn && !s.turn.signal.aborted),
    );
  const refresh = useCallback(
    (s: Session) => {
      if (!current(s)) return;
      setPhase(
        s.capturing
          ? "listening"
          : speaking(s)
            ? "speaking"
            : s.transcribing || waiting(s) || opts.current.paused
              ? "thinking"
              : "listening",
      );
    },
    [current],
  );
  const silence = useCallback((s: Session) => {
    s.speech?.abort();
    s.speech = undefined;
    s.turn?.abort();
    s.turn = undefined;
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
    startEpoch.current++;
    const s = session.current;
    session.current = null;
    if (s) {
      s.abort.abort();
      s.pendingResults = [];
      s.resultIds.clear();
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

  const enqueue = useCallback(
    (s: Session, samples: Float32Array, rate: number) => {
      if (!samples.length) return;
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
    },
    [refresh],
  );

  const transcribe = useCallback(
    async (s: Session, audio: string, serial: number, id: string) => {
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
        s.finalId = id;
        opts.current.onHeard?.(id, text.slice(0, 2000), true);
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

  /** Recognize the utterance so far, so its text appears while the person speaks. */
  const partial = useCallback(
    async (s: Session, id: string, serial: number) => {
      const chunks = s.collector.snapshot(),
        rate = s.context.sampleRate;
      let samples = 0;
      for (const chunk of chunks) samples += chunk.length;
      if (samples < rate * 0.7) return;
      s.partialBusy = true;
      s.partialAt = performance.now();
      try {
        const response = await post(
          s,
          "/api/voice/transcribe",
          {
            audio: base64Bytes(wavFromPcm(chunks, rate, UPLOAD_RATE)),
            language: opts.current.language,
          },
          AbortSignal.timeout(15_000),
        );
        if (!response.ok) return;
        const body: unknown = await response.json();
        const text =
          body && typeof body === "object" && "text" in body
            ? String(body.text).trim()
            : "";
        if (text && current(s) && serial === s.serial && s.finalId !== id)
          opts.current.onHeard?.(id, text.slice(0, 2000), false);
      } catch {
        // Interim text is a convenience; the finished utterance is still sent.
      } finally {
        s.partialBusy = false;
      }
    },
    [current, post],
  );

  const speakRef = useRef<(text: string) => Promise<void>>(async () => {});
  const converse = useCallback(
    async (
      s: Session,
      input: { audio: string } | { result: string },
      id: string,
      serial: number,
    ) => {
      silence(s);
      const turn = new AbortController(),
        own = "audio" in input,
        ownOwner = s.owner;
      let started = false,
        acknowledged = false,
        heard = false;
      let turnId = "",
        receivedSamples = 0,
        completed = false,
        finalText = "";
      s.turn = turn;
      if (own) opts.current.onHeard?.(id, "", false);
      refresh(s);
      try {
        await s.ackBarrier;
        if (turn.signal.aborted || !current(s)) return;
        const response = await post(
          s,
          "/api/voice/turn",
          {
            ...input,
            language: opts.current.language,
            working: own && opts.current.paused,
            fresh: s.turns++ === 0,
          },
          AbortSignal.any([turn.signal, AbortSignal.timeout(60_000)]),
        );
        if (!response.ok) throw new Error("unavailable");
        let rate = 24000;
        await readNdjson(response, (event) => {
          if (turn.signal.aborted || !current(s))
            throw new DOMException("Interrupted.", "AbortError");
          const text = typeof event.text === "string" ? event.text : "";
          if (completed) throw new Error("unavailable");
          if (event.type === "start") {
            if (
              started ||
              typeof event.turn_id !== "string" ||
              !/^[A-Za-z0-9_-]{24}$/.test(event.turn_id) ||
              event.sample_rate !== 24000
            )
              throw new Error("unavailable");
            started = true;
            turnId = event.turn_id;
            const sent = Number(event.sample_rate);
            if (Number.isInteger(sent) && sent >= 8000 && sent <= 48000)
              rate = sent;
          } else if (!started) throw new Error("unavailable");
          else if (event.type === "heard" && own) {
            heard = true;
            s.finalId = id;
            opts.current.onHeard?.(id, text.trim(), true);
          } else if (event.type === "caption" && own)
            opts.current.onCaption?.(id, text, false);
          else if (event.type === "audio" && typeof event.data === "string") {
            if (
              !event.data.length ||
              event.data.length % 4 ||
              !/^[A-Za-z0-9+/]+={0,2}$/.test(event.data)
            )
              throw new Error("unavailable");
            const bytes = atob(event.data);
            if (bytes.length % 2 || btoa(bytes) !== event.data)
              throw new Error("unavailable");
            receivedSamples += bytes.length / 2;
            if (receivedSamples > 1440000) throw new Error("unavailable");
            enqueue(s, pcmSamples(event.data), rate);
          } else if (event.type === "delegate" && own) {
            if (typeof event.request === "string" && event.request.trim())
              opts.current.onDelegate?.(event.request.trim());
          } else if (event.type === "complete") {
            if (
              event.turn_id !== turnId ||
              event.samples !== receivedSamples ||
              receivedSamples <= 0
            )
              throw new Error("unavailable");
            completed = true;
            finalText = text;
          } else if (event.type === "error") throw new Error("unavailable");
        });
        if (!completed) throw new Error("unavailable");
        // Source-node end can precede the device clock. Wait for both clocks.
        const deadline = performance.now() + 65000;
        while (current(s) && !turn.signal.aborted) {
          const timestamp = s.context.getOutputTimestamp?.();
          const hardwareTime =
            timestamp &&
            typeof timestamp.performanceTime === "number" &&
            timestamp.performanceTime > 0 &&
            typeof timestamp.contextTime === "number"
              ? timestamp.contextTime
              : s.context.currentTime -
                (s.context.outputLatency || 0.05) -
                (s.context.baseLatency || 0);
          if (!s.sources.size && hardwareTime >= s.playUntil) break;
          if (performance.now() >= deadline) throw new Error("unavailable");
          await new Promise((resolve) => setTimeout(resolve, 25));
        }
        if (!current(s) || turn.signal.aborted) return;
        const publish = async () => {
          if (!current(s) || ownOwner !== s.owner) return;
          const ack = await post(
            s,
            "/api/voice/played",
            {
              turn_id: turnId,
              played_samples: receivedSamples,
              complete: true,
            },
            AbortSignal.timeout(5000),
          );
          if (!ack.ok) throw new Error("unavailable");
          await ack.body?.cancel();
        };
        const ack = s.ackBarrier.then(publish);
        // Keep this turn's failure, but let later turns wait for settlement.
        s.ackBarrier = ack.catch(() => {});
        await ack;
        acknowledged = true;
        if (own && current(s) && ownOwner === s.owner)
          opts.current.onCaption?.(id, finalText, true);
      } catch (e) {
        const interrupted =
          turn.signal.aborted ||
          !current(s) ||
          (e instanceof DOMException && e.name === "AbortError");
        if (!interrupted && !started) {
          // The conversational voice is down: this turn falls back to dictation.
          if (s.turn === turn) s.turn = undefined;
          if ("audio" in input) {
            heard = true;
            void transcribe(s, input.audio, serial, id);
          } else void speakRef.current(input.result);
        } else if (!interrupted) {
          silence(s);
          setError("unavailable");
        }
      } finally {
        if (s.turn === turn) s.turn = undefined;
        if (own && !acknowledged) opts.current.onCaption?.(id, "", true);
        if (own && !heard && current(s)) {
          s.finalId = id;
          opts.current.onHeard?.(id, "", true);
        }
        refresh(s);
      }
    },
    [current, enqueue, post, refresh, silence, transcribe],
  );

  const start = useCallback(async () => {
    if (session.current || connecting) return;
    setConnecting(true);
    setError(null);
    const ownEpoch = ++startEpoch.current;
    let context: AudioContext | undefined, stream: MediaStream | undefined;
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode)
        throw new Error("browser");
      context = new AudioContext();
      await context.resume();
      if (ownEpoch !== startEpoch.current)
        throw new DOMException("Cancelled", "AbortError");
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      if (ownEpoch !== startEpoch.current)
        throw new DOMException("Cancelled", "AbortError");
      await context.audioWorklet.addModule(WORKLET);
      if (ownEpoch !== startEpoch.current)
        throw new DOMException("Cancelled", "AbortError");
      const analyser = context.createAnalyser(),
        output = context.createGain();
      analyser.fftSize = 1024;
      output.connect(analyser).connect(context.destination);
      const s: Session = {
        owner: Symbol("savia-voice-session"),
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
        turns: 0,
        pendingResults: [],
        resultIds: new Set(),
        ackBarrier: Promise.resolve(),
        partialBusy: false,
        partialAt: 0,
        finalId: "",
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
      const rate = context.sampleRate,
        epoch = ++sessions;
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
        const native = opts.current.conversation;
        if (!native && (s.transcribing || opts.current.paused)) {
          // Dictation: Savia is working on the previous request.
          if (s.capturing) s.collector.reset();
          s.capturing = false;
          s.onset = 0;
          return;
        }
        // While Savia speaks, residual echo must not count as an interruption.
        const voiced = rms > Math.max(0.012, s.noise * 3.5) * (playing ? 2 : 1);
        if (s.collector.waitingForQuiet) {
          s.collector.push(pcm, voiced);
          s.capturing = false;
          s.onset = 0;
          refresh(s);
          return;
        }
        if (!s.capturing && !voiced)
          s.noise = Math.min(0.015, s.noise * 0.98 + rms * 0.02);
        if (!s.capturing) {
          s.onset = voiced ? s.onset + seconds : 0;
          if (s.onset >= (playing ? 0.25 : 0.12)) {
            s.capturing = true;
            s.serial++;
            s.partialAt = performance.now();
            silence(s);
            setError(null);
          }
        }
        const id = `voice-${epoch}-${s.serial}`;
        const utterance = s.collector.push(pcm, voiced);
        if (utterance) {
          s.capturing = false;
          s.onset = 0;
          if (utterance.capped) setError("too_long");
          else {
            const audio = base64Bytes(
              wavFromPcm(utterance.chunks, rate, UPLOAD_RATE),
            );
            if (native) void converse(s, { audio }, id, s.serial);
            else void transcribe(s, audio, s.serial, id);
          }
          utterance.chunks.forEach((chunk) => chunk.fill(0));
        } else if (
          s.capturing &&
          !s.partialBusy &&
          performance.now() - s.partialAt >= PARTIAL_EVERY_MS
        )
          void partial(s, id, s.serial);
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
          // Savia's reply waits for a pause: nobody speaking, nothing playing.
          if (
            s.pendingResults.length &&
            !s.capturing &&
            !s.collector.waitingForQuiet &&
            !s.turn &&
            !s.sources.size
          ) {
            const result = s.pendingResults.shift()!;
            void converse(s, { result }, "result", s.serial);
          }
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
      if (ownEpoch !== startEpoch.current) return;
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
  }, [connecting, converse, current, partial, refresh, silence, transcribe]);

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
            enqueue(s, pcm.decode(value), rate);
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
    [current, enqueue, post, refresh, silence],
  );
  speakRef.current = speak;

  /** Tell the person what Savia answered, in the conversational voice when there is one. */
  const narrate = useCallback(
    (text: string, expectedOwner?: symbol | null) => {
      const s = session.current;
      if (
        !s ||
        !current(s) ||
        (expectedOwner !== undefined && expectedOwner !== s.owner)
      )
        return false;
      if (!opts.current.conversation) {
        void speak(text);
        return true;
      } else if (
        text.trim() &&
        text.length <= 4000 &&
        !s.resultIds.has(text) &&
        s.pendingResults.length < 4 &&
        s.resultIds.size < 64
      ) {
        s.resultIds.add(text);
        s.pendingResults.push(text);
        return true;
      }
      return false;
    },
    [current, speak],
  );

  const interrupt = useCallback(() => {
    const s = session.current;
    if (s) {
      silence(s);
      refresh(s);
    }
  }, [refresh, silence]);

  const resetContext = useCallback(() => {
    const s = session.current;
    if (!s || !current(s)) return;
    silence(s);
    s.collector.reset();
    s.capturing = false;
    s.onset = 0;
    s.pendingResults = [];
    s.resultIds.clear();
    s.serial++;
    s.turns = 0;
    s.owner = Symbol("savia-voice-context");
    s.ackBarrier = Promise.resolve();
    refresh(s);
  }, [current, refresh, silence]);
  const getSessionOwner = useCallback(() => {
    const s = session.current;
    return s && current(s) ? s.owner : null;
  }, [current]);

  useEffect(() => {
    const s = session.current;
    if (s) refresh(s);
  }, [options.paused, refresh]);
  useEffect(() => () => stop(), [stop]);
  useEffect(() => {
    stop();
  }, [options.language, stop]);
  return {
    active,
    connecting,
    phase,
    level,
    error,
    start,
    stop,
    narrate,
    interrupt,
    resetContext,
    getSessionOwner,
    clearError: () => setError(null),
  };
}
