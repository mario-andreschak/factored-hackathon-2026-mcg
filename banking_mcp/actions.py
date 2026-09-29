"""Owner-bound simulated intake and handoff state. No live-bank write exists here."""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from datetime import datetime, timezone

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
    def __init__(self, store: StateStore, repository, coverage_start: int | None):
        self.store, self.repository, self.coverage_start = store, repository, coverage_start
        self.clock = time.time

    def _pending(self, db, principal: Principal, handle: str, *, require_fresh: bool = True):
        if not isinstance(handle, str) or not 32 <= len(handle) <= 64:
            raise BankError("reference_unavailable")
        row = db.execute("""SELECT binding,customer,transaction_id,snapshot,action,decision,reason,facts,expires
            FROM action_pending WHERE id=?""", (_digest(handle),)).fetchone()
        if (not row or (require_fresh and row[8] <= self.clock()) or row[1] != principal.customer
                or not secrets.compare_digest(row[0], principal.binding())):
            raise BankError("reference_unavailable")
        return row

    def _coverage(self, now: int) -> bool:
        return self.coverage_start is not None and self.coverage_start <= now - 86400

    def prepare(self, principal: Principal, transaction_id: str, build: str) -> dict:
        snapshot, row = self.repository.owned_transaction_id(principal, transaction_id, build)
        facts = self.repository._visible(row, snapshot)
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
            covered = self._coverage(now)
            age = (datetime.fromtimestamp(now, timezone.utc).date() - row["transaction_date"].date()).days
            reason = ("duplicate_review" if duplicate else "missing_evidence" if not covered
                      else "high_risk" if count >= 3
                      else "out_of_policy" if age < 0 or age > 120
                      or str(row["transaction_status"]).lower() != "approved" else None)
            decision = "handoff" if reason else "intake"
            db.execute("""INSERT INTO action_pending
                VALUES (?,?,?,?,?,?,?,?,?,?)""", (_digest(handle), principal.binding(),
                principal.customer, transaction_id, snapshot.id, ACTION, decision, reason,
                json.dumps(facts), now + PENDING_SECONDS))
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
        now = self.clock()
        with self.store.connect() as db:
            pending = self._pending(db, principal, pending_handle)
            existing = db.execute("""SELECT id FROM sandbox_cases WHERE
                customer=? AND transaction_id=? AND action=?""",
                (principal.customer, pending[2], ACTION)).fetchone()
            if not existing:
                prior = db.execute("""SELECT count(DISTINCT transaction_id) FROM sandbox_cases
                    WHERE customer=? AND action=? AND transaction_id<>?
                      AND created_at>=? AND created_at<?""",
                    (principal.customer, ACTION, pending[2], now - 86400, now)).fetchone()[0]
                if not self._coverage(now):
                    raise BankError("risk_data_unavailable")
                if prior + 1 >= 3:
                    raise BankError("handoff_required")
                db.execute("""INSERT OR IGNORE INTO sandbox_cases
                    VALUES (?,?,?,?,?,?,?)""", (_receipt_id("CMP-SBX-"),
                    principal.customer, pending[2], ACTION, pending[3], now, pending[7]))
        # A separate durable read determines the claim after uncertain write paths.
        return self.receipt(principal, pending_handle)

    def handoff(self, principal: Principal, reason: str, pending_handle: str | None) -> dict:
        if reason not in HANDOFF_REASONS:
            raise BankError("invalid_arguments")
        with self.store.connect() as db:
            pending = self._pending(db, principal, pending_handle, require_fresh=False) if pending_handle else None
            transaction_id = pending[2] if pending else None
            snapshot = pending[3] if pending else None
            facts = pending[7] if pending else "{}"
            key = _digest(json.dumps([principal.binding(), transaction_id, snapshot, reason]))
            db.execute("""INSERT OR IGNORE INTO sandbox_handoffs
                VALUES (?,?,?,?,?,?,?,?,?)""", (_receipt_id("HOF-"),
                principal.binding(), principal.customer, transaction_id, snapshot,
                reason, self.clock(), facts, key))
            row = db.execute("SELECT id FROM sandbox_handoffs WHERE idempotency_key=?", (key,)).fetchone()
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
