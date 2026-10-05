import { test, expect, type Page } from '@playwright/test';
import { mockRealtime } from './fixtures/realtime-transport';

const chapters = [
  ['El santuario de aguas tranquilas', '/scenes/01-pond-sanctuary.webp'],
  ['El bosque de los faroles', '/scenes/02-lantern-grove.webp'],
  ['Bajo la lluvia', '/scenes/03-rainy-canopy.webp'],
  ['Un horizonte distinto', '/scenes/04-cliff-sunrise.webp'],
  ['Una piedra a la vez', '/scenes/05-river-crossing.webp'],
  ['El reflejo de la luna', '/scenes/06-moonlit-lake.webp'],
  ['Lo que permanece', '/scenes/07-old-ruins.webp'],
  ['La pradera abierta', '/scenes/08-meadow.webp'],
  ['Sobre las nubes', '/scenes/09-floating-islands.webp'],
  ['El camino a casa', '/scenes/10-homecoming-sunset.webp'],
] as const;

async function openStory(page: Page, voice = false, banking = false) {
  await page.route('**/api/avatar/config', route => route.fulfill({
    json: { voiceAvailable: voice, backendAvailable: banking, saviaUrl: banking ? '/savia/' : '', mode: banking ? 'connected' : 'demo',
      realtimeModel: 'mock-only', voiceProvider: voice ? 'openai-realtime' : 'none' },
  }));
  const config = page.waitForResponse('**/api/avatar/config');
  await page.goto('/'); await config;
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => resolve())));
}
async function enterPreview(page: Page) {
  await page.getByRole('button', { name: 'Despertar el mundo' }).click();
  await expect(page.locator('.world')).toBeVisible();
}
async function pause(page: Page) {
  await page.getByRole('button', { name: 'Pausar la historia' }).click();
  await expect(page.getByLabel('Menú de pausa')).toBeVisible();
}
async function type(page: Page, message: string) {
  await page.keyboard.press('t');
  await page.getByLabel('Escribe a tu compañero').fill(message);
  await page.getByRole('button', { name: 'Enviar mensaje', exact: true }).click();
}

test.beforeEach(async ({ page }) => {
  // A failed test must never fall through to either paid voice provider.
  await page.route('**/api/avatar/realtime**', route => route.fulfill({ status: 503,
    json: { error: 'Paid voice is disabled in browser tests.' } }));
  await page.route('**/api/avatar/gemini-token', route => route.fulfill({ status: 503,
    json: { error: 'Paid native voice is disabled in browser tests.' } }));
  await page.route(/\/api\/avatar\/(?:speech|transcribe|conversation)(?:\?|$)/, route => route.fulfill({ status: 503,
    json: { error: 'Paid voice is disabled in browser tests.' } }));
  await page.addInitScript(() => {
    const narration = { texts: [] as string[], cancellations: 0 };
    Object.assign(window, { __narration: narration });
    Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: {
      cancel() { narration.cancellations++; }, speak(utterance: SpeechSynthesisUtterance) { narration.texts.push(utterance.text); },
    } });
  });
});

test('starts black with only drawn eyes and enters a world without chat chrome', async ({ page }) => {
  await openStory(page);
  await expect(page.locator('.drawn-eyes path')).toHaveCount(2);
  await expect(page.getByRole('button')).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'Despertar el mundo' })).toBeVisible();
  await expect(page.getByRole('heading')).toHaveCount(0);
  await expect(page.locator('.world')).toHaveCount(0);
  await expect(page.getByLabel('Escribe a tu compañero')).toHaveCount(0);
  await enterPreview(page);
  await expect(page.locator('.world-painting--ready')).toBeVisible();
  await expect(page.getByLabel('Vista previa del mundo', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Te escucho', { exact: true })).toHaveCount(0);
  await expect(page.locator('.movie-subtitle')).toHaveCount(0);
  await expect(page.getByLabel('Escribe a tu compañero')).toHaveCount(0);
  await expect(page.locator('header,footer,.chapter,.conversation-bar')).toHaveCount(0);
});

