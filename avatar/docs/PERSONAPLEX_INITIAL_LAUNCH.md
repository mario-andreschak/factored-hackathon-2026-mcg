# Operator launcher for one initial role

`experiments/personaplex_browser.py --initial-role` is an explicit source
prototype for warming a worker before its one initial character is selected.
It has not been used to refresh an image or dispatch a cloud worker. The current
fixed-role browser qualification remains separate. Without this flag, the
launcher retains its existing fixed role, version-1 lease, readiness marker and
exact fixed health contract.

## Warm weights are distinct from ready voice

The opt-in sets only `PERSONAPLEX_INITIAL_MODE=1` and probes
`/tmp/personaplex-warm`. The existing `/tmp/personaplex-ready` marker must remain
absent until an authenticated, successful role prime has completed. Both modes
retain the 240-second startup wait and 600-second absolute worker/Sandbox
lifetime. No browser request can build the image or launch another GPU.

The staged worker's private authenticated health response contains exactly:

```json
{
  "ready": false,
  "protocol": "personaplex-pcm-v1",
  "avatar": null,
  "sourceRevision": "3428dfd95309a7f3c84fd93259ded0f810d1ff91",
  "modelRevision": "fdaf4090a61cb315c138a1faee287ffd6c716309",
  "selection": "initial",
  "phase": "warm",
  "voice": "NATM1.pt",
  "promptHash": null,
  "selectionId": null
}
```

`warm` has no selected role, ID or prompt hash. `priming` has the admitted enum
and opaque selection ID, while readiness remains false and the prompt hash is
null. `primed` and `streaming` require the SHA256 of the exact static production
prompt for that role. A primed worker may become unready when too little lifetime
remains for a new stream; this ends availability without a metadata-conflict
claim. An admitted streaming owner retains the original expiry. `closed` requires readiness false and
preserves any admitted binding. A pre-warm `new` state cannot publish a lease.

The launcher publishes an operator-only version-2 lease containing those fields,
its fixed epoch, pinned revisions, Connect Token, fixed provider origin and
original timestamps. It refuses extra health fields, another voice, an invalid
selection ID, wrong prompt hash, readiness inconsistent with its phase, regressing phase or any change
to an admitted avatar/selection/prompt binding. It allows a heartbeat to skip
directly from warm to primed if selection completed between polls. Unknown or
legacy fixed health cannot satisfy opt-in staged readiness.

The first console event says `warm` and `nativeReady:false`; it contains neither
provider origin nor Connect Token nor the later selection ID. A warm lease does
not qualify native voice readiness, and its presence does not enable production
admission by itself. The existing version-1-only relay deliberately rejects it
until a separately reviewed staged API supports the new contract.

## One private prime, one immutable conversation

The worker contract provides authenticated `POST /api/prime` with only
`{selectionId, avatar}`, at most 512 UTF8 bytes. It accepts a static role enum once
while warm, on the sole GPU owner thread. Its opaque ID binds and deduplicates an
admission; it supplies no authority. Successful prime completes within 15 seconds
and requires at least 135 seconds left at admission and 120 seconds afterward.
Failed admitted prime closes the worker rather than allowing another selection.
The native conversation then keeps the same prompt/cache. Bank facts, tool
results, arbitrary prompts and live persona updates are not accepted.

The launcher never calls that route or chooses a role. It only checks health and
publishes a private heartbeat every two seconds. It remains the sole lease-file
writer. A future server that calls `/api/prime` must verify the returned binding
and account for heartbeat promotion lag; writing a competing lease would risk
rolling back state. The server must independently retain origin, session, access
gate, bounded initial-audio admission and one-use ticket controls. First-utterance
classification, context preservation and response latency require their own
review and qualification before activation.

Fixed provider origin, Connect Token authentication, loopback-only outbound CIDR,
source COPY refresh, no runtime HF secret/download, no public raw ports, one
worker, no retries and shutdown controls remain unchanged. Phase conflict or
health loss revokes the owned lease and terminates the same worker. Stop
acknowledgment remains distinct from observed exit. A warm-only run never claims
that a conversation was primed or that browser acceptance passed.

## Local evidence

Thirty-three launcher checks pass, including eleven staged cases. They cover inert
planning, exact health proof, one-way binding, warm-to-primed private lease
publication, fixed-mode compatibility, conflicting state cleanup, bounded
authenticated health fetch, warm-only expiry and explicit CLI dispatch options.
The actual worker state health also passes through the launcher validator at
every phase without a translated hash or fabricated role binding.
All new lifecycle tests use an injected local fake SDK; no cloud/token request,
GPU/model inference or provider speech call occurs.

```powershell
python avatar/experiments/personaplex_browser.py --plan --initial-role
python -m unittest discover -s avatar/experiments -p test_personaplex_browser.py -v
```

`--initial-role` cannot be combined with cache-building/source-refresh flags or
an alternate fixed `--avatar`. An eventual operator execution would require a
separately reviewed refreshed worker image and use `--execute --initial-role`.
This document is source preparation, not a request or record of such execution.
