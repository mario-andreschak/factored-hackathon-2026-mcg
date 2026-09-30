"""Persisted state migrations do not invent evidence for legacy records."""
import json
import sqlite3

import pytest

from banking_mcp.security import StateStore
from banking_mcp.service import HandoffArgs


def test_legacy_state_migration_preserves_unknown_receipts(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE sandbox_cases(id TEXT PRIMARY KEY, customer TEXT NOT NULL,
                transaction_id TEXT NOT NULL, action TEXT NOT NULL, snapshot TEXT NOT NULL,
                created_at REAL NOT NULL, facts TEXT NOT NULL);
            CREATE TABLE sandbox_handoffs(id TEXT PRIMARY KEY, binding TEXT NOT NULL,
                customer TEXT NOT NULL, transaction_id TEXT, snapshot TEXT,
                reason TEXT NOT NULL, created_at INTEGER NOT NULL, facts TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE);
            CREATE TABLE action_pending(id TEXT PRIMARY KEY, binding TEXT NOT NULL,
                customer TEXT NOT NULL, transaction_id TEXT NOT NULL, snapshot TEXT NOT NULL,
                action TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT,
                facts TEXT NOT NULL, expires INTEGER NOT NULL, evidence_digest TEXT,
                request_key TEXT, result_json TEXT);
        """)
        db.execute("INSERT INTO sandbox_cases VALUES (?,?,?,?,?,?,?)", (
            "CMP-SBX-legacy00", "customer-a", "charge-a", "simulated_intake", "build-a", 1, "{}"))
        db.execute("INSERT INTO sandbox_handoffs VALUES (?,?,?,?,?,?,?,?,?)", (
            "HOF-legacy00", "binding-a", "customer-a", "charge-a", "build-a", "customer_request", 1, "{}", "request-a"))
        db.execute("INSERT INTO action_pending(id,binding,customer,transaction_id,snapshot,action,decision,facts,expires) "
                   "VALUES (?,?,?,?,?,?,?,?,?)", ("pending-a", "binding-a", "customer-a", "charge-a", "build-a",
                   "simulated_intake", "intake", "{}", 1))
    store = StateStore(path)
    StateStore(path)  # Reopening must be an idempotent migration.
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_case_receipts").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 1
        assert db.execute("SELECT packet_json FROM sandbox_handoffs").fetchone()[0] is None
        assert db.execute("SELECT confirmation_state FROM action_pending").fetchone()[0] is None
        assert len(db.execute("PRAGMA table_info(sandbox_cases)").fetchall()) == 7


@pytest.mark.parametrize("questions", [None, "question", [1], [""], ["   "], ["x" * 241], ["x"] * 9])
def test_handoff_questions_reject_invalid_shapes_and_bounds(questions):
    with pytest.raises(ValueError):
        HandoffArgs.model_validate({"reason": "customer_request", "unanswered_questions": questions})


def test_handoff_questions_preserve_es_pt_and_default_empty():
    assert HandoffArgs.model_validate({"reason": "customer_request"}).unanswered_questions == []
    questions = [" ¿Cuándo recibiré una respuesta? ", " Quem poderá explicar esta cobrança? "]
    parsed = HandoffArgs.model_validate({"reason": "customer_request", "unanswered_questions": questions})
    assert parsed.unanswered_questions == [question.strip() for question in questions]
    assert json.loads(parsed.model_dump_json())["unanswered_questions"] == parsed.unanswered_questions
