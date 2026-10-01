"""Synthetic only: offline adoption and permission boundary, never live state."""
import json
import os
from pathlib import Path
import sqlite3
import stat
import time

import pytest

from frontend.server import deployment_transition as transition
from scripts.native_dispute_qualification import NativeDisputePort


def fixture(tmp_path):
    root = tmp_path / "code"
    for name in ("banking_mcp", "dispute_workflow", "frontend/server", "scripts"):
        (root / name).mkdir(parents=True)
    for name in ("banking_mcp/security.py", "dispute_workflow/host.py",
                 "frontend/server/deployment_transition.py", "scripts/run_dispute.py",
                 "scripts/reconcile_dispute_deployment.py", "scripts/native_dispute_qualification.py",
                 "requirements-dispute.txt"):
        (root / name).write_text("synthetic source", encoding="utf-8")
    state = tmp_path / "bank"
    state.mkdir()
    bank = state / "banking.db"
    with sqlite3.connect(bank) as db:
        db.executescript("""
        CREATE TABLE replays(jti TEXT PRIMARY KEY, expires INTEGER NOT NULL);
        CREATE TABLE revoked(session TEXT PRIMARY KEY);
        CREATE TABLE sessions(session TEXT PRIMARY KEY, subject TEXT NOT NULL, customer TEXT NOT NULL);
        CREATE TABLE capabilities(id TEXT PRIMARY KEY, kind TEXT NOT NULL, binding TEXT NOT NULL,
            expires INTEGER NOT NULL, payload TEXT NOT NULL);
        INSERT INTO replays VALUES ('old-jti',123);
        INSERT INTO revoked VALUES ('old-revoked');
        INSERT INTO sessions VALUES ('old-session','owner','customer');
        INSERT INTO capabilities VALUES ('old-cap','kind','binding',123,'{}');
        """)
    start = int(time.time()) - 90000
    config = tmp_path / "bank-config.json"
    config.write_text(json.dumps({"mode": "delegated", "state_db": str(bank),
        "ledger_continuity_approved": True, "sandbox_report_coverage_start": start}))
    old_front, old_worker = tmp_path / "frontend", tmp_path / "worker"
    old_front.mkdir()
    old_worker.mkdir()
    archives = {}
    for label, directory in (("frontend", old_front), ("worker", old_worker)):
        archive = tmp_path / (label + "-sealed.tar")
        archive.write_bytes(("synthetic " + label + " archive").encode())
        archives[label] = {"original_dir": str(directory), "path": str(archive),
                           "sha256": transition._file_hash(archive)}
    coverage_file = tmp_path / "coverage-proof.json"
    coverage_file.write_text('{"synthetic":true,"start":%d}' % start)
    proof = tmp_path / "operator.json"
    evidence = {"schema": transition.EVIDENCE_SCHEMA, "bank_path": str(bank),
        "source_sha256": transition._source(root)["sha256"],
        "legacy_ledger": transition._ledger(bank, legacy=True),
        "lease": {"id": "synthetic-exclusive-lease", "exclusive": True, "active": True},
        "authority": {"old_process_retired": True, "old_worker_drained": True,
                      "old_bank_stdio_retired": True, "late_replies_preserved": True},
        "obligations": [{"id": "old-session", "state": "confirmed",
                         "original_receipt_sha256": "a" * 64}],
        "archives": archives,
        "coverage": {"status": "proved", "start": start,
            "provenance": "synthetic:verified-source-history",
            "proof_path": str(coverage_file),
            "proof_sha256": transition._file_hash(coverage_file)}}
    proof.write_text(json.dumps(evidence))
    kwargs = {"bank_config_file": config, "legacy_frontend_state_dir": old_front,
        "legacy_worker_state_dir": old_worker, "native_state_dir": state,
        "new_frontend_state_dir": tmp_path / "new-frontend",
        "native_authority_dir": tmp_path / "control",
        "operator_evidence": proof, "source_root": root}
    return kwargs, bank, proof, root


def test_plan_is_read_only_then_adopts_once_and_allows_new_native_rows(tmp_path):
    kwargs, bank, proof, root = fixture(tmp_path)
    before = bank.read_bytes()
    plan_file, receipt = tmp_path / "plan.json", tmp_path / "receipt.json"
    planned = transition.plan(output=plan_file, **kwargs)
    assert bank.read_bytes() == before
    assert planned["legacy_ledger"]["generation"] is None
    applied = transition.apply(plan_file=plan_file, bank_config_file=kwargs["bank_config_file"],
                               operator_evidence=proof, receipt=receipt)
    assert len(applied["generation"]) == 64
    with sqlite3.connect(bank) as db:
        db.execute("INSERT INTO replays VALUES ('new-jti',456)")
        db.execute("INSERT INTO sandbox_cases VALUES ('case','customer','tx','dispute','snap',1.0,'{}')")
    assert transition.verify(receipt=receipt, bank_config_file=kwargs["bank_config_file"],
        source_root=root, native_state_dir=kwargs["native_state_dir"])["generation"] == applied["generation"]
    with pytest.raises(ValueError):
        transition.apply(plan_file=plan_file, bank_config_file=kwargs["bank_config_file"],
                         operator_evidence=proof, receipt=receipt)
    assert transition._ledger(Path(applied["archive_path"]), legacy=True) == planned["legacy_ledger"]


