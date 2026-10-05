import { test, expect, type Page } from '@playwright/test';

async function mockedRouter(page: Page) {
  await page.addInitScript(() => {
    const originalAudio = window.AudioContext;
    const transport = {
      tracksStopped: 0, contextsClosed: 0, capturesDisconnected: 0, sourcesStarted: 0, sourcesStopped: 0,
      capture: null as { port: { onmessage?: (event: { data: Float32Array }) => void }; context: AudioContext } | null,
      emit(amplitude: number, seconds: number) {
        if (!this.capture) throw new Error('No capture is connected');
        const frames = Math.ceil(seconds * this.capture.context.sampleRate / 2048);
        for (let i = 0; i < frames; i++) this.capture.port.onmessage?.({ data: new Float32Array(2048).fill(amplitude) });
      },
    };
    Object.assign(window, { __routerTransport: transport });
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
        const source = new originalAudio();
        const stream = source.createMediaStreamDestination().stream;
        for (const track of stream.getTracks()) {
          const nativeStop = track.stop.bind(track);
          track.stop = () => { transport.tracksStopped++; nativeStop(); void source.close(); };
        }
        return stream;
      },
    } });
    // A real AudioNode connects through the hook's actual Web Audio graph. Its
    // deterministic capture port replaces physical microphone samples only.
    class TestCapture extends GainNode {
      port = { onmessage: undefined as ((event: { data: Float32Array }) => void) | undefined };
      constructor(context: AudioContext) { super(context); transport.capture = this; }
      disconnect() { transport.capturesDisconnected++; super.disconnect(); }
    }
    Object.defineProperty(window, 'AudioWorkletNode', { value: TestCapture });
  });
  await page.route(/\/api\/avatar\/(?:transcribe|conversation|speech)(?:\?|$)/, route => route.fulfill({ status: 503,
    json: { error: 'No test fixture matched this paid voice operation.' } }));
  await page.route('**/__router_harness', route => route.fulfill({ contentType: 'text/html', body:
    `<!doctype html><html><body><div id="root"></div>
      <script type="module">
        import RefreshRuntime from '/@react-refresh'; RefreshRuntime.injectIntoGlobalHook(window);
        window.$RefreshReg$ = () => {}; window.$RefreshSig$ = () => (type) => type;
        window.__vite_plugin_react_preamble_installed__ = true;
      </script>
      <script type="module" src="/@vite/client"></script>
      <script type="module" src="/e2e/fixtures/router-harness.tsx"></script>
    </body></html>`,
  }));
}
async function connect(page: Page) {
  await page.goto('/__router_harness');
  await page.getByRole('button', { name: 'Connect router voice' }).click();
  await expect(page.getByTestId('connected')).toHaveText('true');
  await expect(page.getByTestId('phase')).toHaveText('listening');
}
async function samples(page: Page, amplitude: number, seconds: number) {
  await page.evaluate(({ amplitude, seconds }) => (window as Window & { __routerTransport: { emit(amplitude: number, seconds: number): void } }).__routerTransport.emit(amplitude, seconds), { amplitude, seconds });
}
async function sendText(page: Page, message: string) {
  await page.getByLabel('Router fixture request').fill(message);
  await page.getByRole('button', { name: 'Send router text' }).click();
}
async function evidence(page: Page) {
  return page.evaluate(() => {
    const value = (window as Window & { __routerTransport: {
      tracksStopped: number; contextsClosed: number; capturesDisconnected: number; sourcesStarted: number; sourcesStopped: number;
    } }).__routerTransport;
    return { tracksStopped: value.tracksStopped, contextsClosed: value.contextsClosed, capturesDisconnected: value.capturesDisconnected,
      sourcesStarted: value.sourcesStarted, sourcesStopped: value.sourcesStopped };
  });
}
function pcmSpeech(page: Page, duration = .25) {
  return page.route('**/api/avatar/speech', route => route.fulfill({ status: 200, contentType: 'audio/pcm',
    headers: { 'X-Audio-Sample-Rate': '24000' }, body: Buffer.alloc(Math.ceil(duration * 24000) * 2) }));
}

