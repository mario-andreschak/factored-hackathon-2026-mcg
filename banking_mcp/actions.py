"""Owner-bound simulated intake and handoff state. No live-bank write exists here."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .security import BankError, Principal, StateStore


ACTION = "simulated_intake"
PENDING_SECONDS = 600
RECEIPT_WAIT_SECONDS = 5
HANDOFF_REASONS = frozenset({"high_risk", "missing_evidence", "out_of_policy",
                             "emergency", "action_unverified", "customer_request",
                             "clarification_exhausted", "duplicate_review", "no_match_exhausted",
                             "tool_failure"})
HANDOFF_PACKET_SCHEMA = "banking-sandbox-handoff/v1"
CASE_RECEIPT_FIELDS = frozenset({"id", "kind", "simulated", "snapshot", "created_at",
                               "status", "transaction"})


def _object(value: str) -> dict:
    """Duplicate keys and non-JSON numbers cannot become persisted evidence."""
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = item
        return result
    def invalid_number(_):
        raise ValueError("invalid number")
    result = json.loads(value, object_pairs_hook=pairs, parse_constant=invalid_number)
    if not isinstance(result, dict):
        raise ValueError("object required")
    return result


def _receipt_id(prefix: str) -> str:
    # Eight base64url characters preserve the provisional CMP-SBX/HOF shape
    # with 48 random bits, while the SQLite primary key remains authoritative.
    return prefix + secrets.token_urlsafe(6)


def _utc(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class Actions:
    def __init__(self, store: StateStore, repository, coverage_start: int | None,
                 evidence_file: Path | None, prepare_secret: str):
        self.store, self.repository, self.coverage_start = store, repository, coverage_start
        self.evidence_file = evidence_file
        self._prepare_secret = prepare_secret.encode("utf-8")
        self.clock = time.time

    def _evidence(self, snapshot, transaction_id: str) -> dict | None:
        """A private, pinned synthetic fixture; unknown signals cannot clear intake."""
        if self.evidence_file is None:
            return None
        try:
            if self.evidence_file.stat().st_size > 1024 * 1024:
                return None
            evidence = json.loads(self.evidence_file.read_text(encoding="utf-8"))
            manifest = json.loads((snapshot.build / "snapshot.json").read_text(encoding="utf-8"))
            if (evidence.get("build_id") != snapshot.id
                    or evidence.get("source_fingerprint") != manifest.get("source_fingerprint")):
                return None
            item = evidence["transactions"][transaction_id]
            if (not isinstance(item, dict) or set(item) != {
                    "historical_complaints", "duplicate_signal", "fraud_score", "amount_usd"}
                    or item["historical_complaints"] not in {"clear_in_snapshot", "exact_open_case", "uncertain"}
                    or item["duplicate_signal"] not in {"clear", "persistent", "unknown"}):
                return None
            for key in ("fraud_score", "amount_usd"):
                value = item[key]
                if value is not None and (type(value) not in {int, float} or not math.isfinite(value)
                                          or value < 0 or (key == "fraud_score" and value > 100)):
                    return None
            return item
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return None

    @staticmethod
    def _evidence_digest(item: dict | None) -> str | None:
        return _digest(json.dumps(item, sort_keys=True)) if item is not None else None

    def _pending(self, db, principal: Principal, handle: str, *, require_fresh: bool = True):
        if not isinstance(handle, str) or not 32 <= len(handle) <= 64:
            raise BankError("reference_unavailable")
        row = db.execute("""SELECT binding,customer,transaction_id,snapshot,action,decision,reason,facts,expires,evidence_digest,result_json,confirmation_state
            FROM action_pending WHERE id=?""", (_digest(handle),)).fetchone()
        if (not row or (require_fresh and row[8] <= self.clock()) or row[1] != principal.customer
                or not secrets.compare_digest(row[0], principal.binding())):
            raise BankError("reference_unavailable")
        try:
            if row[11] not in {None, "prepared", "attempted", "verified"}:
                raise ValueError("invalid confirmation state")
            prepared = _object(row[10])
            if any(prepared.get(field) != value for field, value in (
                    ("snapshot", row[3]), ("action", row[4]), ("decision", row[5]),
                    ("reason", row[6]), ("transaction", _object(row[7])))):
                raise ValueError("pending evidence mismatch")
        except (ValueError, TypeError):
            raise BankError("action_unverified") from None
        return row

    def _coverage(self, db, now: float) -> bool:
        return self.store.sandbox_coverage_complete(db, self.coverage_start, now)

    def _prepare_identity(self, principal: Principal, request_id: str) -> tuple[str, str]:
        try:
            parsed = uuid.UUID(request_id)
            if parsed.version != 4 or str(parsed) != request_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise BankError("invalid_arguments") from None
        key = _digest(json.dumps([principal.binding(), request_id]))
        raw = hmac.new(self._prepare_secret, ("pending:" + key).encode(), hashlib.sha256).digest()
        return key, base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    @staticmethod
    def _prepare_identity_record(db, principal: Principal, key: str, transaction_id: str, build: str):
        existing = db.execute("""SELECT id,binding,customer,transaction_id,snapshot,expires,result_json
            FROM action_pending WHERE request_key=?""", (key,)).fetchone()
        if not existing:
            return None
        if (existing[3] != transaction_id or existing[4] != build
                or existing[2] != principal.customer
                or not secrets.compare_digest(existing[1], principal.binding())):
            raise BankError("invalid_arguments")
        return existing

    def _prepare_replay(self, db, principal: Principal, key: str, handle: str,
                        transaction_id: str, build: str, verified_facts: dict) -> dict | None:
        existing = self._prepare_identity_record(db, principal, key, transaction_id, build)
        if existing is None:
            return None
        if existing[5] <= self.clock() or existing[0] != _digest(handle) or not existing[6]:
            raise BankError("reference_unavailable")
        pending = self._pending(db, principal, handle)
        if verified_facts != _object(pending[7]):
            raise BankError("snapshot_changed")
        projection = self._case_projection(db, principal.customer, transaction_id, verified_facts)
        result = _object(existing[6])
        if projection["state"] == "verified":
            # Keep the original durable pending intent for safe confirm retry,
            # while the prepare response reflects its already-created case.
            result = {**result, "decision": "existing_case", "reason": None, "existing_case": projection}
        elif projection["state"] == "action_unverified":
            result = {**result, "decision": "handoff", "reason": "action_unverified", "existing_case": projection}
        return {**result, "pending_handle": handle}

    @staticmethod
    def _case_projection(db, customer: str, transaction_id: str, facts: dict,
                         *, pending_uncertain: bool = True) -> dict:
        result = {"state": "not_found", "receipt": None,
                  "coverage": "sandbox_only", "source": "sandbox_cases"}
        row = db.execute("""SELECT c.id,c.snapshot,c.created_at,c.facts,r.receipt_json
            FROM sandbox_cases c LEFT JOIN sandbox_case_receipts r ON r.case_id=c.id
            WHERE c.customer=? AND c.transaction_id=? AND c.action=?""",
            (customer, transaction_id, ACTION)).fetchone()
        if row is None:
            # A prepared intake can have an uncertain confirm outcome. Absence
            # from this read is not proof that its attempt was never made.
            if pending_uncertain:
                preparations = db.execute("""SELECT decision,reason,snapshot,facts,result_json,confirmation_state
                    FROM action_pending WHERE customer=? AND transaction_id=? AND action=?""",
                    (customer, transaction_id, ACTION)).fetchall()
                for preparation in preparations:
                    try:
                        prepared = _object(preparation[4])
                        # A retained existing-case intent is prior case evidence;
                        # losing the case rows cannot establish a clean absence.
                        if (preparation[5] != "prepared"
                                or preparation[0] == "existing_case"
                                or preparation[0] not in {"intake", "handoff", "existing_case"}
                                or any(prepared.get(field) != value for field, value in (
                                    ("decision", preparation[0]), ("reason", preparation[1]),
                                    ("snapshot", preparation[2]), ("action", ACTION),
                                    ("transaction", _object(preparation[3]))))):
                            result["state"] = "action_unverified"
                            break
                    except (ValueError, TypeError):
                        result["state"] = "action_unverified"
                        break
            return result
        result["state"] = "action_unverified"
        try:
            if (not isinstance(row[0], str) or re.fullmatch(r"CMP-SBX-[A-Za-z0-9_-]{8}", row[0]) is None
                    or not isinstance(row[1], str) or re.fullmatch(r"[A-Za-z0-9_-]{1,96}", row[1]) is None
                    or type(row[2]) not in {int, float} or not math.isfinite(row[2])
                    or row[2] < 0
                    or _object(row[3]) != facts or row[4] is None):
                return result
            receipt = _object(row[4])
            expected = {"id": row[0], "kind": ACTION, "simulated": True,
                        "snapshot": row[1], "created_at": _utc(row[2]),
                        "status": "received", "transaction": facts}
            if (set(receipt) != CASE_RECEIPT_FIELDS or receipt.get("simulated") is not True
                    or receipt != expected):
                return result
        except (ValueError, TypeError, OverflowError, OSError):
            return result
        return {**result, "state": "verified", "receipt": receipt}

    def local_case_status(self, principal: Principal, transaction_id: str, build: str) -> dict:
        """An owned exact charge projection, never a historical-complaint lookup."""
        snapshot, row = self.repository.owned_transaction_id(principal, transaction_id, build)
        facts = self.repository._visible(row, snapshot)
        try:
            with self.store.authority(principal) as db:
                result = self._case_projection(db, principal.customer, transaction_id, facts)
            self.store.assert_current(principal)
            return result
        except sqlite3.Error:
            raise BankError("service_unavailable") from None

    def prepare(self, principal: Principal, transaction_id: str, build: str, request_id: str) -> dict:
        key, handle = self._prepare_identity(principal, request_id)
        with self.store.authority(principal) as db:
            self._prepare_identity_record(db, principal, key, transaction_id, build)
        snapshot, row = self.repository.owned_transaction_id(principal, transaction_id, build)
        facts = self.repository._visible(row, snapshot)
        evidence = self._evidence(snapshot, transaction_id)
        with self.store.authority(principal, write=True) as db:
            self.repository.assert_current_snapshot(build)
            replay = self._prepare_replay(db, principal, key, handle, transaction_id, build, facts)
            if replay is not None:
                # Exit the transaction before the final fresh identity read.
                result = replay
            else:
                result = self._prepare_new(db, principal, transaction_id, snapshot, row,
                                           evidence, key, handle, facts)
        self.store.assert_current(principal)
        return {**result, "pending_handle": handle}

    def _prepare_new(self, db, principal, transaction_id, snapshot, row,
                     evidence, key, handle, facts):
        now = self.clock()
        # R16's provisional synthetic measure is prior distinct persisted
        # cases, excluding this target, plus this current distinct request.
        prior = db.execute("""SELECT count(DISTINCT transaction_id) FROM sandbox_cases
            WHERE customer=? AND action=? AND transaction_id<>?
              AND created_at>=? AND created_at<?""",
            (principal.customer, ACTION, transaction_id, now - 86400, now)).fetchone()[0]
        existing_case = self._case_projection(db, principal.customer, transaction_id, facts)
        count = prior + 1
        covered = self._coverage(db, now)
        age = (datetime.fromtimestamp(now, timezone.utc).date() - row["transaction_date"].date()).days
        duplicate = bool(evidence and (evidence["historical_complaints"] == "exact_open_case"
                                      or evidence["duplicate_signal"] == "persistent"))
        high = (covered and count >= 3) or bool(evidence and (
            evidence["fraud_score"] is not None and evidence["fraud_score"] >= 70
            or evidence["amount_usd"] is not None and evidence["amount_usd"] >= 1000))
        evidence_incomplete = (evidence is None or evidence["historical_complaints"] == "uncertain"
            or evidence["duplicate_signal"] == "unknown" or evidence["fraud_score"] is None
            or evidence["amount_usd"] is None)
        reason = ("action_unverified" if existing_case["state"] == "action_unverified"
                  else "duplicate_review" if duplicate else "missing_evidence" if age < 0
                  else "out_of_policy" if age > 120
                  or str(row["transaction_status"]).lower() != "approved"
                  else "high_risk" if high else "missing_evidence" if not covered or evidence_incomplete
                  else None)
        if existing_case["state"] == "verified":
            decision, reason = "existing_case", None
        else:
            decision = "handoff" if reason else "intake"
        result = {"snapshot": snapshot.id, "action": ACTION,
                  "decision": decision, "reason": reason, "transaction": facts,
                  "existing_case": existing_case,
                  "risk": {"unrecognized_count_24h": count if covered else None,
                           "risk_data_complete": covered, "coverage": "sandbox_only",
                           "source": "sandbox_cases", "window_start": _utc(now - 86400),
                           "window_end": _utc(now)}}
        db.execute("""INSERT INTO action_pending
            (id,binding,customer,transaction_id,snapshot,action,decision,reason,facts,expires,
             evidence_digest,request_key,result_json,confirmation_state) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (_digest(handle), principal.binding(), principal.customer, transaction_id,
             snapshot.id, ACTION, decision, reason, json.dumps(facts), now + PENDING_SECONDS,
             self._evidence_digest(evidence), key, json.dumps(result), "prepared"))
        return result

    def receipt(self, principal: Principal, pending_handle: str) -> dict:
        with self.store.authority(principal) as db:
            try:
                pending = self._pending(db, principal, pending_handle, require_fresh=False)
            except BankError as exc:
                if exc.code == "action_unverified":
                    return {"state": "action_unverified", "receipt": None}
                raise
            projection = self._case_projection(db, principal.customer, pending[2], _object(pending[7]))
        self.store.assert_current(principal)
        if projection["state"] != "verified":
            return {"state": "action_unverified", "receipt": None}
        return {"state": "created", "receipt": projection["receipt"]}

    def _assert_intake_eligible(self, db, principal: Principal, pending, row: dict,
                                evidence: dict | None, now: float) -> None:
        age = (datetime.fromtimestamp(now, timezone.utc).date() - row["transaction_date"].date()).days
        if age < 0 or age > 120 or str(row["transaction_status"]).lower() != "approved":
            raise BankError("risk_data_unavailable")
        if evidence is None or self._evidence_digest(evidence) != pending[9]:
            raise BankError("risk_data_unavailable")
        if (evidence["historical_complaints"] != "clear_in_snapshot"
                or evidence["duplicate_signal"] != "clear"
                or evidence["fraud_score"] is None or evidence["amount_usd"] is None):
            raise BankError("risk_data_unavailable")
        if evidence["fraud_score"] >= 70 or evidence["amount_usd"] >= 1000:
            raise BankError("handoff_required")
        prior = db.execute("""SELECT count(DISTINCT transaction_id) FROM sandbox_cases
            WHERE customer=? AND action=? AND transaction_id<>?
              AND created_at>=? AND created_at<?""",
            (principal.customer, ACTION, pending[2], now - 86400, now)).fetchone()[0]
        if not self._coverage(db, now):
            raise BankError("risk_data_unavailable")
        if prior + 1 >= 3:
            raise BankError("handoff_required")

    def _wait_for_receipt(self, principal: Principal, pending_handle: str) -> dict:
        """Overlapping confirmation calls only read; an absent case is never rewritten."""
        deadline = time.monotonic() + RECEIPT_WAIT_SECONDS
        while True:
            with self.store.authority(principal) as db:
                if time.monotonic() > deadline:
                    raise BankError("action_unverified")
                pending = self._pending(db, principal, pending_handle)
                projection = self._case_projection(db, principal.customer, pending[2], _object(pending[7]),
                                                   pending_uncertain=False)
                if projection["state"] != "verified" and (projection["state"] == "action_unverified" or pending[11] != "attempted"):
                    raise BankError("action_unverified")
            if projection["state"] == "verified":
                self.store.assert_current(principal)
                return {"state": "created", "receipt": projection["receipt"]}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BankError("action_unverified")
            # The database connection is closed before waiting. Every next
            # read checks real-wall authorization and pending lifetime again.
            time.sleep(min(.05, remaining))

    def confirm(self, principal: Principal, pending_handle: str, confirmed: bool) -> dict:
        if confirmed is not True:
            raise BankError("confirmation_required")
        with self.store.authority(principal) as db:
            pending = self._pending(db, principal, pending_handle)
        if pending[5] != "intake":
            raise BankError("handoff_required")
        if pending[11] == "attempted":
            return self._wait_for_receipt(principal, pending_handle)
        snapshot, row = self.repository.owned_transaction_id(principal, pending[2], pending[3])
        if self.repository._visible(row, snapshot) != json.loads(pending[7]):
            raise BankError("snapshot_changed")
        evidence = self._evidence(snapshot, pending[2])
        already_verified = False
        overlapping_attempt = False
        with self.store.authority(principal, write=True) as db:
            # Commit the attempted marker BEFORE a potentially uncertain case
            # write. A lost/failed write cannot later become a clean no-match.
            pending = self._pending(db, principal, pending_handle)
            existing = self._case_projection(db, principal.customer, pending[2], _object(pending[7]))
            if existing["state"] == "action_unverified":
                if pending[11] == "attempted":
                    overlapping_attempt = True
                else:
                    raise BankError("action_unverified")
            already_verified = existing["state"] == "verified"
            if not already_verified and not overlapping_attempt:
                if pending[11] != "prepared":
                    raise BankError("action_unverified")
                self._assert_intake_eligible(db, principal, pending, row, evidence, self.clock())
                self.repository.assert_current_snapshot(pending[3])
                db.execute("UPDATE action_pending SET confirmation_state='attempted' WHERE id=?",
                           (_digest(pending_handle),))
        if overlapping_attempt:
            return self._wait_for_receipt(principal, pending_handle)
        if already_verified:
            return self.receipt(principal, pending_handle)
        with self.store.authority(principal, write=True) as db:
            # Recheck admission/risk under the same writer lock as the case and
            # receipt. Distinct charges cannot bypass the 24-hour threshold.
            pending = self._pending(db, principal, pending_handle)
            if pending[11] != "attempted":
                raise BankError("action_unverified")
            existing = self._case_projection(db, principal.customer, pending[2], _object(pending[7]),
                                             pending_uncertain=False)
            if existing["state"] == "action_unverified":
                raise BankError("action_unverified")
            if existing["state"] != "verified":
                now = self.clock()
                self._assert_intake_eligible(db, principal, pending, row, evidence, now)
                self.repository.assert_current_snapshot(pending[3])
                receipt_id = _receipt_id("CMP-SBX-")
                db.execute("""INSERT INTO sandbox_cases VALUES (?,?,?,?,?,?,?)""", (receipt_id,
                    principal.customer, pending[2], ACTION, pending[3], now, pending[7]))
                receipt = {"id": receipt_id, "kind": ACTION, "simulated": True,
                           "snapshot": pending[3], "created_at": _utc(now), "status": "received",
                           "transaction": _object(pending[7])}
                db.execute("INSERT INTO sandbox_case_receipts(case_id,receipt_json) VALUES (?,?)",
                           (receipt_id, json.dumps(receipt, sort_keys=True)))
            db.execute("UPDATE action_pending SET confirmation_state='verified' WHERE id=?",
                       (_digest(pending_handle),))
        # A separate durable read determines the claim after uncertain write paths.
        return self.receipt(principal, pending_handle)

    @staticmethod
    def _questions(value: list[str] | None) -> list[str]:
        if value is None:
            return []
        if (not isinstance(value, list) or len(value) > 8
                or any(not isinstance(item, str) or not 1 <= len(item) <= 240
                       or not item.strip() or any(ord(char) < 32 for char in item)
                       or any(0xD800 <= ord(char) <= 0xDFFF for char in item) for item in value)):
            raise BankError("invalid_arguments")
        return list(value)

    @staticmethod
    def _provenance(value: dict | None, snapshot: str | None) -> dict | None:
        if snapshot is None:
            if value is not None:
                raise ValueError("general handoff has no selected charge provenance")
            return None
        if (not isinstance(value, dict) or set(value) != {"source", "snapshot", "as_of"}
                or value.get("source") != "owned_serving_snapshot" or value.get("snapshot") != snapshot
                or not isinstance(value.get("as_of"), str)):
            raise ValueError("invalid selected charge provenance")
        moment = datetime.fromisoformat(value["as_of"].replace("Z", "+00:00"))
        if moment.tzinfo is None or moment.utcoffset().total_seconds() != 0:
            raise ValueError("UTC provenance required")
        return dict(value)

    @staticmethod
    def _handoff_key(principal: Principal, request_id: str | None, pending_handle: str | None,
                     pending, reason: str) -> str:
        if request_id:
            return _digest(json.dumps([principal.binding(), request_id]))
        return _digest(json.dumps([principal.binding(), _digest(pending_handle), pending[2], pending[3], reason]))

    def _handoff_replay(self, db, principal: Principal, key: str, pending, reason: str,
                        questions: list[str]) -> str | None:
        row = db.execute("""SELECT id,binding,customer,transaction_id,snapshot,reason,facts,packet_json
            FROM sandbox_handoffs WHERE idempotency_key=?""", (key,)).fetchone()
        if row is None:
            return None
        transaction_id, snapshot = (pending[2], pending[3]) if pending else (None, None)
        facts = _object(pending[7]) if pending else {}
        if row[1:7] != (principal.binding(), principal.customer, transaction_id, snapshot,
                        reason, json.dumps(facts, sort_keys=True)):
            raise BankError("invalid_arguments")
        try:
            packet = _object(row[7])
            saved_questions = self._questions(packet.get("unanswered_questions"))
            expected = {"schema": HANDOFF_PACKET_SCHEMA, "transaction": facts if pending else None,
                        "transaction_provenance": self._provenance(packet.get("transaction_provenance"), snapshot),
                        "reason": reason, "unanswered_questions": saved_questions, "human_responded": False}
            if packet != expected or packet.get("human_responded") is not False:
                raise ValueError("unverified packet")
        except (ValueError, TypeError, BankError):
            raise BankError("action_unverified") from None
        if saved_questions != questions:
            raise BankError("invalid_arguments")
        return row[0]

    def handoff(self, principal: Principal, reason: str, pending_handle: str | None,
                request_id: str | None = None, unanswered_questions: list[str] | None = None) -> dict:
        if reason not in HANDOFF_REASONS:
            raise BankError("invalid_arguments")
        questions = self._questions(unanswered_questions)
        if request_id is not None or not pending_handle:
            try:
                if not request_id or str(uuid.UUID(request_id)) != request_id:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise BankError("invalid_arguments") from None
        # The packet's selected facts come exclusively from a fresh owned read;
        # question text is bounded caller data and never supplies verified facts.
        with self.store.authority(principal) as db:
            original = self._pending(db, principal, pending_handle, require_fresh=False) if pending_handle else None
            key = self._handoff_key(principal, request_id, pending_handle, original, reason)
            existing_id = self._handoff_replay(db, principal, key, original, reason, questions)
        if existing_id is not None:
            # Retry reads the original verified packet, including its historical
            # provenance. A new serving snapshot cannot force a second write.
            return self.read_handoff(principal, existing_id)
        if original:
            selected_snapshot, selected_row = self.repository.owned_transaction_id(
                principal, original[2], original[3])
            if self.repository._visible(selected_row, selected_snapshot) != _object(original[7]):
                raise BankError("snapshot_changed")
        selected_facts = _object(original[7]) if original else None
        packet = {"schema": HANDOFF_PACKET_SCHEMA, "transaction": selected_facts,
                  "transaction_provenance": {"source": "owned_serving_snapshot", "snapshot": original[3],
                                             "as_of": _utc(time.time())} if original else None,
                  "reason": reason, "unanswered_questions": questions, "human_responded": False}
        with self.store.authority(principal, write=True) as db:
            pending = self._pending(db, principal, pending_handle, require_fresh=False) if pending_handle else None
            if pending != original:
                raise BankError("snapshot_changed")
            transaction_id = pending[2] if pending else None
            snapshot = pending[3] if pending else None
            facts = json.dumps(selected_facts or {}, sort_keys=True)
            existing_id = self._handoff_replay(db, principal, key, pending, reason, questions)
            if existing_id is not None:
                handoff_id = existing_id
            else:
                if pending:
                    self.repository.assert_current_snapshot(pending[3])
                handoff_id = _receipt_id("HOF-")
                db.execute("""INSERT INTO sandbox_handoffs
                    (id,binding,customer,transaction_id,snapshot,reason,created_at,facts,idempotency_key,packet_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""", (handoff_id,
                    principal.binding(), principal.customer, transaction_id, snapshot,
                    reason, self.clock(), facts, key, json.dumps(packet, sort_keys=True)))
        return self.read_handoff(principal, handoff_id)

    def read_handoff(self, principal: Principal, handoff_id: str) -> dict:
        if not isinstance(handoff_id, str) or re.fullmatch(r"HOF-[A-Za-z0-9_-]{8}", handoff_id) is None:
            raise BankError("reference_unavailable")
        with self.store.authority(principal) as db:
            row = db.execute("""SELECT binding,customer,snapshot,reason,created_at,facts,transaction_id,packet_json
                FROM sandbox_handoffs WHERE id=?""", (handoff_id,)).fetchone()
        if not row or row[1] != principal.customer or not secrets.compare_digest(row[0], principal.binding()):
            raise BankError("reference_unavailable")
        try:
            facts, packet = _object(row[5]), _object(row[7])
            expected = {"schema": HANDOFF_PACKET_SCHEMA, "transaction": facts if row[6] else None,
                        "transaction_provenance": self._provenance(packet.get("transaction_provenance"), row[2]),
                        "reason": row[3], "unanswered_questions": self._questions(packet.get("unanswered_questions")),
                        "human_responded": False}
            if (packet != expected or packet.get("human_responded") is not False
                    or row[3] not in HANDOFF_REASONS
                    or (not row[6] and (facts or row[2] is not None))
                    or (row[6] and (not facts or not isinstance(row[2], str)))
                    or type(row[4]) not in {int, float} or not math.isfinite(row[4]) or row[4] < 0):
                raise ValueError("unverified packet")
        except (ValueError, TypeError, OverflowError, OSError, BankError):
            raise BankError("action_unverified") from None
        currentness = "not_applicable"
        if row[6]:
            try:
                currentness = "same_snapshot" if self.repository.snapshot().id == row[2] else "different_snapshot"
            except (BankError, OSError, ValueError):
                currentness = "unknown"
        self.store.assert_current(principal)
        return {"state": "created", "handoff": {"id": handoff_id, "reason": row[3],
                "snapshot": row[2], "created_at": _utc(row[4]), "facts": facts, "packet": packet,
                "transaction_currentness": currentness,
                "human_responded": False}}
