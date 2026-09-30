"""Private, offline, read-only review of unresolved demo prepare identities.

Run with ``python -B -m scripts.triage_recovery --help`` from the repository.
Requires operator-exported detached consolidated SQLite backups; sidecar/hash
checks do not establish provenance. No service is constructed, pending handle
reconstructed, network call made, or action state changed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
from typing import Iterator

import rfc8785

from frontend.server.review import review_reference


_REVIEW = re.compile(r"^rev_[a-f0-9]{24}$")
_UUID4 = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$")
_PUBLIC_TARGET = re.compile(r"^txn_[a-f0-9]{24}$")
_SNAPSHOT = re.compile(r"^[A-Za-z0-9_-]{1,96}$")
_UNRESOLVED = frozenset({"preparing", "prepare_unverified"})
_REASONS = frozenset({"high_risk", "missing_evidence", "out_of_policy", "emergency",
                      "action_unverified", "customer_request", "clarification_exhausted",
                      "duplicate_review", "no_match_exhausted", "tool_failure"})
_ACTION = "simulated_intake"
_PREPARE_FIELDS = frozenset({"snapshot", "action", "decision", "reason", "transaction", "risk"})
_PROJECTION_FIELDS = frozenset({"state", "receipt", "coverage", "source"})
_RECEIPT_FIELDS = frozenset({"id", "kind", "simulated", "snapshot", "created_at", "status", "transaction"})
_PACKET_FIELDS = frozenset({"schema", "transaction", "transaction_provenance", "reason",
                            "unanswered_questions", "human_responded"})
_TRANSACTION_LIMITS = {"transaction_reference": 16, "transaction_date": 40, "process_date": 10,
                       "amount": 40, "currency": 8, "status": 80, "transaction_type": 80,
                       "channel": 80, "product": 80}
_MAX_JSON = 256 * 1024
_FRONTEND_COLUMNS = {
    "action_status": {"session_id", "owner", "expires", "result_json", "updated_at", "action_id",
                      "target_reference", "prepare_transaction_id", "prepare_snapshot",
                      "prepare_conversation_id", "prepare_recovery_attempts", "prepare_recovery_deadline"},
    "chat_sessions": {"session_id", "owner", "expires", "conversation_id", "subject", "customer_id", "revoked"},
}
_MCP_COLUMNS = {
    "sessions": {"session", "subject", "customer"},
    "action_pending": {"binding", "customer", "transaction_id", "snapshot", "action", "decision",
                       "reason", "facts", "expires", "request_key", "result_json"},
    "sandbox_handoffs": {"id", "binding", "customer", "transaction_id", "snapshot", "reason",
                         "facts", "idempotency_key"},
    "sandbox_cases": {"customer", "transaction_id", "action", "snapshot", "created_at", "facts"},
}


class SnapshotError(Exception):
    """A fixed error code; do not echo paths, database content or SQLite errors."""


def principal_binding(subject: str, customer: str, session: str, conversation: str) -> str:
    """Exactly Principal.binding(); expiry is deliberately not part of the digest."""
    return hashlib.sha256(rfc8785.dumps({"sub": subject, "customer": customer,
                                       "session": session, "conversation": conversation})).hexdigest()


def prepare_request_key(binding: str, request_id: str) -> str:
    """Exactly Actions._prepare_identity's key; do not reconstruct its raw handle."""
    return hashlib.sha256(json.dumps([binding, request_id]).encode()).hexdigest()


@contextmanager
def readonly_snapshot(path: Path, required: dict[str, set[str]]) -> Iterator[sqlite3.Connection]:
    """Operator-detached backup prerequisite; immutable reads avoid WAL recovery."""
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_file() or any(Path(str(resolved) + suffix).exists()
                                         for suffix in ("-wal", "-shm", "-journal")):
            raise SnapshotError("snapshot_not_consolidated")
        db = sqlite3.connect(resolved.as_uri() + "?mode=ro&immutable=1", uri=True)
    except SnapshotError:
        raise
    except (OSError, sqlite3.Error, ValueError):
        raise SnapshotError("snapshot_unavailable") from None
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        for table, columns in required.items():
            entry = db.execute("SELECT type FROM sqlite_master WHERE name=?", (table,)).fetchone()
            if not entry or entry[0] != "table":
                raise SnapshotError("snapshot_schema_unavailable")
            actual = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
            if not columns <= actual:
                raise SnapshotError("snapshot_schema_unavailable")
        yield db
    except sqlite3.Error:
        raise SnapshotError("snapshot_unavailable") from None
    finally:
        db.close()


