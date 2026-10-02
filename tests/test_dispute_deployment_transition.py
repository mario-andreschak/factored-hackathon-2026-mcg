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
    for name in (*transition.SOURCE_DIRS, "scripts"):
        (root / name).mkdir(parents=True)
    for name in ("banking_mcp/security.py", "dispute_workflow/host.py",
                 "frontend/server/deployment_transition.py", "scripts/run_dispute.py",
                 "scripts/reconcile_dispute_deployment.py", "scripts/native_dispute_qualification.py",
                 "requirements-dispute.txt", "resources/dispute_workflow.flow.json",
                 "graph_config_v3.yaml", "frontend/package.json", "frontend/package-lock.json",
                 "frontend/index.html"):
        (root / name).write_text("synthetic source", encoding="utf-8")
    state = tmp_path / "bank"
    state.mkdir(mode=0o700)
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
    authority_receipt = tmp_path / "old-authority-receipt.json"
    authority_receipt.write_text('{"synthetic":"old-authority-drained"}')
    lease_receipt = tmp_path / "exclusive-lease.json"
    lease_receipt.write_text('{"synthetic":"exclusive-lease"}')
    old_obligation_receipt = tmp_path / "old-obligation-receipt.json"
    old_obligation_receipt.write_text('{"synthetic":"old-revocation-confirmed"}')
    evidence = {"schema": transition.EVIDENCE_SCHEMA, "bank_path": str(bank),
        "source_sha256": transition._source(root)["sha256"],
        "legacy_ledger": transition._ledger(bank, legacy=True),
        "lease": {"id": "synthetic-exclusive-lease", "exclusive": True, "active": True,
                  "proof_path": str(lease_receipt),
                  "proof_sha256": transition._file_hash(lease_receipt)},
        "authority": {"old_process_retired": True, "old_worker_drained": True,
                      "old_bank_stdio_retired": True, "late_replies_preserved": True,
                      "proof_path": str(authority_receipt),
                      "proof_sha256": transition._file_hash(authority_receipt)},
        "obligations": [{"id": "old-session", "state": "confirmed",
                         "original_receipt_path": str(old_obligation_receipt),
                         "original_receipt_sha256": transition._file_hash(old_obligation_receipt)}],
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
    markers = list(revocations.iterdir())
    assert len(markers) == 1 and markers[0].suffix == ".revoked"
    marker = markers[0]
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


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode contract")
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


@pytest.mark.skipif(os.name != "posix", reason="POSIX group ownership contract")
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


def test_runner_cli_exposes_separate_bank_and_application_source_roots(tmp_path):
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / "scripts/run_dispute.py"), "--help"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0
    for flag in ("--source-root", "--application-source-root", "--transition-receipt",
                 "--native-reader-group", "--enable-simulated-intake"):
        assert flag in result.stdout
    assert "private bank object root" in result.stdout
    assert "application code root" in result.stdout
    assert not list(tmp_path.iterdir())


def test_original_session_binding_change_blocks_restart(tmp_path):
    kwargs, bank, proof, root = fixture(tmp_path)
    plan_file, receipt = tmp_path / "plan.json", tmp_path / "receipt.json"
    transition.plan(output=plan_file, **kwargs)
    transition.apply(plan_file=plan_file, bank_config_file=kwargs["bank_config_file"],
                     operator_evidence=proof, receipt=receipt)
    with sqlite3.connect(bank) as db:
        db.execute("UPDATE sessions SET customer='different' WHERE session='old-session'")
    with pytest.raises(ValueError, match="admission content"):
        transition.verify(receipt=receipt, bank_config_file=kwargs["bank_config_file"],
                          source_root=root, native_state_dir=kwargs["native_state_dir"])


@pytest.mark.parametrize("guarded", ["action_pending", "sandbox_cases",
    "sandbox_case_receipts", "sandbox_handoffs"])
