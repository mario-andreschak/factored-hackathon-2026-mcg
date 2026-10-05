import { test, expect, type Page } from '@playwright/test';

import { mockedPersonaPlex } from './fixtures/personaplex-transport';

async function connect(page: Page) {
  await page.goto('/__personaplex_harness');
  await page.getByRole('button', { name: 'Connect experimental voice' }).click();
  await expect(page.getByTestId('connected')).toHaveText('true');
}
async function evidence(page: Page) {
  return page.evaluate(() => {
    const value = window.__personaplexTransport;
    return { tracksStopped: value.tracksStopped, contextsClosed: value.contextsClosed,
      capturesDisconnected: value.capturesDisconnected, sourcesStarted: value.sourcesStarted,
      sourcesStopped: value.sourcesStopped, socketsClosed: value.socketsClosed, sampleRate: value.sampleRate,
      messages: value.messages, urls: value.urls };
  });
}

async function startAndObserveSpeaking(page: Page, generation: number, sampleIndex: number) {
  const observed = await page.evaluate(async ({ generation, sampleIndex }) => {
    window.__personaplexTransport.audio(generation, sampleIndex, 5760);
    const deadline = performance.now() + 1000;
    let phase = '';
    do {
      phase = document.querySelector('[data-testid="phase"]')?.textContent || '';
      if (phase === 'speaking') break;
      await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
    } while (performance.now() < deadline);
    return { phase, sourcesStarted: window.__personaplexTransport.sourcesStarted };
  }, { generation, sampleIndex });
  expect(observed.phase).toBe('speaking');
  expect(observed.sourcesStarted).toBeGreaterThan(0);
}

test('experimental PCM hook waits for readiness and preserves continuous mute clock without chained voice requests', async ({ page }) => {
  await mockedPersonaPlex(page, { autoReady: false, autoAck: true, ackDelta: 1 });
  const chained: string[] = [];
  page.on('request', request => { if (/\/api\/avatar\/(?:transcribe|conversation|speech|realtime|gemini-token)(?:\?|$)/.test(request.url())) chained.push(request.url()); });
  await page.goto('/__personaplex_harness');
  await page.getByRole('button', { name: 'Connect experimental voice' }).click();
  await expect.poll(async () => (await evidence(page)).urls.length).toBe(1);
  await page.evaluate(() => window.__personaplexTransport.samples(.005, 2));
  expect((await evidence(page)).messages).toHaveLength(0);
  await page.evaluate(() => window.__personaplexTransport.emit({ type: 'ready', protocol: 'personaplex-pcm-v1', sampleRate: 24000, frameSamples: 1920, format: 'pcm16le' }));
  await expect(page.getByTestId('connected')).toHaveText('true');
  await page.evaluate(() => window.__personaplexTransport.samples(.005, 4));
  await page.getByRole('button', { name: 'Mute experimental voice' }).click();
  await expect(page.getByTestId('muted')).toHaveText('true');
  await page.evaluate(() => window.__personaplexTransport.samples(.3, 2));
  const value = await evidence(page), binary = value.messages.filter(Array.isArray) as number[][];
  expect(binary).toHaveLength(6);
  expect(binary.every(packet => packet[0] === 0x10 && (packet.length - 1) % 2 === 0)).toBe(true);
  const targetSamples = binary.reduce((sum, packet) => sum + (packet.length - 1) / 2, 0);
  expect(targetSamples).toBe(Math.floor(6 * 2048 / value.sampleRate * 24000));
  // At most one fractional interval carries pre-mute PCM; the rest is zero.
  expect(binary.slice(-2).every(packet => packet.slice(3).every(byte => byte === 0))).toBe(true);
  expect(chained).toEqual([]);
  await startAndObserveSpeaking(page, 0, 0);
  await page.getByRole('button', { name: 'End experimental voice' }).click();
  expect(await evidence(page)).toMatchObject({ tracksStopped: 1, contextsClosed: 1, capturesDisconnected: 1, socketsClosed: 1 });
});

