# Measured release evidence

## Existing infrastructure capacity and collaboration

The FLUJO/inference foundation has already been tested beyond the two-reviewer
customer film: **300/300 correct requests at client parallelism 300 through FLUJO**,
400/400 direct inference HTTP successes (399 correct), real filesystem tools and
collaboration runs with 18 Fly sandboxes live together. See
[the infrastructure report](INFRASTRUCTURE_CAPACITY.md) and
[aggregate receipt](infrastructure-capacity.json), rechecked against original
per-request records without another provider call.

A further paid fleet/load run for the submission video was skipped because of
budget constraints. That decision is distinct from the failed customer attempt
below. Successful load tests, sandbox exercises and customer recordings retain
their original workloads and deployment identities.

## October 5: new deployed fleet attempt is incomplete

The single authorized customer capture returned correct bank facts and complete foreground speech, but **failed the new fleet customer acceptance**. Its original root run failed on the first model call with HTTP404 because the Modal workspace was disabled. The case ends in `needs_attention`, with no reviewed suggestions or next-check time. There are zero delegated team leads, zero local staff and zero completed root-review children. Ten ready/configured machines do not establish 100 native executions. The original goal remains active and its root worker ready; the failed run is not a terminal goal or a cleanup receipt. No case was resubmitted.

[Actual receipt](fleet-customer-attempt/receipt.json), [foreground audio](fleet-customer-attempt/foreground.wav) and [integrated voice screenshot](fleet-customer-attempt/foreground.png) preserve this partial result. Deployed app source is `a5e48f09`, image `35903f9a…6dc93`; native source is `67d21ad3`, controller `290dd6a7`. Full pins and served UI hashes are in the receipt. Recorder merge `624941ff` and newer generic source merge `0be972ac` are separate from these deployed pins. The actual failed native conversation contains its execution snapshot; that proves snapshot presence, not reviewed completion.

| Customer outcome | Frozen Listen capture | New fleet capture, n=1 |
| --- | --- | --- |
| Useful information | Saved bank facts; spoken merchant/receipt advice, with folio/caveat omissions documented | Fresh HTTP200 reply correctly states Nébula Market, 2026-10-02, 4280.75 MXN and Approved; no reviewed team guidance |
| Native speech and full ACK | 8.2 seconds; one exact full ACK, matching its one-turn scope | 8.85 seconds of reassurance; one full HTTP200 ACK for 212,400 samples at 24 kHz; planned second guidance turn absent |
| Native request → speaking / full ACK | 0.988 / 9.577 seconds, saved-result mode | 4.149 / 12.952 seconds, microphone mode; different input/output boundary |
| Foreground and background | No fresh foreground conversation or team work | Root attempt lasts 5.981 seconds and fails before audible speech. Request interval overlaps nominally by 1.321 seconds; running work during audible speech unqualified |
| Context after reload | Exact bank reply and completed suggestions retained; no duplicate speech | Reload not reached; three original inquiries remain visible in final normal poll |
| Follow-up | Pre-existing awaiting-customer state retained; no new follow-up during recording | No completion or due time; scheduled/executed 30-minute follow-up unqualified, observer not run |
| Full 10×10 execution | Outside scope | 0 of 100 qualified; one failed root excluded from target, no native tool calls or board entries |

The bank-facts question and four displayed facts match the older saved reply. The inquiry questions differ, and saved-result speech differs from microphone reassurance. These are descriptive outcomes, **not a causal speedup comparison**. Historical n=3 language results and post-fix n=1 remain at their original scope. Total provider completions/cost are not independently counted by browser request counts.

Actual caption: “Despacio, con calma, aquí estoy. Todo va a ir bien, poquito a poco.” The existing fictional microphone fixture was reused; recognized text contains “Chankilo” and “Whisper a Hondo”. Four browser partial-ASR requests are observed. Physical microphone input is unqualified. No bank action, resolution or history reset was requested.

