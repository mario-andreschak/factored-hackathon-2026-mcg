"""Silver: enforce contracts, quarantine bad rows, dedup by PK, flag orphans and late arrivals.

Nothing disappears silently: every raw row ends up either in silver, in quarantine
(with reasons), or counted as a removed duplicate. The quality report reconciles
raw = silver + quarantined + duplicates_removed for every table.
"""

from __future__ import annotations

import time

from .common import Settings, connect, ident, load_contracts, sql_path

# Parents first so FK checks can see them.
ORDER = ["customers", "products", "call_center_interactions", "transactions",
         "call_transcripts", "complaints"]


def _typed_select(spec: dict, bronze_cols: set[str], table: str) -> tuple[str, str, list[str]]:
    """Return (select list, reject-reasons expression, contract columns absent from source)."""
    select, reasons, absent = [], [], []
    severity = spec.get("enum_severity", "warn")
    for col, c in spec["columns"].items():
        if c.get("drop"):
            continue
        q, typ = ident(col), c["type"]
        if col not in bronze_cols:
            absent.append(col)
            select.append(f"NULL::{typ} AS {q}")
            if c.get("required"):
                reasons.append(f"'missing_column:{col}'")
            continue
        raw = f"NULLIF(trim({q}), '')"
        typed = f"TRY_CAST({raw} AS {typ})"
        select.append(f"{typed} AS {q}")
        if c.get("required"):
            reasons.append(f"CASE WHEN {raw} IS NULL THEN 'null:{col}' END")
        reasons.append(f"CASE WHEN {raw} IS NOT NULL AND {typed} IS NULL THEN 'cast_failed:{col}' END")
        if c.get("enum") and severity == "reject":
            allowed = ", ".join("'" + v.replace("'", "''") + "'" for v in c["enum"])
            reasons.append(f"CASE WHEN {raw} IS NOT NULL AND {raw} NOT IN ({allowed}) THEN 'enum:{col}' END")
    reasons_expr = "list_filter([" + ", ".join(reasons) + "]::VARCHAR[], x -> x IS NOT NULL)"
    return ", ".join(select), reasons_expr, absent