def test_unreceipted_populated_new_table_is_read_only_pre_service(tmp_path, monkeypatch, guarded):
    from types import SimpleNamespace
    from scripts import run_dispute
    state, data = tmp_path / "bank", tmp_path / "data"
    state.mkdir()
    data.mkdir()
    (data / "QUALIFICATION_SYNTHETIC.json").write_text(
        '{"synthetic":true,"origin":"reviewed-test-fixture"}')
    bank = state / "banking.db"
    with sqlite3.connect(bank) as db:
        db.execute("CREATE TABLE sandbox_ledger_identity(id INTEGER PRIMARY KEY, generation TEXT)")
        db.execute("INSERT INTO sandbox_ledger_identity VALUES (1,?)", ("d" * 64,))
        db.execute("CREATE TABLE " + guarded + "(id TEXT PRIMARY KEY)")
        db.execute("INSERT INTO " + guarded + " VALUES ('old')")
    original = bank.read_bytes()
    authority = tmp_path / "control"
    authority.mkdir()
    (authority / "admissions.json").write_text("[]")
    (authority / "native-profile.json").write_text("{}")
    settings = SimpleNamespace(state_dir=tmp_path / "new-frontend", data_dir=data,
                               chat={"principal_customers": {"owner": "customer"}})
    config = SimpleNamespace(state_db=bank, data_dir=data, mode="delegated",
                             principal_customers={"owner": "customer"})
    called = []
    monkeypatch.setattr(run_dispute, "Service", lambda _: called.append(True))
    with pytest.raises(ValueError, match="fresh origin"):
        run_dispute.application(settings, config, state, "http://127.0.0.1:4200",
                                authority, enable_simulated_intake=True)
    assert not called
    assert bank.read_bytes() == original
    assert not (state / "dispute-bank-generation.json").exists()


def test_lost_adoption_artifacts_and_rows_do_not_become_fresh(tmp_path):
    kwargs, bank, proof, root = fixture(tmp_path)
    plan_file, receipt = tmp_path / "plan.json", tmp_path / "receipt.json"
    transition.plan(output=plan_file, **kwargs)
    transition.apply(plan_file=plan_file, bank_config_file=kwargs["bank_config_file"],
                     operator_evidence=proof, receipt=receipt)
    Path(tmp_path / "bank/legacy-bank-before-native.sqlite3").unlink()
    Path(tmp_path / "bank/dispute-bank-generation.json").unlink()
    receipt.unlink()
    with sqlite3.connect(bank) as db:
        for name in ("replays", "revoked", "sessions", "capabilities"):
            db.execute("DELETE FROM " + name)
    data = tmp_path / "data"
    data.mkdir()
    (data / "QUALIFICATION_SYNTHETIC.json").write_text(
        '{"synthetic":true,"origin":"reviewed-test-fixture"}')
    with pytest.raises(ValueError, match="fresh origin"):
        transition.preflight_unreceipted(bank, kwargs["native_state_dir"],
                                         source_root=None, data_dir=data)


def test_old_replay_content_change_to_future_blocks_restart(tmp_path):
    kwargs, bank, proof, root = fixture(tmp_path)
    plan_file, receipt = tmp_path / "plan.json", tmp_path / "receipt.json"
    transition.plan(output=plan_file, **kwargs)
    transition.apply(plan_file=plan_file, bank_config_file=kwargs["bank_config_file"],
                     operator_evidence=proof, receipt=receipt)
    with sqlite3.connect(bank) as db:
        db.execute("UPDATE replays SET expires=? WHERE jti='old-jti'", (int(time.time()) + 3600,))
    with pytest.raises(ValueError, match="replay"):
        transition.verify(receipt=receipt, bank_config_file=kwargs["bank_config_file"],
                          source_root=root, native_state_dir=kwargs["native_state_dir"])


def test_live_old_replay_deletion_blocks_restart(tmp_path):
    kwargs, bank, proof, root = fixture(tmp_path)
    with sqlite3.connect(bank) as db:
        db.execute("UPDATE replays SET expires=? WHERE jti='old-jti'", (int(time.time()) + 3600,))
    evidence = json.loads(proof.read_text())
    evidence["legacy_ledger"] = transition._ledger(bank, legacy=True)
    proof.write_text(json.dumps(evidence))
    plan_file, receipt = tmp_path / "plan.json", tmp_path / "receipt.json"
    transition.plan(output=plan_file, **kwargs)
    transition.apply(plan_file=plan_file, bank_config_file=kwargs["bank_config_file"],
                     operator_evidence=proof, receipt=receipt)
    with sqlite3.connect(bank) as db:
        db.execute("DELETE FROM replays WHERE jti='old-jti'")
    with pytest.raises(ValueError, match="live old replay"):
        transition.verify(receipt=receipt, bank_config_file=kwargs["bank_config_file"],
                          source_root=root, native_state_dir=kwargs["native_state_dir"])