Raw recorder `completed:false` / exit 1 follows the required-result wait expiring. Total time including browser/video finalization was 324.517 seconds against a requested 300-second observation budget. Original UUID/case/goal/run/native joins, the logical request digest and the distinct facts/binding digest were checked offline in UTF-8. Cookies, original IDs, registry/SQL/debug exports, NDJSON and stacks remain private. Independent customer review agrees with the failure scope; no extra provider/control request was made. Cross-process timings use UTC wall clocks without independent calibration. Frozen films, decks, tags and historical assets remain unchanged.

## Earlier frozen evidence

The release coordinator accepted the actual required product steps in the
fixed-source same-session continuation at `9d77a75`, image `484fe8ed…`: two
complete native WAVs, two exact once-only full-playback HTTP 200 receipts, queued
informational closure during foreground speech, visible completed-worker
suggestions, and exact bank-reply history after new-chat/archive controls.
See [the current evidence and audio](intended-savia-native/README.md) and
[receipt](intended-savia-native/receipt.json). It creates no bank chat, inquiry,
workers or bank actions. The second WAV narrates the actual helpful informational
closure, not worker recommendations. Input is an existing fictional WAV through
the browser microphone control; final ASR has errors and physical microphone
capture is unqualified.

The raw recorder still exits 1: optional `response.finished` diagnostics waited
on the intentionally canceled unused ACK bodies until its 180-second cleanup
timer. Product checks completed before that wait, and the browser is closed.
This observer failure remains separate from accepted product steps. The recorder
now keeps optional finish diagnostics outside its required waits; syntax only was
checked after that edit, with no new capture or model call.

The earlier integrated Savia deployed attempt at source `4a27f0e` verified
the actual served UI bytes, Eyes controls, grounded bank-facts API reply, and one
new informational inquiry during foreground native speech. It stopped when the
native model invented an unasked balance request and triggered a second chat.
The host safely denied balance/account access. No full native WAV or playback
receipt completed, so that attempt's product acceptance remains false. The browser is
closed and no retry was performed. See
[the current failure receipt](intended-savia-bounded-attempt/summary.json).
The first fixed-source attempt also remains a failed partial recording in
[its own receipt](intended-savia-successor-bounded-attempt/summary.json); it
created the third actual inquiry and observed native speaking during its POST.
That partial overlap is separate from the complete continuation audio. The
continuation does not establish complete speech while fresh workers execute.

The table below preserves earlier local and component evidence at its original
revisions: useful selected-charge explanation, actual two-agent inquiry,
customer-marked helpful result, and context after new chat/reload. Earlier
standalone voice recordings do not qualify the corrected integrated Savia UI.
All bank data is generated fiction. Informational closure and simulated intake
do not establish a bank decision or refund.

| Observed behavior | Evidence | Scope |
| --- | --- | --- |
| Selected Spanish facts and existing receipt | `team-story-final/04-grounded-answer.png`; exact API/history in `capture.json` | Actual direct-provider reply, 9.338 seconds; correct merchant, date, amount/currency and existing simulated folio; no new intake |
| Two agents work and finish | `team-story-summary.json` | Two real structured model calls, 1.994/1.988 seconds; 4.278 seconds from POST start to first completed UI poll; seven actual events |
| Useful saved result | `team-story-final/11-saved-useful-result.png` | Compare date/amount against receipts; keep the folio; explicitly no implied bank resolution |
| Helpful acknowledgment, new chat and return | Screens 07–12 and `team-story-final/capture.json` | Eighth event closes only the informational inquiry; stored suggestions and exact previous conversation remain available |
| Portuguese clarification | `portuguese-final/01-portuguese-clarification.png` | Actual correct-language question for missing date/amount; 11.628-second response in this separate clip |
| Real automatic repeat | `actual-half-hour-followup.json` | One unchanged receipt check after 1,800 seconds of normal clock time, deduplicated visible update |
| Historical standalone voice continues during inquiry | `voice-overlap/events.json`, `receipt.json`, audio and WebM | Actual foreground audio while one bank query is pending; its honest failure is spoken afterward and acknowledged once; not corrected integrated UI acceptance |
| Historical standalone useful team result spoken once | `team-voice/useful-team-update.wav`, `receipt.json` | Separate actual two-worker case completed in 4.901 seconds; useful 9.4-second native audio and one full-playback HTTP 200 acknowledgment; not corrected integrated UI acceptance |
| Generic FLUJO MCP and planned execution | `../runtime-mcp.json` | Connected MCP, one completed manual empty-state tool call; installed half-hour schedule disabled; zero bank/model calls |
| Final isolated source replay | `integrated-readonly-summary.{json,md}` | Exact served JS bytes match `b6d46c1` startup manifest; old session, two saved inquiries and exact archived chat retained; GET only |

