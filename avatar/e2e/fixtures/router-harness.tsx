import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { useRouterVoice } from '../../src/useRouterVoice';
import type { TaskReply } from '../../src/useVoice';

declare global {
  interface Window {
    __routerHarness: {
      transcript: { id: string; role: string; text: string; done: boolean }[];
      worlds: { avatar: string; scene: number }[];
      tasks: string[];
      resolveTask?: (result: TaskReply) => void;
    };
  }
}
window.__routerHarness = { transcript: [], worlds: [], tasks: [] };
function Harness() {
  const [text, setText] = useState('');
  const voice = useRouterVoice({
    avatar: 'moss',
    onTranscript: (id, role, text, done) => window.__routerHarness.transcript.push({ id, role, text, done }),
    onWorld: (avatar, scene) => window.__routerHarness.worlds.push({ avatar, scene }),
    onTask: message => {
      window.__routerHarness.tasks.push(message);
      return new Promise(resolve => { window.__routerHarness.resolveTask = resolve; });
    },
  });
  return <main>
    <button onClick={() => void voice.connect()}>Connect router voice</button>
    <button onClick={voice.interrupt}>Interrupt router voice</button>
    <button onClick={voice.toggleMute}>Mute router voice</button>
    <button onClick={voice.disconnect}>End router voice</button>
    <form onSubmit={event => { event.preventDefault(); voice.sendText(text); }}>
      <input aria-label="Router fixture request" value={text} onChange={event => setText(event.target.value)} />
      <button>Send router text</button>
    </form>
    <output data-testid="phase">{voice.phase}</output>
    <output data-testid="connected">{String(voice.connected)}</output>
    <output data-testid="muted">{String(voice.muted)}</output>
    <output data-testid="error">{voice.error}</output>
  </main>;
}
createRoot(document.getElementById('root')!).render(<Harness />);
