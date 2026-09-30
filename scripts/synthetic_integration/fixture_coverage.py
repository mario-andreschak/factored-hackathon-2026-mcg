"""Remote authored coverage setup through bank71's supported API.

Importing performs no bank import, database or attestation work. The provider
invokes this with the installed bank interpreter BEFORE starting any service.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time

from contract import BANK, DATASET_FILES, FIXTURE_PIN_SHA, require, sha256, strict_json, require_runtime_release
from dataset import scoped_path, validate_generated

ACTION_TABLES = ("sandbox_cases", "sandbox_case_receipts", "sandbox_handoffs", "action_pending")
ALL_TABLES = ACTION_TABLES + ("replays", "revoked", "sessions", "capabilities", "sandbox_coverage")


def canonical_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def canonical_digest(value: dict) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def verify_snapshot_sources(objects: dict, expected: dict, fingerprint: str) -> None:
    require(set(objects) == set(expected), "snapshot_generated_source_inventory")
    digest = hashlib.sha256()
    for key in sorted(expected):
        actual, generated = objects[key], expected[key]
        require(actual.get("key") == key and type(actual.get("bytes")) is int
                and actual["bytes"] == generated["bytes"] and actual.get("etag") == generated["etag"]
                and generated["etag"] == "sha256:" + generated["sha256"][:32],
                "snapshot_generated_source_object")
        digest.update(f"{key}|{generated['etag']}|{generated['bytes']}\n".encode())
    require(fingerprint == digest.hexdigest()[:16], "snapshot_generated_fingerprint")


def make_history(*, close_epoch: int, generation: str, build: str, fingerprint: str,
                 snapshot_sha256: str, inputs: dict, release: dict) -> dict:
    require(type(close_epoch) is int and 0 <= close_epoch - inputs["anchor_epoch"] <= 900, "history_close_real_time")
    require(all(isinstance(v, str) and re.fullmatch(r"[a-f0-9]{64}", v)
                for v in (generation, snapshot_sha256, inputs["owner_source_sha256"],
                          inputs["fixture_inputs_sha256"])), "history_digest_required")
    require(inputs["fixture_pin_sha256"] == FIXTURE_PIN_SHA
            and inputs["owners"] == ["CUS900000", "CUS900001", "CUS900002"]
            and type(inputs["coverage_start"]) is int
            and inputs["coverage_start"] == inputs["anchor_epoch"] - 90000, "history_input_binding")
    require(isinstance(build, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,96}", build)
            and isinstance(fingerprint, str) and re.fullmatch(r"[a-f0-9]{16,64}", fingerprint), "history_snapshot_binding")
    require(re.fullmatch(r"[a-f0-9]{40}", release["reviewed_head"])
            and re.fullmatch(r"[a-f0-9]{40}", release["bundle_source_head"])
            and re.fullmatch(r"[a-f0-9]{64}", release["bundle_manifest_sha256"]), "history_review_binding")
    return {"schema": "banking-authored-empty-history-binding/v1", "synthetic": True,
            "evidence_basis": "authored_fictional_past_not_observed_25h_operation",
            "banking_source": BANK, "generator_file_sha256": DATASET_FILES["generate_fixture.py"],
            "fixture_pin_sha256": FIXTURE_PIN_SHA, "inputs": inputs,
            "integration_source": release["reviewed_head"], "bundle_source_head": release["bundle_source_head"],
            "bundle_manifest_sha256": release["bundle_manifest_sha256"], "ledger_generation": generation,
            "dataset": {"build": build, "source_fingerprint": fingerprint, "snapshot_sha256": snapshot_sha256},
            "interval": {"start": inputs["coverage_start"], "end": close_epoch, "closed": True},
            "setup_gap": {"from": inputs["anchor_epoch"], "through": close_epoch, "events": [],
                          "basis": "exclusive_fresh_setup_before_any_service",
                          "clock_precision": "stock_time_time_integer_seconds"},
            "action_counts_before_api": {table: 0 for table in ACTION_TABLES}}


def validate_history(history: dict, **bindings) -> tuple[int, str]:
    require(canonical_digest(history) == canonical_digest(make_history(**bindings)), "authored_history_binding_mismatch")
    return history["interval"]["start"], "synthetic:" + canonical_digest(history)


def read_empty_generation(db) -> str:
    generation = db.execute("SELECT generation FROM sandbox_ledger_identity WHERE id=1").fetchone()[0]
    require(isinstance(generation, str) and re.fullmatch(r"[a-f0-9]{64}", generation), "fresh_generation")
    require(all(db.execute("SELECT count(*) FROM " + table).fetchone()[0] == 0 for table in ALL_TABLES),
            "fixture_ledger_not_empty")
    return generation


def initialize(state_db: Path, snapshot_file: Path, *, generated_dir: Path, out: Path) -> int:
    release = require_runtime_release(dict(os.environ))
    require(sys.executable == "/opt/banking-mcp/.venv/bin/python", "installed_bank_interpreter_required")
    scoped_path(snapshot_file)
    require(snapshot_file.name == "snapshot.json", "snapshot_manifest_name")
    scoped_path(generated_dir)
    scoped_path(state_db, exists=False)
    scoped_path(out, exists=False)
    setup = state_db.parent
    require(setup == out.parent and state_db.name == "actions.sqlite" and out.name == "coverage-history.json"
            and not setup.exists(), "exclusive_fresh_setup_required")
    # Atomic reservation. Failed or already reserved setups are never reused.
    setup.mkdir(mode=0o700, parents=False, exist_ok=False)
    inputs = validate_generated(generated_dir, now=int(time.time()))
    import duckdb
    from banking_mcp.repository import Snapshot
    from banking_mcp.security import StateStore
    from pipeline.bronze import fingerprint as stock_fingerprint
    require(Path(inspect.getfile(StateStore)).resolve() == Path("/opt/banking-mcp/banking_mcp/security.py")
            and Path(inspect.getfile(Snapshot)).resolve() == Path("/opt/banking-mcp/banking_mcp/repository.py"),
            "original_installed_bank_source_required")
    with duckdb.connect(":memory:") as con:
        snapshot = Snapshot(snapshot_file.parent, con)
        require(sorted(snapshot.customers) == inputs["owners"], "snapshot_owner_inventory")
        require(snapshot.source_fingerprint == strict_json(snapshot_file.read_bytes())["source_fingerprint"],
                "snapshot_source_identity")
        verify_snapshot_sources(snapshot.objects, inputs["source_objects"], snapshot.source_fingerprint)
        require(stock_fingerprint(list(snapshot.objects.values())) == snapshot.source_fingerprint,
                "stock_fingerprint_binding")
    store = StateStore(state_db)
    with store.connect() as db:
        generation = read_empty_generation(db)
    close_epoch = int(time.time())
    bindings = dict(close_epoch=close_epoch, generation=generation, build=snapshot.id,
                    fingerprint=snapshot.source_fingerprint, snapshot_sha256=sha256(snapshot_file),
                    inputs=inputs, release=release)
    history = make_history(**bindings)
    start, provenance = validate_history(history, **bindings)
    # Hash the empty generator -> fresh-ledger setup gap BEFORE the supported API.
    with out.open("xb") as stream:
        stream.write(canonical_bytes(history))
    require(sha256(out) == provenance.removeprefix("synthetic:"), "exact_history_byte_provenance")
    with store.connect() as db:
        require(read_empty_generation(db) == generation, "generation_changed_before_api")
    require(int(time.time()) == close_epoch, "setup_close_expired_before_api")
    store.attest_sandbox_coverage(start, provenance)
    with sqlite3.connect(state_db.as_uri() + "?mode=ro", uri=True) as db:
        saved = db.execute("SELECT generation,coverage_start,provenance_digest,attested_at FROM sandbox_coverage WHERE id=1").fetchone()
        require(saved is not None and saved[:3] == (generation, start, hashlib.sha256(provenance.encode()).hexdigest())
                and type(saved[3]) is int and saved[3] == close_epoch, "attestation_outside_closed_setup_gap")
        require(db.execute("SELECT generation FROM sandbox_ledger_identity WHERE id=1").fetchone()[0] == generation
                and all(db.execute("SELECT count(*) FROM " + table).fetchone()[0] == 0 for table in ACTION_TABLES),
                "manufactured_predecessor_forbidden")
    # Real stock stamp. Crossing a second fails and requires a NEW setup.
    receipt = {"schema": "banking-supported-coverage-readback/v1", "history_sha256": sha256(out),
               "history_binding_digest": canonical_digest(history), "provenance": provenance,
               "generation": generation, "configured_start_required": start,
               "attested_at_real": saved[3], "readback_at_real": time.time(),
               "action_counts_after_api": {table: 0 for table in ACTION_TABLES},
               "claims_observed_operational_history": False}
    with (setup / "coverage-readback.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(receipt, indent=2) + "\n")
    return start
