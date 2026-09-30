# Contratos de herramientas v3



Documentar cada herramienta con su firma, parámetros, salida JSON, errores y la tabla o tablas que lee. **Todas** reciben `customer_id` desde la sesión, nunca desde el LLM, y **todas** devuelven `{"status": "ok" | "error", ...}`.

| Herramienta | Firma | Lee | Notas |
|---|---|---|---|
| `get_customer_profile` | `(customer_id)` | customers, products | Devuelve `first_name`, `segment` y `products: [{product_id, product_type, currency, product_status, product_last4}]` |
| `search_transactions` | `(customer_id, date_from, date_to, amount=None, amount_tolerance_pct=1.0, currency=None, merchant=None, transaction_type=None, channel=None, limit=10)` | transactions, products | Ventana por defecto: últimos 90 días si no hay fechas. Si `amount_is_approximate`, la tolerancia es 10% |
| `get_transaction` | `(customer_id, transaction_id)` | transactions | Devuelve error `not_found` si el `transaction_id` no pertenece al cliente (esto es control de acceso) |
| `get_related_complaints` | `(customer_id, product_id=None, amount=None, since=None, only_open=True)` | complaints + sandbox | Heurística H1 |
| `get_complaint` | `(customer_id, complaint_id)` | complaints + sandbox | Se usa para **verificar** tras la creación |
| `get_recent_interactions` | `(customer_id, days=30)` | call_center_interactions, call_transcripts | Devuelve un resumen, **no** `full_text` |
| `create_complaint` | `(customer_id, transaction_id, product_id, claimed_amount, currency, description, idempotency_key)` | escribe `sandbox/complaints_created.csv` | `category='Transactions'`, `subcategory='Cargo no reconocido'`, `status='Open'`. Id con formato `CMP-SBX-XXXXXXXX` |
| `create_handoff` | `(customer_id, payload)` | escribe `sandbox/handoffs.jsonl` | Id con formato `HOF-XXXXXXXX` |
| `retrieve_policy` | `(query, top_k=4)` | `resources/policies/*.md` | Devuelve `[{chunk_id, source, text}]` |

Salida canónica de `search_transactions` (el generador recibe solo esta forma):

```json
{
  "status": "ok",
  "match_count": 2,
  "candidates": [
    {
      "ref": "1",
      "transaction_id": "TRX-TISSB5PSH609J7PQJCU3",
      "transaction_date": "2026-03-10 19:24:27",
      "amount": 253.04,
      "currency": "USD",
      "transaction_type": "Withdrawal",
      "channel": "Web",
      "merchant_name": null,
      "merchant_category": null,
      "transaction_city": "Guadalajara",
      "transaction_country": "México",
      "transaction_status": "Approved",
      "product_type": "Tarjeta Débito",
      "product_last4": "6475",
      "possible_duplicate_of": null
    }
  ],
  "data_quality_flags": ["merchant_missing", "possible_duplicate"]
}
```

- `possible_duplicate_of`: se rellena cuando hay dos registros con el mismo `customer_id`, `amount`, `currency` y `transaction_date` con diferencia ≤ 2 minutos.
- `fraud_score` e `is_fraud` se devuelven en un campo aparte (`risk_signals`) que **solo** lee el motor de políticas y que `sanitize_for_llm()` elimina.


## get_customer_profile: salida y errores

Fuente: customers, products.

```json
{
  "status": "ok",
  "first_name": "Nombre",
  "segment": "internal-only",
  "products": [
    {
      "product_id": "PRD-EXAMPLE",
      "product_type": "Cuenta Ahorro",
      "currency": "COP",
      "product_status": "Active",
      "product_last4": "1234"
    }
  ]
}
```

Errores: not_found, data_unavailable. Todos usan {"status":"error","error":{"code":"...","retryable":false,"message":"texto seguro"}}; no mezclar resultados parciales con status=ok.

## search_transactions: salida y errores

Fuente: transactions, products.

```json
{
  "status": "ok",
  "match_count": 0,
  "candidates": [],
  "risk_signals": {},
  "data_quality_flags": []
}
```

