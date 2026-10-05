# Native PersonaPlex relay candidate

Design reviewed October 1, 2026 against Modal's current official documentation
and installed SDK 1.5.5. The relay, cache/launcher and raw worker are implemented
and tested locally. The hook is connected to an explicit Game provider selection;
the running/default provider remains `none` until the operator enables this
audition. The private CPU weight cache completed on October 1. The first cached
GPU attempt reached its real model/prompt readiness flag in about 80 seconds,
then failed before browser admission during Connect Token provisioning. Worker
termination was confirmed. A later CPU-only probe verified authenticated HTTP
and WSS with the corrected network policy. A later 19.619-second GPU/browser
fixture passed actual continuous native audio, audible interruption, mute clocks
and cleanup. This candidate has no qualified bank narration, live persona
changes or tool calling. Physical-microphone/AEC and human-conversation acceptance
are separate from this public-fixture browser receipt.

## Admission and ownership

Use the avatar server as a same-origin WebSocket relay. Only an operator's local
launcher may create one bounded GPU worker; the HTTP application receives a
ready lease and cannot launch or replace a worker. An unavailable or expired
lease produces 503 before any Modal call. This removes anonymous cold starts
from the browser request path, including when an authenticated visitor retries.

| Surface | Fixed contract |
| --- | --- |
| `POST /api/avatar/personaplex-session` | JSON containing only `{avatar:'moss'\|'orbit'\|'spark'}`. Requires the existing local avatar session, allowed Origin/Host, public ingress gate when configured, six-start-per-minute limit and a ready worker lease. Voice does not require bank login. |
| Admission response | `{ticket,expiresAt,streamPath:'/api/avatar/personaplex',inputSampleRate:24000,outputSampleRate:24000,protocol:'personaplex-pcm-v1'}`. Random 32-byte base64url ticket, one use, 15-second TTL, bound to avatar session, worker lease epoch and fixed avatar preset. `expiresAt` is the ticket deadline, not the GPU lifetime. |
| WebSocket upgrade | `/api/avatar/personaplex?ticket=...`; validate Origin, Host, cookie and ingress gate again. Atomically consume the ticket and reserve the single stream before dialing the fixed worker. Reject a busy worker with 409. No queue or automatic retry. |

The remote ingress must also strip/inject `X-Avatar-Gateway-Token` on Upgrade.
Never pass banking cookies, Modal API credentials or provider access tokens to
the browser or GPU worker. Redact ticket query strings from access logs. Keep
the worker URL/token/epoch in relay memory; an operator-provided lease is fixed
trusted configuration, never a request-selected URL. Validate its HTTPS origin
and port, forbid redirects, and dial only its corresponding WSS path.

Node 22 has no built-in WebSocket server. The backend now pins `ws` 8.22.0 from
the official registry, with server-side Authorization-header support, strict
message limits, UTF-8 validation and compression disabled. The browser uses its
native `WebSocket`, receiving only the local one-use ticket.

## Bounded browser audition: Sandbox Connect Tokens

