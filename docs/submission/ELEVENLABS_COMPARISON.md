# Savia: the bank-controlled case service

A polished voice is not a case. ElevenLabs is a commercial voice platform. Savia is the bank-controlled service: owned facts, deterministic policy, consent, receipt, follow-up, swarm investigation. We built that in ten days with two people.

Savia starts with a customer saying, “I don't recognize this transaction.” The complete R0–R18 engine checks the selected charge, applies ordered policy and prepares a clear next step. Voice and specialist perspectives extend that engine. The customer returns to the same inquiry, checked facts and saved recommendations.

## Confirm once. Keep the control.

Confirm once. Savia blocks the owned card, writes a durable status, and rereads an independent receipt. Asking never writes. Foreign cards, missing consent, and tampered receipts are refused.[^card-ledger]

The blocked status survives a new login. Spanish and Portuguese requests open the same consent flow. One hundred concurrent confirmations produce exactly one block and one receipt. [Card control and concurrency evidence](measurements/CARD_BLOCK_VERIFICATION.md) · [Pinned public acceptance](measurements/card-block-live/README.md).

## One customer voice. Ten teams behind it.

300/300 concurrent FLUJO. 18 sandboxes live together. The customer path we recorded is two reviewers; the architecture is ready to scale. [Foundation capacity](measurements/INFRASTRUCTURE_CAPACITY.md) · [Recorded customer story](CUSTOMER_JOURNEY.md) · [Workload identities and original results](measurements/MEASURED_RESULTS.md).

## What the bank can inspect

| Customer or bank need | Savia capability | Source and measured evidence |
| --- | --- | --- |
| Understand an unfamiliar charge | Owned transaction facts, ordered decision rules and bounded explanation | [Complete engine](DISPUTE_ENGINE.md), [actual grounded reply](measurements/team-story-summary.json) |
| Hear useful guidance | Voice in the same assistant, acknowledged playback and queued completed updates | [Canonical ES/PT guidance and playback](measurements/native-canonical-live/README.md), [native voice capture](measurements/intended-savia-native/README.md), [saved recommendation speech](measurements/saved-recommendations-native/README.md) |
| Compare perspectives and return | Two completed reviewers, durable inquiries, saved suggestions and a return visit | [Customer story](CUSTOMER_JOURNEY.md), [original receipts](measurements/MEASURED_RESULTS.md) |
| Control the card action | Host-resolved owned selection, explicit consent, durable status and independent receipt readback | [Action host](../../dispute_workflow/action_host.py), [confirmed public action](measurements/card-block-live/README.md) |
| Control models and deployment | Banking authority behind generic chat, flow, tool and MCP interfaces | [FLUJO platform guide](FLUJO_PLATFORM_EVIDENCE.md), [product boundary](../FLUJO_PRODUCT_BOUNDARY.md), [direct-host contract](../../frontend/DIRECT_MCP.md) |
| Trace the data and operating decisions | Immutable snapshots, row accounting, ownership exclusion and reproducible diagnostics | [Public replay](../review/PUBLIC_EVIDENCE.md), [measured operating decisions](../review/OPERATING_DECISIONS.md) |
| Inspect provider capacity | 100/100 grounded ES/PT Luna fixture decisions from concurrent local submissions | [Workload, oracle, baseline, outputs and timings](measurements/luna-100/README.md) |

## The bank pilot

Measure repeat contacts, useful answers, handoff quality and cost per case. Start with transaction disputes, preserve the evidence, and expand the service against observed customer value. Ask once. Savia follows through.

[^card-ledger]: *Demo ledger. Same admission rules a production host would use.*

## If asked: the commercial reference and measurement boundaries

ElevenLabs' [September 28 announcement, updated October 5](https://elevenlabs.io/blog/eleven-v4-turbo-in-elevenagents), reports expressive speech, approximately 100 ms median model inference, more than 90 languages, a financial-services transaction-dispute demonstration, and a combined speech, transcription and turn-taking stack. Those are vendor-reported capabilities. The supplied [transaction-dispute video](https://youtu.be/1QJTfaaxVag) provides the commercial voice reference.

The 300/300 result measures concurrently submitted FLUJO reference-code requests, including queueing. Luna's 100 turns measure a separate ES/PT fixture workload; its deterministic baseline also achieves 100/100. The recorded customer collaboration has two completed reviewers. Exact 100-agent customer completion remains a qualification step. Each result retains its source and denominator in the linked receipts.

Demo customers and the card ledger are fictional. Savia does not move real money, assign a live banker, or claim measured ROI.
