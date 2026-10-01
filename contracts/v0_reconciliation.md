# Reconciliación propuesta del contrato v0

Estado: contrato de producto propuesto para revisión de Gloria y del equipo de implementación, vinculado a [issue #10](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/issues/10). Estos documentos no instalan el grafo R0–R18 ni activan el flujo. La versión sintética 1.1.0 identifica el contrato propuesto, no una política bancaria ni una política desplegada.

Se conserva el objetivo de los prompts v0: aclarar un cargo propio no reconocido y llegar a un registro simulado confirmado, durable y releído, o a una solicitud local de revisión humana verificada. El cliente confirma la acción preparada mediante un control explícito del portal; un «sí/sim» de chat, una etiqueta CONFIRMED del clasificador o una selección no autorizan escritura. Los prompts canónicos para este contrato están en `resources/prompts/`. `demo/customer_v0/prompt.md` es un artefacto congelado de lectura, no otro prompt canónico instalado.

## Estado del código fuente frente al contrato

En el main integrado hay tres lecturas y cinco acciones **solo del host** en `banking_mcp/service.py`; el frontend conserva estado de recuperación y una acción preparada, y el MCP conserva pending, casos y handoffs en su ledger SQLite sandbox con reserva única, replay por request_id y relectura de recibo. R16 cuenta casos sandbox propios verificados en 24 horas reales solo cuando un operador atestó la cobertura de **esa generación** del ledger. Las acciones siguen desactivadas por defecto (`chat.action_enabled=false`); la unión privada navegador→FLUJO→MCP aún necesita prueba antes de habilitarse. Estos hechos de código fuente no prueban aceptación del grafo ni ejecución en el worker activo.

El MCP fuente integrado ya busca hasta 90 fechas inclusivas de evento dentro de los límites verificados del snapshot servido y expone un recibo `existing_case` únicamente para un caso sandbox propio con hechos exactos del cargo releídos. El host también persiste y relee un paquete humano con datos del cargo, procedencia, motivo y preguntas pendientes; esto no demuestra atención humana. [El contrato fuente de issue #21](../docs/ISSUE21_DATA_AND_RECEIPTS.md) delimita esas capacidades. Siguen pendientes la consulta y atribución prudente de reclamos históricos propios, el listado R18 sin transacción y la integración de R15 y R0–R18 con las proyecciones, el selector de fallback y el paquete humano completo del grafo. La señal sintética de histórico no equivale a consultar reclamos históricos reales ni demuestra ausencia global. Mantener estas obligaciones como gates de implementación y evaluación, sin degradar el objetivo v0 a una demo de solo lectura.

## Tres decisiones concretas

1. **Historial de reclamos.** El [perfil auditado](../docs/DATA_REVIEW_2026-09-26.md) identifica vínculos de producto históricos que cruzan clientes y ausencia de transaction_id. Se elimina la atribución H1. Los vínculos exactos nuevos son del sandbox; los casos históricos propios potenciales se consultan por separado y su vínculo queda desconocido. Un caso histórico propio abierto de Transactions/Cargo no reconocido, o campos esenciales que no permitan descartarlo, requieren revisión antes de crear. Un cliente sin esos casos, con lecturas completas, puede continuar los demás guardas del registro simulado. Nunca se declara ausencia global de reclamos.
2. **Fechas de búsqueda.** Solo el default sin fechas usa hasta 90 fechas calendario de eventos del snapshot declarado, desde ancla−89 hasta ancla inclusive, limitado por la primera fecha disponible. Se muestran intervalo y carácter histórico. Fechas explícitas y expresiones como «ayer» conservan su sentido respecto de la fecha real del cliente. La elegibilidad de disputa sigue usando esa fecha real y 120 días: encontrar un movimiento histórico no lo vuelve elegible. Auth, confirmaciones y TTL nunca usan el reloj del snapshot. Falta de metadatos o cobertura produce error, no un NO_MATCH engañoso. En el [silver candidato medido de PR #9](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/9e5d78d4a5a8cde3fa79af786b44e7c753846984/docs/data-recovery/event_date_alignment.json), 1.106.307 de 4.425.008 movimientos tienen fecha de evento un día después de `process_date`; el último evento es del 18 de junio aunque la última fecha de proceso es el 17. Es evidencia para diseñar y probar la cobertura, no prueba de que ese candidato ya esté promovido como snapshot de servicio.
3. **Selección con señal de duplicado.** Elegir un ref propio identifica el target; no confirma una creación ni borra la señal. Si la señal persiste al releer, se crea y verifica una derivación con duplicate_review en lugar de repetir R12. Si no hay señal, el target puede avanzar por R13–R17 sin cambiar el match_count total de la búsqueda.

Se elige revisión humana para la señal persistente porque la selección por sí sola no certifica que los dos registros representen cargos independientes. No se concede al LLM permiso para relajar este control.

## Decisiones de prototipo para avanzar

Mientras Gloria y el equipo revisan el contrato, R16 usa una definición **sintética y acotada**: casos sandbox propios de Cargo no reconocido, distintos, persistidos y releíbles en las 24 horas reales previas, más la solicitud actual sobre un movimiento propio distinto. El agregado proviene del ledger SQLite sandbox con tiempo de servidor y cobertura atestada por un operador para la generación vigente; un ledger meramente inicializado o vacío no concede clearance. Un ledger deliberadamente completo y atestado puede medir cero solo para su propio historial. Dos casos previos más la solicitud actual activan el umbral de tres y solicitud de derivación local verificada. Una fuente incompleta/no atestada no equivale a cero y deriva por missing_evidence. No se usan categorías genéricas del call center ni se presenta esta regla como política de un banco real.

El contrato de fallback ES/PT selecciona texto determinista según respuesta y estado del handoff releído. HANDOFF_VERIFIED y ACTION_UNVERIFIED_HANDOFF_VERIFIED incluyen únicamente un ID HOF verificado; las variantes sin verificación no afirman transferencia. Los textos están en `resources/prompts/fallback_templates.yaml`. El frontend actual tiene su propia copia determinista para el panel de acciones, pero el selector del grafo propuesto y la unión a sus lecturas siguen pendientes. Ni un recibo HOF ni el texto prueban que una persona atendió la solicitud.

## Casos de aceptación para la implementación

Son especificaciones de cobertura pendiente, no resultados de pruebas ejecutadas.

| Caso | Resultado requerido |
|---|---|
| Sandbox: caso abierto propio del mismo transaction_id | R15, ID/estado releídos; no insertar otro |
| Caso sandbox de otro cliente, incluso con ID pedido por usuario | Mismo not_found seguro; ninguna información de terceros |
| Historial propio abierto, vínculo desconocido | missing_evidence; no afirmar relación con el movimiento; no crear automáticamente |
| affected_product_id histórico apunta a producto ajeno | No join ni reparación heurística; mantener propiedad del reclamo independiente |
| Lecturas completas sin casos históricos potenciales ni sandbox exactos | Continuar guardas; confirmar registro simulado y releer recibo antes de éxito |
| Lectura incompleta, error o campos esenciales nulos | No transformar vacío en ausencia; impedir creación |
| Dos conversaciones confirman simultáneamente el mismo movimiento | Reserva cliente/transacción/acción y control+inserción atómicos; un registro; replay/recibo coherente |
| Sin fechas; snapshot de ejemplo con último evento 2026-06-18, cobertura comienza antes del default | Consultar eventos 2026-03-21..2026-06-18 (90 fechas inclusivas); identificar snapshot en respuesta |
| «Ayer» el 2026-09-29 | Consultar 2026-09-28, sin cambiarlo a junio; comunicar cobertura/límites reales |
| Evento de marzo encontrado en septiembre | Elegibilidad respecto de fecha real; no autorizar por el ancla histórica |
| Fixture del 2026-05-19 evaluado el 2026-09-29 (133 días) | `OUT_OF_POLICY`, sin intake, aunque el ejemplo hipotético de junio muestre éxito |
| Evento del 2026-06-18 evaluado el 2026-09-29 (103 días) | Pasa solo la guarda temporal; aún requiere estado, ownership, historial, riesgo y consentimiento |
| Fecha de evento futura respecto de `turn.current_date` real | No afirmar que el cargo ya ocurrió ni crear intake; derivar con `missing_evidence` |
| Evento propio del 2026-06-18 en partición `process_date=2026-06-17` | Consulta por fecha de evento lo incluye; filtrar solo la partición del 18 no permite declarar NO_MATCH |
| Evento llega en partición de proceso posterior | Consulta de eventos lo incluye o falla explícitamente por cobertura incompleta |
| Selección válida entre varios movimientos sin señal persistente | Fijar target; conservar match_count; pedir confirmación aparte si procede |
| Cliente dice «sí/sim» o el clasificador devuelve CONFIRMED sin evento del portal | Mantener action.authorized=false; no llamar escritura; mostrar o conservar el control explícito de confirmación |
| Evento del portal para otro owner, sesión, conversación, request_id, acción, target o snapshot; pending expirado/revocado | Rechazar sin escritura; no reciclar el consentimiento ni preparar silenciosamente una solicitud nueva |
| Selección válida con possible_duplicate_of o conflicting_duplicate persistente | duplicate_review; sin bucle de elección ni creación de reclamo |
| Un único candidato propio releído con señal persistente | duplicate_review directo; no pedir selección inútil |
| Snapshot cambia tras selección o confirmación | Invalidar target/consentimiento y volver a identificar/confirmar |
| Escritura/handoff sin lectura de verificación | No anunciar éxito o transferencia creada |
| Ledger SQLite sandbox no atestado para la generación actual, ilegible o con ventana real de 24 h incompleta | `unrecognized_count_24h=null`, `risk_data_complete=false`; HANDOFF/missing_evidence, no asumir cero ni crear intake |
| Ledger SQLite deliberadamente completo, vacío y atestado por operador; primera solicitud distinta propia | Cero casos previos y conteo R16 de uno al incluir la solicitud actual; continuar los demás guardas sin prometer éxito automático |
| Dos casos sandbox distintos propios verificados en las 24 h reales más solicitud actual distinta | Conteo R16 de tres; high_risk, crear y releer derivación, no intake automático |
| Replay idempotente o repetición del mismo movimiento | No incrementar el conteo ni crear un nuevo caso; aplicar R15/control atómico de duplicados |
| Fraud_score o monto alto verificado, pero otro indicador de riesgo incompleto | R16/high_risk con la señal verificada; no esperar ni declarar los demás indicadores como bajos |
| Falla el generador tras derivación creada y releída | Fallback ES/PT comunica la derivación verificada con su ID; nunca dice que sigue sin confirmar |
| Escritura del reclamo incierta seguida por derivación creada y releída | Conservar ACTION_UNVERIFIED para el reclamo y comunicar separadamente la derivación verificada con su ID |

Estos casos deben probarse en ES/PT donde hay interacción. Medir los desvíos a humano, la cobertura de fechas y la proporción de casos que el historial incierto impide automatizar; no ocultarlos del denominador.

Los ocho ejemplos ilustrativos de `resources/prompts/generator_prompt_v3.yml` usaban `current_date=2026-03-31`; seis mostraban candidatos de abril/mayo posteriores a esa fecha, incluso dos con action.executed=true. Sus siete fixtures paralelos en `contracts/examples/` repetían la inconsistencia. Esta propuesta los sitúa en una fecha hipotética posterior al último evento (`2026-06-19`) para que no enseñen una creación sobre un cargo futuro. El ejemplo BLOCKED también citaba R11, regla de NO_MATCH, pese a que el texto rechazaba una solicitud; se convierte en una petición explícita de datos de otro cliente bajo R2, sin lectura privada. Siguen siendo ejemplos sintéticos para revisión de Gloria, no casos gold ni evidencia de ejecución.

## Integración que todavía falta

El MCP fuente ya aplica una ventana de hasta 90 fechas de evento con límites del snapshot verificados; una fecha de partición `process_date` no define esa búsqueda. También verifica y relee el recibo de un caso sandbox propio ligado a los hechos exactos del cargo. Faltan la consulta real de reclamos históricos propios con vínculo desconocido, el listado R18 sin transacción y la unión del grafo R0–R18, incluido R15, con las lecturas y cinco acciones del host. El host ya persiste y relee un paquete local de handoff con cargo, procedencia, motivo y preguntas pendientes; todavía faltan los demás campos narrativos y de reglas del paquete propuesto para el grafo, su selector ES/PT y la prueba de integración, sin declarar entrega a un asesor. [Issue #21](../docs/ISSUE21_DATA_AND_RECEIPTS.md) describe el alcance fuente y sus límites. Las acciones del host ya tienen scopes, pending durable, barrera de consentimiento del portal, reserva atómica, conteo sandbox R16 con atestación y lectura de recibos; requieren integración privada y no están activadas en el worker. La evaluación final independiente ES/PT y la medición del grafo v0 completo siguen siendo gates del producto. Ninguna comprobación de YAML/JSON demuestra estas capacidades.
