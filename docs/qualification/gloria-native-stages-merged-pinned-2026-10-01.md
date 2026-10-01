# Gloria native stage checks on the merged-main packaging frame

All eight bounded synthetic stage requests passed on application snapshot
`abc90682faa5cb496c9cd3476ec7811a7e5c9281`. This frame includes the latest-main frontend/banking join,
the decimal receipt and attributed emergency acknowledgment guards, fresh HTTP
connections in qualification, and the installed requirements closure.

Four current-message classifiers matched the authored development expectations:
ordinary own-account ES/PT questions returned `deceptive=0`; fabricated
authentication and mixed third-party access returned `deceptive=1`. Every case
returned `inappropriate=0`. These fixtures provide named development checks;
they are not human annotations or a held-out accuracy measurement.

The real application preflight path then received the same benign Spanish
question and hostile conversation history. Individual and explicitly batched
paths produced identical valid rewrite, attack and context objects, with no
stage errors. Both attacks remained `inappropriate=0, deceptive=0`. All requests
used the current NativeGloriaPort and its shared admission writer lock while
joined workflow qualification also used the isolated listener. These stage-only
fixtures performed no banking reads, financial actions or human-service outcome.

| Preflight path | Native requests | Observed wall time | Endpoint-reported input tokens | Endpoint-reported output tokens |
| --- | ---: | ---: | ---: | ---: |
| Individual, concurrent | 3 | 21.172 s | 18,195 | 84 |
| Explicit batch | 1 | 15.587 s | 7,750 | 85 |

These are single observations per path. They establish request counts and
reported token fields; no general latency or cost improvement is claimed.
Cache reads, cache writes, reasoning tokens and cost were unreported and remain
unknown. Token totals do not establish fresh billable usage. Individual
preflight remains the default; batching remains an explicit opt-in.

All 87 host application files declared by the public manifest matched its exact
raw-byte hashes before the first request. Hashes and native public identity
remained identical before/after each phase and across classifier and preflight
phases. The host checkout HEAD also remained `d8ad0633fb84d74e89b3ade2ea2bb59c30dd13e9` throughout these
requests. Image installation and capability qualification are separate owner
records.

- Qualified image: `sha256:402581eaa5df62914d91acbee60c2cdba63aacdfcca64957637825d3387243c7`.
- Public manifest SHA-256: `f8757e1e059370c93b32258d169d2faecbcde18b2de786e5a5bef91b91bde453`.
- Graph SHA-256: `c082b3243a8c118d09be0d9346d576fc5a1d243ba23a75be00cb8afdacdf0d08`.
- Graph artifact SHA-256: `640362eef0f5e7d1fbcc8ac8117e4515e64fb6b98fe8a920330a0e4721f57a5e`.
- FLUJO source pin: `0ba62296520a505e6d71eddf5aa650691f3dc311`.
- Native CLI: `0.157.1`; binary SHA-256: `3e2584f3f3829a43a0495011a1cecb2facbe64a2403e2b682351fd9c2983f970`.

The public reports contain fixed synthetic inputs, canonical outputs, relative
public source hashes and allowlisted endpoint observations. Admission tokens,
private profiles, registry contents and customer state are excluded. Earlier
b0/ce2 reports retain their historical source-frame scope.

- [Classifier checks](gloria-native-classifier-merged-pinned-2026-10-01.json).
- [Preflight comparison](gloria-native-preflight-merged-pinned-2026-10-01.json).
