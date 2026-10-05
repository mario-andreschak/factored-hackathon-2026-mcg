# Application-owned recovered-fleet connector

The source-validation sections below describe the original connector review.
The connector was subsequently deployed after the PR #66 startup configuration
fix; an October 5 customer goal reached the native root but failed its first
model call because the provider workspace was disabled. Successful 300-request
FLUJO load and sandbox tests are separate infrastructure evidence. A further paid
video run was skipped because of budget constraints. See the
[infrastructure report](../measurements/INFRASTRUCTURE_CAPACITY.md),
[actual attempt](../measurements/fleet-customer-attempt/receipt.json) and
[release record](../RELEASE_CANDIDATE.md). Frozen recordings retain their scope.

The existing `InquiryService` remains the case owner and follow-up loop. Its
default mode still runs the two bounded bootstrap reviewers. An explicit private
`inquiries` setting in the existing `BANKING_CONFIG_FILE` selects
`recovered-fleet/v1`; `{}` or `{"mode":"bootstrap"}` retains the default. The
disabled [example](fleet-config.example.json) is a review template, not a working
configuration. Unknown/malformed settings or missing private tokens refuse startup.

## Binding and runtime ownership

Before enabling, the runtime owner supplies an approved controller origin and
operator token environment reference, existing native supervisor/workspace/model
and source revision and approved normalized execution-template digest, plus an
absolute path to an owner-provided read-only registry view. Actual compiled flow
IDs are observed from original executions rather than configured in advance. Token
values are injected into HTTP requests and never persisted in the case database.
HTTP is allowed only for loopback; redirects and environment proxies are disabled.

This consumer does not construct the upstream Registry, start a controller,
install flows, clone Machines, choose a provider or adopt any original resource.
The existing controller's `POST /goals` performs its normal installation/start
behavior when a future owner-approved runtime uses this connector. That write
is not exercised by source tests. Existing `swarm_boot`/installer/fleet/relay
lifecycle belongs to the original orchestration owner.

