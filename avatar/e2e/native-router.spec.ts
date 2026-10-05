import { test, expect, type Page } from '@playwright/test';

import { mockedNative } from './fixtures/native-router-transport';

async function connect(page: Page) {
  await page.goto('/__native_router_harness'); await page.getByRole('button', { name: 'Connect native voice' }).click();
  await expect(page.getByTestId('connected')).toHaveText('true');
}
async function emit(page: Page, amplitude: number, seconds: number) { await page.evaluate(({ amplitude, seconds }) => window.__nativeTransport.emit(amplitude, seconds), { amplitude, seconds }); }
async function send(page: Page, text: string) { await page.getByLabel('Native fixture request').fill(text); await page.getByRole('button', { name: 'Send native text' }).click(); }
const requests = (page: Page, suffix: string) => page.evaluate(suffix => window.__nativeTransport.requests.filter(value => value.path.endsWith(suffix)), suffix);
const transcripts = (page: Page) => page.evaluate(() => window.__nativeHarness.transcripts);

test('a one-second thinking pause and resumed speech stay in one message without premature generation', async ({ page }) => {
  await mockedNative(page); await connect(page);
  await page.evaluate(() => { window.__nativeTransport.holdObservers = true; });
  await emit(page, .04, .6);
  await emit(page, 0, 1.1);
  expect(await requests(page, 'native-turn')).toHaveLength(0);
  expect(await requests(page, 'native-observe')).toHaveLength(0);
  await expect(page.getByTestId('phase')).toHaveText('listening');

  await emit(page, .08, .5);
  await emit(page, 0, 1.2);
  expect(await requests(page, 'native-turn')).toHaveLength(0);
  expect(await page.evaluate(() => window.__nativeHarness.utterances)).toBe(1);
  await expect(page.getByTestId('phase')).toHaveText('listening');
  await emit(page, 0, .9);
  await expect.poll(async () => (await requests(page, 'native-turn')).length).toBe(1);
  await expect.poll(async () => (await requests(page, 'native-observe')).length).toBe(1);
  const input = (await requests(page, 'native-turn'))[0].body;
  const wav = Buffer.from(String(input.audio), 'base64');
  const samples = Array.from({ length: (wav.length - 44) / 2 }, (_, i) => wav.readInt16LE(44 + i * 2));
  expect(samples.filter(value => value >= 1308 && value <= 1312).length).toBeGreaterThan(10000);
  expect(samples.filter(value => value >= 2618 && value <= 2624).length).toBeGreaterThan(9000);
  expect(samples.filter(value => value === 0).length).toBeGreaterThan(3 * 24000);
  expect((await requests(page, 'native-observe'))[0].body.audio).toBe(input.audio);
  await page.evaluate(() => window.__nativeTransport.observers[0].resolve('Primera parte de mi idea, y ahora continúo la misma frase.'));
  await expect.poll(async () => (await transcripts(page)).filter(item => item.role === 'user' && item.done).length).toBe(1);
  await expect.poll(async () => (await requests(page, 'native-played')).filter(item => item.body.complete === true).length).toBe(1);
  expect(await page.evaluate(() => window.__nativeHarness.tasks)).toEqual([]);
  await emit(page, 0, 1);
  expect(await requests(page, 'native-turn')).toHaveLength(1);
  await page.getByRole('button', { name: 'End native voice' }).click();
});

test('real WAV enters native transport directly; only hardware-drained completion becomes a heard reply', async ({ page }) => {
  await mockedNative(page); await connect(page); await emit(page, .04, .6); await emit(page, 0, 2.1);
  await expect.poll(async () => (await requests(page, 'native-turn')).length).toBe(1);
  const input = (await requests(page, 'native-turn'))[0].body;
  expect(input).toMatchObject({ format: 'wav', avatar: 'moss', locale: 'es' }); expect(input.message).toBeUndefined();
  const wav = Buffer.from(String(input.audio), 'base64'); expect(wav.toString('ascii', 0, 4)).toBe('RIFF'); expect(wav.readUInt32LE(24)).toBe(24000);
  await expect.poll(async () => (await requests(page, 'native-observe')).length).toBe(1);
  expect((await requests(page, 'native-observe'))[0].body).toMatchObject({ turnId: 'fixture-native-1', audio: input.audio, locale: 'es' });
  await expect.poll(async () => (await requests(page, 'native-played')).length).toBe(1);
  expect((await requests(page, 'native-played'))[0].body).toMatchObject({ turnId: 'fixture-native-1', complete: true, playedSamples: 6000 });
  await expect.poll(async () => (await transcripts(page)).filter(item => item.role === 'assistant' && item.done).length).toBe(1);
  expect(await page.evaluate(() => ({ tasks: window.__nativeHarness.tasks, worlds: window.__nativeHarness.worlds }))).toEqual({ tasks: [], worlds: [] });
  await page.getByRole('button', { name: 'End native voice' }).click();
  expect(await page.evaluate(() => ({ tracks: window.__nativeTransport.tracksStopped, contexts: window.__nativeTransport.contextsClosed, captures: window.__nativeTransport.capturesDisconnected }))).toEqual({ tracks: 1, contexts: 2, captures: 1 });
});