def _text(value: object, limit: int = 128) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= limit


def _number(value: object) -> bool:
    return type(value) in {int, float} and math.isfinite(value) and value > 0


def _json_object(raw: object) -> dict | None:
    if not isinstance(raw, str) or len(raw) > _MAX_JSON:
        return None

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        if len(raw.encode("utf-8")) > _MAX_JSON:
            return None
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        return value if isinstance(value, dict) else None
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return None


def _same_json(left: dict, right: dict) -> bool:
    try:
        return rfc8785.dumps(left) == rfc8785.dumps(right)
    except (ValueError, TypeError, RecursionError):
        return False


def _utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= 40:
        return False
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return moment.tzinfo is not None and moment.utcoffset().total_seconds() == 0
    except (ValueError, TypeError, OverflowError):
        return False


def _transaction(facts: dict) -> bool:
    return (set(facts) == set(_TRANSACTION_LIMITS) | {"merchant"}
            and all(isinstance(facts.get(field), str) and len(facts[field]) <= limit
                    for field, limit in _TRANSACTION_LIMITS.items())
            and re.fullmatch(r"txn_[a-f0-9]{12}", facts["transaction_reference"]) is not None
            and (facts["merchant"] is None or isinstance(facts["merchant"], str) and len(facts["merchant"]) <= 160))


def _case_projection(value: object, facts: dict) -> bool:
    """Validate saved current-schema evidence; this does not establish lost consent."""
    if (not _transaction(facts) or not isinstance(value, dict) or set(value) != _PROJECTION_FIELDS
            or value.get("coverage") != "sandbox_only" or value.get("source") != "sandbox_cases"):
        return False
    if not isinstance(value.get("state"), str):
        return False
    if value["state"] in {"not_found", "action_unverified"}:
        return value.get("receipt") is None
    receipt = value.get("receipt")
    return (value.get("state") == "verified" and isinstance(receipt, dict)
            and set(receipt) == _RECEIPT_FIELDS
            and isinstance(receipt.get("id"), str)
            and re.fullmatch(r"CMP-SBX-[A-Za-z0-9_-]{8}", receipt["id"]) is not None
            and receipt.get("kind") == _ACTION and receipt.get("simulated") is True
            and receipt.get("status") == "received"
            and isinstance(receipt.get("snapshot"), str) and _SNAPSHOT.fullmatch(receipt["snapshot"]) is not None
            and _utc_timestamp(receipt.get("created_at"))
            and isinstance(receipt.get("transaction"), dict) and _same_json(receipt["transaction"], facts))


def _prepare_schema(result: dict, facts: dict) -> str | None:
    """Accept only the two explicit saved schemas, never arbitrary extra fields."""
    fields = set(result)
    if not isinstance(result.get("decision"), str):
        return None
    if fields == _PREPARE_FIELDS:
        return "legacy_prepare/v0" if result.get("decision") in {"intake", "handoff"} else None
    if fields != _PREPARE_FIELDS | {"existing_case"} or not _case_projection(result["existing_case"], facts):
        return None
    state, decision = result["existing_case"]["state"], result.get("decision")
    if ((decision == "existing_case" and state != "verified")
            or (decision != "existing_case" and state == "verified")
            or (decision == "intake" and state != "not_found")
            or (state == "action_unverified" and (decision != "handoff" or result.get("reason") != "action_unverified"))):
        return None
    return "current_prepare/v1"


def _handoff_packet(raw: object, facts: dict, snapshot: str, reason: str) -> bool:
    packet = _json_object(raw)
    if not _transaction(facts) or not packet or set(packet) != _PACKET_FIELDS:
        return False
    provenance, questions = packet.get("transaction_provenance"), packet.get("unanswered_questions")
    return (packet.get("schema") == "banking-sandbox-handoff/v1"
            and isinstance(packet.get("transaction"), dict) and _same_json(packet["transaction"], facts)
            and packet.get("reason") == reason and packet.get("human_responded") is False
            and isinstance(provenance, dict) and set(provenance) == {"source", "snapshot", "as_of"}
            and provenance.get("source") == "owned_serving_snapshot" and provenance.get("snapshot") == snapshot
            and _utc_timestamp(provenance.get("as_of"))
            and isinstance(questions, list) and len(questions) <= 8
            and all(isinstance(question, str) and 1 <= len(question) <= 240 and question.strip()
                    and not any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in question)
                    for question in questions))


