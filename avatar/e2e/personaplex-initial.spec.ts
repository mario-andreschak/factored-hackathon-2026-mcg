import { test, expect, type Page } from '@playwright/test';
import { mockedPersonaPlex } from './fixtures/personaplex-transport';

declare global {
  interface Window {
    __initialProbe: { microphoneCalls: number; binaryTimes: number[] };
  }
}

const initialText = 'I have lots of energy. Help me get moving.';
const admission = () => ({
  protocol: 'personaplex-pcm-v1', streamPath: '/api/avatar/personaplex', inputSampleRate: 24000, outputSampleRate: 24000,
  ticket: 'test_initial_ticket_' + 'a'.repeat(40), expiresAt: new Date(Date.now() + 25_000).toISOString(),
  avatar: 'spark', transcript: initialText, initialContextDelivered: false,
});

async function startCapture(page: Page, observer = false) {
  await page.goto(`/__personaplex_harness?initial=1${observer ? '&observer=1' : ''}`);
  // Instrument the unchanged shared transport, after its init script has run.
  await page.evaluate(() => {
    window.__initialProbe = { microphoneCalls: 0, binaryTimes: [] };
    const originalMic = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = constraints => {
      window.__initialProbe.microphoneCalls++; return originalMic(constraints);
    };
    const originalSend = WebSocket.prototype.send;
    WebSocket.prototype.send = function (value) {
      if (value instanceof Uint8Array) window.__initialProbe.binaryTimes.push(performance.now());
      originalSend.call(this, value);
    };
  });
  await page.getByRole('button', { name: 'Connect experimental voice' }).click();
  await expect(page.getByTestId('initial-listening')).toHaveText('true');
}

async function firstUtterance(page: Page, voiceBlocks = 5) {
  await page.evaluate(voiceBlocks => {
    const transport = window.__personaplexTransport;
    transport.samples(.004, 4); // Below VAD, retained as a distinct pre-roll.
    transport.samples(.25, voiceBlocks);
    transport.samples(0, Math.ceil(.55 * transport.sampleRate / 2048));
  }, voiceBlocks);
}

async function evidence(page: Page) {
  return page.evaluate(() => {
    const transport = window.__personaplexTransport, harness = window.__personaplexHarness;
    return {
      urls: transport.urls, packets: transport.messages.filter(Array.isArray) as number[][],
      controls: transport.messages.filter(event => !Array.isArray(event)) as { type?: string; id?: string }[],
      binaryTimes: window.__initialProbe.binaryTimes, microphoneCalls: window.__initialProbe.microphoneCalls,
      tracksStopped: transport.tracksStopped, contextsClosed: transport.contextsClosed,
      capturesDisconnected: transport.capturesDisconnected, socketsClosed: transport.socketsClosed,
      sourcesStarted: transport.sourcesStarted, sourcesStopped: transport.sourcesStopped,
      selections: harness.initialSelections, initialTranscripts: harness.initialTranscripts,
      transcripts: harness.transcript, userUtterances: harness.userUtterances,
    };
  });
}

async function finish(page: Page) {
  await page.getByRole('button', { name: 'End experimental voice' }).click();
  await expect(page.getByTestId('connected')).toHaveText('false');
  const value = await evidence(page);
  expect(value).toMatchObject({ microphoneCalls: 1, tracksStopped: 1, contextsClosed: 1, capturesDisconnected: 1 });
  return value;
}

const signedSamples = (packet: number[]) => {
  const pcm = Buffer.from(packet.slice(1));
  return Array.from({ length: pcm.length / 2 }, (_, index) => pcm.readInt16LE(index * 2));
};

