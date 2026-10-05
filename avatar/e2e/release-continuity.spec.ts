import { test, expect, type Frame, type Page } from '@playwright/test';
import { mockedNative } from './fixtures/native-router-transport';

const inquiry = 'Consulta mis pagos recientes: el cargo de Café La Esquina por $42.17 del 2 de octubre.';
const foreground = '¿Me explicas qué significa que no tenga una disputa abierta?';
const chargeReply = 'El cargo seleccionado de **Café La Esquina** por $42.17 del 2 de octubre no tiene una disputa abierta.\n\nNo se realizó ninguna acción.';
const transactionReference = 'txn_a1b2c3d4e5f60718293a4b5c';
const taskId = 'synthetic-charge-read-01';

async function setup(page: Page, options: { connect?: boolean } = {}) {
  const evidence = { posts: [] as Record<string, unknown>[], receipts: [] as Record<string, unknown>[], unexpected: [] as string[] };
  let releaseRead!: () => void;
  const readReady = new Promise<void>(resolve => { releaseRead = resolve; });
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
    const body = route.request().postDataJSON() as Record<string, unknown>;
    evidence.receipts.push(body);
    if (body.reply !== chargeReply || body.locale !== 'es' || Object.keys(body).length !== 2)
      return route.fulfill({ status: 409, json: { error: 'Synthetic selected-charge result mismatch' } });
    return route.fulfill({ json: { taskId } });
  });
  await page.route('**/savia/api/auth/me', route => route.fulfill({ json: { authenticated: true } }));
  await page.route('**/savia/api/chat', async route => {
    if (route.request().method() !== 'POST') return route.fulfill({ status: 405 });
    const body = route.request().postDataJSON() as Record<string, unknown>;
    evidence.posts.push(body);
    if (body.message !== inquiry || body.transaction_reference !== transactionReference)
      return route.fulfill({ status: 409, json: { error: 'Synthetic selected-charge context mismatch' } });
    await readReady;
    return route.fulfill({ json: { reply: chargeReply } });
  });
  await page.route('**/savia/', route => route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><head><meta charset="utf-8"><style>body{padding:24px;font:16px system-ui}button,input{padding:12px}input{width:65%}.selected{background:#dcefd8}</style></head><body>
    <h1>Savia sintética · movimientos</h1>
    <button id="charge" aria-pressed="true" aria-label="Cargo seleccionado" data-reference="${transactionReference}" class="selected">Café La Esquina · 2 oct · $42.17</button>
    <button id="launch">Asistente<span>FLUJO</span></button><div id="chat"></div><script>
    window.evidence = { selectedCharge: document.querySelector('#charge').textContent, selectedReference: document.querySelector('#charge').dataset.reference, submitted: [], setters: 0, inputEvents: 0 };
    const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
    Object.defineProperty(HTMLInputElement.prototype, 'value', {...descriptor, set(value) { window.evidence.setters++; descriptor.set.call(this, value); }});
    document.querySelector('#launch').onclick = () => {
      document.querySelector('#chat').innerHTML = '<form><input aria-label="Mensaje para el asistente" maxlength="2000"><button aria-label="Enviar mensaje" disabled>Enviar</button></form>';
      const form = document.querySelector('form'), input = form.querySelector('input'), send = form.querySelector('button');
      input.addEventListener('input', () => { window.evidence.inputEvents++; send.disabled = !input.value.trim(); });
      form.onsubmit = async event => { event.preventDefault(); const message = input.value; const transaction_reference = document.querySelector('#charge[aria-pressed="true"]')?.dataset.reference; window.evidence.submitted.push({message, transaction_reference}); send.disabled = true;
        const busy = document.createElement('div'); busy.className = 'chat-thinking'; busy.textContent = 'Consultando datos sintéticos'; document.body.append(busy);
        const response = await fetch('/savia/api/chat', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message, transaction_reference})});
        const body = await response.json(); busy.remove(); const answer = document.createElement('div'); answer.className = 'chat-message assistant'; answer.dataset.saviaReply = body.reply; const speaker = document.createElement('span'); speaker.textContent = 'Savia'; answer.append(speaker); const rendered = document.createElement('p'); rendered.textContent = body.reply.replaceAll('**', '').replaceAll(String.fromCharCode(10), ' '); answer.append(rendered); document.body.append(answer); send.disabled = false;
      };
    };
    </script></body></html>` }));
  const configured = page.waitForResponse('**/api/avatar/config');
  await page.goto('/'); await configured;
  await expect(page.locator('.audio-provider-notice')).toContainText('audio se envía a OpenRouter / OpenAI');
  if (options.connect !== false) {
    await page.getByRole('button', { name: 'Despertar el mundo' }).click();
    await expect(page.getByRole('status')).toHaveText('Te escucho');
  }
  return { evidence, releaseRead };
}

async function bankFrame(page: Page): Promise<Frame> {
  await expect(page.locator('.workbench-open')).toBeVisible();
  await expect(page.frameLocator('iframe').getByRole('button', { name: 'AsistenteFLUJO' })).toBeVisible();
  return page.frames().find(frame => new URL(frame.url()).pathname === '/savia/')!;
}
async function submitText(page: Page, message: string) {
  if (await page.locator('.workbench-open').count()) {
    // Return from the focused Savia frame through the game's own keyboard
    // affordance while preserving the connected voice session.
    await page.getByRole('button', { name: 'Pausar la historia' }).click();
    await page.getByRole('button', { name: 'Usar el teclado' }).click();
  } else {
    await page.keyboard.press('t');
  }
  await page.getByLabel('Escribe a tu compañero').fill(message);
  await page.getByRole('button', { name: 'Enviar mensaje', exact: true }).click();
}
const requests = (page: Page, suffix: string) => page.evaluate(suffix => window.__nativeTransport.requests.filter(item => item.path.endsWith(suffix)), suffix);

test('a held selected-charge read does not block foreground voice and returns once to the same conversation', async ({ page }) => {
  const { evidence, releaseRead } = await setup(page);
  await submitText(page, inquiry);
  const frame = await bankFrame(page);
  await expect(page.locator('.quiet-work')).toBeVisible();
  await expect.poll(() => evidence.posts).toEqual([{ message: inquiry, transaction_reference: transactionReference }]);
  expect(await frame.evaluate(() => (window as Window & { evidence: unknown }).evidence)).toEqual({
    selectedCharge: 'Café La Esquina · 2 oct · $42.17', selectedReference: transactionReference,
    submitted: [{ message: inquiry, transaction_reference: transactionReference }], setters: 1, inputEvents: 1,
  });

  // The read is still held by the synthetic Savia response while the connected
  // native voice session handles an ordinary follow-up turn.
  await submitText(page, foreground);
  await expect.poll(async () => (await requests(page, 'native-turn')).length).toBe(2);
  await expect.poll(async () => (await requests(page, 'native-played')).filter(item => item.body.complete === true && item.body.turnId === 'fixture-native-2').length).toBe(1);
  expect(evidence.posts).toEqual([{ message: inquiry, transaction_reference: transactionReference }]);
  expect(evidence.receipts).toEqual([]);
  expect(await requests(page, 'native-reset')).toHaveLength(1);

  // Interrupt a foreground reply while the same read remains pending, then
  // continue in the same native session and let the queued result return.
  const sourcesBeforeInterrupt = await page.evaluate(() => {
    window.__nativeTransport.autoComplete = false; window.__nativeTransport.duration = 3;
    return window.__nativeTransport.sourcesStarted;
  });
  await submitText(page, 'Espera, déjame terminar la pregunta.');
  await expect.poll(async () => (await requests(page, 'native-turn')).length).toBe(3);
  await expect.poll(() => page.evaluate(() => window.__nativeTransport.sourcesStarted)).toBeGreaterThan(sourcesBeforeInterrupt);
  await page.getByRole('button', { name: 'Pausar la historia' }).click();
  await expect.poll(() => page.evaluate(() => window.__nativeTransport.sourcesStopped)).toBeGreaterThan(0);
  await page.getByRole('button', { name: 'Volver al mundo' }).click();
  await page.evaluate(() => { window.__nativeTransport.autoComplete = true; window.__nativeTransport.duration = .25; });
  await submitText(page, 'Ya estoy listo, sigue con la explicación.');
  await expect.poll(async () => (await requests(page, 'native-turn')).length).toBe(4);
  await expect.poll(async () => (await requests(page, 'native-played')).filter(item => item.body.complete === true && item.body.turnId === 'fixture-native-4').length).toBe(1);
  expect(evidence.posts).toEqual([{ message: inquiry, transaction_reference: transactionReference }]);
  expect(evidence.receipts).toEqual([]);

  releaseRead();
  await expect(frame.locator('.chat-message.assistant')).toHaveAttribute('data-savia-reply', chargeReply);
  await expect(frame.locator('.chat-message.assistant')).toContainText('Savia');
  await expect.poll(() => evidence.receipts).toEqual([{ reply: chargeReply, locale: 'es' }]);
  await expect.poll(async () => (await requests(page, 'native-result')).length).toBe(1);
  await expect.poll(async () => (await requests(page, 'native-played')).filter(item => item.body.complete === true && item.body.turnId === 'fixture-native-5').length).toBe(1);
  expect(await requests(page, 'native-reset')).toHaveLength(1);
  expect(evidence.posts).toEqual([{ message: inquiry, transaction_reference: transactionReference }]);
  expect(evidence.unexpected).toEqual([]);

  await page.getByRole('button', { name: 'Pausar la historia' }).click();
  await page.getByRole('button', { name: 'Palabras del camino' }).click();
  await expect(page.locator('.history-messages')).toContainText(foreground);
  await expect(page.locator('.history-messages')).toContainText('Respuesta nativa 1.');
  await expect(page.locator('.history-messages')).toContainText('Respuesta nativa 4.');
  await expect(page.locator('.history-messages')).not.toContainText('Respuesta nativa 3.');
});

test('a typed turn submitted during native reset waits for readiness and runs once', async ({ page }) => {
  await setup(page, { connect: false });
  await page.evaluate(() => {
    const windowWithGate = window as Window & { __releaseNativeReset?: () => void; __nativeResetWaiting?: boolean };
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const url = input instanceof Request ? input.url : String(input);
      if (new URL(url, location.href).pathname === '/api/avatar/native-reset') {
        windowWithGate.__nativeResetWaiting = true;
        await new Promise<void>(resolve => { windowWithGate.__releaseNativeReset = resolve; });
      }
      return originalFetch(input, init);
    };
  });
  await page.getByRole('button', { name: 'Despertar el mundo' }).click();
  await expect.poll(() => page.evaluate(() => Boolean((window as Window & { __nativeResetWaiting?: boolean }).__nativeResetWaiting))).toBe(true);

  const typed = 'Hola, ¿qué información debo guardar mientras revisas?';
  await page.keyboard.press('t');
  await page.getByLabel('Escribe a tu compañero').fill(typed);
  await page.getByRole('button', { name: 'Enviar mensaje', exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.__nativeTransport.requests.filter(item => item.path.endsWith('native-turn')).length)).toBe(0);
  await expect(page.locator('.movie-subtitle')).toHaveCount(0);

  await page.evaluate(() => (window as Window & { __releaseNativeReset?: () => void }).__releaseNativeReset?.());
  await expect(page.locator('.game-signal')).toHaveAttribute('aria-label', 'Te escucho');
  await expect.poll(() => page.evaluate(() => window.__nativeTransport.requests.filter(item => item.path.endsWith('native-turn')).length)).toBe(1);
  const turns = await page.evaluate(() => window.__nativeTransport.requests.filter(item => item.path.endsWith('native-turn')));
  expect(turns[0].body.message).toBe(typed);
  expect(turns[0].body.audio).toBeUndefined();
  await expect.poll(() => page.evaluate(() => window.__nativeTransport.requests.filter(item => item.path.endsWith('native-played') && item.body.complete === true).length)).toBe(1);
  expect(await page.evaluate(() => window.__nativeTransport.requests.filter(item => item.path.endsWith('native-result')).length)).toBe(0);
  expect(await page.evaluate(() => window.__nativeTransport.tracksStopped)).toBe(0);
});

test('an owned inquiry pointer queues its verified update after foreground speech and suppresses repeated status copy', async ({ page }) => {
  await setup(page);
  const caseId = 'i_' + 'c'.repeat(32), reply = 'El equipo tiene dos perspectivas útiles. ¿Te ayudan a decidir?';
  const queries: string[] = [], receipts: Record<string, unknown>[] = [];
  let version = 7;
  await page.route('**/savia/api/assistant/voice-update?**', route => {
    const url = new URL(route.request().url()); queries.push(url.search);
    return route.fulfill({ json: { reply, mode: 'assistant', status: 'completed', event_id: version,
      inquiry_state: url.searchParams.get('case_id') === caseId ? 'team_completed' : 'informational_resolved', bank_authority: false } });
  });
  await page.route('**/api/avatar/native-result-receipt', route => {
    const body = route.request().postDataJSON() as Record<string, unknown>; receipts.push(body);
    if (body.reply !== reply || body.locale !== 'es' || Object.keys(body).length !== 2)
      return route.fulfill({ status: 409, json: { error: 'Unverified update' } });
    return route.fulfill({ json: { taskId } });
  });
  await submitText(page, 'Hola, quiero entender el siguiente paso.');
  await expect.poll(async () => (await requests(page, 'native-played')).filter(item => item.body.complete === true).length).toBe(1);
  await page.getByRole('button', { name: 'Mirar el estanque' }).click();
  const frame = await bankFrame(page);
  const pointer = { type: 'savia:inquiry-update', case_id: caseId, event_id: version };
  await page.evaluate(pointer => window.postMessage(pointer, location.origin), pointer);
  expect(queries).toEqual([]); // A parent-window spoof is not the mounted frame.

  await page.evaluate(() => { window.__nativeTransport.autoComplete = false; });
  await submitText(page, 'Mientras espero, sigo pensando qué información guardar.');
  await expect.poll(async () => (await requests(page, 'native-turn')).length).toBe(2);
  await frame.evaluate(pointer => window.parent.postMessage(pointer, location.origin), pointer);
  await expect.poll(() => receipts).toEqual([{ reply, locale: 'es' }]);
  expect(await requests(page, 'native-result')).toHaveLength(0);
  expect(queries).toEqual([`?case_id=${caseId}&after_event_id=0&language=es`]);

  await frame.evaluate(pointer => {
    window.parent.postMessage(pointer, location.origin);
    window.parent.postMessage({ ...pointer, reply: 'Invented human resolution' }, location.origin);
  }, pointer);
  version = 8;
  await frame.evaluate(pointer => window.parent.postMessage(pointer, location.origin), { ...pointer, event_id: version });
  await expect.poll(() => queries.length).toBe(2);
  expect(queries[1]).toBe(`?case_id=${caseId}&after_event_id=7&language=es`);
  expect(receipts).toEqual([{ reply, locale: 'es' }]); // Same copy, newer worker event.

  await page.evaluate(() => { window.__nativeTransport.autoComplete = true; window.__nativeTransport.finish('fixture-native-2'); });
  await expect.poll(async () => (await requests(page, 'native-result')).length).toBe(1);
  await expect.poll(async () => (await requests(page, 'native-played')).filter(item => item.body.turnId === 'fixture-native-3' && item.body.complete === true).length).toBe(1);
  expect(await requests(page, 'native-reset')).toHaveLength(1);
  expect(await requests(page, 'native-result')).toHaveLength(1);
  expect(receipts).toHaveLength(1);
  await frame.evaluate(pointer => window.parent.postMessage(pointer, location.origin), {
    type: 'savia:inquiry-update', case_id: 'i_' + 'd'.repeat(32), event_id: version,
  });
  await expect.poll(() => queries.length).toBe(3);
  expect(receipts).toHaveLength(1); // An old closed inquiry is not a new closure announcement.
  expect(await requests(page, 'native-result')).toHaveLength(1);
});
