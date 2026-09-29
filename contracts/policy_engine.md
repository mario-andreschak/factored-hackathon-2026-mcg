# Motor de políticas determinista v3



Documentar las reglas **en orden de precedencia** (gana la primera que aplique):

| ID | Condición | `response_mode` | Efectos |
|---|---|---|---|
| R0 | `session.authenticated = false` o `session.expired = true` | `AUTH_REQUIRED` | Sin herramientas |
| R1 | `attack.deceptive = 1` o `attack.inappropriate = 1` | `BLOCKED` | Registrar evento de seguridad |
| R2 | `slots.foreign_customer_reference = true` (el usuario pide datos de otro cliente) | `BLOCKED` | Contar como intento de acceso no autorizado |
| R3 | `pending.type = awaiting_confirmation` y `clarification.resolution_type = CONFIRMED` | → ejecutar `create_complaint` → `get_complaint` | `ACTION_DONE` si se verifica; si no, `ACTION_UNVERIFIED` → R10 |
| R4 | `pending.type = awaiting_confirmation` y `DENIED` | `ACTION_CANCELLED` | Limpiar `pending` |
| R5 | `pending.type = awaiting_selection` y `SELECTED` | Continuar desde R8 con el candidato elegido | |
| R6 | `intent ∈ {GREETING, PERSONALITY}` | `SMALL_TALK` | |
| R7 | `intent = OOD` | `OUT_OF_SCOPE` | |
| R8 | `intent = HUMAN_REQUEST` o `emotional_context = Emergencia` | `HANDOFF` | `reason_code = customer_request \| emergency` |
| R9 | Fallo de herramienta tras `tool_retries` | `TOOL_ERROR` | Si `tool_failures ≥ 2` en la sesión → `HANDOFF` |
| R10 | `DISPUTE`/`INQUIRY` sin ningún criterio de búsqueda (sin monto, sin fecha, sin id, sin comercio) | `CLARIFY` | `missing_fields = ["amount","date"]` |
| R11 | `match_count = 0` | `NO_MATCH` | Si `no_match_attempts ≥ max` → `HANDOFF` |
| R12 | Varios candidatos sin target vigente; o señal de duplicado persistente en el target | `CLARIFY` / `HANDOFF` | Sin target: selección con hasta `max_candidates_to_show` candidatos; si hay más, pedir filtro. Con target y señal: `duplicate_review` |
| R13 | Target propio vigente e `intent = TRANSACTION_INQUIRY` | `INFORM` | |
| R14 | Target propio vigente, `DISPUTE` y antigüedad mayor que `dispute_window_days` | `OUT_OF_POLICY` | Ofrecer handoff |
| R15 | Target propio vigente, `DISPUTE` y `duplicate_check = exact_open_case` | `INFORM_EXISTING_CASE` | **No** crear |
| R16 | Target propio vigente, `DISPUTE` y riesgo alto (`fraud_score ≥ umbral` o `amount_usd ≥ umbral` o ≥ N no reconocidas en 24 h) | `HANDOFF` | `reason_code = high_risk`; crear handoff y verificarlo |
| R17 | Target propio vigente, `DISPUTE` y todos los demás guardas aprobados | `CONFIRM_ACTION` | `pending = awaiting_confirmation`, `proposed_action = CREATE_COMPLAINT` |
| R18 | `intent = COMPLAINT_STATUS` | 0 reclamos → `NO_MATCH`; varios → `CLARIFY`; uno → `INFORM` | |

- Cada decisión registra `rule_ids` en `policy_decision`; es la explicación auditable.
- Target propio vigente significa un único candidato propio releído, obtenido por búsqueda completa de una coincidencia o por selección válida del snapshot mostrado. No implica que match_count haya cambiado.
- Con varios candidatos resolver primero la selección; si persiste una señal de duplicado en el target, revisión humana. Con un solo candidato propio releído y señal persistente, duplicate_review directo; no pedir una elección inútil ni repetir R12.


## Semántica normativa y correcciones de integración

La tabla anterior es el inventario R0–R18. Esta sección precisa los guardas y transiciones: prevalece sobre la abreviatura del plan. No es una implementación del motor.

