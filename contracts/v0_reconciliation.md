# Reconciliación propuesta del contrato v0

Estado: propuesta para revisión de Gloria y del equipo de implementación, vinculada a [issue #10](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/issues/10). Estos documentos no implementan herramientas, motor, permisos ni persistencia. La versión sintética 1.1.0 solo identifica el contrato propuesto; no declara una política desplegada.

Se conserva el objetivo de los prompts v0: aclarar un cargo propio no reconocido y llegar a un registro simulado confirmado, durable y releído, o a una derivación humana verificada. Las herramientas ausentes siguen siendo trabajo de implementación. Los prompts canónicos están en `resources/prompts/`.

## Tres decisiones concretas

1. **Historial de reclamos.** El [perfil auditado](../docs/DATA_REVIEW_2026-09-26.md) identifica vínculos de producto históricos que cruzan clientes y ausencia de transaction_id. Se elimina la atribución H1. Los vínculos exactos nuevos son del sandbox; los casos históricos propios potenciales se consultan por separado y su vínculo queda desconocido. Un caso histórico propio abierto de Transactions/Cargo no reconocido, o campos esenciales que no permitan descartarlo, requieren revisión antes de crear. Un cliente sin esos casos, con lecturas completas, puede continuar los demás guardas del registro simulado. Nunca se declara ausencia global de reclamos.
2. **Fechas de búsqueda.** Solo el default sin fechas usa hasta 90 fechas calendario de eventos del snapshot declarado, desde ancla−89 hasta ancla inclusive, limitado por la primera fecha disponible. Se muestran intervalo y carácter histórico. Fechas explícitas y expresiones como «ayer» conservan su sentido respecto de la fecha real del cliente. La elegibilidad de disputa sigue usando esa fecha real y 120 días: encontrar un movimiento histórico no lo vuelve elegible. Auth, confirmaciones y TTL nunca usan el reloj del snapshot. Falta de metadatos o cobertura produce error, no un NO_MATCH engañoso. En el [silver candidato medido de PR #9](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/9e5d78d4a5a8cde3fa79af786b44e7c753846984/docs/data-recovery/event_date_alignment.json), 1.106.307 de 4.425.008 movimientos tienen fecha de evento un día después de `process_date`; el último evento es del 18 de junio aunque la última fecha de proceso es el 17. Es evidencia para diseñar y probar la cobertura, no prueba de que ese candidato ya esté promovido como snapshot de servicio.
3. **Selección con señal de duplicado.** Elegir un ref propio identifica el target; no confirma una creación ni borra la señal. Si la señal persiste al releer, se crea y verifica una derivación con duplicate_review en lugar de repetir R12. Si no hay señal, el target puede avanzar por R13–R17 sin cambiar el match_count total de la búsqueda.

Se elige revisión humana para la señal persistente porque la selección por sí sola no certifica que los dos registros representen cargos independientes. No se concede al LLM permiso para relajar este control.

## Decisiones de prototipo para avanzar

Mientras Gloria y el equipo revisan el contrato, R16 usa una definición **sintética y acotada**: casos sandbox propios de Cargo no reconocido, distintos, persistidos y releíbles en las 24 horas reales previas, más la solicitud actual sobre un movimiento propio distinto. El agregado se obtiene del mismo almacén sandbox con tiempo de servidor y cobertura completa; el almacén inicializado desde vacío puede medir cero solo para su propio historial. Dos casos previos más la solicitud actual activan el umbral de tres y derivación verificada. Una fuente incompleta no equivale a cero y deriva por missing_evidence. No se usan categorías genéricas del call center ni se presenta esta regla como política de un banco real.

El fallback ES/PT selecciona texto determinista según respuesta y estado del handoff releído. HANDOFF_VERIFIED y ACTION_UNVERIFIED_HANDOFF_VERIFIED incluyen únicamente un ID HOF verificado; las variantes sin verificación no afirman transferencia. Los textos están en resources/prompts/fallback_templates.yaml. La selección y lectura real siguen siendo trabajo del runtime.

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
| Selección válida con possible_duplicate_of o conflicting_duplicate persistente | duplicate_review; sin bucle de elección ni creación de reclamo |
| Un único candidato propio releído con señal persistente | duplicate_review directo; no pedir selección inútil |
| Snapshot cambia tras selección o confirmación | Invalidar target/consentimiento y volver a identificar/confirmar |
| Escritura/handoff sin lectura de verificación | No anunciar éxito o transferencia creada |
| Almacén sandbox no inicializado, ilegible o con ventana real de 24 h incompleta | `unrecognized_count_24h=null`, `risk_data_complete=false`; HANDOFF/missing_evidence, no asumir cero ni crear intake |
| Almacén sandbox íntegro y vacío; primera solicitud distinta propia | Cero casos previos y conteo R16 de uno al incluir la solicitud actual; continuar los demás guardas sin prometer éxito automático |
| Dos casos sandbox distintos propios verificados en las 24 h reales más solicitud actual distinta | Conteo R16 de tres; high_risk, crear y releer derivación, no intake automático |
| Replay idempotente o repetición del mismo movimiento | No incrementar el conteo ni crear un nuevo caso; aplicar R15/control atómico de duplicados |
| Fraud_score o monto alto verificado, pero otro indicador de riesgo incompleto | R16/high_risk con la señal verificada; no esperar ni declarar los demás indicadores como bajos |
| Falla el generador tras derivación creada y releída | Fallback ES/PT comunica la derivación verificada con su ID; nunca dice que sigue sin confirmar |
| Escritura del reclamo incierta seguida por derivación creada y releída | Conservar ACTION_UNVERIFIED para el reclamo y comunicar separadamente la derivación verificada con su ID |

Estos casos deben probarse en ES/PT donde hay interacción. Medir los desvíos a humano, la cobertura de fechas y la proporción de casos que el historial incierto impide automatizar; no ocultarlos del denominador.

Los ocho ejemplos ilustrativos de `resources/prompts/generator_prompt_v3.yml` usaban `current_date=2026-03-31`; seis mostraban candidatos de abril/mayo posteriores a esa fecha, incluso dos con action.executed=true. Sus siete fixtures paralelos en `contracts/examples/` repetían la inconsistencia. Esta propuesta los sitúa en una fecha hipotética posterior al último evento (`2026-06-19`) para que no enseñen una creación sobre un cargo futuro. El ejemplo BLOCKED también citaba R11, regla de NO_MATCH, pese a que el texto rechazaba una solicitud; se convierte en una petición explícita de datos de otro cliente bajo R2, sin lectura privada. Siguen siendo ejemplos sintéticos para revisión de Gloria, no casos gold ni evidencia de ejecución.

## Integración que todavía falta

El MCP actual consulta por process_date con límite de 31 días. El contrato de 90 días de event_date requiere una extensión o un adaptador que demuestre cobertura de particiones de proceso anteriores y posteriores al día del evento. También faltan los handlers de reclamos/handoff, scopes de escritura, estado pendiente durable, barrera por turno, consentimiento confiable, reserva atómica y lectura del recibo. El agregado sandbox de R16 debe implementarse con cobertura real y conteo sin replays; los registros históricos de contacto no lo sustituyen. Las variantes ES/PT de fallback están propuestas, pero falta el selector determinista y su prueba de lectura de handoff. La evaluación final independiente ES/PT y la medición del grafo v0 completo siguen siendo gates del producto. Ninguna comprobación de YAML/JSON demuestra estas capacidades.
