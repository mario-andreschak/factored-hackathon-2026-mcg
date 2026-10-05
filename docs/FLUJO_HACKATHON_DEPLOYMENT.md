# FLUJO hackathon branch and deployment source map

> This is the dated source/deployment history below. Use the
> [release candidate report](submission/RELEASE_CANDIDATE.md) for the final-day source,
> running image and customer-path acceptance; the older pins here remain evidence
> of their original observation, not a current runtime inventory.

Updated September 30, 2026, following the owner's request to preserve the
reversed hackathon PRs on a separate FLUJO branch. This replaces the earlier
categorical ban on separate hackathon branches; generic main remains protected
from domain additions. Project repository status in the table below was
rechecked October 1, 2026; the historical worker and FLUJO branch pins retain
their separate evidence dates.

## Which source belongs in which deployment

| Source | Purpose and status |
| --- | --- |
| [FLUJO main](https://github.com/mario-andreschak/FLUJO/tree/main) | General-purpose FLUJO. At `3fccc557df97aba0e96ce28a8e6eebaa8e71d7d9`, its tree is `780c2cf42266f8e55ff1917c137b196ee97df959`, exactly the generic pre-#530 tree of `45e37a5127027070858eca086675ca7675d59f3d`. Generic MCP/execution hooks remain; the hackathon integration is absent. |
| [FLUJO `codex/hackathon-banking`](https://github.com/mario-andreschak/FLUJO/tree/codex/hackathon-banking) | Dedicated hackathon source. Starts from the combined pre-restoration commit `51ff39fc5bac84cbbb49bbd2b21b5ab89de8b14b`, tree `b754c1cae7def51ab9a1343c1726a63c30d2c53a`, which includes #530/#532/#533. Added branch deployment documentation does not alter that application source. |
| Existing local worker | Still source `153a039185b1d303fb0853f1d4935980388a1903`, image `sha256:f99c1998c60a69ea6572685b77ef80a74cb4834486b0fcd2455ff6dc7c9be2b8`. Neither main restoration nor branch preservation upgrades this worker. Its older evidence cannot be relabeled as current-branch acceptance. |
| Project PRs [#31](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/pull/31) / [#32](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/pull/32) | Merged project-owned host/direct-MCP source at observed project main `e967e7e795e6ceef0aebc1f076fa0443d996a236` and included in the local release integration `af3b22d044835edd6a6d99c00add2be4449a3ff3`. It is separate from the preserved FLUJO branch. Source integration is not joined runtime or deployment acceptance. |

The initially published hackathon branch head is
[`0ba62296520a505e6d71eddf5aa650691f3dc311`](https://github.com/mario-andreschak/FLUJO/commit/0ba62296520a505e6d71eddf5aa650691f3dc311),
tree `c1e66af0a8ba9cf436a4f3a76b6b684fdd2ccb1d`. Its difference from `51ff39fc`
is limited to five Markdown documents; application and build configuration
match the preserved combined source. Resolve a new immutable head if the branch
changes later rather than assuming this initial pin still names its tip.

The preserved integration is the already combined source before restoration,
rather than independent cherry-picks of older PR heads:

- [FLUJO #530](https://github.com/mario-andreschak/FLUJO/pull/530): banking runtime integration.
- [FLUJO #532](https://github.com/mario-andreschak/FLUJO/pull/532): protected sandbox banking action route.
- [FLUJO #533](https://github.com/mario-andreschak/FLUJO/pull/533): banking case/handoff integration.

[FLUJO #534](https://github.com/mario-andreschak/FLUJO/pull/534) removed these
domain additions from generic main. The separate branch preserves them for the
hackathon without merging them back or claiming they were generalized.

## Deployment reference

Use the branch's canonical
[hackathon deployment guide](https://github.com/mario-andreschak/FLUJO/blob/codex/hackathon-banking/docs/HACKATHON_DEPLOYMENT.md)
for the source pin, image identity and existing-worker deployment procedure.
Use generic main for ordinary FLUJO builds. Select the dedicated branch explicitly
for a hackathon build, resolve and record its immutable commit before building,
and retain that revision in the image and deployment receipt. Do not use a
moving branch name or an existing image tag as proof of the deployed source.

Preserving this branch and updating documentation are source changes only.
No worker build, pull, replacement, restart, model/provider call or bank action
is performed by this change. An eventual worker replacement uses the single
existing FLUJO/MCP process arrangement, preserves protected state and credentials,
and needs its own exact-source checks and deployment evidence. The Slack gateway
now shares the existing worker's network namespace; replacement of the worker
also requires recreating the gateway against that worker and verifying recovery
bindings before delivery.

## Acceptance still required

Bank actions remain OFF. Branch preservation does not clear owner/session and
transaction ownership checks, explicit host consent, durable request UUID and
receipt read-back, safe uncertain-confirm recovery, revocation, or handoff
verification. Ledger reset/restore continuity, quarantine and explicit operator
reconciliation remain release gates; do not adopt a replacement ledger or clear
quarantine automatically. Do not transplant consent or in-flight banking
requests between runtime revisions.

Retain the private SDK/TLS/MCP/process identity and saved graph/model/catalog
checks. Native execution isolation and a joined customer path must be measured
on the actual pinned deployment. Historical operator tests, mocked acceptance,
source hashes and model capacity counts do not establish those gates. ES/PT
learned-component claims still need independently human-adjudicated held-out
cases compared with the deterministic baseline. This documentation does not
authorize publishing restricted organizer data, history or credentials.
