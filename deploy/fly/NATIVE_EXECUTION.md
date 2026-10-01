# Joined Fly native language boundary

`native-execution.mts` derives the ephemeral language-stage path from
`scripts/native_dispute_qualification.ts`, using FLUJO source
`0ba62296520a505e6d71eddf5aa650691f3dc311`. It accepts only application-issued
`language_only` stage admissions. It exposes no MCP, banking action, handoff or
qualification workflow bridge. Each request receives a fresh protected graph;
saved conversation state cannot be loaded into it.

The application owns admission/revocation controls. The worker reads them and
writes its separate ownership ledger/events. The application remains the sole
owner of banking configuration, dataset and banking/workflow state.

| Location | Owner and permissions | Purpose |
| --- | --- | --- |
| `/data/native-authority/control` and `revocations` | UID10001, GID10002, 2750 | Application-only directory mutation; worker group read/traverse |
| `control/admissions.json` and replacement admission files | UID10001, GID10002, 0640 | Preserve these permissions on **every** atomic replacement |
| `/data/native-authority/worker` | UID1000, 0700 | Worker ownership ledger and events; never application control files |
| `/data/native-flujo` | Worker UID1000 | Independent native-worker configuration/runtime |
| Bank configuration, dataset and state | UID10001, primary GID10001; private parents | Never add the native-reader group to banking data |
| `/opt/native` | Root, no group/world write | Immutable execution/profile inputs |

Bank UID10001 and worker UID1000 have supplementary group10002. This reader
group grants no directory mutation on application controls. No existing banking
ledger or legacy worker data is automatically initialized or migrated by this
adapter.

Install the selected FLUJO model with id `dispute-native-model`, provider `codex`,
adapter `codex-cli`, model name `gpt-6-sol`, and the independently qualified
reasoning effort. Application stages call `model-dispute-native-model`. Set
`FLUJO_DATA_DIR=/data/native-flujo` and use `default-workspace`. Compile the
selected FLUJO build with `FLUJO_EXECUTION_ADAPTER_MODULE=/app/fly-native-execution.mts`.

The immutable restricted profile at `/opt/native/native-profile.json` contains:

```json
{
  "verifiedCliVersion": "0.157.1",
  "verifiedCliPath": "/opt/native/codex-wrapper.mjs",
  "verifiedCliSha256": "<SHA256 of the exact installed wrapper bytes>",
  "verifiedModelCatalogPath": "/opt/native/model-catalog.json",
  "verifiedModelCatalogSha256": "5a1ddcef609e52bd057b247d9487f2c8c4d9453d3d802745ba5325c2e10700e0"
}
```

The wrapper and raw CLI are distinct executable identities. The wrapper validates
the immutable raw CLI at `/opt/native/codex.raw` against SHA256
`3e2584f3f3829a43a0495011a1cecb2facbe64a2403e2b682351fd9c2983f970`.
`--version` reports the checked raw CLI version; a version string does not make
the wrapper's SHA256 equal to the raw CLI hash. Record both hashes in the image
and deployment receipt. Root owns the raw CLI/wrapper with mode0555; profile and
catalog may be0444. The wrapper shebang uses the image's immutable
`/usr/local/bin/node`.

For normal invocation, the wrapper requires worker UID1000 and the SDK's fresh
0700 `codex-private-*` home under
`/data/native-flujo/workspaces/default-workspace/db`. It rejects symlinked or
broader homes, inconsistent private temporary paths, resumed sessions and loose
ownership/permissions. Bubblewrap creates user, PID, IPC and UTS namespaces, a
new session and no capabilities. Its filesystem contains only the current
invocation home, the pinned raw executable, public CA/DNS files, fresh `/tmp`,
empty `/run`/`/home`, and a new namespace's `/proc` and `/dev`. Other worker logs,
admissions, bank state, other invocation homes and application source are absent.
The host root, `/usr`, `/lib`, `/opt` and `/data` are never bound wholesale.

Provider networking remains available. FLUJO's separately pinned native profile
still denies model shell/patch/browser/code/subagent/resource capabilities. This
filesystem boundary complements that capability gate; it does not assert a
provider egress allowlist. Namespace failure is terminal and never retries
outside bubblewrap.

Focused source checks:

```powershell
$env:FLUJO_SOURCE_ROOT='C:/Users/Moe/Documents/GitHub/FLUJO'
node --test deploy/fly/tests/native-boundary.test.mjs
```

The tests exercise actual adapter declarations with synthetic controls and no
provider execution: denied substitutions, permissions, revoked stages,
unbranded contexts, writable profiles and forbidden tools. Wrapper tests verify
the permitted mount/environment set and strict home admission. These are not
kernel or real-provider evidence.

Before production activation, qualify the **installed image** on the actual
Linux kernel: user/PID namespace creation under UID1000, an actual wrapped native
stage, provider TLS/DNS, and denied reads of synthetic bank/config/ledger and
generic-worker-log sentinels. Verify controls cannot be replaced by UID1000,
including after the application replaces admissions and creates revocation
markers. Verify only the current invocation's home is mounted and that process
enumeration cannot see host worker/application processes. Record namespace
failures truthfully; an unavailable namespace must keep native execution denied.