test('all ten places decode real artwork and can be visited through the pause menu', async ({ page }) => {
  // Ten deliberate scene fades and artwork decodes exceed one short interaction's budget.
  test.setTimeout(60000);
  await openStory(page); await enterPreview(page);
  for (const [name, asset] of chapters) {
    await pause(page);
    await page.getByRole('button', { name: 'Explorar otro lugar' }).click();
    await expect(page.getByRole('button', { name: /^Viajar a / })).toHaveCount(10);
    await page.getByRole('button', { name: `Viajar a ${name}`, exact: true }).click();
    await expect.poll(() => page.locator('.world-painting--ready').last().getAttribute('src')).toBe(asset);
    await expect.poll(() => page.locator('.world-painting--ready').last().evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)).toBe(true);
  }
});

test('typed mood selects a companion and manual choice controls later cues', async ({ page }) => {
  await openStory(page);
  await type(page, 'Please explain this payment');
  await expect(page.locator('.world--orbit')).toBeVisible();
  await pause(page);
  await expect(page.getByRole('button', { name: 'Elegir a Orbit' })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'Elegir a Spark' }).click();
  await type(page, 'I feel anxious and overwhelmed');
  await expect(page.locator('.world--spark')).toBeVisible();
  await expect(page.locator('canvas[data-character="rigged"]')).toBeVisible();
  const model = await page.request.get('/models/spark.glb');
  expect(model.status()).toBe(200);
  expect((await model.body()).subarray(0, 4).toString('ascii')).toBe('glTF');
  await pause(page);
  await expect(page.getByRole('button', { name: 'Elegir a Spark' })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'Palabras del camino' }).click();
  await expect(page.locator('.history-user')).toHaveCount(2);
  await expect(page.locator('.history-user').last()).toContainText('anxious and overwhelmed');
  await expect(page.locator('.history-assistant').first().locator('span')).toHaveText('ORBIT');
  await expect(page.locator('.history-assistant').last().locator('span')).toHaveText('SPARK');
  await expect(page.locator('.history-assistant').last()).toContainText('con impulso');
});

test('the offline preview remains silent and accessible text survives interruption', async ({ page }) => {
  await openStory(page); await type(page, 'Hello');
  await expect(page.locator('.world')).toHaveAttribute('data-phase', 'idle');
  expect(await page.evaluate(() => (window as Window & { __narration: { texts: string[] } }).__narration.texts)).toEqual([]);
  await page.keyboard.press('Space');
  await expect(page.locator('.world')).toHaveAttribute('data-phase', 'idle');
  await pause(page); await page.getByRole('button', { name: 'Palabras del camino' }).click();
  await expect(page.locator('.history-user')).toHaveCount(1);
  await expect(page.locator('.history-assistant')).toHaveCount(1);
});

test('character hotspot invites deliberate travel and interruption cancels pending travel', async ({ page }) => {
  await openStory(page); await type(page, 'Hello');
  const painting = page.locator('.world-painting--ready').last();
  await expect(painting).toHaveAttribute('src', chapters[0][1]);
  await page.getByRole('button', { name: 'Hablar con Moss' }).click();
  await expect(painting).toHaveAttribute('src', chapters[0][1]);
  await page.keyboard.press('Space');
  await page.waitForTimeout(2800); // Travel has a deliberate 2600ms narrative delay.
  await expect(painting).toHaveAttribute('src', chapters[0][1]);
  await page.getByRole('button', { name: 'Hablar con Moss' }).click();
  await expect.poll(() => painting.getAttribute('src')).toBe(chapters[1][1]);
});

test('gentler motion follows the system and can be changed in pause controls', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await openStory(page); await enterPreview(page);
  await expect(page.locator('.world--still')).toBeVisible(); await pause(page);
  const toggle = page.getByRole('button', { name: 'Movimiento más suave' });
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  await toggle.click(); await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await expect(page.locator('.world--still')).toHaveCount(0);
  await toggle.click(); await expect(page.locator('.world--still')).toBeVisible();
});

test('microphone denial never claims listening and offers truthful recovery', async ({ page }) => {
  let starts = 0;
  page.on('request', req => { if (req.url().includes('/api/avatar/realtime')) starts++; });
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: {
      getUserMedia: async () => { throw new DOMException('Denied by browser-test user', 'NotAllowedError'); },
    } });
  });
  await openStory(page, true);
  await page.getByRole('button', { name: 'Despertar el mundo' }).click();
  await expect(page.getByRole('alert')).toContainText('No se permitió usar el micrófono');
  await expect(page.getByRole('alert')).toContainText('usa el teclado');
  await expect(page.locator('.world')).toBeVisible();
  await expect(page.getByLabel('Te escucho', { exact: true })).toHaveCount(0);
  expect(starts).toBe(0);
});

