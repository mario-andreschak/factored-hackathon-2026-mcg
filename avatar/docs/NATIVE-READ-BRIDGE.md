# Optional native-to-visible read bridge

Prepared 1 October 2026. Server capability/configuration, Game's read bridge and
durable native playback hold are implemented. Focused integration checks,
TypeScript/Vite, 93 unit passes/one optional skip, 64 browser passes/one optional
skip and final production image boundaries pass. Joined live bridge acceptance
remains a separate gate below.

The exact operator opt-in is `AVATAR_NATIVE_READ_BRIDGE=readonly`, disabled when
absent or empty. Config advertises `nativeReadBridgeAvailable: true` only when
all of the following are configured:

- `AVATAR_VOICE_PROVIDER=personaplex`.
- `AVATAR_BACKGROUND_ASR=openrouter` and the existing server-side OpenRouter key.
- A fixed `SAVIA_UPSTREAM`.
- The exact read-only bridge opt-in.

The browser receives only this boolean capability, not keys, worker URLs or
lease IDs. Capability discovery does not start a GPU, admit a microphone or
authorize a bank account. Actual recognition still requires the same avatar
session's ready native relay. Savia still requires its own authenticated owner
for the visible read workflow. No existing proxy/task route or banking authority
changes in this increment.

Compose forwards `AVATAR_BACKGROUND_ASR` and `AVATAR_NATIVE_READ_BRIDGE` with
empty defaults. This is configuration passthrough only; an operator must
separately prepare the private worker and configure a lease path accessible to
the intended runtime. There is no default lease, credential mount or browser-
triggered GPU convenience.

With the feature disabled, observed utterances continue to add user history and
intent scenery without submitting a bank question. The candidate enabled flow
allows only an explicit owned read inquiry through the existing visible
Workbench controls. The fixed native role is retained. A client playback hold
must silence native audio/captions throughout the admitted read while leaving
PCM input and the model clock continuous; user turns, mute or an interruption
ACK cannot release it while work is active. After completion, it remains held
until a genuinely later user turn finishes and the current interruption/quiet
fences are satisfied. Native conversation then resumes without receiving the
bank answer. Actual answers appear in Savia and optional subtitles,
without feeding bank facts or synthesizing result speech into PersonaPlex.

One task owner must be acquired before asynchronous work. A first sign-in can
retain one still-unadmitted inquiry only while its current login interaction is
open; fresh account proof is required before visible submission. Closing that
interaction, logout or native disconnect erases the pending inquiry. Identity
changes, duplicate/busy requests and late results retain Workbench/parent epoch
guards. Once admitted, observing the real read can finish independently of
voice cancellation or closing the computer; prior-account replies are still
withheld. No refund, dispute filing or other bank action is
enabled. Native result narration remains disabled; the permanent synthetic gate
passed continuation suppression but failed strict speech qualification.

Three new focused server cases verify exact flag parsing, all prerequisite and
provider omissions, key-free boolean projection, and unchanged denied voice/
bank admission. The selected four server suites pass **52 cases and one optional
installed-upstream skip**, with no provider/bank dispatch. The owners additionally
report **11 focused Game bridge passes**, **4 new native hold passes** and
**3 new Workbench passes**. These cover visible single submission, first-login
revalidation, erased abandoned sign-in requests, action/ambiguity rejection,
identity withholding, cancellation before admission and continued observation
after admission. The hold remains fenced through user turns, mute, privacy and
ACKs; stale completions cannot release a newer task or session.

The pre-session-policy source and image build pass TypeScript/Vite and **88 units/one optional
skip**. Image `532b0e2956b4fd43f60cc81386ac3e20e17a6941667ea821f114ea95746f5a70`
was independently checked as UID1000, read-only, all capabilities dropped,
no-new-privileges, 256 MiB and a loopback-only published port. Static page/assets/
final GLB pass; private paths return404, all six disabled voice admission routes
return503, and observer/read-bridge capability is false by default. No provider
keys, worker lease or Savia target were supplied. The exact owned container was
stopped and removed. This proves packaging/default admission, not a live joined
spoken inquiry. The final complete browser rerun passes **64 cases/one optional
real-upstream skip**, 65 total, **2.3 minutes**, as reported by the parent. It
supersedes an initial 63-pass/one-skip/one-failure run after a test-only playback
phase observation correction; production sources/image were unchanged.

The prior 84-unit/46-browser regression and image `e3ccd0b65721541622202e0f3790ab99b8412ee3a5e8147f281f4db8847b3ea0`
precede `taskHold` and this bridge. The successful native public-audio audition
also remains transport evidence; it did not use this bridge or speak a grounded
bank result. Native bank narration remains disabled.

The current 120-second new-start policy and per-message avatar-history revision
pass TypeScript/Vite, **93 units/one optional skip** and **64 browser passes/one
optional real-upstream skip**, 65 total in 2.4 minutes. Current image
`64cdc922b49c2e681e09530770e3b68494d4cb06dd11f034f5d22066d499b46b`
passes the same restricted runtime/static/private-path/default-disabled
admission boundaries and its owned container was removed. These receipts do
not enable bank narration, PersonaPlex Docker lease support or joined live owned
inquiry acceptance. A separate actual public rice-cooking request now passes
native/background-ASR/actual-Game delivery while PCM continues; it uses no Savia
or read bridge.