test('VAD barge-in immediately stops response while preserving new captured audio and independent old observation', async ({ page }) => {
  await mockedNative(page); await connect(page);
  await page.evaluate(() => { window.__nativeTransport.duration = 3; window.__nativeTransport.holdObservers = true; });
  await emit(page, .04, .5); await emit(page, 0, 2.1);
  await expect(page.getByTestId('phase')).toHaveText('speaking');
  await expect.poll(async () => (await requests(page, 'native-observe')).length).toBe(1);
  await emit(page, .07, .5);
  expect(await page.evaluate(() => window.__nativeTransport.sourcesStopped)).toBeGreaterThan(0);
  expect((await requests(page, 'native-observe'))[0].aborted).toBe(false);
  await emit(page, 0, 2.1);
  await expect.poll(async () => (await requests(page, 'native-turn')).length).toBe(2);
  const wav = Buffer.from(String((await requests(page, 'native-turn'))[1].body.audio), 'base64');
  const pcm = new Int16Array(wav.buffer, wav.byteOffset + 44, (wav.length - 44) / 2);
  const onset = pcm.findIndex(value => value > 1500); expect(onset).toBeGreaterThanOrEqual(0); expect(onset).toBeLessThanOrEqual(4800);
  expect([...pcm.slice(onset, onset + 3000)].every(value => value > 1500)).toBe(true);
  await page.evaluate(() => { window.__nativeTransport.observers[0].resolve('Observación anterior'); });
  await expect.poll(async () => (await requests(page, 'native-observe')).length).toBe(2);
  expect((await transcripts(page)).some(item => item.text === 'Observación anterior')).toBe(false);
  expect((await transcripts(page)).some(item => item.id === 'native-fixture-native-1' && item.done)).toBe(false);
  const firstReceipt = (await requests(page, 'native-played')).find(item => item.body.turnId === 'fixture-native-1'); expect(firstReceipt?.body.complete).toBe(false);
  await page.getByRole('button', { name: 'End native voice' }).click();
});

test('late cancelled native fetch cannot schedule audio or caption into its replacement turn', async ({ page }) => {
  await mockedNative(page); await connect(page); await page.evaluate(() => { window.__nativeTransport.holdTurnFetch = true; });
  await send(page, 'Primera respuesta'); await expect.poll(async () => (await requests(page, 'native-turn')).length).toBe(1);
  await send(page, 'Segunda respuesta');
  await page.evaluate(() => { window.__nativeTransport.holdTurnFetch = false; window.__nativeTransport.delayedTurns[0](); });
  await expect.poll(async () => (await requests(page, 'native-turn')).length).toBe(2);
  await expect.poll(async () => (await transcripts(page)).filter(item => item.role === 'assistant' && item.done).length).toBe(1);
  expect((await transcripts(page)).some(item => item.id === 'native-fixture-native-1')).toBe(false);
  expect(await page.evaluate(() => window.__nativeTransport.sourcesStarted)).toBe(1);
  expect(await page.evaluate(() => window.__nativeTransport.bodyCancelled)).toBe(1);
  await page.getByRole('button', { name: 'End native voice' }).click();
});

test('mute and locale change invalidate capture/observation; deliberate reconnect starts fresh Portuguese history', async ({ page }) => {
  await mockedNative(page); await connect(page); await page.evaluate(() => { window.__nativeTransport.holdObservers = true; });
  await emit(page, .04, .5); await emit(page, 0, 2.1); await expect.poll(async () => (await requests(page, 'native-observe')).length).toBe(1);
  await page.getByRole('button', { name: 'Mute native voice' }).click(); await emit(page, .1, 1); await emit(page, 0, 2.1);
  expect((await requests(page, 'native-turn')).length).toBe(1); expect((await requests(page, 'native-observe'))[0].aborted).toBe(true);
  await page.getByRole('button', { name: 'Portuguese native voice' }).click(); await expect(page.getByTestId('connected')).toHaveText('false');
  await page.evaluate(() => { window.__nativeTransport.observers[0].resolve('Respuesta privada anterior'); });
  expect((await transcripts(page)).some(item => item.text === 'Respuesta privada anterior')).toBe(false);
  await page.getByRole('button', { name: 'Connect native voice' }).click(); await expect(page.getByTestId('connected')).toHaveText('true'); await send(page, 'Olá');
  await expect.poll(async () => (await requests(page, 'native-turn')).length).toBe(2);
  expect((await requests(page, 'native-turn'))[1].body.locale).toBe('pt'); expect((await requests(page, 'native-reset')).length).toBe(2);
  await page.getByRole('button', { name: 'End native voice' }).click();
});

