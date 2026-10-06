# Verified presentation and host outcome snapshots

The current source keeps verified results consistent across presentation and
measurement. Registered Savia replies go to speech synthesis as the canonical
host script, retaining financial limits and next steps. Analytics observes the
host's saved verified result separately from the workflow's planned outcome.

## Canonical result narration

The voice layer reads every registered result through the existing TTS provider.
It preserves the whole plain-text script in bounded chunks, requires 24 kHz,
rejects fragmented container/error bodies, and records canonical assistant
history only after the exact, once-only playback acknowledgment. Native speech
continues to handle small talk and bank-request delegation.

The regressions supply a false refund, false dispute resolution, false human
pickup and omitted caveats through the former native-result route. The result
route now bypasses that completion and sends the registered host text to
`/audio/speech`. Further checks cover the last chunk, foreign/expired/consumed
results, invalid rates, failed streams, odd PCM and interruptions. They use
provider mocks and fictional data.

This verifies the requested speech script, canonical caption and acknowledgment
of returned audio bytes. It does not align the waveform with a transcript or
establish human comprehension. A clean even-length premature PCM EOF cannot be
distinguished from complete speech solely by the raw transport. Complete
narration can be longer; live speech latency and provider cost were not measured.
The earlier recorded native retellings retain their original source and scope.

## Read-only host observations

The analytics extractor joins the current saved action slot to its exact
session, owner and immutable expiry admission. It validates the existing host
projection and reports verified simulated intake, existing intake, saved handoff
request and unverified states. Recovery upgrades an outcome only after the
host has persisted its verified readback. Cancellation and revocation have
separate coverage; disagreeing copies cannot count as verified.

These are current-slot counts with observed source/time bounds. They are not
lifetime action counts or a resolution rate. Original workflow intent metrics
remain separate, and exact turn/query attribution remains unknown. HMAC
pseudonyms replace source/admission/session identities; copied metadata excludes
customer text, amounts, merchants, handles, requests and receipt identifiers.
Read-only extraction changes neither source state nor banking behavior.

The checks include three real local joined-host lifecycles: confirmation and
replay followed by revocation, cancellation followed by handoff, and a bank
commit whose uncertain saved host state becomes verified only after readback.
Other cases exercise foreign admissions, malformed evidence, BLOB fields,
conflicting copies, rebuilds, old schemas and privacy. A simulated intake proves
intake; a handoff request does not prove human pickup. Cost and card-block
lifetime analytics remain separate work.

## Qualification and reproduction

The combined affected suite passed **183 tests and 195 subtests**, with no
failures, errors or skips. After integration onto corrected main, the separate
graph/preparation gates passed **22 tests and 106 subtests**. The
[receipt](qualification.json) pins the tested and integrated sources, component
hashes and limits. Independent code review also passed 62 voice tests and 49
analytics tests; these overlapping checks are not added to the combined total.

```powershell
python -m pytest frontend/tests/test_voice.py frontend/tests/test_api.py frontend/tests/test_dispute_locale.py frontend/tests/test_action_error_locale.py tests/test_host_outcome_analytics.py tests/test_agent_analytics.py tests/test_report_customer_outcomes.py tests/test_dispute_graph.py -q
python -m pytest tests/test_dispute_graph.py::DisputeManifestFreshnessTests tests/test_synthetic_integration_contract.py::SourceGates -q
```

Use the existing frontend/dispute dependencies. The native graph compiler checks
also require the separately pinned FLUJO authoring checkout; the repository-only
freshness check runs without it. This is source qualification, not a new live
voice recording or whole-production acceptance. Deployed source and image remain
separately identified in release receipts.