test('captured speech becomes a real WAV, streamed words drive PCM playback and resources close', async ({ page }) => {
  await mockedRouter(page);
  let recording: { audio: string; format: string } | undefined;
  const turns: Record<string, unknown>[] = [];
  await page.route('**/api/avatar/transcribe', route => {
    recording = route.request().postDataJSON(); return route.fulfill({ json: { text: 'Hello from a captured test utterance' } });
  });
  await page.route('**/api/avatar/conversation', route => {
    turns.push(route.request().postDataJSON());
    return route.fulfill({ contentType: 'application/x-ndjson', body:
      JSON.stringify({ type: 'text', delta: 'Hello traveler. We can take our time.' }) + '\n' +
      JSON.stringify({ type: 'tool', name: 'set_world', id: 'world-1', args: { avatar: 'orbit', sceneIndex: 2 } }) + '\n' });
  });
  await pcmSpeech(page); await connect(page);
  await samples(page, .04, .6); await samples(page, 0, .6);
  await expect.poll(() => turns.length).toBe(1);
  expect(turns[0]).toMatchObject({ message: 'Hello from a captured test utterance', avatar: 'moss', history: [] });
  expect(recording?.format).toBe('wav');
  const wav = Buffer.from(recording!.audio, 'base64');
  expect(wav.toString('ascii', 0, 4)).toBe('RIFF');
  expect(wav.toString('ascii', 8, 12)).toBe('WAVE');
  expect(wav.readUInt16LE(22)).toBe(1);
  await expect.poll(() => page.evaluate(() => window.__routerHarness.worlds)).toEqual([{ avatar: 'orbit', scene: 2 }]);
  await expect.poll(async () => (await evidence(page)).sourcesStarted).toBeGreaterThan(0);
  await expect(page.getByTestId('phase')).toHaveText('listening');
  await expect.poll(() => page.evaluate(() => window.__routerHarness.transcript.some(item => item.role === 'assistant' && item.done))).toBe(true);
  await page.getByRole('button', { name: 'End router voice' }).click();
  await expect(page.getByTestId('connected')).toHaveText('false');
  expect(await evidence(page)).toMatchObject({ tracksStopped: 1, contextsClosed: 1, capturesDisconnected: 1 });
});

test('interruption stops scheduled PCM and muted microphone samples never dispatch transcription', async ({ page }) => {
  await mockedRouter(page);
  let transcriptions = 0;
  await page.route('**/api/avatar/transcribe', route => { transcriptions++; return route.fulfill({ json: { text: 'Should not run while muted' } }); });
  await page.route('**/api/avatar/conversation', route => route.fulfill({ contentType: 'application/x-ndjson',
    body: JSON.stringify({ type: 'text', delta: 'Here is a sentence long enough to speak.' }) + '\n' }));
  await pcmSpeech(page, 3); await connect(page);
  await sendText(page, 'Say something');
  await expect(page.getByTestId('phase')).toHaveText('speaking');
  await page.getByRole('button', { name: 'Interrupt router voice' }).click();
  await expect(page.getByTestId('phase')).toHaveText('listening');
  expect((await evidence(page)).sourcesStopped).toBeGreaterThan(0);
  await page.getByRole('button', { name: 'Mute router voice' }).click();
  await expect(page.getByTestId('muted')).toHaveText('true');
  await samples(page, .04, .6); await samples(page, 0, .6);
  expect(transcriptions).toBe(0);
  await page.getByRole('button', { name: 'End router voice' }).click();
  expect(await evidence(page)).toMatchObject({ tracksStopped: 1, contextsClosed: 1, capturesDisconnected: 1 });
});

