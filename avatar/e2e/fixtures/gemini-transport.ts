import type { Page } from '@playwright/test';

export async function mockedGemini(page: Page) {
  await page.addInitScript(() => {
    const originalAudio = window.AudioContext;
    const originalSocket = window.WebSocket;
    const transport = {
      tracksStopped: 0, contextsClosed: 0, capturesDisconnected: 0, sourcesStarted: 0, sourcesStopped: 0, socketsClosed: 0,
      messages: [] as Record<string, unknown>[], urls: [] as string[],
      capture: null as { port: { onmessage?: (event: { data: Float32Array }) => void } } | null,
      socket: null as { onmessage?: (event: { data: string | Blob }) => void } | null,
      emit(event: object, blob = false) { return this.socket?.onmessage?.({ data: blob ? new Blob([JSON.stringify(event)]) : JSON.stringify(event) }); },
      samples(amplitude: number) { this.capture?.port.onmessage?.({ data: new Float32Array(2048).fill(amplitude) }); },
    };
    Object.assign(window, { __geminiTransport: transport });
    class TestAudioContext extends originalAudio {
      close() { transport.contextsClosed++; return super.close(); }
      createBufferSource() {
        const source = super.createBufferSource();
        const start = source.start.bind(source), stop = source.stop.bind(source);
        source.start = (...args: Parameters<typeof source.start>) => { transport.sourcesStarted++; start(...args); };
        source.stop = (...args: Parameters<typeof source.stop>) => { transport.sourcesStopped++; stop(...args); };
        return source;
      }
    }
    Object.defineProperty(window, 'AudioContext', { value: TestAudioContext });
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: {
      async getUserMedia() {
        const source = new originalAudio(); const stream = source.createMediaStreamDestination().stream;
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
    class TestSocket {
      static OPEN = 1; static CONNECTING = 0; static CLOSING = 2; static CLOSED = 3;
      readyState = 0; binaryType = 'blob';
      onopen?: (event: object) => void;
      onmessage?: (event: { data: string | Blob }) => void;
      onclose?: (event: { code: number; reason: string; wasClean: boolean }) => void;
      constructor(url: string) {
        // Keep Vite's local development socket native; only replace the provider.
        if (!url.startsWith('wss://generativelanguage.googleapis.com/')) return new originalSocket(url) as unknown as TestSocket;
        transport.urls.push(url); transport.socket = this;
        setTimeout(() => { this.readyState = 1; this.onopen?.({}); }, 0);
      }
      send(message: string) {
        const event = JSON.parse(message); transport.messages.push(event);
        if (event.setup) void transport.emit({ setupComplete: {} });
      }
      close() { transport.socketsClosed++; this.readyState = 3; this.onclose?.({ code: 1000, reason: '', wasClean: true }); }
    }
    Object.defineProperty(window, 'WebSocket', { value: TestSocket });
  });
  // Native Live must never make a separate STT/chat/TTS request.
  await page.route(/\/api\/avatar\/(?:transcribe|conversation|speech)(?:\?|$)/, route => route.fulfill({ status: 503,
    json: { error: 'A native Live test must not call chained audio endpoints.' } }));
  await page.route('**/api/avatar/realtime**', route => route.fulfill({ status: 503, json: { error: 'The native fixture must not call OpenAI.' } }));
  await page.route('**/api/avatar/gemini-token', route => route.fulfill({ json: {
    token: 'auth_tokens/e2e-short-lived', model: 'gemini-3.8-live',
    websocketUrl: 'wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained',
    expiresAt: new Date(Date.now() + 30 * 60_000).toISOString(), newSessionExpiresAt: new Date(Date.now() + 60_000).toISOString(),
    setup: { model: 'models/gemini-3.8-live' },
  } }));
  await page.route('**/__gemini_harness', route => route.fulfill({ contentType: 'text/html', body:
    `<!doctype html><html><body><div id="root"></div>
      <script type="module">
        import RefreshRuntime from '/@react-refresh'; RefreshRuntime.injectIntoGlobalHook(window);
        window.$RefreshReg$ = () => {}; window.$RefreshSig$ = () => (type) => type;
        window.__vite_plugin_react_preamble_installed__ = true;
      </script>
      <script type="module" src="/@vite/client"></script>
      <script type="module" src="/e2e/fixtures/gemini-harness.tsx"></script>
    </body></html>`,
  }));
}