1. R0, R1 y R2 preceden siempre cualquier lectura privada o escritura, incluso al confirmar. R2 lee turn.unauthorized_reference (preprocesador) OR turn.slots.foreign_customer_reference. Un ID ajeno no se consulta. Reiniciar action.authorized=false al cambiar de turno.
2. R3 es una transición, nunca una autorización por el solo texto CONFIRMED. Verificar tipo de pending, target, snapshot, sesión, pertenencia, vigencia de 600 segundos configurables, misma transacción, estado Approved, ventana, ausencia de duplicado y señales de riesgo actuales. Releer esos datos bajo el scope del cliente antes de autorizar; si cambiaron, volver a la regla aplicable y pedir nueva confirmación si procede. Persistir idempotency_key antes de escribir.
3. R3 terminal: action.executed AND action.verified => ACTION_DONE; ejecutada o resultado de escritura desconocido sin verificación => ACTION_UNVERIFIED y handoff.required=true, reason_code=action_unverified. Fallo confirmado sin escritura => TOOL_ERROR/R9. Nunca volver a execute_action si action_attempted=true; recuperar por clave idempotente antes de cualquier reintento. La flecha a R10 del plan era incorrecta: R10 no trata verificaciones.
4. R4 cancela, revoca autorización y limpia pending. R5 solo acepta un ref presente en el snapshot mostrado; fija workflow_state.transaction_id, conserva candidate_snapshot_hash, relee sus datos y reclamos dentro del cliente, y continúa desde R8. La selección nunca confirma la creación. transaction_unique indica un target elegido y releído, no que desaparecieron otros resultados: conservar el match_count original. Para pending.candidate_type=complaint, continuar R18. Si cambió el snapshot invalidar la selección y pedir una nueva, sin reutilizar consentimiento.
5. UNCLEAR con pending vigente => CLARIFY; sumar una vez por turno; al alcanzar max_clarification_attempts => HANDOFF, reason_code=clarification_exhausted. NEW_REQUEST limpia pending y vuelve a detect_intent. Pending expirado exige nueva identificación/confirmación.
6. R6/R7 solo aplican sin una solicitud de negocio activa. R8 también considera turn.human_requested, detectado en el mensaje original por código, para respetar una petición de asesor combinada con disputa. Emergencia significa riesgo activo, no una mera mención de fraude.
7. R9 distingue reintentos por llamada (tool_retries) de fallos agotados acumulados (counters.tool_failures). Al alcanzar max_tool_failures => HANDOFF/tool_failure. Error de recuperación de políticas no transforma datos ausentes en hechos.
8. R10–R17 solo aplican a TRANSACTION_DISPUTE/TRANSACTION_INQUIRY y resultados de búsqueda status=ok. R10 exige workflow_state.search_criteria_present=false; antes de buscar se pueden pedir criterios y evitar una lectura innecesaria.
9. R11 aumenta no_match_attempts una vez por turno. Al alcanzar max_no_match_attempts => HANDOFF/no_match_exhausted. R12 pide elegir si hay varios candidatos y ningún target vigente. Mostrar hasta max_candidates_to_show; si hay más pedir filtro adicional. Con target propio elegido/releído, R13–R17 evalúan ese target sin reescribir match_count ni volver a pedir la misma elección. Si persiste possible_duplicate_of o conflicting_duplicate en el target, HANDOFF/duplicate_review con rule_ids=["R12"], también con un solo candidato visible; no crear ni colapsar registros. Incluir la selección y la ambigüedad en el paquete verificado. Guardas R0–R2 y petición humana R8 conservan precedencia.
10. R13 permite informar cualquier estado observado sin prometer ejecución. R14, además de antigüedad >dispute_window_days, impide disputar estados fuera de allowed_transaction_statuses. Campos esenciales nulos => CLARIFY; riesgo o control de duplicados incompleto => HANDOFF/missing_evidence, nunca riesgo bajo por defecto.
11. R15 requiere duplicate_check=exact_open_case y vínculo sandbox cliente/transaction_id verificado; solo entonces fija existing_case y permite INFORM_EXISTING_CASE. Un reclamo histórico propio sin vínculo no activa R15: historical_uncertain/incomplete => HANDOFF/missing_evidence antes de R17, sin atribuirlo a esta transacción. clear_in_snapshot permite continuar sin prometer ausencia fuera de las fuentes del prototipo. R16 consume exclusivamente risk_signals internos, conversión USD verificada y unrecognized_count_24h de reportes del cliente (no todas sus compras).
12. R17 requiere todos los guardas aprobados; guarda el snapshot, intent y created_turn_id. requires_confirmation=true no equivale a action.authorized.
13. R18 consulta reclamos, no transacciones: si hay complaint_id, get_complaint; si no, list_customer_complaints. Cero => NO_MATCH, uno => INFORM, varios => CLARIFY con candidate_type=complaint y refs con complaint_id. Releer el caso elegido por get_complaint. No usar match_count transaccional ni exigir transaction_id para este dominio; el listado de estado nunca concede clearance de escritura.
14. HANDOFF no es sinónimo de transferencia creada. generate_handoff_summary -> create_handoff (una ejecución idempotente + verificación); fallo => mantener created=false y generar texto de revisión requerida. ACTION_UNVERIFIED mantiene ese modo al crear el handoff; no se sobrescribe por HANDOFF.
15. R14 puede ofrecer derivación; solo se crea si el usuario la solicita, aplicando R8. Toda decisión incluye rule_ids y reason_code. Las ampliaciones missing_evidence, clarification_exhausted y duplicate_review son códigos internos documentados.

