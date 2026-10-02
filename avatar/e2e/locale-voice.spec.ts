import { test, expect, type Page } from '@playwright/test';
import { mockedGemini } from './fixtures/gemini-transport';

type NativeTransport = {
  tracksStopped: number; capturesDisconnected: number; socketsClosed: number;
  messages: Record<string, unknown>[];
  capture: { context: AudioContext; port: { onmessage: ((event: { data: Float32Array }) => void) | null } };
  socket: { onmessage: ((event: { data: string | Blob }) => void) | null };
  emit(event: object): void;
  samples(amplitude: number): void;
};
type LocaleVoiceEvidence = {
  streams: MediaStream[]; nativeStarted: number; nativeStopped: number;
  oldMessage?: (event: { data: string | Blob }) => void;
  oldCapture?: (event: { data: Float32Array }) => void;
  oldContext?: AudioContext;
};
type FixtureWindow = Window & { __geminiTransport: NativeTransport; __localeVoice: LocaleVoiceEvidence };

async function emit(page: Page, event: object) {
  await page.evaluate(event => (window as FixtureWindow).__geminiTransport.emit(event), event);
}
const pcm = { serverContent: { modelTurn: { parts: [{ inlineData: {
  mimeType: 'audio/pcm;rate=24000', data: Buffer.alloc(24000 * 2 * 2).toString('base64'),
} }] } } };

test.use({ locale: 'en-US' });

