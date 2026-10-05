# Actual customer comparison

Local deterministic copy on same facts; no task execution, provider, handoff or follow-up. Not a prior production runtime.

AI-authored cases and agent screening; independent human adjudication remains pending. HTTP success is separate from useful behavior.

| Case | Actual reply ms | HTTP | History exact | Observed model attempts / accepted | Actual response |
| --- | ---: | ---: | --- | --- | --- |
| es-selected | 31267.9 | 200 | True | unattributed | No pude completar la operación ni confirmar su resultado. Inténtalo nuevamente o solicita atención humana. El servicio está disponible en español y portugués. |
| pt-selected | 32244.1 | 200 | True | unattributed | No pude completar la operación ni confirmar su resultado. Inténtalo nuevamente o solicita atención humana. El servicio está disponible en español y portugués. |
| es-ambiguous | 31089.0 | 200 | True | unattributed | No pude completar la operación ni confirmar su resultado. Inténtalo nuevamente o solicita atención humana. El servicio está disponible en español y portugués. |
| pt-ambiguous | 31350.7 | 200 | True | unattributed | No pude completar la operación ni confirmar su resultado. Inténtalo nuevamente o solicita atención humana. El servicio está disponible en español y portugués. |
| es-human | 24960.6 | 200 | True | unattributed | No se pudo completar la consulta. Inténtalo de nuevo más tarde. Estoy disponible en español y portugués. |
| pt-human | 31376.0 | 200 | True | unattributed | No pude completar la operación ni confirmar su resultado. Inténtalo nuevamente o solicita atención humana. El servicio está disponible en español y portugués. |

n=6; latency range 24.96–32.24s; median 31.31s.

Baseline local CPU render times are in the JSON. They do not include authentication, network, bank reads, action, or follow-up; no speedup ratio is justified.

Useful answer, correct language and grounding require checking each exact reply against its display facts. No improvement percentage or resolved-dispute rate is inferred.
