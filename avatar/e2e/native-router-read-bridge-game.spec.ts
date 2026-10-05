import { test, expect, type Frame, type Page } from '@playwright/test';
import { mockedNative } from './fixtures/native-router-transport';

const inquiry = 'Consulta mis pagos recientes.';
const reply = 'Resultado sintético de Savia: el pago de $42.17 no tiene una disputa abierta. No se realizó ninguna acción.';
const taskId = 'synthetic-visible-read-receipt';

async function readGame(page: Page, options: { holdRead?: boolean; holdReceipt?: boolean } = {}) {
  const evidence = { posts: [] as { message: string }[], receipts: [] as Record<string, unknown>[], unexpected: [] as string[], authReads: 0 };
  let release!: () => void;
  const readReady = options.holdRead ? new Promise<void>(resolve => { release = resolve; }) : Promise.resolve();
  let releaseReceipt!: () => void;
  const receiptReady = options.holdReceipt ? new Promise<void>(resolve => { releaseReceipt = resolve; }) : Promise.resolve();
  // This blanket denial exists before navigation, the frame, or any voice gesture.
  await page.route('**/savia/**', route => {
    evidence.unexpected.push(new URL(route.request().url()).pathname);
    return route.fulfill({ status: 503, json: { error: 'Unmatched synthetic Savia operation' } });
  });
  await mockedNative(page, { passthroughPaths: ['/api/avatar/config', '/api/avatar/native-result-receipt'] });
  await page.route('**/api/avatar/config', route => route.fulfill({ json: {
    voiceProvider: 'openrouter-native', voiceAvailable: true, backgroundAsrAvailable: true,
    nativeReadBridgeAvailable: true, backendAvailable: true, saviaUrl: '/savia/', mode: 'connected', realtimeModel: '',
  } }));
  await page.route('**/api/avatar/native-result-receipt', async route => {
    const body = route.request().postDataJSON() as Record<string, unknown>; evidence.receipts.push(body);
    if (body.reply !== reply || body.locale !== 'es' || Object.keys(body).length !== 2)
      return route.fulfill({ status: 409, json: { error: 'Synthetic owned result mismatch' } });
    await receiptReady; return route.fulfill({ json: { taskId } });
  });
  await page.route('**/savia/api/auth/me', route => { evidence.authReads++; return route.fulfill({ json: { authenticated: true } }); });
  await page.route('**/savia/api/chat', async route => {
    if (route.request().method() !== 'POST') { evidence.unexpected.push('non-POST synthetic read'); return route.fulfill({ status: 405 }); }
    evidence.posts.push(route.request().postDataJSON()); await readReady;
    return route.fulfill({ json: { reply } });
  });
  await page.route('**/savia/', route => route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><head><meta charset="utf-8"><style>body{padding:24px;font:16px system-ui}button,input{padding:12px}input{width:65%}</style></head><body>
    <h1>Savia sintética</h1><button id="launch">Hablemos</button><div id="chat"></div><script>
    window.evidence = { submitted: [], setters: 0, inputEvents: 0, sendClicks: 0 };
    const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
    Object.defineProperty(HTMLInputElement.prototype, 'value', {...descriptor, set(value) { window.evidence.setters++; descriptor.set.call(this, value); }});
    document.querySelector('#launch').onclick = () => {
      document.querySelector('#chat').innerHTML = '<form><input aria-label="Mensaje para el asistente" maxlength="2000"><button aria-label="Enviar mensaje" disabled>Enviar</button></form>';
      const form = document.querySelector('form'), input = form.querySelector('input'), send = form.querySelector('button');
      input.addEventListener('input', () => { window.evidence.inputEvents++; send.disabled = !input.value.trim(); });
      form.onsubmit = async event => {
        event.preventDefault(); const message = input.value; window.evidence.submitted.push(message); window.evidence.sendClicks++; send.disabled = true;
        const busy = document.createElement('div'); busy.className = 'chat-thinking'; busy.textContent = 'Consultando únicamente datos sintéticos'; document.body.append(busy);
        const response = await fetch('/savia/api/chat', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message})});
        const body = await response.json(); busy.remove(); const answer = document.createElement('div'); answer.className = 'chat-message assistant'; answer.textContent = body.reply; document.body.append(answer); send.disabled = false;
      };
    };
    </script></body></html>` }));
  const configured = page.waitForResponse('**/api/avatar/config'); await page.goto('/'); await configured;
  await page.getByRole('button', { name: 'Despertar el mundo' }).click(); await expect(page.getByRole('status')).toHaveText('Te escucho');
  return { evidence, releaseRead: () => release?.(), releaseReceipt: () => releaseReceipt?.() };
}
async function typeRead(page: Page) {
  await page.keyboard.press('t'); await page.getByLabel('Escribe a tu compañero').fill(inquiry);
  await page.getByRole('button', { name: 'Enviar mensaje', exact: true }).click();
}
async function bankFrame(page: Page): Promise<Frame> {
  await expect(page.locator('.workbench-open')).toBeVisible();
  await expect(page.frameLocator('iframe').getByRole('button', { name: 'Hablemos' })).toBeVisible();
  return page.frames().find(frame => new URL(frame.url()).pathname === '/savia/')!;
}
const nativeRequests = (page: Page, suffix: string) => page.evaluate(suffix => window.__nativeTransport.requests.filter(item => item.path.endsWith(suffix)), suffix);
async function endVoice(page: Page) {
  await page.getByRole('button', { name: 'Pausar la historia' }).click();
  await page.getByRole('button', { name: 'Terminar conversación de voz', exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.__nativeTransport.tracksStopped)).toBe(1);
}

test('typed read visibly operates the real Workbench and queues its owned result until input and output are clear', async ({ page }) => {
  const { evidence, releaseRead } = await readGame(page, { holdRead: true });
  await page.evaluate(() => { window.__nativeTransport.duration = 3; window.__nativeTransport.autoComplete = false; });
  await typeRead(page); const frame = await bankFrame(page);
  await expect(page.locator('.quiet-work')).toBeVisible();
  await expect(page.locator('.world')).toHaveAttribute('data-phase', 'speaking');
  await expect(page.locator('.agent-cursor')).toBeVisible();
  await expect.poll(() => evidence.posts).toEqual([{ message: inquiry }]);
  expect(await frame.evaluate(() => (window as Window & { evidence: unknown }).evidence)).toEqual({ submitted: [inquiry], setters: 1, inputEvents: 1, sendClicks: 1 });
  expect(await page.locator('.workbench-open').getAttribute('aria-hidden')).toBe('false');
  expect(await page.locator('.workbench-open').evaluate(element => element.inert)).toBe(false);
  releaseRead(); await expect.poll(() => evidence.receipts).toEqual([{ reply, locale: 'es' }]);
  expect(await nativeRequests(page, 'native-result')).toHaveLength(0); // The original native HTTP response is still open.
  await expect(page.locator('.workbench-footer')).toContainText('Savia respondió a tu consulta');
  await expect(frame.locator('.chat-message.assistant')).toHaveText(reply);
  await page.evaluate(() => { window.__nativeTransport.duration = .25; window.__nativeTransport.autoComplete = true; window.__nativeTransport.emit(.07, .6); });
  expect(await nativeRequests(page, 'native-result')).toHaveLength(0); // The new utterance owns input.
  await page.evaluate(() => window.__nativeTransport.emit(0, 2.1));
  await expect.poll(async () => (await nativeRequests(page, 'native-result')).length).toBe(1);
  expect((await nativeRequests(page, 'native-result'))[0].body).toEqual({ taskId, avatar: 'orbit', locale: 'es' });
  await expect.poll(async () => (await nativeRequests(page, 'native-played')).some(item => item.body.turnId === 'fixture-native-3' && item.body.complete === true)).toBe(true);
  const order = await page.evaluate(() => window.__nativeTransport.requests.filter(item => /native-(?:turn|played|result)$/.test(item.path)).map(item => ({ path: item.path, complete: item.body.complete, turnId: item.body.turnId })));
  const heardSecond = order.findIndex(item => item.path.endsWith('native-played') && item.turnId === 'fixture-native-2' && item.complete === true);
  expect(order.findIndex(item => item.path.endsWith('native-result'))).toBeGreaterThan(heardSecond);
  expect(await nativeRequests(page, 'native-observe')).toHaveLength(0); // Pond/task privacy pauses the independent observer.
  expect(evidence.posts).toEqual([{ message: inquiry }]); expect(evidence.unexpected).toEqual([]); expect(evidence.authReads).toBeGreaterThan(0);
  // Mock PCM and generic captions prove routing/playback, never semantic accuracy of spoken banking facts.
});

test('End Voice after coordinator admission but before visible click prevents a synthetic bank POST', async ({ page }) => {
  const { evidence } = await readGame(page); await page.evaluate(() => { window.__nativeTransport.autoComplete = false; });
  await typeRead(page);
  const timing = await page.evaluate(async () => {
    const waitFor = async (find: () => HTMLElement | null | undefined) => {
      const deadline = performance.now() + 5000;
      while (performance.now() < deadline) { const found = find(); if (found) return found; await new Promise<void>(resolve => requestAnimationFrame(() => resolve())); }
      throw new Error('Synthetic coordinator UI was unavailable');
    };
    await waitFor(() => document.querySelector<HTMLElement>('.quiet-work')); const admittedAt = performance.now();
    (await waitFor(() => document.querySelector<HTMLElement>('.pause-control'))).click();
    const end = await waitFor(() => [...document.querySelectorAll('button')].find(button => button.textContent?.trim() === 'Terminar conversación de voz'));
    end.click(); return { elapsed: performance.now() - admittedAt };
  });
  expect(timing.elapsed).toBeLessThan(400); // The delegate's initial delay, before Workbench.execute.
  await expect.poll(() => page.evaluate(() => window.__nativeTransport.tracksStopped)).toBe(1);
  await expect(page.locator('.quiet-work')).toHaveCount(0); await expect(page.locator('.agent-cursor')).toHaveCount(0);
  const frame = await bankFrame(page);
  expect(await frame.evaluate(() => (window as Window & { evidence: { submitted: string[] } }).evidence.submitted)).toEqual([]);
  expect(evidence.posts).toEqual([]); expect(evidence.receipts).toEqual([]); expect(await nativeRequests(page, 'native-result')).toHaveLength(0);
  expect(evidence.unexpected).toEqual([]);
});

test('an already clicked read finishes as observed text after End Voice without a late receipt or spoken result', async ({ page }) => {
  const { evidence, releaseRead } = await readGame(page, { holdRead: true });
  await page.evaluate(() => { window.__nativeTransport.autoComplete = false; }); await typeRead(page); const frame = await bankFrame(page);
  await expect.poll(() => evidence.posts).toEqual([{ message: inquiry }]);
  await endVoice(page); const sourcesAtEnd = await page.evaluate(() => window.__nativeTransport.sourcesStarted);
  releaseRead(); await expect(frame.locator('.chat-message.assistant')).toHaveText(reply);
  await expect(page.locator('.sr-only[aria-live="polite"]')).toHaveText(reply); await expect(page.locator('.quiet-work')).toHaveCount(0);
  expect(evidence.posts).toEqual([{ message: inquiry }]); expect(evidence.receipts).toEqual([]);
  expect(await nativeRequests(page, 'native-result')).toHaveLength(0); expect(await page.evaluate(() => window.__nativeTransport.sourcesStarted)).toBe(sourcesAtEnd);
  expect(evidence.unexpected).toEqual([]);
});

test('an admitted read completing after End and reconnect cannot acquire the new native voice owner', async ({ page }) => {
  const { evidence, releaseRead } = await readGame(page, { holdRead: true });
  await page.evaluate(() => { window.__nativeTransport.autoComplete = false; }); await typeRead(page); const frame = await bankFrame(page);
  await expect.poll(() => evidence.posts).toEqual([{ message: inquiry }]); await endVoice(page);
  await page.getByRole('button', { name: 'Iniciar conversación de voz', exact: true }).click();
  await expect.poll(async () => (await nativeRequests(page, 'native-reset')).length).toBe(2);
  await expect(page.getByLabel('Te escucho', { exact: true })).toBeVisible();
  const sourcesAtReconnect = await page.evaluate(() => window.__nativeTransport.sourcesStarted);
  releaseRead(); await expect(frame.locator('.chat-message.assistant')).toHaveText(reply);
  await expect(page.locator('.sr-only[aria-live="polite"]')).toHaveText(reply); await expect(page.locator('.quiet-work')).toHaveCount(0);
  expect(evidence.receipts).toEqual([]); expect(await nativeRequests(page, 'native-result')).toHaveLength(0);
  expect(await page.evaluate(() => window.__nativeTransport.sourcesStarted)).toBe(sourcesAtReconnect);
  expect(evidence.posts).toEqual([{ message: inquiry }]); expect(evidence.unexpected).toEqual([]);
});

test('receipt lookup resolving after End and reconnect cannot narrate its old read in the new voice session', async ({ page }) => {
  const { evidence, releaseReceipt } = await readGame(page, { holdReceipt: true });
  await page.evaluate(() => { window.__nativeTransport.autoComplete = false; }); await typeRead(page); const frame = await bankFrame(page);
  await expect.poll(() => evidence.receipts).toEqual([{ reply, locale: 'es' }]);
  await expect(frame.locator('.chat-message.assistant')).toHaveText(reply); await endVoice(page);
  await page.getByRole('button', { name: 'Iniciar conversación de voz', exact: true }).click();
  await expect.poll(async () => (await nativeRequests(page, 'native-reset')).length).toBe(2);
  await expect(page.getByLabel('Te escucho', { exact: true })).toBeVisible();
  const sourcesAtReconnect = await page.evaluate(() => window.__nativeTransport.sourcesStarted);
  releaseReceipt(); await expect(page.locator('.sr-only[aria-live="polite"]')).toHaveText(reply);
  expect(await nativeRequests(page, 'native-result')).toHaveLength(0);
  expect(await page.evaluate(() => window.__nativeTransport.sourcesStarted)).toBe(sourcesAtReconnect);
  expect(evidence.receipts).toEqual([{ reply, locale: 'es' }]); expect(evidence.unexpected).toEqual([]);
});