test('changing Spanish to Portuguese ends native capture, rejects old audio/captions and reconnects with Portuguese', async ({ page }) => {
  await mockedGemini(page);
  await page.addInitScript(() => {
    const record: LocaleVoiceEvidence = { streams: [], nativeStarted: 0, nativeStopped: 0 };
    Object.assign(window, { __localeVoice: record });
    const capture = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    // The shared fixture produces genuine silent tracks locally, never devices.
    navigator.mediaDevices.getUserMedia = async constraints => {
      const stream = await capture(constraints); record.streams.push(stream); return stream;
    };
    const OriginalContext = window.AudioContext;
    class ObservedContext extends OriginalContext {
      createBufferSource() {
        const source = super.createBufferSource(), start = source.start.bind(source), stop = source.stop.bind(source);
        source.start = (...args: Parameters<typeof source.start>) => {
          if (!source.loop && source.buffer?.sampleRate === 24000) record.nativeStarted++;
          start(...args);
        };
        source.stop = (...args: Parameters<typeof source.stop>) => {
          if (!source.loop && source.buffer?.sampleRate === 24000) record.nativeStopped++;
          stop(...args);
        };
        return source;
      }
    }
    Object.defineProperty(window, 'AudioContext', { value: ObservedContext });
  });
  const requests: { avatar?: string; locale?: string }[] = [], forbidden: string[] = [];
  await page.route(/\/(?:api|savia)(?:\/|$)/, async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/avatar/config') {
      await route.fulfill({ json: { voiceProvider: 'gemini-live', voiceAvailable: true,
        initialVoiceAvailable: false, backendAvailable: false, backgroundAsrAvailable: false,
        nativeReadBridgeAvailable: false, saviaUrl: '', mode: 'demo', realtimeModel: 'mock-native' } });
    } else if (path === '/api/avatar/gemini-token') {
      requests.push(route.request().postDataJSON());
      await route.fulfill({ json: { token: `auth_tokens/local-locale-${requests.length}`, model: 'gemini-e2e-locale',
        expiresAt: new Date(Date.now() + 60_000).toISOString(), newSessionExpiresAt: new Date(Date.now() + 30_000).toISOString(),
        setup: { model: 'models/gemini-e2e-locale' } } });
    } else { forbidden.push(path); await route.abort('blockedbyclient'); }
  });

  const config = page.waitForResponse('**/api/avatar/config'); await page.goto('/'); await config;
  await page.getByRole('button', { name: 'Despertar el mundo', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('Te escucho');
  expect(requests).toEqual([{ avatar: 'moss', locale: 'es' }]);
  await emit(page, { serverContent: { inputTranscription: { text: 'Quiero conversar con calma.', finished: true } } });
  await expect(page.locator('.world--moss')).toBeVisible();
  await page.getByRole('button', { name: 'Pausar la historia', exact: true }).click();
  await expect(page.getByLabel('Menú de pausa', { exact: true })).toBeVisible();
  // A new model turn reaches actual native PCM playback while the pause menu is
  // visible; the language selection must close this still-connected session.
  await emit(page, { serverContent: { interrupted: true } });
  await emit(page, { serverContent: { outputTranscription: { text: 'Una frase española antes del cambio.', finished: true } } });
  await emit(page, pcm);
  await expect.poll(() => page.evaluate(() => (window as FixtureWindow).__localeVoice.nativeStarted)).toBe(1);
  await expect(page.locator('.world')).toHaveAttribute('data-phase', 'speaking');
  await page.evaluate(() => {
    const { __geminiTransport: transport, __localeVoice: record } = window as FixtureWindow;
    record.oldMessage = transport.socket.onmessage ?? undefined;
    record.oldCapture = transport.capture.port.onmessage ?? undefined;
    record.oldContext = transport.capture.context;
  });

  await page.getByRole('button', { name: 'Português', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'pt-BR');
  await expect(page.getByRole('button', { name: 'Iniciar conversa por voz', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Encerrar conversa por voz', exact: true })).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => {
    const { __geminiTransport: transport, __localeVoice: record } = window as FixtureWindow;
    return { tracks: record.streams[0].getTracks().map(track => track.readyState), context: record.oldContext?.state,
      stopped: record.nativeStopped, capture: transport.capturesDisconnected, socket: transport.socketsClosed };
  })).toEqual({ tracks: ['ended'], context: 'closed', stopped: 1, capture: 1, socket: 1 });
  const beforeLate = await page.evaluate(() => (window as FixtureWindow).__geminiTransport.messages.length);
  await page.evaluate(async event => {
    const record = (window as FixtureWindow).__localeVoice;
    record.oldCapture?.({ data: new Float32Array(2048).fill(.04) });
    record.oldMessage?.({ data: new Blob([JSON.stringify(event)]) });
    record.oldMessage?.({ data: JSON.stringify({ serverContent: {
      outputTranscription: { text: 'Marcador viejo que jamás debe aparecer.', finished: true },
    } }) });
    await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  }, pcm);
  await expect(page.locator('.world')).toHaveAttribute('data-phase', 'idle');
  expect(await page.evaluate(() => (window as FixtureWindow).__localeVoice.nativeStarted)).toBe(1);
  expect(await page.evaluate(() => (window as FixtureWindow).__geminiTransport.messages.length)).toBe(beforeLate);
  await expect(page.locator('main')).not.toContainText('Marcador viejo');

  await page.getByRole('button', { name: 'Iniciar conversa por voz', exact: true }).click();
  await expect(page.getByLabel('Estou ouvindo', { exact: true })).toBeVisible();
  expect(requests).toEqual([{ avatar: 'moss', locale: 'es' }, { avatar: 'moss', locale: 'pt' }]);
  // An old closure stays invalid after a replacement session exists, too.
  await page.evaluate(async event => {
    (window as FixtureWindow).__localeVoice.oldMessage?.({ data: JSON.stringify(event) });
    await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  }, pcm);
  expect(await page.evaluate(() => (window as FixtureWindow).__localeVoice.nativeStarted)).toBe(1);
  await emit(page, { serverContent: { outputTranscription: { text: 'Agora podemos conversar em português.', finished: true } } });
  await emit(page, pcm);
  await expect.poll(() => page.evaluate(() => (window as FixtureWindow).__localeVoice.nativeStarted)).toBe(2);
  await page.getByRole('button', { name: 'Pausar a história', exact: true }).click();
  await page.getByRole('button', { name: 'Palavras do caminho', exact: true }).click();
  await expect(page.locator('.history-messages')).toContainText('Agora podemos conversar em português.');
  await expect(page.locator('.history-messages')).not.toContainText('Marcador viejo');
  await page.getByRole('button', { name: 'Fechar transcrição', exact: true }).click();
  await page.getByRole('button', { name: 'Pausar a história', exact: true }).click();
  await page.getByRole('button', { name: 'Encerrar conversa por voz', exact: true }).click();
  await expect.poll(() => page.evaluate(() => {
    const { __geminiTransport: transport, __localeVoice: record } = window as FixtureWindow;
    return { tracks: record.streams.flatMap(stream => stream.getTracks().map(track => track.readyState)),
      capture: transport.capturesDisconnected, socket: transport.socketsClosed };
  })).toEqual({ tracks: ['ended', 'ended'], capture: 2, socket: 2 });
  expect(forbidden, 'No chained voice, bank or alternate provider request was attempted').toEqual([]);
  await expect(page.locator('iframe')).toHaveCount(0);
});
