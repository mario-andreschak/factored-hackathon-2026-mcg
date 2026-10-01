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
| Ambiguous and unsupported | Multiple candidates require selection; ambiguous pesos require currency; balance/history unsupported cases do not fabricate evidence. |
| Human and emergency | A human request in the original message survives a false intent label. Active current misuse escalates; a past unfamiliar charge alone does not imply emergency. |
| Model failure | Timeout or malformed classification fails closed. An invented success or receipt is rejected, retried once, then safely replaced. |
| Ownership | Authentication and third-party guards precede private reads, including when the model suppresses the foreign-reference signal. Stored pending state never crosses customers or conversations. |
| Consent and replay | Chat `sí/sim`, a model `CONFIRMED`, and selection never authorize intake. Replayed turns or uncertain outcomes never attempt another write. |
| Receipt uncertainty | An attempted action without verified readback retains `ACTION_UNVERIFIED`, including after a verified human-review receipt. |
| Policy precedence | Authentication/ownership beat old success; age/status beat new intake; an exact existing case beats risk; missing coverage never means low risk. |

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

The first joined local run on October 1, 2026 at 03:58 UTC collected 81 cases:
68 passed and 13 failed against the supervisor's then-mutable integration
source. This checkpoint deliberately retains the normative assertions. The
remaining findings include receipt proof ingestion, ordinary person/spouse
requests missed by local guards, complaint selection, and distinguishing a
candidate-list hash from its underlying snapshot ID. A test port missing the
real adapter's optional `correction` keyword was corrected after this run.

The initial Windows test environment lacked `tzdata`; installing it in the
isolated acceptance environment resolved that environment failure. The local
test environment uses Python 3.13, pytest 9.1.1, PyYAML 6.0.3, Jinja2 3.1.6,
and tzdata 2026.4. No provider, MCP transport, S3, or bank write is invoked by
this suite. Subsequent source fixes require a new joined run before calling
this checkpoint accepted.

The default repository bank port intentionally has no complete historical
complaint or dispute-risk adapter. Its safe `unsupported_history` error and
`HANDOFF/missing_evidence` behavior are tested, not described as full banking
coverage. Injected complete fictional observations exercise the other
canonical motor paths independently of that deployment limitation.