test('owned result waits through user speech and response; same-tick persona applies to next native request', async ({ page }) => {
  await mockedNative(page); await connect(page); await page.getByRole('button', { name: 'Spark same tick' }).click();
  await expect.poll(async () => (await requests(page, 'native-turn')).length).toBe(1); expect((await requests(page, 'native-turn'))[0].body.avatar).toBe('spark');
  await expect(page.getByTestId('phase')).toHaveText('listening');
  await emit(page, .04, .5); await page.getByRole('button', { name: 'Queue native result' }).click();
  expect(await requests(page, 'native-result')).toHaveLength(0); await emit(page, 0, 2.1);
  await expect.poll(async () => (await requests(page, 'native-result')).length).toBe(1);
  const ordered = await page.evaluate(() => window.__nativeTransport.requests.filter(item => /native-(?:turn|played|result)$/.test(item.path)).map(item => item.path));
  expect(ordered.indexOf('/api/avatar/native-result')).toBeGreaterThan(ordered.lastIndexOf('/api/avatar/native-turn'));
  expect((await requests(page, 'native-result'))[0].body).toEqual({ taskId: 'synthetic-owned-receipt', avatar: 'spark', locale: 'es' });
  await page.getByRole('button', { name: 'Queue native result' }).click(); expect(await requests(page, 'native-result')).toHaveLength(1);
  await page.getByRole('button', { name: 'End native voice' }).click();
});

test('fully played receipt pending HTTP completion cannot commit an old caption after interruption', async ({ page }) => {
  await mockedNative(page); await connect(page); await page.evaluate(() => { window.__nativeTransport.holdFullReceipts = true; });
  await send(page, 'Dime algo'); await expect.poll(async () => (await requests(page, 'native-played')).length).toBe(1);
  expect((await transcripts(page)).filter(item => item.role === 'assistant' && item.done)).toHaveLength(0);
  await page.getByRole('button', { name: 'Interrupt native voice' }).click();
  await page.evaluate(() => { window.__nativeTransport.fullReceipts[0](); }); await page.waitForTimeout(50);
  expect((await transcripts(page)).filter(item => item.role === 'assistant' && item.done)).toHaveLength(0);
  expect((await requests(page, 'native-played'))[0].body.complete).toBe(true); // It had actually drained before interruption.
  await page.getByRole('button', { name: 'End native voice' }).click();
});

test('25-second capped speech cannot restart until quiet, and the next fresh utterance still submits', async ({ page }) => {
  await mockedNative(page); await connect(page); await emit(page, .04, 26); await expect(page.getByTestId('error')).not.toHaveText('');
  await emit(page, .04, .6); expect(await requests(page, 'native-turn')).toHaveLength(0);
  await emit(page, 0, 2.1); await emit(page, .04, .5); await emit(page, 0, 2.1);
  await expect.poll(async () => (await requests(page, 'native-turn')).length).toBe(1);
  await page.getByRole('button', { name: 'End native voice' }).click();
});

test('explicit first-login context reset retains the microphone and ignores only its old rejected full receipt', async ({ page }) => {
  await mockedNative(page); await connect(page);
  await page.evaluate(() => { window.__nativeTransport.holdFullReceipts = true; }); await send(page, 'Antes del inicio de sesión');
  await expect.poll(async () => (await requests(page, 'native-played')).length).toBe(1);
  await page.getByRole('button', { name: 'Reset native account context' }).click();
  expect(await page.evaluate(() => ({ tracks: window.__nativeTransport.tracksStopped, contexts: window.__nativeTransport.contextsClosed }))).toEqual({ tracks: 0, contexts: 0 });
  expect((await requests(page, 'native-played'))[0].aborted).toBe(true);
  await page.evaluate(() => { window.__nativeTransport.holdFullReceipts = false; });
  await send(page, 'Contexto nuevo');
  await expect.poll(async () => (await requests(page, 'native-turn')).length).toBe(2); // The old stalled ACK cannot block fresh input.
  await expect.poll(async () => (await transcripts(page)).some(item => item.id === 'native-fixture-native-2' && item.done)).toBe(true);
  await page.evaluate(() => window.__nativeTransport.fullReceipts[0](409));
  await expect(page.getByTestId('connected')).toHaveText('true'); await expect(page.getByTestId('error')).toHaveText('');
  expect((await transcripts(page)).some(item => item.id === 'native-fixture-native-1' && item.done)).toBe(false);
  await page.getByRole('button', { name: 'End native voice' }).click();
});
