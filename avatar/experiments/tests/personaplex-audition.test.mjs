import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { loopbackUrl, parseWav, wav, publicFixture, inspectOutput, WireObservation, scheduledRecording, plan } from '../personaplex_browser_audition.mjs';

const report = { source_revision: '3428dfd95309a7f3c84fd93259ded0f810d1ff91', model_revision: 'fdaf4090a61cb315c138a1faee287ffd6c716309',
  banking_access: false, clock_frames: 338, continuation_start_frame: 188 };
const output = (generation, clock, count = 1920) => { const packet = Buffer.alloc(13 + count * 2); packet[0] = 0x11; packet.writeUInt32LE(generation, 1); packet.writeBigUInt64LE(BigInt(clock), 5); return packet; };

test('audition accepts only explicit loopback origins without credentials, paths or tokens', () => {
  assert.equal(loopbackUrl(), 'http://127.0.0.1:43937');
  assert.equal(loopbackUrl('http://[::1]:43937/'), 'http://[::1]:43937');
  for (const input of ['https://example.com', 'http://127.0.0.1.attacker.test', 'file:///tmp/a', 'http://user:pass@localhost', 'http://localhost/?ticket=x', 'http://localhost/private', 'http://localhost/#secret']) assert.throws(() => loopbackUrl(input));
});

test('PCM fixture uses only qualified public slices with silence before and between live speech', () => {
  const pcm = Buffer.alloc(338 * 1920 * 2); pcm.fill(7, 0, 4 * 24000 * 2); pcm.fill(9, 188 * 1920 * 2, (188 * 1920 + 8 * 24000) * 2);
  const fixture = publicFixture(pcm, report);
  assert.equal(fixture.length, 25.8 * 24000 * 2);
  assert.ok(fixture.subarray(0, 4 * 24000 * 2).every(value => value === 0));
  assert.ok(fixture.subarray(4 * 24000 * 2, 8 * 24000 * 2).every(value => value === 7));
  assert.ok(fixture.subarray(8 * 24000 * 2, 10 * 24000 * 2).every(value => value === 0));
  assert.ok(fixture.subarray(10 * 24000 * 2, 16 * 24000 * 2).every(value => value === 9));
  assert.deepEqual(fixture.subarray(16 * 24000 * 2, 16.8 * 24000 * 2), pcm.subarray(3.2 * 24000 * 2, 4 * 24000 * 2));
  assert.ok(fixture.subarray(16.8 * 24000 * 2, 18 * 24000 * 2).every(value => value === 9));
  assert.ok(fixture.subarray(18 * 24000 * 2).every(value => value === 0));
  assert.deepEqual(parseWav(wav(fixture)), fixture);
  assert.throws(() => publicFixture(pcm, { ...report, banking_access: true }));
  assert.throws(() => publicFixture(pcm, { ...report, continuation_start_frame: 187 }));
  assert.throws(() => parseWav(wav(fixture).subarray(0, 44)));
  const stereo = wav(fixture); stereo.writeUInt16LE(2, 22); assert.throws(() => parseWav(stereo));
});

test('fixed source artifact is the original pinned public-input WAV, when locally present', async t => {
  let bytes;
  try { bytes = await readFile(new URL('../../.local/personaplex-forced-result/20261001-024017/input.wav', import.meta.url)); }
  catch (error) { if (error.code === 'ENOENT') { t.skip('Ignored operator audition artifact is not present.'); return; } throw error; }
  assert.equal(createHash('sha256').update(bytes).digest('hex'), '02ad05f7d5c8fc4a736d20a97e352f3615be2aaec2512b0191ed722272ff7a05');
  assert.equal(publicFixture(parseWav(bytes), report).length, 25.8 * 24000 * 2);
});

test('observer preserves global clock across a generation ACK and bounds recordable PCM', () => {
  const wire = new WireObservation(); wire.received(JSON.stringify({ type: 'ready', protocol: 'personaplex-pcm-v1', sampleRate: 24000, frameSamples: 1920, format: 'pcm16le' }), 100);
  wire.received(output(0, 0), 180); wire.sent(JSON.stringify({ type: 'interrupt', id: 'private-control-id' }), 200);
  // New-generation audio can precede ACK; it keeps the global sample clock.
  wire.received(output(1, 3840), 260); wire.received(JSON.stringify({ type: 'interrupted', id: 'private-control-id', generation: 1 }), 270);
  wire.received(output(1, 5760), 340);
  assert.equal(wire.interrupts[0].ackLatencyMs, 70); assert.equal(wire.outputSamples, 5760); assert.equal(wire.pending.size, 0);
  assert.throws(() => wire.received(output(1, 7681), 400), { code: 'noncontiguous_native_clock' });
  assert.throws(() => inspectOutput(Buffer.alloc(14)), { code: 'invalid_native_packet' });
  const huge = output(0, BigInt(Number.MAX_SAFE_INTEGER) + 1n); assert.throws(() => inspectOutput(huge), { code: 'invalid_native_clock' });
});

test('mute evidence counts continuing native clock while excluding the resampler boundary', () => {
  const wire = new WireObservation(); wire.mute = 100;
  const capture = Buffer.alloc(4097); capture[0] = 0x10; capture.writeInt16LE(99, 1);
  wire.sent(capture, 101); assert.equal(wire.mutedPackets, 0);
  capture.fill(0, 1); wire.sent(capture, 251); assert.equal(wire.mutedSamples, 2048); assert.equal(wire.mutedNonzero, 0);
  capture.writeInt16LE(2, 1); wire.sent(capture, 300); assert.equal(wire.mutedNonzero, 1);
});

test('scheduled playback recording trims interrupted samples and preserves actual quiet gaps', () => {
  const rows = [{ start: 1, end: 1.04, pcm: Array(1920).fill(.5) }, { start: 1.08, end: 1.16, pcm: Array(1920).fill(-.25) }];
  const pcm = scheduledRecording(rows);
  assert.equal(pcm.readInt16LE(0), 16384); assert.equal(pcm.readInt16LE(1200 * 2), 0); assert.equal(pcm.readInt16LE(2000 * 2), -8192);
  assert.throws(() => scheduledRecording([{ start: 1, end: 2, pcm: [Infinity] }]), { code: 'invalid_recording' });
});

test('default invocation is a preparation plan and performs no browser/provider execution', () => {
  const script = fileURLToPath(new URL('../personaplex_browser_audition.mjs', import.meta.url));
  const result = JSON.parse(execFileSync(process.execPath, [script], { encoding: 'utf8', timeout: 2000 }));
  assert.deepEqual(result, plan()); assert.equal(result.status, 'prepared_not_executed');
  assert.equal(result.durationLimitSeconds, 45); assert.ok(!JSON.stringify(result).includes('ticket'));
});
