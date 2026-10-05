# Final deterministic dispute-core qualification

**1,078/1,078 checks passed, with zero failures, errors or skips.** This fresh
October 5 run exercises the real R0–R18 dispute policy, workflow/state machinery,
guarded replies, owned bank reads, consent/action-host contracts, durable receipts
and handoff using generated local fixtures. It made no provider requests or live
banking actions.

The deterministic dispute engine is Savia's core. Voice and larger swarm
orchestration are extensions with separate evidence. These core checks establish
the implemented decision and data/authority contracts independently of either
extension.

## What the checks exercise

- Ordered R0–R18 and query-policy decisions, clarification, security and explicit
  human requests, including independent acceptance observations through the real
  runtime and state store.
- Spanish/Portuguese reply grounding, allowed status/merchant facts, rejection of
  invented facts, sensitive credential collection and unauthorized outcome claims.
- Customer-owned bank reads, source evidence, consent-scoped action requests,
  exact receipt read-back, prior-receipt integrity and replay/restart behavior.
- Query-scoped durable state, validated handoff packets and customer ownership,
  including local process/concurrency tests on fictional stores.

| Suite | Passing checks |
| --- | ---: |
| `test_case_handoff_receipts.py` | 54 |
| `test_case_handoff_schema.py` | 9 |
| `test_dispute_acceptance.py` | 97 |
| `test_dispute_action_host.py` | 8 |
| `test_dispute_bank_read.py` | 76 |
| `test_dispute_handoff.py` | 102 |
| `test_dispute_policy.py` | 83 |
| `test_dispute_prior_receipts.py` | 16 |
| `test_dispute_query_policy.py` | 51 |
| `test_dispute_query_state.py` | 10 |
| `test_dispute_response.py` | 519 |
| `test_dispute_source_reads.py` | 17 |
| `test_dispute_state.py` | 34 |
| `test_owned_case_projection.py` | 2 |

## Exact source and execution

The clean tested checkout was
`1e0bb0924ea4d9ac21300c9e04f242d4fe475aee`. Application/core/test blobs were
confirmed identical to integrated source
`effd6ed35719ecd913021e6a805edc1c466ee76c` before execution. The before/after
184-file source manifest and Git identity are unchanged. Its SHA-256 is
`677e0d95f92fe2527ad815030e152e5d0a081bf26b9162cea07af300a5ad40ef`.

Pytest reported 123.14 seconds; the guarded process, source verification and
receipt capture took 123.824 seconds. Environment: Python 3.13.1 on Windows,
pytest 9.1.1. The [receipt](receipt.json) records every measured dependency,
the exact 14-suite command, timestamps, JUnit counts and original artifact hashes.
The harness disables external pytest plugins, bytecode/cache writes and external
Python DNS/socket connections. No external attempt was observed.

- [Source manifest](source-manifest.json)
- [Later-source congruence](source-congruence.json)
- [Pytest output](pytest-output.txt)
- [JUnit](junit.xml)
- [Network guard](network-guard.json)
- [Exact qualification harness](core-engine-run.py)

The original receipt and console output are copied unchanged. Public JUnit omits
the machine hostname and masks two synthetic sensitive-input parameter values; [publication manifest](publication-manifest.json) records
the original JUnit hash and the public derivative hash.

The later-source comparison proves all 39 dispute/banking domain files and
executed core-test files are byte-identical at `f3c57b26` and `ce8f6c80`.
Changed deployment-transition, graph and other unexecuted test files are listed
explicitly; this does not transfer the original pass to either entire later HEAD.

## Reproduce

Use an isolated Python environment with `requirements-dispute.txt` and
`pytest==9.1.1`. From a clean checkout, select an unused scratch output directory:

```powershell
python docs/submission/measurements/core-engine-final/core-engine-run.py --repo . --expected-head (git rev-parse HEAD) --out .tmp/core-engine-replay
```

The harness refuses a different expected HEAD or a dirty checkout, executes the
same 14 suites, and requires unchanged source hashes afterward. To replay the
original source exactly, use a separate clean checkout of the commit above and
invoke this public harness against it. Later documentation-only commits can have
a different Git identity; compare the source manifest when assessing congruence.

This is source qualification over fictional fixtures and controlled observations.
It does not establish real-bank resolution, a current deployed customer journey,
language-provider quality, installed native-flow execution or complete
Windows/Linux workflow coverage. Those measurements retain their own receipts.
