# Native OpenRouter audio adapter

This adapter sends a completed microphone utterance directly to `openai/gpt-audio` and streams that model's native PCM speech response. It fixes the provider to OpenAI, disables fallback, and uses Coral for all three characters. Moss, Orbit and Spark differ through their speaking instructions; they are not three separately cloned voices. Typed messages use the same native model and output path. There is no dedicated TTS request.

This is **endpointed audio over HTTP with SSE output**, not a persistent Realtime WebSocket or a provider receiving continuous microphone audio. Local voice activity detection ends an utterance before its audio request starts. The browser continues capturing new speech while the response plays and can stop the current output immediately. The user has accepted Spanish interaction and talk-over in the local production preview; measured browser/audio cleanup, physical microphone/AEC qualification and joined banking narration remain separate gates.

## Operator opt-in

Set the following in the component's ignored `.env`:

```dotenv
AVATAR_VOICE_PROVIDER=openrouter-native
```

Use the existing `OPENROUTER_API_KEY` in ignored `openrouter.env` or the server environment. The `npm run dev` and `npm start` commands already load this file. No additional provider key is needed. An OpenRouter key alone does not enable this adapter; an otherwise unconfigured installation remains without voice. Requests require available OpenRouter credit and the installation's existing session, origin, rate, capacity and public access-gate checks. There is no automatic provider retry or fallback.

From `avatar`, use `npm run dev` for the local supervised frontend/server, or `npm run build` followed by `npm start` for the built component. See [operations](OPERATIONS.md) for the existing production TLS/access-gate boundary. Do not expose an ungated paid inference endpoint.

The default product language is Latin American Spanish. The pause menu selects Brazilian Portuguese. A locale change disconnects native voice and clears its server conversation on the next connection. Coral's language instructions do not establish a particular accent or guarantee voice quality.

The optional visible banking inquiry bridge requires a configured Savia installation:

```dotenv
AVATAR_NATIVE_READ_BRIDGE=readonly
SAVIA_UPSTREAM=http://127.0.0.1:43800
SAVIA_PUBLIC_ORIGIN=http://localhost:43800
```

These addresses describe the installed local Savia transport and its required Origin; use the exact configured Origin for another installation. The bridge remains off unless explicitly selected. Savia owns login and account permissions. The user signs in on the visible embedded screen. Eligible spoken or typed read-only inquiries use actual visible UI interactions; the adapter does not authorize a dispute, transfer or other write operation. The read continues after backend admission even if voice is interrupted. Ending voice cancels pending/pre-submit admission; it does not prove an already-admitted job was canceled.

Background recognition supports transcript, scene/intent selection and conversation history. It receives the same captured WAV through a separate bounded, owned observer request; it does **not** generate the native spoken answer. The voice request still contains actual audio. Observation is suppressed while the account screen/task is active, and stale observations cannot admit a new read. This also means continuous user transcription is not promised while that screen is open.

