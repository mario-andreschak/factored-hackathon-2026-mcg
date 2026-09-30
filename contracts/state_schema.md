# Contrato ChatState v3

Estado interno; jamás enviar completo al LLM.

```json
{
  "session": {
    "session_id": "str",
    "customer_id": "str | null",
    "authenticated": "bool",
    "expired": "bool"
  },
  "turn": {
    "user_question": "str",
    "clean_query": "str",
    "sub_queries": [
      {
        "query_text": "str"
      }
    ],
    "language": "es | pt | other",
    "emotional_context": "Neutro | Positivo | Frustración | Emergencia",
    "attack": {
      "inappropriate": 0,
      "deceptive": 0
    },
    "intent": "TRANSACTION_DISPUTE | ... | OOD",
    "slots": {
      "amount": "number|null",
      "currency": "str|null",
      "currency_raw": "str|null",
      "date_from": "str|null",
      "date_to": "str|null",
      "date_expression": "str|null",
      "merchant": "str|null",
      "transaction_type": "str|null",
      "channel": "str|null",
      "city": "str|null",
      "country": "str|null",
      "transaction_id": "str|null",
      "complaint_id": "str|null",
      "product_hint": "str|null",
      "product_last4": "str|null",
      "amount_is_approximate": "bool",
      "foreign_customer_reference": "bool"
    },
    "clarification": {
      "resolution_type": "SELECTED|CONFIRMED|DENIED|UNCLEAR|NEW_REQUEST",
      "selected_ref": "str|null"
    },
    "current_date": "YYYY-MM-DD",
    "turn_id": "str",
    "human_requested": false,
    "unauthorized_reference": false,
    "effective_language": "es | pt",
    "intents": [],
    "active_query_index": 0,
    "validation_errors": [],
    "validation_attempts": 0,
    "current_timestamp": "ISO8601 UTC"
  },
  "workflow_state": {
    "pending": {
      "type": "none | awaiting_selection | awaiting_confirmation",
      "candidates": [
        {
          "ref": "1",
          "transaction_id": "TRX-...",
          "label": "str"
        }
      ],
      "proposed_action": "CREATE_COMPLAINT | null",
      "target_transaction_id": "str | null",
      "turns_waiting": 0,
      "created_turn_id": null,
      "intent": null,
      "candidate_type": "transaction | complaint",
      "snapshot_hash": null
    },
    "transaction_identified": false,
    "transaction_unique": false,
    "transaction_id": null,
    "existing_case": {
      "found": false,
      "complaint_id": null,
      "status": null
    },
    "missing_fields": [],
    "policy_decision": {
      "response_mode": "INFORM",
      "rule_ids": [
        "R7"
      ],
      "requires_confirmation": false,
      "requires_human": false,
      "reason_code": null
    },
    "action": {
      "name": null,
      "authorized": false,
      "executed": false,
      "verified": false,
      "result_id": null,
      "error": null,
      "idempotency_key": null,
      "authorization_expires_at": null
    },
    "handoff": {
      "required": false,
      "created": false,
      "handoff_id": null,
      "reason_code": null
    },
    "counters": {
      "clarification_attempts": 0,
      "no_match_attempts": 0,
      "tool_failures": 0,
      "last_counted_turn_id": null
    },
    "action_attempted": false,
    "action_outcome": "none | failed | unknown | executed | verified",
    "search_criteria_present": false,
    "complaint_match_count": 0,
    "candidate_snapshot_hash": null,
    "confirmation_turn_id": null,
    "unrecognized_count_24h": 0,
    "risk_data_complete": false,
    "handoff_attempted": false
  },
  "tool_results": {
    "get_customer_profile": {
      "status": "ok | error",
      "first_name": "str",
      "products": []
    },
    "search_transactions": {
      "status": "ok | error",
      "match_count": 0,
      "candidates": [],
      "risk_signals": {},
      "data_quality_flags": []
    },
    "get_related_complaints": {
      "status": "ok | error",
      "complaints": []
    },
    "get_complaint": {
      "status": "ok | error",
      "complaint": null
    },
    "get_transaction": {
      "status": "ok|error",
      "transaction": null,
      "risk_signals": {}
    },
    "get_recent_interactions": {
      "status": "ok|error",
      "interactions": []
    },
    "retrieve_policy": {
      "status": "ok|error",
      "chunks": []
    },
    "create_complaint": {
      "status": "ok|error",
      "complaint_id": null,
      "executed": false
    },
    "create_handoff": {
      "status": "ok|error",
      "handoff_id": null,
      "created": false
    }
  },
  "trace": [
    {
      "node": "str",
      "started_at": "iso",
      "latency_ms": 0,
      "model": "str|null",
      "prompt_version": "str|null",
      "tokens_in": 0,
      "tokens_out": 0
    }
  ],
  "response": {
    "message": "str",
    "language": "es|pt",
    "arquetipos": [],
    "chunk_ids": [],
    "data_sources": [],
    "grounding_violation": 0
  },
  "runtime": {
    "node_errors": [],
    "policy_version": "str",
    "workflow_id": "str",
    "safe_fallback_used": false
  }
}
```