def test_real_action_host_schema_and_authorized_new_write_survive_verify(tmp_path):
    from types import SimpleNamespace
    from banking_mcp.security import Principal, StateStore
    from dispute_workflow.action_host import BankingActionHost

    kwargs, bank, proof, root = fixture(tmp_path)
    plan_file, receipt = tmp_path / "plan.json", tmp_path / "receipt.json"
    transition.plan(output=plan_file, **kwargs)
    adopted = transition.apply(plan_file=plan_file,
        bank_config_file=kwargs["bank_config_file"], operator_evidence=proof, receipt=receipt)
    config = SimpleNamespace(mode="delegated", ledger_continuity_approved=True, state_db=bank)
    store = StateStore(bank, ledger_continuity_approved=True)
    service = SimpleNamespace(config=config, store=store)
    workflow_store = SimpleNamespace(path=tmp_path / "new-workflow.sqlite3")
    host = BankingActionHost(service, workflow_store)
    assert host.ledger_generation == adopted["generation"]
    principal = Principal("new-subject", "new-customer", "new-session", "new-conversation",
                          int(time.time()) + 600, adopted["generation"])
    store.admit(principal, "new-jti")
    assert transition.verify(receipt=receipt, bank_config_file=kwargs["bank_config_file"],
        source_root=root, native_state_dir=kwargs["native_state_dir"])["generation"] == adopted["generation"]
    with sqlite3.connect(bank) as db:
        db.execute("INSERT INTO dispute_host_cancelled VALUES (?,?,?,?)",
                   ("new-binding", "new-pending", "new-query", int(time.time())))
    assert transition.verify(receipt=receipt, bank_config_file=kwargs["bank_config_file"],
        source_root=root, native_state_dir=kwargs["native_state_dir"])["generation"] == adopted["generation"]


def test_missing_or_changed_original_authority_receipt_fails_closed(tmp_path):
    kwargs, bank, proof, root = fixture(tmp_path)
    evidence = json.loads(proof.read_text())
    receipt_path = Path(evidence["obligations"][0]["original_receipt_path"])
    receipt_path.unlink()
    with pytest.raises(ValueError, match="proof"):
        transition.plan(output=tmp_path / "plan.json", **kwargs)
    receipt_path.write_text('{"synthetic":"old-revocation-confirmed"}')
    plan_file, receipt = tmp_path / "plan.json", tmp_path / "receipt.json"
    transition.plan(output=plan_file, **kwargs)
    transition.apply(plan_file=plan_file, bank_config_file=kwargs["bank_config_file"],
                     operator_evidence=proof, receipt=receipt)
    receipt_path.write_text('{"synthetic":"changed"}')
    with pytest.raises(ValueError, match="obligation proof changed"):
        transition.verify(receipt=receipt, bank_config_file=kwargs["bank_config_file"],
                          source_root=root, native_state_dir=kwargs["native_state_dir"])


def test_archive_parent_sync_precedes_adoption_and_fault_preserves_original(tmp_path, monkeypatch):
    kwargs, bank, proof, _ = fixture(tmp_path)
    original = transition._ledger(bank, legacy=True)
    plan_file, receipt = tmp_path / "plan.json", tmp_path / "receipt.json"
    transition.plan(output=plan_file, **kwargs)
    real_sync = transition._fsync_parent_directory
    calls = []

    def fail_archive_sync(parent):
        calls.append(parent)
        if parent == bank.parent:
            raise OSError("synthetic archive directory sync failure")
        real_sync(parent)

    monkeypatch.setattr(transition, "_fsync_parent_directory", fail_archive_sync)
    with pytest.raises(OSError, match="archive directory sync failure"):
        transition.apply(plan_file=plan_file, bank_config_file=kwargs["bank_config_file"],
                         operator_evidence=proof, receipt=receipt)
    archive = bank.parent / "legacy-bank-before-native.sqlite3"
    assert calls == [bank.parent]
    assert archive.exists()
    assert transition._ledger(archive, legacy=True) == original
    assert transition._ledger(bank, legacy=True) == original
    assert not receipt.exists()
    assert not (bank.parent / "dispute-bank-generation.json").exists()
    with sqlite3.connect(bank) as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='sandbox_ledger_identity'").fetchone()


