import type { Page } from '@playwright/test';

export async function mockRealtime(page: Page, gotoHarness = true) {
  await page.addInitScript(() => {
    const originalAudio = window.AudioContext;
    const evidence = {
      peersClosed: 0, channelsClosed: 0, tracksStopped: 0, contextsClosed: 0,
      messages: [] as Record<string, unknown>[],
      channel: null as { readyState: string; onopen?: () => void; onmessage?: (event: { data: string }) => void } | null,
      emit(event: object) { this.channel?.onmessage?.({ data: JSON.stringify(event) }); },
    };
    Object.assign(window, { __voiceTransport: evidence });
    class TestAudioContext extends originalAudio {
      close() { evidence.contextsClosed++; return super.close(); }
    }
    Object.defineProperty(window, 'AudioContext', { value: TestAudioContext });
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: {
      async getUserMedia() {
        // Genuine silent audio track, generated locally; no microphone/device access.
        const source = new originalAudio();
        const stream = source.createMediaStreamDestination().stream;
        for (const track of stream.getTracks()) {
          const nativeStop = track.stop.bind(track);
          track.stop = () => { evidence.tracksStopped++; nativeStop(); void source.close(); };
        }
        return stream;
      },
    } });
    class TestPeer {
      connectionState = 'new';
      onconnectionstatechange?: () => void;
      addTrack() {}
      createDataChannel() {
        const channel = {
          readyState: 'connecting', onopen: undefined as (() => void) | undefined,
          onmessage: undefined as ((event: { data: string }) => void) | undefined,
          send(message: string) { evidence.messages.push(JSON.parse(message)); },
          close() { evidence.channelsClosed++; this.readyState = 'closed'; },
        };
        evidence.channel = channel;
        return channel;
      }
      async createOffer() { return { type: 'offer', sdp: 'v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n' }; }
      async setLocalDescription() {}
      async setRemoteDescription() {
        this.connectionState = 'connected';
        if (evidence.channel) { evidence.channel.readyState = 'open'; evidence.channel.onopen?.(); }
      }
      close() { evidence.peersClosed++; this.connectionState = 'closed'; this.onconnectionstatechange?.(); }
    }
    Object.defineProperty(window, 'RTCPeerConnection', { value: TestPeer });
  });
  await page.route('**/api/avatar/realtime**', route => route.fulfill({
    status: 201, contentType: 'application/sdp', body: 'v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n',
  }));
  await page.route('**/__voice_harness', route => route.fulfill({ contentType: 'text/html', body:
    `<!doctype html><html><body><div id="root"></div>
      <script type="module">
        import RefreshRuntime from '/@react-refresh';
        RefreshRuntime.injectIntoGlobalHook(window);
        window.$RefreshReg$ = () => {};
        window.$RefreshSig$ = () => (type) => type;
        window.__vite_plugin_react_preamble_installed__ = true;
      </script>
      <script type="module" src="/@vite/client"></script>
      <script type="module" src="/e2e/fixtures/voice-harness.tsx"></script>
    </body></html>`,
  }));
  if (gotoHarness) await page.goto('/__voice_harness');
}
