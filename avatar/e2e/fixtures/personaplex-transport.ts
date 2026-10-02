import type { Page } from '@playwright/test';

export interface Transport {
  tracksStopped: number; contextsClosed: number; capturesDisconnected: number;
  sourcesStarted: number; sourcesStopped: number; socketsClosed: number; sampleRate: number;
  messages: ({ type?: string; id?: string } | number[])[]; urls: string[];
  socket: { bufferedAmount: number } | null;
  emit(event: object): void;
  audio(generation: number, sampleIndex: number, samples?: number, delayed?: boolean): void;
  samples(amplitude: number, blocks?: number): void;
  releaseBlob?: () => void;
}
declare global { interface Window { __personaplexTransport: Transport } }

export async function mockedPersonaPlex(page: Page, options = { autoReady: true, autoAck: true, ackDelta: 1 }) {
  await page.addInitScript(({ autoReady, autoAck, ackDelta }) => {
    const originalAudio = window.AudioContext, originalSocket = window.WebSocket;
    const transport = {
      tracksStopped: 0, contextsClosed: 0, capturesDisconnected: 0, sourcesStarted: 0, sourcesStopped: 0,
      socketsClosed: 0, sampleRate: 0, messages: [] as ({ type?: string; id?: string } | number[])[], urls: [] as string[],
      socket: null as { bufferedAmount: number; onmessage?: (event: { data: string | ArrayBuffer | Blob }) => void } | null,
      capture: null as { port: { onmessage?: (event: { data: Float32Array }) => void } } | null,
      releaseBlob: undefined as (() => void) | undefined,
      emit(event: object) { this.socket?.onmessage?.({ data: JSON.stringify(event) }); },
      audio(generation: number, sampleIndex: number, samples = 1920, delayed = false) {
        const packet = new ArrayBuffer(13 + samples * 2), view = new DataView(packet);
        view.setUint8(0, 0x11); view.setUint32(1, generation, true); view.setBigUint64(5, BigInt(sampleIndex), true);
        for (let index = 0; index < samples; index++) view.setInt16(13 + index * 2, Math.sin(index * .13) * 12000, true);
        if (!delayed) this.socket?.onmessage?.({ data: packet });
        else {
          const blob = new Blob([packet]);
          Object.defineProperty(blob, 'arrayBuffer', { value: () => new Promise<ArrayBuffer>(resolve => {
            this.releaseBlob = () => resolve(packet);
          }) });
          this.socket?.onmessage?.({ data: blob });
        }
      },
      samples(amplitude: number, blocks = 1) {
        for (let index = 0; index < blocks; index++) this.capture?.port.onmessage?.({ data: new Float32Array(2048).fill(amplitude) });
      },
    };
    Object.assign(window, { __personaplexTransport: transport });
    class TestAudioContext extends originalAudio {
      constructor() { super(); transport.sampleRate = this.sampleRate; }
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
        const source = new originalAudio(), stream = source.createMediaStreamDestination().stream;
        for (const track of stream.getTracks()) {
          const stop = track.stop.bind(track);
          track.stop = () => { transport.tracksStopped++; stop(); void source.close(); };
        }
        return stream;
      },
    } });
    class TestCapture extends GainNode {
      port = { onmessage: undefined as ((event: { data: Float32Array }) => void) | undefined };
      constructor(context: AudioContext) { super(context); transport.capture = this; }
      disconnect() { transport.capturesDisconnected++; super.disconnect(); }
    }
    Object.defineProperty(window, 'AudioWorkletNode', { value: TestCapture });
    let generation = 0;
    class TestSocket {
      static OPEN = 1; static CONNECTING = 0; static CLOSING = 2; static CLOSED = 3;
      readyState = 0; bufferedAmount = 0; binaryType = 'blob';
      onmessage?: (event: { data: string | ArrayBuffer | Blob }) => void;
      onclose?: (event: object) => void;
      constructor(url: string | URL) {
        if (new URL(String(url), location.href).pathname !== '/api/avatar/personaplex') return new originalSocket(url) as unknown as TestSocket;
        transport.urls.push(String(url)); transport.socket = this; generation = 0;
        setTimeout(() => {
          this.readyState = 1;
          if (autoReady) transport.emit({ type: 'ready', protocol: 'personaplex-pcm-v1', sampleRate: 24000, frameSamples: 1920, format: 'pcm16le' });
        }, 0);
      }
      send(value: string | Uint8Array) {
        if (typeof value !== 'string') { transport.messages.push(Array.from(value)); return; }
        const event = JSON.parse(value); transport.messages.push(event);
        if (event.type === 'interrupt' && autoAck) {
          generation += ackDelta;
          setTimeout(() => transport.emit({ type: 'interrupted', id: event.id, generation }), 0);
        }
      }
      close() { transport.socketsClosed++; this.readyState = 3; this.onclose?.({}); }
    }
    Object.defineProperty(window, 'WebSocket', { value: TestSocket });
  }, options);
  await page.route('**/api/avatar/personaplex-session', route => route.fulfill({ json: {
    protocol: 'personaplex-pcm-v1', streamPath: '/api/avatar/personaplex', inputSampleRate: 24000, outputSampleRate: 24000,
    ticket: 'test_ticket_' + 'a'.repeat(40), expiresAt: new Date(Date.now() + 25_000).toISOString(),
  } }));
  await page.route(/\/api\/avatar\/(?:transcribe|conversation|speech|realtime|gemini-token)(?:\?|$)/, route => route.fulfill({ status: 503,
    json: { error: 'Experimental native PCM must not call another voice pipeline.' } }));
  await page.route(/\/__personaplex_harness(?:\?|$)/, route => route.fulfill({ contentType: 'text/html', body:
    `<!doctype html><html><body><div id="root"></div>
      <script type="module">
        import RefreshRuntime from '/@react-refresh'; RefreshRuntime.injectIntoGlobalHook(window);
        window.$RefreshReg$ = () => {}; window.$RefreshSig$ = () => type => type;
        window.__vite_plugin_react_preamble_installed__ = true;
      </script>
      <script type="module" src="/@vite/client"></script>
      <script type="module" src="/e2e/fixtures/personaplex-harness.tsx"></script>
    </body></html>`,
  }));
}
