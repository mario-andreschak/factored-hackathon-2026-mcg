# Isolated native transaction dispute workflow qualification

> Historical native-image qualification, retained with its original pins.
> The [final-day fictional launcher](../deploy/rc/README.md) uses generic model
> completions and an in-process banking service; it does not qualify this native
> image. Current acceptance belongs to the [release report](submission/RELEASE_CANDIDATE.md).

This repository owns the adapter, workflow and qualification harness. FLUJO
generic main and the shared local/Fly workers are unchanged. The isolated image
builds immutable FLUJO revision `0ba62296520a505e6d71eddf5aa650691f3dc311`
through its existing `FLUJO_EXECUTION_ADAPTER_MODULE` hook.

The saved four-node graph calls a registered, per-admitted-turn MCP closure.
The canonical 21 stages run in the application's Python orchestrator; the graph
does not install 21 invented FLUJO handlers. Its model relay is untrusted. The
adapter separately validates and captures the exact tool projection, and the
host must render that validated application result.

Every interpretation stage uses a fresh ephemeral FLUJO language graph and the
restricted native profile. The generic direct-model route does not propagate
execution context, so the private adapter rewrites trusted stage calls into
these graphs. Native conversations do not inherit stored history, tool caches
or sticky tool state. The application owns durable customer state.

The [implementation guide](DISPUTE_IMPLEMENTATION.md) records contributor credit
and naming history. The installed results below describe the pre-rename image;
they do not qualify the renamed source. Use a new context, image and report for
the full qualification of the renamed workflow.

## Historical pins and demonstrated capability boundary

- Native CLI: `0.157.1`, Linux x64 musl binary SHA256
  `3e2584f3f3829a43a0495011a1cecb2facbe64a2403e2b682351fd9c2983f970`.
- Restricted catalog SHA256:
  `5a1ddcef609e52bd057b247d9487f2c8c4d9453d3d802745ba5325c2e10700e0`.
- Configured model: `gpt-6-sol`, installed as `gloria-native-model`.
- Exact package-lock SHA256:
  `afad61fa19dc4bb61bc997cde4b9aaaa20e8baaf866a22da716c9cc364f2c791`.

CLI 0.153.3 passed forced dispatch probes but the actual account's upstream
rejected both model aliases. CLI 0.157.1 returned an actual provider response
without FLUJO source changes. Fourteen forced native probes exercise both
catalog models: approved MCP succeeds; inherited rogue MCP, foreign resource
reads, foreign apply_patch and functions.exec are denied without file changes
or foreign data disclosure. Their upstream responses and authentication are
synthetic; they prove native dispatch behavior. Normal workflow cases use the
actual provider and are reported separately.

Admissions live only in a private runtime mount. A durable ledger consumes an
outer admission before execution and binds conversations to the admitted
owner/session/customer/expiry fingerprint. Consumption is checked again after
request-body parsing, preventing concurrent slow-body replay. Restarted
workers reject consumed admissions and foreign sessions before model or MCP
dispatch. Native loaded state is rejected. Revocation, expiry and cancellation
are checked before provider calls, tool calls and commits.

## Joined application interface

```python
from scripts.native_dispute_qualification import NativeDisputePort

port = NativeDisputePort(
    workflow_factory,                 # callable: model -> owned Workflow
    "http://127.0.0.1:43922",          # isolated service, not the shared worker
    private_authority_directory,
    timeout=90,
)
state = await port.run(
    admitted_binding, original_message,
    turn_id=admitted_turn_id,
    selection=trusted_selection,
    query_scope_id=trusted_query_scope,
)
```

`workflow_factory(model)` constructs the real owner-scoped bank reads, action
host and ConversationStore and installs `StageAdapters(model)` with a bounded
stage timeout appropriate to the qualification. Trusted selections remain in
the application call; they never become model/tool arguments. The returned
state contains the application's validated response. DisputeChatService consumes
this state directly, avoiding outer model paraphrasing.

The host creates a private language-only admission for the turn and revokes it
in `finally` before removing its registry record. Revocation publishes an
independent fsynced 0600 marker named by the stage token's SHA256. The worker
checks that marker before and after admission/body awaits and at every execution
fence. Unexpected marker I/O denies execution. A permanent registry sharing
conflict therefore leaves a denied record; it cannot extend stage authority.
Markers are private, monotonic and scoped to one stage token. Registry edits use a kernel lock released after process death,
0600 temporary files, atomic replacement and POSIX directory fsync. An old
marker cannot prevent restart. Windows replacement retries transient reader
sharing conflicts for at most five seconds while retaining the writer lock and
the same fsynced file; permanent failures preserve the original registry and
remove the temporary file. Never serve the per-turn closure on shared HTTP
or derive identity, selection or consent from model text.

## Reproduction

Prepare a new ignored build context from the clean permitted source checkout,
a previously inspected restricted catalog and the exact verified native binary.
Choose new run-specific output paths; never overwrite a historical report.

