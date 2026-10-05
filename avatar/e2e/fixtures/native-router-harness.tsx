import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { useNativeRouterVoice } from '../../src/useNativeRouterVoice';
import type { Locale } from '../../src/locale';

declare global {
  interface Window { __nativeHarness: {
    transcripts: { id: string; role: string; text: string; done: boolean }[];
    interruptions: number; utterances: number; tasks: string[]; worlds: string[]; observedErrors: number;
  }; }
}
window.__nativeHarness = { transcripts: [], interruptions: 0, utterances: 0, tasks: [], worlds: [], observedErrors: 0 };
function Harness() {
  const [text, setText] = useState(''), [locale, setLocale] = useState<Locale>('es'), [paused, setPaused] = useState(false);
  const voice = useNativeRouterVoice({ avatar: 'moss', locale, backgroundAsr: true, observerPaused: paused,
    onTranscript: (id, role, text, done) => window.__nativeHarness.transcripts.push({ id, role, text, done }),
    onInterrupted: () => { window.__nativeHarness.interruptions++; },
    onUserUtterance: () => { window.__nativeHarness.utterances++; },
    onObserverError: () => { window.__nativeHarness.observedErrors++; },
    onWorld: avatar => { window.__nativeHarness.worlds.push(avatar); },
    onTask: async message => { window.__nativeHarness.tasks.push(message); return { reply: 'Synthetic result' }; },
  });
  return <main>
    <button onClick={() => void voice.connect()}>Connect native voice</button>
    <button onClick={voice.interrupt}>Interrupt native voice</button>
    <button onClick={voice.toggleMute}>Mute native voice</button>
    <button onClick={voice.disconnect}>End native voice</button>
    <button onClick={voice.resetAccountContext}>Reset native account context</button>
    <button onClick={() => setLocale('pt')}>Portuguese native voice</button>
    <button onClick={() => setPaused(value => !value)}>Pause native observation</button>
    <button onClick={() => { voice.setPersona('spark'); voice.sendText('Cambio inmediato'); }}>Spark same tick</button>
    <button onClick={() => voice.sendTaskResult('synthetic-owned-receipt')}>Queue native result</button>
    <form onSubmit={event => { event.preventDefault(); voice.sendText(text); }}>
      <input aria-label="Native fixture request" value={text} onChange={event => setText(event.target.value)} /><button>Send native text</button>
    </form>
    <output data-testid="phase">{voice.phase}</output><output data-testid="connected">{String(voice.connected)}</output>
    <output data-testid="muted">{String(voice.muted)}</output><output data-testid="error">{voice.error}</output>
  </main>;
}
createRoot(document.getElementById('root')!).render(<Harness />);
