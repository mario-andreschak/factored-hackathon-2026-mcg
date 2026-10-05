import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { useSaviaVoice } from "./useSaviaVoice";
import { UtteranceCollector } from "./utteranceObserver";

class Node {
  gain = { value: 0 };
  connect(node: Node) {
    return node;
  }
  disconnect() {}
}
class Source extends Node {
  buffer?: { duration: number };
  onended: (() => void) | null = null;
  start() {}
  stop() {}
}
class Context {
  static instances: Context[] = [];
  sampleRate = 16000;
  currentTime = 0;
  deviceTime = 0;
  outputLatency = 0.05;
  baseLatency = 0;
  destination = new Node();
  sources: Source[] = [];
  audioWorklet = { addModule: vi.fn(async () => {}) };
  constructor() {
    Context.instances.push(this);
  }
  async resume() {}
  async close() {}
  getOutputTimestamp() {
    return { contextTime: this.deviceTime, performanceTime: 1 };
  }
  createGain() {
    return new Node();
  }
  createMediaStreamSource() {
    return new Node();
  }
  createAnalyser() {
    return Object.assign(new Node(), {
      fftSize: 1024,
      getFloatTimeDomainData(array: Float32Array) {
        array.fill(0);
      },
    });
  }
  createBuffer(_channels: number, samples: number, rate: number) {
    return {
      duration: samples / rate,
      getChannelData: () => new Float32Array(samples),
    };
  }
  createBufferSource() {
    const node = new Source();
    this.sources.push(node);
    return node;
  }
}
class Worklet extends Node {
  static latest: Worklet;
  port = {
    onmessage: null as ((event: { data: Float32Array }) => void) | null,
  };
  constructor() {
    super();
    Worklet.latest = this;
  }
}

let frames: Map<number, FrameRequestCallback>, nextFrame: number;
let requests: { path: string; body: Record<string, unknown> }[];
beforeEach(() => {
  vi.useFakeTimers();
  Context.instances = [];
  frames = new Map();
  nextFrame = 0;
  requests = [];
  vi.stubGlobal("AudioContext", Context);
  vi.stubGlobal("AudioWorkletNode", Worklet);
  vi.stubGlobal("navigator", {
    mediaDevices: {
      getUserMedia: vi.fn(async () => ({
        getTracks: () => [{ stop: vi.fn() }],
      })),
    },
  });
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    frames.set(++nextFrame, callback);
    return nextFrame;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body));
      requests.push({ path, body });
      if (path === "/api/voice/turn") {
        const ordinal = requests.filter(
          (request) => request.path === path,
        ).length;
        const turnId = String.fromCharCode(64 + ordinal).repeat(24);
        const caption = body.result
          ? "El equipo dejó una sugerencia útil."
          : "Estoy aquí mientras esperas.";
        return new Response(
          [
            { type: "start", sample_rate: 24000, turn_id: turnId },
            { type: "caption", text: caption },
            { type: "audio", data: btoa("\x10\x00".repeat(240)) },
            { type: "complete", text: caption, turn_id: turnId, samples: 240 },
          ]
            .map((event) => JSON.stringify(event))
            .join("\n"),
          { headers: { "Content-Type": "application/x-ndjson" } },
        );
      }
      if (path === "/api/voice/played")
        return new Response("{}", {
          headers: { "Content-Type": "application/json" },
        });
      if (path === "/api/voice/transcribe")
        return new Response('{"text":"Estoy pensando"}', {
          headers: { "Content-Type": "application/json" },
        });
      throw new Error("Unexpected voice endpoint");
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
const options = () => ({
  language: "es" as const,
  paused: true,
  conversation: true,
  onUtterance: vi.fn(),
  onDelegate: vi.fn(),
  onCaption: vi.fn(),
});
function feed(count: number, value: number) {
  act(() => {
    for (let i = 0; i < count; i++)
      Worklet.latest.port.onmessage?.({
        data: new Float32Array(1600).fill(value),
      });
  });
}
async function tick(ms = 25) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}
function frame() {
  act(() => {
    const callbacks = [...frames.values()];
    frames.clear();
    callbacks.forEach((callback) => callback(performance.now() + 100));
  });
}
const turns = () =>
  requests.filter((request) => request.path === "/api/voice/turn");
const acks = () =>
  requests.filter((request) => request.path === "/api/voice/played");

