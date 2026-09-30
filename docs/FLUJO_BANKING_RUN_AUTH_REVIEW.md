# Second review of the FLUJO banking proposal

> **Historical review, September 27:** the findings and open gates below describe
> the code inspected on that date. See [current implementation and acceptance](BANKING_MCP_IMPLEMENTATION.md)
> and [current decisions](BANKING_MCP_NEXT_STEPS.md) for the implemented scope,
> measured results and remaining follow-ups.

**Date:** 2026-09-27. **Verdict:** retain FLUJO as backend/MCP client, revise the security and scaling contract before implementation. The original direction is feasible; several details were incomplete or overstated. The [revised proposal](FLUJO_BANKING_RUN_AUTH.md) incorporates the corrections below. This is a source/architecture review with limited executed probes, not certification of an implemented bank system.

> September 28 correction: this review correctly identified Static/preset gaps,
> but the resulting banking-specific ingress bypassed the requested existing UI
> and Slack workflow. The [presets plan](FLUJO_TOOL_PRESETS_PLAN.md) corrects that
> integration decision. Historical probe results below retain their original scope.

## Review scope and provenance

- Hackathon repo fast-forwarded from `ecdd0b9` to `5787cc6`; this includes the team's DuckDB pipeline. Reviewed gold/lookup/lineage/report code as a new serving alternative without changing it.
- FLUJO checkout: `15d019f7b952b2f2d3aea1197722ac8d9f520d7c`; existing staged/uncommitted work preserved. Relevant backend/route files are inspected working-tree sources; no FLUJO banking implementation was edited.
- Runtime dependencies actually loaded by probes: MCP SDK 1.30.0 and client 2.0.0, Node 22.13.1. The `mcpBetaProtocol` identifier is an experimental FLUJO switch, not evidence that the installed v2 package is a beta.
- User-authorized live instance: `http://localhost:4200`, `default-workspace`. Its routes were observed independently; its exact running build/commit was not attested. Fixture had only Start/Static/Finish nodes, with synthetic messages and no provider/MCP/data calls.
- No organizer rows, credentials, production customers, or real bank actions were used. Test flow/conversations were removed and subsequent GETs returned 404. Ordinary runtime statistics/events may retain synthetic test metadata.

## Findings and corrections

| Finding | Evidence | Required revision |
| --- | --- | --- |
| **Shared elicitation can route to the wrong conversation.** | `elicitationContext.ts:36` keys by workspace/server; `elicitation.ts:89,117` reads that context and emits to its conversation. Actual module probe: B replaces A, clearing the server erases B. | Disable bank elicitation; later correlate authenticated originating requests, including cleanup and input resolution. One shared MCP client is safe only with a restricted protocol profile. |
| **Approval has a separate execution boundary.** | `resumeAfterApproval.ts:82` calls ModelHandler with tool calls/maps/MCP nodes but no conversation/run/authority. Existing tests mock the dispatcher. | Explicitly reauthenticate, attach fresh context and enforce owner before execution or live registry resolution. Bank consent remains independently operation-bound. |
| **The change map omitted self-orchestrating adapters.** | Claude subscription `:659`, Codex `:460` execute MCP calls inside their own loops. They currently pass only conversation identity, not customer authorization. | Extend adapter options/types and both dispatch paths, or explicitly exclude those providers until tested. |
| **`callTool` is not every MCP operation.** | `tasksProtocol.ts:232` sends follow-up requests directly; resources/prompts use their own service methods; task restart polls have no live customer authority. | Synchronous tools only initially; no customer resources/prompts/tasks, including unsolicited task results. Expand authorization when enabling them. |
| **`@conversation.id` is not uniform across nodes.** | Dynamic resolver `:60` allows explicit target; fixed presets are authoritative in tested path. Static `:199` skips trusted context/presets; live authored `@conversation.id` stayed literal. | Retain references for correlation; inject identity through verified runtime context for Model, Static and approval. Do not assume Static template expansion. |
| **Ingress accepts more than a customer chat message.** | Parser accepts `processNodeId`, app/skill/debug/routing fields; raw conversation creation accepts a flow snapshot. Generic local live history accepted bogus and missing bearers. | Dedicated narrow DTO, fixed workspace/graph revision, server-created owner binding before any state load, no generic route forwarding. |
| **There is already a deployment service-auth seam.** | `src/proxy.ts:53` uses the snapshot bearer in worker mode. Host/Origin-only guards are a different policy. | Reuse the admission pattern with separate bank execution/admin credentials. Do not give frontend a broad snapshot/control token. |
| **Runtime hiding is not a security sandbox.** | Authority is non-enumerable, but graph runtime and generic local tools have broader capabilities; persistent KV is scoped to flow/folder/global, not customer. | Private factory/provenance; no shell/files/global memory/customer `captureKv` in bank graph; validate all reachable subflows; redact serialization surfaces. |
| **The signed request was under-specified.** | Original plan bound subject/tool but not finalized normalized business arguments and lacked a concrete token validation profile. `tools.ts:240,252` resolves/normalizes arguments before sending. | Sign after final normalization; bind argument digest, separate issuer/audience/type/key domains, session checks and explicit retry/replay behavior. Keys stay outside interpolatable globals. |
| **Service API key was described too broadly as MCP authorization.** | Official MCP authorization is optional; conforming OAuth deployments include discovery and resource/token rules. Fixed API key does not demonstrate those. | Clearly label custom internal service authentication + delegation. Evaluate actual OAuth/token exchange separately. |
| **Per-batch and cache limits do not bound 500 active runs.** | ModelHandler `:3289,4243` groups one batch; lease pool explicitly omits execution caps; cache `:37` evicts terminal states only. | Central fair admission/queues and bank/provider/S3 aggregate bounds; measure active/paused state and stream buffers. |
| **Horizontal scaling needs state/events as well as locks.** | Conversation state, event bus, approval/elicitation/cancel registries and locks are local. | Start one process; multi-worker design must include conversation ownership/routing, durable state, event delivery and fenced failover. A distributed lock alone is insufficient. |
| **Source-date index completeness can silently fail.** | `If-Match` only checks files fetched. A newly added row in a previously excluded date is invisible to a stale index. Pipeline gold drops source-file lineage; its report manifest is aggregate lineage. | Version-pinned or enforced immutable source manifest; invalidation/atomic rebuild otherwise. Do not turn unavailable/stale index into an empty customer history. |