The original bounded comparison is **n=3**, with actual HTTP success and exact
history 3/3, agent-screened useful replies 2/3, and correct language 3/3. Latency
was 7.105–12.970 seconds, median 9.338 seconds. The Portuguese selected-charge
reply needlessly asked for facts already supplied and remains a recorded failure.
Independent human adjudication is pending. See the visible same-facts baseline
comparison in `final-comparison-counted.md` and exact replies in its JSON.

A separate **n=1 exact post-fix Portuguese retry** succeeded at useful selected
fact display: 18.8075 seconds, HTTP 200, and exact two-message history. It now
explains the selected merchant, date, amount/currency and approved status,
then asks what does not match the purchase. The visible answer is the trusted
host `selected_fallback` after the runtime's safe fallback; it is not accepted
free-form model generation. See `post-fix-pt-selected-counted.{json,md}`.
The material change retains compatible selected facts across rewritten queries;
the exact runtime source hash is recorded. This one retry is separate from the
original n=3 and does not turn it into a uniform new-source benchmark.

The deterministic baseline renders the same selected facts or asks for missing
date/amount. It uses no provider, bank action, team, handoff or follow-up. Its
local CPU time has a different boundary from actual network response time;
there is no measured speedup, population quality rate or causal improvement claim.

Actual customer and agent calls use explicit direct OpenRouter
`google/gemini-3.1-flash-lite`. The earlier slow generic FLUJO/Codex profile is
preserved separately in `slow-story-*`; generation timed out and the host gave
a guarded deterministic answer. Its useful simulated intake/follow-up proof
does not convert the timed-out generation into a successful model response.

Banking Service and ActionHost wrappers are actual shipped implementations
executing in process. Their counts can include nested receipt read-back;
they do not establish Banking MCP network transport. Provider costs remain
unknown where the provider did not report them. Voice audio is real provider
output; prerecorded/fake browser microphone input does not qualify a physical mic.

Source and replay limits are explicit. The backend startup receipt is preserved,
and initial browser asset identity was not independently captured. The UI owner
reported final asset hashes; between screens 10 and 11 it fixed saved-answer
visibility, then the same case was reloaded without repeating either agent.
The report does not claim a single uniform frozen n=3 release benchmark.
See `team-story-summary.json` and `REPLAY.md` for provenance and commands.

The final read-only replay closes the source-byte gap for the isolated release
head, without rewriting earlier recordings. It confirms one case and one
receipt retained in the simulated ledger. The action API returned `none` and
the followup list was empty in the preserved team-story context; the original
slow opt-in belonged to another session whose browser cookie was not saved.
No authority was transplanted, and historical folio wording is not counted as
a new receipt verification. These limits are in `integrated-readonly-summary.json`.

Only the completed voice result is qualified. Earlier queued/working audio
overstated progress and is excluded from media; the final guard suppresses
those automatic announcements while retaining UI progress and the unchanged
completed speech path. The guard passed focused checks without another paid
run. The joined capture's final screenshot shows an older closed inquiry;
authenticated case responses and full-playback acknowledgment establish the
new completed result. Its visual WebM contains no native audio.

No actual live human investigation, refund, bank dispute resolution, seven-day
reliability or enabled generic FLUJO recurring execution is demonstrated.
