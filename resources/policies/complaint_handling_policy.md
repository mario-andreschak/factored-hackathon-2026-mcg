> Política SINTÉTICA creada por el equipo para el prototipo del hackathon.

## Registro
<!-- chunk_id: complaint-01 -->

Los reclamos simulados del prototipo se guardan en un ledger SQLite sandbox, con categoría Transactions y subcategoría Cargo no reconocido. El recibo se comunica solo tras relectura bajo el mismo cliente. Nunca se escribe en los datos originales ni se afirma haber registrado un reclamo en un banco real.

## Prevención de duplicados
<!-- chunk_id: complaint-02 -->

Son abiertos los estados Open, In Process y Escalated. Closed, Resolved y Rejected son terminales. En sandbox solo un vínculo verificado del mismo cliente y transaction_id identifica un reclamo de esa transacción y evita un registro duplicado. La reserva de creación y el control de duplicados son atómicos entre conversaciones.

El origen histórico no contiene transaction_id y sus afectados_productos no son vínculos válidos para atribución. Los reclamos propios abiertos de Transactions/Cargo no reconocido se conservan por separado con vínculo desconocido; campos faltantes que impidan descartarlos requieren revisión. No inferir relación por importe/moneda ni reparar producto por heurística. Si hay uno de estos casos o el control es incompleto, se solicita revisión humana antes de crear. Solo lecturas completas sin casos potenciales permiten continuar los demás guardas en el snapshot; no prueban ausencia de reclamos fuera del prototipo.

## Consulta de estado
<!-- chunk_id: complaint-03 -->

Solo se informa el estado releído del caso del cliente autenticado. El estado histórico sin transaction_id no se atribuye a un cargo específico. No se infiere resolución ni éxito por una afirmación del usuario. Una solicitud local HOF releída acredita el registro del paquete para revisión, no que un asesor la recibió o respondió.