Errores: invalid_filter, data_unavailable. Todos usan {"status":"error","error":{"code":"...","retryable":false,"message":"texto seguro"}}; no mezclar resultados parciales con status=ok.

## get_transaction: salida y errores

Fuente: transactions.

```json
{
  "status": "ok",
  "transaction": null,
  "risk_signals": {}
}
```

Errores: not_found, data_unavailable. Todos usan {"status":"error","error":{"code":"...","retryable":false,"message":"texto seguro"}}; no mezclar resultados parciales con status=ok.

## get_related_complaints: salida y errores

Fuente: complaints, sandbox/complaints_created.csv.

```json
{
  "status": "ok",
  "complaints": [],
  "match_method": "heuristic | exact_sandbox",
  "data_quality_flags": []
}
```

Errores: invalid_filter, data_unavailable. Todos usan {"status":"error","error":{"code":"...","retryable":false,"message":"texto seguro"}}; no mezclar resultados parciales con status=ok.

## get_complaint: salida y errores

Fuente: complaints, sandbox/complaints_created.csv.

```json
{
  "status": "ok",
  "complaint": {
    "complaint_id": "CMP-SBX-EXAMPLE",
    "status": "Open",
    "transaction_id": "TRX-EXAMPLE"
  }
}
```

Errores: not_found, data_unavailable. Todos usan {"status":"error","error":{"code":"...","retryable":false,"message":"texto seguro"}}; no mezclar resultados parciales con status=ok.

## get_recent_interactions: salida y errores

Fuente: call_center_interactions, call_transcripts.

```json
{
  "status": "ok",
  "interactions": [
    {
      "interaction_id": "INT-EXAMPLE",
      "interaction_date": "2026-03-12",
      "contact_reason": "Transaccional",
      "was_resolved": false,
      "was_escalated": false
    }
  ]
}
```

Errores: data_unavailable. Todos usan {"status":"error","error":{"code":"...","retryable":false,"message":"texto seguro"}}; no mezclar resultados parciales con status=ok.

## create_complaint: salida y errores

Fuente: escribe únicamente sandbox/complaints_created.csv.

```json
{
  "status": "ok",
  "complaint_id": "CMP-SBX-XXXXXXXX",
  "executed": true,
  "verified": false,
  "idempotent_replay": false
}
```

Errores: not_found, unauthorized_action, stale_confirmation, conflict, write_failed, write_outcome_unknown. Todos usan {"status":"error","error":{"code":"...","retryable":false,"message":"texto seguro"}}; no mezclar resultados parciales con status=ok.

## create_handoff: salida y errores

Fuente: escribe únicamente sandbox/handoffs.jsonl.

```json
{
  "status": "ok",
  "handoff_id": "HOF-XXXXXXXX",
  "created": true
}
```

Errores: invalid_payload, write_failed, verification_failed. Todos usan {"status":"error","error":{"code":"...","retryable":false,"message":"texto seguro"}}; no mezclar resultados parciales con status=ok.

## retrieve_policy: salida y errores

