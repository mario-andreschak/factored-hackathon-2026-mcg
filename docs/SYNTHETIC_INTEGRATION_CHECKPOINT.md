# Held private synthetic API integration source

This is a separate preparation checkpoint. `contract.PREPARATION_ONLY = True`
refuses dispatch before artifact consumption, Skopeo, Docker or service startup.
No integration dispatch or runtime result is claimed by this revision. PR24's
original build/discovery evidence remains separate and contains zero banking
tool/action calls.

The first proposed checkpoint exercises real HTTP APIs through the Python
frontend, the installed FLUJO worker and its stdio Banking MCP. It does not build
the browser UI or install a browser. Browser evidence needs a separately pinned
static build and browser driver. The deterministic fixture provider must make a
real ordinary chat request that runs the real worker graph and Finish routing to
create an owned conversation. Its calls are counted separately from external
model/provider requests, which must remain zero.

## Fixed package input

| Input | Pin |
| --- | --- |
| Private repository | `mario-andreschak/factored-hackathon-2026-mcg` |
| Package reviewed head | `6ebeaf73b57e7d79c691e2e48763e2adc7928398` |
| Successful run / attempt | `36679668855` / `1` |
| Small receipts artifact | `11081194098` |
| Receipts ZIP SHA256 | `31a8ce432309d4154dc67f6a45ac83dcb6c382dc3c9fc495db20e9a8f3a84120` |
| Private OCI artifact | `11080919734` |
| OCI ZIP SHA256 | `1853f64b4a732af88880862a6b79f2d655261b9ed6eddc2e90c72562e7699202` |
| Inner OCI archive SHA256 | `ddf7cd40b2b6545ddfa458c235494789e52076747bffb52dd8ceb2b636cbd5a9` |
| Inner archive bytes | `1867014144` |
| Banking runtime source | `71ac0f020303abfd0073302a148752f0d2c9f23b` |
| FLUJO runtime source | `51ff39fc5bac84cbbb49bbd2b21b5ab89de8b14b` |

The downloader verifies repository privacy, successful exact run/head/attempt,
artifact origin/digest/expiry, ZIP inventory, every receipt, OCI index,
manifest/config, all compressed layers and uncompressed diff IDs. Expiry fails;
there is no substitute download or rebuilding of the original application.
The original base/daemon observations remain the package job's evidence.

Restoration checks the complete runtime configuration, including strict boolean
ArgsEscaped, exposed ports, healthcheck, volumes and stop signal. The OCI export
omitted the original daemon healthcheck. This harness explicitly records that
omission and makes no inherited healthcheck survival claim.

The loaded raw config digest, original daemon ID and derived image ID are
distinct records. Source copies and runtime use verified full image IDs. The
derived Dockerfile's named base context uses the validated local OCI manifest
digest (`oci-layout://<layout>@sha256:<digest>`). Before startup the harness verifies original
bank/compiled FLUJO/launcher bytes, the derived layer prefix, controlled config
changes, and all copied fixture/harness source. It then supplies a separate
read-only release file. The image contains no baked authorization marker.

## DATASET source/input pin

The DATASET contribution has **no new implementation commit**. Its original
manifest hash is `7fbd438c1b58a7bfc68132f979f0bfbd2422f289b6b849522d50b79001d9a405`.
The portable source here contains only the original manifest, generator,
source-cache JSON and exact `source/pipeline/contracts.yaml`. `contract.py` pins
all four byte hashes. The known YAML path is explicitly permitted in the future
bundle; arbitrary YAML is rejected. The original pin includes reference input,
history and blueprint hashes; those dated reference inputs are not runtime data.

The future committed bundle must include these exact four files beneath
`fixture/dataset_source/`, plus the reviewed frontend, integration provider,
deterministic provider, graph and policy template. The bundle manifest binds its
own producer commit separately from the 64-character DATASET file pin. Runtime
history also records the integration head, bundle producer head/manifest hash,
generator hash, newly generated input/history/blueprint hashes, actual snapshot
ID/fingerprint/hash, customer CSV byte hash and actual fresh ledger generation.

`dataset.generate()` can execute only after the remote release gate. It generates
into a new private directory at actual UTC, runs the pinned generator's check,
then independently verifies CSV rows, owner inventory, real anchor, closed
empty history and blueprint hashes. The fixture has three fictional owners and
seven charges, six with valid ownership. Unit receipt/HOF doubles produced by
the generator are never loaded into action state or used as runtime evidence.
PyYAML is available through the installed banking pipeline dependency closure;
the generator runs with that interpreter. No generator or pipeline was run
locally for this preparation.