test('initial intake listens before admission, binds the selected role, and delivers text only after actual READY', async ({ page }) => {
  await mockedPersonaPlex(page, { autoReady: false, autoAck: true, ackDelta: 1 });
  const requests: { audio: string; format: string }[] = [];
  await page.route('**/api/avatar/personaplex-initial', route => {
    requests.push(route.request().postDataJSON()); return route.fulfill({ json: admission() });
  });
  await startCapture(page);
  await page.evaluate(() => window.__personaplexTransport.samples(.004, 4));
  expect(requests).toEqual([]);
  expect(await evidence(page)).toMatchObject({ urls: [], packets: [], initialTranscripts: [], microphoneCalls: 1 });
  await firstUtterance(page);
  await expect.poll(() => requests.length).toBe(1);
  await expect.poll(async () => (await evidence(page)).urls.length).toBe(1);
  await expect(page.getByTestId('initial-listening')).toHaveText('false');
  await expect(page.getByTestId('initial-avatar')).toHaveText('spark');
  await expect(page.getByTestId('connected')).toHaveText('false');
  expect(await evidence(page)).toMatchObject({ selections: ['spark'], initialTranscripts: [], packets: [] });
  expect(Object.keys(requests[0]).sort()).toEqual(['audio', 'format']);
  const wav = Buffer.from(requests[0].audio, 'base64');
  expect(requests[0].format).toBe('wav'); expect(wav.toString('ascii', 0, 4)).toBe('RIFF');
  expect(wav.readUInt32LE(24)).toBe(24000);
  expect(wav.readUInt32LE(40) / 2 / 24000).toBeLessThanOrEqual(12);
  await page.evaluate(() => window.__personaplexTransport.emit({ type: 'ready', protocol: 'personaplex-pcm-v1', sampleRate: 24000, frameSamples: 1920, format: 'pcm16le' }));
  await expect(page.getByTestId('connected')).toHaveText('true');
  await expect.poll(async () => (await evidence(page)).initialTranscripts.length).toBe(1);
  expect((await evidence(page)).initialTranscripts[0].text).toBe(initialText);
  const stopped = await finish(page); expect(stopped.socketsClosed).toBe(1);
});