def _report(reference: str, now: float) -> dict:
    return {"scope": "offline_snapshots_only", "review_reference": reference,
            "checked_at": int(now), "state": "unresolved",
            "required_disposition": "leave_unresolved_locked",
            "snapshot_action_locked": "unproven", "live_action_lock": "unproven",
            "consent_verified": False,
            "consent_for_lost_prepare_proven": False,
            "human_pickup": "unproven", "handoff_evidence": "unproven",
            "case_evidence": "unproven", "finding": "review_reference_not_found"}


def _existing_case(mcp: sqlite3.Connection, row: sqlite3.Row, customer: str, output: dict) -> None:
    # This table has no request/session binding. Even an exact snapshot match
    # is only an existing case, never consent for the lost prepare.
    cases = mcp.execute("""SELECT snapshot FROM sandbox_cases
        WHERE customer=? AND transaction_id=? AND action=?""",
        (customer, row["prepare_transaction_id"], _ACTION)).fetchall()
    if cases:
        output["case_evidence"] = "existing_case_only"
        output["case_snapshot_matches"] = any(case["snapshot"] == row["prepare_snapshot"] for case in cases)


def _inspect(frontend: sqlite3.Connection, mcp: sqlite3.Connection, row: sqlite3.Row,
             reference: str, now: float) -> dict:
    output = _report(reference, now)
    saved = _json_object(row["result_json"])
    if not saved or saved.get("state") not in _UNRESOLVED:
        output["finding"] = "not_unresolved_prepare"
        return output
    output["frontend_state"] = saved["state"]
    output["snapshot_action_locked"] = True
    sessions = frontend.execute("SELECT * FROM chat_sessions WHERE session_id=?", (row["session_id"],)).fetchall()
    if len(sessions) != 1:
        output["finding"] = "frontend_identity_mismatch"
        return output
    session = sessions[0]
    if (not _text(row["owner"]) or not _text(row["session_id"])
            or row["session_id"] != session["session_id"] or row["owner"] != session["owner"]
            or type(row["expires"]) is not int or row["expires"] <= 0
            or row["expires"] != session["expires"]
            or not _text(session["subject"]) or not _text(session["customer_id"])
            or not isinstance(session["conversation_id"], str) or not _UUID4.fullmatch(session["conversation_id"])
            or row["prepare_conversation_id"] != session["conversation_id"]
            or not isinstance(saved.get("request_id"), str) or not _UUID4.fullmatch(saved["request_id"])
            or not isinstance(row["target_reference"], str) or not _PUBLIC_TARGET.fullmatch(row["target_reference"])
            or ("target_reference" in saved and saved["target_reference"] != row["target_reference"])
            or not _text(row["prepare_transaction_id"])
            or not isinstance(row["prepare_snapshot"], str) or not _SNAPSHOT.fullmatch(row["prepare_snapshot"])
            or type(session["revoked"]) is not int or session["revoked"] not in {0, 1}
            or type(row["prepare_recovery_attempts"]) is not int or row["prepare_recovery_attempts"] < 0
            or type(row["prepare_recovery_deadline"]) is not int or row["prepare_recovery_deadline"] <= 0):
        output["finding"] = "frontend_identity_mismatch"
        return output
    output["session_expired"] = session["expires"] <= now
    output["session_revoked"] = bool(session["revoked"])
    output["recovery_exhausted"] = (row["prepare_recovery_attempts"] >= 6
                                     or now + 20 >= row["prepare_recovery_deadline"])
    identities = mcp.execute("SELECT subject,customer FROM sessions WHERE session=?", (row["session_id"],)).fetchall()
    if (len(identities) != 1 or identities[0]["subject"] != session["subject"]
            or identities[0]["customer"] != session["customer_id"]):
        output["finding"] = "mcp_identity_mismatch"
        return output
    try:
        binding = principal_binding(session["subject"], session["customer_id"], row["session_id"],
                                    session["conversation_id"])
    except (ValueError, TypeError, UnicodeError):
        output["finding"] = "frontend_identity_mismatch"
        return output
    key = prepare_request_key(binding, saved["request_id"])
    pending = mcp.execute("SELECT * FROM action_pending WHERE request_key=?", (key,)).fetchall()
    if not pending:
        _existing_case(mcp, row, session["customer_id"], output)
        output["finding"] = "pending_evidence_absent"
        return output
    if len(pending) != 1:
        output["finding"] = "pending_evidence_ambiguous"
        return output
    pending = pending[0]
    facts, result = _json_object(pending["facts"]), _json_object(pending["result_json"])
    schema = _prepare_schema(result, facts) if facts and result else None
    if (pending["binding"] != binding or pending["customer"] != session["customer_id"]
            or pending["transaction_id"] != row["prepare_transaction_id"]
            or pending["snapshot"] != row["prepare_snapshot"] or pending["action"] != _ACTION
            or not _number(pending["expires"]) or not facts or not result
            or schema is None
            or result.get("snapshot") != pending["snapshot"] or result.get("action") != pending["action"]
            or result.get("decision") != pending["decision"] or result.get("reason") != pending["reason"]
            or pending["decision"] not in {"intake", "handoff", "existing_case"}
            or (pending["decision"] in {"intake", "existing_case"} and pending["reason"] is not None)
            or (pending["decision"] == "handoff" and pending["reason"] not in _REASONS)
            or not isinstance(result.get("transaction"), dict) or not _same_json(result["transaction"], facts)
            or not isinstance(result.get("risk"), dict)):
        output["finding"] = "pending_evidence_mismatch"
        return output
    output["prepare_schema"] = schema
    expired = pending["expires"] <= now
    _existing_case(mcp, row, session["customer_id"], output)
    output["pending_expired"] = expired
    output["finding"] = "pending_evidence_expired" if expired else "exact_pending_prepare_evidence"
    # Only the same request key is eligible. Never search by a HOF ID supplied
    # by a user or by an approximate customer/transaction match.
    handoffs = mcp.execute("SELECT * FROM sandbox_handoffs WHERE idempotency_key=?", (key,)).fetchall()
    if not handoffs:
        return output
    if len(handoffs) != 1:
        output["finding"] = "handoff_evidence_ambiguous"
        return output
    handoff = handoffs[0]
    handoff_facts = _json_object(handoff["facts"])
    if (pending["decision"] != "handoff" or handoff["binding"] != binding
            or handoff["customer"] != session["customer_id"]
            or handoff["transaction_id"] != row["prepare_transaction_id"]
            or handoff["snapshot"] != row["prepare_snapshot"] or handoff["reason"] != pending["reason"]
            or not isinstance(handoff["id"], str) or not re.fullmatch(r"HOF-[A-Za-z0-9_-]{8}", handoff["id"])
            or not handoff_facts or not _same_json(handoff_facts, facts)):
        output["finding"] = "handoff_evidence_mismatch"
        return output
    if "packet_json" not in handoff.keys() or handoff["packet_json"] is None:
        # A matched historical row is useful triage evidence, but cannot prove
        # the new saved packet or its questions/provenance/human-response fields.
        if schema == "legacy_prepare/v0":
            output["handoff_evidence"] = "historical_request_matched_row"
            output["handoff_reference"] = handoff["id"]
            output["finding"] = "historical_handoff_row_evidence"
        else:
            output["finding"] = "handoff_packet_unverified"
        return output
    if not _handoff_packet(handoff["packet_json"], facts, pending["snapshot"], pending["reason"]):
        output["finding"] = "handoff_packet_unverified"
        return output
    output["handoff_evidence"] = "exact_request_matched_packet"
    output["handoff_reference"] = handoff["id"]
    # HOF packets outlive the prepare TTL. Expiry remains explicit metadata;
    # even exact historical packets never resolve or authorize an action.
    output["finding"] = "exact_handoff_packet_evidence"
    return output


