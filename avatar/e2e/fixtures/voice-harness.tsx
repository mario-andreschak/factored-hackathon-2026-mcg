import React from 'react';
import { createRoot } from 'react-dom/client';
import { useVoice } from '../../src/useVoice';
import type { TaskReply } from '../../src/useVoice';

declare global {
  interface Window {
    __voiceHarness: {
      transcript: { id: string; role: string; text: string }[];
      tasks: string[];
      resolveTask?: (result: TaskReply) => void;
    };
  }
}

window.__voiceHarness = { transcript: [], tasks: [] };
function Harness() {
  const voice = useVoice({
    avatar: 'moss',
    onTranscript: (id, role, text) => { window.__voiceHarness.transcript.push({ id, role, text }); },
    onWorld: () => {},
    onTask: message => {
      window.__voiceHarness.tasks.push(message);
      return new Promise(resolve => { window.__voiceHarness.resolveTask = resolve; });
    },
  });
  return <main>
    <button onClick={() => void voice.connect()}>Connect test voice</button>
    <button onClick={voice.interrupt}>Interrupt test voice</button>
    <button onClick={voice.toggleMute}>Mute test voice</button>
    <button onClick={voice.disconnect}>End test voice</button>
    <output data-testid="phase">{voice.phase}</output>
    <output data-testid="connected">{String(voice.connected)}</output>
    <output data-testid="muted">{String(voice.muted)}</output>
    <output data-testid="error">{voice.error}</output>
  </main>;
}
createRoot(document.getElementById('root')!).render(<Harness />);