def run(settings: Settings, run_id: str, stats: dict) -> None:
    contracts = load_contracts()
    con = connect(settings)
    settings.silver.mkdir(parents=True, exist_ok=True)
    settings.quarantine.mkdir(parents=True, exist_ok=True)
    failures = []

    for table in [t for t in ORDER if t in settings.tables]:
        t0 = time.perf_counter()
        spec = contracts[table]
        pk = ident(spec["pk"])
        bronze = sql_path(settings.bronze / f"{table}.parquet")
        bronze_cols = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{bronze}'").fetchall()}
        select, reasons_expr, absent = _typed_select(spec, bronze_cols, table)
        unexpected = sorted(c for c in bronze_cols
                            if not c.startswith("_") and c not in spec["columns"])

        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE typed AS
            SELECT {select}, _source_file, _partition_date, _run_id, _ingested_at,
                   {reasons_expr} AS _reject_reasons
            FROM '{bronze}'
        """)
        raw_rows = con.execute("SELECT count(*) FROM typed").fetchone()[0]

        # Quarantine: keep the offending row + reasons (local only, git-ignored).
        con.execute(f"""COPY (SELECT * FROM typed WHERE len(_reject_reasons) > 0)
                        TO '{sql_path(settings.quarantine / f"{table}.parquet")}' (FORMAT parquet)""")
        reject_reasons = dict(con.execute("""
            SELECT reason, count(*) FROM (SELECT unnest(_reject_reasons) AS reason FROM typed)
            GROUP BY 1 ORDER BY 2 DESC""").fetchall())
        rejected = con.execute("SELECT count(*) FROM typed WHERE len(_reject_reasons) > 0").fetchone()[0]

        # Dedup. A content hash separates exact re-deliveries from conflicting versions.
        content_cols = [ident(c) for c, s in spec["columns"].items() if not s.get("drop")]
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE ranked AS
            SELECT *, row_number() OVER (PARTITION BY {pk}
                                         ORDER BY {spec["dedup_order"]}, _row_hash) AS _rn
            FROM (
                SELECT *, md5(concat_ws('|', {", ".join(f"coalesce({c}::VARCHAR, '∅')" for c in content_cols)}))
                            AS _row_hash
                FROM typed WHERE len(_reject_reasons) = 0
            )
        """)
        dup = con.execute(f"""
            SELECT count(*) FILTER (WHERE _rn > 1),
                   count(DISTINCT {pk}) FILTER (WHERE n_versions > 1),
                   count(DISTINCT {pk}) FILTER (WHERE n_hashes > 1)
            FROM (SELECT *, count(*) OVER (PARTITION BY {pk}) AS n_versions,
                            count(DISTINCT _row_hash) OVER (PARTITION BY {pk}) AS n_hashes
                  FROM ranked)
        """).fetchone()

        # Orphan flags against parents already written this run.
        fk_cols, fk_stats = [], {}
        for col, c in spec["columns"].items():
            if not c.get("fk") or c.get("drop"):
                continue
            parent, parent_col = c["fk"].split(".")
            parent_path = settings.silver / f"{parent}.parquet"
            flag = f"_fk_{col}_missing"
            if parent in settings.tables and parent_path.exists():
                fk_cols.append(f"""({ident(col)} IS NOT NULL AND {ident(col)} NOT IN
                    (SELECT {ident(parent_col)} FROM '{sql_path(parent_path)}')) AS {ident(flag)}""")
            else:
                fk_cols.append(f"NULL::BOOLEAN AS {ident(flag)}")
            fk_stats[col] = parent

        late = ("(_partition_date IS NOT NULL AND process_date IS NOT NULL "
                "AND _partition_date > process_date)"
                if "process_date" in spec["columns"] else "false")
        partition_mismatch = ("(_partition_date IS NOT NULL AND process_date IS NOT NULL "
                              "AND _partition_date <> process_date)"
                              if "process_date" in spec["columns"] else "false")
        extra = (", " + ", ".join(fk_cols)) if fk_cols else ""
        out = settings.silver / f"{table}.parquet"
        con.execute(f"""
            COPY (
                SELECT * EXCLUDE (_rn, _reject_reasons),
                       {late} AS _late_arrival,
                       {partition_mismatch} AS _partition_mismatch
                       {extra}
                FROM ranked WHERE _rn = 1
                ORDER BY {pk}
            ) TO '{sql_path(out)}' (FORMAT parquet, COMPRESSION zstd)
        """)
        silver_rows = con.execute(f"SELECT count(*) FROM '{sql_path(out)}'").fetchone()[0]

        orphans = {}
        for col, parent in fk_stats.items():
            flag = ident(f"_fk_{col}_missing")
            nonnull, missing = con.execute(
                f"SELECT count({ident(col)}), count(*) FILTER (WHERE {flag}) FROM '{sql_path(out)}'"
            ).fetchone()
            orphans[col] = {"parent": parent, "non_null": nonnull,
                            "missing_in_parent": missing if parent in settings.tables else None}
        late_n, mismatch_n = con.execute(
            f"SELECT count(*) FILTER (WHERE _late_arrival), count(*) FILTER (WHERE _partition_mismatch) "
            f"FROM '{sql_path(out)}'").fetchone()

        # Null rates on nullable columns and out-of-vocabulary enum values (warn mode).
        nullable = [c for c, s in spec["columns"].items() if not s.get("drop") and not s.get("required")]
        null_rates = {}
        if nullable and silver_rows:
            row = con.execute("SELECT " + ", ".join(
                f"avg(({ident(c)} IS NULL)::INT)" for c in nullable) + f" FROM '{sql_path(out)}'").fetchone()
            null_rates = {c: round(v, 4) for c, v in zip(nullable, row)}
        enum_issues = {}
        for col, c in spec["columns"].items():
            if c.get("enum") and not c.get("drop"):
                allowed = ", ".join("'" + v.replace("'", "''") + "'" for v in c["enum"])
                vals = con.execute(f"""SELECT {ident(col)}, count(*) FROM '{sql_path(out)}'
                    WHERE {ident(col)} IS NOT NULL AND {ident(col)} NOT IN ({allowed})
                    GROUP BY 1 ORDER BY 2 DESC LIMIT 8""").fetchall()
                if vals:
                    enum_issues[col] = dict(vals)

        reject_rate = rejected / raw_rows if raw_rows else 0.0
        s = stats.setdefault(table, {})
        s["silver"] = {
            "raw_rows": raw_rows,
            "quarantined_rows": rejected,
            "reject_rate": round(reject_rate, 5),
            "reject_reasons": reject_reasons,
            "duplicate_rows_removed": dup[0],
            "pks_with_multiple_versions": dup[1],
            "pks_with_conflicting_content": dup[2],
            "rows": silver_rows,
            "reconciles": raw_rows == silver_rows + rejected + dup[0],
            "late_arrivals": late_n,
            "partition_date_mismatch": mismatch_n,
            "orphans": orphans,
            "null_rates": null_rates,
            "enum_out_of_vocabulary": enum_issues,
            "contract_columns_absent_in_source": absent,
            "source_columns_not_in_contract": unexpected,
            "seconds": round(time.perf_counter() - t0, 1),
        }
        print(f"silver  {table:<26} {silver_rows:>11,} rows | quarantined {rejected:,} "
              f"| dups removed {dup[0]:,} | late {late_n:,} ({s['silver']['seconds']}s)", flush=True)
        if reject_rate > spec.get("max_reject_rate", 0.05):
            failures.append(f"{table}: reject rate {reject_rate:.2%} > "
                            f"{spec.get('max_reject_rate', 0.05):.2%} — top reasons {list(reject_reasons)[:3]}")

    if failures:
        stats["_contract_failures"] = failures
