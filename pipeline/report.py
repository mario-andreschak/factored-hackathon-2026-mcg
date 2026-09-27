"""Write docs/pipeline/manifest.json and quality_report.md (aggregates only, safe to commit)."""

from __future__ import annotations

import json
from pathlib import Path

from .common import PIPELINE_VERSION, contracts_digest


def _fmt(n) -> str:
    return f"{n:,}" if isinstance(n, int) else ("—" if n is None else str(n))


def write(report_dir: Path, run: dict, stats: dict) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"pipeline_version": PIPELINE_VERSION, "contracts_sha256_12": contracts_digest(),
                **run, "tables": {k: v for k, v in stats.items() if not k.startswith("_")},
                "gold": stats.get("_gold", {}),
                "contract_failures": stats.get("_contract_failures", [])}
    (report_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

    L = [f"# Data quality report",
         "",
         f"Run `{run['run_id']}` · pipeline {PIPELINE_VERSION} · contracts `{contracts_digest()}` · "
         f"source `{run['source']}` · stages `{run['stages']}`",
         "",
         "Measured by `python -m pipeline run`. Every raw row is accounted for: "
         "**raw = silver + quarantined + duplicates removed** (the *Reconciles* column).",
         ""]
    if stats.get("_contract_failures"):
        L += ["> **Contract failures:**", *[f"> - {f}" for f in stats["_contract_failures"]], ""]

    L += ["## Row accounting", "",
          "| Table | Source objects | Raw rows | Quarantined | Dups removed | Silver rows | Reconciles | "
          "Late arrivals | Partition≠process_date |",
          "|---|---:|---:|---:|---:|---:|:-:|---:|---:|"]
    for t, s in stats.items():
        if t.startswith("_"):
            continue
        b, sv = s.get("bronze", {}), s.get("silver", {})
        L.append(f"| {t} | {_fmt(b.get('source_objects'))} | {_fmt(sv.get('raw_rows', b.get('rows')))} | "
                 f"{_fmt(sv.get('quarantined_rows'))} | {_fmt(sv.get('duplicate_rows_removed'))} | "
                 f"{_fmt(sv.get('rows'))} | {'✅' if sv.get('reconciles') else ('❌' if sv else '—')} | "
                 f"{_fmt(sv.get('late_arrivals'))} | {_fmt(sv.get('partition_date_mismatch'))} |")

    L += ["", "## Duplicates", "",
          "| Table | Duplicate rows removed | PKs with >1 version | PKs whose versions differ |",
          "|---|---:|---:|---:|"]
    for t, s in stats.items():
        sv = s.get("silver") if not t.startswith("_") else None
        if sv:
            L.append(f"| {t} | {_fmt(sv['duplicate_rows_removed'])} | {_fmt(sv['pks_with_multiple_versions'])} "
                     f"| {_fmt(sv['pks_with_conflicting_content'])} |")

    L += ["", "## Referential integrity (orphans are flagged, not dropped)", "",
          "| Table.column | → parent | Non-null | Missing in parent | Rate | Parent owned by another customer |",
          "|---|---|---:|---:|---:|---:|"]
    for t, s in stats.items():
        sv = s.get("silver") if not t.startswith("_") else None
        for col, o in (sv or {}).get("orphans", {}).items():
            m, nn = o["missing_in_parent"], o["non_null"]
            rate = f"{m / nn:.2%}" if m is not None and nn else "—"
            other = o.get("owned_by_other_customer")
            other_s = "—" if other is None else (f"{_fmt(other)} ({other / nn:.2%})" if nn else _fmt(other))
            L.append(f"| {t}.{col} | {o['parent']} | {_fmt(nn)} | {_fmt(m)} | {rate} | {other_s} |")

    L += ["", "## Quarantine reasons", ""]
    any_q = False
    for t, s in stats.items():
        sv = s.get("silver") if not t.startswith("_") else None
        if sv and sv["reject_reasons"]:
            any_q = True
            L.append(f"- **{t}**: " + ", ".join(f"`{r}` {_fmt(n)}" for r, n in list(sv["reject_reasons"].items())[:8]))
    if not any_q:
        L.append("None.")

    L += ["", "## Nullable columns — null rate (top 6 per table)", ""]
    for t, s in stats.items():
        sv = s.get("silver") if not t.startswith("_") else None
        if sv and sv["null_rates"]:
            top = sorted(sv["null_rates"].items(), key=lambda kv: -kv[1])[:6]
            L.append(f"- **{t}**: " + ", ".join(f"{c} {v:.1%}" for c, v in top))

    L += ["", "## Contract drift", ""]
    drift = False
    for t, s in stats.items():
        sv = s.get("silver") if not t.startswith("_") else None
        if not sv:
            continue
        for label, key in (("out-of-vocabulary values (enum, warn mode)", "enum_out_of_vocabulary"),):
            for col, vals in sv[key].items():
                drift = True
                L.append(f"- **{t}.{col}** {label}: " + ", ".join(f"`{v}` {_fmt(n)}" for v, n in vals.items()))
        for col, groups in sv.get("inconsistent_spellings", {}).items():
            drift = True
            for grp in groups:
                L.append(f"- **{t}.{col}** same value, different spelling: "
                         + ", ".join(f"`{v}` {_fmt(n)}" for v, n in grp.items()))
        if sv["contract_columns_absent_in_source"]:
            drift = True
            L.append(f"- **{t}** contract columns absent in source: {sv['contract_columns_absent_in_source']}")
        if sv["source_columns_not_in_contract"]:
            drift = True
            L.append(f"- **{t}** source columns not in contract (schema evolution?): "
                     f"{sv['source_columns_not_in_contract']}")
    if not drift:
        L.append("None detected.")

    gold = stats.get("_gold", {})
    if gold:
        L += ["", "## Gold outputs", ""]
        if "transactions_by_customer" in gold:
            x = gold["transactions_by_customer"]
            L.append(f"- **transactions_by_customer**: {_fmt(x['rows'])} rows in {x['buckets']} buckets; "
                     f"{_fmt(x['ownership_valid_rows'])} with product owned by the same customer "
                     f"(only these are served).")
        if "classifier_dataset" in gold:
            x = gold["classifier_dataset"]
            L.append(f"- **classifier_dataset**: {_fmt(x['rows'])} rows, splits {x['splits']}, "
                     f"time holdout {x['time_holdout']}. Distinct normalized texts: "
                     f"{_fmt(x['distinct_normalized_texts'])}. **Test rows whose exact text also appears in "
                     f"train: {_fmt(x['test_rows_with_text_seen_in_train'])} "
                     f"({x['test_text_leakage_rate']})** — report metrics on the unseen-text subset too.")
        if "contact_demand" in gold:
            x = gold["contact_demand"]
            L.append(f"- **contact_demand**: {_fmt(x['rows'])} rows. Top reasons: " + "; ".join(
                f"{r['reason']} {r['share']:.1%}" for r in x["top_contact_reasons"][:6]))
        if "demo_seed_candidates" in gold:
            x = gold["demo_seed_candidates"]
            L.append("- **demo_seed_candidates** (customers eligible per scenario; up to 25 picked each): "
                     + ", ".join(f"{k} {_fmt(v)}" for k, v in x["customers_eligible"].items())
                     + (". **No natural near-duplicate charges exist**: the 'charged twice' demo needs a "
                        "clearly labeled synthetic injection." if not x["customers_eligible"].get("near_duplicate")
                        else "."))
        if "lookup_bench" in gold:
            x = gold["lookup_bench"]
            L.append(f"- **lookup latency** ({x['samples']} customers, local disk): "
                     f"p50 {x['p50_ms']} ms · p95 {x['p95_ms']} ms · max {x['max_ms']} ms.")
    L.append("")
    (report_dir / "quality_report.md").write_text("\n".join(L), encoding="utf-8")