La búsqueda por defecto histórica no modifica la elegibilidad: calcular antigüedad con turn.current_date real y fecha del evento, según dispute_window_anchor=current_date. Una transacción encontrada puede estar fuera de los 120 días. current_timestamp y expiración nunca se congelan al snapshot.

## Campos derivados y configuración

policy_engine lee session.*, turn.attack, turn.intent, turn.emotional_context, turn.slots, turn.clarification, turn.human_requested, turn.unauthorized_reference, turn.current_date y workflow_state.*, además de tool_results.*. match_count/candidates/risk_signals provienen de tool_results.search_transactions; el target se revalida por get_transaction; los reclamos de get_related_complaints/get_complaint/list_customer_complaints. Todos los valores y umbrales están en config/policy_rules.yaml. Comparar fechas del evento, no process_date.

El preprocesador calcula unauthorized_reference antes de redactar o enviar datos privados al LLM; redacta documentos, nombres completos, teléfonos, direcciones e IDs de cliente dejando marcadores semánticos. La misma protección se aplica a histórico, campos libres de herramientas y chunks. Mantener indicación de referencia ajena, pero no el identificador sensible.

## validate_response

Entrada: JSON del generador, response_mode, effective_language, structured_data, workflow_state saneado y policy_context. Validar estructura cerrada: message:string; language:es|pt; arquetipos:lista permitida; chunk_ids:list[str]; data_sources:list[str]; grounding_violation:0|1. grounding_violation=1 usa fallback; no se convierte en evidencia.

- Extraer IDs con patrón (?<![A-Z0-9])(?:TRX|CMP|HOF)-[A-Z0-9-]+ y exigir pertenencia al conjunto exacto de IDs de structured_data/workflow_state. También comparar los montos, monedas y fechas citados con hechos de entrada; no aceptar números inventados.
- Frases de éxito configurables se buscan tras normalizar Unicode/casefold. En modos distintos de ACTION_DONE prohibir éxito de creación de reclamo, aun si está en una pregunta o negación: los textos de fallback evitan esa ambigüedad.
- ACTION_DONE requiere authorized=true, executed=true, verified=true, result_id no nulo y coincidente con relectura. Un estado inconsistente usa mensaje neutral de ACTION_UNVERIFIED, nunca una plantilla de éxito.
- HANDOFF solo afirma derivación creada si handoff.created=true tras relectura. La excepción de éxito para handoff se valida separadamente de las frases de creación de reclamos.
- language de salida debe ser effective_language (pt si entrada pt; es para es/other). Para other se añade aviso de idiomas. Esta normalización resuelve la incompatibilidad de exigir igualdad con other y responder en español.
- chunk_ids debe ser subconjunto de los chunk_id de policy_context; data_sources subconjunto de las fuentes permitidas de structured_data. Prohibir campos privados, detalles de herramientas y umbrales de riesgo en message.
- Primer fallo: incrementar turn.validation_attempts, guardar códigos seguros en turn.validation_errors y reintentar generate una vez con instrucción adicional del sistema. No añadir otra variable Jinja no declarada; el adaptador añade el mensaje de corrección.
- Segundo fallo/error LLM: safe_fallback usa resources/prompts/fallback_templates.yaml según modo e idioma efectivo, solo con datos verificados. Volver a validar los placeholders; si faltan o falla la plantilla, emitir el texto neutral de TOOL_ERROR en ese idioma. No bucles de reintentos.
- El chequeo de frases es conservador y no prueba ausencia de toda alucinación semántica. Registrar su cobertura y falsos positivos en la evaluación.

## Alcanzabilidad de modos

SMALL_TALK=R6; OUT_OF_SCOPE=R7; BLOCKED=R1/R2; AUTH_REQUIRED=R0; CLARIFY=R10/R12/R18/UNCLEAR; NO_MATCH=R11/R18; INFORM=R13/R18; INFORM_EXISTING_CASE=R15; CONFIRM_ACTION=R17; ACTION_DONE/ACTION_UNVERIFIED=R3 terminal; ACTION_CANCELLED=R4; OUT_OF_POLICY=R14; HANDOFF=R8/R9/R11/R12 duplicate_review/R16/agotamiento/missing_evidence; TOOL_ERROR=R9/R3 fallida.

## Moneda ambigua y aclaración de campos

Si currency_raw indica pesos/$ y currency=null por monedas ambiguas, R10 produce CLARIFY con missing_fields=["currency"] antes de buscar o autorizar. Una respuesta que aporta campos mantiene el intent del workflow, fusiona solo slots explícitos y revalida. Si sigue sin aclararse, incrementar clarification_attempts una vez por turno; al máximo, HANDOFF/clarification_exhausted. pending.type puede seguir none para aclaraciones de campos; el histórico resuelve continuidad y el estado conserva intent y missing_fields. No tratar falta de moneda como búsqueda indiferente entre monedas.