def test_missing_old_settlement_or_coverage_blocks_plan(tmp_path):
    kwargs, bank, proof, root = fixture(tmp_path)
    data = json.loads(proof.read_text())
    data["obligations"][0]["state"] = "uncertain"
    proof.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="obligations"):
        transition.plan(output=tmp_path / "plan.json", **kwargs)
    data["obligations"][0]["state"] = "confirmed"
    data["coverage"]["status"] = "unknown"
    proof.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="coverage"):
        transition.plan(output=tmp_path / "plan.json", **kwargs)
    assert transition._ledger(bank, legacy=True)["generation"] is None


def test_changed_source_plan_and_receipt_fail_closed(tmp_path):
    kwargs, bank, proof, root = fixture(tmp_path)
    plan_file, receipt = tmp_path / "plan.json", tmp_path / "receipt.json"
    transition.plan(output=plan_file, **kwargs)
    (root / "dispute_workflow/host.py").write_text("changed")
    with pytest.raises(ValueError):
        transition.apply(plan_file=plan_file, bank_config_file=kwargs["bank_config_file"],
                         operator_evidence=proof, receipt=receipt)
    assert transition._ledger(bank, legacy=True)["generation"] is None
    (root / "dispute_workflow/host.py").write_text("synthetic source")
    transition.apply(plan_file=plan_file, bank_config_file=kwargs["bank_config_file"],
                     operator_evidence=proof, receipt=receipt)
    (root / "banking_mcp/security.py").write_text("changed")
    with pytest.raises(ValueError, match="source"):
        transition.verify(receipt=receipt, bank_config_file=kwargs["bank_config_file"],
                          source_root=root, native_state_dir=kwargs["native_state_dir"])


@pytest.mark.skipif(os.name != "posix", reason="POSIX group permission contract")
def test_native_reader_group_atomic_replacement_and_revocation(tmp_path):
    gid = os.getegid()
    authority = tmp_path / "control"
    authority.mkdir()
    os.chmod(authority, 0o2750)
    os.chown(authority, -1, gid)
    admissions = authority / "admissions.json"
    admissions.write_text("[]")
    os.chown(admissions, -1, gid)
    os.chmod(admissions, 0o640)
    port = NativeDisputePort(lambda _: None, "http://127.0.0.1:4200", authority,
                             reader_group=gid)
    with port._edit_admissions() as records:
        records.append({"stageToken": "synthetic"})
    assert stat.S_IMODE(admissions.stat().st_mode) == 0o640
    assert admissions.stat().st_gid == gid
    lock = authority / ".admissions-host.lock"
    assert stat.S_IMODE(lock.stat().st_mode) == 0o600
    port._revoke_stage("synthetic")
    revocations = authority / "revocations"
    marker = next(revocations.iterdir())
    assert stat.S_IMODE(revocations.stat().st_mode) == 0o2750
    assert stat.S_IMODE(marker.stat().st_mode) == 0o640
    assert marker.stat().st_gid == gid
    port._revoke_stage("synthetic")
    os.chmod(marker, 0o600)
    with pytest.raises(ValueError):
        port._revoke_stage("synthetic")
    with pytest.raises(ValueError):
        NativeDisputePort(lambda _: None, "http://127.0.0.1:4200", authority,
                          reader_group=2**31 - 1)


