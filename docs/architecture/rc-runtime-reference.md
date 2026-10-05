# Savia RC — implementation reference

Reviewed 5 October 2026. Deployment: [savia-rc-2026.fly.dev](https://savia-rc-2026.fly.dev). Current application source: `7089ca7b63006a066477415aaf54a6932d21a9b2`, branch `codex/savia-listen-saved-result`; image `sha256:39457d88ec4a8577d32dc4623bab5f71a5e5349b808c002db0e258510ce0d38e`. This document describes the integrated Savia submission: browser-rendered googly eyes, the Moss voice persona, authenticated banking inquiry and two informational workers. The original rc.1 source and its recorded journey remain pinned separately below.

The current successor adds an explicit **Escuchar recomendaciones / Ouvir recomendações** control for saved completed team results while voice is active. Its supporting capture records one useful, condensed merchant/receipt reply, 8.2 seconds of actual PCM and one exact full-playback acknowledgement, with no new banking question or workers. It preserves the three inquiries and the grounded conversation after reload. See [the scoped supporting record](../submission/measurements/saved-recommendations-native/README.md); this does not qualify the target 100-conversation fleet.

## 1. Deployment and process topology

One Fly Machine runs two application processes under UID/GID 1000: the Node HTTP gateway and Python/Uvicorn Savia server. `tini` and `public_start.py` supervise their lifecycle. The Python process contains the workflow host, Banking MCP `Service`, voice adapters and inquiry scheduler. These modules communicate through Python calls; they are not separate containers or network services.

The current RC's process topology is described below; the target product/fleet design is in [the technical product architecture](system-landscape.md).

| Boundary | Executable or component | Listener / interface | Responsibility |
| --- | --- | --- | --- |
| Customer browser | React/Vite bundle; `App.tsx`, `Eyes.tsx`, `useSaviaVoice.ts`, `InquiryPanel.tsx` | HTTPS to the public origin; Web Audio locally | Display owned account data, capture speech, play streamed PCM, render eyes and case events |
| Fly edge | Fly HTTP/TLS ingress | Public 443; HTTP 80 redirects to HTTPS | Terminate TLS and forward to Machine port 8080 |
| Gateway process | `node deploy/rc/public-gateway.mjs` | `0.0.0.0:8080` → `127.0.0.1:43900` | Verify visitor cookie, exact host and mutation origin; stream requests and responses |
| Savia process | `python deploy/rc/run.py` → Uvicorn | `127.0.0.1:43900` | Serve built UI and authenticated `/api/*`; bind sessions to approved customers |
| In-process banking | `DisputeHostFactory`, `BankingActionHost`, `banking_mcp.service.Service` | Python method calls with host-bound authorization | Resolve owned selections, execute scoped reads, validate workflow results and simulated intake receipts |
| In-process voice | `Conversation`, `VoiceService` | Authenticated HTTP routes; outbound HTTPS | Native audio conversation, bank-request delegation, one-use host-result narration and playback accounting |
| In-process inquiry team | `InquiryService` | Python async tasks and SQLite | Run evidence and next-step workers concurrently; persist suggestions and due checks |
| External inference | OpenRouter | HTTPS `/api/v1/chat/completions` | Native GPT Audio; language completions for workflow stages and workers |

The deployed Machine is `851d7dc4460048`, region `iad`, with one shared CPU and 1024 MB RAM. Encrypted volume `vol_4qlemp91ly8qn98r` (`rc_data`, 1 GB) mounts at `/data`. Fly auto-stop is disabled and the configured minimum is one running Machine. The gateway streams the Python response rather than buffering voice until completion.

## 2. Data preparation and persistent state

At first boot, if `/data/rc-private/fixture.json` is absent, the supervisor invokes `run.py --prepare`. `build_fixture` generates current-date fictional source files and runs the project's DuckDB pipeline to publish a Parquet snapshot. It creates private profile bindings, a signer and synthetic bank admission state. Preparation is a startup operation; no recurring ETL daemon is configured. Subsequent boots reopen the same fixture and volume. Source hashes are checked before the application starts.

| Location under `/data/rc-private` | Owner / access | Contents and lifetime |
| --- | --- | --- |
| `source/`, `data/` | Generated at preparation; read by server modules | Fictional CSV source, synthetic marker, published `CURRENT` snapshot and Parquet data; queried using DuckDB inside Python |
| `fixture.json`, `private-admission.json`, signer and FX fixture | Server-private files | Exact fictional instance binding, generated admission material and pinned source hashes |
| `gateway-policy.json` | Gateway secret loaded at boot | Visitor-cookie signing secret; persists across image replacement |
| `instance/frontend.sqlite3` | Portal session store | Profile bindings, session cookies and authentication-policy reconciliation |
| `instance/frontend-chat.sqlite3` | Authenticated chat service | Public transcript, owner/session binding, action recovery and revocation state |
| `instance/dispute-workflow.sqlite3` | Workflow host | Query scopes and workflow state |
| `instance/bank.sqlite3` | Banking MCP Service | Synthetic bank authorization, handles and simulated intake ledger |
| `instance/savia-inquiries.sqlite3` | InquiryService | Owner-scoped inquiries, two worker rows per case, event cursors, deadlines and leases |
| `instance/frontend-followups.sqlite3` | Receipt-follow-up service | Separate opt-in tracking of simulated intake receipts |
| Python memory: `Conversation` | Voice service | Bounded conversation history, active turns, pending playback and one-use narration records; lost on process restart |

Portal screens and Banking MCP read the published snapshot with customer/product ownership checks. The browser receives scoped JSON and opaque references, never snapshot files. Provider keys arrive through the server environment (`OPENROUTER_API_KEY`); they are absent from the browser bundle. The RC does not import the organizer S3 dataset or the September 30 application's sessions and ledgers.

## 3. Authenticated request paths

The visitor gate and customer session are two distinct checks. `POST /_rc/enter` creates an eight-hour signed visitor cookie. `POST /api/auth/login` creates the inner profile session. The Python host resolves the customer from this session, not from a browser-supplied customer ID. Both gateway and host validate the configured public origin for mutations; cookies use the configured secure policy.

| Method and route | Request / response | Execution path |
| --- | --- | --- |
| GET `/api/overview`, `/api/transactions` | Scoped account JSON; optional filters | Profile session → Repository → ownership-checked DuckDB query |
| POST `/api/chat/messages` | Message, language, optional opaque transaction reference and query scope → verified reply | Session → owned selection → workflow host → bounded language stages and in-process bank reads → persisted transcript |
| GET `/api/chat/history` | Retained messages and query context | Current session/customer → chat store and workflow context |
| POST `/api/action/prepare`, `/confirm`, `/handoff` | Explicit UI action → verified simulated intake state | Host consent and selection checks → in-process bank authority → receipt verification |
| POST `/api/assistant/cases` | `{message, language, transaction_reference?}` → HTTP 202 `{id, items}` | Session → stable owner binding → minimized selected facts → queued inquiry in SQLite |
| GET `/api/assistant/cases` | `{items}` with worker states, reviewed suggestions and bounded events | Authenticated owner → inquiry store; UI polls every 2 seconds while working, otherwise every 15 seconds |
| POST `/api/assistant/cases/{id}/resolve` | `{resolved:true}` → `informational_resolved` | Owner check → customer-marked useful explanation → tracking stops |
| GET `/api/assistant/voice-update` | Case ID and event cursor → server-owned reply; HTTP 204 if unchanged | Owner check → latest meaningful event → eligible reply registered for this voice session |
| POST `/api/auth/logout` | HTTP 204 after host handling | Retire portal session; host manages admitted-session revocation and retained recovery state |

Bank actions are simulated in this fictional instance. Informational case closure does not submit an action, create a bank resolution or extend consent. Receipt-follow-up endpoints under `/api/followups` are a separate subsystem from the informational inquiry scheduler.

## 4. Voice protocol and avatar execution

The eyes are a React/CSS component inside the assistant dialog. Their activity and level come from `useSaviaVoice`; they have no server process or banking client. Moss is the submitted persona, configured with the provider's `coral` voice. Spanish (`es`) and Brazilian Portuguese (`pt`) are supported.

| Interface | Encoding and authority |
| --- | --- |
| POST `/api/voice/turn` | Exactly one input: base64 WAV `audio`, text `message`, or registered host `result`; language plus bounded turn flags |
| Response from `/api/voice/turn` | `application/x-ndjson`: `start`, optional `heard`, incremental `caption` / `audio`, optional `delegate`, `complete`; errors are explicit events |
| `audio` event | Base64 PCM16, signed little-endian, mono, 24 kHz; decoded and scheduled by browser Web Audio |
| Outbound native request | HTTPS to OpenRouter; `openai/gpt-audio`, streaming text/audio modalities, `coral`, PCM16; bank-delegation tool offered only when admitted |
| POST `/api/voice/played` | Active `turn_id`, exact `played_samples`, `complete`; one matching acknowledgement commits spoken assistant text to voice history |
| POST `/api/voice/transcribe` | Configured recognition adapter; used for dictation and to gate explicit bank-request intent |
| POST `/api/voice/speak` | Configured read-aloud fallback; accepts unused speech chunks registered from actual host output, not arbitrary browser prose |

For an account question, the execution sequence is:

1. The browser collects an utterance and posts it to the authenticated voice route. Python performs bounded recognition to decide whether the current words explicitly request bank work; the native audio model still receives the audio itself.
2. `Conversation` opens the GPT Audio stream. When permitted, the model can call `consultar_savia`. Python emits a `delegate` event; this is a request for host work, not a bank operation.
3. The browser's delegation handler sends the request through ordinary `/api/chat/messages` with the current portal session and selected context. The workflow resolves ownership and returns an actual host reply.
4. The host persists that reply and calls `Conversation.remember_result(session_id, reply)`. The exact reply remains visible in the UI. The browser submits it as a `result` turn for Moss to narrate.
5. The voice service requires an exact, unused result registered to that session within five minutes. It consumes the result once, then streams its spoken retelling. Spoken wording may differ from the persisted screen answer.
6. The browser counts PCM samples and waits for queued playback to drain before sending `/api/voice/played`. Stale turns, mismatched sample counts and reused acknowledgements are rejected. Interruption cancels the active playback path; receiving audio alone does not establish that it was heard.

Meaningful inquiry updates use the same narration binding. The UI fetches `/api/assistant/voice-update` with an event cursor; completed, awaiting-customer and informationally resolved replies are registered by the server. The voice hook queues a background reply while foreground playback is active and deduplicates updates. Queued/working case status is not registered as a completed narration result.

Voice history is bounded and expires after 30 minutes of inactivity. It is separate from the durable portal transcript. A process restart retains cases and chat on the volume but discards active audio turns and their in-memory narration/playback authority.

## 5. Swarm execution, scheduling and failure states

`InquiryService` implements a fixed two-worker team, not an open-ended agent network. A stable HMAC owner binding is derived by the authenticated host from its trusted customer mapping. The selected transaction contributes only reviewed display fields: date, amount, currency, merchant and status. Neither worker receives customer identity, signing material, bank handles or a bank client.

| Stage | Implementation / limit | Durable result |
| --- | --- | --- |
| Intake | Host validates owned reference and bounded message | Inquiry `queued`; worker roles `evidence` and `next_steps` |
| Claim | SQLite `BEGIN IMMEDIATE`; one queued case per scheduler pass; 90-second lease | Inquiry `team_working`; lease and meaningful event |
| Execute | `asyncio.gather` starts both roles; separate actual model calls; 35-second worker deadline, 30-second direct-provider transport budget | Per-role `working`, then `completed` or `failed` |
| Validate | Output must be exactly `{"suggestion":"ENUM"}` with a role-allowed enum | Reviewed suggestion code saved; arbitrary model prose and transport errors are discarded |
| Finish | Both completed → `team_completed`; otherwise `needs_attention` | Final team event and next due time |
| Follow-up | App loop checks approximately every 2 seconds; first due check after 1800 seconds | One transition to `awaiting_customer`; unchanged checks do not create repeated visible events |
| End tracking | Seven-day deadline or explicit customer resolution | No further due check; retained inquiry, suggestions and events remain readable |
| Interrupted team | Expired lease detected after crash/restart | Unfinished workers marked failed; case `needs_attention`; no silent team replay |

The same configured language adapter serves workflow stages and both workers. The deployed RC selects direct OpenRouter; the launcher's default model for that profile is `google/gemini-3.1-flash-lite`. Each worker chooses a reviewed suggestion rather than publishing free-form advice. Follow-up checks do not automatically rerun the models or bank reads. Clearing the chat leaves informational cases intact; a new authenticated session for the same customer can recover them.

Provider or bank failures remain explicit failed/unverified states. A failed narration must not become a claimed bank answer. The gateway returns 502 if the local application is unreachable; `/healthz` returns 503 when its Savia probe fails. The supervisor terminates the sibling child if either application process exits. Health proves local service readiness, not a completed customer journey.

## 6. Build, configuration and verification

`build_public_context.py --revision <commit>` exports committed, allowlisted application source and a per-file manifest. `Dockerfile.public` builds the Vite UI in a Node stage, installs Python dependencies, copies the built assets and verifies source hashes. Private directories, local environment files and generated data/state are outside the build context. Runtime preparation populates the persistent volume.

| Setting / record | Current value or source |
| --- | --- |
| Public origin | `RC_PUBLIC_ORIGIN=https://savia-rc-2026.fly.dev` |
| Gateway ingress / upstream | `0.0.0.0:8080` / `127.0.0.1:43900` |
| Provider configuration | `OPENROUTER_API_KEY` from server secrets; optional `OPENROUTER_CHAT_MODEL` override; native voice configured in `run.py` |
| Runtime directory | `/data/rc-private`; application state in `instance/` |
| Original rc.1 application commit | `9d77a7599128b668b0e34f9c2937eb40b6bd3824` |
| Original rc.1 image digest | `sha256:484fe8edc07ac37dd78f61deb7a08254352b8ce597fa8265f917706e93d199a5` |
| Live checks for this document | Fly Machine `started`; 1 CPU / 1024 MB / encrypted 1 GB volume; public `/healthz` HTTP 200 with `savia:true` |
| Customer-path evidence | Frozen release record: grounded bank answer, both actual workers, saved suggestions, new-chat recovery and two full native-playback acknowledgements |

The live metadata and health checks above were read on 5 October 2026. This documentation update does not repeat customer transactions or deployment. The retained acceptance used prerecorded/file-backed or typed input; physical microphone/AEC behavior remains unqualified. One actual 30-minute follow-up is recorded; seven-day operation is implemented but not observed for a full week.

## 7. Relationship to September 30 and FLUJO

| September 30 configured stack | Current submitted RC |
| --- | --- |
| Docker containers / combined Fly processes, including FLUJO worker :4200 | Node gateway :8080 plus Python Savia :43900; FLUJO is not built into the RC image |
| Banking MCP as a stdio child of FLUJO | Shipped Banking MCP `Service` called in process by the project host |
| Organizer S3 → offline publication → migrated snapshot | Fresh fictional source → same project pipeline → persistent RC snapshot |
| Worker-owned model, conversation and bank-authority state | Project workflow and banking stores; direct OpenRouter inference |
| No integrated submission voice/team shown | Browser eyes/audio hook, server native voice and two async inquiry workers shown at their execution locations |

The September 30 Docker and Fly diagrams remain dated historical configuration records in the viewer. The optional local `--provider flujo` profile uses ordinary generic language interfaces. The separately qualified Inquiry MCP exposes owner-bound stdio tick/status tools to a generic FLUJO flow; its measured schedule is disabled and its state is separate from the portal. Neither is a process or scheduler in the deployed RC diagram. FLUJO main remains generic under the [product boundary](../FLUJO_PRODUCT_BOUNDARY.md).

## 8. Source references

| Architecture fact | Repository source |
| --- | --- |
| Machine resources, ingress, volume and health policy | [Fly RC config](../../deploy/rc/fly.public.toml), [public setup](../../deploy/rc/PUBLIC.md) |
| Build and supervision | [Dockerfile](../../deploy/rc/Dockerfile.public), [supervisor](../../deploy/rc/public_start.py), [manifest exporter](../../deploy/rc/build_public_context.py) |
| Runtime composition, fictional fixture and model selection | [RC launcher](../../deploy/rc/run.py), [fixture builder](../../scripts/qualify_dispute_app.py) |
| Gateway authentication and streaming proxy | [Gateway source](../../deploy/rc/public-gateway.mjs) |
| Sessions, API routes and task startup | [FastAPI app](../../frontend/server/app.py), [session store](../../frontend/server/state.py) |
| Bank ownership and authority | [Host contract](../../frontend/DIRECT_MCP.md), [bank service](../../banking_mcp/service.py) |
| Native voice, result binding and playback | [Conversation](../../frontend/server/conversation.py), [voice adapter](../../frontend/server/voice.py), [browser hook](../../frontend/src/avatar/useSaviaVoice.ts) |
| Integrated eyes and update polling | [Eyes](../../frontend/src/avatar/Eyes.tsx), [assistant UI](../../frontend/src/App.tsx), [inquiry panel](../../frontend/src/InquiryPanel.tsx) |
| Two-worker leases, scheduler and case API | [Inquiry service](../../savia_assistant/service.py), [API](../../savia_assistant/api.py), [inquiry contract](../submission/assistant/README.md) |
| Frozen image and scoped acceptance | [Release record](../submission/RELEASE_CANDIDATE.md), [native receipt](../submission/measurements/intended-savia-native/receipt.json) |

Regenerate the diagrams and HTML with `python docs/architecture/build-landscapes.py`. The Markdown is the technical document source; SVG is editable vector output. The document PDF includes the topology and the interface/storage tables. The standalone legacy avatar worlds are outside this architecture.