| Campo | Tipo | Escribe | Lee |
| --- | --- | --- | --- |
| session.session_id | str | decode_session | handlers deterministas; proyección según docs/INTEGRATION.md |
| session.customer_id | str | null | decode_session | handlers deterministas; proyección según docs/INTEGRATION.md |
| session.authenticated | bool | decode_session | handlers deterministas; proyección según docs/INTEGRATION.md |
| session.expired | bool | decode_session | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.user_question | str | adaptador de entrada / decode_session | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.clean_query | str | rewrite_decompose | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.sub_queries | array | rewrite_decompose | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.language | es | pt | other | detect_context | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.emotional_context | Neutro | Positivo | Frustración | Emergencia | detect_context | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.attack.inappropriate | integer | detect_attack | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.attack.deceptive | integer | detect_attack | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.intent | TRANSACTION_DISPUTE | ... | OOD | adaptador detect_intent / router pending | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.slots.amount | number|null | extract_slots | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.slots.currency | str|null | extract_slots | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.slots.currency_raw | str|null | extract_slots | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.slots.date_from | str|null | extract_slots | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.slots.date_to | str|null | extract_slots | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.slots.date_expression | str|null | extract_slots | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.slots.merchant | str|null | extract_slots | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.slots.transaction_type | str|null | extract_slots | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.slots.channel | str|null | extract_slots | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.slots.city | str|null | extract_slots | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.slots.country | str|null | extract_slots | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.slots.transaction_id | str|null | extract_slots | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.slots.complaint_id | str|null | extract_slots | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.slots.product_hint | str|null | extract_slots | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.slots.product_last4 | str|null | extract_slots | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.slots.amount_is_approximate | bool | extract_slots | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.slots.foreign_customer_reference | bool | extract_slots | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.clarification.resolution_type | SELECTED|CONFIRMED|DENIED|UNCLEAR|NEW_REQUEST | resolve_clarification | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.clarification.selected_ref | str|null | resolve_clarification | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.current_date | YYYY-MM-DD | adaptador de entrada / decode_session | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.turn_id | str | adaptador de entrada / decode_session | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.human_requested | bool | preprocesador local | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.unauthorized_reference | bool | preprocesador local | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.effective_language | es | pt | adaptador detect_context | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.intents | array | adaptador detect_intent | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.active_query_index | integer | router de consultas | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.validation_errors | array | validate_response | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.validation_attempts | integer | validate_response | handlers deterministas; proyección según docs/INTEGRATION.md |
| turn.current_timestamp | ISO8601 UTC | adaptador de entrada / decode_session | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.pending.type | none | awaiting_selection | awaiting_confirmation | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.pending.candidates | array | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.pending.proposed_action | CREATE_COMPLAINT | null | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.pending.target_transaction_id | str | null | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.pending.turns_waiting | integer | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.pending.created_turn_id | str|null | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.pending.intent | str|null | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.pending.candidate_type | transaction | complaint | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.pending.snapshot_hash | str|null | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.transaction_identified | bool | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.transaction_unique | bool | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.transaction_id | str|null | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.existing_case.found | bool | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.existing_case.complaint_id | str|null | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.existing_case.status | str|null | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.missing_fields | array | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.policy_decision.response_mode | INFORM | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.policy_decision.rule_ids | array | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.policy_decision.requires_confirmation | bool | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.policy_decision.requires_human | bool | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.policy_decision.reason_code | str|null | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.action.name | str|null | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.action.authorized | bool | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.action.executed | bool | execute_action | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.action.verified | bool | verify_action | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.action.result_id | str|null | execute_action | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.action.error | str|null | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.action.idempotency_key | str|null | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.action.authorization_expires_at | str|null | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.handoff.required | bool | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.handoff.created | bool | create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.handoff.handoff_id | str|null | create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.handoff.reason_code | str|null | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.counters.clarification_attempts | integer | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.counters.no_match_attempts | integer | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.counters.tool_failures | integer | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.counters.last_counted_turn_id | str|null | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.action_attempted | bool | execute_action | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.action_outcome | none | failed | unknown | executed | verified | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.search_criteria_present | bool | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.complaint_match_count | integer | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.candidate_snapshot_hash | str|null | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.confirmation_turn_id | str|null | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.unrecognized_count_24h | integer | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.risk_data_complete | bool | policy_engine con resultados de execute/verify | handlers deterministas; proyección según docs/INTEGRATION.md |
| workflow_state.handoff_attempted | bool | create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.get_customer_profile.status | ok | error | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.get_customer_profile.first_name | str | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.get_customer_profile.products | array | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.search_transactions.status | ok | error | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.search_transactions.match_count | integer | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.search_transactions.candidates | array | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.search_transactions.risk_signals | object | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.search_transactions.data_quality_flags | array | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.get_related_complaints.status | ok | error | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.get_related_complaints.complaints | array | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.get_complaint.status | ok | error | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.get_complaint.complaint | str|null | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.get_transaction.status | ok|error | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.get_transaction.transaction | str|null | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.get_transaction.risk_signals | object | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.get_recent_interactions.status | ok|error | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.get_recent_interactions.interactions | array | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.retrieve_policy.status | ok|error | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.retrieve_policy.chunks | array | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.create_complaint.status | ok|error | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.create_complaint.complaint_id | str|null | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.create_complaint.executed | bool | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.create_handoff.status | ok|error | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.create_handoff.handoff_id | str|null | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| tool_results.create_handoff.created | bool | load_customer_context / run_tools / execute_action / verify_action / create_handoff | handlers deterministas; proyección según docs/INTEGRATION.md |
| trace | array | wrapper de nodos / persist | auditoría / persist |
| response.message | str | generate / safe_fallback | validate_response / persist |
| response.language | es|pt | generate / safe_fallback | validate_response / persist |
| response.arquetipos | array | generate / safe_fallback | validate_response / persist |
| response.chunk_ids | array | generate / safe_fallback | validate_response / persist |
| response.data_sources | array | generate / safe_fallback | validate_response / persist |
| response.grounding_violation | integer | generate / safe_fallback | validate_response / persist |
| runtime.node_errors | array | wrapper de nodos / persist | auditoría / persist |
| runtime.policy_version | str | wrapper de nodos / persist | auditoría / persist |
| runtime.workflow_id | str | wrapper de nodos / persist | auditoría / persist |
| runtime.safe_fallback_used | bool | wrapper de nodos / persist | auditoría / persist |

