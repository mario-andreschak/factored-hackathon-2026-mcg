# Reconciliación propuesta del contrato v0

Estado: propuesta para revisión de Gloria y del equipo de implementación, vinculada a [issue #10](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/issues/10). Estos documentos no implementan herramientas, motor, permisos ni persistencia. La versión sintética 1.1.0 solo identifica el contrato propuesto; no declara una política desplegada.

Se conserva el objetivo de los prompts v0: aclarar un cargo propio no reconocido y llegar a un registro simulado confirmado, durable y releído, o a una derivación humana verificada. Las herramientas ausentes siguen siendo trabajo de implementación. Los prompts canónicos están en `resources/prompts/`.

## Tres decisiones concretas

1. **Historial de reclamos.** El [perfil auditado](../docs/DATA_REVIEW_2026-09-26.md) identifica vínculos de producto históricos que cruzan clientes y ausencia de transaction_id. Se elimina la atribución H1. Los vínculos exactos nuevos son del sandbox; los casos históricos propios potenciales se consultan por separado y su vínculo queda desconocido. Un caso histórico propio abierto de Transactions/Cargo no reconocido, o campos esenciales que no permitan descartarlo, requieren revisión antes de crear. Un cliente sin esos casos, con lecturas completas, puede continuar los demás guardas del registro simulado. Nunca se declara ausencia global de reclamos.
2. **Fechas de búsqueda.** Solo el default sin fechas usa hasta 90 fechas calendario de eventos del snapshot declarado, desde ancla−89 hasta ancla inclusive, limitado por la primera fecha disponible. Se muestran intervalo y carácter histórico. Fechas explícitas y expresiones como «ayer» conservan su sentido respecto de la fecha real del cliente. La elegibilidad de disputa sigue usando esa fecha real y 120 días: encontrar un movimiento histórico no lo vuelve elegible. Auth, confirmaciones y TTL nunca usan el reloj del snapshot. Falta de metadatos o cobertura produce error, no un NO_MATCH engañoso.
3. **Selección con señal de duplicado.** Elegir un ref propio identifica el target; no confirma una creación ni borra la señal. Si la señal persiste al releer, se crea y verifica una derivación con duplicate_review en lugar de repetir R12. Si no hay señal, el target puede avanzar por R13–R17 sin cambiar el match_count total de la búsqueda.

Se elige revisión humana para la señal persistente porque la selección por sí sola no certifica que los dos registros representen cargos independientes. No se concede al LLM permiso para relajar este control.

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
| Sin fechas; snapshot termina 2026-06-17, cobertura comienza antes del default | Consultar eventos 2026-03-20..2026-06-17; identificar snapshot en respuesta |
| «Ayer» el 2026-09-29 | Consultar 2026-09-28, sin cambiarlo a junio; comunicar cobertura/límites reales |
| Evento de marzo encontrado en septiembre | Elegibilidad respecto de fecha real; no autorizar por el ancla histórica |
| Evento llega en partición de proceso posterior | Consulta de eventos lo incluye o falla explícitamente por cobertura incompleta |
| Selección válida entre varios movimientos sin señal persistente | Fijar target; conservar match_count; pedir confirmación aparte si procede |
| Selección válida con possible_duplicate_of o conflicting_duplicate persistente | duplicate_review; sin bucle de elección ni creación de reclamo |
| Un único candidato propio releído con señal persistente | duplicate_review directo; no pedir selección inútil |
| Snapshot cambia tras selección o confirmación | Invalidar target/consentimiento y volver a identificar/confirmar |
| Escritura/handoff sin lectura de verificación | No anunciar éxito o transferencia creada |

Estos casos deben probarse en ES/PT donde hay interacción. Medir los desvíos a humano, la cobertura de fechas y la proporción de casos que el historial incierto impide automatizar; no ocultarlos del denominador.

## Integración que todavía falta

El MCP actual consulta por process_date con límite de 31 días. El contrato de 90 días de event_date requiere una extensión o un adaptador con prueba de cobertura de llegada tardía. También faltan los handlers de reclamos/handoff, scopes de escritura, estado pendiente durable, barrera por turno, consentimiento confiable, reserva atómica y lectura del recibo. La evaluación final independiente ES/PT y la medición del grafo v0 completo siguen siendo gates del producto. Ninguna comprobación de YAML/JSON demuestra estas capacidades.
