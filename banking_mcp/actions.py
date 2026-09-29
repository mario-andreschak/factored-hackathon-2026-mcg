"""Owner-bound simulated intake and handoff state. No live-bank write exists here."""
from __future__ import annotations

import hashlib
import json
import math
import secrets
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .security import BankError, Principal, StateStore


ACTION = "simulated_intake"
PENDING_SECONDS = 600
HANDOFF_REASONS = frozenset({"high_risk", "missing_evidence", "out_of_policy",
                             "emergency", "action_unverified", "customer_request",
                             "clarification_exhausted", "duplicate_review", "no_match_exhausted",
                             "tool_failure"})


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
                 evidence_file: Path | None):
        self.store, self.repository, self.coverage_start = store, repository, coverage_start
        self.evidence_file = evidence_file
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
        row = db.execute("""SELECT binding,customer,transaction_id,snapshot,action,decision,reason,facts,expires,evidence_digest
            FROM action_pending WHERE id=?""", (_digest(handle),)).fetchone()
        if (not row or (require_fresh and row[8] <= self.clock()) or row[1] != principal.customer
                or not secrets.compare_digest(row[0], principal.binding())):
            raise BankError("reference_unavailable")
        return row

    def _coverage(self, db, now: float) -> bool:
        return self.store.sandbox_coverage_complete(db, self.coverage_start, now)

    def prepare(self, principal: Principal, transaction_id: str, build: str) -> dict:
        snapshot, row = self.repository.owned_transaction_id(principal, transaction_id, build)
        facts = self.repository._visible(row, snapshot)
        evidence = self._evidence(snapshot, transaction_id)
        now = self.clock()
        handle = secrets.token_urlsafe(32)
        with self.store.connect() as db:
            # R16's provisional synthetic measure is prior distinct persisted
            # cases, excluding this target, plus this current distinct request.
            prior = db.execute("""SELECT count(DISTINCT transaction_id) FROM sandbox_cases
                WHERE customer=? AND action=? AND transaction_id<>?
                  AND created_at>=? AND created_at<?""",
                (principal.customer, ACTION, transaction_id, now - 86400, now)).fetchone()[0]
            duplicate = db.execute("""SELECT 1 FROM sandbox_cases
                WHERE customer=? AND transaction_id=? AND action=?""",
                (principal.customer, transaction_id, ACTION)).fetchone() is not None
            count = prior + 1
            covered = self._coverage(db, now)
            age = (datetime.fromtimestamp(now, timezone.utc).date() - row["transaction_date"].date()).days
            duplicate = duplicate or bool(evidence and (evidence["historical_complaints"] == "exact_open_case"
                                                     or evidence["duplicate_signal"] == "persistent"))
            high = (covered and count >= 3) or bool(evidence and (
                evidence["fraud_score"] is not None and evidence["fraud_score"] >= 70
                or evidence["amount_usd"] is not None and evidence["amount_usd"] >= 1000))
            evidence_incomplete = (evidence is None or evidence["historical_complaints"] == "uncertain"
                or evidence["duplicate_signal"] == "unknown" or evidence["fraud_score"] is None
                or evidence["amount_usd"] is None)
            reason = ("duplicate_review" if duplicate else "missing_evidence" if age < 0
                      else "out_of_policy" if age > 120
                      or str(row["transaction_status"]).lower() != "approved"
                      else "high_risk" if high else "missing_evidence" if not covered or evidence_incomplete
                      else None)
            decision = "handoff" if reason else "intake"
            db.execute("""INSERT INTO action_pending
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (_digest(handle), principal.binding(),
                principal.customer, transaction_id, snapshot.id, ACTION, decision, reason,
                json.dumps(facts), now + PENDING_SECONDS, self._evidence_digest(evidence)))
        return {"pending_handle": handle, "snapshot": snapshot.id, "action": ACTION,
                "decision": decision, "reason": reason, "transaction": facts,
                "risk": {"unrecognized_count_24h": count if covered else None,
                         "risk_data_complete": covered, "coverage": "sandbox_only",
                         "source": "sandbox_cases", "window_start": _utc(now - 86400),
                         "window_end": _utc(now)}}

    def receipt(self, principal: Principal, pending_handle: str) -> dict:
        with self.store.connect() as db:
            pending = self._pending(db, principal, pending_handle, require_fresh=False)
            row = db.execute("""SELECT id,snapshot,created_at,facts FROM sandbox_cases
                WHERE customer=? AND transaction_id=? AND action=? AND snapshot=?""",
                (principal.customer, pending[2], ACTION, pending[3])).fetchone()
        if not row:
            return {"state": "action_unverified", "receipt": None}
        return {"state": "created", "receipt": {"id": row[0], "kind": ACTION,
                "simulated": True, "snapshot": row[1], "created_at": _utc(row[2]),
                "transaction": json.loads(row[3])}}

    def confirm(self, principal: Principal, pending_handle: str, confirmed: bool) -> dict:
        if confirmed is not True:
            raise BankError("confirmation_required")
        with self.store.connect() as db:
            pending = self._pending(db, principal, pending_handle)
        if pending[5] != "intake":
            raise BankError("handoff_required")
        snapshot, row = self.repository.owned_transaction_id(principal, pending[2], pending[3])
        if self.repository._visible(row, snapshot) != json.loads(pending[7]):
            raise BankError("snapshot_changed")
        evidence = self._evidence(snapshot, pending[2])
        if evidence is None or self._evidence_digest(evidence) != pending[9]:
            raise BankError("risk_data_unavailable")
        with self.store.connect() as db:
            # Reserve the SQLite writer before reading the R16 count. The same
            # transaction serializes distinct charge confirmations and revokes
            # across MCP processes, not merely across threads in this process.
            db.execute("BEGIN IMMEDIATE")
            now = self.clock()
            pending = self._pending(db, principal, pending_handle)
            if principal.expires <= int(time.time()) or db.execute(
                    "SELECT 1 FROM revoked WHERE session=?", (principal.session,)).fetchone():
                raise BankError("authorization_denied")
            age = (datetime.fromtimestamp(now, timezone.utc).date() - row["transaction_date"].date()).days
            if age < 0 or age > 120 or str(row["transaction_status"]).lower() != "approved":
                raise BankError("risk_data_unavailable")
            existing = db.execute("""SELECT id FROM sandbox_cases WHERE
                customer=? AND transaction_id=? AND action=?""",
                (principal.customer, pending[2], ACTION)).fetchone()
            if not existing:
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
                db.execute("""INSERT OR IGNORE INTO sandbox_cases
                    VALUES (?,?,?,?,?,?,?)""", (_receipt_id("CMP-SBX-"),
                    principal.customer, pending[2], ACTION, pending[3], now, pending[7]))
        # A separate durable read determines the claim after uncertain write paths.
        return self.receipt(principal, pending_handle)

    def handoff(self, principal: Principal, reason: str, pending_handle: str | None,
                request_id: str | None = None) -> dict:
        if reason not in HANDOFF_REASONS:
            raise BankError("invalid_arguments")
        if request_id is not None or not pending_handle:
            try:
                if not request_id or str(uuid.UUID(request_id)) != request_id:
                    raise ValueError()
            except ValueError:
                raise BankError("invalid_arguments") from None
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if principal.expires <= int(time.time()) or db.execute(
                    "SELECT 1 FROM revoked WHERE session=?", (principal.session,)).fetchone():
                raise BankError("authorization_denied")
            pending = self._pending(db, principal, pending_handle, require_fresh=False) if pending_handle else None
            transaction_id = pending[2] if pending else None
            snapshot = pending[3] if pending else None
            facts = pending[7] if pending else "{}"
            key = _digest(json.dumps([principal.binding(), request_id])) if request_id else _digest(
                json.dumps([principal.binding(), _digest(pending_handle), transaction_id, snapshot, reason]))
            db.execute("""INSERT OR IGNORE INTO sandbox_handoffs
                VALUES (?,?,?,?,?,?,?,?,?)""", (_receipt_id("HOF-"),
                principal.binding(), principal.customer, transaction_id, snapshot,
                reason, self.clock(), facts, key))
            row = db.execute("""SELECT id,transaction_id,snapshot,reason,facts FROM sandbox_handoffs
                WHERE idempotency_key=?""", (key,)).fetchone()
            if row[1:] != (transaction_id, snapshot, reason, facts):
                raise BankError("invalid_arguments")
        return self.read_handoff(principal, row[0])

    def read_handoff(self, principal: Principal, handoff_id: str) -> dict:
        if not isinstance(handoff_id, str) or not handoff_id.startswith("HOF-") or len(handoff_id) != 12:
            raise BankError("reference_unavailable")
        with self.store.connect() as db:
            row = db.execute("""SELECT binding,customer,snapshot,reason,created_at,facts
                FROM sandbox_handoffs WHERE id=?""", (handoff_id,)).fetchone()
        if not row or row[1] != principal.customer or not secrets.compare_digest(row[0], principal.binding()):
            raise BankError("reference_unavailable")
        return {"state": "created", "handoff": {"id": handoff_id, "reason": row[3],
                "snapshot": row[2], "created_at": _utc(row[4]), "facts": json.loads(row[5]),
                "human_responded": False}}
