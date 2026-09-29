> Política SINTÉTICA creada por el equipo para el prototipo del hackathon.

## Registro
<!-- chunk_id: complaint-01 -->

Los reclamos del prototipo se guardan en sandbox, con categoría Transactions y subcategoría Cargo no reconocido. Nunca se escribe en los datos originales.

## Prevención de duplicados
<!-- chunk_id: complaint-02 -->

Son abiertos los estados Open, In Process y Escalated. Closed, Resolved y Rejected son terminales. En origen no existe vínculo transaction_id: la coincidencia por cliente, producto, moneda e importe es heurística. En sandbox el vínculo es exacto. Un posible reclamo abierto relacionado impide crear otro automáticamente.

## Consulta de estado
<!-- chunk_id: complaint-03 -->

Solo se informa el estado releído del caso del cliente autenticado. No se infiere resolución ni éxito por una afirmación del usuario.