test('experimental manual stop holds output until new user speech and drops canceled assistant generations', async ({ page }) => {
  await mockedPersonaPlex(page); await connect(page);
  await startAndObserveSpeaking(page, 0, 0);
  // Keep an actual source live while clicking; phase polling can outlast a short buffer.
  await page.evaluate(async () => {
    window.__personaplexTransport.audio(0, 5760, 1920);
    await Promise.resolve(); await Promise.resolve();
    [...document.querySelectorAll('button')].find(button => button.textContent === 'Interrupt experimental voice')!.click();
  });
  await expect(page.getByTestId('phase')).toHaveText('listening');
  expect((await evidence(page)).sourcesStopped).toBeGreaterThan(0);
  await page.waitForTimeout(30);
  const held = (await evidence(page)).sourcesStarted;
  await page.evaluate(() => {
    window.__personaplexTransport.audio(1, 7680, 1920);
    window.__personaplexTransport.emit({ type: 'transcript', role: 'assistant', generation: 0, id: 'old-voice', text: 'Canceled old speech.', done: true });
    window.__personaplexTransport.emit({ type: 'transcript', role: 'user', id: 'new-user', text: 'Please continue.', done: true });
  });
  await page.waitForTimeout(30);
  expect((await evidence(page)).sourcesStarted).toBe(held);
  expect(await page.evaluate(() => window.__personaplexHarness.transcript.some(row => row.text === 'Canceled old speech.'))).toBe(false);
  expect(await page.evaluate(() => window.__personaplexHarness.transcript.some(row => row.text === 'Please continue.'))).toBe(true);
  await page.evaluate(() => window.__personaplexTransport.samples(.3, 3));
  await page.waitForTimeout(30);
  await page.evaluate(() => window.__personaplexTransport.samples(0, 12));
  await page.evaluate(() => window.__personaplexTransport.audio(2, 9600, 5760));
  await expect.poll(async () => (await evidence(page)).sourcesStarted).toBe(held + 1);
  await page.getByRole('button', { name: 'End experimental voice' }).click();
});

test('experimental interruption rejects an ACK that fails to advance the request generation', async ({ page }) => {
  await mockedPersonaPlex(page, { autoReady: true, autoAck: true, ackDelta: 0 }); await connect(page);
  await page.getByRole('button', { name: 'Interrupt experimental voice' }).click();
  await expect(page.getByTestId('connected')).toHaveText('false');
  await expect(page.getByTestId('error')).not.toBeEmpty();
  await expect(page.getByTestId('phase')).toHaveText('idle');
});

test('experimental new-generation audio before ACK remains held then resumes after user silence', async ({ page }) => {
  await mockedPersonaPlex(page, { autoReady: true, autoAck: false, ackDelta: 1 }); await connect(page);
  await page.evaluate(() => window.__personaplexTransport.samples(.3, 3));
  await expect.poll(async () => (await evidence(page)).messages.filter(event => !Array.isArray(event) && event.type === 'interrupt').length).toBe(1);
  await page.evaluate(() => {
    const control = window.__personaplexTransport.messages.find(event => !Array.isArray(event) && event.type === 'interrupt') as { id: string };
    window.__personaplexTransport.audio(1, 0, 1920);
    window.__personaplexTransport.emit({ type: 'interrupted', id: control.id, generation: 1 });
  });
  await page.waitForTimeout(30);
  expect((await evidence(page)).sourcesStarted).toBe(0);
  await expect(page.getByTestId('connected')).toHaveText('true');
  await page.evaluate(() => {
    window.__personaplexTransport.samples(0, 12);
    window.__personaplexTransport.audio(1, 1920, 5760);
  });
  await expect.poll(async () => (await evidence(page)).sourcesStarted).toBe(1);
  await page.getByRole('button', { name: 'End experimental voice' }).click();
});

