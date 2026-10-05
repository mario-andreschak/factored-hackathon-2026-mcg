# Initial spoken-role selection: integration review

Reviewed 1 October 2026. This is a default-off source prototype, with no enabled
public route or browser integration. It does not replace the validated fixed
operator-role mode. Its measured baseline remains 93 units/one optional skip,
64 browser passes/one optional skip and image
`64cdc922b49c2e681e09530770e3b68494d4cb06dd11f034f5d22066d499b46b`.
Those receipts do not qualify this new flow. Bank narration remains disabled.

## Actual three-role prerequisite

The isolated fixed-role run at
`avatar/.local/personaplex-fixed-roles/20261001-062557-1790853957136559400/`
completed with one model load, **57.032 seconds load/initial prompt**, 900 native
frames/72 audio-clock seconds and three independent 300-frame conversations.
Exact production prompts were retained; two deliberate between-conversation
resets occurred, with zero in-conversation reset, prompt update or forced token.
It was not wall-clock paced. Three independent ASR requests completed.

| Form | Observed evidence | Remaining conclusion |
| --- | --- | --- |
| Moss | Native caption includes Moss; ASR hears “I must” rather than a name. Response addresses the anxious request. | Missing ASR name recognition is not contradictory identity. Human calm/slow/brief style remains unqualified. |
| Orbit | No self-name in the sample; response addresses planning. | No wrong name observed. Analytical style and usefulness need listening/review. |
| Spark | No self-name in the sample; response addresses the energetic request. | No wrong name observed. Energetic rhythm and interruption behavior need listening/review. |

The user did not require self-naming. The name-matcher's absence is not a style
failure or misidentity proof, and relevant responses do not establish three
qualified conversational styles. Unlike the combined adaptive-prompt trial,
these samples show no contradictory name. Neither run proves automatic routing,
first-problem continuity or frontend/native form agreement.

## Private staged contract

The worker's explicit `PERSONAPLEX_INITIAL_MODE=1` loads/warms weights and NATM1
without a role. `/tmp/personaplex-warm` proves WARM; native READY remains absent.
Default fixed mode retains its v1 lease and five-key health contract. The staged
launcher uses explicit `--initial-role` and a private v2 lease; it starts no GPU
through the browser. Current production relay rejects v2. The source owners
report 33 focused launcher and 28 focused worker passes; no staged native/provider/
browser run is qualified. See
[staged operator contract](PERSONAPLEX_INITIAL_LAUNCH.md).

The authenticated private health shape has exactly ten keys:
`{ready,protocol,avatar,sourceRevision,modelRevision,selection,phase,voice,promptHash,selectionId}`.
`selection` is `initial`, voice is NATM1, and phase progresses
`warm → priming → primed → streaming → closed`. Warm has null role/hash/ID;
priming binds role/ID; primed/streaming bind the exact static production prompt
hash. A bound, unadmitted `primed` worker legitimately reports `ready:false` below
the 120-second new-stream floor; the launcher treats that as unavailable rather
than malformed metadata. An admitted `streaming` owner retains its original
expiry. The launcher freezes that tuple monotonically and writes heartbeats.

Private `POST /api/prime` accepts only unique-key JSON
`{selectionId,avatar}`, at most 512 bytes. Role is a three-value enum; opaque ID
matches `[A-Za-z0-9_-]{1,128}`. Modal-injected epoch authentication is required.
One synchronous WARM→PRIMING reservation precedes GPU work. A 15-second prime
needs at least 135 lifetime seconds at admission and 120 after priming. Failure,
cancellation or disconnect consumes selection and closes the worker; late GPU
completion cannot publish ready or authorize reuse. Lifetime 600/warmup 240 remain
absolute. No arbitrary prompt, text result, initial audio or role-switch API is
implemented by this contract.

## Public integration requirements

The future Node intake must reserve one initial owner before paid recognition,
bound to avatar session, fresh private lease epoch and server-generated selection
ID. Keep Origin/Host checks, remote operator gate, fixed destination, body/rate/
capacity limits and cancellation; bank login is unnecessary for initial voice.
Only bounded validated audio reaches the fixed recognizer. The server derives
one approved role from recognized text; browser worker URLs, lease credentials,
prompt hashes, customer IDs and result strings are rejected. No request may
provision a GPU or overwrite the launcher's lease.

One utterance ID must survive classification/history/optional task admission
without duplicate ASR, transcript or inquiry. Abandonment, mute, identity change,
lease change and deadline invalidate late work. A successful private prime must
be matched to the same frozen role/ID/hash in the lease; allow its bounded
heartbeat promotion delay, without retrying prime. Keep warm listening distinct
from an actually ready/connected native conversation.

## Finite first-utterance replay proposal

Role-only prime does **not** deliver the first problem to the native model. The
reviewed proposal supplies that context as the user's original audio after
actual native READY. It is not implemented or qualified by the staged worker
contract, and does not introduce a native text/tool-result API.

