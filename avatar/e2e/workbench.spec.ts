import { test, expect, type Page } from '@playwright/test';

async function harness(page: Page) {
  await page.route('**/__workbench_harness', route => route.fulfill({ contentType: 'text/html', body:
    `<!doctype html><html><body><div id="root"></div>
      <script type="module">
        import RefreshRuntime from '/@react-refresh';
        RefreshRuntime.injectIntoGlobalHook(window);
        window.$RefreshReg$ = () => {};
        window.$RefreshSig$ = () => (type) => type;
        window.__vite_plugin_react_preamble_installed__ = true;
      </script>
      <script type="module" src="/@vite/client"></script>
      <script type="module" src="/e2e/fixtures/workbench-harness.tsx"></script>
    </body></html>`,
  }));
  await page.goto('/__workbench_harness');
}

test('embedded real Savia login renders through the restricted proxy without credentials', async ({ page, request, baseURL }) => {
  test.skip(!process.env.AVATAR_E2E_SAVIA && !process.env.SAVIA_UPSTREAM, 'Set AVATAR_E2E_SAVIA or SAVIA_UPSTREAM for the optional installed-Savia smoke.');
  await page.context().grantPermissions(['local-network-access'], { origin: new URL(baseURL!).origin });
  const raw = await request.get('/savia/');
  expect(raw.status(), 'Configure SAVIA_UPSTREAM to the existing local Savia service for this read-only smoke').toBe(200);
  expect(raw.headers()['x-frame-options']).toBe('SAMEORIGIN');
  expect(raw.headers()['content-security-policy']).toContain("frame-ancestors 'self'");
  // Exercise the served game document for genuine network access. The isolated
  // fulfilled harness is reserved for deterministic synthetic bank fixtures.
  await page.route('**/api/avatar/config', route => route.fulfill({ json: {
    voiceAvailable: false, voiceProvider: 'none', backendAvailable: true,
    saviaUrl: '/savia/', mode: 'connected', realtimeModel: 'fixture-no-voice',
  } }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Despertar el mundo' }).click();
  await expect(page.locator('.world')).toBeVisible();
  await page.getByRole('button', { name: 'Mirar el estanque' }).click();
  const frame = page.frameLocator('iframe[title="Savia secure banking workspace"]');
  await expect(frame.getByRole('button', { name: /Entrar|Ingresar|Iniciar|Continuar/ }).first()).toBeVisible();
  await expect(frame.locator('input[type="password"]')).toBeVisible();
  await expect(page.locator('.workbench-open')).toBeVisible();
});

async function fakeBank(page: Page, responseDelay = 650, historyDelay = 0, narrow = false) {
  await page.route('**/savia/', route => route.fulfill({ contentType: 'text/html', body: `<!doctype html>
    <html><head><meta charset="utf-8"><style>body{font:16px system-ui;padding:24px}input{width:70%;padding:12px}button{padding:12px}.chat-message{margin:12px}</style></head><body>
    <h1>Savia synthetic browser fixture</h1><button id="menu" aria-label="Abrir menú" style="display:${narrow ? 'block' : 'none'}">Menu</button>
    <nav id="navigation" style="${narrow ? 'position:fixed;left:0;top:100px;transform:translateX(-200%);width:260px' : ''}"><button id="launch">Hablemos</button></nav><div id="chat"></div>
    <script>
      window.evidence = { setters: 0, inputEvents: 0, submitted: [] };
      if (${narrow}) window.evidence.menuOpens = 0;
      document.querySelector('#menu').onclick = () => { window.evidence.menuOpens++; document.querySelector('#navigation').style.transform = 'none'; };
      const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
      Object.defineProperty(HTMLInputElement.prototype, 'value', {...descriptor, set(value) { window.evidence.setters++; descriptor.set.call(this, value); }});
      document.querySelector('#launch').onclick = () => {
        document.querySelector('#chat').innerHTML = '<form class="chat-input"><input aria-label="Mensaje para el asistente" maxlength="2000"><button aria-label="Enviar mensaje" disabled>Enviar</button></form>';
        const form = document.querySelector('form'), input = form.querySelector('input'), send = form.querySelector('button');
        let restoring = ${historyDelay} > 0;
        if (restoring) {
          const history = document.createElement('div'); history.className = 'chat-thinking'; history.textContent = 'Recuperando tu conversación…'; document.body.append(history);
          setTimeout(() => { history.remove(); restoring = false; send.disabled = !input.value.trim(); }, ${historyDelay});
        }
        input.addEventListener('input', () => { window.evidence.inputEvents++; send.disabled = restoring || !input.value.trim(); });
        form.onsubmit = event => { event.preventDefault(); const value = input.value; window.evidence.submitted.push(value); send.disabled = true;
          const busy = document.createElement('div'); busy.className = 'chat-thinking'; busy.textContent = 'Actual fixture request pending'; document.body.append(busy);
          setTimeout(() => { busy.remove(); const reply = document.createElement('div'); reply.className = 'chat-message assistant'; reply.textContent = 'Verified synthetic UI reply: ' + value; document.body.append(reply); send.disabled = false; }, ${responseDelay});
        };
      };
    </script></body></html>` }));
}

test('visible computer automation uses the native input setter and actual form reply', async ({ page }) => {
  await fakeBank(page);
  await harness(page);
  await expect(page.frameLocator('iframe').getByRole('button', { name: 'Hablemos' })).toBeVisible();
  const message = 'Explain this fictional transaction';
  await page.getByLabel('Fixture request').fill(message);
  await page.getByRole('button', { name: 'Execute fixture request' }).click();
  await expect(page.locator('.agent-cursor')).toBeVisible();
  await expect(page.frameLocator('iframe').getByLabel('Mensaje para el asistente')).toHaveValue(message);
  await expect(page.getByTestId('reply')).toHaveText('Verified synthetic UI reply: ' + message);
  const frame = page.frames().find(frame => frame.url().endsWith('/savia/'))!;
  const evidence = await frame.evaluate(() => (window as Window & { evidence?: unknown }).evidence);
  expect(evidence).toEqual({ setters: 1, inputEvents: 1, submitted: [message] });
  await expect(page.locator('.agent-cursor')).toHaveCount(0);
  await expect(page.locator('.workbench-footer')).toContainText('Savia respondió a tu consulta');
});

test('logout with a failed revocation response suppresses the prior pending reply', async ({ page }) => {
  await fakeBank(page, 1800);
  await page.route('**/savia/api/auth/logout', route => route.fulfill({ status: 503, json: { error: 'Synthetic revocation failure' } }));
  await harness(page);
  await expect(page.frameLocator('iframe').getByRole('button', { name: 'Hablemos' })).toBeVisible();
  await expect(page.getByTestId('account-changes')).toHaveText('0');
  await page.getByLabel('Fixture request').fill('Prior identity inquiry');
  await page.getByRole('button', { name: 'Execute fixture request' }).click();
  const frame = page.frames().find(frame => frame.url().endsWith('/savia/'))!;
  await expect.poll(() => frame.evaluate(() => (window as Window & { evidence: { submitted: string[] } }).evidence.submitted.length)).toBe(1);
  await frame.evaluate(() => fetch('/savia/api/auth/logout', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(response => response.status));
  await expect(page.getByTestId('account-changes')).toHaveText('1');
  await expect(page.getByTestId('reply')).toContainText('respuesta anterior no se mostró');
  await expect(page.locator('.agent-cursor')).toHaveCount(0);
  await expect(page.getByTestId('reply')).not.toContainText('Verified synthetic UI reply');
});

test('successful invite login during cursor travel prevents a prior-context submit', async ({ page }) => {
  await fakeBank(page);
  await page.route('**/savia/api/auth/invite', route => route.fulfill({ json: { authenticated: true } }));
  await harness(page);
  await expect(page.frameLocator('iframe').getByRole('button', { name: 'Hablemos' })).toBeVisible();
  await expect(page.getByTestId('account-changes')).toHaveText('0');
  await page.getByLabel('Fixture request').fill('Prior identity inquiry');
  await page.getByRole('button', { name: 'Execute fixture request' }).click();
  await expect(page.locator('.workbench-footer')).toContainText('Abriendo el asistente de Savia');
  const frame = page.frames().find(frame => frame.url().endsWith('/savia/'))!;
  await frame.evaluate(() => fetch('/savia/api/auth/invite', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(response => response.status));
  await expect(page.getByTestId('account-changes')).toHaveText('1');
  await expect(page.getByTestId('reply')).toContainText('consulta anterior no se envió');
  expect(await frame.evaluate(() => (window as Window & { evidence: { submitted: string[] } }).evidence.submitted)).toEqual([]);
});

test('initial Savia history recovery finishes before one visible query is admitted', async ({ page }) => {
  await fakeBank(page, 350, 1600); await harness(page);
  await expect(page.frameLocator('iframe').getByRole('button', { name: 'Hablemos' })).toBeVisible();
  await page.getByLabel('Fixture request').fill('One query after restoring history');
  await page.getByRole('button', { name: 'Execute fixture request' }).click();
  await expect(page.locator('.agent-cursor')).toBeVisible();
  await expect(page.getByTestId('reply')).toHaveText('Verified synthetic UI reply: One query after restoring history');
  const frame = page.frames().find(frame => frame.url().endsWith('/savia/'))!;
  expect(await frame.evaluate(() => (window as Window & { evidence: unknown }).evidence)).toEqual({ setters: 1, inputEvents: 1, submitted: ['One query after restoring history'] });
});

test('a genuine active Savia inquiry is refused without another submission', async ({ page }) => {
  await fakeBank(page); await harness(page);
  const frame = page.frameLocator('iframe');
  await frame.getByRole('button', { name: 'Hablemos' }).click();
  const owner = page.frames().find(frame => frame.url().endsWith('/savia/'))!;
  await owner.evaluate(() => {
    const pending = document.createElement('div'); pending.className = 'chat-thinking'; pending.textContent = 'Consultando tus datos con FLUJO…'; document.body.append(pending);
  });
  await page.getByLabel('Fixture request').fill('A request that must not duplicate active work');
  await page.getByRole('button', { name: 'Execute fixture request' }).click();
  await expect(page.getByTestId('reply')).toContainText('ya está procesando una consulta');
  expect(await owner.evaluate(() => (window as Window & { evidence: { submitted: string[] } }).evidence.submitted)).toEqual([]);
});

test('narrow Savia navigation is visibly opened before using its offscreen assistant control', async ({ page }) => {
  await fakeBank(page, 350, 0, true); await harness(page);
  await expect(page.frameLocator('iframe').getByRole('button', { name: 'Abrir menú' })).toBeVisible();
  const owner = page.frames().find(frame => frame.url().endsWith('/savia/'))!;
  expect(await owner.getByRole('button', { name: 'Hablemos' }).evaluate(el => el.getBoundingClientRect().right)).toBeLessThan(0);
  await page.getByLabel('Fixture request').fill('One inquiry through visible narrow navigation');
  await page.getByRole('button', { name: 'Execute fixture request' }).click();
  await expect(page.locator('.agent-cursor')).toBeVisible();
  await expect(page.getByTestId('reply')).toHaveText('Verified synthetic UI reply: One inquiry through visible narrow navigation');
  expect(await owner.evaluate(() => (window as Window & { evidence: unknown }).evidence)).toEqual({ setters: 1, inputEvents: 1, submitted: ['One inquiry through visible narrow navigation'], menuOpens: 1 });
});

test('closing the outer computer during send cursor travel prevents a hidden submission', async ({ page }) => {
  await fakeBank(page); await harness(page);
  await expect(page.frameLocator('iframe').getByRole('button', { name: 'Hablemos' })).toBeVisible();
  const owner = page.frames().find(frame => frame.url().endsWith('/savia/'))!;
  await page.getByLabel('Fixture request').fill('A read that must stay visible');
  await page.getByRole('button', { name: 'Execute fixture request' }).click();
  await expect(page.locator('.workbench-footer')).toContainText('Enviando tu consulta');
  await page.getByRole('button', { name: 'Cerrar computadora' }).click();
  await expect(page.getByTestId('reply')).toContainText('Abre la ventana de Savia');
  expect(await owner.evaluate(() => (window as Window & { evidence: { submitted: string[] } }).evidence.submitted)).toEqual([]);
  await expect(page.locator('.agent-cursor')).toHaveCount(0);
});

test('voice cancellation before submission stops cursor travel without submitting', async ({ page }) => {
  await fakeBank(page); await harness(page);
  await expect(page.frameLocator('iframe').getByRole('button', { name: 'Hablemos' })).toBeVisible();
  const owner = page.frames().find(frame => frame.url().endsWith('/savia/'))!;
  await page.getByLabel('Fixture request').fill('An unadmitted cancellable read');
  await page.getByRole('button', { name: 'Execute fixture request' }).click();
  await expect(page.locator('.workbench-footer')).toContainText('Escribiendo tu consulta');
  await page.getByRole('button', { name: 'Abort fixture read' }).click();
  await expect(page.getByTestId('reply')).toContainText('se detuvo antes de enviarse');
  expect(await owner.evaluate(() => (window as Window & { evidence: { submitted: string[] } }).evidence.submitted)).toEqual([]);
  await expect(page.locator('.agent-cursor')).toHaveCount(0);
});

test('an already admitted read still returns after voice cancellation and closing the computer', async ({ page }) => {
  await fakeBank(page, 900); await harness(page);
  await expect(page.frameLocator('iframe').getByRole('button', { name: 'Hablemos' })).toBeVisible();
  const owner = page.frames().find(frame => frame.url().endsWith('/savia/'))!;
  const message = 'An admitted read remains independent';
  await page.getByLabel('Fixture request').fill(message);
  await page.getByRole('button', { name: 'Execute fixture request' }).click();
  await expect.poll(() => owner.evaluate(() => (window as Window & { evidence: { submitted: string[] } }).evidence.submitted.length)).toBe(1);
  await page.getByRole('button', { name: 'Abort fixture read' }).click();
  await page.getByRole('button', { name: 'Cerrar computadora' }).click();
  await expect(page.getByTestId('reply')).toHaveText('Verified synthetic UI reply: ' + message);
  expect(await owner.evaluate(() => (window as Window & { evidence: { submitted: string[] } }).evidence.submitted)).toEqual([message]);
});
