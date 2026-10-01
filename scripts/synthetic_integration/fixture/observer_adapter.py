"""Read-only joins and transport-event counts for the held instrumented fixture."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
import sqlite3
import time

from contract import require, strict_json
from dataset import scoped_path

TOOL_NAMES = frozenset({"banking_status", "list_my_transactions", "get_my_transaction",
    "prepare_unrecognized_charge", "confirm_simulated_intake", "read_intake_receipt",
    "create_verified_handoff", "read_verified_handoff"})
UUID4 = r"[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}"


def complete_bootstrap_log(raw: bytes) -> list[dict] | None:
    """Wait on partial stock appends; reject malformed complete records."""
    require(len(raw) <= 4 * 1024 * 1024, "bootstrap_private_record_limit")
    if not raw or not raw.endswith(b"\n"):
        return None
    return [strict_json(line) for line in raw.splitlines()]


def verify_bootstrap_records(state: dict, events: list[dict], *, graph: dict, conversation: str,
                             accepted_routing: dict, reply: dict, provider_rejections: int,
                             owner: dict, expected_owner: dict) -> dict:
    """Validate independent stock conversation/log records against issued routing.

    Callers must obtain these by read-only reads of the actual worker workspace,
    after the cookie-bound frontend chat response. Fixture call counts alone do
    not establish runFlow or Finish admission.
    """
    require(reply.get("mode") == "flujo" and reply.get("status") == "completed"
            and type(provider_rejections) is int and provider_rejections == 0, "bootstrap_frontend_completed_required")
    require(owner == expected_owner and set(owner) == {"issuer", "subject", "graph", "deployment", "workspace"},
            "bootstrap_stock_owner_required")
    require(isinstance(conversation, str) and re.fullmatch(UUID4, conversation) is not None
            and state.get("conversationId") == conversation and state.get("flowId") == graph["id"]
            and state.get("flowSnapshot") == graph and state.get("status") == "completed"
            and state.get("currentNodeId") == "finish" and state.get("source") == "api"
            and state.get("executionExtensionOwned") is True and not state.get("lastError")
            and not state.get("isCancelled") and not state.get("capped"), "bootstrap_terminal_state_required")
    run_id = state.get("logicalRunId")
    recovery = state.get("recovery", {})
    require(isinstance(run_id, str) and re.fullmatch(UUID4, run_id) is not None
            and recovery.get("runId") == run_id and recovery.get("classification") == "completed",
            "bootstrap_completed_run_required")
    require(len(accepted_routing) == 1, "bootstrap_one_accepted_routing_required")
    issued_id, issued = next(iter(accepted_routing.items()))
    require(issued.get("function") == "handoff_to_finish"
            and issued.get("arguments_sha256") == hashlib.sha256(b"{}").hexdigest()
            and isinstance(issued.get("wire_sha256"), str)
            and re.fullmatch(r"[a-f0-9]{64}", issued["wire_sha256"]) is not None, "bootstrap_issued_routing_invalid")
    calls = [call for message in state.get("messages", []) if message.get("role") == "assistant"
             for call in message.get("tool_calls", []) if call.get("id") == issued_id]
    require(len(calls) == 1 and calls[0].get("type") == "function"
            and calls[0].get("function", {}).get("name") == "handoff_to_finish"
            and strict_json(calls[0]["function"].get("arguments", "")) == {}, "bootstrap_consumed_routing_required")
    results = [message for message in state.get("messages", []) if message.get("role") == "tool"
               and message.get("tool_call_id") == issued_id]
    require(len(results) == 1 and strict_json(results[0].get("content", "")) == {
                "status": "Handoff processed", "targetNodeId": "finish"}, "bootstrap_routing_result_required")
    require(events and all(event.get("conversationId") == conversation and type(event.get("seq")) is int
            and event["seq"] >= 0 for event in events)
            and all(after["seq"] > before["seq"] for before, after in zip(events, events[1:])),
            "bootstrap_event_identity_or_order")
    starts = [i for i, event in enumerate(events) if event.get("type") == "run:start"]
    require(len(starts) == 1 and events[starts[0]].get("flowId") == graph["id"], "bootstrap_normal_run_start_required")
    run_events = events[starts[0]:]
    require(not any(event.get("type") == "error" for event in run_events), "bootstrap_run_error")
    nodes = [(event["type"], event.get("node", {}).get("nodeId")) for event in run_events
             if event.get("type") in {"node:enter", "node:exit"}]
    require(nodes == [(kind, node) for node in ("start", "process", "finish") for kind in ("node:enter", "node:exit")],
            "bootstrap_start_process_finish_required")
    exits = [event for event in run_events if event.get("type") == "node:exit"
             and event.get("node", {}).get("nodeId") == "finish"]
    done = [event for event in run_events if event.get("type") == "run:done"]
    require(len(exits) == len(done) == 1 and exits[0].get("action") == "FINAL_RESPONSE"
            and done[0].get("status") == "completed" and done[0]["seq"] > exits[0]["seq"],
            "bootstrap_finish_completion_required")
    transitions = [event for event in run_events if event.get("type") == "recovery:transition"]
    terminal = [event for event in transitions if event.get("recovery", {}).get("classification") == "completed"]
    require([event.get("recovery", {}).get("classification") for event in transitions] == ["running", "completed"]
            and all(event.get("recovery", {}).get("runId") == run_id for event in transitions)
            and len(terminal) == 1 and exits[0]["seq"] < terminal[0]["seq"] < done[0]["seq"],
            "bootstrap_same_run_terminal_transition_required")
    handoffs = [event for event in run_events if event.get("type") == "handoff"
                and event.get("from", {}).get("nodeId") == "process"]
    process_exit = next(event for event in run_events if event.get("type") == "node:exit"
                        and event.get("node", {}).get("nodeId") == "process")
    finish_enter = next(event for event in run_events if event.get("type") == "node:enter"
                        and event.get("node", {}).get("nodeId") == "finish")
    require(len(handoffs) == 1 and handoffs[0].get("toNodeId") == "finish"
            and handoffs[0].get("edgeId") == "process-finish"
            and process_exit["seq"] < handoffs[0]["seq"] < finish_enter["seq"],
            "bootstrap_finish_handoff_required")
    return {"status": "completed", "finish_verified": True, "logical_run_sha256": hashlib.sha256(run_id.encode()).hexdigest(),
            "conversation_sha256": hashlib.sha256(conversation.encode()).hexdigest(),
            "routing_wire_sha256": issued["wire_sha256"], "finish_sequence": exits[0]["seq"], "done_sequence": done[0]["seq"]}


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
