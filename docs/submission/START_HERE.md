# Start here: Savia, powered by FLUJO

**The deterministic R0–R18 dispute engine is the foundation; voice and specialist
collaboration extend it.** The [complete engine guide](DISPUTE_ENGINE.md) maps
nineteen ordered rules, owned reads, clarification, explicit consent, simulated
intake with independently verified receipts, durable recovery and human handoff
to implemented source and executable tests.

**Ask once. Explore options. Return for a clear next step.** Savia helps a
customer understand an unfamiliar charge through Spanish or Portuguese
conversation, checked transaction facts, background investigation and saved
advice. The submission joins a polished customer experience to substantial data,
AI and orchestration engineering.

Open the [submission portal](https://savia-rc-2026.fly.dev/submission/) for the four
submission destinations: **Savia Pitch, Savia GitHub, Savia Video and Savia
Development Process**. The customer film shows the qualified recorded
demonstration in 140.611 seconds.

| Destination | Direct access |
| --- | --- |
| Savia Pitch | [Six-slide pitch](https://savia-rc-2026.fly.dev/submission/pitch/savia-final-pitch.html), [PDF](media/decks/final/savia-final-pitch.pdf), [editable PowerPoint](media/decks/final/savia-final-pitch.pptx) |
| Savia GitHub | [Repository](https://github.com/mario-andreschak/factored-hackathon-2026-mcg) |
| Savia Video | [Customer film](https://savia-rc-2026.fly.dev/submission/#video); [qualified 140.611-second demonstration](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/releases/download/v0.1.0-rc.2/savia-submission.mp4) |
| Savia Development Process | [Readable development account](DEVELOPMENT_PROCESS.md), [visual timeline](https://savia-rc-2026.fly.dev/submission/development.html) |

## A useful review route

1. **See the customer value.** Read the [pitch](https://savia-rc-2026.fly.dev/submission/pitch/savia-final-pitch.html)
   and [customer story](CUSTOMER_JOURNEY.md). Try the
   [fictional demo](https://savia-rc-2026.fly.dev) with **SAVIA-2026** at both the
   entry gate and fictional-profile login. Customers and bank intake are
   simulated; recorded model completions and native speech are real.
2. **Inspect a successful customer example.** The
   [two-reviewer recording and receipt](measurements/team-story-summary.md)
   show two actual model calls completing, useful evidence/next-step suggestions,
   customer-marked helpful closure and retained context. The
   [saved-recommendation supplement](measurements/saved-recommendations-native/README.md)
   records one explicit Listen click, 8.2 seconds of actual native audio, exact
   full-playback acknowledgment and recovery of the saved advice after reload.
3. **Inspect the core engine, then the expandable system.** The
   [deterministic workflow](DISPUTE_ENGINE.md) is a complete submission foundation
   independently of the avatar and swarm. Inspect its policy, runtime, response,
   consent and recovery modules before assessing conversational enhancements. The
   [architecture](../architecture/system-landscape.md) separates the customer
   experience, orchestration, banking authority and data plane. The
   [FLUJO capacity evidence](measurements/INFRASTRUCTURE_CAPACITY.md) includes a
   real 300-request flow test with 300/300 correct references and collaboration
   across 18 live Fly sandboxes. The
   [fleet connector](assistant/FLEET_CONNECTOR.md) implements durable dispatch,
   recovery and independent-result verification for Savia's larger team design.
4. **Follow the data into the product decisions.** The
   [pipeline receipt](../pipeline/quality_report.md) accounts for 5,899,720 rows
   across six table families and produces customer-sharded serving data,
   analytics and an ML dataset. The [ML account](../../ml/README.md) explains
   why template-heavy source transcripts required a separate held-out intent
   diagnostic. The product uses owned transactions rather than unreliable
   historical complaint links.
5. **Assess engineering through executable evidence.** The new
   [100 concurrent Luna request benchmark](measurements/luna-100/README.md)
   records 100/100 completed, exact-correct and bounded-safe ES/PT fixture
   decisions, with published prompts, outputs, independent oracle and timings.
   The [public offline replay](../review/PUBLIC_EVIDENCE.md) passes 67/67 source
   checks plus seven pipeline and four analytics invariants. Use the
   [evidence map](EVIDENCE_MAP.md) for source files, tests, exact denominators,
   reproduction commands and the boundary of each result. The
   [verified presentation and host outcomes](measurements/verified-outcomes/README.md)
   add canonical result narration and separate current host receipts from planned
   workflow outcomes, with 183 passing tests and 195 subtests. The
   [development process](DEVELOPMENT_PROCESS.md) connects those decisions to
   implementation, review and deployment. The
   [ElevenLabs comparison](ELEVENLABS_COMPARISON.md) evaluates the alternatives
   against the same product requirements and dates its findings.

For a local preview, serve [the portal source](../../web/submission/index.html)
using the repository's submission build/run instructions. GitHub displays HTML
source; the hosted links above provide the designed reading experience.

## What makes the implementation substantial

Savia carries a question beyond one chat turn: owned selected facts, durable
inquiry state, two different reviewer roles, meaningful events, explicit
customer acknowledgment and recoverable saved suggestions. The host owns
authentication, consent and verified simulated receipts. Language output has
bounded authority. Quiet follow-up and exact playback acknowledgments make
background work and speech observable rather than inferred from animation.

The data work also changed the design. All 4,425,008 served transactions passed
customer/product ownership checks, while all 44,570 populated historical
complaint-product links crossed ownership. The team found only 42 distinct
normalized transcript texts across 171,321 rows, and every one of the 2,946 test
texts also appeared in training. Recognizing those limits led to fresh
transaction grounding and a separately authored, frozen ES/PT router evaluation.

FLUJO contributes a reusable foundation: generic chat, flows, tools, MCP,
execution, workspace and recovery interfaces. Its load and sandbox evidence
extends beyond the two-reviewer customer example. Banking code belongs in this
repository, Banking MCP or the isolated hackathon branch, following the
[product boundary](../FLUJO_PRODUCT_BOUNDARY.md). That separation makes Savia
one application of the orchestration platform and keeps the platform useful for
other domains.

## For an agent reviewing a fresh checkout

Read this guide, the [evidence map](EVIDENCE_MAP.md), the
[development process](DEVELOPMENT_PROCESS.md) and the architecture before
evaluating individual archival reports. Then inspect the linked implementations
and run the relevant offline checks. All paths below are repository-relative;
private records and credentials are unnecessary for the source checks.

- Product and voice: `frontend/src/avatar/`, `frontend/server/conversation.py`,
  `savia_assistant/service.py`, and their UI/API tests.
- Orchestration and extensibility: `savia_assistant/fleet.py`, the fleet
  connector contract, generic MCP graph and infrastructure receipts.
- Banking correctness: `dispute_workflow/`, `banking_mcp/`, policy contracts,
  ownership, consent, replay and receipt-recovery tests.
- Data/ML/analytics: `pipeline/`, `ml/`, `analytics/`, published aggregate
  receipts and synthetic regression fixtures.

Match claims to the date, source and workload in their receipts. A source test,
a recorded customer journey, a capacity test and a product architecture answer
different questions. Earlier failures and fixes remain in the archive so those
results can be audited. The recorded two-reviewer customer success and tested
FLUJO infrastructure remain evidence in their own scopes.

The ten-team, ten-conversation customer investigation is the larger integration
target. Its October 5 attempt reached the original native root but its first
model request encountered a disabled provider workspace; it produced no
accepted fleet result. The [capacity report](measurements/INFRASTRUCTURE_CAPACITY.md)
preserves that exact distinction. Real bank resolution, human pickup,
customer push/email delivery and multi-day reliability require their own
acceptance evidence. These boundaries accompany a working recorded product,
an implemented integration and measured infrastructure.