These are banking deployment blockers or design requirements. They do not establish that FLUJO's existing single-user local product violates its own advertised security contract.

## Source walk

Paths below are relative to the inspected FLUJO checkout. Files separated by commas within a directory entry share that directory. They give Fable concrete review locations without depending on our machine's paths.

| Concern | Files examined / key locations |
| --- | --- |
| HTTP/exposure/service auth | `src/proxy.ts:45`; `src/utils/http/`: `localRequest.ts`, `publicApiAllowlist.ts:88`; `src/app/api/_workspace.ts`; `src/backend/services/workspace/`: `workerMode.ts`, `snapshotControlAuth.ts` |
| Request parsing/run adapter | `src/app/v1/chat/completions/`: `route.ts:129,260`, `requestParser.ts:215`, `chatCompletionService.ts:81` and its streaming/resume variants |
| Conversation/read/control | `src/app/v1/chat/conversations/`: `route.ts:603`, `[conversationId]/route.ts:85`, `[conversationId]/respond/route.ts:110`; `src/app/v1/chat/events/route.ts`; resource/archive/recovery route inventory |
| Run authority/persistence | `src/backend/execution/flow/`: `runFlow.ts:375,547,1093,1226`, `types.ts`, `types/modelHandler.ts`, `executionAuthority.ts`, `persistConversationState.ts:56`, `loadConversationState.ts:70` |
| Approval execution | `src/backend/execution/flow/resumeAfterApproval.ts:82`; conversation respond route above; approval decision/tests and live registry resolution paths |
| Model/static/subflow dispatch | `src/backend/execution/flow/`: `handlers/ModelHandler.ts:3237,3860`, `nodes/StaticNode.ts:179,199`, `nodes/SubflowNode.ts:1703`, `handlers/subflowToolInvocation.ts:240`, `handlers/subflowDetachedInvocation.ts:223`, session/recovery helpers |
| Provider-owned loops | `src/backend/services/model/adapters/`: `claudeSubscriptionAdapter.ts:659`, `codexAdapter.ts:460`, `types.ts:158`; `src/backend/services/model/index.ts`; ModelHandler adapter options |
| MCP connection/dispatch | `src/backend/services/mcp/`: `index.ts:418,2040,2204,2381,2669`, `connection.ts:324,481`, `betaClient.ts`, `tools.ts:283`, `trustedToolContext.ts`, `proxyForward.ts:107` |
| MCP async/UI features | `src/backend/services/mcp/`: `elicitationContext.ts:36`, `elicitation.ts:89`, `clientTasks.ts`, `tasksProtocol.ts:232`, `remoteTaskResume.ts:145`, `sampling.ts`; tool-test/App routes |
| Shared state/capacity | `src/backend/execution/flow/`: `conversationExecutionLock.ts`, `conversationStateCache.ts:37`, `FlowExecutor.ts:105`, `engine/ExecutionEventBus.ts:58`, `resolveKvNodeRefs.ts:43`; `src/backend/services/mcp/mcpLeasePool.ts` |
| References/templates | `src/utils/resolveDynamicReferences.ts:60`, `src/utils/shared/promptRefs.ts`, `src/backend/execution/flow/handlers/ToolHandler.ts`; Static docs/implementation and dynamic-reference tests |
| S3 serving alternative | Hackathon `pipeline/bronze.py`, `silver.py`, `gold.py:36`, `lookup.py:24`, `report.py`, `docs/pipeline/quality_report.md` |

