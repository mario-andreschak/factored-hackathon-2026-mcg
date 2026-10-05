import { test, expect, type Page } from '@playwright/test';

const esPlaces = [
  'El santuario de aguas tranquilas', 'El bosque de los faroles', 'Bajo la lluvia',
  'Un horizonte distinto', 'Una piedra a la vez', 'El reflejo de la luna',
  'Lo que permanece', 'La pradera abierta', 'Sobre las nubes', 'El camino a casa',
];
const ptPlaces = [
  'O santuário das águas tranquilas', 'O bosque dos lampiões', 'Sob a chuva',
  'Um horizonte diferente', 'Uma pedra de cada vez', 'O reflexo da lua',
  'O que permanece', 'O campo aberto', 'Acima das nuvens', 'O caminho de casa',
];

/** Exercise the actual game; deny every service outside the local demo config. */
async function demoOnly(page: Page) {
  const denied: string[] = [];
  await page.route(/\/(?:api|savia)(?:\/|$)/, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/avatar/config') {
      await route.fulfill({ json: { voiceAvailable: false, initialVoiceAvailable: false,
        backendAvailable: false, backgroundAsrAvailable: false, nativeReadBridgeAvailable: false,
        saviaUrl: '', mode: 'demo', realtimeModel: '', voiceProvider: 'none' } });
    } else { denied.push(path); await route.abort('blockedbyclient'); }
  });
  await page.routeWebSocket('**', socket => {
    const target = new URL(socket.url()), origin = new URL(page.url());
    // Vite's development-only HMR connection is local tooling, outside voice.
    if (target.host === origin.host && target.pathname === '/' && target.searchParams.has('token')) {
      socket.connectToServer(); return;
    }
    denied.push('websocket'); socket.close();
  });
  await page.addInitScript(() => {
    Object.assign(window, { __localeSafety: { microphone: 0, speech: 0 } });
    const safety = (window as Window & { __localeSafety: { microphone: number; speech: number } }).__localeSafety;
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: {
      getUserMedia: async () => { safety.microphone++; throw new DOMException('Local demo test', 'NotAllowedError'); },
    } });
    Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: {
      cancel() {}, speak() { safety.speech++; },
    } });
  });
  return async () => {
    expect(denied, 'No provider, socket or banking request was attempted').toEqual([]);
    expect(await page.evaluate(() => (window as Window & {
      __localeSafety: { microphone: number; speech: number };
    }).__localeSafety)).toEqual({ microphone: 0, speech: 0 });
  };
}

async function openGame(page: Page, wake: string) {
  const loaded = page.waitForResponse('**/api/avatar/config');
  await page.goto('/'); await loaded;
  await expect(page.getByRole('button', { name: wake, exact: true })).toBeVisible();
}
async function enter(page: Page, wake: string) {
  await page.getByRole('button', { name: wake, exact: true }).click();
  await expect(page.locator('.world-painting--ready')).toBeVisible();
}
async function pause(page: Page, label: string, menu: string) {
  await page.getByRole('button', { name: label, exact: true }).click();
  await expect(page.getByLabel(menu, { exact: true })).toBeVisible();
}
async function checkGallery(page: Page, label: string, prefix: string, places: string[]) {
  await page.getByRole('button', { name: label, exact: true }).click();
  const cards = page.locator('.game-chapter-grid button');
  await expect(cards).toHaveCount(10);
  for (let i = 0; i < places.length; i++) {
    await expect(cards.nth(i)).toHaveAccessibleName(`${prefix}${places[i]}`);
    await expect(cards.nth(i).locator('img')).toHaveAttribute('alt', places[i]);
  }
}

