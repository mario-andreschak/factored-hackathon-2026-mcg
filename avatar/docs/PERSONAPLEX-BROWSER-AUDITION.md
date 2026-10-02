# Prepared native Game audition

`experiments/personaplex_browser_audition.mjs` is an operator-invoked qualification run. The default command prints a plan without opening a browser, reading credentials, requesting a session, or running cloud work:

```powershell
node experiments/personaplex_browser_audition.mjs
```

Only the explicitly executed command consumes one already-running, ready PersonaPlex lease. It cannot launch or replace a GPU worker. Use the isolated production server with PersonaPlex enabled, no Savia upstream, and no other provider credentials:

```powershell
node experiments/personaplex_browser_audition.mjs --execute --url http://127.0.0.1:43937
```

The origin must be an HTTP(S) loopback origin. Credentials, paths, queries, fragments and remote hosts are rejected. There are no automatic retries, and one admitted WebSocket stream is required. The run fails after 42 seconds and reserves three seconds for browser cleanup; the overall active audition budget is 45 seconds. File preparation occurs before that active budget.

Worker preparation is a separate bounded phase: `personaplex_browser.py` waits at most 240 seconds for the real model/prompt ready flag, and `personaplex_pcm_server.py` has the same initialization bound within its unchanged 600-second lifetime. A later attempt's cold checksum read took 152.205 seconds; prompt setup finished at 178.827 worker seconds, too late for the former 180-second launcher window once container startup was included. That stopped worker's termination was confirmed. The extra headroom preserves all checksums and pinned-cache verification, requires only the existing CPU `--refresh-worker` source overlay, and neither launches a GPU nor retries an audition by itself. The browser's 45-second limit and existing successful native receipt are unchanged.

The test uses installed Edge and its real fake-file microphone device, the actual Game, the actual hook, the actual AudioWorklet, and the actual same-origin relay. It does not mock WebSocket, provider output, capture processing, resampling or audio playback. Passive instrumentation delegates each WebAudio and microphone call to the original browser API. It observes only non-looping 24 kHz buffers connected directly to the voice analyser; the separate looping ambience context is excluded.

The only permitted microphone input is the SHA-256-pinned ignored artifact `.local/personaplex-forced-result/20261001-024017/input.wav`. That 27.04-second file contains original public NVIDIA microphone audio and synthetic silence, rather than the experiment's generated bank narration. The harness extracts the first four seconds containing “Hi” and eight continuation seconds beginning at frame 188 containing the rice question. It adds four leading quiet seconds and two seconds between the excerpts. At fixture second 16 it replaces a quiet part of the continuation tail with the exact public “Hi” bytes from source seconds 3.2–4. The remaining continuation tail and 7.8 quiet seconds keep the fake-device loop at 25.8 seconds. It verifies the pinned source/model revisions, frame counts, and `banking_access: false` before reading those slices. An arbitrary file path or live private microphone cannot be selected.

That repeat timing uses both actual browser auditions. In `2026-10-01T09-19-29-585Z`, the initial public speech windows were fixture seconds 7.2–8 and 10–13.8; sustained native playback ran at scheduled-output seconds 13.6–19.2, with its output timeline beginning roughly 3.3 seconds after CLI start. In `2026-10-01T09-33-43-290Z`, the sustained answer had an audible window at CLI milliseconds 16843–17751, but the second-18 repeat triggered VAD at 19091, just after the answer ended. Both runs correctly failed acoustic overlap acceptance. Moving the repeat to fixture second 16 targets the measured overlap near CLI second 17.1 in the second run and falls within the first answer's broader window. This is an evidence-based candidate; the next run must still demonstrate actual audible overlap rather than accepting an expected timestamp.

Required evidence includes native readiness, real user-quiet entry into the world, a microphone-VAD interrupt that stops a currently audible native buffer, the worker's next-generation acknowledgement, and a newly scheduled audible buffer after user quiet. The script then uses the real pause/mute controls and requires at least 1.5 seconds of continuing zero-valued microphone PCM while muted. It verifies exactly one microphone acquisition, worklet module, admission and socket, contiguous global output clock across generations, and no Savia or alternate voice-route request. Missing actual acoustic overlap is reported as missing barge-in evidence; a manual pause is never substituted for it.

Local output appears under `.local/personaplex-browser/<timestamp>/`:

- `report.json`: fixed diagnostic categories and aggregate timing, generation, clock, mute and resource counts, including merged numeric scheduled-audible windows and the fixed public-repeat timing. It excludes session tickets, provider URLs, headers, transcripts, banking identifiers and arbitrary provider exceptions.
- `native-wire-output.wav`: all received native PCM, including audio held by the browser during interruption. This is transport evidence.
- `native-scheduled-output.wav`: the actual decoded buffers scheduled by the native hook, trimmed when stopped and preserving quiet gaps. It is not a hardware loopback recording.
- `public-microphone.wav`: the verified public audio fixture with silence.
- `world.png`: the actual Game after ending the voice session.

Cleanup attempts the real “End voice” control even after a failure, checks microphone tracks, voice sources, voice context and socket closure when the page remains observable, and closes the browser context unconditionally. A failed page or expired deadline can prevent in-page cleanup measurement; the report distinguishes that from browser closure.

Run the seven supplemental local checks explicitly; they are excluded from the production Docker application-test scope:

```powershell
node --test experiments/tests/personaplex-audition.test.mjs
```

These qualify input bounds, source identity when the ignored artifact is present, PCM extraction, global clock/ACK observation, mute boundary handling, scheduled-recording trimming, and the default preparation mode. Eight separate deterministic browser fixtures exercise the actual hook against mocked transport. Neither set constitutes a real-provider browser audition. Earlier provisional voice feedback was superseded by rejection of this English voice for the LATAM product; bank narration remains unqualified and disabled.