def test_runner_rejects_changed_generation_before_service_or_state_creation(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from scripts import run_dispute

    kwargs, bank, proof, root = fixture(tmp_path)
    plan_file, receipt = tmp_path / "plan.json", tmp_path / "receipt.json"
    transition.plan(output=plan_file, **kwargs)
    transition.apply(plan_file=plan_file, bank_config_file=kwargs["bank_config_file"],
                     operator_evidence=proof, receipt=receipt)
    with sqlite3.connect(bank) as db:
        db.execute("UPDATE sandbox_ledger_identity SET generation=?", ("b" * 64,))
    data = tmp_path / "data"
    settings = SimpleNamespace(state_dir=kwargs["new_frontend_state_dir"],
                               data_dir=data, chat={"principal_customers": {"owner": "customer"}})
    config = SimpleNamespace(state_db=bank, data_dir=data, mode="delegated",
                             principal_customers={"owner": "customer"})
    called = []
    monkeypatch.setattr(run_dispute, "Service", lambda _: called.append(True))
    with pytest.raises(ValueError, match="generation"):
        run_dispute.application(settings, config, kwargs["native_state_dir"],
            "http://127.0.0.1:4200", kwargs["native_authority_dir"],
            transition_receipt=receipt, application_source_root=root,
            bank_config_file=kwargs["bank_config_file"])
    assert not called
    assert not kwargs["new_frontend_state_dir"].exists()


def test_default_native_port_keeps_private_files(tmp_path):
    authority = tmp_path / "private-control"
    authority.mkdir(mode=0o700)
    port = NativeDisputePort(lambda _: None, "http://127.0.0.1:4200", authority)
    with port._edit_admissions() as records:
        records.append({"stageToken": "synthetic"})
    port._revoke_stage("synthetic")
    assert stat.S_IMODE((authority / "admissions.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((authority / "revocations").stat().st_mode) == 0o700
    assert stat.S_IMODE(next((authority / "revocations").iterdir()).stat().st_mode) == 0o600


def test_original_revocation_loss_blocks_restart(tmp_path):
    kwargs, bank, proof, root = fixture(tmp_path)
    plan_file, receipt = tmp_path / "plan.json", tmp_path / "receipt.json"
    transition.plan(output=plan_file, **kwargs)
    transition.apply(plan_file=plan_file, bank_config_file=kwargs["bank_config_file"],
                     operator_evidence=proof, receipt=receipt)
    with sqlite3.connect(bank) as db:
        db.execute("DELETE FROM revoked WHERE session='old-revoked'")
    with pytest.raises(ValueError, match="revocation lost"):
        transition.verify(receipt=receipt, bank_config_file=kwargs["bank_config_file"],
                          source_root=root, native_state_dir=kwargs["native_state_dir"])


def test_missing_adopted_receipt_cannot_pass_as_fresh_even_without_archive(tmp_path):
    kwargs, bank, proof, root = fixture(tmp_path)
    plan_file, receipt = tmp_path / "plan.json", tmp_path / "receipt.json"
    transition.plan(output=plan_file, **kwargs)
    transition.apply(plan_file=plan_file, bank_config_file=kwargs["bank_config_file"],
                     operator_evidence=proof, receipt=receipt)
    synthetic = tmp_path / "data"
    synthetic.mkdir()
    (synthetic / "QUALIFICATION_SYNTHETIC.json").write_text(
        '{"synthetic":true,"origin":"test-fixture"}')
    with pytest.raises(ValueError, match="transition receipt"):
        transition.preflight_unreceipted(bank, kwargs["native_state_dir"],
                                         source_root=None, data_dir=synthetic)
    Path(tmp_path / "bank/legacy-bank-before-native.sqlite3").unlink()
    with pytest.raises(ValueError, match="transition receipt"):
        transition.preflight_unreceipted(bank, kwargs["native_state_dir"],
                                         source_root=None, data_dir=synthetic)


def test_fresh_authored_origin_restart_and_group_path(tmp_path):
    from types import SimpleNamespace
    from scripts import run_dispute
    bank_dir = tmp_path / "fresh"
    bank_dir.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    (data / "QUALIFICATION_SYNTHETIC.json").write_text(
        '{"synthetic":true,"origin":"reviewed-test-fixture"}')
    bank = bank_dir / "banking.db"
    preflight = transition.preflight_unreceipted(bank, bank_dir,
                                                  source_root=None, data_dir=data)
    assert preflight["new"] is True
    with sqlite3.connect(bank) as db:
        db.execute("CREATE TABLE sandbox_ledger_identity(id INTEGER PRIMARY KEY, generation TEXT)")
        db.execute("INSERT INTO sandbox_ledger_identity VALUES (1,?)", ("c" * 64,))
    (bank_dir / "dispute-bank-generation.json").write_text(json.dumps({
        "schema": "dispute-bank-generation/v1", "ledger_file": bank.name,
        "ledger_generation": "c" * 64}))
    transition.publish_fresh_origin(bank_dir, bank.name, "c" * 64, preflight)
    assert transition.preflight_unreceipted(bank, bank_dir,
        source_root=None, data_dir=data)["new"] is False
    config = SimpleNamespace(state_db=bank, data_dir=data, mode="delegated",
                             principal_customers={"owner": "customer"})
    settings = SimpleNamespace(state_dir=tmp_path / "new-frontend", data_dir=data,
                               chat={"principal_customers": {"owner": "customer"}})
    control = tmp_path / "control"
    control.mkdir()
    os.chmod(control, 0o2750)
    os.chown(control, -1, os.getegid())
    admissions = control / "admissions.json"
    admissions.write_text("[]")
    os.chown(admissions, -1, os.getegid())
    os.chmod(admissions, 0o640)
    (control / "native-profile.json").write_text("{}")
    called = []
    def stop_before_service(_):
        called.append(True)
        raise RuntimeError("service construction reached")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(run_dispute, "Service", stop_before_service)
        with pytest.raises(RuntimeError, match="service construction reached"):
            run_dispute.application(settings, config, bank_dir, "http://127.0.0.1:4200",
                control, enable_simulated_intake=True, native_reader_group=os.getegid())
    assert called
