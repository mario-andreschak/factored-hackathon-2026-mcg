import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

function wav(pcm) {
  const header = Buffer.alloc(44);
  header.write('RIFF'); header.writeUInt32LE(pcm.length + 36, 4); header.write('WAVEfmt ', 8);
  header.writeUInt32LE(16, 16); header.writeUInt16LE(1, 20); header.writeUInt16LE(1, 22);
  header.writeUInt32LE(24000, 24); header.writeUInt32LE(48000, 28);
  header.writeUInt16LE(2, 32); header.writeUInt16LE(16, 34);
  header.write('data', 36); header.writeUInt32LE(pcm.length, 40);
  return Buffer.concat([header, pcm]);
}

/** Attach to an actual fictional browser capture before its voice requests.
 * This observes responses only; it initiates no model, bank or microphone work.
 * No cookies, headers, request text, or recorded customer input are stored.
 */
export async function captureReleaseAudio(page, outputDir) {
  await mkdir(outputDir, { recursive: true });
  const pending = [], turns = []; let sequence = 0;
  const observe = response => {
    const route = new URL(response.url()).pathname;
    if (!['/api/avatar/native-turn', '/api/avatar/native-result'].includes(route)) return;
    const index = ++sequence;
    pending.push((async () => {
      const record = { index, route, httpStatus: response.status(), completed: false,
        sampleRate: 24000, sampleRateQualification: 'assumed', physicalMicrophoneQualified: false };
      turns.push(record);
      try {
        if (!response.ok()) return;
        const bytes = await response.body(); if (bytes.length > 4 * 1024 * 1024) return;
        const events = bytes.toString('utf8').trim().split('\n').filter(Boolean).map(line => JSON.parse(line));
        const complete = events.at(-1);
        if (complete?.type !== 'complete' || events.some(event => event.type === 'error')) return;
        const chunks = events.filter(event => event.type === 'audio').map(event => Buffer.from(event.data, 'base64'));
        const pcm = Buffer.concat(chunks);
        if (!pcm.length || pcm.length % 2 || pcm.length > 31 * 24000 * 2 || pcm.length / 2 !== complete.samples) return;
        const name = `native-${String(index).padStart(2, '0')}.wav`;
        await writeFile(path.join(outputDir, name), wav(pcm), { flag: 'wx' });
        Object.assign(record, { completed: true, audio: name, samples: complete.samples,
          seconds: complete.samples / 24000, transcript: complete.text, usage: complete.usage });
      } catch { record.captureFailed = true; }
    })());
  };
  page.on('response', observe);
  return async () => {
    page.off('response', observe); await Promise.allSettled(pending);
    const report = { schema: 'savia-actual-native-audio-capture/v1', actualProviderResponses: true,
      playedReceiptQualifiedByThisObserver: false, turns: turns.sort((a, b) => a.index - b.index) };
    await writeFile(path.join(outputDir, 'native-audio.json'), JSON.stringify(report, null, 2) + '\n', { flag: 'wx' });
    return report;
  };
}
