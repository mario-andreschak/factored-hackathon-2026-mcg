import fs from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { performance } from 'node:perf_hooks';

if (!process.argv.includes('--execute')) throw Error('Pass --execute for one paid prerecorded audio turn.');
const base = 'http://127.0.0.1:43941';
const fixture = new URL('../.local/qwen-native/20261001-084853-1790862533806878800/es.wav', import.meta.url);
const input = await fs.readFile(fixture);
const hash = createHash('sha256').update(input).digest('hex');
if (hash !== '3956bc585e5bac204010593ea5ae37182ac47828d034ffcb36f8e8daca481d6c') throw Error('Unexpected public audio fixture.');
const dir = new URL('../.local/rc-voice-audio-input/', import.meta.url);
await fs.mkdir(dir, { recursive: true });
await fs.writeFile(new URL('started.json', dir), JSON.stringify({ started_at: new Date().toISOString(), max_calls: 1 }), { flag: 'wx' });
const config = await fetch(base + '/api/avatar/config');
const cookie = config.headers.getSetCookie()[0].split(';')[0];
const start = performance.now();
const response = await fetch(base + '/api/avatar/native-turn', {
  method: 'POST', headers: { Origin: base, Cookie: cookie, 'Content-Type': 'application/json' },
  body: JSON.stringify({ audio: input.toString('base64'), format: 'wav', avatar: 'moss', locale: 'es' }),
  signal: AbortSignal.timeout(45000),
});
const reader = response.body.getReader(), decoder = new TextDecoder();
let carry = '', chunks = [], complete = null, firstAudioMs = null;
while (true) {
  const { done, value } = await reader.read();
  carry += decoder.decode(value ?? new Uint8Array(), { stream: !done });
  const lines = carry.split('\n'); carry = lines.pop();
  for (const line of lines) {
    if (!line.trim()) continue;
    const event = JSON.parse(line);
    if (event.type === 'audio') { firstAudioMs ??= Math.round(performance.now() - start); chunks.push(Buffer.from(event.data, 'base64')); }
    if (event.type === 'complete') complete = event;
    if (event.type === 'error') throw Error(event.code);
  }
  if (done) break;
}
if (!complete || carry.trim()) throw Error('Native stream incomplete.');
const pcm = Buffer.concat(chunks);
if (pcm.length / 2 !== complete.samples) throw Error('Native sample count mismatch.');
const header = Buffer.alloc(44);
header.write('RIFF'); header.writeUInt32LE(pcm.length + 36, 4); header.write('WAVEfmt ', 8);
header.writeUInt32LE(16, 16); header.writeUInt16LE(1, 20); header.writeUInt16LE(1, 22);
header.writeUInt32LE(24000, 24); header.writeUInt32LE(48000, 28); header.writeUInt16LE(2, 32); header.writeUInt16LE(16, 34);
header.write('data', 36); header.writeUInt32LE(pcm.length, 40);
await fs.writeFile(new URL('reply.wav', dir), Buffer.concat([header, pcm]), { flag: 'wx' });
const report = {
  schema: 'savia-prerecorded-spanish-native-input/v1', recorded_at: new Date().toISOString(),
  http_status: response.status, actual_provider_calls: 1, provider: 'openrouter-native', model: 'openai/gpt-audio',
  input: { kind: 'public synthetic prerecorded Spanish WAV', sha256: hash, sample_rate_hz: 24000, seconds: 4.136875,
    utterance: 'Tranquilo, respira hondo. Todo va a salir bien.', typed_message_sent: false },
  bank_calls: 0, generic_flujo_calls: 0, physical_microphone: false, browser_playback: false, playback_ack_sent: false,
  output_sample_rate_hz: 24000, output_sample_rate_qualification: 'assumed', first_audio_ms: firstAudioMs,
  completion_ms: Math.round(performance.now() - start), audio_seconds: complete.samples / 24000, reply: complete.text, usage: complete.usage,
};
await fs.writeFile(new URL('report.json', dir), JSON.stringify(report, null, 2), { flag: 'wx' });
console.log(JSON.stringify(report));