```powershell
python scripts/native_dispute_qualification.py --flujo-root '<clean-pinned-checkout>' --context private/native-dispute-new --catalog '<restricted-catalog.json>' --native-binary '<verified-linux-binary>' --native-version 0.157.1
docker build -t codex-dispute-native-qualification:new private/native-dispute-new
node scripts/native_dispute_qualification.mjs --flujo-root '<pinned-git-repo-with-authoring-dependencies>' --context private/native-dispute-new --image codex-dispute-native-qualification:new --output private/native-dispute-new-result.json --retain-runtime true
python scripts/native_dispute_qualification.py --publish-report private/native-dispute-new-result.json --public-output docs/qualification/dispute-native-new.json
python -m unittest tests.test_dispute_graph tests.test_native_dispute_qualification -q
```

The binary package is `@openai/codex@0.157.1-linux-x64`; verify its registry
tarball integrity before extracting the musl binary. The builder image must
have the pinned package-lock dependencies. The build context contains only
public source, canonical policy/prompts and the verified native binary. Login
is transferred at runtime into a separate readonly mount and never baked into
the image or published report.

The runner checks host source bytes, in-image source hashes and exact context-manifest SHA before
any provider call. It installs/readbacks the model, actual MCP server and saved
graph, then checks ES/PT normal turns, cancellation fallback with zero bank
reads, transport replay, restart replay, foreign owner/session, poisoned
native state and slow-body concurrent replay. Full synthetic diagnostics stay
under ignored `private/`; public reports contain only reviewed projections and
redacted measurements. Publication requires all fourteen capability and fourteen
boundary cases to pass, four installed no-provider revocation probes, five exact
adapter fence probes, installed source equality and an image credential-file
audit. The cancellation probe uses an actual Windows reader denying delete
sharing, then verifies that a late callback is denied despite its retained
registry record and that sibling admissions survive. The public allowlist excludes private paths, admissions, tokens, raw
model content and responses; incomplete qualifications cannot be published.

`--retain-runtime true` retains a successful qualification for joined HTTP
tests. `--serve-only true --retain-runtime diagnostic` starts a separately
identified diagnostic listener; it explicitly does not claim qualification.
The private `host-integration.json` records its endpoint, authority directory,
container and cleanup paths. Stop only that named owned container and remove
only its checked private auth copy after joined tests. Final source freeze
requires a fresh context/image and a final installed report; earlier passing
runs do not qualify later source edits.

## Current renamed source integration

The [combined renamed source report](qualification/dispute-naming-source-2026-10-01.json)
qualifies frozen source `ea8f62176157cb016ff07db86c8d2e8c49272aa9`, including
85 protected hashes, 1,725 tests and 428 subtests. Its source-only graph remains
uninstalled with actions disabled. All previous reports remain byte-identical;
none of their installed runtime results transfers to this renamed artifact.
Exact replacement-image/native/provider acceptance still requires the gates below.

## Previous source integration and runtime requalification

The historical PR39 portal/preview graph covered 85 protected files. Its
[separate source report](qualification/release-preview-source-2026-10-01.json)
qualifies its original pre-rename source snapshot and fictional read preview only.
Neither that preview nor a graph freshness pass establishes installation or
native/provider execution. The installed image/report below remains historical
and must not be substituted for a replacement image's exact qualification.

The credential-question source correction and regenerated bridge at
`d7a4f432000db0a225a010235083427f957c35b5` are validated separately by the
[combined source report](qualification/gloria-credential-source-2026-10-01.json).
They have not been installed or executed in the image below. Its report remains
immutable historical evidence for `abc9068`; passing results cannot transfer
across the changed protected response source and graph hashes. A replacement
image still requires the full installation, capability, revocation, fence and
joined qualification appropriate to its intended runtime use. The source merge
does not activate the shared deployment or enable banking actions.

## Historical abc9068 frozen source validation

That isolated qualification uses application source
`abc90682faa5cb496c9cd3476ec7811a7e5c9281`, image
`sha256:402581eaa5df62914d91acbee60c2cdba63aacdfcca64957637825d3387243c7`,
and external source-manifest SHA256
`f8757e1e059370c93b32258d169d2faecbcde18b2de786e5a5bef91b91bde453`.
All 87 application files and 1,410 FLUJO files match their installed bytes.
The bank requirements file is copied and hashed as provenance; the image
installs the independent workflow application dependency closure.

The [sanitized installed report](qualification/gloria-native-release-2026-10-01.json)
records 37 passing checks: fourteen workflow boundary cases, fourteen native
capability probes, four revocation probes and five exact adapter fences.
The real provider returned exact validated Spanish and Portuguese tool
projections. Timeout used the guarded fallback with zero bank reads; restart,
foreign-session, replay, poisoned-state and late-callback cases denied execution.
These workflow cases use the public synthetic development fixture and expose
no banking action tools.

The separately retained joined listener's readiness report has zero workflow
cases and deliberately reports qualification false. Its installed pins and
capability/revocation/fence gates pass, permitting the separate joined
application qualification. It is distinct from the passing full boundary
report. Shared deployment remains unactivated.
