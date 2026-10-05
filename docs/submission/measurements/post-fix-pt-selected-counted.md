# Actual customer comparison

Local deterministic copy on same facts; no task execution, provider, handoff or follow-up. Not a prior production runtime.

AI-authored cases and agent screening; independent human adjudication remains pending. HTTP success is separate from useful behavior.

| Case | Deterministic baseline copy (local CPU ms) | Actual reply (HTTP ms) | Agent usefulness screening | HTTP / exact history | Model attempts / transport completions |
| --- | --- | --- | --- | --- | --- |
| pt-selected | O registro mostra 4280.75 MXN com data 2026-10-02. O estabelecimento registrado é «Nébula Market». O estado registrado é aprovado. (0.009 ms) | Vamos conferir esta cobrança. O registro mostra 4.280,75 MXN, de 2 de outubro de 2026. O estabelecimento registrado é «Nébula Market». O estado registrado é aprovado. Isso ajuda a identificar o lançamento. Se não reconhecer o estabelecimento, conte o que não corresponde à sua compra. (18807.5 ms) | useful: Single exact post-fix fresh-login retry now explains the already-selected facts and asks what does not match. The displayed answer is a trusted host selected-fact fallback, not accepted free-form model generation. | 200 / True | 11 / 11 |

n=1; latency range 18.81–18.81s; median 18.81s.

Baseline local CPU render times are in the JSON. They do not include authentication, network, bank reads, action, or follow-up; no speedup ratio is justified.

The baseline renders selected facts or asks for missing date/amount. Its usefulness is limited to that copy behavior; it cannot execute a team request, bank action, handoff or durable follow-up. No baseline quality rate is inferred.

Useful answer, correct language and grounding require checking each exact reply against its display facts. No improvement percentage or resolved-dispute rate is inferred.
