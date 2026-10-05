# Actual customer comparison

Local deterministic copy on same facts; no task execution, provider, handoff or follow-up. Not a prior production runtime.

AI-authored cases and agent screening; independent human adjudication remains pending. HTTP success is separate from useful behavior.

| Case | Deterministic baseline copy (local CPU ms) | Actual reply (HTTP ms) | Agent usefulness screening | HTTP / exact history | Model attempts / transport completions |
| --- | --- | --- | --- | --- | --- |
| es-selected | El registro muestra 4280.75 MXN con fecha 2026-10-02. El comercio registrado es «Nébula Market». El estado registrado es aprobado. (0.007 ms) | La transacción identificada es una compra en **Nébula Market** por **4280.75 MXN**, realizada el **2026-10-02** con tu tarjeta terminada en **4381**. Ya existe el reclamo **CMP-SBX--HCaKBpE**, con estado **received**, relacionado con este movimiento en el entorno de prueba. No se crea otro reclamo. El proceso actual se encuentra en revisión, sin plazos ni resultados garantizados. (9338.0 ms) | useful: Correct merchant, date, amount/currency and existing simulated folio; no duplicate case. Chat gives limited next-step detail; team result supplies receipt comparison and folio advice. | 200 / True | 6 / 6 |
| pt-selected | O registro mostra 4280.75 MXN com data 2026-10-02. O estabelecimento registrado é «Nébula Market». O estado registrado é aprovado. (0.012 ms) | Consulta 1: Para que eu possa localizar a transação que você não reconhece, por favor, informe o valor e a data aproximada da compra.  Consulta 2: Preciso esclarecer a solicitação. Informe: valor, data. (12970.1 ms) | not useful: Selected date/amount were supplied, but two rewritten subqueries needlessly ask for them again; no useful selected-fact explanation. | 200 / True | 10 / 10 |
| pt-ambiguous | Qual data e valor aparecem no lançamento que você quer revisar? (0.010 ms) | Para localizar a cobrança que você não reconhece, por favor, informe a data e o valor da transação. Com esses dados, poderei verificar os detalhes em sua conta. (7104.8 ms) | useful: Correct Portuguese clarification asks for the missing date and amount; no completion or handoff is asserted. | 200 / True | 6 / 6 |

n=3; latency range 7.10–12.97s; median 9.34s.

Baseline local CPU render times are in the JSON. They do not include authentication, network, bank reads, action, or follow-up; no speedup ratio is justified.

The baseline renders selected facts or asks for missing date/amount. Its usefulness is limited to that copy behavior; it cannot execute a team request, bank action, handoff or durable follow-up. No baseline quality rate is inferred.

Useful answer, correct language and grounding require checking each exact reply against its display facts. No improvement percentage or resolved-dispute rate is inferred.