test('initial PCM is a finite normal-speed prefix with one history delivery and no observer duplicate', async ({ page }) => {
  await mockedPersonaPlex(page);
  const requests: string[] = [];
  page.on('request', request => { if (/\/api\/avatar\//.test(request.url())) requests.push(new URL(request.url()).pathname); });
  await page.route('**/api/avatar/personaplex-initial', route => route.fulfill({ json: admission() }));
  await startCapture(page, true); await firstUtterance(page);
  await expect(page.getByTestId('connected')).toHaveText('true');
  // Quiet real microphone events must not interleave with the recorded prefix.
  await page.evaluate(() => window.__personaplexTransport.samples(0, 6));
  await page.evaluate(() => window.__personaplexTransport.audio(0, 0, 1920));
  await expect.poll(async () => (await evidence(page)).sourcesStarted).toBe(1);
  await page.waitForTimeout(1400);
  const prefix = await evidence(page);
  expect(prefix.packets.length).toBeGreaterThan(5);
  expect(prefix.packets.every(packet => packet[0] === 0x10 && packet.length === 3841)).toBe(true);
  const samples = prefix.packets.flatMap(signedSamples);
  expect(samples.some(sample => sample > 7500)).toBe(true);
  expect(samples.slice(0, 1920).some(sample => sample > 50 && sample < 300)).toBe(true);
  expect(samples.slice(-128).every(sample => sample === 0)).toBe(true);
  const gaps = prefix.binaryTimes.slice(1).map((time, index) => time - prefix.binaryTimes[index]);
  expect(gaps.every(gap => gap >= 55)).toBe(true);
  expect(prefix.binaryTimes.at(-1)! - prefix.binaryTimes[0]).toBeGreaterThanOrEqual((prefix.packets.length - 1) * 65);
  expect(prefix.initialTranscripts).toHaveLength(1); expect(prefix.transcripts).toHaveLength(1);
  expect(prefix.userUtterances).toBe(0); expect(prefix.controls).toEqual([]);
  expect(requests).toEqual(['/api/avatar/personaplex-initial']);
  await page.waitForTimeout(200);
  expect((await evidence(page)).packets).toHaveLength(prefix.packets.length);
  await page.evaluate(() => window.__personaplexTransport.samples(0, 2));
  expect((await evidence(page)).packets.length).toBeGreaterThan(prefix.packets.length);
  await finish(page);
});

test('NEW speech during replay drops the unsent prefix and holds output through matching ACK and real quiet', async ({ page }) => {
  await mockedPersonaPlex(page, { autoReady: true, autoAck: false, ackDelta: 1 });
  await page.route('**/api/avatar/personaplex-initial', route => route.fulfill({ json: admission() }));
  await startCapture(page); await firstUtterance(page, 18);
  await expect(page.getByTestId('connected')).toHaveText('true');
  await page.evaluate(() => {
    window.__personaplexTransport.samples(.003, 6);
    window.__personaplexTransport.audio(0, 0, 1920);
  });
  await expect.poll(async () => (await evidence(page)).sourcesStarted).toBe(1);
  await page.evaluate(() => window.__personaplexTransport.samples(.45, 3));
  await expect.poll(async () => (await evidence(page)).controls.length).toBe(1);
  const barge = await evidence(page);
  expect(barge.controls[0].type).toBe('interrupt');
  expect(barge.sourcesStopped).toBeGreaterThan(0);
  const handoffPacket = barge.packets.find(packet => packet.length > 3841)!;
  expect(handoffPacket).toBeDefined();
  const handoff = signedSamples(handoffPacket);
  expect(handoff.length).toBeLessThanOrEqual(4800);
  expect(handoff.some(sample => sample > 50 && sample < 200)).toBe(true);
  expect(handoff.some(sample => sample > 14000)).toBe(true);
  const fenceIndex = barge.packets.length;
  await page.waitForTimeout(200);
  expect((await evidence(page)).packets).toHaveLength(fenceIndex);
  await page.evaluate(() => {
    window.__personaplexTransport.samples(0, Math.ceil(.55 * window.__personaplexTransport.sampleRate / 2048));
    window.__personaplexTransport.audio(1, 1920, 1920);
    window.__personaplexTransport.emit({ type: 'transcript', role: 'assistant', generation: 0, id: 'old-replay', text: 'Old replay response.', done: true });
  });
  await page.waitForTimeout(30);
  expect((await evidence(page)).sourcesStarted).toBe(barge.sourcesStarted);
  await page.evaluate(id => {
    window.__personaplexTransport.emit({ type: 'interrupted', id, generation: 1 });
    window.__personaplexTransport.audio(1, 3840, 1920);
  }, barge.controls[0].id);
  await expect.poll(async () => (await evidence(page)).sourcesStarted).toBe(barge.sourcesStarted + 1);
  const resumed = await evidence(page);
  expect(resumed.packets.slice(fenceIndex).flatMap(signedSamples).some(sample => sample > 7500 && sample < 8500)).toBe(false);
  expect(resumed.initialTranscripts).toHaveLength(1);
  expect(resumed.transcripts.some(row => row.id === 'old-replay')).toBe(false);
  expect(resumed.userUtterances).toBe(1);
  await finish(page);
});

test('NEW speech cancels a held initial HTTP request and late selection never opens a socket or delivers intent', async ({ page }) => {
  await mockedPersonaPlex(page);
  let release!: () => void; const held = new Promise<void>(resolve => { release = resolve; });
  let requests = 0, abortedRequests = 0;
  page.on('requestfailed', request => { if (new URL(request.url()).pathname === '/api/avatar/personaplex-initial') abortedRequests++; });
  await page.route('**/api/avatar/personaplex-initial', async route => {
    requests++; await held; await route.fulfill({ json: admission() }).catch(() => {});
  });
  await startCapture(page); await firstUtterance(page);
  await expect.poll(() => requests).toBe(1);
  await page.evaluate(() => window.__personaplexTransport.samples(.45, 3));
  await expect(page.getByTestId('error')).toContainText('interrupted');
  release(); await page.waitForTimeout(100);
  await expect.poll(() => abortedRequests).toBe(1);
  const stopped = await evidence(page);
  expect(stopped).toMatchObject({ urls: [], packets: [], selections: [], initialTranscripts: [], microphoneCalls: 1,
    tracksStopped: 1, contextsClosed: 1, capturesDisconnected: 1 });
  await expect(page.getByTestId('initial-listening')).toHaveText('false');
  expect(requests).toBe(1);
});

test('muting during replay erases the recorded prefix and preserves live zero PCM clock', async ({ page }) => {
  await mockedPersonaPlex(page);
  await page.route('**/api/avatar/personaplex-initial', route => route.fulfill({ json: admission() }));
  await startCapture(page); await firstUtterance(page, 18);
  await expect(page.getByTestId('connected')).toHaveText('true');
  await expect.poll(async () => (await evidence(page)).packets.length).toBeGreaterThan(0);
  await page.getByRole('button', { name: 'Mute experimental voice' }).click();
  await expect(page.getByTestId('muted')).toHaveText('true');
  const before = await evidence(page);
  await page.evaluate(() => window.__personaplexTransport.samples(.45, 4));
  const muted = await evidence(page), zeroPackets = muted.packets.slice(before.packets.length);
  expect(zeroPackets).toHaveLength(4);
  expect(zeroPackets.every(packet => packet.slice(1).every(byte => byte === 0))).toBe(true);
  await page.waitForTimeout(240);
  expect((await evidence(page)).packets).toHaveLength(muted.packets.length);
  expect(muted.initialTranscripts).toHaveLength(1); expect(muted.userUtterances).toBe(0);
  await finish(page);
});

test('an unfinished first utterance exceeding twelve seconds is rejected before ASR or native admission', async ({ page }) => {
  await mockedPersonaPlex(page);
  const requests: string[] = [];
  page.on('request', request => { if (/\/api\/avatar\//.test(request.url())) requests.push(new URL(request.url()).pathname); });
  await page.route('**/api/avatar/personaplex-initial', route => route.fulfill({ json: admission() }));
  await startCapture(page);
  await page.evaluate(() => window.__personaplexTransport.samples(.25, Math.ceil(12.2 * window.__personaplexTransport.sampleRate / 2048)));
  await expect(page.getByTestId('error')).toContainText('shorter thought');
  await expect(page.getByTestId('initial-listening')).toHaveText('false');
  expect(requests).toEqual([]);
  expect(await evidence(page)).toMatchObject({ urls: [], packets: [], selections: [], initialTranscripts: [],
    microphoneCalls: 1, tracksStopped: 1, contextsClosed: 1, capturesDisconnected: 1 });
});

test('ending an initial replay cancels its finite timer and late packets cannot revive its single microphone session', async ({ page }) => {
  await mockedPersonaPlex(page);
  await page.route('**/api/avatar/personaplex-initial', route => route.fulfill({ json: admission() }));
  await startCapture(page); await firstUtterance(page, 18);
  await expect(page.getByTestId('connected')).toHaveText('true');
  await expect.poll(async () => (await evidence(page)).packets.length).toBeGreaterThan(0);
  const stopped = await finish(page);
  await page.evaluate(() => {
    window.__personaplexTransport.samples(.45, 6);
    window.__personaplexTransport.audio(0, 0, 1920);
    window.__personaplexTransport.emit({ type: 'transcript', role: 'assistant', generation: 0, id: 'late-initial', text: 'Late initial audio.', done: true });
  });
  await page.waitForTimeout(260);
  const later = await evidence(page);
  expect(later.packets).toHaveLength(stopped.packets.length);
  expect(later.sourcesStarted).toBe(stopped.sourcesStarted);
  expect(later.transcripts).toEqual(stopped.transcripts);
  expect(later.socketsClosed).toBe(1);
});

test('malformed native admission cannot publish an initial role, history or socket', async ({ page }) => {
  await mockedPersonaPlex(page);
  await page.route('**/api/avatar/personaplex-initial', route => route.fulfill({ json: { ...admission(), ticket: 'invalid' } }));
  await startCapture(page); await firstUtterance(page);
  await expect(page.getByTestId('error')).toContainText('Invalid native voice admission');
  await expect(page.getByTestId('initial-avatar')).toHaveText('moss');
  expect(await evidence(page)).toMatchObject({ urls: [], packets: [], selections: [], initialTranscripts: [],
    microphoneCalls: 1, tracksStopped: 1, contextsClosed: 1, capturesDisconnected: 1 });
});

test('speech onset during the last replay drain preserves real preroll, VAD carry and only fresh observer context', async ({ page }) => {
  await mockedPersonaPlex(page, { autoReady: false, autoAck: true, ackDelta: 1 });
  let replayFrames = 0;
  const observedBodies: { audio: string; format: string }[] = [];
  await page.route('**/api/avatar/personaplex-initial', route => {
    const wav = Buffer.from(route.request().postDataJSON().audio, 'base64');
    replayFrames = Math.ceil(wav.readUInt32LE(40) / 2 / 1920);
    return route.fulfill({ json: admission() });
  });
  await page.route('**/api/avatar/transcribe', route => {
    observedBodies.push(route.request().postDataJSON());
    return route.fulfill({ json: { text: 'A fresh live thought.' } });
  });
  await startCapture(page, true); await firstUtterance(page);
  await expect.poll(async () => (await evidence(page)).urls.length).toBe(1);
  await page.clock.install();
  await page.clock.pauseAt(new Date(Date.now() + 1000));
  await page.evaluate(() => window.__personaplexTransport.emit({ type: 'ready', protocol: 'personaplex-pcm-v1', sampleRate: 24000, frameSamples: 1920, format: 'pcm16le' }));
  await expect(page.getByTestId('connected')).toHaveText('true');
  await page.clock.runFor((replayFrames - 1) * 80);
  expect((await evidence(page)).packets).toHaveLength(replayFrames);
  // One worklet block is <80ms: onset exists but has not reached VAD admission.
  await page.evaluate(() => window.__personaplexTransport.samples(.45, 1));
  expect((await evidence(page)).controls).toEqual([]);
  await page.clock.runFor(80);
  const completed = await evidence(page);
  expect(completed.packets).toHaveLength(replayFrames + 1);
  expect(signedSamples(completed.packets.at(-1)!).every(sample => sample > 14000)).toBe(true);
  // The second block must complete the existing onset, rather than start over.
  await page.evaluate(() => window.__personaplexTransport.samples(.45, 1));
  expect((await evidence(page)).controls.filter(control => control.type === 'interrupt')).toHaveLength(1);
  await page.clock.runFor(1);
  await page.evaluate(() => {
    window.__personaplexTransport.samples(.45, 1);
    window.__personaplexTransport.samples(0, Math.ceil(.55 * window.__personaplexTransport.sampleRate / 2048));
  });
  await expect.poll(() => observedBodies.length).toBe(1);
  await expect.poll(async () => (await evidence(page)).transcripts.map(row => row.text)).toEqual([initialText, 'A fresh live thought.']);
  const observed = Buffer.from(observedBodies[0].audio, 'base64');
  expect(observed.readUInt32LE(24)).toBe(16000);
  expect(observed.readUInt32LE(40) / 2 / 16000).toBeLessThan(.8);
  expect(Array.from({ length: 32 }, (_, index) => observed.readInt16LE(44 + index * 2)).every(sample => sample > 14000)).toBe(true);
  expect((await evidence(page)).initialTranscripts).toHaveLength(1);
  await finish(page);
});