test("a thinking pause stays one recording; background work permits foreground speech and queued team narration waits for hardware playback", async () => {
  const callbacks = options();
  const hook = renderHook(() => useSaviaVoice(callbacks));
  await act(async () => {
    await hook.result.current.start();
  });
  feed(6, 0.04);
  feed(12, 0);
  feed(5, 0.08);
  feed(19, 0);
  await tick();
  expect(turns()).toHaveLength(0);
  expect(callbacks.onDelegate).not.toHaveBeenCalled();
  feed(1, 0);
  await tick();
  expect(turns()).toHaveLength(1);
  expect(turns()[0].body.working).toBe(true);
  const recording = atob(String(turns()[0].body.audio));
  expect(recording.startsWith("RIFF")).toBe(true);
  expect(recording.length).toBe(44 + 1600 * 43 * 2);
  act(() => {
    hook.result.current.narrate("Respuesta canónica del equipo.");
    hook.result.current.narrate("Respuesta canónica del equipo.");
  });
  frame();
  await tick();
  expect(turns()).toHaveLength(1);
  expect(acks()).toHaveLength(0);
  const context = Context.instances[0];
  act(() => {
    context.currentTime = 1;
    context.sources[0].onended?.();
  });
  await tick();
  expect(acks()).toHaveLength(0); // Node ended; device has not drained.
  context.deviceTime = 1;
  await tick();
  expect(acks()).toHaveLength(1);
  expect(acks()[0].body.complete).toBe(true);
  frame();
  await tick();
  expect(turns()).toHaveLength(2);
  expect(turns()[1].body.result).toBe("Respuesta canónica del equipo.");
  act(() => {
    context.currentTime = 2;
    context.deviceTime = 2;
    context.sources[1].onended?.();
  });
  await tick();
  frame();
  await tick();
  expect(acks()).toHaveLength(2);
  expect(turns()).toHaveLength(2);
  expect(callbacks.onUtterance).not.toHaveBeenCalled();
  expect(callbacks.onDelegate).not.toHaveBeenCalled();
});

test("barge-in clears an unheard partial caption without a full-played acknowledgement", async () => {
  const callbacks = options();
  const hook = renderHook(() => useSaviaVoice(callbacks));
  await act(async () => {
    await hook.result.current.start();
  });
  feed(3, 0.04);
  feed(20, 0);
  await tick();
  expect(turns()).toHaveLength(1);
  expect(callbacks.onCaption).toHaveBeenCalledWith(
    expect.any(String),
    "Estoy aquí mientras esperas.",
    false,
  );
  feed(3, 0.08);
  await tick();
  expect(acks()).toHaveLength(0);
  expect(callbacks.onCaption).toHaveBeenLastCalledWith(
    expect.any(String),
    "",
    true,
  );
});

test("capped speech and its resumed tail cannot dispatch or release a queued result before two continuous quiet seconds", async () => {
  const hook = renderHook(() => useSaviaVoice(options()));
  await act(async () => {
    await hook.result.current.start();
  });
  feed(260, 0.04);
  act(() => hook.result.current.narrate("Respuesta canónica del equipo."));
  feed(10, 0);
  feed(6, 0.04);
  frame();
  await tick();
  expect(turns()).toHaveLength(0);
  feed(19, 0);
  frame();
  await tick();
  expect(turns()).toHaveLength(0);
  feed(1, 0);
  frame();
  await tick();
  expect(turns()).toHaveLength(1);
  expect(turns()[0].body.result).toBe("Respuesta canónica del equipo.");
});

test("collector retains both speech segments and resets the deadline after a thinking pause", () => {
  const collector = new UtteranceCollector(16000);
  const push = (n: number, value: number) => {
    let result;
    for (let i = 0; i < n; i++)
      result =
        collector.push(new Float32Array(1600).fill(value), value !== 0) ??
        result;
    return result;
  };
  expect(push(6, 0.2)).toBeUndefined();
  expect(push(12, 0)).toBeUndefined();
  expect(push(5, 0.4)).toBeUndefined();
  expect(push(19, 0)).toBeUndefined();
  const result = push(1, 0)!;
  expect(
    result.chunks.filter((chunk) => chunk[0] > 0.19 && chunk[0] < 0.21),
  ).toHaveLength(6);
  expect(
    result.chunks.filter((chunk) => chunk[0] > 0.39 && chunk[0] < 0.41),
  ).toHaveLength(5);
});

test("starting a new chat discards queued narration and partial microphone input while keeping capture available", async () => {
  const hook = renderHook(() => useSaviaVoice(options()));
  await act(async () => {
    await hook.result.current.start();
  });
  feed(3, 0.04);
  const previousOwner = hook.result.current.getSessionOwner();
  act(() => {
    hook.result.current.narrate("Respuesta de la conversación anterior.");
    hook.result.current.resetContext();
  });
  feed(20, 0);
  frame();
  await tick();
  expect(hook.result.current.active).toBe(true);
  expect(turns()).toHaveLength(0);
  expect(hook.result.current.getSessionOwner()).not.toBe(previousOwner);
  act(() => {
    expect(
      hook.result.current.narrate(
        "Una consulta anterior llegó tarde.",
        previousOwner,
      ),
    ).toBe(false);
  });
  feed(3, 0.08);
  feed(20, 0);
  await tick();
  expect(turns()).toHaveLength(1);
  expect(turns()[0].body.fresh).toBe(true);
  expect(turns()[0].body.result).toBeUndefined();
});

test("a late team reply cannot move from an old microphone session into a restarted voice session", async () => {
  const hook = renderHook(() => useSaviaVoice(options()));
  await act(async () => {
    await hook.result.current.start();
  });
  const previousOwner = hook.result.current.getSessionOwner();
  act(() => {
    hook.result.current.stop();
  });
  await act(async () => {
    await hook.result.current.start();
  });
  expect(hook.result.current.getSessionOwner()).not.toBe(previousOwner);
  act(() => {
    expect(
      hook.result.current.narrate(
        "Respuesta de la sesión anterior.",
        previousOwner,
      ),
    ).toBe(false);
  });
  frame();
  await tick();
  expect(turns()).toHaveLength(0);
});
