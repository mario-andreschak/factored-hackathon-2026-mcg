"""Read-only joins and transport-event counts for the held instrumented fixture."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from contract import require, strict_json
from dataset import scoped_path

TOOL_NAMES = frozenset({"banking_status", "list_my_transactions", "get_my_transaction",
    "prepare_unrecognized_charge", "confirm_simulated_intake", "read_intake_receipt",
    "create_verified_handoff", "read_verified_handoff"})


def token_from_cookie(header: str) -> str:
    require(isinstance(header, str) and len(header) <= 4096, "fixture_cookie_header")
    parts = [part.strip().split("=", 1) for part in header.split(";") if part.strip()]
    tokens = [part[1] for part in parts if len(part) == 2 and part[0] == "flujo_bank_session"]
    require(len(tokens) == 1 and 1 <= len(tokens[0]) <= 128, "fixture_session_cookie_required")
    return tokens[0]


def canonical(value) -> str:
    # All retained facts use the exact reviewed helper's RFC8785 digest; imported
    # only by the released adapter, not by pure contract tests.
    from frontend_helpers.frontend_fault import canonical_digest
    return canonical_digest(value)


@contextmanager
def read_db(path: Path):
    scoped_path(path)
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("BEGIN")
        yield db
    finally:
        db.close()


def one(db, sql: str, args=()) -> dict:
    rows = db.execute(sql, args).fetchall()
    require(len(rows) == 1, "fixture_row_missing_or_ambiguous")
    return dict(rows[0])


def utc(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def transport_counts(raw: bytes, *, generations: set[str]) -> dict:
    require(len(raw) <= 4 * 1024 * 1024 and raw.endswith(b"\n"), "observer_log_incomplete")
    calls = {name: 0 for name in TOOL_NAMES}
    started, finished, ready, attached, sequence = {}, set(), set(), set(), {}
    external, forbidden = 0, 0
    for line in raw.splitlines():
        row = strict_json(line)
        require(set(row) <= {"generation", "pid", "sequence", "event", "name", "send", "child"}
                and row["generation"] in generations and type(row["pid"]) is int
                and type(row["sequence"]) is int, "observer_event_fields")
        process = row["generation"], row["pid"]
        require(row["sequence"] == sequence.get(process, 0) + 1, "observer_event_sequence")
        sequence[process] = row["sequence"]
        event = row["event"]
        if event == "observer_ready":
            require(process not in ready, "observer_duplicate_ready")
            ready.add(process)
        elif event == "bank_transport_attached":
            require(process in ready, "observer_not_ready")
            attached.add(process)
        elif event in {"send_started", "send_completed"}:
            require(process in attached and row.get("name") in TOOL_NAMES
                    and type(row.get("send")) is int and type(row.get("child")) is int,
                    "observer_transport_not_attached")
            key = (*process, row["child"], row["send"])
            if event == "send_started":
                require(key not in started, "observer_duplicate_send")
                started[key] = row["name"]
            else:
                require(key in started and started[key] == row["name"] and key not in finished,
                        "observer_unmatched_completion")
                finished.add(key)
                calls[row["name"]] += 1
        elif event == "external_attempt":
            external += 1
        elif event in {"forbidden_tool", "forbidden_network"}:
            forbidden += 1
        else:
            require(False, "observer_failed_or_interrupted")
    require({process[0] for process in ready} == generations
            and {process[0] for process in attached} == generations
            and set(started) == finished, "observer_generation_or_send_gap")
    return {"tool_calls": calls, "external_network_attempts": external,
            "forbidden_dispatch_attempts": forbidden}


class LedgerAdapter:
    def __init__(self, root: Path, metadata: dict):
        self.root, self.metadata = root, metadata
        self.bank = root / "bank-state/actions.sqlite"

    def generation(self, db):
        generation = one(db, "SELECT generation FROM sandbox_ledger_identity WHERE id=1")["generation"]
        require(generation == self.metadata["generation"], "ledger_generation_changed")
        return generation

    def owner(self, context) -> str:
        return canonical({"sub": context.scope.subject, "customer": context.scope.customer_id,
                          "session": context.scope.bank_session_id, "conversation": context.conversation})

    def pending_by_request(self, context, request_id: str) -> dict:
        key = hashlib.sha256(json.dumps([self.owner(context), request_id]).encode()).hexdigest()
        with read_db(self.bank) as db:
            self.generation(db)
            row = one(db, "SELECT * FROM action_pending WHERE request_key=?", (key,))
        require(row["binding"] == self.owner(context) and row["customer"] == context.scope.customer_id
                and row["transaction_id"] == context.scope.transaction_id and row["snapshot"] == context.scope.snapshot
                and canonical(strict_json(row["facts"])) == context.scope.facts_sha256, "pending_owner_or_facts")
        return row

    def receipt(self, case_id: str, contexts) -> dict:
        with read_db(self.bank) as db:
            self.generation(db)
            case = one(db, "SELECT * FROM sandbox_cases WHERE id=?", (case_id,))
            saved = one(db, "SELECT receipt_json FROM sandbox_case_receipts WHERE case_id=?", (case_id,))
        context = next((ctx for ctx in contexts if case["customer"] == ctx.scope.customer_id
                        and case["transaction_id"] == ctx.scope.transaction_id), None)
        require(context is not None and case["action"] == "simulated_intake"
                and case["snapshot"] == context.scope.snapshot
                and type(case["created_at"]) in {int, float} and 0 <= case["created_at"] <= time.time()
                and canonical(strict_json(case["facts"])) == context.scope.facts_sha256, "receipt_owner_or_facts")
        expected = {"id": case["id"], "kind": "simulated_intake", "simulated": True,
                    "snapshot": case["snapshot"], "created_at": utc(case["created_at"]),
                    "status": "received", "transaction": strict_json(case["facts"])}
        require(strict_json(saved["receipt_json"]) == expected, "saved_receipt_join")
        return expected

    def handoff(self, handoff_id: str, contexts) -> dict:
        with read_db(self.bank) as db:
            self.generation(db)
            row = one(db, "SELECT * FROM sandbox_handoffs WHERE id=?", (handoff_id,))
        context = next((ctx for ctx in contexts if row["binding"] == self.owner(ctx)
                        and row["customer"] == ctx.scope.customer_id), None)
        require(context is not None, "handoff_owner_join")
        facts, packet = strict_json(row["facts"]), strict_json(row["packet_json"])
        general = row["transaction_id"] is None
        if general:
            require(row["snapshot"] is None and facts == {} and packet.get("transaction") is None
                    and packet.get("transaction_provenance") is None, "general_handoff_facts")
        else:
            provenance = packet.get("transaction_provenance")
            require(row["transaction_id"] == context.scope.transaction_id and row["snapshot"] == context.scope.snapshot
                    and canonical(facts) == context.scope.facts_sha256 and packet.get("transaction") == facts
                    and isinstance(provenance, dict) and set(provenance) == {"source", "snapshot", "as_of"}
                    and provenance["source"] == "owned_serving_snapshot" and provenance["snapshot"] == row["snapshot"],
                    "handoff_facts")
            moment = datetime.fromisoformat(provenance["as_of"].replace("Z", "+00:00"))
            require(moment.tzinfo is not None and moment.utcoffset().total_seconds() == 0
                    and 0 <= moment.timestamp() <= row["created_at"] + 1, "handoff_provenance_time")
        require(set(packet) == {"schema", "transaction", "transaction_provenance", "reason", "unanswered_questions", "human_responded"}
                and packet["schema"] == "banking-sandbox-handoff/v1" and packet["reason"] == row["reason"]
                and isinstance(packet["unanswered_questions"], list) and packet["human_responded"] is False,
                "handoff_packet_join")
        questions = packet["unanswered_questions"]
        require(len(questions) <= 8 and all(isinstance(q, str) and 1 <= len(q) <= 240 and q.strip()
                and all(ord(c) >= 32 and not 0xD800 <= ord(c) <= 0xDFFF for c in q) for q in questions)
                and type(row["created_at"]) in {int, float} and 0 <= row["created_at"] <= time.time(),
                "handoff_questions_or_creation")
        current = (self.root / "dataset/CURRENT").read_text(encoding="utf-8").strip()
        scoped_path(self.root / "dataset/builds" / current)
        return {"id": row["id"], "reason": row["reason"], "snapshot": row["snapshot"],
                "created_at": utc(row["created_at"]), "facts": facts, "packet": packet,
                "human_responded": False, "transaction_currentness": "not_applicable" if general
                    else "same_snapshot" if current == row["snapshot"] else "different_snapshot"}
