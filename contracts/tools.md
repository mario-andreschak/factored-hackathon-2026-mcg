# Contratos de herramientas v3



Documentar cada herramienta con su firma, parámetros, salida JSON, errores y la tabla o tablas que lee. **Todas** reciben `customer_id` desde la sesión, nunca desde el LLM, y **todas** devuelven `{"status": "ok" | "error", ...}`.

| Herramienta | Firma | Lee | Notas |
|---|---|---|---|
| `get_customer_profile` | `(customer_id)` | customers, products | Devuelve `first_name`, `segment` y `products: [{product_id, product_type, currency, product_status, product_last4}]` |
| `search_transactions` | `(customer_id, date_from, date_to, amount=None, amount_tolerance_pct=1.0, currency=None, merchant=None, transaction_type=None, channel=None, limit=10)` | transactions, products | Sin fechas: ventana de 90 días de eventos anclada al snapshot declarado. Fechas del cliente se conservan. Si `amount_is_approximate`, la tolerancia es 10% |
| `get_transaction` | `(customer_id, transaction_id)` | transactions | Devuelve error `not_found` si el `transaction_id` no pertenece al cliente (esto es control de acceso) |
| `get_related_complaints` | `(customer_id, transaction_id, only_open=True)` | complaints + sandbox | Vínculo exacto en sandbox; historial abierto del cliente separado, sin atribuirlo a la transacción |
| `list_customer_complaints` | `(customer_id, only_open=False)` | complaints + sandbox | Consulta R18 sin exigir transaction_id; estados propios, no control de duplicados de escritura |
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
  "data_quality_flags": ["merchant_missing", "possible_duplicate"],
  "search_context": {
    "date_from": "2026-03-01",
    "date_to": "2026-03-31",
    "date_basis": "event_date",
    "snapshot_id": "SNAPSHOT-EXAMPLE",
    "used_snapshot_default": false,
    "coverage_complete": true
  }
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
  "data_quality_flags": [],
  "search_context": {
    "date_from": "2026-03-21",
    "date_to": "2026-06-18",
    "date_basis": "event_date",
    "snapshot_id": "SNAPSHOT-EXAMPLE",
    "used_snapshot_default": true,
    "coverage_complete": true
  }
}
```

Errores: invalid_filter, data_unavailable. Todos usan {"status":"error","error":{"code":"...","retryable":false,"message":"texto seguro"}}; no mezclar resultados parciales con status=ok.

## get_transaction: salida y errores

Fuente: transactions.

```json
{
  "status": "ok",
  "transaction": null,
  "risk_signals": {},
  "data_quality_flags": []
}
```

Errores: not_found, data_unavailable. Todos usan {"status":"error","error":{"code":"...","retryable":false,"message":"texto seguro"}}; no mezclar resultados parciales con status=ok.

## get_related_complaints: salida y errores

Fuente: complaints, sandbox/complaints_created.csv.

```json
{
  "status": "ok",
  "complaints": [],
  "historical_candidates": [],
  "match_method": "exact_sandbox",
  "duplicate_check": "clear_in_snapshot",
  "data_quality_flags": []
}
```

Errores: invalid_filter, data_unavailable. Todos usan {"status":"error","error":{"code":"...","retryable":false,"message":"texto seguro"}}; no mezclar resultados parciales con status=ok.

## list_customer_complaints: salida y errores

Fuente: complaints, sandbox/complaints_created.csv. Filtro por customer_id antes de cualquier lectura o unión; salida de estado, independiente de transacciones.

```json
{"status":"ok","match_count":0,"complaints":[],"coverage_complete":true}
```

Cada entrada contiene ref estable en el snapshot, complaint_id, status, source, transaction_id (null en origen histórico) y linkage=unknown|exact_sandbox. match_count cuenta todos los casos propios del filtro; una cobertura incompleta devuelve data_unavailable, no NO_MATCH. El adaptador muestra hasta max_candidates_to_show y exige filtro adicional si hay más, sin truncar silenciosamente el conteo. Nunca usar este listado como autorización ni prueba de ausencia de duplicados de una transacción. Errores: data_unavailable, con el mismo sobre seguro de las otras herramientas.

## get_complaint: salida y errores

Fuente: complaints, sandbox/complaints_created.csv.

```json
{
  "status": "ok",
  "complaint": {
    "complaint_id": "CMP-SBX-EXAMPLE",
    "status": "Open",
    "transaction_id": "TRX-EXAMPLE",
    "linkage": "exact_sandbox"
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

search_transactions: fechas de evento, extremos inclusivos. Solo cuando ambas fechas son nulas usar [max(dataset_first_event_date, dataset_latest_event_date-(default_search_window_days-1)), dataset_latest_event_date], 90 fechas calendario como máximo. El snapshot y sus límites se validan en código; si faltan, data_unavailable, sin sustituirlos por la fecha del proceso. Una fecha explícita, parcial o relativa se resuelve/pide aclaración sin recortarla ni trasladarla al snapshot. current_date sigue siendo la fecha real del cliente; current_timestamp, expiración y TTL siguen el reloj real. La antigüedad de disputa se calcula respecto de current_date, no del ancla de búsqueda.

Toda búsqueda devuelve search_context={date_from,date_to,date_basis:"event_date",snapshot_id,used_snapshot_default,coverage_complete}. Solo una cobertura completa puede informar match_count total o NO_MATCH; una lectura truncada/parcial falla con data_unavailable. La proyección al cliente incluye intervalo y snapshot histórico cuando se usa el default. El MCP actual de 31 días por process_date no satisface este contrato: extenderlo o demostrar en un adaptador la cobertura de eventos en particiones de proceso anteriores y posteriores; nunca traducir 90 días de eventos a 90 días de proceso sin esa prueba. El ejemplo anterior usa el último día de evento (2026-06-18) del candidato medido, no el último `process_date` (2026-06-17) ni la fecha actual del cliente.

Comparación monetaria Decimal, moneda exacta, tolerancia porcentual sobre abs(amount). Para amount=0, coincidencia exacta. Monto aproximado: 10%; normal: 1%. city/country/product_hint/product_last4 son filtros adicionales del adaptador, siempre dentro del cliente. Limitar salida LLM a cinco candidatos pero match_count representa todos. Ref estable dentro del snapshot y pending, no índice global.

Deduplicar transaction_id conservando process_date más reciente; si empata y difiere el contenido, data_quality_flags=conflicting_duplicate y no actuar. Diferentes IDs del mismo cliente, monto, moneda y fecha a <=2 minutos reciben possible_duplicate_of; nunca se resuelven arbitrariamente como una sola transacción.

get_transaction recalcula las señales para el target desde los registros autoritativos del snapshot, incluida comparación de versiones empatadas y otros IDs propios cercanos; devuelve data_quality_flags del target y transaction.possible_duplicate_of. No copiar un flag global de otro candidato ni perder un conflicto al releer. Si no puede completar este control, data_unavailable y ninguna autorización.

get_related_complaints: validar primero la propiedad de transaction_id. complaints contiene solo casos sandbox del mismo cliente y transaction_id exacto; match_method=exact_sandbox. No usar affected_product_id del origen para enlazar productos/transacciones: los vínculos poblados auditados cruzan clientes y no existe transaction_id histórico. Se elimina H1; reparar un ID por importe/moneda tampoco crea evidencia de relación.

historical_candidates contiene por separado los reclamos históricos propios abiertos de Transactions/Cargo no reconocido, sin filtrar por producto, importe o moneda para excluir un posible duplicado. Un estado/categoría/subcategoría nulo que no permita descartar un caso se conserva como incierto. Cada entrada tiene complaint_id, status y linkage="unknown"; no incluye datos de terceros. No atribuir estos casos al movimiento elegido ni fijar existing_case.found por ellos. R18 puede consultar su estado propio por complaint_id sin atribución transaccional. No excluir casos abiertos antiguos por fecha.

duplicate_check enum: exact_open_case si hay vínculo sandbox abierto verificado; historical_uncertain si no hay tal vínculo pero sí historical_candidates; incomplete si alguna lectura, propiedad o cobertura requerida no se verifica; clear_in_snapshot solo si ambas lecturas completas no encuentran casos abiertos exactos ni históricos potenciales. historical_uncertain/incomplete impiden creación automática y llevan a revisión humana/missing_evidence. clear_in_snapshot permite continuar los demás guardas del prototipo, sin afirmar que no existe ningún reclamo fuera de sus fuentes. Fallos y campos nulos esenciales nunca se convierten en ausencia.

get_complaint filtra por propietario antes de releer: un caso histórico devuelve transaction_id=null, linkage=unknown, sin reparar affected_product_id. Un recibo sandbox devuelve linkage=exact_sandbox y todos los campos que verify_action compara; un caso histórico nunca verifica la creación de una acción sandbox.

get_customer_profile devuelve segment solo internamente. A LLM de entrada se permite únicamente customer_currencies, lista deduplicada; al generador first_name y productos mínimos. get_recent_interactions resume campos categóricos en código; no envía texto completo ni customer_text/agent_text originales al LLM.

Normalizar amount_usd internamente con daily_exchange_rates de fecha del evento y par moneda/USD; si falta tipo de cambio no asumir riesgo bajo. risk_signals y datos de riesgo quedan en canal interno y paquete humano, nunca en structured_data ni prompts.

create_complaint vuelve a comprobar sesión, propiedad, Approved, ventana real, política, duplicate_check=clear_in_snapshot y confirmación del target exacto. Revalidar el control de casos bajo una reserva atómica por cliente/transacción/acción para impedir duplicados entre conversaciones; además idempotency_key=SHA256(session identity + workflow ID + transaction ID + CREATE_COMPLAINT), guardada antes del intento y reutilizada tras timeout. Nunca insertar dos veces. case_type=Claim; resto de constantes según tabla. No devolver verified=true: verify_action relee por get_complaint y compara cliente, transaction_id, producto, importe y moneda.

create_handoff recibe payload ensamblado por código y una clave estable en payload para reintentos idempotentes. created=true únicamente después de releer el registro local con el mismo ID y verificar campos obligatorios. En fallo conservar required=true, created=false y no anunciar transferencia creada.

data_s3 permanece de solo lectura. El almacenamiento sandbox es interno y nunca se envía íntegro a modelos externos. Errores, descripciones y campos de texto se sanean antes de usarse.

## Paquete final de handoff (interno, ensamblado en código)

Campos obligatorios: handoff_id:string, created_at:ISO8601, reason_code:high_risk|customer_request|emergency|no_match_exhausted|tool_failure|action_unverified|out_of_policy|clarification_exhausted|missing_evidence|duplicate_review, rule_ids:list[string], request_summary:string, customer_language:es|pt|other, verified_facts:list[{field,value,source}], customer_stated_claims:list[string], actions_taken:list[{action,result}], evidence:list[{source,id}], open_questions:list[string], risk_signals:objeto interno opcional.
El resumen narrativo solo llena request_summary, customer_language, customer_stated_claims y suggested_open_questions; código filtra estas últimas y las guarda como open_questions (máximo cuatro). Los hechos y acciones siempre se reconstruyen desde herramientas y trace; jamás desde salida narrativa. customer_id se agrega exclusivamente en el almacén interno para control de acceso. risk_signals puede contener fraud_score e is_fraud para el humano, pero se excluye de cualquier entrada al LLM y mensaje al cliente.