This is a targeted walk of banking trust, execution and capacity paths. It is not a review of every FLUJO feature or every route's implementation. Publication must still inventory the exact exposed banking routes and every allowed graph capability.

## Executed evidence

### Installed SDK carrier probe

```powershell
node scripts/review_mcp_transport.mjs --flujo-root C:/Users/Moe/Documents/GitHub/FLUJO
```

Actual clients send requests to an actual v1 MCP server transport via an in-process Fetch bridge. One client/transport is shared across concurrent calls; synthetic replies are deliberately reordered. The server checks request-specific assertion correlation, not a global current user.

| Probe | Result | What it establishes |
| --- | --- | --- |
| v1 `_meta` -> server handler `extra._meta`, 500 calls | Pass | Installed v1 preserves host metadata and call correlation. |
| v2 `_meta` -> same server, 500 calls | Pass | Installed v2 legacy negotiation preserves the custom metadata. |
| v2 custom per-request header, 500 calls | Pass | Header differs per call, assertion absent from request body; attempted Authorization override cannot replace service credential. |
| v1 per-request header negative control, 2 calls | Pass | v1 ignores this option, so header alternative needs v2 or a reviewed transport change. |
| Actual elicitation-context TS module, fixed workspace helper stub | Hazard reproduced | Server-keyed overwrite/cleanup semantics; does not simulate full live elicitation/SSE delivery. |

No network calls, signing, token validation, FLUJO principal propagation, retries, source reads or real provider work occur here. **500 carrier calls are not a 500-customer banking load test.** v2 modern negotiation remains untested.

### FLUJO existing tests

```powershell
node scripts/run-local-jest.cjs --selectProjects node --runInBand --runTestsByPath __tests__/flow/dynamicReferences.test.ts __tests__/mcp/trustedToolContext.test.ts __tests__/flow/conversationExecutionLock.test.ts __tests__/mcp/elicitation.test.ts __tests__/chat/applyApprovalDecision.test.ts __tests__/mcp/betaProtocolToggle.test.ts
```

**6 suites / 35 tests passed.** These corroborate existing reference/preset, ticket-context, lock and adapter behavior. They do not cover banking owners, overlapping elicitation, signatures or customer isolation. Existing mocked approval tests passing does not resolve the missing context finding.

### Live local instance

```powershell
python scripts/review_flujo_live.py --base http://localhost:4200
```

Two synthetic conversations ran concurrently through one authored Static flow. IDs stayed separate; Static `@conversation.id` remained literal. Conversation B history was readable with a bogus caller-A bearer/customer header and without a bearer. This demonstrates that the **generic local API offers no verified customer-owner boundary**, consistent with its single-user posture. It is not a claim that a future authenticated frontend exposes that route publicly. The created flow and both conversations were deleted and subsequent GETs returned 404. Two setup attempts also cleaned up their created resources; they revealed the required `flow-<name>` API prefix and Static reference behavior.

Aggregate evidence is saved in [FLUJO_BANKING_REVIEW_EVIDENCE.json](FLUJO_BANKING_REVIEW_EVIDENCE.json). The scripts fail if assertions do not hold; rerun against the exact implementation checkout when Fable evaluates it.

## Alternatives reassessed