The request forwards the generic `teamLimits:{concurrency:9}` operationally to
`POST /goals`, alongside role/task instructions. The intended Savia variant has
one lead plus nine children on each of ten team Machines, with root supervision
separate. Stock recovered revision `f9d372a66dd2cb09f4bcfed34967404cf12d9007`
supports the goal/run protocol but ignores `teamLimits` and installs concurrency10;
it is not a supported nine-child activation pin. The generic successor is now
published in the private engine at
[`290dd6a7c19fa92c267bddd04f625f6cfbe39459`](https://github.com/flujo-app/swarm-teams/commit/290dd6a7c19fa92c267bddd04f625f6cfbe39459),
tree `ac679ed5e8d3eabab81af553bdb282456bae5e34`, under `swarm-teams/`.
The upstream publication is draft [PR60](https://github.com/flujo-app/iambrokeplshlp/pull/60)
at head `6b3a1cb4081b48faefddccc3d8a478e0219dfb33`, stacked on optional-profiles
PR59. These are source publications, not an adopted running controller/image.

The focused patch changes exactly `fleet/controller.mjs`,
`fleet/provisioners.mjs` and `test/fleet.test.mjs`. It validates limits before goal
creation, persists `goal.teamLimits`, passes the selected limits to supervisor
installation, and forwards them through delegation to workspace/Fly installation.
Stock defaults remain10. The source owner and recovery reviewer report eight
loopback fleet fixture tests passing, including selected9 root/workspace-child
installation and invalid11 rejection before goal creation. That evidence does not
qualify live Fly installation, model work or fleet capacity. The consumer's exact
`teamLimits:{concurrency:9}` body needs no optional-profile manifest.

The disabled example names the published private-engine successor. Before
activation, the runtime owner must select and verify the actual controller/source
pin and deployed compatibility; publication alone does not supply that binding.

`team_machines` is an upper bound1–10, not a headcount or working capacity claim.
The configured digest pins the root-review execution pair described below;
the connector does not independently qualify installation. Model-ID propagation,
native read access, fleet/relay reachability and funding still need runtime-owner
qualification before activation.

## Durable acceptance and recovery

`POST /api/assistant/cases` accepts an optional UUIDv4 `request_id`. It binds the
authenticated stable owner, canonical customer input/language/selection and the
first trusted display-fact snapshot. Same owner/key/input reads the original case
before another selection lookup or runtime availability check. Changed input with
the same key returns409. The request key is scoped by owner. Existing clients
without a key remain supported.

InquiryPanel retains one UUID for the full unchanged submission payload, including
language and transaction selection, across ambiguous POST failures. Success or a
changed logical submission selects a new key. This is in-component retry protection;
browser reload does not persist an unsatisfied submission key. Deploy the new
frontend and API together; older APIs reject the added field.

The private SQLite records retain immutable source/template/configuration pins,
input digest and the secret-free outbound body before fleet dispatch. A transaction
sets a unique attempt token and `submitting` fence before the sole initial
`POST /goals`. A lost/malformed ACK, process interruption, stale binding, original
identity mismatch or UNKNOWN becomes held. No create/start replay, automatic
resubmit or customer reset endpoint exists. New dispatch is queued behind an
unresolved hold or active original goal on the same controller/registry/workspace
lane. Changing a source or model pin cannot bypass that lane hold. This serializes
initial goals because the existing controller replaces fixed workspace flow/token
bindings. Queued intents do not starve known-run polling. Before the sole POST, a
local registry preflight also rejects occupied/UNKNOWN original workspace runs
and explicitly unconfirmed cleanup. It does not acquire upstream ownership or
make an external writer's concurrent changes atomic.

Known ACKs save original goal/supervisor/run handles. Polls use only
`GET /goals/{goalId}` and `GET /runs/{runId}?waitMs=0`. The existing two-second app
loop runs the consumer; upstream polling is bounded to30-second intervals. Attempt
leases are300 seconds to cover the bounded reads. Every asynchronous state,
handle, board and review/worker publication requires the current unexpired attempt
under an atomic write transaction. Older ACKs/results cannot overwrite a newer
hold, human acceptance or expired tracking horizon.

Operator reconciliation remains external to the customer API. Preserve original
identities/receipts and upstream OFF, UNKNOWN, cleanup and ownership holds. A
tracking pause leaves the customer case unresolved. There are no new bank reads,
ticket deliveries, emails or pushes in this module.

## Reviewed result convention

Recovered revision `f9d372a66dd2cb09f4bcfed34967404cf12d9007` carries this strict
JSON through existing final result strings and `board_post.text`; no engine change
or role-manifest framework is required. The recovery owner confirmed this
transport and the existing independent/fresh conclusion-check cycle.

The final result object has exactly:

```text
schema_version: 1
binding: {case_id, request_id, input_digest, source_revision, template_digest,
          goal_id, run_id}
suggestions: [
  {role, suggestion, author_conversation_id, finding_seq,
   reviewer_conversation_id, review_seq}, ...
]
conclusion_review: {reviewer_conversation_id, review_seq}
```

Exactly one `evidence` enum (`review_merchant`, `review_date_amount`,
`ask_selection`) and one `next_steps` enum (`keep_receipt`, `ask_human`,
`await_bank`) are accepted. The host emits its existing localized copy from these
enums and the original minimized facts. Model prose never becomes a customer
suggestion, voice authority, bank outcome or human acceptance.

Each author completes with and posts an identical finding record:
`{binding, role, suggestion, author_conversation_id}`. Its independent reviewer
receives the exact canonical finding JSON in a user/task message, then completes
with and posts `{binding, finding_seq, role, suggestion, verdict:"accept",
reviewer_conversation_id, check}`. `check` is a nonempty private explanation of at
most1200 characters. A rejected or missing check is not acceptance.

The fresh conclusion checker receives the exact canonical proposal
`{binding, suggestions}` including all finding/review references. It completes
with and posts `{proposal, verdict:"accept", reviewer_conversation_id, check}`.
The final packet references that sequence. All two authors, two reviewers, fresh
checker and original lead must have distinct native conversation IDs. Every board
sequence must be unique, observed for this goal and match the native completed
output. Duplicate JSON keys, invented identities and review of another proposal
are rejected. Canonical JSON here is UTF-8 `json.dumps(..., ensure_ascii=False,
sort_keys=True, separators=(",", ":"))`.

## Read-only proof and customer projection

The recovered HTTP status routes omit lead/native child identities. The bound
registry reader extracts the original run→worker→goal→lead join, verifies original
goal text, flow name and target/workspace, and never modifies the registry. Its
read is bounded to16MB and runs outside the foreground event loop.

This initial observer uses existing authenticated native conversation GETs and
`GET /v1/chat/conversations/{id}/debug/state` in the bound supervisor workspace.
The existing debug route returns `{status,breakpoints,debugState}`; the consumer
extracts only `debugState.flowSnapshot` and verifies original conversation/status/
flow identity. The source route is present on the preserved hackathon compatibility
revision `0ba62296520a505e6d71eddf5aa650691f3dc311`. Its state loader can reconcile
interruption/repair dangling messages and persist native state; this GET does not
enable debugging, resume a run or submit model work. Actual deployed compatibility,
access and these read side effects require native-owner qualification. The native
conversation detail GET can also flush/repair transcript state. A mutable installed
flow GET cannot prove an original execution snapshot. Missing
saved execution snapshots leave review pending. There is no fallback to mutable
current flow definitions or dependency on invented upstream installation receipts
or run snapshot-digest fields.

The template digest is SHA-256 of canonical normalized original execution snapshots
for exactly `swarm_supervisor` and `swarm_agent`. Compiler-generated flow/node IDs
are replaced by stable name/order references; timestamps, viewport and node/edge
layout metadata are excluded. Ordered node type/data, model/tool/prompt properties,
other flow properties and edge semantics are retained. All five child's original
agent snapshots must agree; process model IDs and subflow concurrency9 are checked.
The runtime owner must provide this normalized digest from the approved compiled
definitions before activation; it is not a hash of all three raw FlowSpecs.

Successful proof saves only private observed flow IDs/full snapshot digests and
the original goal/run/lead join with provenance `original_native_execution_snapshots`.
The expected source revision remains an owner pin, not an independent Git
attestation. The observer verifies completed status, child parent links, original
input correlation and exact reviewer tasks and outputs. It qualifies only the
root's local review subset. Cross-Machine
identity/task receipts require the orchestration owner's existing observation
adapter before any full-fleet claim. Board authors authenticate Workers, not the
native conversation named in text; board prose/IDs alone never suffice.

Latest200 board entries are retained privately while polling, up to1000 observed
entries per case. A missing older referenced entry, conflicting entry, inaccessible
native transcript, malformed packet or free-text completion remains
`review_pending` with public `needs_attention`, no result and no helpful closure.
Confirmed failures also expose only existing localized customer states.

Successful proof adds the two approved informational suggestions and a meaningful
durable `team_completed` event. Unchanged polls do not append events or repeat
canonical voice authority. Private handles, provenance, credentials and histories
remain out of public responses. Public `execution` metadata reports only typed
state, review status and the observed root-review subset count; it always sets
`full_fleet_count_verified:false`. It never claims100 concurrent AIs.

Informational closure still requires an explicit owned customer confirmation after
verified results. No completion resolves a banking problem. The existing internal
`accept_human` requires a real operator principal; a draft, submitted packet or
delivery receipt cannot call it. Actual acceptance invalidates in-flight publication
without clearing an already held original run. No external ticket/notification
destination or consent is invented by this source change.

## Focused validation

Synthetic HTTP transports and native/registry fixtures exercise actual consumer
code, without a provider. Coverage includes once-only dispatch, immutable input
collisions, owner isolation, lost ACK/crash recovery, read-only restart, binding
drift, fabricated/stale/rejected review, late ACK and older review after UNKNOWN,
human acceptance during review, meaningful cursors and canonical voice projection.
Bootstrap and existing host/Listen tests retain their scope. Passing source tests
does not qualify deployment, real inference or exact ten-by-ten customer execution.

Final local checks:50 assistant tests;55 focused host tests plus9 subtests;
78 InquiryPanel/Assistant UI tests; production frontend build and `git diff --check`.
These checks cover source behavior with mock upstream/native transport only.

The optional scoped MCP reads the same private `BANKING_CONFIG_FILE.inquiries`
binding and environment token references as the host API; its owner namespace and
state directory must match the intended host deployment. An unconfigured bootstrap
MCP is not an activation path for fleet cases. The complete bounded result protocol
is embedded in each saved outbound task so a worker needs no repository access.
