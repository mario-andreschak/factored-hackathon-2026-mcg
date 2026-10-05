import { test, expect, type Page } from '@playwright/test';

import { mockedGemini } from './fixtures/gemini-transport';

async function connect(page: Page) {
  await page.goto('/__gemini_harness');
  await page.getByRole('button', { name: 'Connect native voice' }).click();
  await expect(page.getByTestId('connected')).toHaveText('true');
  await expect(page.getByTestId('phase')).toHaveText('listening');
}
async function emit(page: Page, event: object, blob = false) {
  await page.evaluate(({ event, blob }) => (window as Window & { __geminiTransport: { emit(event: object, blob: boolean): void } }).__geminiTransport.emit(event, blob), { event, blob });
}
async function samples(page: Page, amplitude: number) {
  await page.evaluate(amplitude => (window as Window & { __geminiTransport: { samples(amplitude: number): void } }).__geminiTransport.samples(amplitude), amplitude);
}
async function evidence(page: Page) {
  return page.evaluate(() => {
    const value = (window as Window & { __geminiTransport: {
      tracksStopped: number; contextsClosed: number; capturesDisconnected: number; sourcesStarted: number; sourcesStopped: number; socketsClosed: number;
      messages: Record<string, unknown>[]; urls: string[];
    } }).__geminiTransport;
    return { tracksStopped: value.tracksStopped, contextsClosed: value.contextsClosed, capturesDisconnected: value.capturesDisconnected,
      sourcesStarted: value.sourcesStarted, sourcesStopped: value.sourcesStopped, socketsClosed: value.socketsClosed, messages: value.messages, urls: value.urls };
  });
}
const audioTurn = (duration = 2) => ({ serverContent: { modelTurn: { parts: [{ inlineData: {
  mimeType: 'audio/pcm;rate=24000', data: Buffer.alloc(duration * 24000 * 2).toString('base64'),
} }] } } });

test('native Live continuously streams PCM and receives native audio/transcription without chained requests', async ({ page }) => {
  await mockedGemini(page);
  const chained: string[] = [];
  page.on('request', request => { if (/\/api\/avatar\/(?:transcribe|conversation|speech)(?:\?|$)/.test(request.url())) chained.push(request.url()); });
  await connect(page);
  const first = await evidence(page);
  expect(first.messages[0]).toEqual({ setup: { model: 'models/gemini-3.8-live' } });
  expect(first.urls[0]).toContain('BidiGenerateContentConstrained?access_token=');
  expect(first.urls[0]).not.toContain('key=');
  await samples(page, .02); await samples(page, 0);
  const pcm = (await evidence(page)).messages.filter(message => message.realtimeInput && (message.realtimeInput as { audio?: unknown }).audio);
  expect(pcm).toHaveLength(2);
  const audio = (pcm[0].realtimeInput as { audio: { data: string; mimeType: string } }).audio;
  expect(audio.mimeType).toBe('audio/pcm;rate=16000');
  expect(Buffer.from(audio.data, 'base64').length % 2).toBe(0);
  expect(Buffer.from(audio.data, 'base64').toString('ascii', 0, 4)).not.toBe('RIFF');
  await emit(page, { serverContent: { inputTranscription: { text: 'I feel worried.', finished: true } } });
  await emit(page, audioTurn(), true);
  await expect(page.getByTestId('phase')).toHaveText('speaking');
  expect((await evidence(page)).sourcesStarted).toBeGreaterThan(0);
  await emit(page, { serverContent: { outputTranscription: { text: 'We can take our time.', finished: true } } });
  await expect.poll(() => page.evaluate(() => window.__geminiHarness.transcript.some(item => item.role === 'assistant' && item.text.includes('take our time')))).toBe(true);
  await emit(page, { serverContent: { interrupted: true } });
  await expect(page.getByTestId('phase')).toHaveText('listening');
  expect((await evidence(page)).sourcesStopped).toBeGreaterThan(0);
  await page.getByRole('button', { name: 'Mute native voice' }).click();
  await expect(page.getByTestId('muted')).toHaveText('true');
  const beforeMute = (await evidence(page)).messages.length;
  await samples(page, .04); expect((await evidence(page)).messages).toHaveLength(beforeMute);
  expect((await evidence(page)).messages.some(message => (message.realtimeInput as { audioStreamEnd?: boolean } | undefined)?.audioStreamEnd)).toBe(true);
  expect(chained).toEqual([]);
  await page.getByRole('button', { name: 'End native voice' }).click();
  expect(await evidence(page)).toMatchObject({ tracksStopped: 1, contextsClosed: 1, capturesDisconnected: 1, socketsClosed: 1 });
});