def test_directory_sync_platform_branch_and_no_overwrite_after_fault(tmp_path, monkeypatch):
    with monkeypatch.context() as patch:
        # Windows lacks O_DIRECTORY; supply only the flag needed to reach the mocked POSIX open.
        patch.setattr(transition.os, "O_DIRECTORY", 0, raising=False)
        patch.setattr(transition.os, "open", lambda *args, **kwargs: (_ for _ in ()).throw(
            PermissionError("synthetic Windows directory open")))
        transition._fsync_parent_directory(tmp_path, platform_name="nt")
        with pytest.raises(PermissionError, match="synthetic Windows"):
            transition._fsync_parent_directory(tmp_path, platform_name="posix")
    artifact = tmp_path / "no-overwrite.json"
    with monkeypatch.context() as patch:
        patch.setattr(transition, "_fsync_parent_directory",
                      lambda _: (_ for _ in ()).throw(PermissionError("synthetic sync fault")))
        with pytest.raises(PermissionError, match="synthetic sync fault"):
            transition._atomic_new(artifact, b'{"synthetic":true}\n')
    assert artifact.read_bytes() == b'{"synthetic":true}\n'
    assert not list(tmp_path.glob(".transition-*"))
    with pytest.raises(ValueError, match="already exists"):
        transition._atomic_new(artifact, b"replaced")
    assert artifact.read_bytes() == b'{"synthetic":true}\n'


def test_crossplatform_real_fresh_factory_write_and_restart(tmp_path):
    from types import SimpleNamespace
    from banking_mcp.security import Principal, StateStore
    from scripts.run_dispute import NativeHostFactory

    state, data = tmp_path / "fresh-bank", tmp_path / "synthetic-data"
    state.mkdir(mode=0o700)
    data.mkdir()
    (data / "QUALIFICATION_SYNTHETIC.json").write_text(
        '{"synthetic":true,"origin":"crossplatform-authored-fixture"}')
    bank = state / "banking.db"
    first = transition.preflight_unreceipted(bank, state, source_root=None, data_dir=data)
    assert first["new"] is True
    store = StateStore(bank, ledger_continuity_approved=True)
    service = SimpleNamespace(config=SimpleNamespace(
        mode="delegated", ledger_continuity_approved=True, state_db=bank), store=store)
    workflow_path = state / "dispute-workflow.sqlite3"
    authority = tmp_path / "control"
    factory = NativeHostFactory(workflow_path, service, "http://127.0.0.1:4200", authority)
    transition.publish_fresh_origin(state, bank.name, factory.ledger_generation, first)
    principal = Principal("new-owner", "new-customer", "new-session", "new-conversation",
                          int(time.time()) + 600, factory.ledger_generation)
    store.admit(principal, "new-jti")
    restart = transition.preflight_unreceipted(bank, state, source_root=None, data_dir=data)
    assert restart["new"] is False
    restarted = NativeHostFactory(workflow_path, service, "http://127.0.0.1:4200", authority)
    assert restarted.ledger_generation == factory.ledger_generation


@pytest.mark.parametrize("name", ["dispute-bank-generation.json", "frontend-chat.sqlite3",
                                  "dispute-workflow.sqlite3"])
def test_dangling_retained_binding_refused_before_service(tmp_path, monkeypatch, name):
    from types import SimpleNamespace
    from scripts import run_dispute

    state, data, control = tmp_path / "fresh", tmp_path / "data", tmp_path / "control"
    state.mkdir()
    data.mkdir()
    control.mkdir()
    (data / "QUALIFICATION_SYNTHETIC.json").write_text(
        '{"synthetic":true,"origin":"reviewed-test-fixture"}')
    (control / "admissions.json").write_text("[]")
    (control / "native-profile.json").write_text("{}")
    suspect = state / name
    try:
        suspect.symlink_to(state / "missing-target")
    except OSError:
        pytest.skip("host cannot create a synthetic symlink")
    bank = state / "banking.db"
    settings = SimpleNamespace(state_dir=tmp_path / "new-frontend", data_dir=data,
                               chat={"principal_customers": {"owner": "customer"}})
    config = SimpleNamespace(state_db=bank, data_dir=data, mode="delegated",
                             principal_customers={"owner": "customer"})
    called = []
    monkeypatch.setattr(run_dispute, "Service", lambda _: called.append(True))
    with pytest.raises(ValueError, match="symlink or nonregular"):
        run_dispute.application(settings, config, state, "http://127.0.0.1:4200",
                                control, enable_simulated_intake=True)
    assert not called
    assert not bank.exists() and not settings.state_dir.exists()
    assert suspect.is_symlink() and not suspect.exists()


def test_nonregular_retained_binding_refused_before_service(tmp_path):
    state, data = tmp_path / "fresh", tmp_path / "data"
    state.mkdir()
    data.mkdir()
    (data / "QUALIFICATION_SYNTHETIC.json").write_text(
        '{"synthetic":true,"origin":"reviewed-test-fixture"}')
    (state / "frontend-chat.sqlite3").mkdir()
    with pytest.raises(ValueError, match="nonregular"):
        transition.preflight_unreceipted(state / "banking.db", state,
                                         source_root=None, data_dir=data)
    assert not (state / "banking.db").exists()