Use one existing microphone/worklet for `capture → preparing → replay → live`.
Capture a completed utterance, bounded to 12 seconds of 24-kHz PCM including
200-ms pre-roll and endpoint silence. Reject a still-active capped utterance;
do not classify or replay a silently truncated problem. The current live capture
handler returns before READY and the existing observer permits 25 seconds, so
initial intake needs its own bounded phase. Show listening only during capture,
then preparation while ASR and the one-shot static prime finish.

After the authenticated stream's actual READY, a finite scheduler sends one
1920-sample/80-ms PCM frame at normal 1x speed, zero-padding only the final partial
frame. Native output plays at normal speed throughout. Real microphone samples
continue meter/VAD and bounded pre-roll, but quiet live samples are not queued
behind replay. Recorded bytes bypass live VAD, the observer and user-turn/task
callbacks. At the final frame, switch to current real microphone input without
replaying the intake again or resetting the model cache.

NEW real speech during preparation cancels the old intake and suppresses its
ASR/history/intent. Abort its request and erase local audio; burn a reservation
whose prime may have started. During replay, NEW speech cancels all unsent replay
frames, clears playback, and uses the existing interrupt/ACK generation fence
before genuine live continuation. Playback/captions remain held until matching
ACK **and genuine new-user quiet**. The current worker ACK does not purge queued
PCM: up to the existing 480-ms bound may still enter the native cache. This is
bounded retained context, not a promise of semantic cancellation. Normal-1x
pacing avoids a growing catch-up queue, but that residual behavior still needs
actual acoustic interruption qualification.

Deliver initial ASR to the actual Game once, only after READY, with the frozen
role and utterance ID. Its origin must mean history/scene-only: the current
`observedTranscript` also admits the optional read bridge, which would invoke
task hold and silence replay. Keep first-intake bank admission disabled until
its joined flow is separately qualified; replay must never be offered to ASR
again. Waiting until replay ends is not proof that free native audio avoided an
invented bank answer. Any later explicit initial-read mode needs its own early
output hold and cancellation boundary, separate from transcript delivery. It
would intentionally withhold speech while work runs, and cannot claim a voiced
backend interaction. Only new real microphone turns can release an existing
task hold; ordinary opted-in observer behavior resumes after LIVE.

## Timing and ownership gates

Reserve for the full pipeline. The proposed server prototype uses 195 seconds
at completed-capture admission: `ASR 45s + prime 15s + lease promotion 3s + replay
12s + live-use floor 120s`. Its pre-capture capability needs 207 seconds to cover
another 12 seconds of capture. These proposed budgets leave no WebSocket/READY
margin; recheck usable remaining time before stream admission and READY, with a
bounded connection allowance, rather than relying only on the private
135-second prime floor. Neither rule is current production qualification.
Previous 0.999-second public ASR and 57.032-second fixed initialization are single
observations, not initial-role latency.

Use a monotonic finite scheduler with an explicit lateness limit. A delayed
timer must not burst many frames, silently skip original speech, or keep replay
alive after cancellation. Reset input resampler carry and collector/VAD state
at phase changes; retain only the intended current-microphone pre-roll. Mute,
manual stop, hidden/closed page, identity change, lease expiry, disconnect and
late asynchronous work must erase intake audio and cancel its scheduler. Mute
must stop recorded speech too, not merely disable the physical track.

The server's opaque owner binds session, private lease epoch, selection ID,
audio hash and static role hash. Revalidate that binding at prime response,
heartbeat promotion and one-use claim; no stale response can reconnect or
deliver old text. A request abort can detach only after response delivery is
acknowledged, while session and absolute worker deadline stay enforced. The
client must never obtain private worker addresses or credentials.

## Focused acceptance boundaries

Before any paid qualification, cover these deterministic boundaries:

- One microphone/worklet; 12-second/200-ms bounds; exact first and last samples;
  44.1/48-kHz resampling; incomplete/capped capture rejected.
- One ASR, choice, prime, native admission and history ID. NEW speech/mute/abort
  before and during prime cannot deliver old text or reclaim its consumed owner.
- Exactly one finite PCM writer: 80-ms replay cadence, padded tail, no live
  silence interleaving, no delayed burst, no packet after cancellation, and a
  bounded transition to current live samples.
- Replay content cannot trigger VAD interruption, observer ASR, duplicate
  history, native read admission or task-hold release. Actual NEW speech can;
  test it on the first frame, last frame and during a pending ACK.
- Output at normal speed remains clock-contiguous; stale-generation audio and
  captions are withheld through ACK plus genuine quiet. Disconnect disposes
  tracks, worklet, context, replay timer and all in-memory audio.
- Available capacity just above/below capture, prime, claim and READY floors;
  heartbeat delay, expired ticket, changed lease/session and exact absolute expiry.

Then measure public nonbank speech end-to-end: capture-end, admission, ASR,
frozen choice, prime, lease promotion, READY, first output and replay completion.
Listen for response continuity, usable delay, matching visible/native form and
the three intended styles, including actual speech overlapping replay output.
Physical microphone/AEC and a joined owned inquiry remain separate gates. Fixed
mode stays available until this source prototype earns its own acceptance.
