# Customer comparison and actual screen capture

Use only a confirmed generated fictional runtime. The private JSON configuration
contains `base_url`, `profile`, `code`, `generated_only: true`, and `runtime`
(exact application/image/source identity and execution mode). Keep it under
`private/`. Browser configuration may specify `channel: "msedge"` if needed.

Create fresh output paths; the recorder refuses to overwrite a capture directory.
The maintained private binding describes the isolated runtime and generated
fictional profile. The live provider is explicit direct OpenRouter
`google/gemini-3.1-flash-lite`; the earlier slow FLUJO/Codex provider run is a
separate execution profile.

```powershell
python -X utf8 scripts/submission/measure_customer.py --config-private private/rc-runtime-20261004/measurement.json --output NEW-comparison.json --cases es-selected,pt-selected,pt-ambiguous --selected-reference txn_3c58c0b66b4802b22b323ca5
node scripts/submission/record_customer.mjs private/rc-runtime-20261004/measurement.json NEW-story-directory docs/submission/measurements/team-story-final/recipe.json
node scripts/submission/record_customer.mjs private/rc-runtime-20261004/measurement.json NEW-pt-directory docs/submission/measurements/portuguese-final/recipe.json
```

The saved recipe follows the maintained fictional fixture's Nébula Market
purchase. For another generated fixture, replace its observed merchant button
and selected reference. The existing receipt is read, never confirmed again.
Recipe and scenario questions are fictional and contain no credentials.

The harness provides six AI-authored cases: selected charge explanation,
ambiguity, and an explicit request for human help in both ES and PT. The final
bounded comparison uses three: selected ES, selected PT, and ambiguous PT.
The ES row reuses the exact recorded fixed question rather than paying for a
duplicate call; the two PT rows each use a fresh authenticated session.
The deterministic baseline uses the same
selected display facts and existing repository copy: explain the selection,
suggest human help when requested, otherwise ask date/amount. It executes no
model, bank action, or follow-up. Its CPU time is not equivalent to network
response latency. No historical production baseline or improvement percentage
is implied. Independent human usefulness/language/grounding judgment is pending.

The browser recorder follows real rendered controls without replacing requests
or injecting responses. Public artifacts contain fictional visible text,
timed HTTP statuses, PNG screenshots and a WebM. Its private recipe specifies
rendered `click`, `fill`, `wait`, `snapshot`, `pause`, and `reload` steps. Login
uses the browser context's real HTTP session before the page opens, so the
recording does not show the access code.

Final measured evidence:

- `final-comparison-counted.{json,md}` preserves the original n=3: HTTP and
  exact history 3/3, agent-screened useful 2/3, language correct 3/3; 7.105–12.970
  seconds, median 9.338 seconds. Its Portuguese selected-facts failure is retained.
- `post-fix-pt-selected-counted.{json,md}` records one exact fresh-login retry
  after compatible selected facts were retained through query rewriting:
  18.8075 seconds, useful correct-language selected-fact display, HTTP/history
  1/1. Its visible answer is the trusted host fallback, not accepted free-form
  model generation. This n=1 stays separate from the original n=3.
- `team-story-summary.{json,md}` records one real two-model inquiry: 4.278 seconds
  from POST start to the first completed UI poll; two bounded structured model
  choices selected reviewed guidance, with trusted date/amount projected by the
  server. Actual customer helpful acknowledgment closes only that informational
  inquiry. The stored answer survives new chat, prior-chat view, and reload.
- `team-story-final/` contains the actual 242.2-second WebM, original screenshots,
  safe API traces and public recipe. Snapshot 11 holds the useful saved answer
  at 212.351 seconds; the UI owner fixed answer retention before this read-only
  reload, without repeating either worker. Initial loaded asset identity was
  not independently recorded; source-owner build hashes and the older startup
  metadata are explicitly distinguished in the summary.
- `portuguese-final/` contains a separate actual clarification clip: 11.628-second
  response, screenshot at 15.430 seconds held for 12 seconds. This timing is not
  the 7.105-second paired comparison request.
- `actual-half-hour-followup.json` records a real unchanged receipt check after
  1,800 seconds of normal clock time. It establishes one repeat, not week-long
  reliability, a refund, or a bank decision.
- `team-voice/useful-team-update.wav` and its receipt qualify a separate actual
  two-worker inquiry and useful completed speech: 4.901-second case completion,
  9.4 seconds of native audio, and one full-playback HTTP 200 acknowledgment.
  Queued/working overstatement audio is excluded, and the final guard suppresses
  it. The visual WebM is silent; its final screenshot is not current-case proof.
- `pre-fix-comparison.*`, `fast-es-first*` and `slow-story-*` preserve earlier
  failures and separate provider profiles. Failed/duplicate browser warm-ups
  are retained under private scratch; successful original story evidence remains.
- `integrated-readonly-summary.{json,md}` qualifies final isolated source
  `b6d46c1`: received JS bytes match the startup manifest, old session remains
  valid, two inquiries/suggestions survive reload, and original chat text is
  exact. It made only GET requests and verified one case/one receipt in the
  ledger. Its current action status was `none` and followups empty; historical
  folio text is not fresh receipt proof. Raw screenshot 05's premature label is
  preserved and annotated. Earlier slow opt-in session authority was not copied.

To regenerate the compact summaries from the existing actual calls:

```powershell
python -X utf8 scripts/submission/summarize_final.py docs/submission/measurements/team-story-final/capture.json docs/submission/measurements/final-comparison-pt.json --output-directory docs/submission/measurements --observations-private private/rc-runtime-20261004/observations.jsonl
python -X utf8 scripts/submission/summarize_comparison.py docs/submission/measurements/final-comparison.json --observations-private private/rc-runtime-20261004/observations.jsonl --output-prefix docs/submission/measurements/final-comparison-counted
python -X utf8 scripts/submission/summarize_comparison.py docs/submission/measurements/post-fix-pt-selected.json --observations-private private/rc-runtime-20261004/observations.jsonl --output-prefix docs/submission/measurements/post-fix-pt-selected-counted
python -X utf8 scripts/submission/summarize_readonly.py docs/submission/measurements/integrated-readonly-final/capture.json --original-capture docs/submission/measurements/team-story-final/capture.json --bank-ledger-private private/rc-runtime-20261004/instance/bank.sqlite3 --output-prefix docs/submission/measurements/integrated-readonly-summary
```

Only use exclusive serialized measurement windows to attribute actual model
and tool counts. Bank Service wrappers may contain nested read-back operations;
they are not Banking MCP network transport counts. Model transport completion
does not establish semantic acceptance. Costs remain null unless observed.
A successful HTTP request, local
receipt, or persisted intake never establishes a resolved dispute or refund.
The story's exact assistant wording comes from `capture.json`, not a planned
script. Record follow-up only once its actual UI/API is installed.
