import { useCallback, useEffect, useRef, useState } from 'react';

export function useAmbience() {
  const [enabled, setEnabled] = useState(false);
  const resource = useRef<{ context: AudioContext; source: AudioBufferSourceNode } | null>(null);
  const stop = useCallback(() => {
    resource.current?.source.stop(); void resource.current?.context.close(); resource.current = null; setEnabled(false);
  }, []);
  const toggle = useCallback(() => {
    if (resource.current) { stop(); return; }
    const context = new AudioContext();
    const buffer = context.createBuffer(1, context.sampleRate * 6, context.sampleRate);
    const samples = buffer.getChannelData(0); let value = 0;
    for (let i = 0; i < samples.length; i++) { value = (value + (Math.random() * 2 - 1) * .025) / 1.025; samples[i] = value; }
    const source = context.createBufferSource(); source.buffer = buffer; source.loop = true;
    const filter = context.createBiquadFilter(); filter.type = 'lowpass'; filter.frequency.value = 520;
    const gain = context.createGain(); gain.gain.value = .14;
    source.connect(filter).connect(gain).connect(context.destination); source.start();
    resource.current = { context, source }; void context.resume(); setEnabled(true);
  }, [stop]);
  useEffect(() => () => { if (resource.current) { resource.current.source.stop(); void resource.current.context.close(); } }, []);
  return { enabled, toggle };
}
