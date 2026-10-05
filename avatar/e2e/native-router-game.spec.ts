import { test, expect, type Page } from '@playwright/test';
import { mockedNative } from './fixtures/native-router-transport';

async function game(page: Page) {
  await mockedNative(page, { passthroughPaths: ['/api/avatar/config'] });
  const forbidden: string[] = [];
  await page.route('**/savia/**', route => { forbidden.push(route.request().url()); return route.abort(); });
  await page.route('**/api/avatar/config', route => route.fulfill({ json: {
    voiceProvider: 'openrouter-native', voiceAvailable: true, backgroundAsrAvailable: true,
    nativeReadBridgeAvailable: false, backendAvailable: false, saviaUrl: '', mode: 'demo', realtimeModel: '',
  } }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Despertar el mundo' }).click();
  await expect(page.getByRole('status')).toHaveText('Te escucho');
  return forbidden;
}
async function capture(page: Page, amplitude = .04) {
  await page.evaluate(amplitude => { window.__nativeTransport.emit(amplitude, .6); window.__nativeTransport.emit(0, 2.1); }, amplitude);
}
async function history(page: Page) {
  await page.getByRole('button', { name: 'Pausar la historia' }).click();
  await page.getByRole('button', { name: 'Palabras del camino' }).click();
}

test('native captured speech chooses the movie character and only completed playback enters history', async ({ page }) => {
  const forbidden = await game(page);
  await page.evaluate(() => { window.__nativeTransport.duration = 1.2; window.__nativeTransport.holdObservers = true; });
  await capture(page);
  await expect.poll(() => page.evaluate(() => window.__nativeTransport.observers.length)).toBe(1);
  await page.evaluate(() => window.__nativeTransport.observers[0].resolve('Explícame este plan con claridad.'));
  await expect(page.locator('.world--orbit')).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.__nativeTransport.sourcesStarted)).toBeGreaterThan(0);
  await expect(page.locator('.world')).toHaveAttribute('data-phase', 'speaking');
  await expect.poll(() => page.evaluate(() => window.__nativeTransport.requests.filter(r => r.path.endsWith('native-played') && r.body.complete === true).length)).toBe(1);
  await history(page);
  await expect(page.locator('.history-messages')).toContainText('Explícame este plan con claridad.');
  await expect(page.locator('.history-messages')).toContainText('Respuesta nativa 1.');
  expect(forbidden).toEqual([]);
  expect(await page.evaluate(() => window.__nativeTransport.requests.filter(r => r.path.endsWith('native-turn')).map(r => r.body.format))).toEqual(['wav']);
});

test('movie barge-in preserves the new utterance and excludes the cancelled generated reply', async ({ page }) => {
  const forbidden = await game(page);
  await page.evaluate(() => { window.__nativeTransport.duration = 3; window.__nativeTransport.autoComplete = false; window.__nativeTransport.holdObservers = true; });
  await capture(page);
  await expect.poll(() => page.evaluate(() => window.__nativeTransport.sourcesStarted)).toBeGreaterThan(0);
  await page.evaluate(() => { window.__nativeTransport.duration = .25; window.__nativeTransport.autoComplete = true; });
  await capture(page, .08);
  await expect.poll(() => page.evaluate(() => window.__nativeTransport.requests.filter(r => r.path.endsWith('native-turn')).length)).toBe(2);
  await expect.poll(() => page.evaluate(() => window.__nativeTransport.sourcesStopped)).toBeGreaterThan(0);
  await page.evaluate(() => window.__nativeTransport.observers[0].resolve('Texto antiguo que no debe aparecer.'));
  await expect.poll(() => page.evaluate(() => window.__nativeTransport.observers.length)).toBe(2);
  await page.evaluate(() => window.__nativeTransport.observers[1].resolve('Vamos rápido, tengo energía.'));
  await expect(page.locator('.world--spark')).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.__nativeTransport.requests.some(r => r.path.endsWith('native-played') && r.body.turnId === 'fixture-native-2' && r.body.complete === true))).toBe(true);
  const second = await page.evaluate(() => window.__nativeTransport.requests.filter(r => r.path.endsWith('native-turn'))[1].body.audio as string);
  const wav = Buffer.from(second, 'base64');
  expect(wav.toString('ascii', 0, 4)).toBe('RIFF');
  expect([...Array.from({ length: (wav.length - 44) / 2 }, (_, i) => wav.readInt16LE(44 + i * 2))].filter(v => v >= 2500).length).toBeGreaterThan(3000);
  await history(page);
  await expect(page.locator('.history-messages')).toContainText('Respuesta nativa 2.');
  await expect(page.locator('.history-messages')).not.toContainText('Respuesta nativa 1.');
  await expect(page.locator('.history-messages')).not.toContainText('Texto antiguo');
  expect(forbidden).toEqual([]);
});

test('Portuguese switch stops the old movie voice and starts a fresh localized native session', async ({ page }) => {
  const forbidden = await game(page);
  await capture(page);
  await expect(page.locator('.world--moss')).toBeVisible();
  await page.getByRole('button', { name: 'Pausar la historia' }).click();
  await page.getByRole('button', { name: 'Português', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'pt-BR');
  await expect.poll(() => page.evaluate(() => window.__nativeTransport.tracksStopped)).toBe(1);
  await page.getByRole('button', { name: 'Iniciar conversa por voz', exact: true }).click();
  await expect(page.getByLabel('Estou ouvindo', { exact: true })).toBeVisible();
  await capture(page);
  await expect.poll(() => page.evaluate(() => window.__nativeTransport.requests.filter(r => r.path.endsWith('native-turn')).length)).toBe(2);
  expect(await page.evaluate(() => window.__nativeTransport.requests.filter(r => r.path.endsWith('native-turn')).map(r => r.body.locale))).toEqual(['es', 'pt']);
  await page.getByRole('button', { name: 'Pausar a história' }).click();
  await page.getByRole('button', { name: 'Encerrar conversa por voz', exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.__nativeTransport.tracksStopped)).toBe(2);
  expect(forbidden).toEqual([]);
});
