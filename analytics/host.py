"""Read-only current host snapshots, deliberately separate from workflow intent.

The frontend's owner/expiry-bound saved projection is the evidence source. This
does not call a host recovery endpoint, reread the bank, or infer a turn linkage.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from frontend.server.action import project_action_result


SCHEMA = """
CREATE TABLE IF NOT EXISTS host_sources (
    source_ref TEXT PRIMARY KEY, source TEXT NOT NULL, status TEXT NOT NULL,
    rejected_bindings INTEGER NOT NULL, invalid_sessions INTEGER NOT NULL,
    cancellation_status TEXT NOT NULL, revocation_status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS host_sessions (
    host_ref TEXT PRIMARY KEY, session_ref TEXT NOT NULL, customer_ref TEXT,
    expires_at TEXT NOT NULL, expired INTEGER NOT NULL, local_revoked INTEGER NOT NULL,
    revocation_state TEXT NOT NULL, revocation_updated_at TEXT
);
CREATE TABLE IF NOT EXISTS host_actions (
    host_ref TEXT PRIMARY KEY, outcome TEXT NOT NULL, updated_at TEXT,
    verified_record_created_at TEXT, retained_prior_receipt INTEGER NOT NULL,
    retained_prior_handoff INTEGER NOT NULL, recovery_attempts INTEGER,
    recovery_deadline TEXT, recovery_exhausted INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS host_cancellations (
    cancellation_ref TEXT PRIMARY KEY, host_ref TEXT NOT NULL, cancelled_at TEXT NOT NULL
);
"""

_STATES = frozenset({"none", "preparing", "prepare_unverified", "pending_confirmation",
                    "intake_verified", "existing_case_verified", "handoff_verified",
                    "handoff_unverified", "action_unverified"})
_VERIFIED = {"intake_verified": "verified_simulated_intake",
             "existing_case_verified": "verified_existing_simulated_intake",
             "handoff_verified": "verified_handoff_request"}
_ACTION_FINGERPRINT_FIELDS = ("session_id", "owner", "expires", "result_json", "updated_at",
    "target_reference", "action_id", "revision", "prepare_recovery_attempts", "prepare_recovery_deadline",
    "query_scope_id", "action_conversation_id", "query_snapshot_hash")


def _columns(db, table):
    # Every table name supplied here is a fixed constant.
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def _stamp(value, *, now):
    if type(value) not in (int, float):
        return None
    try:
        if not 0 <= value <= now.timestamp() + 5:
            return None
        return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError):
        return None


def _expiry(value):
    if type(value) is not int or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError):
        return None


def _created(value, updated):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        limit = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        if parsed.utcoffset() is not None and 0 <= parsed.timestamp() <= limit.timestamp() + 5:
            return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, TypeError, AttributeError):
        pass
    return None


def _identity(row):
    if (any(not isinstance(row[key], str) or not row[key] for key in ("session_id", "owner", "customer_id"))
            or _expiry(row["expires"]) is None or type(row["revoked"]) is not int or row["revoked"] not in (0, 1)):
        return None
    return json.dumps([row["owner"], row["session_id"], row["expires"]], separators=(",", ":"))


def _bound(row, session):
    return bool(session and _expiry(row["expires"]) and row["owner"] == session["owner"]
                and row["expires"] == session["expires"])


def _fingerprint(values):
    # SQLite can retain BLOBs in old or malformed columns. Keep their digest in
    # memory without allowing a non-JSON value to abort unrelated observations.
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"),
                         default=lambda value: {"blob_sha256": hashlib.sha256(value).hexdigest()})
    return hashlib.sha256(encoded.encode()).hexdigest()


def _action(row, now):
    updated = _stamp(row["updated_at"], now=now)
    record = {"outcome": "invalid_evidence", "updated_at": updated,
              "verified_record_created_at": None, "retained_prior_receipt": 0,
              "retained_prior_handoff": 0, "recovery_attempts": None,
              "recovery_deadline": None, "recovery_exhausted": 0}
    try:
        raw = json.loads(row["result_json"])
        if not isinstance(raw, dict) or raw.get("state") not in _STATES or updated is None:
            return record
        if row["target_reference"] is not None and (not isinstance(row["target_reference"], str)
                or not re.fullmatch(r"txn_[a-f0-9]{24}", row["target_reference"])):
            return record
        # Apply the same authoritative row target override as the host reader.
        if row["target_reference"]:
            raw["target_reference"] = row["target_reference"]
        else:
            raw.pop("target_reference", None)
        projected = project_action_result(raw)
        state = projected["state"]
        if state != raw["state"]:
            return record
        packet = projected.get("handoff")
        if state == "handoff_verified" and (row["target_reference"] is None
                and not projected.get("pending_handle") and packet["snapshot"] is not None):
            return record
        # Conflicting top-level facts cannot upgrade a saved verified claim.
        proof = projected.get("receipt") if state in {"intake_verified", "existing_case_verified"} else packet
        if state in _VERIFIED:
            created = _created(proof.get("created_at"), updated)
            if created is None:
                return record
            if "snapshot" in projected and state != "existing_case_verified" and projected["snapshot"] != proof["snapshot"]:
                return record
            facts = proof.get("transaction", proof.get("facts"))
            if "transaction" in projected and projected["transaction"] != facts:
                return record
            if state == "handoff_verified" and "reason" in projected and projected["reason"] != proof["reason"]:
                return record
            record["verified_record_created_at"] = created
        record.update(outcome=_VERIFIED.get(state, state),
                      retained_prior_receipt=int("prior_receipt" in projected),
                      retained_prior_handoff=int("prior_handoff" in projected),
                      recovery_exhausted=int(projected.get("recovery_exhausted") is True))
        attempts = row.get("prepare_recovery_attempts")
        record["recovery_attempts"] = attempts if type(attempts) is int and attempts >= 0 else None
        record["recovery_deadline"] = _expiry(row.get("prepare_recovery_deadline"))
        return record
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return record


def snapshots(paths, pseudonym, now):
    """Return allowlisted rows only; duplicate or disagreeing sources fail closed.

    A current action slot is keyed by immutable admission, not source file or
    action revision. Identical replay copies count once; disagreements are
    reported as conflicting snapshots instead of choosing the newest success.
    """
    sources, sessions, actions, cancellations = {}, {}, {}, {}
    for path in sorted({Path(path).resolve() for path in paths}):
        source_ref = pseudonym("host_source", str(path))
        coverage = {"source_ref": source_ref, "source": "frontend_action_status",
                    "status": "unsupported_schema", "rejected_bindings": 0, "invalid_sessions": 0,
                    "cancellation_status": "unavailable", "revocation_status": "unavailable"}
        sources[source_ref] = coverage
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")  # Consistent action/session/revocation/cancellation snapshot.
            session_columns = _columns(db, "chat_sessions")
            if not {"session_id", "owner", "expires", "customer_id", "revoked"} <= session_columns:
                continue
            outbox_columns = _columns(db, "pending_revocations")
            outbox_supported = {"session_id", "owner", "expires", "state", "updated_at"} <= outbox_columns
            coverage["revocation_status"] = "supported" if outbox_supported else "unavailable"
            admitted = {}
            for saved in db.execute("SELECT * FROM chat_sessions"):
                row = dict(saved)
                identity = _identity(row)
                if identity is None:
                    coverage["invalid_sessions"] += 1
                    continue
                host_ref = pseudonym("host_admission", identity)
                admitted[row["session_id"]] = (row, host_ref)
                record = {"host_ref": host_ref, "session_ref": pseudonym("session", row["session_id"]),
                          "customer_ref": pseudonym("customer", row["customer_id"]),
                          "expires_at": _expiry(row["expires"]), "expired": int(row["expires"] <= now.timestamp()),
                          "local_revoked": row["revoked"],
                          "revocation_state": "unresolved" if row["revoked"] else "not_requested",
                          "revocation_updated_at": None,
                          "_identity": _fingerprint([row.get(key) for key in ("customer_id", "subject", "ledger_generation")])}
                if outbox_supported:
                    outbox = db.execute("SELECT * FROM pending_revocations WHERE session_id=?", (row["session_id"],)).fetchone()
                    if outbox:
                        valid = (_bound(outbox, row) and row["revoked"] == 1
                                 and outbox["state"] in {"pending", "confirmed", "expired_unconfirmed"})
                        for key in ("subject", "ledger_generation"):
                            if key in outbox.keys():
                                valid = (valid and key in row and isinstance(row[key], str)
                                         and bool(row[key]) and outbox[key] == row[key])
                        stamp = _stamp(outbox["updated_at"], now=now)
                        record["revocation_state"] = outbox["state"] if valid and stamp else "invalid_binding"
                        record["revocation_updated_at"] = stamp if valid else None
                _merge(sessions, host_ref, record, "revocation_state")
            action_columns = _columns(db, "action_status")
            if not action_columns:
                coverage["status"] = "no_action_store"
            elif {"session_id", "owner", "expires", "result_json", "updated_at", "target_reference"} <= action_columns:
                coverage["status"] = "supported"
                for saved in db.execute("SELECT * FROM action_status"):
                    row = dict(saved)
                    admitted_row = admitted.get(row["session_id"])
                    if not admitted_row or not _bound(row, admitted_row[0]):
                        coverage["rejected_bindings"] += 1
                        continue
                    host_ref = admitted_row[1]
                    record = {"host_ref": host_ref, **_action(row, now)}
                    # The fingerprint is in memory only and catches private
                    # proof/target differences even when public categories agree.
                    record["_fingerprint"] = _fingerprint({key: row.get(key) for key in _ACTION_FINGERPRINT_FIELDS})
                    _merge(actions, host_ref, record, "outcome")
            cancelled_columns = _columns(db, "cancelled_action_handles")
            if {"session_id", "handle_hash", "owner", "expires", "cancelled_at"} <= cancelled_columns:
                coverage["cancellation_status"] = "supported"
                for saved in db.execute("SELECT * FROM cancelled_action_handles"):
                    row = dict(saved)
                    admitted_row = admitted.get(row["session_id"])
                    stamp = _stamp(row["cancelled_at"], now=now)
                    if (not admitted_row or not _bound(row, admitted_row[0]) or stamp is None
                            or not isinstance(row["handle_hash"], str) or not re.fullmatch(r"[a-f0-9]{64}", row["handle_hash"])):
                        coverage["rejected_bindings"] += 1
                        continue
                    host_ref = admitted_row[1]
                    reference = pseudonym("host_cancellation", host_ref + ":" + row["handle_hash"])
                    cancellations[reference] = {"cancellation_ref": reference, "host_ref": host_ref, "cancelled_at": stamp}
    # Identity disagreement between source copies never supplies completion.
    for host_ref, session in sessions.items():
        if session["revocation_state"] == "conflicting_snapshot" and host_ref in actions:
            _invalidate(actions[host_ref])
    return list(sources.values()), list(sessions.values()), list(actions.values()), list(cancellations.values())


def _merge(records, key, record, status):
    previous = records.get(key)
    if previous is None:
        records[key] = record
    elif previous != record:
        previous[status] = "conflicting_snapshot"
        if status == "outcome":
            _invalidate(previous)
        else:
            previous["customer_ref"] = None


def _invalidate(record):
    record.update(outcome="conflicting_snapshot", verified_record_created_at=None,
                  retained_prior_receipt=0, retained_prior_handoff=0, recovery_attempts=None,
                  recovery_deadline=None, recovery_exhausted=0)