test.describe('English browser still starts in Latin American Spanish', () => {
  test.use({ locale: 'en-US' });

  test('Spanish default labels, ten places and silent preview', async ({ page }) => {
    const safe = await demoOnly(page);
    await openGame(page, 'Despertar el mundo');
    await expect(page.locator('html')).toHaveAttribute('lang', 'es-CO');
    expect(await page.evaluate(() => navigator.language)).toBe('en-US');
    expect(await page.evaluate(() => localStorage.getItem('elsewhere.locale'))).toBeNull();
    await enter(page, 'Despertar el mundo');
    await expect(page.getByLabel('Vista previa del mundo', { exact: true })).toBeVisible();
    await pause(page, 'Pausar la historia', 'Menú de pausa');
    await expect(page.getByRole('button', { name: 'Español', exact: true })).toHaveAttribute('aria-pressed', 'true');
    for (const name of ['Moss', 'Orbit', 'Spark']) await expect(page.getByRole('button', { name: `Elegir a ${name}`, exact: true })).toBeVisible();
    await checkGallery(page, 'Explorar otro lugar', 'Viajar a ', esPlaces);
    await page.getByRole('button', { name: 'Viajar a El camino a casa', exact: true }).click();
    await expect(page.locator('.world-painting--ready').last()).toHaveAttribute('src', '/scenes/10-homecoming-sunset.webp');
    await safe();
  });

  test('manual Portuguese choice changes the live menu, gallery and fictional computer, then survives reload', async ({ page }) => {
    const safe = await demoOnly(page);
    await openGame(page, 'Despertar el mundo'); await enter(page, 'Despertar el mundo');
    await pause(page, 'Pausar la historia', 'Menú de pausa');
    await page.getByRole('button', { name: 'Português', exact: true }).click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'pt-BR');
    await expect(page.getByLabel('Menu de pausa', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Português', exact: true })).toHaveAttribute('aria-pressed', 'true');
    expect(await page.evaluate(() => localStorage.getItem('elsewhere.locale'))).toBe('pt');
    await checkGallery(page, 'Explorar outro lugar', 'Viajar para ', ptPlaces);
    await page.getByRole('button', { name: 'Viajar para O santuário das águas tranquilas', exact: true }).click();
    await page.getByRole('button', { name: 'Olhar o lago', exact: true }).click();
    const pond = page.getByLabel('Computador do mundo', { exact: true });
    await expect(pond).toBeVisible(); await expect(pond).toHaveAttribute('lang', 'pt-BR');
    await expect(pond).toContainText('Uma visão mais clara.');
    await expect(pond).toContainText('EXEMPLO FICTÍCIO');
    await expect(pond).toContainText('Assinatura na nuvem');
    await expect(pond.locator('.demo-row')).toHaveCount(3);
    await pond.getByRole('button', { name: 'Ver um exemplo', exact: true }).click();
    await expect(pond.locator('.workbench-footer')).toContainText('Exemplo revisado · nenhuma consulta foi enviada');
    await expect(pond.locator('.demo-detail')).toContainText('Esta transação é fictícia');
    await expect(page.locator('iframe')).toHaveCount(0);
    await safe();
    const loaded = page.waitForResponse('**/api/avatar/config'); await page.reload(); await loaded;
    await expect(page.getByRole('button', { name: 'Despertar o mundo', exact: true })).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('lang', 'pt-BR');
    expect(await page.evaluate(() => navigator.language)).toBe('en-US');
    await safe();
  });
});

test.describe('Portuguese browser preference and deliberate Spanish override', () => {
  test.use({ locale: 'pt-BR' });

  test('Portuguese preferred browser receives Portuguese UI and typed demo dialogue', async ({ page }) => {
    const safe = await demoOnly(page);
    await openGame(page, 'Despertar o mundo');
    await expect(page.locator('html')).toHaveAttribute('lang', 'pt-BR');
    expect(await page.evaluate(() => navigator.language)).toBe('pt-BR');
    expect(await page.evaluate(() => localStorage.getItem('elsewhere.locale'))).toBeNull();
    await page.keyboard.press('t');
    await page.getByLabel('Escreva para seu companheiro', { exact: true }).fill('Estou ansioso e sobrecarregado');
    await page.getByRole('button', { name: 'Enviar mensagem', exact: true }).click();
    await expect(page.locator('.world--moss')).toBeVisible();
    await pause(page, 'Pausar a história', 'Menu de pausa');
    await page.getByRole('button', { name: 'Palavras do caminho', exact: true }).click();
    await expect(page.getByLabel('Transcrição da conversa', { exact: true })).toBeVisible();
    await expect(page.locator('.history-user')).toContainText('Estou ansioso e sobrecarregado');
    await expect(page.locator('.history-assistant')).toContainText('Você não precisa resolver tudo de uma vez.');
    await safe();
  });

  test('a saved Spanish selection takes precedence over Portuguese navigator after reload', async ({ page }) => {
    const safe = await demoOnly(page);
    await openGame(page, 'Despertar o mundo'); await enter(page, 'Despertar o mundo');
    await pause(page, 'Pausar a história', 'Menu de pausa');
    await page.getByRole('button', { name: 'Español', exact: true }).click();
    await expect(page.getByLabel('Menú de pausa', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Español', exact: true })).toHaveAttribute('aria-pressed', 'true');
    expect(await page.evaluate(() => localStorage.getItem('elsewhere.locale'))).toBe('es');
    await safe();
    const loaded = page.waitForResponse('**/api/avatar/config'); await page.reload(); await loaded;
    await expect(page.getByRole('button', { name: 'Despertar el mundo', exact: true })).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('lang', 'es-CO');
    expect(await page.evaluate(() => navigator.language)).toBe('pt-BR');
    await safe();
  });
});