test('experimental missing interrupt acknowledgement fails rather than remaining silently held', async ({ page }) => {
  await mockedPersonaPlex(page, { autoReady: true, autoAck: false, ackDelta: 1 }); await connect(page);
  await page.clock.install();
  await page.getByRole('button', { name: 'Interrupt experimental voice' }).click();
  await page.clock.fastForward(6000);
  await expect(page.getByTestId('connected')).toHaveText('false');
  await expect(page.getByTestId('error')).not.toBeEmpty();
  expect(await evidence(page)).toMatchObject({ tracksStopped: 1, contextsClosed: 1, capturesDisconnected: 1, socketsClosed: 1 });
});

test('experimental rapid manual stop and user onset coalesce one pending interrupt until ACK', async ({ page }) => {
  await mockedPersonaPlex(page, { autoReady: true, autoAck: false, ackDelta: 1 }); await connect(page);
  await page.getByRole('button', { name: 'Interrupt experimental voice' }).click();
  await page.evaluate(() => window.__personaplexTransport.samples(.3, 3));
  const controls = (await evidence(page)).messages.filter(event => !Array.isArray(event) && event.type === 'interrupt') as { id: string }[];
  expect(controls).toHaveLength(1);
  await page.evaluate(id => {
    window.__personaplexTransport.emit({ type: 'interrupted', id, generation: 1 });
    window.__personaplexTransport.samples(0, 12);
  }, controls[0].id);
  await page.evaluate(() => window.__personaplexTransport.audio(1, 0, 5760));
  await expect.poll(async () => (await evidence(page)).sourcesStarted).toBe(1);
  await expect(page.getByTestId('connected')).toHaveText('true');
  await page.getByRole('button', { name: 'End experimental voice' }).click();
});

test('experimental backlog failure stays disconnected and idle during an interrupt', async ({ page }) => {
  await mockedPersonaPlex(page); await connect(page);
  await page.evaluate(() => { window.__personaplexTransport.socket!.bufferedAmount = 24001; });
  await page.getByRole('button', { name: 'Interrupt experimental voice' }).click();
  await expect(page.getByTestId('connected')).toHaveText('false');
  await expect(page.getByTestId('phase')).toHaveText('idle');
  await expect(page.getByTestId('error')).toContainText('fell behind');
});

test('experimental pending binary decode is suppressed after teardown and reconnect has a fresh clock', async ({ page }) => {
  await mockedPersonaPlex(page); await connect(page);
  await page.evaluate(() => window.__personaplexTransport.audio(0, 0, 1920, true));
  await expect.poll(() => page.evaluate(() => Boolean(window.__personaplexTransport.releaseBlob))).toBe(true);
  await page.getByRole('button', { name: 'End experimental voice' }).click();
  await page.evaluate(() => window.__personaplexTransport.releaseBlob?.());
  await page.waitForTimeout(30);
  expect((await evidence(page)).sourcesStarted).toBe(0);
  await page.getByRole('button', { name: 'Connect experimental voice' }).click();
  await expect(page.getByTestId('connected')).toHaveText('true');
  await page.evaluate(() => window.__personaplexTransport.audio(0, 0, 1920));
  await expect.poll(async () => (await evidence(page)).sourcesStarted).toBe(1);
  // Same-generation missing samples must fail rather than silently stretching clock.
  await page.evaluate(() => window.__personaplexTransport.audio(0, 9999, 1920));
  await expect(page.getByTestId('connected')).toHaveText('false');
  expect(await evidence(page)).toMatchObject({ tracksStopped: 2, contextsClosed: 2, capturesDisconnected: 2, socketsClosed: 2 });
});

