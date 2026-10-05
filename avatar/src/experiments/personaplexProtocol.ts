/** Custom PCM protocol; never send these packets to NVIDIA's stock Opus server. */
export const PERSONAPLEX_PROTOCOL = 'personaplex-pcm-v1';
export const PCM_RATE = 24000;
export const PCM_FRAME_SAMPLES = 1920;
export const OUTPUT_HEADER_BYTES = 13;

export function capturePacket(pcm: Uint8Array): Uint8Array {
  if (!pcm.length || pcm.length % 2 || pcm.length > PCM_FRAME_SAMPLES * 2 * 6) throw new Error('Invalid microphone frame.');
  const packet = new Uint8Array(pcm.length + 1); packet[0] = 0x10; packet.set(pcm, 1); return packet;
}

export function outputPacket(buffer: ArrayBuffer) {
  const length = buffer.byteLength - OUTPUT_HEADER_BYTES;
  if (length <= 0 || length % 2 || length > PCM_FRAME_SAMPLES * 2 * 6) throw new Error('Invalid native audio frame.');
  const view = new DataView(buffer);
  if (view.getUint8(0) !== 0x11) throw new Error('Unexpected voice protocol.');
  const generation = view.getUint32(1, true), clock = view.getBigUint64(5, true);
  if (clock > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error('Invalid voice clock.');
  const samples = new Float32Array(length / 2);
  for (let i = 0; i < samples.length; i++) samples[i] = view.getInt16(OUTPUT_HEADER_BYTES + i * 2, true) / 32768;
  return { generation, sampleIndex: Number(clock), samples };
}