def _snapshot_digest(path: Path) -> str:
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_file() or any(Path(str(resolved) + suffix).exists()
                                         for suffix in ("-wal", "-shm", "-journal")):
            raise SnapshotError("snapshot_not_consolidated")
        digest = hashlib.sha256()
        with resolved.open("rb") as snapshot:
            for chunk in iter(lambda: snapshot.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except SnapshotError:
        raise
    except OSError:
        raise SnapshotError("snapshot_unavailable") from None


def _read_report(frontend: sqlite3.Connection, mcp: sqlite3.Connection,
                 reference: str | None, now: float) -> dict:
    rows = frontend.execute("SELECT * FROM action_status").fetchall()
    if reference is not None:
        matching = [row for row in rows if review_reference(row["action_id"]) == reference]
        if not matching:
            return _report(reference, now)
        if len(matching) != 1:
            result = _report(reference, now)
            result["finding"] = "review_reference_ambiguous"
            return result
        return _inspect(frontend, mcp, matching[0], reference, now)
    counts = Counter()
    reference_counts = Counter(review_reference(row["action_id"]) for row in rows)
    unresolved = exhausted = expired = invalid_reference = unclassified = 0
    for row in rows:
        result = _json_object(row["result_json"])
        if not result:
            unclassified += 1
            continue
        if result.get("state") not in _UNRESOLVED:
            continue
        unresolved += 1
        if ((type(row["prepare_recovery_attempts"]) is int and row["prepare_recovery_attempts"] >= 6)
                or (type(row["prepare_recovery_deadline"]) is int
                    and 0 < row["prepare_recovery_deadline"] <= now + 20)):
            exhausted += 1
        ref = review_reference(row["action_id"])
        if ref is None:
            invalid_reference += 1
            counts["review_reference_unavailable"] += 1
            continue
        if reference_counts[ref] != 1:
            counts["review_reference_ambiguous"] += 1
            continue
        item = _inspect(frontend, mcp, row, ref, now)
        expired += int(item.get("pending_expired", False))
        counts[item["finding"]] += 1
    return {"mode": "summary", "scope": "offline_snapshots_only",
            "checked_at": int(now), "state": "unresolved",
            "required_disposition": "leave_unresolved_locked",
            "snapshot_action_locked": True if unresolved else "unproven",
            "live_action_lock": "unproven", "consent_verified": False,
            "consent_for_lost_prepare_proven": False, "human_pickup": "unproven",
            "unresolved_prepare_count": unresolved, "recovery_exhausted_count": exhausted,
            "pending_expired_count": expired,
            "unclassified_action_status_count": unclassified,
            "review_reference_unavailable_count": invalid_reference,
            "findings": dict(sorted(counts.items()))}


def triage(frontend_path: Path, mcp_path: Path, reference: str | None = None, *,
           now: float | None = None) -> dict:
    """Return redacted historical evidence; every outcome leaves state unresolved."""
    now = time.time() if now is None else now
    if reference is not None and not _REVIEW.fullmatch(reference):
        raise ValueError("invalid_review_reference")
    try:
        if frontend_path.samefile(mcp_path):
            raise SnapshotError("snapshot_paths_not_distinct")
    except OSError:
        raise SnapshotError("snapshot_unavailable") from None
    digests = {"frontend": _snapshot_digest(frontend_path), "mcp": _snapshot_digest(mcp_path)}
    with readonly_snapshot(frontend_path, _FRONTEND_COLUMNS) as frontend:
        with readonly_snapshot(mcp_path, _MCP_COLUMNS) as mcp:
            result = _read_report(frontend, mcp, reference, now)
    if digests != {"frontend": _snapshot_digest(frontend_path), "mcp": _snapshot_digest(mcp_path)}:
        raise SnapshotError("snapshot_changed_during_read")
    result["snapshot_sha256"] = digests
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend-snapshot", type=Path, required=True)
    parser.add_argument("--mcp-snapshot", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--review-reference")
    mode.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = triage(args.frontend_snapshot, args.mcp_snapshot, args.review_reference)
    except (SnapshotError, ValueError) as exc:
        result = {"scope": "offline_snapshots_only", "state": "unresolved",
                  "required_disposition": "leave_unresolved_locked",
                  "snapshot_action_locked": "unproven", "live_action_lock": "unproven",
                  "consent_verified": False, "consent_for_lost_prepare_proven": False,
                  "human_pickup": "unproven", "finding": str(exc)}
        print(json.dumps(result, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