test('opted background observation tees bounded WAV while native PCM and playback continue', async ({ page }) => {
  await mockedPersonaPlex(page);
  const requests: string[] = [], bodies: { audio: string; format: string }[] = [];
  page.on('request', request => { if (/\/api\/avatar\/(?:transcribe|conversation|speech)(?:\?|$)/.test(request.url())) requests.push(new URL(request.url()).pathname); });
  await page.route('**/api/avatar/transcribe', route => {
    bodies.push(route.request().postDataJSON());
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ text: 'Review this transaction.' }) });
  });
  await page.goto('/__personaplex_harness?observer=1');
  await page.getByRole('button', { name: 'Connect experimental voice' }).click();
  await expect(page.getByTestId('connected')).toHaveText('true');
  await page.evaluate(() => { window.__personaplexTransport.samples(.3, 4); window.__personaplexTransport.samples(0, 14); });
  await expect.poll(() => page.evaluate(() => window.__personaplexHarness.transcript.filter(t => t.role === 'user').map(t => t.text))).toEqual(['Review this transaction.']);
  expect(requests).toEqual(['/api/avatar/transcribe']); expect(bodies).toHaveLength(1);
  const audio = Buffer.from(bodies[0].audio, 'base64');
  expect(bodies[0].format).toBe('wav'); expect(audio.toString('ascii', 0, 4)).toBe('RIFF'); expect(audio.readUInt32LE(24)).toBe(16000);
  expect((await evidence(page)).messages.filter(Array.isArray)).toHaveLength(18);
  await page.evaluate(() => window.__personaplexTransport.audio(1, 0, 5760));
  await expect(page.getByTestId('phase')).toHaveText('speaking');
  await page.getByRole('button', { name: 'End experimental voice' }).click();
});

test('background identity reset withholds a pending transcript and privacy pause collects no new speech', async ({ page }) => {
  await mockedPersonaPlex(page);
  let release!: () => void; const gate = new Promise<void>(resolve => { release = resolve; });
  let requests = 0;
  await page.route('**/api/avatar/transcribe', async route => {
    requests++; await gate;
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ text: 'Prior account text.' }) }).catch(() => {});
  });
  await page.goto('/__personaplex_harness?observer=1');
  await page.getByRole('button', { name: 'Connect experimental voice' }).click();
  await expect(page.getByTestId('connected')).toHaveText('true');
  await page.evaluate(() => { window.__personaplexTransport.samples(.3, 4); window.__personaplexTransport.samples(0, 14); });
  await expect.poll(() => requests).toBe(1);
  await page.getByRole('button', { name: 'Reset background observer' }).click(); release();
  await page.getByRole('button', { name: 'Pause background observer' }).click();
  await page.evaluate(() => { window.__personaplexTransport.samples(.3, 4); window.__personaplexTransport.samples(0, 14); });
  await page.waitForTimeout(80);
  expect(requests).toBe(1); expect(await page.evaluate(() => window.__personaplexHarness.transcript)).toEqual([]);
  await expect(page.getByTestId('connected')).toHaveText('true');
  expect((await evidence(page)).messages.filter(Array.isArray)).toHaveLength(36);
  await page.getByRole('button', { name: 'End experimental voice' }).click();
});

