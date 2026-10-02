import { test, expect, type Page } from '@playwright/test';
import { mockedPersonaPlex } from './fixtures/personaplex-transport';

type Role = 'moss' | 'orbit' | 'spark';
const firstThoughts: Record<Role, string> = {
  moss: 'I am worried and overwhelmed. Help me take one small step.',
  orbit: 'Please explain a clear plan for tomorrow and organize the next steps.',
  spark: 'Let us go fast! I have energy and want to get moving now.',
};
const names: Record<Role, string> = { moss: 'Moss', orbit: 'Orbit', spark: 'Spark' };

async function initialGame(page: Page, role: Role) {
  await mockedPersonaPlex(page, { autoReady: false, autoAck: true, ackDelta: 1 });
  const observed = { configReads: 0, initial: [] as { audio: string; format: string }[], otherVoice: [] as string[] };
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (/^\/api\/avatar\/(?:personaplex-session|transcribe|conversation|speech|realtime|gemini-token)$/.test(path)) observed.otherVoice.push(path);
  });
  await page.route('**/api/avatar/config', route => {
    observed.configReads++;
    return route.fulfill({ json: { voiceAvailable: false, initialVoiceAvailable: observed.initial.length === 0,
      voiceAvatar: null, voiceProvider: 'personaplex', backgroundAsrAvailable: true,
      backendAvailable: false, nativeReadBridgeAvailable: false, saviaUrl: '', mode: 'demo', realtimeModel: '' } });
  });
  await page.route('**/api/avatar/personaplex-initial', route => {
    observed.initial.push(route.request().postDataJSON());
    return route.fulfill({ json: { protocol: 'personaplex-pcm-v1', streamPath: '/api/avatar/personaplex',
      inputSampleRate: 24000, outputSampleRate: 24000, ticket: 'initial_game_ticket_' + 'x'.repeat(40),
      expiresAt: new Date(Date.now() + 25_000).toISOString(), avatar: role,
      transcript: firstThoughts[role], initialContextDelivered: false } });
  });
  const response = page.waitForResponse('**/api/avatar/config'); await page.goto('/'); await response;
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => resolve())));
  return observed;
}

async function listeningEyes(page: Page) {
  await page.getByRole('button', { name: 'Despertar el mundo' }).click();
  await expect(page.getByRole('status')).toHaveText('Te escucho');
  await expect(page.getByRole('button', { name: 'Dejar de escuchar', exact: true })).toBeVisible();
  await expect(page.locator('.drawn-eyes')).toBeVisible();
  await expect(page.locator('.darkness')).not.toHaveClass(/eyes-connecting/);
  expect(await page.evaluate(() => window.__personaplexTransport.urls)).toEqual([]);
}

async function speakFirstThought(page: Page) {
  await page.evaluate(() => {
    const transport = window.__personaplexTransport;
    transport.samples(.004, 4);
    transport.samples(.25, 5);
    transport.samples(0, Math.ceil(.55 * transport.sampleRate / 2048));
  });
  await expect.poll(() => page.evaluate(() => window.__personaplexTransport.urls.length)).toBe(1);
  expect(await page.evaluate(() => window.__personaplexTransport.messages)).toEqual([]);
}

async function nativeReady(page: Page, role: Role) {
  await page.evaluate(() => window.__personaplexTransport.emit({ type: 'ready', protocol: 'personaplex-pcm-v1',
    sampleRate: 24000, frameSamples: 1920, format: 'pcm16le' }));
  await expect(page.locator(`.world--${role}`)).toBeVisible();
  await expect(page.getByLabel('Te escucho', { exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.__personaplexTransport.messages.filter(Array.isArray).length)).toBeGreaterThan(0);
}

for (const role of ['moss', 'orbit', 'spark'] as const) {
  test(`initial spoken ${role} mood enters its matching world once and retains its static native history role`, async ({ page }) => {
    const observed = await initialGame(page, role);
    await listeningEyes(page); expect(observed.initial).toEqual([]);
    await speakFirstThought(page);
    expect(observed.initial).toHaveLength(1);
    expect(Object.keys(observed.initial[0]).sort()).toEqual(['audio', 'format']);
    const captured = Buffer.from(observed.initial[0].audio, 'base64');
    expect(captured.toString('ascii', 0, 4)).toBe('RIFF'); expect(captured.readUInt32LE(24)).toBe(24000);
    expect(captured.readUInt32LE(40)).toBe(captured.length - 44); expect((captured.length - 44) / 48000).toBeLessThanOrEqual(12);
    // A selected world alone does not advertise an admitted native listener.
    await expect(page.getByLabel('Te escucho', { exact: true })).toHaveCount(0);
    await nativeReady(page, role);
    const caption = 'We will keep this conversation simple and take the next step together.';
    await page.evaluate(text => {
      const event = { type: 'transcript', role: 'assistant', generation: 0, id: 'fixed-native-reply', text, done: true };
      window.__personaplexTransport.emit(event); window.__personaplexTransport.emit(event);
    }, caption);
    await expect(page.locator('.sr-only[aria-live="polite"]')).toContainText(caption);
    await expect(page.locator(`.world--${role}`)).toBeVisible();
    await page.getByRole('button', { name: 'Pausar la historia' }).click();
    await page.getByRole('button', { name: 'Palabras del camino' }).click();
    await expect(page.getByLabel('Transcripción de la conversación')).toBeVisible();
    await expect(page.locator('.history-user')).toHaveCount(1);
    await expect(page.locator('.history-user p')).toHaveText(firstThoughts[role]);
    await expect(page.locator('.history-assistant')).toHaveCount(1);
    await expect(page.locator('.history-assistant span')).toHaveText(names[role].toUpperCase());
    await expect(page.locator('.history-assistant p')).toHaveText(caption);
    await page.getByRole('button', { name: 'Cerrar transcripción' }).click();
    await page.getByRole('button', { name: 'Pausar la historia' }).click();
    await page.getByRole('button', { name: 'Terminar conversación de voz', exact: true }).click();
    await expect.poll(() => observed.configReads).toBeGreaterThanOrEqual(2);
    await expect(page.getByRole('button', { name: 'Iniciar conversación de voz', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Terminar conversación de voz', exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => window.__personaplexTransport.tracksStopped)).toBe(1);
    expect(await page.evaluate(() => window.__personaplexTransport.socketsClosed)).toBe(1);
    expect(observed.initial).toHaveLength(1); expect(observed.otherVoice).toEqual([]);
  });
}

test('stopping initial listening preserves warm availability, while manual character change ends the admitted static role', async ({ page }) => {
  const observed = await initialGame(page, 'spark');
  await listeningEyes(page);
  await page.getByRole('button', { name: 'Dejar de escuchar', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Despertar el mundo' })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.__personaplexTransport.tracksStopped)).toBe(1);
  expect(observed.initial).toEqual([]); expect(observed.otherVoice).toEqual([]);
  expect(await page.evaluate(() => window.__personaplexTransport.urls)).toEqual([]);
  await listeningEyes(page); await speakFirstThought(page); await nativeReady(page, 'spark');
  await page.getByRole('button', { name: 'Pausar la historia' }).click();
  await page.getByRole('button', { name: 'Elegir a Moss', exact: true }).click();
  await expect(page.locator('.world--moss')).toBeVisible();
  await expect(page.getByLabel('Vista previa del mundo', { exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.__personaplexTransport.tracksStopped)).toBe(2);
  expect(await page.evaluate(() => window.__personaplexTransport.socketsClosed)).toBe(1);
  expect(observed.initial).toHaveLength(1); expect(observed.otherVoice).toEqual([]);
});