test('native asynchronous tools deduplicate and return WHEN_IDLE while speech interruptions leave reads admitted', async ({ page }) => {
  await mockedGemini(page); await connect(page);
  const call = { toolCall: { functionCalls: [{ id: 'owned-read-1', name: 'delegate_task', args: { message: 'One owned synthetic inquiry' } }] } };
  await emit(page, call); await emit(page, call);
  await expect.poll(() => page.evaluate(() => window.__geminiHarness.tasks)).toEqual(['One owned synthetic inquiry']);
  await emit(page, audioTurn());
  await expect(page.getByTestId('phase')).toHaveText('speaking');
  await page.getByRole('button', { name: 'Interrupt native voice' }).click();
  await expect(page.getByTestId('phase')).toHaveText('listening');
  await page.evaluate(() => window.__geminiHarness.resolveTask?.({ reply: 'Actual synthetic public bank result', mode: 'flujo', status: 'completed' }));
  await expect.poll(async () => (await evidence(page)).messages.filter(message => message.toolResponse).length).toBe(1);
  const response = (await evidence(page)).messages.find(message => message.toolResponse)!;
  expect(response).toMatchObject({ toolResponse: { functionResponses: [{ id: 'owned-read-1', name: 'delegate_task', scheduling: 'WHEN_IDLE' }] } });
  expect(JSON.stringify(response)).toContain('Actual synthetic public bank result');
  await emit(page, { toolCall: { functionCalls: [{ id: 'world-1', name: 'set_world', args: { avatar: 'spark', sceneIndex: 4, reason: 'User wants energy' } }] } });
  await expect.poll(() => page.evaluate(() => window.__geminiHarness.worlds)).toEqual([{ avatar: 'spark', scene: 4 }]);
  await expect.poll(async () => (await evidence(page)).messages.filter(message => message.toolResponse).length).toBe(2);
  expect((await evidence(page)).messages.filter(message => message.toolResponse).at(-1)).toMatchObject({
    toolResponse: { functionResponses: [{ id: 'world-1', scheduling: 'SILENT' }] },
  });
  await page.getByRole('button', { name: 'End native voice' }).click();
});

test('native cancellation and disconnect suppress late tool replies and reconnect starts fresh', async ({ page }) => {
  await mockedGemini(page); await connect(page);
  const call = { toolCall: { functionCalls: [{ id: 'read-cancelled', name: 'delegate_task', args: { message: 'Synthetic admitted inquiry' } }] } };
  await emit(page, call); await expect.poll(() => page.evaluate(() => window.__geminiHarness.tasks.length)).toBe(1);
  await emit(page, { toolCallCancellation: { ids: ['read-cancelled'] } });
  await page.evaluate(() => window.__geminiHarness.resolveTask?.({ reply: 'Cancelled voice tool result' }));
  await page.waitForTimeout(100);
  expect((await evidence(page)).messages.filter(message => message.toolResponse)).toHaveLength(0);
  await emit(page, { toolCall: { functionCalls: [{ id: 'late-read', name: 'delegate_task', args: { message: 'Late owned inquiry' } }] } });
  await expect.poll(() => page.evaluate(() => window.__geminiHarness.tasks.length)).toBe(2);
  await page.getByRole('button', { name: 'End native voice' }).click();
  await page.evaluate(() => window.__geminiHarness.resolveTask?.({ reply: 'Previous voice lifecycle result' }));
  await page.waitForTimeout(100);
  expect((await evidence(page)).messages.filter(message => message.toolResponse)).toHaveLength(0);
  await page.getByRole('button', { name: 'Connect native voice' }).click();
  await expect(page.getByTestId('connected')).toHaveText('true'); await emit(page, call);
  await expect.poll(() => page.evaluate(() => window.__geminiHarness.tasks.length)).toBe(3);
  await emit(page, { goAway: { timeLeft: '1s' } });
  await expect(page.getByTestId('connected')).toHaveText('false');
  await expect(page.getByTestId('error')).not.toBeEmpty();
  expect(await evidence(page)).toMatchObject({ tracksStopped: 2, contextsClosed: 2, capturesDisconnected: 2, socketsClosed: 2 });
});

test('native interim captions replace hypotheses, later utterances get fresh IDs and teardown emits no old caption', async ({ page }) => {
  await mockedGemini(page); await connect(page);
  await emit(page, { serverContent: { interimInputTranscription: { text: 'I have' } } });
  await emit(page, { serverContent: { interimInputTranscription: { text: 'I have two' } } });
  await emit(page, { serverContent: { inputTranscription: { text: 'I have two questions.', finished: true } } });
  await expect.poll(() => page.evaluate(() => window.__geminiHarness.transcript.at(-1)?.text)).toBe('I have two questions.');
  const first = await page.evaluate(() => window.__geminiHarness.transcript.at(-1)!);
  expect(first.done).toBe(true);
  await emit(page, { serverContent: { inputTranscription: { text: 'My second utterance.', finished: true } } });
  await expect.poll(() => page.evaluate(() => window.__geminiHarness.transcript.at(-1)?.text)).toBe('My second utterance.');
  const second = await page.evaluate(() => window.__geminiHarness.transcript.at(-1)!);
  expect(second.id).not.toBe(first.id);
  await emit(page, { serverContent: { outputTranscription: { text: 'An unfinished prior-account caption.' } } });
  await expect.poll(() => page.evaluate(() => window.__geminiHarness.transcript.at(-1)?.text)).toBe('An unfinished prior-account caption.');
  const before = await page.evaluate(() => window.__geminiHarness.transcript.length);
  await page.getByRole('button', { name: 'End native voice' }).click();
  await page.waitForTimeout(50);
  expect(await page.evaluate(() => window.__geminiHarness.transcript.length)).toBe(before);
  await page.getByRole('button', { name: 'Connect native voice' }).click();
  await expect(page.getByTestId('connected')).toHaveText('true');
  await emit(page, { serverContent: { inputTranscription: { text: 'Fresh connection.', finished: true } } });
  await expect.poll(() => page.evaluate(() => window.__geminiHarness.transcript.at(-1)?.text)).toBe('Fresh connection.');
  expect(await page.evaluate(() => window.__geminiHarness.transcript.at(-1)!.id)).not.toBe(second.id);
  await page.getByRole('button', { name: 'End native voice' }).click();
});

