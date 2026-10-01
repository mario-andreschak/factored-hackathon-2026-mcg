# Gloria development acceptance

These independently authored development cases execute the application-owned
`gloria_workflow` orchestration and deterministic motor. They use newly invented
ES/PT messages and fictional records, not the frozen router evaluation files or
organizer data. A scripted language port and an observed, read-only bank port
make classification errors, timeouts, malformed outputs, stale evidence, and
receipt uncertainty reproducible.

Run from the repository root after the Gloria implementation is integrated:

```powershell
python -m pytest tests/test_gloria_acceptance.py -q
```

## Contract-derived cases

| Area | Required observation |
| --- | --- |
| Normal ES/PT | An eligible, owned dispute requests the portal control; inquiry reports evidence; no chat action write. |
| Ambiguous and unsupported | Multiple candidates require selection; ambiguous pesos require currency; an explicit currency reply retains the amount; an unrelated balance request changes scope; unsupported history does not fabricate evidence. |
| Human and emergency | A human request in the original message survives a false intent label. Active current misuse escalates; a past unfamiliar charge alone does not imply emergency. |
| Model failure | Timeout or malformed classification fails closed. An invented success or receipt is rejected, retried once, then safely replaced. |
| Ownership | Authentication and third-party guards precede private reads, including when the model suppresses the foreign-reference signal. Stored pending state never crosses customers or conversations. |
| Consent and replay | Chat `sí/sim`, a model `CONFIRMED`, and selection never authorize intake. Replayed turns or uncertain outcomes never attempt another write; an expired session cannot replay private evidence. |
| Receipt uncertainty | An attempted action without verified readback retains `ACTION_UNVERIFIED`, including after a verified human-review receipt. Both native host envelopes and the agreed canonical test projection are exercised. |
| Policy precedence | Authentication/ownership beat old success; age/status beat new intake; an exact existing case beats risk; missing coverage never means low risk. A risk report must cover exactly 24 hours and have a nonfuture endpoint within the configured freshness bound. |

## Evidence scope

The suite tests actual local orchestration and pure policy against injected ports.
It does not measure provider understanding, accuracy on a held-out benchmark,
native FLUJO execution isolation, a deployed joined customer path, or real bank
actions. Scripted classifications are inputs to boundary tests, not evidence of
learned-component ES/PT quality. Language assertions check the declared output
language and fallback behavior, not full linguistic quality.

The generic FLUJO main branch, shared worker, provider/model bindings, restricted
records, and frozen evaluation data are untouched. Production authorization and
the protected banking MCP remain separate from the language workflow.

## Execution evidence

Latest independent local run: **90 passed, 1 failed, 0 skipped in 2.39 seconds**,
September 30, 2026 at 23:16 Bogotá (October 1 at 04:16 UTC). The tests were
executed against the actual supervisor integration package with the committed
acceptance file at `a8f5bcd9b1849605d8ed12ce9c41f4edd1904fd9`.

The remaining failure is a real topic-switch guard: after a dispute asks for
currency, “Ahora quiero saber mi saldo en USD” with model intent `OOD` wrongly
supplies the old dispute's missing currency and returns `CONFIRM_ACTION`.
It must start a new request and return `OUT_OF_SCOPE` without transaction
search. The assertion remains enabled. All other 90 cases, including the four
freshness boundaries and cached-success receipt revalidation, pass.

The integration checkout's Git HEAD was
`367bc5c948319bd58d47c768688b4477fd30acfc`; runtime and host work were still
uncommitted there. Therefore that HEAD alone does **not** identify the tested
source. The worker's durable `acceptance-status.json` records SHA256 maps of
application modules, canonical prompts, contracts, policy configuration, and
the relevant frontend/MCP action boundaries both before and after execution.
Those maps were identical throughout the run. Their sorted JSON-map SHA256 is
`b6a64e09a5e7bbe9733b26bf9f3e9cb3c8bf22f3caa429667bd3c37b09a0c715`.

An earlier 83-case checkpoint passed before the later freshness/continuity
freeze. It is retained as historical development evidence, not substituted
for this latest run.

The suite exposed status-field incompatibility, missing selection snapshots,
adapter input mismatch, absent bounded repairs and language notices, receipt
proof handling, ordinary person/spouse guards, complaint selection, and a
candidate-hash/snapshot-ID mismatch. The owners corrected those source issues;
the contract assertions were preserved. The observed test port was adjusted
to accept the real adapter's optional `correction` argument.

The initial Windows test environment lacked `tzdata`; installing it in the
isolated acceptance environment resolved that environment failure. The local
test environment uses Python 3.13, pytest 9.1.1, PyYAML 6.0.3, Jinja2 3.1.6,
and tzdata 2026.4. No provider, MCP transport, S3, or bank write is invoked by
this suite. A later source change or deployment needs its own joined run;
these passing results do not establish a deployed customer path.

The default repository bank port intentionally has no complete historical
complaint or dispute-risk adapter. Its safe `unsupported_history` error and
`HANDOFF/missing_evidence` behavior are tested, not described as full banking
coverage. Injected complete fictional observations exercise the other
canonical motor paths independently of that deployment limitation.

The supervisor's configured-model qualifier is separate evidence. Its four
synthetic mode/language cases are a development smoke check; they neither
establish held-out ES/PT accuracy nor verify action authorization or a saved
FLUJO graph. Extraction must be assessed from the captured intent/slots and
the expected source facts. Unknown provider cost must remain unknown. A
qualifier report also needs a source capture made before execution and a
matching capture afterward to identify the exact code measured.