A supervised [read-only validation beta](http://localhost:43942) now has native voice/observer, Savia and the exact read bridge flag configured. It is separate from the bank-disabled `http://127.0.0.1:43941` preview. Distinct loopback hostnames isolate their host-only session cookies; different ports alone would not. Preparation verified only the component config, with no new Savia login, bank query or physical microphone acceptance by root. Its joined spoken inquiry/result gate remains pending.

## Conversation and result boundaries

`server/openrouter-native.mjs` fixes the native model, provider, Coral voice, PCM16 output and 512-token completion cap. Each operation has a 45-second deadline, bounded cancellation cleanup, a 31-second PCM ceiling and independent 4 MiB provider/client stream limits. Audio deltas are independently base64-decoded and emitted in packets of at most 24,000 PCM bytes, with actual response backpressure. Public errors contain fixed safe wording/codes rather than provider bodies.

Both server and browser explicitly label the **24 kHz mono PCM16 rate as assumed**. Current reviewed Chat audio contracts do not independently establish that rate. Recognizable audition playback does not change this qualification label.

Completion requires stable audio identity, nonempty PCM and caption, a valid terminal, exactly one `[DONE]`, clean EOF and bounded reported usage. Native WAV turns additionally require positive reported input-audio tokens. Explicit non-stop finishes, changed identity, tools/refusal/message envelopes, unknown fields and late speech fail closed. The terminal compatibility rule accepts positive expiry after previously accumulated audio, followed only by harmless assistant/empty-content metadata or an identical, previously observed ID-only frame. The latter frame is a tested application compatibility inference; the actual Portuguese receipt observed only bare assistant metadata. This is not the literal Node SDK terminal predicate.

Received bytes and displayed interim captions do not qualify heard history. The server publishes a strictly validated result before exposing completion; its response controller remains revocable through delivery. Only a full browser playback receipt matching the completed sample count admits assistant text to future context. Partial/interrupted assistant speech is omitted. A response cancellation preserves independent recognition of its already-captured user input; reset, account changes and locale changes revoke both owned paths. First sign-in can retain the microphone while resetting its account scope and discarding old recognition/output/ACK state. A delayed backend result is bound to the captured native session owner and cannot be queued into a replacement connection.

Savia results enter voice through recent, account-bound, single-use server receipts. The browser cannot submit history, tools, model routing or invented backend facts to a native turn. Result narration waits behind current user capture/output. The live companion may continue while the heavy read runs; it has no account tools and is instructed to avoid invented facts or action promises. That concurrent behavior remains an actual joined banking qualification gate.

The last consumed backend result may remain as separately quoted trusted data for at most 120 seconds. It is not an unheard assistant transcript or authorization. Any private result/history forwarding requires a fresh Savia identity check and unchanged owner. Reset/account/locale changes clear this context. Logout and upstream authentication rejection revoke native owners synchronously, and old-account task replies are withheld before delivery.

## Evidence and remaining gates

The user's accepted Spanish Coral preview is `es.failed-diagnostic.wav` from ignored `.local/openrouter-s2s-sdk-terminal/2026-10-01T16-07-55-356Z`. Its human voice-quality acceptance remains separate from that request's failed strict terminal receipt. The Portuguese request at `.local/openrouter-s2s-pt-tail/2026-10-01T16-44-50-910Z/report.json` completed under the application metadata-tail rule: 278,400 decoded PCM bytes, one `[DONE]`, clean EOF, and $0.009474 reported cost. Portuguese subjective acceptance is pending. Neither probe exercised this production browser hook, a real microphone, Savia or a banking result. [Audition evidence](OPENROUTER_S2S_AUDITION.md) preserves all earlier failed receipts and charged admissions.

After these probes, the user tried Spanish speech and talk-over in the local native preview on port 43941 and reported, “it's amazing. excellent.” This is human-reported acceptance of Spanish live interaction/interruption. It is not an instrumented AEC measurement, Portuguese acceptance, banking-result qualification or a claim that this HTTP adapter uses a persistent provider Live session.

The current `npm run check` passed TypeScript/Vite and **297 unit cases with one optional installed-upstream skip**. The clean native browser suite passed **16/16 in 40.9 seconds**: eight hook, three movie and five visible-read cases, including reconnect ownership, first-login ACK scope and speech animation during background work. These use synthetic transports.

The actual production HTTP QA then completed **two native Spanish/Portuguese WAV turns** through this server/module, with strict completion, clean EOF, unchanged source fingerprints and closed ephemeral server. First decoded PCM arrived after **1.764 s / 1.297 s**; new reported cost was **$0.0284**, or **$0.059458** for these six controlled requests including the four prior S2S charges. That subtotal excludes live-preview usage, Modal and other research. The two playback receipts were explicitly simulated. No observer ASR, Savia, bank, GPU or physical microphone was exercised; request decode timings are not audible latency. The rate remains assumed. The final restricted image passed **41 runtime checks**, with a clean build of **289 passes / 9 explicit skips**, and both owned containers removed. See the [canonical validation ledger](OPENROUTER_NATIVE_VALIDATION.md) for exact receipts, image ID, source, costs and remaining gates.

Before claiming native release acceptance, finish instrumented production input/output, interruption and cleanup checks, physical microphone/AEC behavior, Portuguese subjective quality, and joined spoken inquiry → visible owned Savia read → accurate native result speech → heard-history continuation. Current fixtures and the user's Spanish interaction acceptance do not close those remaining gates. No additional paid probe, bank query or production deployment is authorized by this document.
