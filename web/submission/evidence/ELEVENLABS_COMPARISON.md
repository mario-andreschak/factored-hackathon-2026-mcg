# Savia and ElevenLabs: voice quality and case follow-through

**Savia's product is a persistent customer inquiry:** checked facts, permitted actions, multiple perspectives and useful results when the customer returns. The integrated Spanish/Portuguese voice is its front door. The strongest evidence is the completed customer story, not a proposed agent count.

ElevenLabs is a useful commercial reference for natural voice. Its [September 28 announcement, updated October 5](https://elevenlabs.io/blog/eleven-v4-turbo-in-elevenagents), presents expressive speech, approximately 100 ms median model inference, more than 90 languages, and a financial-services transaction-dispute demonstration. It describes a combined speech, transcription and turn-taking stack. These are vendor-reported capabilities; we have no matched performance comparison.

## What judges can inspect in Savia

| Customer or bank need | Implemented Savia capability | Demonstrated or executable evidence |
| --- | --- | --- |
| Understand an unfamiliar charge | Customer-owned selected facts and bounded explanation | [Actual grounded reply](measurements/team-story-summary.json), [customer story](CUSTOMER_JOURNEY.md) |
| Hear useful guidance | Voice inside the same assistant; full-playback acknowledgement and queued completed update | [Integrated native capture](measurements/intended-savia-native/README.md), [saved recommendation speech](measurements/saved-recommendations-native/README.md) |
| Explore more than one perspective | Evidence and next-step reviewers; saved suggestions with real work status | Two actual completed model calls and retained results in [team-story-summary.json](measurements/team-story-summary.json) |
| Return without starting over | Durable inquiries, saved suggestions, archived exact conversation and explicit helpful closure | [Recorded return visit](CUSTOMER_JOURNEY.md), [retained context measurements](measurements/MEASURED_RESULTS.md) |
| Keep actions under bank authority | Host-resolved owned selections, explicit consent, bank-owned receipt and readback, restart/idempotency checks | [Action host](../../dispute_workflow/action_host.py), [bank action tests](../../tests/test_dispute_action_host.py) |
| Change models or deployment without changing the banking contract | Application-owned banking domain behind generic FLUJO chat/flow/tool/MCP interfaces; separate language and action capabilities | [Product boundary](../FLUJO_PRODUCT_BOUNDARY.md), [direct MCP contract](../../frontend/DIRECT_MCP.md), [system landscape](../architecture/system-landscape.md) |
| Inspect operational evidence | Immutable data snapshots, row accounting, ownership exclusion, public fixture replay and fixed diagnostic baselines | [Public replay](../review/PUBLIC_EVIDENCE.md), [pipeline contract](../../pipeline/README.md) |
| Inspect a new subscription-backed provider option | 100 concurrent local GPT-6 Luna requests over predeclared ES/PT ownership/grounding fixtures | [Prompts, oracle, outputs and timings](measurements/luna-100/README.md); no bank writes or Modal execution |

## How to present the difference

The commercial voice showcase sets a useful standard for conversation. Savia's bank-pilot proposal centers on the inquiry lifecycle: retain evidence, let specialists explore it, take a consented permitted step, and bring the customer back to a useful result. A bank can inspect and extend the application-owned policy, data and action boundary independently of the voice or language provider.

This is a product positioning comparison, not a claim that ElevenAgents lacks workflows, tools, analytics or handoff. Savia has not established better voice quality, lower latency, lower cost, broader language support or greater compliance than ElevenLabs. Model inference latency and complete customer-response latency use different boundaries.

## Completed prototype and extension scope

The frozen submission shows grounded facts, two completed reviewers, saved results, native speech and a return visit. A separate real-clock receipt check ran after 1,800 seconds without a duplicate visible update. These successes retain their source and workload identities in the [release report](RELEASE_CANDIDATE.md).

The ten-team/100-conversation connector is an extensible architecture with implemented source. Its later customer run failed at the initial root inference call when its provider workspace was disabled. That record qualifies the extension's state; it does not relabel the completed two-reviewer submission as a failed demo. Historical collaboration with 18 live sandboxes and reference-code load tests remain separate [infrastructure evidence](measurements/INFRASTRUCTURE_CAPACITY.md).

The local Luna test exercises 100 concurrent provider requests, not 100 collaborative customer agents. Bank data and actions are fictional. Live human pickup, a real-bank refund, push/email delivery, measured repeat-contact reduction and sustained multi-day operation remain bounded pilot objectives.

**Pilot question:** does persistent, grounded follow-through reduce repeat contacts and improve useful answers and human handoff at an acceptable cost per case? Savia makes that question implementable and measurable; the present evidence supports the prototype, without inventing pilot outcomes.