test('320px mobile contains the world, pause menu, places, keyboard and pond', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 740 }); await openStory(page);
  const contained = async () => expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await contained(); await enterPreview(page); await contained();
  await pause(page); await contained();
  await expect(page.getByRole('button', { name: 'Movimiento más suave' })).toBeVisible();
  await page.getByRole('button', { name: 'Explorar otro lugar' }).click(); await contained();
  await page.getByRole('button', { name: 'Cerrar lugares' }).click();
  await page.keyboard.press('t'); await contained();
  await expect(page.getByLabel('Escribe a tu compañero')).toBeVisible();
  await page.getByRole('button', { name: 'Cerrar teclado' }).click();
  await page.getByRole('button', { name: 'Mirar el estanque' }).click(); await contained();
  await expect(page.getByRole('button', { name: 'Ver un ejemplo' })).toBeVisible();
});

test('the bank screen stays unloaded until requested and cannot interrupt the eyes introduction', async ({ page }) => {
  await mockRealtime(page, false);
  let bankLoads = 0;
  await page.route('**/savia/', async route => {
    bankLoads++;
    await new Promise(resolve => setTimeout(resolve, 600));
    await route.fulfill({ contentType: 'text/html', body: '<html><body><button>Sign in to Savia</button></body></html>' });
  });
  await page.route('**/api/avatar/config', route => route.fulfill({ json: {
    voiceAvailable: true, voiceProvider: 'openai-realtime', backendAvailable: true,
    saviaUrl: '/savia/', mode: 'connected', realtimeModel: 'mock-only',
  } }));
  await page.goto('/');
  await expect(page.locator('iframe')).toHaveCount(0);
  await page.getByRole('button', { name: 'Despertar el mundo' }).click();
  await expect(page.getByRole('status')).toHaveText('Te escucho');
  await page.waitForTimeout(800);
  expect(bankLoads).toBe(0);
  await expect(page.getByRole('status')).toHaveText('Te escucho');
  await page.evaluate(() => (window as Window & { __voiceTransport: { emit(event: object): void } }).__voiceTransport.emit({
    type: 'conversation.item.input_audio_transcription.completed', item_id: 'intro-utterance', transcript: 'I am overwhelmed and need a calm moment',
  }));
  await expect(page.locator('.world--moss')).toBeVisible();
  await expect(page.locator('iframe')).toHaveCount(0);
  await page.getByRole('button', { name: 'Mirar el estanque' }).click();
  await expect(page.frameLocator('iframe').getByRole('button', { name: 'Sign in to Savia' })).toBeVisible();
  expect(bankLoads).toBe(1);
});