Fuente: resources/policies/*.md.

```json
{
  "status": "ok",
  "chunks": [
    {
      "chunk_id": "dispute-01",
      "source": "transaction_dispute_policy.md",
      "text": "Política sintética"
    }
  ]
}
```

Errores: index_unavailable, invalid_query. Todos usan {"status":"error","error":{"code":"...","retryable":false,"message":"texto seguro"}}; no mezclar resultados parciales con status=ok.

## Reglas de implementación y privacidad

Todas las herramientas de cliente usan un contexto de sesión inyectado por código, con autenticación y expiración verificadas antes de cada llamada. retrieve_policy no recibe customer_id: es la excepción explícita porque consulta documentos públicos sintéticos. Reintentar solo errores transitorios, hasta tool_retries; no reintentar unauthorized_action, invalid_filter o not_found.

Aplicar filtro por customer_id antes de cualquier agregación o join. get_transaction/get_complaint devuelven el mismo not_found para ausencia y pertenencia ajena, sin revelar cuál. Las relaciones products.customer_id y transaction.customer_id deben coincidir. No consultar por documentos ni sustituir la identidad por slots.

search_transactions: extremos inclusivos; ventana por defecto [current_date-90,current_date]; comparación monetaria Decimal, moneda exacta, tolerancia porcentual sobre abs(amount). Para amount=0, coincidencia exacta. Monto aproximado: 10%; normal: 1%. city/country/product_hint/product_last4 son filtros adicionales del adaptador, siempre dentro del cliente. Limitar salida LLM a cinco candidatos pero match_count representa todos. Ref estable dentro del snapshot y pending, no índice global.

Deduplicar transaction_id conservando process_date más reciente; si empata y difiere el contenido, data_quality_flags=conflicting_duplicate y no actuar. Diferentes IDs del mismo cliente, monto, moneda y fecha a <=2 minutos reciben possible_duplicate_of; nunca se resuelven arbitrariamente como una sola transacción.

get_related_complaints: H1 exige mismo cliente, producto, moneda, monto ±1%, category=Transactions, subcategory=Cargo no reconocido, y estado Open/In Process/Escalated. No hay transaction_id en el origen. Retornar match_method=heuristic y no afirmar identidad exacta. En sandbox usar el vínculo transaction_id exacto. since no debe excluir reclamos abiertos antiguos; un dato nulo requerido deja duplicate_check_incomplete, no prueba ausencia.

get_customer_profile devuelve segment solo internamente. A LLM de entrada se permite únicamente customer_currencies, lista deduplicada; al generador first_name y productos mínimos. get_recent_interactions resume campos categóricos en código; no envía texto completo ni customer_text/agent_text originales al LLM.

Normalizar amount_usd internamente con daily_exchange_rates de fecha del evento y par moneda/USD; si falta tipo de cambio no asumir riesgo bajo. risk_signals y datos de riesgo quedan en canal interno y paquete humano, nunca en structured_data ni prompts.

create_complaint vuelve a comprobar sesión, propiedad, Approved, ventana, política, ausencia de duplicado y confirmación del target exacto. idempotency_key=SHA256(session identity + workflow ID + transaction ID + CREATE_COMPLAINT); guardarla antes del intento y reutilizarla tras timeout. Reserva atómica/bloqueo por clave, nunca insertar dos veces. case_type=Claim; resto de constantes según tabla. No devolver verified=true: verify_action relee por get_complaint y compara cliente, transaction_id, producto, importe y moneda.

create_handoff recibe payload ensamblado por código y una clave estable en payload para reintentos idempotentes. created=true únicamente después de releer el registro local con el mismo ID y verificar campos obligatorios. En fallo conservar required=true, created=false y no anunciar transferencia creada.

data_s3 permanece de solo lectura. El almacenamiento sandbox es interno y nunca se envía íntegro a modelos externos. Errores, descripciones y campos de texto se sanean antes de usarse.

## Paquete final de handoff (interno, ensamblado en código)

Campos obligatorios: handoff_id:string, created_at:ISO8601, reason_code:high_risk|customer_request|emergency|no_match_exhausted|tool_failure|action_unverified|out_of_policy|clarification_exhausted|missing_evidence, rule_ids:list[string], request_summary:string, customer_language:es|pt|other, verified_facts:list[{field,value,source}], customer_stated_claims:list[string], actions_taken:list[{action,result}], evidence:list[{source,id}], open_questions:list[string], risk_signals:objeto interno opcional.
El resumen narrativo solo llena request_summary, customer_language, customer_stated_claims y suggested_open_questions; código filtra estas últimas y las guarda como open_questions (máximo cuatro). Los hechos y acciones siempre se reconstruyen desde herramientas y trace; jamás desde salida narrativa. customer_id se agrega exclusivamente en el almacén interno para control de acceso. risk_signals puede contener fraud_score e is_fraud para el humano, pero se excluye de cualquier entrada al LLM y mensaje al cliente.