test('native delegated output waits for user activity and audible playback without waiting for a provider turnComplete', async ({ page }) => {
  await mockedGemini(page); await connect(page);
  await emit(page, { toolCall: { functionCalls: [{ id: 'activity-read', name: 'delegate_task', args: { message: 'Synthetic activity inquiry' } }] } });
  await expect.poll(() => page.evaluate(() => window.__geminiHarness.tasks.length)).toBe(1);
  await emit(page, { voiceActivity: { voiceActivityType: 'ACTIVITY_START' } });
  await page.evaluate(() => window.__geminiHarness.resolveTask?.({ reply: 'Deferred activity result' }));
  await page.waitForTimeout(60);
  expect((await evidence(page)).messages.filter(message => message.toolResponse)).toHaveLength(0);
  await emit(page, { voiceActivity: { voiceActivityType: 'ACTIVITY_END' } });
  await expect.poll(async () => (await evidence(page)).messages.filter(message => message.toolResponse).length).toBe(1);
  expect(JSON.stringify((await evidence(page)).messages.filter(message => message.toolResponse))).toContain('Deferred activity result');
  await emit(page, { toolCall: { functionCalls: [{ id: 'playback-read', name: 'delegate_task', args: { message: 'Synthetic playback inquiry' } }] } });
  await expect.poll(() => page.evaluate(() => window.__geminiHarness.tasks.length)).toBe(2);
  await emit(page, audioTurn(.4));
  await expect(page.getByTestId('phase')).toHaveText('speaking');
  await page.evaluate(() => window.__geminiHarness.resolveTask?.({ reply: 'Deferred audible playback result' }));
  await page.waitForTimeout(60);
  expect((await evidence(page)).messages.filter(message => message.toolResponse)).toHaveLength(1);
  await expect.poll(async () => (await evidence(page)).messages.filter(message => message.toolResponse).length).toBe(2);
  const last = (await evidence(page)).messages.filter(message => message.toolResponse).at(-1);
  expect(last).toMatchObject({ toolResponse: { functionResponses: [{ id: 'playback-read', scheduling: 'WHEN_IDLE' }] } });
  expect(JSON.stringify(last)).toContain('Deferred audible playback result');
  await page.getByRole('button', { name: 'End native voice' }).click();
});

test('native configured model comes from the server while the provider destination remains fixed', async ({ page }) => {
  await mockedGemini(page);
  await page.route('**/api/avatar/gemini-token', route => route.fulfill({ json: {
    token: 'auth_tokens/e2e-configured', model: 'gemini-e2e-configured-model',
    setup: { model: 'models/gemini-e2e-configured-model' },
    websocketUrl: 'wss://untrusted-fixture.invalid/steal-token',
  } }));
  await connect(page);
  const result = await evidence(page);
  expect(result.messages[0]).toEqual({ setup: { model: 'models/gemini-e2e-configured-model' } });
  expect(result.urls).toHaveLength(1);
  expect(result.urls[0]).toMatch(/^wss:\/\/generativelanguage\.googleapis\.com\/ws\/google\.ai\.generativelanguage\.v1beta\.GenerativeService\.BidiGenerateContentConstrained\?access_token=/);
  expect(result.urls[0]).not.toContain('untrusted-fixture');
  await page.getByRole('button', { name: 'End native voice' }).click();
});

for (const invalid of [
  { label: 'mismatched setup model', model: 'gemini-configured-model', setup: { model: 'models/gemini-other-model' } },
  { label: 'malformed model identifier', model: 'gemini-../../untrusted', setup: { model: 'models/gemini-../../untrusted' } },
]) {
  test(`native ${invalid.label} rejects admission and closes microphone resources`, async ({ page }) => {
    await mockedGemini(page);
    await page.route('**/api/avatar/gemini-token', route => route.fulfill({ json: {
      token: 'auth_tokens/e2e-invalid', model: invalid.model, setup: invalid.setup,
    } }));
    await page.goto('/__gemini_harness');
    await page.getByRole('button', { name: 'Connect native voice' }).click();
    await expect(page.getByTestId('error')).toContainText('configuración de voz no es válida');
    await expect(page.getByTestId('connected')).toHaveText('false');
    await expect(page.getByTestId('phase')).toHaveText('idle');
    expect(await evidence(page)).toMatchObject({ tracksStopped: 1, contextsClosed: 1, capturesDisconnected: 1, socketsClosed: 0, urls: [] });
  });
}
