import { test, expect, type Page } from '@playwright/test';
import { mockedPersonaPlex } from './fixtures/personaplex-transport';

async function nativeGame(page: Page, avatar: 'moss' | 'orbit' | 'spark') {
  await mockedPersonaPlex(page);
  const observed = { admissions: [] as string[], configReads: 0, otherVoiceRequests: [] as string[] };
  page.on('request', request => {
    if (new URL(request.url()).pathname === '/api/avatar/personaplex-session') observed.admissions.push(request.postDataJSON().avatar);
    if (/\/api\/avatar\/(?:transcribe|conversation|speech|realtime|gemini-token)(?:\?|$)/.test(request.url())) observed.otherVoiceRequests.push(request.url());
  });
  await page.route('**/api/avatar/config', route => {
    observed.configReads++;
    return route.fulfill({ json: { voiceAvailable: observed.admissions.length === 0,
      voiceAvatar: avatar, voiceProvider: 'personaplex', backendAvailable: false,
      saviaUrl: '', mode: 'demo', realtimeModel: '' } });
  });
  const config = page.waitForResponse('**/api/avatar/config');
  await page.goto('/'); await config;
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => resolve())));
  await page.getByRole('button', { name: 'Despertar el mundo' }).click();
  await expect.poll(() => page.evaluate(() => window.__personaplexTransport.urls.length)).toBe(1);
  await expect(page.getByRole('status')).toHaveText('Te escucho');
  // Activity opens the world without manufacturing a user transcription.
  await page.evaluate(() => { window.__personaplexTransport.samples(.1, 3); window.__personaplexTransport.samples(0, 14); });
  await expect(page.locator(`.world--${avatar}`)).toBeVisible();
  await expect(page.getByLabel('Te escucho', { exact: true })).toBeVisible();
  return observed;
}

test('typed fallback ends the fixed native role before transcript mood changes the world', async ({ page }) => {
  const observed = await nativeGame(page, 'spark');
  await page.keyboard.press('t');
  await page.getByLabel('Escribe a tu compañero').fill('Please explain this plan');
  await page.getByRole('button', { name: 'Enviar mensaje', exact: true }).click();
  await expect(page.locator('.world--orbit')).toBeVisible();
  await expect(page.getByLabel('Vista previa del mundo', { exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.__personaplexTransport.tracksStopped)).toBe(1);
  expect(await page.evaluate(() => window.__personaplexTransport.socketsClosed)).toBe(1);
  expect(observed.admissions).toEqual(['spark']);
  expect(observed.otherVoiceRequests).toEqual([]);
});

test('forest gallery closes a different fixed native role before selecting Moss', async ({ page }) => {
  const observed = await nativeGame(page, 'orbit');
  await page.getByRole('button', { name: 'Pausar la historia' }).click();
  await page.getByRole('button', { name: 'Explorar otro lugar' }).click();
  await page.getByRole('button', { name: 'Viajar a El bosque de los faroles', exact: true }).click();
  await expect(page.locator('.world--moss')).toBeVisible();
  await expect(page.locator('.world-painting--ready').last()).toHaveAttribute('src', '/scenes/02-lantern-grove.webp');
  await expect(page.getByLabel('Vista previa del mundo', { exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.__personaplexTransport.tracksStopped)).toBe(1);
  expect(await page.evaluate(() => window.__personaplexTransport.socketsClosed)).toBe(1);
  expect(observed.admissions).toEqual(['orbit']);
  expect(observed.otherVoiceRequests).toEqual([]);
});

test('ending a consumed native lease refreshes availability and does not offer another admission', async ({ page }) => {
  const observed = await nativeGame(page, 'moss');
  await page.getByRole('button', { name: 'Pausar la historia' }).click();
  await page.getByRole('button', { name: 'Terminar conversación de voz', exact: true }).click();
  await expect.poll(() => observed.configReads).toBeGreaterThanOrEqual(2);
  await expect(page.getByRole('button', { name: 'Iniciar conversación de voz', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Terminar conversación de voz', exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => window.__personaplexTransport.tracksStopped)).toBe(1);
  expect(observed.admissions).toEqual(['moss']);
  expect(observed.otherVoiceRequests).toEqual([]);
});
