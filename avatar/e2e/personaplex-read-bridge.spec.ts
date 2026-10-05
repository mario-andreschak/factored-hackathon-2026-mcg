import { test, expect, type Page, type Frame } from '@playwright/test';
import { mockedPersonaPlex } from './fixtures/personaplex-transport';

const inquiry = 'Please check my recent payments.';
const reply = 'Synthetic Savia result: this payment has no open dispute. No action was taken.';

async function nativeReadGame(page: Page, options: { enabled?: boolean; signedIn?: boolean; responseDelay?: number } = {}) {
  await mockedPersonaPlex(page);
  const evidence = { signedIn: options.signedIn ?? true, observations: 0, nextText: inquiry, pipelines: [] as string[], authReads: 0 };
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (/^\/api\/avatar\/(?:transcribe|conversation|speech|realtime|gemini-token)$/.test(path)) evidence.pipelines.push(path);
  });
  await page.route('**/api/avatar/config', route => route.fulfill({ json: {
    voiceAvailable: true, voiceProvider: 'personaplex', voiceAvatar: 'moss', backgroundAsrAvailable: true,
    nativeReadBridgeAvailable: options.enabled ?? true, backendAvailable: true,
    saviaUrl: '/savia/', mode: 'connected', realtimeModel: '',
  } }));
  await page.route('**/api/avatar/transcribe', route => {
    evidence.observations++; return route.fulfill({ json: { text: evidence.nextText } });
  });
  await page.route('**/savia/api/auth/me', route => {
    evidence.authReads++; return route.fulfill({ status: evidence.signedIn ? 200 : 401, json: { authenticated: evidence.signedIn } });
  });
  await page.route('**/savia/api/auth/login', route => { evidence.signedIn = true; return route.fulfill({ json: { authenticated: true } }); });
  await page.route('**/savia/api/auth/logout', route => { evidence.signedIn = false; return route.fulfill({ status: 204 }); });
  await page.route('**/savia/', route => route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><head><meta charset="utf-8"><style>body{padding:24px;font:16px system-ui}button,input{padding:12px}input{width:65%}</style></head><body>
    <h1>Synthetic Savia</h1><button id="login">Sign in to the fixture</button><button id="launch">Hablemos</button><div id="chat"></div>
    <script>
    window.evidence = { submitted: [], setters: 0, inputEvents: 0 };
    const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
    Object.defineProperty(HTMLInputElement.prototype, 'value', {...descriptor, set(value) { window.evidence.setters++; descriptor.set.call(this, value); }});
    document.querySelector('#login').onclick = () => fetch('/savia/api/auth/login', {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    document.querySelector('#launch').onclick = () => {
      document.querySelector('#chat').innerHTML = '<form><input aria-label="Mensaje para el asistente" maxlength="2000"><button aria-label="Enviar mensaje" disabled>Send</button></form>';
      const form = document.querySelector('form'), input = form.querySelector('input'), send = form.querySelector('button');
      input.addEventListener('input', () => { window.evidence.inputEvents++; send.disabled = !input.value.trim(); });
      form.onsubmit = event => { event.preventDefault(); window.evidence.submitted.push(input.value); send.disabled = true;
        const thinking = document.createElement('div'); thinking.className = 'chat-thinking'; thinking.textContent = 'Reading the synthetic account'; document.body.append(thinking);
        setTimeout(() => { thinking.remove(); const response = document.createElement('div'); response.className = 'chat-message assistant'; response.textContent = ${JSON.stringify(reply)}; document.body.append(response); send.disabled = false; }, ${options.responseDelay ?? 1000});
      };
    };
    </script></body></html>` }));
  const configured = page.waitForResponse('**/api/avatar/config');
  await page.goto('/'); await configured;
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => resolve())));
  await page.getByRole('button', { name: 'Despertar el mundo' }).click();
  await expect(page.getByRole('status')).toHaveText('Te escucho');
  return evidence;
}

async function utterance(page: Page) {
  await page.evaluate(() => { window.__personaplexTransport.samples(.3, 4); window.__personaplexTransport.samples(0, 14); });
}
async function bankFrame(page: Page) {
  await expect(page.frameLocator('iframe').getByRole('button', { name: 'Hablemos' })).toBeVisible();
  return page.frames().find(frame => frame.url().endsWith('/savia/'))!;
}
async function submissions(frame: Frame) { return frame.evaluate(() => (window as Window & { evidence: { submitted: string[] } }).evidence.submitted); }
async function endNative(page: Page) { await page.evaluate(() => window.__personaplexTransport.emit({ type: 'error' })); }

test('bridge disabled keeps observed account speech in the world without a bank submission', async ({ page }) => {
  const evidence = await nativeReadGame(page, { enabled: false });
  await utterance(page); await expect.poll(() => evidence.observations).toBe(1);
  await expect(page.locator('.world--moss')).toBeVisible();
  await expect(page.locator('.workbench-open')).toHaveCount(0);
  await expect(page.locator('iframe')).toHaveCount(0);
  expect(evidence.authReads).toBe(0);
  expect(evidence.pipelines).toEqual(['/api/avatar/transcribe']);
});

test('one spoken read visibly submits once while native output is held and actual result stays text', async ({ page }) => {
  const evidence = await nativeReadGame(page, { responseDelay: 2200 });
  await utterance(page);
  const frame = await bankFrame(page);
  await expect.poll(() => submissions(frame)).toEqual([inquiry]);
  const started = await page.evaluate(() => window.__personaplexTransport.sourcesStarted);
  await page.evaluate(() => {
    const t = window.__personaplexTransport, generation = t.messages.filter(message => !Array.isArray(message) && message.type === 'interrupt').length;
    t.audio(generation, 0, 1920); t.emit({ type: 'transcript', role: 'assistant', id: 'unsafe-native-result', text: 'An invented bank answer', done: true, generation });
    t.samples(.2, 4); t.samples(0, 14);
  });
  await expect(page.locator('.workbench-footer')).toContainText('Savia respondió a tu consulta');
  await expect(page.locator('.sr-only[aria-live="polite"]')).toHaveText(reply);
  expect(await page.evaluate(() => window.__personaplexTransport.sourcesStarted)).toBe(started);
  expect(await submissions(frame)).toEqual([inquiry]);
  expect(evidence.observations).toBe(1);
  expect(evidence.pipelines).toEqual(['/api/avatar/transcribe']);
  expect(await frame.evaluate(() => (window as Window & { evidence: unknown }).evidence)).toEqual({ submitted: [inquiry], setters: 1, inputEvents: 1 });
  expect(await page.evaluate(() => ({ stopped: window.__personaplexTransport.tracksStopped, closed: window.__personaplexTransport.socketsClosed }))).toEqual({ stopped: 0, closed: 0 });
});

test('first sign-in retains native session and only then admits the pending spoken inquiry', async ({ page }) => {
  const evidence = await nativeReadGame(page, { signedIn: false });
  await utterance(page); const frame = await bankFrame(page);
  await expect(page.locator('.sr-only[aria-live="polite"]')).toHaveText('Ven al estanque. Inicia sesión para ver tu cuenta.');
  expect(await submissions(frame)).toEqual([]);
  await expect(page.locator('.quiet-work')).toHaveCount(0);
  const authReads = evidence.authReads;
  await frame.getByRole('button', { name: 'Sign in to the fixture' }).click();
  await expect.poll(() => submissions(frame)).toEqual([inquiry]);
  await expect(page.locator('.sr-only[aria-live="polite"]')).toHaveText(reply);
  expect(evidence.authReads).toBeGreaterThan(authReads);
  expect(await page.evaluate(() => ({ stopped: window.__personaplexTransport.tracksStopped, closed: window.__personaplexTransport.socketsClosed }))).toEqual({ stopped: 0, closed: 0 });
  expect(evidence.observations).toBe(1);
});

test('closing sign-in erases the pending inquiry instead of replaying it after login', async ({ page }) => {
  await nativeReadGame(page, { signedIn: false }); await utterance(page);
  const frame = await bankFrame(page);
  await expect(page.locator('.sr-only[aria-live="polite"]')).toContainText('Inicia sesión');
  await page.getByRole('button', { name: 'Cerrar computadora' }).click();
  await frame.evaluate(() => fetch('/savia/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }));
  await page.getByRole('button', { name: 'Mirar el estanque' }).click();
  await expect(frame.getByRole('button', { name: 'Hablemos' })).toBeVisible();
  expect(await submissions(frame)).toEqual([]);
  await expect(page.locator('.quiet-work')).toHaveCount(0);
});

test('native disconnect erases an inquiry awaiting authentication', async ({ page }) => {
  await nativeReadGame(page, { signedIn: false }); await utterance(page); const frame = await bankFrame(page);
  await expect(page.locator('.sr-only[aria-live="polite"]')).toContainText('Inicia sesión');
  await endNative(page);
  await expect.poll(() => page.evaluate(() => window.__personaplexTransport.tracksStopped)).toBe(1);
  await frame.getByRole('button', { name: 'Sign in to the fixture' }).click();
  expect(await submissions(frame)).toEqual([]);
  await expect(page.locator('.quiet-work')).toHaveCount(0);
});

test('an already admitted visible read completes when native voice disconnects', async ({ page }) => {
  await nativeReadGame(page, { responseDelay: 1500 }); await utterance(page); const frame = await bankFrame(page);
  await expect.poll(() => submissions(frame)).toEqual([inquiry]);
  await endNative(page);
  await expect.poll(() => page.evaluate(() => window.__personaplexTransport.tracksStopped)).toBe(1);
  await expect(page.locator('.sr-only[aria-live="polite"]')).toHaveText(reply);
  expect(await submissions(frame)).toEqual([inquiry]);
});

test('actions, ambiguous mentions and oversized transcripts never enter the native read bridge', async ({ page }) => {
  const evidence = await nativeReadGame(page);
  for (const [index, text] of ['Payments.', 'Please refund this payment.', 'File a dispute for this charge.', 'Check payments ' + 'x'.repeat(2000)].entries()) {
    evidence.nextText = text; await utterance(page); await expect.poll(() => evidence.observations).toBe(index + 1);
  }
  await expect(page.locator('.workbench-open')).toHaveCount(0);
  await expect(page.locator('iframe')).toHaveCount(0);
  expect(evidence.authReads).toBe(0);
});

test('logout erases a pending sign-in inquiry before any visible submission', async ({ page }) => {
  await nativeReadGame(page, { signedIn: false }); await utterance(page); const frame = await bankFrame(page);
  await expect(page.locator('.sr-only[aria-live="polite"]')).toContainText('Inicia sesión');
  await frame.evaluate(() => fetch('/savia/api/auth/logout', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }));
  await expect.poll(() => page.evaluate(() => window.__personaplexTransport.tracksStopped)).toBe(1);
  await expect(page.locator('.sr-only[aria-live="polite"]')).toBeEmpty();
  expect(await submissions(frame)).toEqual([]);
});

test('first login arriving during an older authentication check gets a fresh proof before one read', async ({ page }) => {
  const evidence = await nativeReadGame(page, { signedIn: false });
  let release!: () => void, checks = 0;
  const oldCheck = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/savia/api/auth/me', async route => {
    checks++;
    if (checks === 1) { await oldCheck; await route.fulfill({ status: 401, json: { authenticated: false } }); }
    else await route.fulfill({ status: evidence.signedIn ? 200 : 401, json: { authenticated: evidence.signedIn } });
  });
  await utterance(page); const frame = await bankFrame(page);
  await expect.poll(() => checks).toBeGreaterThan(0);
  await frame.getByRole('button', { name: 'Sign in to the fixture' }).click();
  await expect.poll(() => evidence.signedIn).toBe(true);
  expect(await submissions(frame)).toEqual([]);
  release(); await expect.poll(() => submissions(frame)).toEqual([inquiry]);
  await expect(page.locator('.sr-only[aria-live="polite"]')).toHaveText(reply);
  expect(checks).toBeGreaterThan(1);
  expect(await page.evaluate(() => window.__personaplexTransport.socketsClosed)).toBe(0);
});

test('native disconnect during visible cursor travel prevents a not-yet-admitted submission', async ({ page }) => {
  await nativeReadGame(page); await utterance(page); const frame = await bankFrame(page);
  await expect(page.locator('.workbench-footer')).toContainText('Abriendo el asistente de Savia');
  await endNative(page);
  await expect.poll(() => page.evaluate(() => window.__personaplexTransport.tracksStopped)).toBe(1);
  await expect(page.locator('.agent-cursor')).toHaveCount(0);
  await expect(page.locator('.quiet-work')).toHaveCount(0);
  expect(await submissions(frame)).toEqual([]);
});

test('logout after an admitted read withholds the actual prior-account reply from Game', async ({ page }) => {
  await nativeReadGame(page, { responseDelay: 1400 }); await utterance(page); const frame = await bankFrame(page);
  await expect.poll(() => submissions(frame)).toEqual([inquiry]);
  await frame.evaluate(() => fetch('/savia/api/auth/logout', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }));
  await expect(frame.locator('.chat-message.assistant')).toHaveText(reply);
  await expect(page.locator('.sr-only[aria-live="polite"]')).toBeEmpty();
  await expect(page.locator('.quiet-work')).toHaveCount(0);
  expect(await page.evaluate(() => window.__personaplexTransport.socketsClosed)).toBe(1);
  expect(await submissions(frame)).toEqual([inquiry]);
});
