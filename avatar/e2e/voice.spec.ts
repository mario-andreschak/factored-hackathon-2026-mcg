import { test, expect, type Page } from '@playwright/test';
import { mockRealtime as mockedVoice } from './fixtures/realtime-transport';

async function emit(page: Page, event: object) {
  await page.evaluate(event => (window as Window & { __voiceTransport: { emit(event: object): void } }).__voiceTransport.emit(event), event);
}
async function evidence(page: Page) {
  return page.evaluate(() => {
    const value = (window as Window & { __voiceTransport: {
      peersClosed: number; channelsClosed: number; tracksStopped: number; contextsClosed: number;
      messages: { type: string; item?: { call_id?: string; output?: string } }[];
    } }).__voiceTransport;
    return { peersClosed: value.peersClosed, channelsClosed: value.channelsClosed,
      tracksStopped: value.tracksStopped, contextsClosed: value.contextsClosed, messages: value.messages };
  });
}

test('real voice hook preserves async delegated work across speech interruption and cleans every resource', async ({ page }) => {
  await mockedVoice(page);
  await page.getByRole('button', { name: 'Connect test voice' }).click();
  await expect(page.getByTestId('connected')).toHaveText('true');
  await expect(page.getByTestId('phase')).toHaveText('listening');
  await emit(page, { type: 'response.created' });
  await emit(page, { type: 'output_audio_buffer.started' });
  await expect(page.getByTestId('phase')).toHaveText('speaking');
  await page.getByRole('button', { name: 'Interrupt test voice' }).click();
  await expect(page.getByTestId('phase')).toHaveText('listening');
  expect((await evidence(page)).messages.map(item => item.type)).toContain('response.cancel');
  expect((await evidence(page)).messages.map(item => item.type)).toContain('output_audio_buffer.clear');
  await emit(page, { type: 'response.done', response: { output: [{ type: 'function_call',
    name: 'delegate_task', call_id: 'read-1', arguments: JSON.stringify({ message: 'Synthetic read only' }) }] } });
  await expect.poll(() => page.evaluate(() => window.__voiceHarness.tasks)).toEqual(['Synthetic read only']);
  await emit(page, { type: 'input_audio_buffer.speech_started' });
  await page.evaluate(() => window.__voiceHarness.resolveTask?.({ reply: 'Verified synthetic result', mode: 'flujo', status: 'completed' }));
  await expect.poll(async () => (await evidence(page)).messages.filter(item => item.type === 'conversation.item.create').length).toBe(1);
  // A completed bank read is retained, while the model waits until speech stops.
  expect((await evidence(page)).messages.filter(item => item.type === 'response.create')).toHaveLength(0);
  await emit(page, { type: 'input_audio_buffer.speech_stopped' });
  await emit(page, { type: 'response.done', response: { output: [] } });
  await expect.poll(async () => (await evidence(page)).messages.filter(item => item.type === 'response.create').length).toBe(1);
  await page.getByRole('button', { name: 'Mute test voice' }).click();
  await expect(page.getByTestId('muted')).toHaveText('true');
  await page.getByRole('button', { name: 'End test voice' }).click();
  await expect(page.getByTestId('connected')).toHaveText('false');
  await expect(page.getByTestId('phase')).toHaveText('idle');
  await expect.poll(async () => (await evidence(page)).tracksStopped).toBe(1);
  expect(await evidence(page)).toMatchObject({ peersClosed: 1, channelsClosed: 1, contextsClosed: 1 });
});

test('duplicate tool events run once and a late result cannot speak into an ended session', async ({ page }) => {
  await mockedVoice(page);
  await page.getByRole('button', { name: 'Connect test voice' }).click();
  await expect(page.getByTestId('connected')).toHaveText('true');
  const done = { type: 'response.done', response: { output: [{ type: 'function_call',
    name: 'delegate_task', call_id: 'same-read', arguments: JSON.stringify({ message: 'One synthetic read' }) }] } };
  await emit(page, done); await emit(page, done);
  await expect.poll(() => page.evaluate(() => window.__voiceHarness.tasks.length)).toBe(1);
  await page.getByRole('button', { name: 'End test voice' }).click();
  await page.evaluate(() => window.__voiceHarness.resolveTask?.({ reply: 'Late synthetic result' }));
  await page.waitForTimeout(100);
  expect((await evidence(page)).messages).toHaveLength(0);
  await page.getByRole('button', { name: 'Connect test voice' }).click();
  await expect(page.getByTestId('connected')).toHaveText('true');
  await emit(page, done);
  await expect.poll(() => page.evaluate(() => window.__voiceHarness.tasks.length)).toBe(2);
  await page.getByRole('button', { name: 'End test voice' }).click();
  expect(await evidence(page)).toMatchObject({ peersClosed: 2, channelsClosed: 2, tracksStopped: 2, contextsClosed: 2 });
});