## Proposed fresh phases

1. **Stock missing coverage:** no coverage row/config match, fresh action tables,
   independently read incomplete risk and public prior-24h count `null`.
   ES/PT normal prepares must yield the stock selected missing-evidence handoff,
   with default empty questions and zero intake. Status readback preserves the
   saved packet. Anonymous/foreign denials must preserve pending counts and MCP
   dispatch counts as well as case/receipt/HOF counts. General PT handoff tests
   explicit UUID retry, frozen questions, conflict and restart.
2. **Lost prepare response:** another fresh stock generation uses ES normal.
   The reviewed prepare transport verifies and consumes the actual completed
   upstream prepare, persisted pending row and selected missing-coverage HOF.
   The runner requires exactly one pending/HOF increase, zero case/receipt,
   one consumed drop and actual host UUID/action identity. Restart retains the
   consumed journal and existing session. GET status must recover the same host
   UUID, pending handle hash, conversation hash, ledger generation and saved HOF
   packet hash. The host revision may advance. No fresh POST prepare, confirmation,
   additional pending identity or HOF is allowed during recovery.
3. **Authored empty past:** a separate fresh ledger uses only
   `StateStore.attest_sandbox_coverage(start, provenance)`. ES/PT normal prepare,
   false consent rejection, true consent, independent actual receipt read,
   confirm retry, and new-host-intent existing-case readback. General handoff
   question/retry conflicts are separate from selected missing-coverage defaults.
4. **Lost confirmation response:** another fresh attested ledger uses the real
   ES normal charge. A private gate forwards and consumes exactly one real
   completed confirmation, verifies its actual new saved receipt, then drops the
   response. The runner requires one case/receipt increase, one confirmation
   dispatch, one consumed correlated marker and `forwarded_faults +1`. Status
   recovery and restart must read the same receipt without another confirmation.
   Logout then denies further confirmation without pending/MCP dispatch changes.

The browser's prepare UUID does not choose the host idempotency key. The frontend
ignores it and mints a trusted UUID before persisting intent. An unresolved second
prepare returns409; status recovery retains its pending handle. A prepare after
a terminal result is a new host identity. The lost-prepare probe must
correlate the observed host UUID with actual persisted state and recover through
the reviewed fault/status path. Its actual provider/observer adapter still needs
source review; fresh repeated POSTs are not retry proof.

## Coverage initialization contract

The provider must finish data generation/build validation before any service
starts. `fixture_coverage.initialize()` resolves scoped paths, rejects lexical
traversal and parent links, and atomically reserves a fresh0700 setup directory
before creating the stock StateStore. Failed/reserved directories cannot be
reused. The provider must have no frontend/worker/MCP writer active during this
exclusive setup.

Ownership is derived from verified generated customer CSV bytes and compared
with actual `Snapshot` customers; the Snapshot constructor validates serving
inventory, lineage, quality and ownership. The manifest must be `snapshot.json`.
Its source object inventory must match only the three generated CSV object keys,
actual byte lengths and stock local SHA256 ETags; the stock fingerprint must
agree. Matching only owner IDs does not authorize another build. All nine action/auth/coverage tables
must initially be empty. The harness hashes an explicit zero-event gap from the
generator's real anchor to the setup close, bound to the fresh64hex generation.
The authored artifact is written as exact canonical JSON bytes, so the provenance
suffix equals the SHA256 of the actual immutable file. It checks
emptiness/generation again before the supported API. Read-only readback
requires the stock real `attested_at` to equal the recorded close at the stock
integer-second precision, the same generation/start/provenance digest and empty
action tables. A second-boundary crossing fails and requires a new isolated
setup; no timestamps are changed. The subsequent private readback receipt binds
the history file and records actual readback time. The provider must configure
the exact stored coverage start. Coverage is an authored fictional past interval,
not observed25h operation, customer history or bank evidence.

## Pending exact review and provider contract

