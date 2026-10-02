import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { useGeminiLive } from '../../src/useGeminiLive';
import type { TaskReply } from '../../src/useVoice';

declare global {
  interface Window {
    __geminiHarness: {
      transcript: { id: string; role: string; text: string; done: boolean }[];
      worlds: { avatar: string; scene: number }[];
      tasks: string[];
      resolveTask?: (result: TaskReply) => void;
    };
  }
}
window.__geminiHarness = { transcript: [], worlds: [], tasks: [] };
function Harness() {
  const [text, setText] = useState('');
  const voice = useGeminiLive({
    avatar: 'moss',
    onTranscript: (id, role, text, done) => window.__geminiHarness.transcript.push({ id, role, text, done }),
    onWorld: (avatar, scene) => window.__geminiHarness.worlds.push({ avatar, scene }),
    onTask: message => {
      window.__geminiHarness.tasks.push(message);
      return new Promise(resolve => { window.__geminiHarness.resolveTask = resolve; });
    },
  });
  return <main>
    <button onClick={() => void voice.connect()}>Connect native voice</button>
    <button onClick={voice.interrupt}>Interrupt native voice</button>
    <button onClick={voice.toggleMute}>Mute native voice</button>
    <button onClick={voice.disconnect}>End native voice</button>
    <form onSubmit={event => { event.preventDefault(); voice.sendText(text); }}>
      <input aria-label="Native fixture request" value={text} onChange={event => setText(event.target.value)} />
      <button>Send native text</button>
    </form>
    <output data-testid="phase">{voice.phase}</output>
    <output data-testid="connected">{String(voice.connected)}</output>
    <output data-testid="muted">{String(voice.muted)}</output>
    <output data-testid="error">{voice.error}</output>
  </main>;
}
createRoot(document.getElementById('root')!).render(<Harness />);