class _TrackedReadOnlyConnection:
    """Keep the real SQLite handle reachable after a readonly helper returns."""

    def __init__(self, db):
        self.db = db
        self.entered = 0
        self.exited = 0
        self.closed = False
        self.query_only = db.execute("PRAGMA query_only").fetchone()[0]

    def __getattr__(self, name):
        return getattr(self.db, name)

    def __enter__(self):
        self.entered += 1
        return self.db.__enter__()

    def __exit__(self, *args):
        self.exited += 1
        return self.db.__exit__(*args)

    def close(self):
        self.db.close()
        self.closed = True


def _track_readonly_connections(monkeypatch):
    opened = []
    original = transition._connect_ro

    def connect(path):
        wrapped = _TrackedReadOnlyConnection(original(path))
        opened.append((Path(path), wrapped))
        return wrapped

    monkeypatch.setattr(transition, "_connect_ro", connect)
    return opened


def _assert_readonly_connections_released(opened):
    assert opened
    for _, handle in opened:
        assert handle.query_only == 1
        assert handle.entered == handle.exited == 1
        assert handle.closed
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            handle.db.execute("SELECT 1")


def test_verify_closes_archive_and_active_readers_on_success_and_failure(tmp_path, monkeypatch):
    kwargs, bank, proof, root = fixture(tmp_path)
    plan_file, receipt = tmp_path / "plan.json", tmp_path / "receipt.json"
    transition.plan(output=plan_file, **kwargs)
    transition.apply(plan_file=plan_file, bank_config_file=kwargs["bank_config_file"],
                     operator_evidence=proof, receipt=receipt)
    archive = tmp_path / "bank/legacy-bank-before-native.sqlite3"
    opened = _track_readonly_connections(monkeypatch)
    assert transition.verify(receipt=receipt, bank_config_file=kwargs["bank_config_file"],
        source_root=root, native_state_dir=kwargs["native_state_dir"])["generation"]
    assert [path for path, _ in opened].count(archive) == 2
    assert [path for path, _ in opened].count(bank) == 2
    _assert_readonly_connections_released(opened)

    opened.clear()
    with sqlite3.connect(bank) as db:
        db.execute("DELETE FROM revoked WHERE session='old-revoked'")
    with pytest.raises(ValueError, match="revocation lost"):
        transition.verify(receipt=receipt, bank_config_file=kwargs["bank_config_file"],
                          source_root=root, native_state_dir=kwargs["native_state_dir"])
    assert [path for path, _ in opened].count(archive) == 2
    assert [path for path, _ in opened].count(bank) == 1
    _assert_readonly_connections_released(opened)


def test_preflight_closes_existing_ledger_reader_on_success_and_failure(tmp_path, monkeypatch):
    state, data = tmp_path / "bank", tmp_path / "data"
    state.mkdir()
    data.mkdir()
    (data / "QUALIFICATION_SYNTHETIC.json").write_text(
        '{"synthetic":true,"origin":"tracked-readonly-test"}')
    bank = state / "banking.db"
    new = transition.preflight_unreceipted(bank, state, source_root=None, data_dir=data)
    with sqlite3.connect(bank) as db:
        db.execute("CREATE TABLE sandbox_ledger_identity(id INTEGER PRIMARY KEY, generation TEXT)")
        db.execute("INSERT INTO sandbox_ledger_identity VALUES (1,?)", ("a" * 64,))
    transition.publish_fresh_origin(state, bank.name, "a" * 64, new)
    (state / "dispute-bank-generation.json").write_text(json.dumps({
        "schema": "dispute-bank-generation/v1", "ledger_file": bank.name,
        "ledger_generation": "a" * 64}))
    opened = _track_readonly_connections(monkeypatch)
    assert transition.preflight_unreceipted(bank, state, source_root=None, data_dir=data)["new"] is False
    assert [path for path, _ in opened] == [bank]
    _assert_readonly_connections_released(opened)

    opened.clear()
    marker = state / "native-fresh-origin.json"
    saved = json.loads(marker.read_text())
    marker.write_text(json.dumps({**saved, "ledger_generation": "b" * 64}))
    with pytest.raises(ValueError, match="fresh origin provenance changed"):
        transition.preflight_unreceipted(bank, state, source_root=None, data_dir=data)
    assert [path for path, _ in opened] == [bank]
    _assert_readonly_connections_released(opened)
    # Local synthetic file is removable after both exits. Linux permits unlink of
    # open files too, so the tracked handle assertions carry the close proof.
    bank.unlink()
    assert not bank.exists()