1. **v1 signed metadata remains a reasonable first carrier** because it is the default FLUJO path and the actual SDK preserves it. Safety comes from provenance, signature, bank checks and the restricted profile, not metadata secrecy alone.
2. **v2 custom header is a real alternative now**, not a hypothetical future capability. SDK v2 2.0.0 supports it; `Authorization` is reserved. Add a bank-specific factory/config choice before using it so general MCP behavior stays explicit. Do not conflate changing credential transport with implementing customer ownership.
3. **Opaque capabilities are defensible:** server-issued random tokens plus a private owner/scope/expiry registry can replace JWTs. They trade crypto-profile complexity for registry availability and per-call lookup; conversation ID alone is not such a capability.
4. **Immutable per-customer clients can be secure.** The original wording was too categorical. They need subject/credential pool keys, lifecycle bounds and state/result ownership, and carry more connection overhead. Updating one shared config/header under concurrency remains unsuitable.
5. **Existing pipeline gold is an actual serving alternative.** Its local sequential lookup benchmark cannot prove 500 clients or direct-source semantics. Use it deliberately as a snapshot path or reuse lineage to build the direct-source index; it should not be ignored or mislabeled.
6. **Static confirmed-action flow reduces model authority.** Frontend registers exact consent; bank consumes it atomically and derives the case payload. This preserves graphical iteration while removing dependence on model-generated consent or generic tool approval as the authorization authority.
7. **OAuth/token exchange is the longer-term interoperable path.** It requires a real authorization-server integration and request-safe token transport; it is not accomplished by putting a static API key in Authorization.

## Primary web research and effect on the plan

Accessed 2026-09-27; no secondary technical commentary is used as authority.

- [MCP authorization, 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization): optional authorization, OAuth/discovery and audience validation when implemented; corrects the claim of automatic conformance from a service key.
- [MCP authorization, 2026-07-28 source](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/authorization/index.mdx): confirms transport/resource boundary; does not standardize our customer delegation envelope.
- [MCP security best practices](https://modelcontextprotocol.io/docs/2025-11-25/tutorials/security/security_best_practices): sessions are not authentication and token passthrough is prohibited; requires fresh audience-specific credentials and owner checks.
- [TypeScript SDK v2 request options](https://ts.sdk.modelcontextprotocol.io/v2/api/index/@modelcontextprotocol/client/) and [Streamable HTTP source](https://github.com/modelcontextprotocol/typescript-sdk/blob/main/packages/client/src/client/streamableHttp.ts): custom per-request headers, transport-owned reserved headers. Installed-code probes independently verify the subset proposed here.
- [RFC 8725](https://www.rfc-editor.org/rfc/rfc8725.html): fixed algorithm/issuer/audience/type validation and separate token profiles; incorporated into the explicit assertion contract.
- [RFC 8693](https://www.rfc-editor.org/rfc/rfc8693.html): distinguishes actor/subject delegation and audience-specific token exchange; evaluated as a future alternative, not an implemented protocol.
- [OWASP authorization](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html): default-deny and per-request object permission checks; informs ingress/owner gates.
- [OWASP transaction authorization](https://cheatsheetseries.owasp.org/cheatsheets/Transaction_Authorization_Cheat_Sheet.html): unique operation-bound consent and server enforcement; informs confirmation/idempotency design.
- [AWS GetObject](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html): version permissions and conditional/range reads; informs source-version and index-completeness contract.

## Handoff to Fable

Review the revised proposal against these questions:

1. Are frontend, ingress, run-context factory and bank signer trust boundaries sufficient under the stated customer adversary model?
2. Would you choose v1 `_meta`, v2 custom headers or opaque capabilities for the first implementation, and why?
3. Does the restricted protocol/graph profile close every customer-bearing path, especially elicitation, tasks, adapters, Static and approval?
4. Is the owner/session/consent store contract complete under creation races, revocation, retries, crashes and reconnects?
5. Which exact 500-run latency/error budgets and single-worker capacity should we test before needing distributed execution?
6. Can the source owner guarantee an immutable/versioned snapshot, or should the team explicitly choose the existing gold serving path?

**Open implementation gates:** no verified banking ingress, durable customer-owner registry, signed delegation, bank verifier, consent transaction or end-to-end 500-user test exists yet. Passing this review means the proposal is better grounded and ready for independent review; it does not mean those gates passed.