test('switching identity before the first bank reply clears the parent voice and transcript', async ({ page }) => {
  await mockRealtime(page, false);
  await page.route('**/savia/api/auth/me', route => route.fulfill({ json: { authenticated: true } }));
  await page.route('**/savia/api/auth/login', route => route.fulfill({ json: { authenticated: true } }));
  await page.route('**/savia/', route => route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><body>
    <button id="launch">Hablemos</button><div id="chat"></div><script>
    window.submitted = 0;
    setTimeout(() => fetch('/savia/api/auth/me'), 100);
    document.querySelector('#launch').onclick = () => {
      document.querySelector('#chat').innerHTML = '<form><input aria-label="Mensaje para el asistente" maxlength="2000"><button aria-label="Enviar mensaje">Enviar</button></form>';
      document.querySelector('form').onsubmit = event => {
        event.preventDefault(); window.submitted++;
        const busy = document.createElement('div'); busy.className = 'chat-thinking'; document.body.append(busy);
        setTimeout(() => { busy.remove(); const reply = document.createElement('div'); reply.className = 'chat-message assistant'; reply.textContent = 'Private prior-identity synthetic result'; document.body.append(reply); }, 2200);
      };
    };
    </script></body></html>` }));
  await page.route('**/api/avatar/config', route => route.fulfill({ json: {
    voiceAvailable: true, voiceProvider: 'openai-realtime', backendAvailable: true,
    saviaUrl: '/savia/', mode: 'connected', realtimeModel: 'mock-only',
  } }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Despertar el mundo' }).click();
  await expect(page.getByRole('status')).toHaveText('Te escucho');
  await page.evaluate(() => (window as Window & { __voiceTransport: { emit(event: object): void } }).__voiceTransport.emit({
    type: 'conversation.item.input_audio_transcription.completed', item_id: 'private-utterance', transcript: 'Please explain my private prior-account inquiry',
  }));
  await page.evaluate(() => (window as Window & { __voiceTransport: { emit(event: object): void } }).__voiceTransport.emit({
    type: 'response.done', response: { output: [{ type: 'function_call', name: 'delegate_task', call_id: 'prior-read', arguments: JSON.stringify({ message: 'One synthetic owned inquiry' }) }] },
  }));
  await expect(page.frameLocator('iframe').getByRole('button', { name: 'Hablemos' })).toBeVisible();
  const frame = page.frames().find(frame => frame.url().endsWith('/savia/'))!;
  await expect.poll(() => frame.evaluate(() => (window as Window & { submitted: number }).submitted)).toBe(1);
  await frame.evaluate(() => fetch('/savia/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(response => response.status));
  await expect.poll(() => page.evaluate(() => (window as Window & { __voiceTransport: { tracksStopped: number } }).__voiceTransport.tracksStopped)).toBe(1);
  await page.getByRole('button', { name: 'Cerrar computadora' }).click();
  await pause(page); await page.getByRole('button', { name: 'Palabras del camino' }).click();
  await expect(page.locator('.history-user')).toHaveCount(0);
  await page.waitForTimeout(2300);
  await expect(page.locator('.history-messages')).not.toContainText('Private prior-identity synthetic result');
});

test('plural English and Spanish keyboard inquiries delegate to the actual visible workspace', async ({ page }) => {
  await page.route('**/savia/api/auth/me', route => route.fulfill({ json: { authenticated: true } }));
  await page.route('**/savia/', route => route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><head><meta charset="utf-8"></head><body>
    <form><input aria-label="Mensaje para el asistente" maxlength="2000"><button aria-label="Enviar mensaje" disabled>Enviar</button></form><script>
    const form = document.querySelector('form'), input = form.querySelector('input'), send = form.querySelector('button');
    window.submitted = [];
    input.oninput = () => { send.disabled = !input.value.trim(); };
    form.onsubmit = event => {
      event.preventDefault(); const value = input.value; window.submitted.push(value);
      const busy = document.createElement('div'); busy.className = 'chat-thinking'; busy.textContent = 'Consultando tus datos con FLUJO…'; document.body.append(busy);
      setTimeout(() => { busy.remove(); const reply = document.createElement('div'); reply.className = 'chat-message assistant'; reply.textContent = 'Observed synthetic public answer: ' + value; document.body.append(reply); }, 100);
    };
    </script></body></html>` }));
  await openStory(page, false, true);
  for (const message of ['Explain my transactions', 'Consulta mis movimientos recientes']) {
    await type(page, message);
    await expect(page.locator('.world--orbit')).toBeVisible();
    await expect(page.locator('.agent-cursor')).toBeVisible();
    await expect(page.frameLocator('iframe').locator('.chat-message.assistant').last()).toHaveText('Observed synthetic public answer: ' + message);
    await expect(page.locator('.agent-cursor')).toHaveCount(0);
    await page.getByRole('button', { name: 'Cerrar computadora' }).click();
    await pause(page); await page.getByRole('button', { name: 'Palabras del camino' }).click();
    await expect(page.locator('.history-assistant').last()).toHaveText('ORBITObserved synthetic public answer: ' + message);
    await page.getByRole('button', { name: 'Cerrar transcripción' }).click();
  }
  const owner = page.frames().find(frame => frame.url().endsWith('/savia/'))!;
  expect(await owner.evaluate(() => (window as Window & { submitted: string[] }).submitted)).toEqual(['Explain my transactions', 'Consulta mis movimientos recientes']);
});
