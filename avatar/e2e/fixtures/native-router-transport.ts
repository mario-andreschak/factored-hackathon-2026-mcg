import type { Page } from '@playwright/test';

export interface RequestRecord { path: string; body: Record<string, unknown>; aborted: boolean; }
export interface NativeTransport {
  requests: RequestRecord[]; tracksStopped: number; contextsClosed: number; capturesDisconnected: number;
  sourcesStarted: number; sourcesStopped: number; bodyCancelled: number; duration: number; autoComplete: boolean;
  holdObservers: boolean; holdFullReceipts: boolean; holdTurnFetch: boolean;
  observers: { resolve: (text: string) => void; record: RequestRecord }[];
  fullReceipts: ((status?: number) => void)[]; delayedTurns: (() => void)[];
  emit(amplitude: number, seconds: number): void; finish(id: string): void;
}
declare global { interface Window { __nativeTransport: NativeTransport; } }

export async function mockedNative(page: Page, options: { passthroughPaths?: string[] } = {}) {
  const allowedApiPaths = options.passthroughPaths ?? [];
  await page.addInitScript(({ allowedApiPaths }) => {
    const OriginalAudio = window.AudioContext, originalFetch = window.fetch.bind(window);
    let serial = 0;
    const streams = new Map<string, { stream: ReadableStreamDefaultController<Uint8Array>; samples: number; caption: string }>();
    let capture: { port: { onmessage?: (event: { data: Float32Array }) => void }; context: AudioContext } | null = null;
    const transport: NativeTransport = {
      requests: [], tracksStopped: 0, contextsClosed: 0, capturesDisconnected: 0, sourcesStarted: 0, sourcesStopped: 0,
      bodyCancelled: 0, duration: .25, autoComplete: true, holdObservers: false, holdFullReceipts: false, holdTurnFetch: false,
      observers: [], fullReceipts: [], delayedTurns: [],
      emit(amplitude, seconds) {
        if (!capture) throw new Error('Synthetic capture is unavailable');
        const frames = Math.ceil(seconds * capture.context.sampleRate / 2048);
        for (let i = 0; i < frames; i++) capture.port.onmessage?.({ data: new Float32Array(2048).fill(amplitude) });
      },
      finish(id) {
        const entry = streams.get(id); if (!entry) throw new Error('Synthetic native turn is unavailable');
        entry.stream.enqueue(new TextEncoder().encode(JSON.stringify({ type: 'complete', turnId: id, samples: entry.samples, text: entry.caption, usage: {} }) + '\n'));
        entry.stream.close(); streams.delete(id);
      },
    };
    window.__nativeTransport = transport;
    class TestAudioContext extends OriginalAudio {
      close() { transport.contextsClosed++; return super.close(); }
      createBufferSource() {
        const source = super.createBufferSource(), start = source.start.bind(source), stop = source.stop.bind(source);
        source.start = (...args: Parameters<typeof source.start>) => { transport.sourcesStarted++; start(...args); };
        source.stop = (...args: Parameters<typeof source.stop>) => { transport.sourcesStopped++; stop(...args); };
        return source;
      }
    }
    Object.defineProperty(window, 'AudioContext', { value: TestAudioContext });
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: {
      async getUserMedia() {
        const context = new OriginalAudio(), stream = context.createMediaStreamDestination().stream;
        for (const track of stream.getTracks()) {
          const stop = track.stop.bind(track);
          track.stop = () => { transport.tracksStopped++; stop(); void context.close(); };
        }
        return stream;
      },
    } });
    class TestCapture extends GainNode {
      port = { onmessage: undefined as ((event: { data: Float32Array }) => void) | undefined };
      constructor(context: AudioContext) { super(context); capture = this; }
      disconnect() { transport.capturesDisconnected++; super.disconnect(); }
    }
    Object.defineProperty(window, 'AudioWorkletNode', { value: TestCapture });
    window.fetch = async (input, init) => {
      const path = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href).pathname;
      if (!path.startsWith('/api/') || allowedApiPaths.includes(path)) return originalFetch(input, init);
      if (!/^\/api\/avatar\/native-(?:reset|turn|played|observe|result)$/.test(path)) throw new Error('Unexpected provider or bank operation in local native fixture');
      const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
      const record = { path, body, aborted: Boolean(init?.signal?.aborted) }; transport.requests.push(record);
      init?.signal?.addEventListener('abort', () => { record.aborted = true; }, { once: true });
      if (path.endsWith('native-reset')) return Response.json({ reset: true });
      if (path.endsWith('native-played')) {
        const status = body.complete === true && transport.holdFullReceipts
          ? await new Promise<number>(resolve => { transport.fullReceipts.push((status = 200) => resolve(status)); }) : 200;
        return Response.json(status === 200 ? { stored: true } : { code: 'native_turn_ended' }, { status });
      }
      if (path.endsWith('native-observe')) {
        if (transport.holdObservers) return new Promise<Response>(resolve => { transport.observers.push({ record, resolve: text => resolve(Response.json({ text })) }); });
        return Response.json({ text: 'Quiero cocinar arroz sin que se pegue.' });
      }
      const create = () => {
        const id = `fixture-native-${++serial}`, samples = Math.ceil(transport.duration * 24000), caption = `Respuesta nativa ${serial}.`;
        const body = new ReadableStream<Uint8Array>({
          start(stream) {
            streams.set(id, { stream, samples, caption });
            const send = (event: object) => stream.enqueue(new TextEncoder().encode(JSON.stringify(event) + '\n'));
            send({ type: 'start', turnId: id, sampleRate: 24000, sampleRateQualification: 'assumed' });
            // Independently base64 encoded PCM packets, like the bounded real server.
            for (let offset = 0; offset < samples; offset += 12000) {
              const count = Math.min(12000, samples - offset), bytes = new Uint8Array(count * 2);
              const view = new DataView(bytes.buffer); for (let i = 0; i < count; i++) view.setInt16(i * 2, Math.round(Math.sin((offset + i) * .08) * 3000), true);
              let binary = ''; for (const byte of bytes) binary += String.fromCharCode(byte);
              send({ type: 'audio', turnId: id, data: btoa(binary) });
            }
            send({ type: 'caption', turnId: id, text: caption });
            if (transport.autoComplete) transport.finish(id);
          }, cancel() { transport.bodyCancelled++; streams.delete(id); },
        });
        return new Response(body, { headers: { 'Content-Type': 'application/x-ndjson' } });
      };
      if (transport.holdTurnFetch) await new Promise<void>(resolve => { transport.delayedTurns.push(resolve); });
      return create();
    };
  }, { allowedApiPaths });
  await page.route('**/__native_router_harness', route => route.fulfill({ contentType: 'text/html', body:
    `<!doctype html><html><body><div id="root"></div><script type="module">
      import RefreshRuntime from '/@react-refresh'; RefreshRuntime.injectIntoGlobalHook(window);
      window.$RefreshReg$ = () => {}; window.$RefreshSig$ = () => (type) => type;
      window.__vite_plugin_react_preamble_installed__ = true;
    </script><script type="module" src="/@vite/client"></script>
    <script type="module" src="/e2e/fixtures/native-router-harness.tsx"></script></body></html>` }));
}