test('task hold suppresses output through user turns and mute, then waits for a genuinely later turn', async ({ page }) => {
  await mockedPersonaPlex(page); await connect(page);
  await page.evaluate(() => window.__personaplexTransport.audio(0, 0, 5760));
  await expect(page.getByTestId('phase')).toHaveText('speaking');
  await page.evaluate(async () => {
    window.__personaplexTransport.audio(0, 5760, 1920);
    await Promise.resolve(); await Promise.resolve();
    [...document.querySelectorAll('button')].find(button => button.textContent === 'Begin task hold')!.click();
  });
  await page.waitForTimeout(30);
  const stopped = await evidence(page);
  expect(stopped.sourcesStopped).toBeGreaterThan(0);
  await page.evaluate(() => {
    for (let turn = 0; turn < 2; turn++) {
      window.__personaplexTransport.samples(.3, 3); window.__personaplexTransport.samples(0, 12);
    }
    window.__personaplexTransport.audio(1, 7680, 1920);
    window.__personaplexTransport.emit({ type: 'transcript', role: 'assistant', generation: 1, id: 'held-caption', text: 'Discard this native answer.', done: true });
  });
  await page.getByRole('button', { name: 'Mute experimental voice' }).click();
  await page.evaluate(() => window.__personaplexTransport.samples(.3, 3));
  await page.getByRole('button', { name: 'Mute experimental voice' }).click();
  await page.evaluate(() => window.__personaplexTransport.samples(.3, 3));
  await page.getByRole('button', { name: 'Complete task hold', exact: true }).click();
  await page.evaluate(() => {
    window.__personaplexTransport.samples(0, 12);
    window.__personaplexTransport.audio(1, 9600, 1920);
  });
  await page.waitForTimeout(30);
  const held = await evidence(page);
  expect(held.sourcesStarted).toBe(stopped.sourcesStarted);
  expect(held.messages.filter(event => !Array.isArray(event) && event.type === 'interrupt')).toHaveLength(1);
  const inputs = held.messages.filter(Array.isArray) as number[][];
  expect(inputs).toHaveLength(48);
  expect(inputs.slice(30, 33).every(packet => packet.slice(3).every(byte => byte === 0))).toBe(true);
  expect(await page.evaluate(() => window.__personaplexHarness.transcript)).toEqual([]);
  await page.evaluate(() => window.__personaplexTransport.samples(.3, 3));
  await page.waitForTimeout(30);
  await page.evaluate(() => {
    window.__personaplexTransport.samples(0, 12);
    window.__personaplexTransport.audio(2, 11520, 5760);
    window.__personaplexTransport.emit({ type: 'transcript', role: 'assistant', generation: 2, id: 'new-caption', text: 'A fresh ordinary reply.', done: true });
  });
  await expect.poll(async () => (await evidence(page)).sourcesStarted).toBe(stopped.sourcesStarted + 1);
  await expect.poll(() => page.evaluate(() => window.__personaplexHarness.transcript.map(row => row.text))).toEqual(['A fresh ordinary reply.']);
  await page.getByRole('button', { name: 'End experimental voice' }).click();
});

test('task completion cannot resume during privacy pause or before the later turn ACK', async ({ page }) => {
  await mockedPersonaPlex(page, { autoReady: true, autoAck: false, ackDelta: 1 }); await connect(page);
  const ack = async (index: number) => {
    const controls = (await evidence(page)).messages.filter(event => !Array.isArray(event) && event.type === 'interrupt') as { id: string }[];
    await page.evaluate(({ id, generation }) => window.__personaplexTransport.emit({ type: 'interrupted', id, generation }), { id: controls[index].id, generation: index + 1 });
    await page.waitForTimeout(20);
  };
  await page.getByRole('button', { name: 'Begin task hold', exact: true }).click(); await ack(0);
  await page.getByRole('button', { name: 'Complete task hold', exact: true }).click();
  await page.getByRole('button', { name: 'Pause background observer' }).click();
  await page.evaluate(() => { window.__personaplexTransport.samples(.3, 3); window.__personaplexTransport.samples(0, 12); });
  expect((await evidence(page)).messages.filter(event => !Array.isArray(event) && event.type === 'interrupt')).toHaveLength(1);
  await page.getByRole('button', { name: 'Pause background observer' }).click();
  await page.evaluate(() => window.__personaplexTransport.samples(.3, 3));
  await page.getByRole('button', { name: 'Pause background observer' }).click(); await ack(1);
  await page.evaluate(() => { window.__personaplexTransport.samples(0, 12); window.__personaplexTransport.audio(2, 0, 1920); });
  await page.getByRole('button', { name: 'Pause background observer' }).click();
  await page.waitForTimeout(30); expect((await evidence(page)).sourcesStarted).toBe(0);
  await page.evaluate(() => { window.__personaplexTransport.samples(.3, 3); window.__personaplexTransport.samples(0, 12); window.__personaplexTransport.audio(3, 1920, 1920); });
  await page.waitForTimeout(30); expect((await evidence(page)).sourcesStarted).toBe(0);
  await ack(2);
  await page.evaluate(() => window.__personaplexTransport.audio(3, 3840, 5760));
  await expect.poll(async () => (await evidence(page)).sourcesStarted).toBe(1);
  await page.getByRole('button', { name: 'End experimental voice' }).click();
});

