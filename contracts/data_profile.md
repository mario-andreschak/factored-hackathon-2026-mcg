# Perfil de datos verificado

Consultas completas sobre CSV; data_s3 se abre exclusivamente para lectura.

## transaction_type

```sql
SELECT transaction_type, count(*) AS n FROM read_csv('data_s3/transactions/*/*/*/*.csv', hive_partitioning=true, union_by_name=true) GROUP BY transaction_type ORDER BY n DESC;
```

| transaction_type | n |
| --- | --- |
| Purchase | 1083406 |
| Withdrawal | 964673 |
| Transfer | 896438 |
| Payment | 738964 |
| Deposit | 609409 |
| Adjustment | 132118 |
## channel

```sql
SELECT channel, count(*) AS n FROM read_csv('data_s3/transactions/*/*/*/*.csv', hive_partitioning=true, union_by_name=true) GROUP BY channel ORDER BY n DESC;
```

| channel | n |
| --- | --- |
| POS | 1548161 |
| ATM | 1328334 |
| Web | 663445 |
| App | 663414 |
| Branch | 132495 |
| Transfer | 89159 |
## transaction_status

```sql
SELECT transaction_status, count(*) AS n FROM read_csv('data_s3/transactions/*/*/*/*.csv', hive_partitioning=true, union_by_name=true) GROUP BY transaction_status ORDER BY n DESC;
```

| transaction_status | n |
| --- | --- |
| Approved | 4070681 |
| Declined | 221234 |
| Pending | 88343 |
| Reversed | 44750 |
## currency

```sql
SELECT currency, count(*) AS n FROM read_csv('data_s3/transactions/*/*/*/*.csv', hive_partitioning=true, union_by_name=true) GROUP BY currency ORDER BY n DESC;
```

| currency | n |
| --- | --- |
| USD | 2437979 |
| COP | 1194444 |
| ARS | 792585 |
## complaint_categories

```sql
SELECT category, subcategory, count(*) AS n FROM read_csv('data_s3/complaints/*/*/*/*.csv', hive_partitioning=true, union_by_name=true) GROUP BY category, subcategory ORDER BY n DESC;
```

| category | subcategory | n |
| --- | --- | --- |
| Transactions | Cargo no reconocido | 12297 |
| Fees | Cobro indebido | 12194 |
| Technical | Problema con app | 12128 |
| Branch | Atención en sucursal | 11892 |
| Service | Calidad de servicio | 11886 |
| Branch | NULL | 1469 |
| Fees | NULL | 1359 |
| Service | NULL | 1308 |
| Transactions | NULL | 1283 |
| Technical | NULL | 1279 |
## complaint_status

```sql
SELECT status, count(*) AS n FROM read_csv('data_s3/complaints/*/*/*/*.csv', hive_partitioning=true, union_by_name=true) GROUP BY status ORDER BY n DESC;
```

| status | n |
| --- | --- |
| In Process | 26823 |
| Open | 20125 |
| Resolved | 13512 |
| Escalated | 3321 |
| Closed | 2609 |
| Rejected | 705 |
## product_type

```sql
SELECT product_type, count(*) AS n FROM read_csv('data_s3/products.csv', hive_partitioning=true, union_by_name=true) GROUP BY product_type ORDER BY n DESC;
```

| product_type | n |
| --- | --- |
| Cuenta Ahorro | 120203 |
| Tarjeta Crédito | 100102 |
| Cuenta Corriente | 99979 |
| Tarjeta Débito | 39938 |
| Préstamo Personal | 19960 |
| Préstamo Hipotecario | 11910 |
| Inversión | 5859 |
| Seguro | 2049 |
## transcript_language

```sql
SELECT detected_language, count(*) AS n FROM read_csv('data_s3/call_transcripts/*/*/*/*.csv', hive_partitioning=true, union_by_name=true) GROUP BY detected_language ORDER BY n DESC;
```

| detected_language | n |
| --- | --- |
| es | 171321 |
## contact_reasons

```sql
SELECT contact_reason, reason_category, count(*) AS n FROM read_csv('data_s3/call_center_interactions/*/*/*/*.csv', hive_partitioning=true, union_by_name=true) GROUP BY contact_reason, reason_category ORDER BY n DESC;
```

| contact_reason | reason_category | n |
| --- | --- | --- |
| Transaccional | Transaccional | 240056 |
| Producto | Producto | 150863 |
| Queja | Queja | 117021 |
| Técnico | Técnico | 102899 |
| Comercial | Comercial | 54879 |
| Retención | Retención | 20578 |
## case_type

```sql
SELECT case_type, count(*) AS n FROM read_csv('data_s3/complaints/*/*/*/*.csv', hive_partitioning=true, union_by_name=true) GROUP BY case_type ORDER BY n DESC;
```

| case_type | n |
| --- | --- |
| Complaint | 40452 |
| Claim | 16598 |
| Request | 6761 |
| Suggestion | 3284 |

Estados abiertos: Open, In Process, Escalated. Closed y Resolved son terminales; NULL o un estado desconocido impiden crear hasta aclarar.
## Umbral de riesgo sintético

Consulta: COUNT(fraud_score), COUNT(*) FILTER (WHERE fraud_score < 70), QUANTILE_CONT(fraud_score, .95/.99). N no nulo=3539851; fracción bajo 70=0.999718; p95=28.52; p99=29.72. El umbral 70 no está calibrado contra resultados humanos.

El diccionario PDF confirma las enumeraciones de tipos, canales y estados. Rejected también es terminal.
