import React, { useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { usePersonaPlex } from '../../src/experiments/usePersonaPlex';
import type { AvatarId } from '../../src/domain';

declare global {
  interface Window {
    __personaplexHarness: {
      transcript: { id: string; role: string; text: string; done: boolean }[];
      initialSelections: AvatarId[]; initialTranscripts: { id: string; text: string }[]; userUtterances: number;
    };
  }
}
window.__personaplexHarness = { transcript: [], initialSelections: [], initialTranscripts: [], userUtterances: 0 };
function Harness() {
  const [observerPaused, setObserverPaused] = useState(false);
  const initialRole = new URLSearchParams(location.search).get('initial') === '1';
  const [initialAvatar, setInitialAvatar] = useState<AvatarId>('moss');
  const taskHolds = useRef<(() => void)[]>([]);
  const voice = usePersonaPlex({
    avatar: 'moss',
    initialRole,
    backgroundAsr: new URLSearchParams(location.search).has('observer'), observerPaused,
    onTranscript: (id, role, text, done) => window.__personaplexHarness.transcript.push({ id, role, text, done }),
    onObservedTranscript: (id, text) => window.__personaplexHarness.transcript.push({ id, role: 'user', text, done: true }),
    ...(initialRole ? {
      onInitialSelection: (avatar: AvatarId) => { setInitialAvatar(avatar); window.__personaplexHarness.initialSelections.push(avatar); },
      onInitialTranscript: (id: string, text: string) => {
        window.__personaplexHarness.initialTranscripts.push({ id, text });
        window.__personaplexHarness.transcript.push({ id, role: 'user', text, done: true });
      },
      onUserUtterance: () => { window.__personaplexHarness.userUtterances++; },
    } : {}),
  });
  return <main>
    <button onClick={() => void (initialRole ? voice.connect('moss', new URLSearchParams(location.search).has('observer'), true) : voice.connect())}>Connect experimental voice</button>
    <button onClick={voice.interrupt}>Interrupt experimental voice</button>
    <button onClick={voice.toggleMute}>Mute experimental voice</button>
    <button onClick={voice.disconnect}>End experimental voice</button>
    <button onClick={voice.resetObserver}>Reset background observer</button>
    <button onClick={() => setObserverPaused(value => !value)}>Pause background observer</button>
    <button onClick={() => { const finish = voice.beginTaskHold(); if (finish) taskHolds.current.push(finish); }}>Begin task hold</button>
    <button onClick={() => taskHolds.current.at(-1)?.()}>Complete task hold</button>
    <button onClick={() => taskHolds.current[0]?.()}>Complete first task hold</button>
    <output data-testid="phase">{voice.phase}</output>
    <output data-testid="connected">{String(voice.connected)}</output>
    <output data-testid="muted">{String(voice.muted)}</output>
    <output data-testid="error">{voice.error}</output>
    {initialRole && <>
      <output data-testid="initial-listening">{String(voice.initialListening)}</output>
      <output data-testid="initial-avatar">{initialAvatar}</output>
    </>}
  </main>;
}
createRoot(document.getElementById('root')!).render(<Harness />);