test('stale task completion cannot release a newer hold or a reconnected session', async ({ page }) => {
  await mockedPersonaPlex(page); await connect(page);
  await page.getByRole('button', { name: 'Begin task hold', exact: true }).click();
  await page.waitForTimeout(30);
  await page.getByRole('button', { name: 'Complete task hold', exact: true }).click();
  await page.getByRole('button', { name: 'Begin task hold', exact: true }).click();
  await page.waitForTimeout(30);
  await page.getByRole('button', { name: 'Complete first task hold' }).click();
  await page.evaluate(() => { window.__personaplexTransport.samples(.3, 3); window.__personaplexTransport.samples(0, 12); window.__personaplexTransport.audio(2, 0, 1920); });
  await page.waitForTimeout(30); expect((await evidence(page)).sourcesStarted).toBe(0);
  await page.getByRole('button', { name: 'End experimental voice' }).click();
  await page.getByRole('button', { name: 'Connect experimental voice' }).click();
  await expect(page.getByTestId('connected')).toHaveText('true');
  await page.getByRole('button', { name: 'Begin task hold', exact: true }).click();
  await page.waitForTimeout(30);
  await page.getByRole('button', { name: 'Complete first task hold' }).click();
  await page.evaluate(() => { window.__personaplexTransport.samples(.3, 3); window.__personaplexTransport.samples(0, 12); window.__personaplexTransport.audio(1, 0, 1920); });
  await page.waitForTimeout(30); expect((await evidence(page)).sourcesStarted).toBe(0);
  await page.getByRole('button', { name: 'Complete task hold', exact: true }).click();
  await page.evaluate(() => window.__personaplexTransport.samples(.3, 3)); await page.waitForTimeout(30);
  await page.evaluate(() => { window.__personaplexTransport.samples(0, 12); window.__personaplexTransport.audio(2, 1920, 5760); });
  await expect.poll(async () => (await evidence(page)).sourcesStarted).toBe(1);
  await page.getByRole('button', { name: 'End experimental voice' }).click();
});

test('beginning work aborts pending and queued background observations without stopping native capture', async ({ page }) => {
  await mockedPersonaPlex(page);
  let release!: () => void; const pending = new Promise<void>(resolve => { release = resolve; });
  let requests = 0;
  await page.route('**/api/avatar/transcribe', async route => {
    requests++;
    if (requests === 1) await pending;
    await route.fulfill({ json: { text: requests === 1 ? 'Stale observed text.' : 'Fresh observed text.' } }).catch(() => {});
  });
  await page.goto('/__personaplex_harness?observer=1');
  await page.getByRole('button', { name: 'Connect experimental voice' }).click();
  await expect(page.getByTestId('connected')).toHaveText('true');
  await page.evaluate(() => { for (let turn = 0; turn < 2; turn++) { window.__personaplexTransport.samples(.3, 4); window.__personaplexTransport.samples(0, 14); } });
  await expect.poll(() => requests).toBe(1);
  await page.getByRole('button', { name: 'Begin task hold', exact: true }).click(); release();
  await page.evaluate(() => { window.__personaplexTransport.samples(.3, 4); window.__personaplexTransport.samples(0, 14); });
  await page.waitForTimeout(50);
  expect(requests).toBe(1); expect(await page.evaluate(() => window.__personaplexHarness.transcript)).toEqual([]);
  expect((await evidence(page)).messages.filter(Array.isArray)).toHaveLength(54);
  await page.getByRole('button', { name: 'Complete task hold', exact: true }).click();
  await page.evaluate(() => window.__personaplexTransport.samples(.3, 4)); await page.waitForTimeout(30);
  await page.evaluate(() => window.__personaplexTransport.samples(0, 14));
  await expect.poll(() => requests).toBe(2);
  await expect.poll(() => page.evaluate(() => window.__personaplexHarness.transcript.map(row => row.text))).toEqual(['Fresh observed text.']);
  await page.getByRole('button', { name: 'End experimental voice' }).click();
});
