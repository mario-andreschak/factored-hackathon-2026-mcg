import test from 'node:test';
import assert from 'node:assert/strict';
import { capturePacket, outputPacket } from '../src/experiments/personaplexProtocol';

test('native wire framing retains little-endian generation, clock and signed PCM', () => {
  const wire = new ArrayBuffer(19), view = new DataView(wire);
  view.setUint8(0, 0x11); view.setUint32(1, 0x12345678, true); view.setBigUint64(5, 1920n * 250n, true);
  [-32768, 0, 32767].forEach((sample, i) => view.setInt16(13 + i * 2, sample, true));
  const parsed = outputPacket(wire);
  assert.equal(parsed.generation, 0x12345678); assert.equal(parsed.sampleIndex, 480000);
  assert.deepEqual([...parsed.samples], [-1, 0, 32767 / 32768]);
  assert.deepEqual([...capturePacket(new Uint8Array([0, 128, 255, 127]))], [0x10, 0, 128, 255, 127]);
});

test('native wire rejects malformed clocks, codecs, partial samples and unbounded audio', () => {
  assert.throws(() => capturePacket(new Uint8Array(1)));
  assert.throws(() => capturePacket(new Uint8Array(24000)));
  assert.throws(() => outputPacket(new ArrayBuffer(13)));
  assert.throws(() => outputPacket(new ArrayBuffer(16)));
  const wrongCodec = new ArrayBuffer(15); new DataView(wrongCodec).setUint8(0, 1);
  assert.throws(() => outputPacket(wrongCodec));
  const oversizedClock = new ArrayBuffer(15), view = new DataView(oversizedClock);
  view.setUint8(0, 0x11); view.setBigUint64(5, 0xffffffffffffffffn, true);
  assert.throws(() => outputPacket(oversizedClock));
});