## Invariantes y ciclo de vida

- session.customer_id se escribe exclusivamente en decode_session desde una sesión de confianza. Un ID escrito por el usuario no autentica.
- turn.slots tiene exactamente las 17 claves del slot_extraction_prompt; turn.clarification tiene resolution_type y selected_ref. turn.intents preserva la lista completa del clasificador. Procesar consultas independientes de forma serial, sin confirmar varias acciones con un único sí.
- get_history solo restaura workflow_state del mismo customer_id y sesión. Jamás sustituye identidad ni autenticación actual.
- Cada turno reinicia resultados de clasificación, validación y herramientas. Los resultados anteriores se revalidan antes de usarse. trace es evidencia operativa, nunca chain-of-thought.
- pending se conserva durante la resolución y se limpia después de consumir la selección/confirmación, al cambiar de tema, al cancelar o cuando turns_waiting > pending_expiry_turns. La expiración invalida toda autorización.
- Una confirmación solo corresponde al target y snapshot mostrados, dentro de la misma sesión. No se autoriza a partir del texto reescrito sin contrastarlo con el mensaje original saneado.
- Contadores de clarificación y búsqueda fallida aumentan una vez por turno (last_counted_turn_id), no por cada reentrada al motor. Se reinician al abrir un workflow nuevo.
- action_attempted y action_outcome evitan bucles de escritura cuando verify_action vuelve al motor. executed no implica verified. Un timeout de escritura deja outcome=unknown.
- El estado completo es interno. workflow_state y pending que reciben los LLM son proyecciones con lista permitida; sin customer_id, risk_signals, idempotency_key ni campos privados. Los candidatos de pending son la excepción mínima necesaria para seleccionar una referencia, no una autorización.
- turn.language conserva es|pt|other. effective_language=pt si language=pt; de lo contrario es. La salida se valida contra effective_language; para other se informa que el servicio está disponible en ES/PT.
- Persistir prompt_version, modelo, tokens y latencia por nodo. No registrar secretos ni texto privado en trace.