test('an interrupted delegated read resumes once and late results never cross a disconnected session', async ({ page }) => {
  await mockedRouter(page);
  const turns: Record<string, unknown>[] = [];
  await page.route('**/api/avatar/conversation', route => {
    const body = route.request().postDataJSON(); turns.push(body);
    return route.fulfill({ contentType: 'application/x-ndjson', body: body.backendResult
      ? JSON.stringify({ type: 'text', delta: 'The actual synthetic read returned safely.' }) + '\n'
      : JSON.stringify({ type: 'tool', name: 'delegate_task', id: 'read-1', args: { message: 'One owned read' } }) + '\n' });
  });
  await pcmSpeech(page); await connect(page);
  await sendText(page, 'Check my transaction');
  await expect.poll(() => page.evaluate(() => window.__routerHarness.tasks)).toEqual(['One owned read']);
  await page.getByRole('button', { name: 'Interrupt router voice' }).click();
  await page.evaluate(() => window.__routerHarness.resolveTask?.({ reply: 'Synthetic verified bank result', mode: 'flujo', status: 'completed' }));
  await expect.poll(() => turns.length).toBe(2);
  expect(turns[1]).toMatchObject({ backendResult: { reply: 'Synthetic verified bank result', mode: 'flujo', status: 'completed' } });
  await expect(page.getByTestId('phase')).toHaveText('listening');
  await sendText(page, 'Second owned read');
  await expect.poll(() => page.evaluate(() => window.__routerHarness.tasks.length)).toBe(2);
  await page.getByRole('button', { name: 'End router voice' }).click();
  await page.evaluate(() => window.__routerHarness.resolveTask?.({ reply: 'Late prior-session result' }));
  await page.waitForTimeout(100);
  expect(turns).toHaveLength(3);
  await page.getByRole('button', { name: 'Connect router voice' }).click();
  await expect(page.getByTestId('connected')).toHaveText('true');
  await sendText(page, 'Fresh session read');
  await expect.poll(() => page.evaluate(() => window.__routerHarness.tasks.length)).toBe(3);
  await page.getByRole('button', { name: 'End router voice' }).click();
  expect(await evidence(page)).toMatchObject({ tracksStopped: 2, contextsClosed: 2, capturesDisconnected: 2 });
});

test('a completed background read waits while the user is speaking and resumes after their turn', async ({ page }) => {
  await mockedRouter(page);
  const turns: Record<string, unknown>[] = [];
  await page.route('**/api/avatar/transcribe', route => route.fulfill({ json: { text: 'I am still explaining my problem' } }));
  await page.route('**/api/avatar/conversation', route => {
    const body = route.request().postDataJSON(); turns.push(body);
    const event = body.backendResult ? { type: 'text', delta: 'The completed bank read is ready now.' }
      : body.message === 'First bank inquiry' ? { type: 'tool', name: 'delegate_task', id: 'background-1', args: { message: 'First owned inquiry' } }
      : { type: 'text', delta: 'I heard the extra detail you just shared.' };
    return route.fulfill({ contentType: 'application/x-ndjson', body: JSON.stringify(event) + '\n' });
  });
  await pcmSpeech(page); await connect(page);
  await sendText(page, 'First bank inquiry');
  await expect.poll(() => page.evaluate(() => window.__routerHarness.tasks.length)).toBe(1);
  await samples(page, .04, .5);
  await page.evaluate(() => window.__routerHarness.resolveTask?.({ reply: 'Actual completed synthetic inquiry', mode: 'flujo', status: 'completed' }));
  await page.waitForTimeout(100);
  expect(turns).toHaveLength(1);
  await samples(page, 0, .6);
  await expect.poll(() => turns.length).toBe(3);
  expect(turns[1]).toMatchObject({ message: 'I am still explaining my problem' });
  expect(turns[2]).toMatchObject({ backendResult: { reply: 'Actual completed synthetic inquiry' } });
  await expect(page.getByTestId('phase')).toHaveText('listening');
  await page.getByRole('button', { name: 'End router voice' }).click();
  expect(await evidence(page)).toMatchObject({ tracksStopped: 1, contextsClosed: 1, capturesDisconnected: 1 });
});
