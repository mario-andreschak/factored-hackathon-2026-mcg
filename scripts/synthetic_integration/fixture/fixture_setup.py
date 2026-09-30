"""Held remote setup with the original interpreter/pipeline/StateStore only."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

from contract import require, require_runtime_release, strict_json
from dataset import generate, scoped_path
from fixture_coverage import initialize, read_empty_generation, verify_snapshot_sources


def setup(root: Path, *, attested: bool, service_token: str) -> None:
    require_runtime_release(dict(os.environ))
    require(sys.executable == "/opt/banking-mcp/.venv/bin/python", "original_bank_interpreter")
    scoped_path(root)
    inputs = generate(Path("/opt/integration/fixture/dataset_source"), root / "generated")
    subprocess.run([sys.executable, "-m", "pipeline", "run", "--source", str(root / "generated/inputs"),
                    "--out", str(root / "dataset"), "--reports", str(root / "reports"),
                    "--tables", "customers", "products", "transactions", "--threads", "1",
                    "--memory-limit", "256MB"], cwd="/opt/banking-mcp", check=True, timeout=120,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Import only AFTER the release guard. No Service/Actions call is used here.
    import duckdb
    from banking_mcp.repository import Snapshot, Repository
    from banking_mcp.security import StateStore
    from pipeline.common import current_build
    require(Path(inspect.getfile(Snapshot)).resolve() == Path("/opt/banking-mcp/banking_mcp/repository.py")
            and Path(inspect.getfile(StateStore)).resolve() == Path("/opt/banking-mcp/banking_mcp/security.py"),
            "original_installed_bank_required")
    build = current_build(root / "dataset")
    scoped_path(build)
    facts = {}
    with duckdb.connect(":memory:") as con:
        snapshot = Snapshot(build, con)
        require(sorted(snapshot.customers) == inputs["owners"], "generated_owner_inventory")
        verify_snapshot_sources(snapshot.objects, inputs["source_objects"], snapshot.source_fingerprint)
        # Independent read-only projections of the actual ownership-checked gold
        # facts. No MCP call, capability, pending row or receipt is initialized.
        paths = [str(p) for files in snapshot.bucket_files.values() for p in files]
        con.read_parquet(paths).create_view("fixture_transactions")
        for actor, customer, transaction in (("es", "CUS900000", "TXN90000000"),
                                              ("pt", "CUS900001", "TXN90000001")):
            result = con.execute("SELECT * FROM fixture_transactions WHERE transaction_id=? AND customer_id=? "
                                 "AND ownership_valid", [transaction, customer])
            names = [item[0] for item in result.description]
            rows = result.fetchall()
            require(len(rows) == 1, "generated_owned_normal_charge")
            row = dict(zip(names, rows[0]))
            require(snapshot.products[row["product_id"]][0] == customer, "generated_product_owner")
            facts[actor] = Repository._visible(SimpleNamespace(config=SimpleNamespace(service_token=service_token)),
                                                row, snapshot)
    marker = {"kind": "team_synthetic_fixture", "build_id": build.name,
              "source_fingerprint": snapshot.source_fingerprint}
    for path in (root / "synthetic_provenance.json", build / "synthetic_provenance.json"):
        with path.open("x", encoding="utf-8") as stream:
            json.dump(marker, stream, sort_keys=True, separators=(",", ":"))
    blueprint = strict_json((root / "generated/risk_evidence_blueprint.json").read_bytes())
    evidence = {"build_id": build.name, "source_fingerprint": snapshot.source_fingerprint,
                "transactions": blueprint["normal_transactions"]}
    with (root / "risk-evidence.json").open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, sort_keys=True, separators=(",", ":"))
    state_db = root / "bank-state/actions.sqlite"
    if attested:
        coverage_start = initialize(state_db, build / "snapshot.json", generated_dir=root / "generated",
                                    out=root / "bank-state/coverage-history.json")
    else:
        state_db.parent.mkdir(mode=0o700)
        store = StateStore(state_db)
        with store.connect() as db:
            read_empty_generation(db)
            require(db.execute("SELECT count(*) FROM sandbox_coverage").fetchone()[0] == 0,
                    "stock_coverage_must_be_absent")
        coverage_start = None
    # Verify real fresh generation after setup; this metadata alone is never
    # commit proof. Observers reopen the original database on every readback.
    with StateStore(state_db).connect() as db:
        generation = db.execute("SELECT generation FROM sandbox_ledger_identity WHERE id=1").fetchone()[0]
    metadata = {**marker, "facts": facts, "generation": generation, "coverage_start": coverage_start,
                "snapshot_file": str(build / "snapshot.json"), "created_at_real": time.time(),
                "risk_evidence_sha256": hashlib.sha256((root / "risk-evidence.json").read_bytes()).hexdigest()}
    with (root / "setup-readback.json").open("x", encoding="utf-8") as stream:
        json.dump(metadata, stream, sort_keys=True, separators=(",", ":"))


if __name__ == "__main__":
    require_runtime_release(dict(os.environ))
    require(len(sys.argv) == 3 and sys.argv[2] in {"stock", "attested"}, "setup_arguments")
    setup(Path(sys.argv[1]), attested=sys.argv[2] == "attested",
          service_token=os.environ["SYNTHETIC_BANK_SERVICE_TOKEN"])