Prefer one Sandbox over a public Web Function for the first browser audition.
Modal supports authenticated HTTP/WSS using `create_connect_token(port=8080)`.
The relay sends its token in `Authorization: Bearer ...`; use no token-bearing
browser URL, cookie or raw forwarded port. Include only an opaque lease epoch
in optional metadata; the worker can verify Modal's `X-Verified-User-Data`.
Installed SDK 1.5.5 exposes no token expiry/one-use arguments, so do not claim
those properties for the Modal token. Our local admission ticket supplies them.
No `encrypted_ports` or `unencrypted_ports` fallback is enabled. The launcher
allows outbound CIDR `127.0.0.0/8` only and leaves `block_network` unset. An actual
ready CPU worker with `block_network=True` failed Connect Token provisioning with
`ConflictError`/`FAILED_PRECONDITION`; the fixed loopback-only CIDR policy passed
authenticated HTTP and WSS and terminated cleanly. This permits local loopback
connections without public egress or runtime model downloads. Never combine
`block_network=True` with CIDR policies.
[Modal Sandbox networking](https://modal.com/docs/guide/sandbox-networking)

The launcher owns a single `A100-80GB` Sandbox, CPU `(2,4)`, memory
`(32768,65536)` MiB and `timeout=600`. It starts the fixed source-backed worker
on port 8080, using the already qualified Python 3.11/Torch 2.4.1 image. Add an
exec readiness probe for a flag written only after model/prompt warmup; mere
TCP acceptance is insufficient. Call `wait_until_ready(timeout=240)`, check
private health/model revision, then issue the connect credential and register
the lease. Start/ready failure, parent cancellation, client disconnect and the
deadline all revoke the lease and issue exactly one `terminate(wait=False)` in
`finally`, with a five-second command deadline. Record acknowledgment separately;
then use bounded exit polls for at most ten seconds. Only an observed exit marks
termination confirmed. Unobserved exit retains a cleanup warning and exits the
launcher with status 1, while the provider lifetime remains the final backstop.
Sandboxes survive their creation client's exit, and readiness timeout does not
terminate them. The provider's 600-second lifetime is the final backstop;
`idle_timeout` is insufficient. GPU Sandboxes use the gVisor runtime.
[Modal Sandbox lifecycle](https://modal.com/docs/guide/sandboxes)

The lease closes streams before the Sandbox's remaining lifetime expires;
warmup consumes that lifetime. The client hook's 600-second maximum is only an
upper bound, not a promise of 600 seconds after connection. Capture the created
Sandbox ID locally for cleanup, without putting it in browser config. Do not
detach, deploy, create a named persistent secret, run a second worker or
automatically retry. These are application bounds; verify actual termination.
[Sandbox API](https://modal.com/docs/sdk/py/latest/Sandbox)

At current standard rates, 600 seconds at the maximum resource limits estimates
`600 × (0.000694 + 4 × 0.00003942 + 64 × 0.00000667) = $0.7671`.
Sandbox CPU/RAM rates differ from Function rates. CPU image building is separate;
about $1 total is a target estimate, not an enforced account budget. No region
premium or nonpreemptible option is selected. [Modal pricing](https://modal.com/pricing)

## Remove download and warmup from the user gesture

Keep NVIDIA source revision `3428dfd95309a7f3c84fd93259ded0f810d1ff91` and model
revision `fdaf4090a61cb315c138a1faee287ffd6c716309`. Build a private immutable
weight image before launching the audition. Modal supports image layers for
weights; a Volume is another option for later reuse, but adds persistent
resource ownership. Store only the fixed five model assets and verified voice
embeddings, with a revision/checksum manifest. Never publish gated weights to a
public registry. [Modal model storage](https://modal.com/docs/guide/model-weights)

Keep the heavyweight layer before frequently edited relay source. A copied
preparation script plus CPU `Image.run_commands(..., secrets=[Secret.from_dict(...)])`
can download the pinned assets using existing granted Hugging Face access.
The secret exists only in the build environment: no token in image ENV, source,
arguments, credential cache or output. Use `add_local_file(...,copy=True)` for
the preparation and worker source; a Sandbox must not depend on Function source
mount behavior. Reuse the existing `build_image()` dependency chain rather than
changing pinned versions. [Image API](https://modal.com/docs/sdk/py/latest/Image)

Runtime uses explicit local files with `HF_HUB_OFFLINE=1` and
`local_files_only=True`, no HF secret and no download fallback. Reject an
incomplete manifest. Private operator warmup still loads weights into VRAM,
initializes Mimi/LM and runs representative frames; report actual ready only
afterwards. Image caching removed the observed download from the cached GPU
attempt, but its approximately 80-second prompt/model initialization still
happened before user admission. That attempt failed before authenticated transport.
[Modal cold starts](https://modal.com/docs/guide/cold-start)

Memory snapshots are a possible later optimization, not an audition prerequisite:
Function snapshots require deployment, GPU snapshots are alpha, and storage
loading is not automatically accelerated. [Modal snapshots](https://modal.com/docs/guide/memory-snapshots)

## Native PCM protocol

The stock NVIDIA server uses Opus and accepts client prompt/voice query
parameters. The custom worker must bind presets server-side and implement this
raw PCM adapter; the implemented browser hook connects through our relay to that
custom worker. Keep fresh Mimi/LM streaming caches per admitted user, one GPU stream,
and reset them on disconnect. [Pinned NVIDIA server](https://github.com/NVIDIA/personaplex/blob/3428dfd95309a7f3c84fd93259ded0f810d1ff91/moshi/moshi/server.py)

| Message | Wire format |
| --- | --- |
| Ready JSON | `{type:'ready',protocol:'personaplex-pcm-v1',sampleRate:24000,frameSamples:1920,format:'pcm16le'}` after actual warmup. |
| Input binary | `0x10` followed by signed PCM16LE, mono 24 kHz, even payload length. |
| Output binary | `0x11`, uint32 LE generation, uint64 LE sampleIndex, then PCM16LE. Header is 13 bytes. The global clock continues across interruptions. Anchor at the first new-generation packet after discarded output, then enforce contiguity. |
| Captions JSON | `{type:'transcript',id,role:'assistant',text,done,generation}`. Agent text tokens qualify only assistant captions; fabricated user-ASR captions are rejected. |
| Interrupt | Client `{type:'interrupt',id}`; worker `{type:'interrupted',id,generation}` after invalidating prior output/forced-result work. Generation increases monotonically. |
| Errors | A fixed bounded public code/message; no provider diagnostics, paths or credentials. |

Each audio payload allows at most six native frames (23,040 bytes); prefer one
1,920-sample/80-ms frame per output. Bound JSON to 16 KiB and caption text to
8,000 characters. Limit outstanding input/output to 0.48 seconds, never buffer
unlimited audio to hide slow inference. Continuous clock input includes zero
PCM while muted; microphone tracks are disabled. Interrupt clears browser
playback immediately and generations reject late audio. Server ping/pong,
missing-audio timeout, backpressure failure, session expiry and disconnect close
both sockets, clear queues and release the stream. Qualify these timings with
real capture rather than treating offline compute time as end-to-end latency.

## Bank results and remaining gates

PersonaPlex is not a qualified tool planner or user-ASR provider. Existing Savia
authentication and the visible Workbench remain the task authority. Future
result injection must originate from the server's admitted task, bound to the
current bank identity, avatar session and live worker epoch. Browser-authored
result strings cannot prove bank facts. A voice interrupt does not cancel an
already admitted Savia read. Logout prevents later result delivery.

The forced synthetic test preserved model cache and exact text IDs. Independent
ASR preserved `$42.17`, misheard `Mira Chen` as `By Merchant`, and detected the
unsupported continuation `No action will be taken`. Therefore bank-result speech
stays disabled until names/amounts are audibly verified and free bank narration
is mechanically bounded. Native speech quality approval is separate from that
qualification. The later public-fixture browser receipt proves its measured
interruption path; it does not qualify tool calling or bank-result speech.

Eleven relay checks now cover origin/gate/ticket expiry/replay, unready-worker
no-start behavior, strict wire parsing, global clocks through interruption,
secret projection and disconnect/shutdown cleanup. Twenty-one launcher/cache checks
and ten worker checks cover local native framing/auth/readiness and bounded
termination. Seven additional CPU-probe checks qualify local HTTP/WSS framing
and cleanup. The current full Python experiment suite passes 103 cases, including
the intrinsic-pacing candidate's twenty-two local cases. Accurate closed bank-result
speech has its own later qualification gate and remains disabled in this basic
conversation audition. All three fixed launch personas currently share NATM1;
earlier general voice-quality feedback was provisional and later superseded by
the user's rejection of this English voice for the LATAM product. These transport
receipts do not qualify Spanish or Portuguese speech.

The corrected real browser receipt at
`avatar/.local/personaplex-browser/2026-10-01T09-40-43-286Z/report.json` completed
in 19.619 seconds with one admission and one provider WebSocket, zero bank calls,
ready in 1,520 ms and first PCM in 1,769 ms. It observed audible VAD interruption
and quiet resume, VAD acknowledgments at 129/128 ms and manual acknowledgment at
134 ms. Muted input stayed zero for 1.746 seconds/37,888 samples. PCM clocks had
no gaps; all tracks, contexts and sources closed. The matching launcher receipt
recorded actual model readiness in 58.147 seconds and confirmed worker exit and
termination after 104.769 seconds total. The launcher's own
`nativeBrowserAcceptanceVerified:false` field is preserved: only the separate
browser fixture can establish this acceptance. There was no chained voice
endpoint, runtime model download or surviving GPU worker.

Optional background user ASR is implemented behind
`AVATAR_BACKGROUND_ASR=openrouter` and a server-only OpenRouter key; its default
is off. It sends bounded completed microphone utterances to transcription while
native PCM remains the conversation path. Dispatch requires the current ready
stream owner, valid session/lease deadlines and existing ingress/rate controls.
Disconnect or expiry aborts the observer; late results are withheld. This enables
user captions/intent observation, not tool authority or bank narration, and does
not enable OpenRouter conversation/TTS under the PersonaPlex provider. Its
source/lifecycle tests are separate from the above observer-off browser receipt.

The intrinsic speech-accuracy study uses native padding timing and a measured
silent drain, with a permanently closed post-reply output gate. It remains
unqualified after one failed inference attempt; production narration remains disabled. See
[intrinsic pacing qualification](PERSONAPLEX_INTRINSIC_PACING.md).

## Operator commands and lease

From the repository root, planning is local:

```powershell
python avatar/experiments/personaplex_browser.py --plan
```

The separately authorized CPU cache build uses already granted HF access, no
GPU, a 600-second download-step timeout and no permanent named secret:

```powershell
python avatar/experiments/personaplex_browser.py --build-cache
```

After review and a completed cache, the authorized one-worker audition is:

```powershell
python avatar/experiments/personaplex_browser.py --execute --avatar moss
```

When only the worker changes, preserve the expensive private weight layer. This
explicit CPU-only refresh copies worker/core/pinned source over the existing
image ID and runs bounded Python compilation; it never reads HF credentials or
re-enters the model download/build stage:

```powershell
python avatar/experiments/personaplex_browser.py --refresh-worker
```

Default ignored artifacts live in `avatar/.local/personaplex-browser/`.
`cache.json` records the pinned private image reference. `lease.json` contains
the temporary connect token, exact pins/epoch/avatar, deadline and a two-second
health heartbeat. Permissions are restricted before credentials are written;
publication is atomic. Relay rejects heartbeats older than six seconds. The
launcher removes only its own epoch's lease and writes a sanitized cleanup
report. A one-launcher lock prevents a second GPU job. `worker.json` retains the
local cleanup ID; `last-run.json` records whether termination was confirmed.
Failures preserve the actual stage, an allowlisted exception class and fixed
gRPC status when available. Raw messages, URLs and credentials are omitted.
App and Sandbox async operations use one attached async lifecycle.
Sanitized previous reports are archived locally before another explicit launch.
The second cached GPU attempt ended at the former 120-second readiness deadline:
its worker was still awaiting model initialization, SDK status was
`ServiceError`/`CANCELLED`, and the termination wait had not confirmed exit before
the client deadline. A subsequent owned-worker poll observed exit 137 and Modal
showed the worker terminated. This was a readiness-budget failure; the report
does not establish preemption or a model exception. An interim 180-second readiness
budget also proved too short during a later cold cached-image read: checksum
verification consumed 152.205 worker seconds and prompt readiness arrived at
178.827 seconds, with container startup consuming part of the launcher window.
That later worker's termination was acknowledged and confirmed. Launcher and
worker initialization now each permit 240 seconds within the unchanged
600-second Sandbox/lifetime; all checksum verification remains mandatory and
there is no automatic retry. This additional source headroom has not itself
been qualified by another actual attempt. Fixed worker
milestones now identify hash verification, imports, model loads, warmup and prompt
stages without reflecting raw diagnostics or user input.

Set `AVATAR_VOICE_PROVIDER=personaplex` and `AVATAR_PERSONAPLEX_LEASE_FILE` to the
absolute lease path on the separate test server. Config returns only fixed
`voiceAvatar` and boolean availability; an active/consumed epoch cannot accept a
second stream. Availability becoming false during an active session is not a
request to disconnect that existing hook. Voice persona is fixed at launch;
changing the visual avatar ends that native session and uses silent preview.

## CPU-only transport diagnosis

`modal_transport_probe.py` is an explicit operator diagnosis, never part of the
web application or an automatic retry. The default plan reads no key or private
file. Each `--execute` creates one 30-second, maximum half-core/512-MiB Sandbox
with a small Python standard-library source image. It creates a Connect Token,
verifies fixed health and actual WSS echo, then terminates in `finally`. No GPU,
model, HF secret, raw port or persistent service is involved. The maximum
Sandbox runtime estimate is $0.000691; image preparation is separate.

```powershell
python avatar/experiments/modal_transport_probe.py --plan
# One explicit diagnosis; never automatically repeated:
python avatar/experiments/modal_transport_probe.py --execute --egress-policy loopback-only
```

The CPU transport qualification passed with `loopback-only` and confirmed
termination. Its ignored `avatar/.local/modal-transport-probe/last-run.json`
records only safe results. The probe's `blocked` policy remains available for
diagnosing the observed precondition failure, but is not used by the voice
launcher. The current SDK provides separate legacy and V2 Connect Token APIs;
GPU requests use the legacy backend. The observed network-policy precondition
failure and successful authenticated CPU transport do not justify adding a
raw-port fallback. The subsequent native browser receipt above qualifies the
corrected GPU transport for that bounded fixture.
[Sandbox V2](https://modal.com/docs/guide/sandbox-v2)

## Later production alternative

For a deployed Web Function, require `requires_proxy_auth=True` on `web_server`
or `asgi_app` and keep its workspace Proxy Token only in the relay. Web Functions
are public by default; Modal proxy auth rejects unauthorized calls before
starting a container. Never substitute the CLI API token for a Proxy Token.
[Modal proxy auth](https://modal.com/docs/guide/webhook-proxy-auth),
[private endpoint example](https://modal.com/docs/examples/basic_web)

Use one container and a GPU-exclusive voice lock. Permit a separate readiness
control request without admitting another user stream. Modal supports RFC6455
WebSockets, with a 2-MiB platform message limit and no per-message deflate;
our narrower limits still apply. Retain operator leases and no automatic
cold-start path. A persistent warm pool requires a separately chosen spending
policy and measured readiness; it is outside this bounded audition.
[Modal WebSocket hosting](https://modal.com/docs/guide/webhooks)
