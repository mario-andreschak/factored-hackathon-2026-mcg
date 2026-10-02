import React, { useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import Workbench, { type WorkbenchHandle } from '../../src/Workbench';
import '../../src/styles.css';

function Harness() {
  const workbench = useRef<WorkbenchHandle>(null);
  const operation = useRef<AbortController>(null);
  const [open, setOpen] = useState(true);
  const [message, setMessage] = useState('');
  const [reply, setReply] = useState('');
  const [accountChanges, setAccountChanges] = useState(0);
  return <main>
    <form style={{ position: 'fixed', zIndex: 100, top: 0, left: 0, background: 'white', color: 'black' }} onSubmit={event => {
      event.preventDefault();
      operation.current = new AbortController();
      void workbench.current?.execute(message, { signal: operation.current.signal }).then(result => setReply(result.reply)).catch(error => setReply(error.message));
    }}>
      <input aria-label="Fixture request" value={message} onChange={event => setMessage(event.target.value)} />
      <button>Execute fixture request</button><output data-testid="reply">{reply}</output>
      <button type="button" onClick={() => operation.current?.abort()}>Abort fixture read</button>
      <button type="button" onClick={() => setOpen(true)}>Open fixture computer</button>
      <output data-testid="account-changes">{accountChanges}</output>
    </form>
    <Workbench ref={workbench} avatar="moss" open={open} mode="connected" saviaUrl="/savia/" onClose={() => setOpen(false)} onLoad={() => {}}
      onAccountChange={() => { setAccountChanges(count => count + 1); setReply(''); }} />
  </main>;
}
createRoot(document.getElementById('root')!).render(<Harness />);
