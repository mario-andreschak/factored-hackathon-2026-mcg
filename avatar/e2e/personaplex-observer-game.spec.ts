import { test, expect, type Page } from '@playwright/test';
import { mockedPersonaPlex } from './fixtures/personaplex-transport';

async function observedGame(page: Page, withComputer = false) {
  await mockedPersonaPlex(page);
  const evidence = { admissions: [] as string[], configReads: 0, pipelines: [] as string[] };
  page.on('request', request => {
    const pathname = new URL(request.url()).pathname;
    if (pathname === '/api/avatar/personaplex-session') evidence.admissions.push(request.postDataJSON().avatar);
    if (/^\/api\/avatar\/(?:transcribe|conversation|speech|realtime|gemini-token)$/.test(pathname)) evidence.pipelines.push(pathname);
  });
  await page.route('**/api/avatar/config', route => {
    evidence.configReads++;
    return route.fulfill({ json: {
      voiceAvailable: evidence.admissions.length === 0, voiceProvider: 'personaplex', voiceAvatar: 'moss',
      backgroundAsrAvailable: true, backendAvailable: withComputer, saviaUrl: withComputer ? '/savia/' : '',
      mode: withComputer ? 'connected' : 'demo', realtimeModel: '',
    } });
  });
  const configured = page.waitForResponse('**/api/avatar/config');
  await page.goto('/'); await configured;
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => resolve())));
  await page.getByRole('button', { name: 'Despertar el mundo' }).click();
  await expect(page.getByRole('status')).toHaveText('Te escucho');
  return evidence;
}

async function completeUtterance(page: Page) {
  await page.evaluate(() => {
    window.__personaplexTransport.samples(.3, 4);
    window.__personaplexTransport.samples(0, 14);
  });
}

test('observed speech changes scenery while the fixed native voice role and PCM remain active', async ({ page }) => {
  const evidence = await observedGame(page);
  const text = 'I am furious about this unrecognized charge.';
  let observations = 0;
  await page.route('**/api/avatar/transcribe', route => {
    observations++;
    return route.fulfill({ json: { text } });
  });
  await completeUtterance(page);
  await expect(page.locator('.world-painting--ready').last()).toHaveAttribute('src', '/scenes/07-old-ruins.webp');
  await expect(page.locator('main.story-moss')).toBeVisible();
  await expect(page.locator('.world--moss')).toBeVisible();
  await expect(page.getByLabel('Te escucho', { exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.__personaplexTransport.messages.filter(Array.isArray).length)).toBe(18);
  const sources = await page.evaluate(() => window.__personaplexTransport.sourcesStarted);
  await page.evaluate(() => window.__personaplexTransport.audio(1, 0, 5760));
  await expect.poll(() => page.evaluate(() => window.__personaplexTransport.sourcesStarted)).toBe(sources + 1);
  await expect(page.locator('.world')).toHaveAttribute('data-phase', 'speaking');
  await page.getByRole('button', { name: 'Pausar la historia' }).click();
  await page.getByRole('button', { name: 'Palabras del camino' }).click();
  await expect(page.locator('.history-user p')).toHaveText(text);
  expect(observations).toBe(1);
  expect(evidence.admissions).toEqual(['moss']);
  expect(evidence.pipelines).toEqual(['/api/avatar/transcribe']);
  expect(await page.evaluate(() => ({ tracks: window.__personaplexTransport.tracksStopped, sockets: window.__personaplexTransport.socketsClosed }))).toEqual({ tracks: 0, sockets: 0 });
});

test('first Savia login withholds a pending background result before retaining the native connection', async ({ page }) => {
  await page.route('**/savia/', route => route.fulfill({ contentType: 'text/html', body:
    '<!doctype html><html><body><button>Public login fixture</button></body></html>' }));
  await page.route('**/savia/api/auth/me', route => route.fulfill({ status: 401, json: { authenticated: false } }));
  await page.route('**/savia/api/auth/login', route => route.fulfill({ json: { authenticated: true } }));
  const evidence = await observedGame(page, true);
  // Native VAD opens the scene at 80ms; stay below the observer's 120ms onset.
  await page.evaluate(() => {
    window.__personaplexTransport.samples(.1, 2);
    window.__personaplexTransport.samples(0, 14);
  });
  await expect(page.locator('.world--moss')).toBeVisible();
  await page.getByRole('button', { name: 'Mirar el estanque' }).click();
  await expect(page.frameLocator('iframe').getByRole('button', { name: 'Public login fixture' })).toBeVisible();
  const frame = page.frames().find(candidate => candidate.url().endsWith('/savia/'))!;
  await page.getByRole('button', { name: 'Cerrar computadora' }).click();
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  let observations = 0, fulfilled = false;
  await page.route('**/api/avatar/transcribe', async route => {
    observations++;
    if (observations === 1) {
      await pending;
      await route.fulfill({ json: { text: 'Prior login text about an unrecognized charge.' } }).catch(() => {});
      fulfilled = true;
    } else await route.fulfill({ json: { text: 'A new public thought.' } });
  });
  await completeUtterance(page);
  await expect.poll(() => observations).toBe(1);
  const reads = evidence.configReads;
  // Exercise the installed Workbench fetch bridge while the observer is active.
  // All authentication traffic is fulfilled by this synthetic browser fixture.
  await frame.evaluate(() => fetch('/savia/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(response => response.status));
  await expect.poll(() => evidence.configReads).toBeGreaterThan(reads);
  release(); await expect.poll(() => fulfilled).toBe(true);
  await completeUtterance(page);
  await expect.poll(() => observations).toBe(2);
  await page.getByRole('button', { name: 'Pausar la historia' }).click();
  await page.getByRole('button', { name: 'Palabras del camino' }).click();
  await expect(page.locator('.history-user p')).toHaveText('A new public thought.');
  await expect(page.locator('.history-user')).toHaveCount(1);
  await expect(page.locator('main.story-moss')).toBeVisible();
  expect(evidence.admissions).toEqual(['moss']);
  expect(evidence.pipelines).toEqual(['/api/avatar/transcribe', '/api/avatar/transcribe']);
  expect(await page.evaluate(() => ({ tracks: window.__personaplexTransport.tracksStopped, sockets: window.__personaplexTransport.socketsClosed }))).toEqual({ tracks: 0, sockets: 0 });
});