`dependencies.pending.json` identifies available file pins and unresolved slots.
The corrected frontend validation source is exact commit
`36ae3fbfce3f5b1d5554b72a48928f55dc4bc277`; the root's assigned static
API/fault/observer scopes found no blocker. PR26 merged this source into main
`c099b01e3b8affa6e0160cf3b9b4c24697641056` under ordinary source-only guards.
Independent validation reported148 focused tests plus54 subtests passing.
This is no runtime release.
The previous `6baa44e` Windows tests reported a collection-time expiry failure.
The committed correction changes only observer-test timing: future bounds are calculated at
invocation. Helper and production files are byte-identical; real-clock guards,
TTL and acceptance rules remain unchanged. The root's static delta review passed.
All required CI checks must be green before execution review. GitHub currently
blocks jobs before any steps run because of an account billing or spending limit;
all14 fresh push/PR jobs and all7 merge-main jobs never started and are not green.
This is separate from source-test results. No rerun is requested while blocked.
The timing fix is no runtime proof or authorization to execute. The four
API helper blob hashes are pinned in `contract.FRONTEND_FILES` and required at
`fixture/frontend_helpers/frontend_driver.py`, `fixture/frontend_helpers/frontend_fault.py`,
`fixture/frontend_helpers/frontend_confirm_fault.py` and `fixture/frontend_helpers/frontend_observers.py` in the
future private bundle. Browser helpers/build/truth adapters are excluded from
the first API checkpoint. The derived frontend environment adds the helpers'
required `rfc8785==0.1.4`, matching the installed banking requirement; the
frontend's separate pinned PyJWT version remains in its own environment.
The helper directory is a Python namespace package so its reviewed relative
imports work unchanged; PYTHONPATH includes its parent and the frontend package
parent. The pure source coverage compatibility audit hash is
`b904a4e8c05594520738935039533345f75c8d7e2c2ad4eafc751e922cb05cd3`.
Before releasing execution, root must review an exact committed integration head,
corrected committed frontend selection/forwarding/observer source, the real
fixture provider/graph/policy, and a private successful bundle artifact with
producer head, ZIP/manifest/graph/policy/provider hashes. `validate_review()`
rejects null identities and nonexact heads. A separately reviewed revision must
remove the source hold. There is no dispatch input that disables it.

The provider is currently absent. Required interface methods are `start/stop`,
`credentials(es|pt)`, `bind_selection(actor,cookie,"normal")`, `bind_general`,
`observe`, `read_coverage`, `read_risk_by_request(actor,host_uuid)`, independent
saved receipt/HOF reads (including by general request UUID), `arm_response_loss`,
`read_consumed_fault`, `read_prepare_recovery`, and `restart_preserving_state`. Selection/bootstrap must
use ordinary authenticated frontend paths and actual repository facts. No seeded
conversation IDs, fabricated MCP/HTTP returns, direct-MCP scenario shortcuts,
signature bypass, client-controlled identity/upstream/fault or guard bypass is
accepted. The configured frontend must use a reviewed supported mode compatible
with its current invite guard.

`observe` returns only nonnegative counts and actual stdio dispatch counts.
`read_coverage` independently returns `{rows,configured_start_matches,
generation_matches,complete}`. The completed fault marker is exactly
`{operation,target_matches,completed_upstream,consumed,consent,receipt,handoff_id}`;
all flags are strict booleans, receipt/HOF matches actual independently saved
evidence, and the target is matched internally. Raw cookies, capabilities,
signed bodies, policy secrets and full response logs must never be retained.
`read_prepare_recovery` must join the reviewed consumed journal, actual host
intent and saved bank pending/HOF. Its exact field inventory is
`PREPARE_RECOVERY_FIELDS`: host/action UUIDs and revision, conversation/capability/
packet hashes, one pending identity, saved HOF ID, current generation and strict
target/completed-upstream/consumed flags. It exposes no raw pending capability or
cookie. Declared values alone cannot satisfy that adapter's source review.

## Isolation, retained evidence and limits

Only a private GitHub-hosted Linux runner can pass source gates. Runtime uses a
single disposable non-root container with no network, read-only root, dropped
capabilities, bounded resources, private tmpfs state, no host ports or Docker
socket and no GitHub token. All process output is suppressed. Uploads are an
allowlist of sanitized `checkpoint.json`, `source-identities.json` and
`observations.json`; completed phase results survive later failure. Dataset and
coverage readback files remain private runtime inputs unless a separately
reviewed sanitized evidence projection is added. No local Docker/artifact
restore/service/action/model/HTTP work is authorized by this preparation.

Pure source checks validate contracts, tampering rejection, source identity and
hold behavior; they do not prove integration. Synthetic credentials and authored
coverage are disclosed fixture inputs. External provider calls, real model
ES/PT behavior, browser UX, joined human acceptance, capacity, shared deployment,
held-out comparison and future virtual clock evaluation remain unproven. The
two-clock ledger design is deferred and is not required for this first checkpoint.
