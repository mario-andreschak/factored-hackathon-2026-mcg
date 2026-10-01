"""Persistence checks use actual generated data and SQLite, without a provider."""
import json
import hashlib
import sqlite3

import pytest

from scripts.local_dispute_demo import DemoRejected, load_demo, main, prepare


@pytest.fixture(scope="module")
def original(tmp_path_factory):
    root = tmp_path_factory.mktemp("persistent-local-demo")
    return prepare(root)


def test_repeat_prepare_preserves_admission_generation_coverage_and_database(original):
    first = original
    files = (first.root / "input-settings" / "frontend.json", first.bank_config_file,
             first.root / "local-access.json", first.root / "authored-history.json")
    before = [path.read_bytes() for path in files]
    with sqlite3.connect(first.bank_config.state_db) as db:
        db.execute("INSERT INTO sessions VALUES (?,?,?)",
                   ("persistence-check", "fixture-only", "fixture-only"))
        # This is a storage sentinel, not a claim of real intake qualification.
        db.execute("INSERT INTO sandbox_case_receipts VALUES (?,?)",
                   ("CMP-SBX-persistence-check", '{"storage_sentinel":true}'))
        coverage = db.execute("SELECT * FROM sandbox_coverage").fetchall()
        generation = db.execute("SELECT * FROM sandbox_ledger_identity").fetchall()
    try:
        second = prepare(first.root)
        assert second.settings.demo_code == first.settings.demo_code
        assert [path.read_bytes() for path in files] == before
        with sqlite3.connect(second.bank_config.state_db) as db:
            assert db.execute("SELECT * FROM sandbox_coverage").fetchall() == coverage
            assert db.execute("SELECT * FROM sandbox_ledger_identity").fetchall() == generation
            assert db.execute("SELECT subject FROM sessions WHERE session='persistence-check'").fetchone() == ("fixture-only",)
            assert db.execute("SELECT receipt_json FROM sandbox_case_receipts WHERE case_id='CMP-SBX-persistence-check'").fetchone() == ('{"storage_sentinel":true}',)
    finally:
        with sqlite3.connect(first.bank_config.state_db) as db:
            db.execute("DELETE FROM sessions WHERE session='persistence-check'")
            db.execute("DELETE FROM sandbox_case_receipts WHERE case_id='CMP-SBX-persistence-check'")


def test_changed_coverage_is_refused_without_reattesting(original):
    with sqlite3.connect(original.bank_config.state_db) as db:
        previous = db.execute("SELECT provenance_digest FROM sandbox_coverage WHERE id=1").fetchone()[0]
        db.execute("UPDATE sandbox_coverage SET provenance_digest=? WHERE id=1", ("0" * 64,))
    try:
        with pytest.raises(DemoRejected, match="retained_coverage_changed"):
            prepare(original.root)
        with sqlite3.connect(original.bank_config.state_db) as db:
            assert db.execute("SELECT provenance_digest FROM sandbox_coverage WHERE id=1").fetchone()[0] == "0" * 64
    finally:
        with sqlite3.connect(original.bank_config.state_db) as db:
            db.execute("UPDATE sandbox_coverage SET provenance_digest=? WHERE id=1", (previous,))


@pytest.mark.parametrize("relative", ["fixture/event-rates.csv", "fixture/private-admission.json",
                                     "input-settings/frontend.json"])
def test_changed_private_inputs_refuse_without_reset(original, relative):
    path = original.root / relative
    before = path.read_bytes()
    try:
        path.write_bytes(before + b"changed")
        with pytest.raises(DemoRejected, match="retained_input_changed"):
            prepare(original.root)
        assert path.read_bytes() == before + b"changed"
        assert original.bank_config.state_db.exists()
    finally:
        path.write_bytes(before)


def test_missing_database_is_not_recreated_or_reattested(original):
    path = original.bank_config.state_db
    saved = path.with_suffix(".retained")
    path.rename(saved)
    try:
        with pytest.raises(DemoRejected, match="retained_ledger_missing"):
            prepare(original.root)
        assert not path.exists()
    finally:
        saved.rename(path)
    assert load_demo(original.root).manifest["coverage"] == original.manifest["coverage"]


def test_rewriting_manifest_hash_cannot_adopt_changed_secrets(original):
    config = original.root / "input-settings" / "frontend.json"
    manifest = original.root / "local-demo.json"
    saved_config, saved_manifest = config.read_bytes(), manifest.read_bytes()
    try:
        changed = json.loads(saved_config)
        changed["demo_code"] = "replacement-access-code"
        config.write_text(json.dumps(changed), encoding="utf-8")
        rewritten = json.loads(saved_manifest)
        rewritten["input_sha256"]["input-settings/frontend.json"] = hashlib.sha256(config.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(rewritten), encoding="utf-8")
        with pytest.raises(DemoRejected, match="retained_history_binding_changed"):
            prepare(original.root)
    finally:
        config.write_bytes(saved_config)
        manifest.write_bytes(saved_manifest)


def test_foreign_occupied_directory_is_preserved(tmp_path):
    sentinel = tmp_path / "do-not-adopt.txt"
    sentinel.write_text("another instance", encoding="utf-8")
    with pytest.raises(DemoRejected, match="occupied_demo_directory"):
        prepare(tmp_path)
    assert list(tmp_path.iterdir()) == [sentinel]
    assert sentinel.read_text(encoding="utf-8") == "another instance"


def test_public_status_contains_no_private_access_values(original, capsys):
    assert main(["status", "--root", str(original.root)]) == 0
    output = capsys.readouterr()
    status = json.loads(output.out)
    assert status["synthetic"] is True
    assert "requires actual chat" in status["native_execution_verification"]
    assert original.settings.demo_code not in output.out + output.err
    assert original.bank_config.service_token not in output.out + output.err
    assert original.settings.chat["execution_token"] not in output.out + output.err
    assert "customer_id" not in output.out
