"""Pinned portable source and pure validation of freshly generated inputs."""
from __future__ import annotations

import csv
from datetime import datetime
import io
import os
from pathlib import Path
import subprocess
import time

from contract import (BANK, FLUJO, DATASET_FILES, FIXTURE_PIN_SHA, require,
                      require_runtime_release, safe_path, sha256, strict_json)

PRIVATE_ROOT = Path("/run/synthetic-integration")


def scoped_path(path: Path, root: Path = PRIVATE_ROOT, *, exists: bool = True) -> Path:
    require(path.is_absolute() and ".." not in path.parts and path != root
            and path.is_relative_to(root), "private_path_scope")
    require(all(not p.is_symlink() for p in (path, *path.parents)), "private_path_link")
    resolved = path.resolve(strict=exists)
    require(resolved == path and resolved.is_relative_to(root.resolve(strict=True)),
            "private_path_resolution")
    return resolved


def verify_source(source: Path) -> None:
    for relative, digest in DATASET_FILES.items():
        path = source / relative
        require(path.is_file() and not path.is_symlink() and sha256(path) == digest,
                "dataset_source_hash")
    pin = strict_json((source / "fixture_pin.json").read_bytes())
    require(pin["base_bank_commit"] == BANK and pin["base_flujo_commit"] == FLUJO
            and pin["new_runtime_source_pin"] is None, "dataset_source_identity")


def validate_generated(root: Path, *, now: int) -> dict:
    proof = strict_json((root / "fixture_inputs.json").read_bytes())
    require(proof.get("schema") == "present-relative-fictional-inputs/v1"
            and proof.get("base_bank_commit") == BANK and proof.get("base_flujo_commit") == FLUJO
            and proof.get("generator_source_sha256") == DATASET_FILES["generate_fixture.py"]
            and proof.get("contracts_source_sha256") == DATASET_FILES["source/pipeline/contracts.yaml"]
            and proof.get("serving_build_created") is False, "generated_fixture_identity")
    anchor = datetime.fromisoformat(proof["generated_at_real_utc"].replace("Z", "+00:00"))
    require(anchor.tzinfo is not None and anchor.utcoffset().total_seconds() == 0
            and anchor.microsecond == 0 and type(now) is int
            and 0 <= now - int(anchor.timestamp()) <= 900, "generated_fixture_real_anchor")
    transaction = "inputs/" + safe_path(proof["transaction_source_key"])
    expected = {"inputs/customers.csv", "inputs/products.csv", transaction,
                "closed_history.json", "coverage_initialization.json", "risk_evidence_blueprint.json"}
    digests = proof.get("source_files_sha256")
    require(isinstance(digests, dict) and set(digests) == expected, "generated_input_inventory")
    for relative, digest in digests.items():
        path = root / safe_path(relative)
        require(path.is_file() and not path.is_symlink() and sha256(path) == digest,
                "generated_input_hash")
    tables = {}
    source_objects = {}
    for table, filename in (("customers", "inputs/customers.csv"),
                            ("products", "inputs/products.csv"), ("transactions", transaction)):
        reader = csv.DictReader(io.StringIO((root / filename).read_text(encoding="utf-8")))
        require(reader.fieldnames and len(set(reader.fieldnames)) == len(reader.fieldnames), "generated_csv_columns")
        rows = list(reader)
        require(all(None not in row and None not in row.values() for row in rows)
                and rows == proof["tables"][table], "generated_csv_rows")
        tables[table] = rows
        source_objects[filename.removeprefix("inputs/")] = {
            "bytes": (root / filename).stat().st_size, "sha256": sha256(root / filename),
            "etag": "sha256:" + sha256(root / filename)[:32]}
    require({p.relative_to(root / "inputs").as_posix() for p in (root / "inputs").rglob("*.csv")}
            == set(source_objects), "extra_fixture_csv_forbidden")
    owners = sorted(row["customer_id"] for row in tables["customers"])
    require(owners == ["CUS900000", "CUS900001", "CUS900002"]
            and len(tables["products"]) == 3 and len(tables["transactions"]) == 7,
            "fictional_owner_inventory")
    history = strict_json((root / "closed_history.json").read_bytes())
    require(history.get("schema") == "authored-closed-synthetic-past-ledger/v1"
            and history.get("generation_anchor_real_utc") == proof["generated_at_real_utc"]
            and history.get("closed_through_real_utc") == proof["generated_at_real_utc"]
            and type(history.get("coverage_start_epoch")) is int
            and history["coverage_start_epoch"] == int(anchor.timestamp()) - 90000
            and datetime.fromisoformat(history["coverage_start_utc"].replace("Z", "+00:00")).timestamp()
                == history["coverage_start_epoch"]
            and all(history.get(key) == [] for key in ("cases", "receipts", "handoffs"))
            and sorted(history.get("owner_allowlist", [])) == owners
            and proof["closed_history_manifest_sha256"] == digests["closed_history.json"],
            "authored_closed_history_required")
    blueprint = strict_json((root / "coverage_initialization.json").read_bytes())
    require(blueprint.get("api_called_now") is False
            and blueprint.get("raw_SQL_or_timestamp_rewrite_permitted") is False
            and blueprint.get("start") == history["coverage_start_epoch"]
            and blueprint.get("history_manifest_sha256") == digests["closed_history.json"], "coverage_blueprint_binding")
    return {"fixture_pin_sha256": FIXTURE_PIN_SHA, "fixture_inputs_sha256": sha256(root / "fixture_inputs.json"),
            "source_files_sha256": digests, "source_objects": source_objects,
            "anchor_epoch": int(anchor.timestamp()),
            "coverage_start": history["coverage_start_epoch"], "owners": owners,
            "owner_source_sha256": sha256(root / "inputs/customers.csv")}


def generate(source: Path, destination: Path) -> dict:
    """Remote only. Generator writes inputs/unit doubles, never action state."""
    require_runtime_release(dict(os.environ))
    verify_source(source)
    scoped_path(destination, exists=False)
    require(not destination.exists(), "fresh_generator_destination")
    command = ["/opt/banking-mcp/.venv/bin/python", str(source / "generate_fixture.py"),
               "--output-dir", str(destination)]
    subprocess.run(command, check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(command + ["--check"], check=True, timeout=60,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return validate_generated(destination, now=int(time.time()))
