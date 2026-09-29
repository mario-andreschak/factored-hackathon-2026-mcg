"""Customer-bound frontend adapter for the deployed FLUJO banking ingress.

Credentials, dataset identities, assertions and upstream conversation IDs never
leave this server. The browser submits only a user message. The existing FLUJO
adapter independently pins the approved graph and enforces customer ownership.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import contextmanager
import math
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Iterator
from urllib.parse import urlsplit
import uuid

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


_CONVERSATION = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$")
_PUBLIC_TRANSACTION = re.compile(r"^txn_[a-f0-9]{24}$")
_PENDING_HANDLE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
_REQUEST_ID = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$")
_RECEIPT_ID = re.compile(r"^CMP-SBX-[A-Za-z0-9_-]{8}$")
_HANDOFF_ID = re.compile(r"^HOF-[A-Za-z0-9_-]{8}$")
_CUSTOMER_HANDOFF_REASONS = frozenset({"out_of_policy", "emergency", "customer_request",
                                       "clarification_exhausted"})
_RECOVERABLE_HANDOFF_REASONS = _CUSTOMER_HANDOFF_REASONS | {
    "high_risk", "missing_evidence", "duplicate_review", "action_unverified"}
_MAX_RESPONSE = 4 * 1024 * 1024
_MAX_HISTORY_BYTES = 256 * 1024
_TIMEOUT = 450
_REVOKE_TIMEOUT = 10
_REVOKE_LEASE = 15
_REVOKE_POLL = 2


class ChatError(Exception):
    """Public, fixed errors; upstream responses and credentials are never echoed."""

    def __init__(self, code: str, status_code: int, message: str):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.message = message


class ChatService:
    def __init__(self, config: dict[str, Any] | None, state_dir: Path):
        self._configured = False
        self._reason = "El asistente de FLUJO todavía no está conectado a esta demo."
        self._customer_subjects: dict[str, str] = {}
        self._action_enabled = False
        self._approved_subject_customers: dict[str, str] = {}
        self._approved_owner_subjects: dict[str, tuple[str, str]] = {}
        self._db_path = Path(state_dir) / "frontend-chat.sqlite3"
        # Injectable only by trusted server/test code, never request data.
        self._transport: httpx.AsyncBaseTransport | None = None
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires INTEGER NOT NULL,
                conversation_id TEXT, revoked INTEGER NOT NULL DEFAULT 0,
                active_id TEXT, active_until INTEGER NOT NULL DEFAULT 0,
                subject TEXT, customer_id TEXT
            )""")
            # Persist the approved admission identity, never credentials. An
            # existing volume gets the same columns without discarding history.
            columns = {row[1] for row in db.execute("PRAGMA table_info(chat_sessions)")}
            if "subject" not in columns:
                db.execute("ALTER TABLE chat_sessions ADD COLUMN subject TEXT")
            if "customer_id" not in columns:
                db.execute("ALTER TABLE chat_sessions ADD COLUMN customer_id TEXT")
            db.execute("""CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                operation TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                text TEXT NOT NULL, selection_json TEXT,
                UNIQUE(session_id, operation, role)
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS chat_messages_session ON chat_messages(session_id, id)")
            db.execute("""CREATE TABLE IF NOT EXISTS action_status (
                session_id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires INTEGER NOT NULL,
                result_json TEXT NOT NULL, updated_at INTEGER NOT NULL,
                action_id TEXT, target_reference TEXT, revision INTEGER NOT NULL DEFAULT 0
            )""")
            action_columns = {row[1] for row in db.execute("PRAGMA table_info(action_status)")}
            if "action_id" not in action_columns:
                db.execute("ALTER TABLE action_status ADD COLUMN action_id TEXT")
            if "target_reference" not in action_columns:
                db.execute("ALTER TABLE action_status ADD COLUMN target_reference TEXT")
            if "revision" not in action_columns:
                db.execute("ALTER TABLE action_status ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
            # Legacy status can still be recovered, but without a saved public
            # target it cannot authorize a new confirmation.
            db.execute("UPDATE action_status SET action_id=lower(hex(randomblob(16))) WHERE action_id IS NULL")
            db.execute("CREATE TABLE IF NOT EXISTS chat_migrations (name TEXT PRIMARY KEY)")
            db.execute("""CREATE TABLE IF NOT EXISTS pending_revocations (
                session_id TEXT PRIMARY KEY, owner TEXT NOT NULL, subject TEXT NOT NULL,
                expires INTEGER NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('pending','confirmed','expired_unconfirmed')),
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at INTEGER NOT NULL,
                lease_token TEXT, lease_until INTEGER NOT NULL DEFAULT 0,
                last_error_code TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS pending_revocations_due ON pending_revocations(state, next_attempt_at)")
            if not db.execute("SELECT 1 FROM chat_migrations WHERE name='public-transcript-v1'").fetchone():
                # An earlier frontend retained private worker context without a
                # displayable transcript. Start those sessions afresh once so a
                # restored welcome screen cannot conceal previous model context.
                db.execute("""UPDATE chat_sessions SET conversation_id=NULL, active_id=NULL, active_until=0
                    WHERE NOT EXISTS (SELECT 1 FROM chat_messages m WHERE m.session_id=chat_sessions.session_id)""")
                db.execute("INSERT INTO chat_migrations VALUES ('public-transcript-v1')")
        # Persisted admission tuples can be queued even if the signer config
        # is temporarily absent. The configured pass also recovers old rows.
        self._migrate_legacy_revocations()
        if not config:
            return
        try:
            self._configure(config)
        except (ValueError, TypeError, KeyError, OSError):
            self._reason = "La conexión segura del asistente requiere configuración."
            return
        self._configured = True
        self._migrate_legacy_revocations()

    def _configure(self, config: dict[str, Any]) -> None:
        if not isinstance(config, dict) or not isinstance(config.get("base_url"), str):
            raise ValueError("Invalid ingress configuration")
        self._base_url = config["base_url"].rstrip("/")
        endpoint = urlsplit(self._base_url)
        if (endpoint.scheme not in {"https", "http"} or not endpoint.hostname
                or endpoint.username or endpoint.password or endpoint.query
                or endpoint.fragment or endpoint.path not in {"", "/"}
                or (endpoint.scheme == "http" and endpoint.hostname not in
                    {"flujo", "localhost", "127.0.0.1", "::1", "host.docker.internal"})):
            raise ValueError("Private service URL required")
        self._model = config["model"]
        if not isinstance(config.get("action_enabled", False), bool):
            raise ValueError("Invalid action configuration")
        self._action_enabled = config.get("action_enabled", False)
        self._execution_token = config["execution_token"]
        self._issuer = config["frontend_issuer"]
        self._kid = config["frontend_kid"]
        if (not isinstance(self._model, str) or not self._model.startswith("flow-")
                or not 6 <= len(self._model) <= 256
                or not isinstance(self._execution_token, str)
                or not 16 <= len(self._execution_token) <= 4096
                or any(char.isspace() for char in self._execution_token)
                or not all(isinstance(value, str) and 1 <= len(value) <= 128
                           for value in [self._issuer, self._kid])
                or config["frontend_audience"] != "flujo-banking-ingress"):
            raise ValueError("Invalid ingress configuration")
        key_file = Path(config["frontend_signing_key_file"])
        if not key_file.is_absolute():
            raise ValueError("Absolute signer path required")
        key = serialization.load_pem_private_key(key_file.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("Ed25519 signer required")
        self._key = key
        mappings = config["principal_customers"]
        if not isinstance(mappings, dict) or not mappings or len(mappings) > 1000:
            raise ValueError("Approved principal mapping required")
        for subject, customer in mappings.items():
            if not all(isinstance(value, str) and 1 <= len(value) <= 128
                       for value in [subject, customer]):
                raise ValueError("Invalid principal mapping")
            # The deployed bank may have multiple preapproved subjects for one
            # customer. A fixed first subject is used for the life of this config.
            self._approved_subject_customers[subject] = customer
            self._approved_owner_subjects[self._owner_for_subject(subject)] = (subject, customer)
            self._customer_subjects.setdefault(customer, subject)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self._db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = 10000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def status(self, customer_id: str) -> dict[str, Any]:
        available = self._configured and customer_id in self._customer_subjects
        return {"available": available, "mode": "flujo" if available else "unavailable",
                "read_only": not (available and self._action_enabled),
                "sandbox_intake_available": available and self._action_enabled,
                **({} if available else {"reason": self._reason if not self._configured
                    else "El asistente no está habilitado para este perfil de demostración."})}

    def has_active_session(self, session_id: str, session_exp: int) -> bool:
        """Use before policy rotation to avoid revoking sessions with no chat work."""
        with self._connection() as db:
            row = db.execute("SELECT expires,revoked FROM chat_sessions WHERE session_id=?",
                             (session_id,)).fetchone()
        return bool(row and row["expires"] == session_exp and not row["revoked"])

    def has_any_session(self) -> bool:
        """Reject reuse of a real chat volume for a synthetic invite preview."""
        with self._connection() as db:
            return db.execute("SELECT 1 FROM chat_sessions LIMIT 1").fetchone() is not None

    def admitted_customer(self, session_id: str, session_exp: int) -> str | None:
        """Return only the private customer bound at admission, for rotation."""
        with self._connection() as db:
            row = db.execute("""SELECT expires,revoked,customer_id FROM chat_sessions
                WHERE session_id=?""", (session_id,)).fetchone()
        if row and row["expires"] == session_exp and not row["revoked"]:
            return row["customer_id"]
        return None

    def history(self, customer_id: str, session_id: str, session_exp: int) -> dict[str, Any]:
        if not self.status(customer_id)["available"]:
            return {"available": False, "messages": [], "active": False}
        _, owner = self._identity(customer_id, session_id, session_exp)
        with self._connection() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT * FROM chat_sessions WHERE session_id=?", (session_id,)).fetchone()
            if row is None:
                return {"available": True, "messages": [], "active": False}
            if row["owner"] != owner or row["expires"] != session_exp:
                raise ChatError("session_mismatch", 401, "La sesión del asistente no está disponible.")
            if row["revoked"]:
                raise ChatError("session_expired", 401, "Tu sesión expiró. Vuelve a ingresar.")
            stored = db.execute("SELECT role,text,selection_json FROM chat_messages WHERE session_id=? ORDER BY id DESC LIMIT 100",
                                (session_id,)).fetchall()
            messages = [{"role": entry["role"], "text": entry["text"],
                         **({"selection": json.loads(entry["selection_json"])} if entry["selection_json"] else {})}
                        for entry in reversed(stored)]
            size = sum(len(json.dumps(message, ensure_ascii=False).encode("utf-8")) for message in messages)
            limited = len(stored) == 100
            while size > _MAX_HISTORY_BYTES and len(messages) > 2:
                # Keep complete recent exchanges. Every stored pair is atomic.
                removed = messages[:2]
                messages = messages[2:]
                size -= sum(len(json.dumps(message, ensure_ascii=False).encode("utf-8")) for message in removed)
                limited = True
            now = int(time.time())
            if session_exp <= now:
                raise ChatError("session_expired", 401, "Tu sesión expiró. Vuelve a ingresar.")
            return {"available": True, "messages": messages,
                    "active": bool(row["active_id"] and row["active_until"] > now),
                    "limited": limited}

    @staticmethod
    def _action_row(db: sqlite3.Connection, session_id: str, owner: str,
                    session_exp: int) -> sqlite3.Row | None:
        row = db.execute("SELECT * FROM action_status WHERE session_id=?", (session_id,)).fetchone()
        if row and (row["owner"] != owner or row["expires"] != session_exp):
            raise ChatError("session_mismatch", 401, "La sesión del asistente no está disponible.")
        return row

    @staticmethod
    def _action_result(row: sqlite3.Row) -> dict[str, Any]:
        result = json.loads(row["result_json"])
        if not isinstance(result, dict):
            raise ChatError("action_invalid_state", 503, "No se pudo verificar la recepción simulada.")
        if row["target_reference"]:
            result["target_reference"] = row["target_reference"]
        return result

    @staticmethod
    def _verified_terminal(result: dict[str, Any]) -> bool:
        if result.get("state") == "intake_verified":
            receipt = result.get("receipt")
            return (isinstance(receipt, dict) and isinstance(receipt.get("id"), str)
                    and bool(_RECEIPT_ID.fullmatch(receipt["id"])))
        if result.get("state") == "handoff_verified":
            handoff = result.get("handoff")
            return (isinstance(handoff, dict) and isinstance(handoff.get("id"), str)
                    and bool(_HANDOFF_ID.fullmatch(handoff["id"])))
        return False

    @staticmethod
    def _assert_action_session(db: sqlite3.Connection, session_id: str,
                               owner: str, session_exp: int) -> None:
        session = db.execute("SELECT owner,expires,revoked FROM chat_sessions WHERE session_id=?",
                             (session_id,)).fetchone()
        if (not session or session["owner"] != owner or session["expires"] != session_exp
                or session["revoked"] or session_exp <= int(time.time())):
            raise ChatError("session_expired", 401, "Tu sesión expiró. Vuelve a ingresar.")

    def _reserve_action(self, session_id: str, owner: str, session_exp: int,
                        target_reference: str | None, initial: dict[str, Any]
                        ) -> tuple[str, int, sqlite3.Row | None]:
        now = int(time.time())
        action_id = str(uuid.uuid4())
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._assert_action_session(db, session_id, owner, session_exp)
            row = self._action_row(db, session_id, owner, session_exp)
            if row and not self._verified_terminal(self._action_result(row)):
                raise ChatError("action_in_progress", 409,
                                "Primero resuelve o revisa la solicitud anterior con Savia.")
            revision = row["revision"] + 1 if row else 1
            result = dict(initial)
            if target_reference:
                result["target_reference"] = target_reference
            db.execute("""INSERT INTO action_status
                (session_id,owner,expires,result_json,updated_at,action_id,target_reference,revision)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET
                result_json=excluded.result_json,updated_at=excluded.updated_at,
                action_id=excluded.action_id,target_reference=excluded.target_reference,
                revision=excluded.revision""",
                (session_id, owner, session_exp, json.dumps(result), now, action_id,
                 target_reference, revision))
        return action_id, revision, row

    def _rollback_unadmitted_action(self, session_id: str, owner: str, session_exp: int,
                                    action_id: str, revision: int,
                                    previous: sqlite3.Row | None) -> None:
        """A definitive pre-admission 429 can restore the prior visible state.

        The revision stays monotonic so a late observer of the old state cannot
        write through the rollback. Ambiguous transport failures never call it.
        """
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._assert_action_session(db, session_id, owner, session_exp)
            current = self._action_row(db, session_id, owner, session_exp)
            if not current or current["action_id"] != action_id or current["revision"] != revision:
                raise ChatError("action_changed", 409,
                                "La solicitud cambió. Actualiza su estado antes de continuar.")
            if previous is None:
                db.execute("DELETE FROM action_status WHERE session_id=?", (session_id,))
            else:
                db.execute("""UPDATE action_status SET result_json=?,updated_at=?,action_id=?,
                    target_reference=?,revision=? WHERE session_id=?""",
                    (previous["result_json"], int(time.time()), previous["action_id"],
                     previous["target_reference"], revision + 1, session_id))

    def _advance_action(self, session_id: str, owner: str, session_exp: int,
                        action_id: str, revision: int, result: dict[str, Any]) -> tuple[dict[str, Any], int]:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._assert_action_session(db, session_id, owner, session_exp)
            row = self._action_row(db, session_id, owner, session_exp)
            if not row or row["action_id"] != action_id or row["revision"] != revision:
                raise ChatError("action_changed", 409,
                                "La solicitud cambió. Actualiza su estado antes de continuar.")
            saved = dict(result)
            if row["target_reference"]:
                saved["target_reference"] = row["target_reference"]
            db.execute("""UPDATE action_status SET result_json=?,updated_at=?,revision=?
                WHERE session_id=? AND action_id=? AND revision=?""",
                (json.dumps(saved), int(time.time()), revision + 1,
                 session_id, action_id, revision))
        return saved, revision + 1

    def _current_action(self, session_id: str, owner: str,
                        session_exp: int) -> tuple[sqlite3.Row | None, dict[str, Any] | None]:
        with self._connection() as db:
            self._assert_action_session(db, session_id, owner, session_exp)
            row = self._action_row(db, session_id, owner, session_exp)
        return row, self._action_result(row) if row else None

    async def action(self, customer_id: str, session_id: str, session_exp: int,
                     operation: dict[str, Any], *, target_reference: str | None = None) -> dict[str, Any]:
        """A trusted frontend control, separate from model text and tool arguments."""
        if not self._action_enabled:
            raise ChatError("action_unavailable", 503, "La recepción simulada no está habilitada.")
        kind = operation.get("operation")
        if kind not in {"prepare", "confirm", "handoff"}:
            raise ChatError("invalid_action", 400, "La solicitud no está disponible.")
        operation = dict(operation)
        supplied_request_id = operation.get("requestId")
        if supplied_request_id is not None and (not isinstance(supplied_request_id, str)
                or not _REQUEST_ID.fullmatch(supplied_request_id)):
            raise ChatError("invalid_action", 400, "La solicitud no está disponible.")
        if kind == "prepare":
            # FLUJO forwards this to its policy-triggered handoff. Persist it
            # before the call so a lost HOF response can reuse the same key.
            operation.setdefault("requestId", str(uuid.uuid4()))
        if kind == "handoff" and operation.get("reason") not in _RECOVERABLE_HANDOFF_REASONS:
            raise ChatError("invalid_action", 400, "La solicitud no está disponible.")
        handle = operation.get("pendingHandle")
        if kind in {"prepare", "confirm"} or handle:
            if not isinstance(target_reference, str) or not _PUBLIC_TRANSACTION.fullmatch(target_reference):
                raise ChatError("action_target_required", 409,
                                "Selecciona el mismo movimiento antes de continuar.")
        subject, owner = self._identity(customer_id, session_id, session_exp)
        with self._connection() as db:
            row = self._bind(db, session_id, owner, session_exp)
            if row["revoked"]:
                raise ChatError("session_expired", 401, "Tu sesión expiró. Vuelve a ingresar.")
            conversation = row["conversation_id"]
            if row["active_until"] > int(time.time()):
                raise ChatError("chat_busy", 429, "Espera la respuesta de tu consulta anterior.")
        if not isinstance(conversation, str) or not _CONVERSATION.fullmatch(conversation):
            raise ChatError("inquiry_required", 409,
                            "Primero consulta el movimiento con Savia para iniciar una conversación segura.")
        action_id: str | None = None
        revision: int | None = None
        previous: sqlite3.Row | None = None
        confirm_handoff_retry = False
        if kind == "prepare":
            action_id, revision, previous = self._reserve_action(session_id, owner, session_exp,
                target_reference, {"state": "preparing", "request_id": operation["requestId"]})
        elif kind == "confirm" or handle:
            if not isinstance(handle, str) or not _PENDING_HANDLE.fullmatch(handle):
                raise ChatError("action_mismatch", 409, "La solicitud no corresponde al movimiento seleccionado.")
            current, saved = self._current_action(session_id, owner, session_exp)
            if (not current or current["target_reference"] != target_reference
                    or saved.get("pending_handle") != handle):
                raise ChatError("action_mismatch", 409, "La solicitud no corresponde al movimiento seleccionado.")
            if kind == "confirm" and saved.get("state") == "intake_verified" and self._verified_terminal(saved):
                return saved
            if kind == "handoff" and saved.get("state") == "handoff_verified" and self._verified_terminal(saved):
                return saved
            retry = kind == "handoff" and (
                saved.get("state") == "handoff_unverified" or
                (saved.get("state") == "action_unverified" and
                 isinstance(saved.get("handoff"), dict) and
                 saved["handoff"].get("state") == "handoff_unverified" and
                 operation.get("reason") == "action_unverified"))
            if retry:
                if (saved.get("reason") or "action_unverified") != operation.get("reason"):
                    raise ChatError("action_mismatch", 409,
                                    "La solicitud no corresponde al movimiento seleccionado.")
                saved_request_id = saved.get("request_id")
                if supplied_request_id is not None and supplied_request_id != saved_request_id:
                    raise ChatError("action_mismatch", 409,
                                    "La solicitud no corresponde al movimiento seleccionado.")
                if saved_request_id:
                    operation["requestId"] = saved_request_id
                else:
                    operation.pop("requestId", None)
                confirm_handoff_retry = saved.get("state") == "action_unverified"
            elif kind == "handoff":
                if saved.get("state") == "action_unverified":
                    # A lost confirm response might hide a policy-created HOF.
                    # Without its reason we cannot choose a safe idempotency key.
                    raise ChatError("action_in_progress", 409,
                                    "Primero revisa el estado de la solicitud anterior.")
                if operation["reason"] not in _CUSTOMER_HANDOFF_REASONS:
                    raise ChatError("action_mismatch", 409,
                                    "La solicitud no corresponde al movimiento seleccionado.")
                operation.setdefault("requestId", str(uuid.uuid4()))
            allowed = ({"pending_confirmation"} if kind == "confirm" else
                       {"pending_confirmation", "action_unverified", "handoff_unverified"})
            if saved.get("state") not in allowed:
                raise ChatError("action_in_progress", 409,
                                "Primero revisa el estado de la solicitud anterior.")
            action_id, revision = current["action_id"], current["revision"]
            previous = current
            uncertain = {"state": "action_unverified" if kind == "confirm" or confirm_handoff_retry
                         else "handoff_unverified",
                         "pending_handle": handle}
            if confirm_handoff_retry:
                uncertain["handoff"] = {"state": "handoff_unverified"}
            if request_id := operation.get("requestId"):
                uncertain["request_id"] = request_id
            if reason := operation.get("reason"):
                uncertain["reason"] = reason
            _, revision = self._advance_action(session_id, owner, session_exp,
                                               action_id, revision, uncertain)
        else:
            # A general handoff has no transaction target or pending handle,
            # but still needs an identity before the upstream write begins.
            current, saved = self._current_action(session_id, owner, session_exp)
            if (current and saved.get("state") == "handoff_unverified"
                    and not saved.get("pending_handle")
                    and current["target_reference"] is None
                    and saved.get("reason") == operation["reason"]
                    and saved.get("request_id") == supplied_request_id):
                action_id, revision = current["action_id"], current["revision"]
                previous = current
                _, revision = self._advance_action(session_id, owner, session_exp,
                    action_id, revision, {"state": "handoff_unverified",
                                          "reason": operation["reason"],
                                          "request_id": supplied_request_id})
            else:
                if operation["reason"] not in _CUSTOMER_HANDOFF_REASONS:
                    raise ChatError("action_mismatch", 409,
                                    "La solicitud no corresponde a una revisión pendiente.")
                operation.setdefault("requestId", str(uuid.uuid4()))
                initial = {"state": "handoff_unverified",
                           "request_id": operation["requestId"], "reason": operation["reason"]}
                action_id, revision, previous = self._reserve_action(session_id, owner,
                                                                       session_exp, None, initial)

        payload = {"conversationId": conversation, **operation}

        def finish(result: dict[str, Any]) -> dict[str, Any]:
            nonlocal revision
            saved = ({"state": "action_unverified", "reason": "action_unverified",
                      "handoff": result} if confirm_handoff_retry else dict(result))
            if handle:
                saved.setdefault("pending_handle", handle)
            if request_id := operation.get("requestId"):
                saved.setdefault("request_id", request_id)
            if reason := operation.get("reason"):
                saved.setdefault("reason", reason)
            if action_id is not None and revision is not None:
                saved, revision = self._advance_action(session_id, owner, session_exp,
                                                       action_id, revision, saved)
            return saved
        try:
            result = await self._post("/v1/banking/action", self._headers(subject, session_id, session_exp),
                                      payload, timeout_seconds=45)
            if kind == "prepare":
                if self._verified_terminal(result) and result.get("state") == "handoff_verified":
                    return finish(result)
                if (result.get("state") == "handoff_unverified"
                        and result.get("reason") in _RECOVERABLE_HANDOFF_REASONS
                        and isinstance(result.get("pending_handle"), str)
                        and _PENDING_HANDLE.fullmatch(result["pending_handle"])):
                    return finish(result)
                if (result.get("state") != "pending_confirmation" or
                        not isinstance(result.get("pending_handle"), str) or
                        not _PENDING_HANDLE.fullmatch(result["pending_handle"])):
                    return finish({"state": "prepare_unverified"})
            if kind == "confirm" and result.get("state") == "handoff_unverified" and (
                    result.get("reason") in {"high_risk", "missing_evidence", "action_unverified"}):
                return finish(result)
            if kind == "confirm" and result.get("state") == "action_unverified" and (
                    isinstance(result.get("handoff"), dict)):
                return finish({**result, "reason": "action_unverified"})
            if kind == "confirm" and not self._verified_terminal(result):
                return finish({"state": "action_unverified"})
            if kind == "handoff" and result.get("state") != "handoff_unverified" and not self._verified_terminal(result):
                return finish({"state": "handoff_unverified"})
            return finish(result)
        except ChatError as exc:
            if exc.code == "chat_busy" and action_id is not None and revision is not None:
                self._rollback_unadmitted_action(session_id, owner, session_exp,
                                                  action_id, revision, previous)
                raise
            if kind == "prepare" and exc.code in {
                    "chat_timeout", "chat_unreachable", "chat_upstream_failed"}:
                return finish({"state": "prepare_unverified"})
            if kind == "handoff" and exc.code in {
                    "chat_timeout", "chat_unreachable", "chat_upstream_failed"}:
                try:
                    retry = await self._post("/v1/banking/action", self._headers(subject, session_id, session_exp),
                                             payload, timeout_seconds=20)
                except ChatError as retry_error:
                    if retry_error.code not in {"chat_timeout", "chat_unreachable", "chat_upstream_failed"}:
                        raise
                    return finish({"state": "handoff_unverified"})
                if retry.get("state") != "handoff_unverified" and not self._verified_terminal(retry):
                    return finish({"state": "handoff_unverified"})
                return finish(retry)
            if kind != "confirm" or exc.code not in {
                    "chat_timeout", "chat_unreachable", "chat_upstream_failed"}:
                raise
            # The write may have committed before its response was lost. Read
            # the same pending identity; never issue a second confirm.
            try:
                receipt = await self._post("/v1/banking/action", self._headers(subject, session_id, session_exp),
                    {"conversationId": conversation, "operation": "receipt",
                     "pendingHandle": handle}, timeout_seconds=20)
            except ChatError as receipt_error:
                if receipt_error.code not in {"chat_timeout", "chat_unreachable", "chat_upstream_failed"}:
                    raise
                return finish({"state": "action_unverified"})
            if receipt.get("state") == "intake_verified" and self._verified_terminal(receipt):
                return finish(receipt)
            # Receipt absence does not identify whether FLUJO made a policy
            # handoff under another reason before the response was lost.
            return finish({"state": "action_unverified"})

    def _remember_action(self, session_id: str, owner: str, session_exp: int,
                         result: dict[str, Any]) -> None:
        # Legacy test/migration helper: even direct local recovery updates must
        # obey the current action identity and revision.
        row, _ = self._current_action(session_id, owner, session_exp)
        if not row:
            raise ChatError("action_invalid_state", 503, "No se pudo verificar la recepción simulada.")
        self._advance_action(session_id, owner, session_exp, row["action_id"], row["revision"], result)

    async def action_status(self, customer_id: str, session_id: str, session_exp: int) -> dict[str, Any]:
        if not self._action_enabled:
            raise ChatError("action_unavailable", 503, "La recepción simulada no está habilitada.")
        subject, owner = self._identity(customer_id, session_id, session_exp)
        with self._connection() as db:
            session = db.execute("SELECT owner,expires,revoked,conversation_id FROM chat_sessions WHERE session_id=?",
                                 (session_id,)).fetchone()
        if (not session or session["owner"] != owner or session["expires"] != session_exp
                or session["revoked"]):
            raise ChatError("session_mismatch", 401, "La sesión del asistente no está disponible.")
        row, saved = self._current_action(session_id, owner, session_exp)
        if not row:
            return {"state": "none"}
        if saved.get("state") == "action_unverified" and isinstance(saved.get("pending_handle"), str):
            try:
                receipt = await self._post("/v1/banking/action", self._headers(subject, session_id, session_exp),
                    {"conversationId": session["conversation_id"], "operation": "receipt",
                     "pendingHandle": saved["pending_handle"]}, timeout_seconds=20)
            except ChatError as exc:
                # A lost receipt response leaves the durable uncertain state.
                # Local ownership/revocation errors must still propagate.
                if exc.code not in {"chat_timeout", "chat_unreachable", "chat_upstream_failed"}:
                    raise
            else:
                if self._verified_terminal(receipt) and receipt.get("state") == "intake_verified":
                    try:
                        recovered, _ = self._advance_action(session_id, owner, session_exp,
                            row["action_id"], row["revision"],
                            {**receipt, "pending_handle": saved["pending_handle"]})
                        return recovered
                    except ChatError as changed:
                        if changed.code != "action_changed":
                            raise
                        # A later status may have recovered A and allowed B to
                        # start. Return the current slot, never overwrite B.
        _, latest = self._current_action(session_id, owner, session_exp)
        return latest if latest else {"state": "none"}

    @staticmethod
    def _validate_session(session_id: str, session_exp: int) -> None:
        now = int(time.time())
        if (not isinstance(session_id, str) or not 16 <= len(session_id) <= 128
                or not isinstance(session_exp, int) or isinstance(session_exp, bool)
                or session_exp <= now or session_exp > now + 8 * 3600):
            raise ChatError("session_expired", 401, "Tu sesión expiró. Vuelve a ingresar.")

    def _identity(self, customer_id: str, session_id: str, session_exp: int) -> tuple[str, str]:
        if not self.status(customer_id)["available"]:
            raise ChatError("chat_unavailable", 503, self.status(customer_id)["reason"])
        self._validate_session(session_id, session_exp)
        subject = self._customer_subjects[customer_id]
        # Preserve a previously bound subject when an approved mapping changes
        # order across a restart. The later _bind check still enforces the
        # immutable session owner and expiry under the write transaction.
        with self._connection() as db:
            bound = db.execute("SELECT owner FROM chat_sessions WHERE session_id=?", (session_id,)).fetchone()
        if bound:
            approved = self._approved_owner_subjects.get(bound["owner"])
            if approved and approved[1] == customer_id:
                subject = approved[0]
        return subject, self._owner_for_subject(subject)

    def _revoke_identity(self, customer_id: str, session_id: str,
                         session_exp: int) -> tuple[str, str] | None:
        """Recover the immutable admission identity during signer config loss."""
        self._validate_session(session_id, session_exp)
        with self._connection() as db:
            row = db.execute("SELECT owner,expires,subject,customer_id FROM chat_sessions WHERE session_id=?",
                             (session_id,)).fetchone()
        if row:
            if row["expires"] != session_exp or (row["customer_id"] and row["customer_id"] != customer_id):
                raise ChatError("session_mismatch", 401, "La sesión del asistente no está disponible.")
            if row["subject"] and row["customer_id"] == customer_id:
                return row["subject"], row["owner"]
            approved = self._approved_owner_subjects.get(row["owner"])
            if approved and approved[1] == customer_id:
                return approved[0], row["owner"]
            return None
        if self.status(customer_id)["available"]:
            return self._identity(customer_id, session_id, session_exp)
        return None

    def _owner_for_subject(self, subject: str) -> str:
        return hashlib.sha256(json.dumps([self._issuer, subject, self._model],
                                         separators=(",", ":")).encode()).hexdigest()

    def _migrate_legacy_revocations(self) -> None:
        """Queue older local revoke markers without inventing a subject.

        Retrying an already applied revoke is safe under the worker's idempotent
        contract. Historic owner-only rows require a current approved mapping.
        """
        now = int(time.time())
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("""SELECT session_id,owner FROM chat_sessions
                WHERE subject IS NULL AND customer_id IS NULL""").fetchall()
            for row in rows:
                approved = self._approved_owner_subjects.get(row["owner"])
                if approved:
                    db.execute("""UPDATE chat_sessions SET subject=?,customer_id=?
                        WHERE session_id=? AND subject IS NULL AND customer_id IS NULL""",
                        (approved[0], approved[1], row["session_id"]))
            rows = db.execute("""SELECT s.session_id,s.owner,s.expires,s.subject,s.customer_id FROM chat_sessions s
                WHERE s.revoked=1 AND s.expires>? AND NOT EXISTS
                (SELECT 1 FROM pending_revocations p WHERE p.session_id=s.session_id)""",
                (now,)).fetchall()
            for row in rows:
                approved = self._approved_owner_subjects.get(row["owner"])
                subject = (row["subject"] if row["subject"] and row["customer_id"] else
                           approved[0] if approved else None)
                if subject:
                    db.execute("""INSERT OR IGNORE INTO pending_revocations
                        (session_id,owner,subject,expires,state,next_attempt_at,created_at,updated_at)
                        VALUES (?,?,?,?,'pending',?,?,?)""",
                        (row["session_id"], row["owner"], subject, row["expires"], now, now, now))

    def _bind(self, db: sqlite3.Connection, session_id: str, owner: str, session_exp: int) -> sqlite3.Row:
        db.execute("INSERT OR IGNORE INTO chat_sessions(session_id, owner, expires) VALUES (?, ?, ?)",
                   (session_id, owner, session_exp))
        row = db.execute("SELECT * FROM chat_sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row is None or row["owner"] != owner or row["expires"] != session_exp:
            raise ChatError("session_mismatch", 401, "La sesión del asistente no está disponible.")
        return row

    def _headers(self, subject: str, session_id: str, session_exp: int) -> dict[str, str]:
        now = int(time.time())
        assertion = jwt.encode({"iss": self._issuer, "aud": "flujo-banking-ingress",
            "sub": subject, "session_id": session_id, "session_exp": session_exp,
            "iat": now, "nbf": now, "exp": min(now + 120, session_exp),
            "jti": str(uuid.uuid4()), "scope": ["bank:read"]}, self._key, algorithm="EdDSA",
            headers={"kid": self._kid, "typ": "flujo-ingress+jwt"})
        return {"Content-Type": "application/json", "Authorization": "Bearer " + self._execution_token,
                "X-Flujo-User-Assertion": assertion}

    async def _post(self, path: str, headers: dict[str, str], payload: dict[str, Any],
                    timeout_seconds: float = _TIMEOUT) -> dict[str, Any]:
        try:
            # HTTPX's read timeout applies to each chunk. A total deadline also
            # bounds a slow response stream and the complete logout request.
            async with asyncio.timeout(timeout_seconds), httpx.AsyncClient(
                    timeout=httpx.Timeout(timeout_seconds, connect=10),
                    trust_env=False, follow_redirects=False, transport=self._transport) as client:
                async with client.stream("POST", self._base_url + path, headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        if response.status_code == 429:
                            raise ChatError("chat_busy", 429, "El asistente está ocupado. Inténtalo en un momento.")
                        if response.status_code in {401, 403}:
                            raise ChatError("chat_authorization_failed", 503,
                                            "La conexión segura del asistente no está disponible.")
                        raise ChatError("chat_upstream_failed", 502,
                                        "FLUJO no pudo completar esta consulta. Puedes volver a intentarlo.")
                    parts: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > _MAX_RESPONSE:
                            raise ChatError("chat_invalid_response", 502, "No se pudo verificar la respuesta de FLUJO.")
                        parts.append(chunk)
                    result = json.loads(b"".join(parts))
                    if not isinstance(result, dict):
                        raise ValueError()
                    return result
        except ChatError:
            raise
        except (httpx.TimeoutException, TimeoutError):
            raise ChatError("chat_timeout", 504,
                            "La consulta tardó más de lo esperado. No se ha reenviado automáticamente.") from None
        except (httpx.HTTPError, ValueError, UnicodeError):
            raise ChatError("chat_unreachable", 502, "No fue posible conectar con el asistente de FLUJO.") from None

    @staticmethod
    def _selection(selection: dict[str, Any] | None) -> dict[str, Any] | None:
        if selection is None:
            return None
        fields = {"reference", "occurred_at", "type", "amount", "currency", "status"}
        if (not isinstance(selection, dict) or set(selection) != fields
                or not isinstance(selection["reference"], str)
                or not re.fullmatch(r"txn_[a-f0-9]{24}", selection["reference"])
                or not all(isinstance(selection[field], str) and 1 <= len(selection[field]) <= maximum
                           for field, maximum in [("occurred_at", 40), ("type", 80), ("currency", 8), ("status", 80)])
                or isinstance(selection["amount"], bool)
                or not isinstance(selection["amount"], (int, float)) or not math.isfinite(selection["amount"])):
            raise ChatError("invalid_selection", 400, "El movimiento seleccionado no está disponible.")
        return {field: selection[field] for field in sorted(fields)}

    async def send(self, customer_id: str, session_id: str, session_exp: int, message: str, *,
                   display_message: str | None = None, selection: dict[str, Any] | None = None) -> dict[str, Any]:
        subject, owner = self._identity(customer_id, session_id, session_exp)
        if (not isinstance(message, str) or not message.strip() or len(message.strip()) > 4096
                or len(message.encode("utf-8")) > 12000):
            raise ChatError("invalid_message", 400, "Escribe una consulta de hasta 4096 caracteres.")
        public_message = message.strip() if display_message is None else display_message
        if (not isinstance(public_message, str) or not public_message.strip()
                or len(public_message.strip()) > 4096 or len(public_message.encode("utf-8")) > 12000):
            raise ChatError("invalid_message", 400, "Escribe una consulta de hasta 4096 caracteres.")
        public_selection = self._selection(selection)
        operation = str(uuid.uuid4())
        now = int(time.time())
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._bind(db, session_id, owner, session_exp)
            if row["revoked"]:
                raise ChatError("session_expired", 401, "Tu sesión expiró. Vuelve a ingresar.")
            if row["active_until"] > now:
                raise ChatError("chat_busy", 429, "Espera la respuesta de tu consulta anterior.")
            if row["subject"] is None and row["customer_id"] is None:
                db.execute("UPDATE chat_sessions SET subject=?,customer_id=? WHERE session_id=?",
                           (subject, customer_id, session_id))
            elif row["subject"] != subject or row["customer_id"] != customer_id:
                raise ChatError("session_mismatch", 401, "La sesión del asistente no está disponible.")
            conversation = row["conversation_id"]
            db.execute("UPDATE chat_sessions SET active_id = ?, active_until = ? WHERE session_id = ?",
                       (operation, min(now + _TIMEOUT + 15, session_exp), session_id))
        try:
            metadata = {"flujo": "true", "appendMessages": "true"}
            if conversation:
                if not _CONVERSATION.fullmatch(conversation):
                    raise ChatError("chat_invalid_state", 503, "La sesión del asistente no está disponible.")
                metadata["conversationId"] = conversation
            result = await self._post("/v1/chat/completions", self._headers(subject, session_id, session_exp),
                {"model": self._model, "messages": [{"role": "user", "content": message.strip()}],
                 "stream": False, "metadata": metadata})
            reply, returned_conversation, status = self._public_reply(result)
            if conversation and returned_conversation != conversation:
                raise ChatError("chat_invalid_response", 502, "No se pudo verificar la respuesta de FLUJO.")
            with self._connection() as db:
                db.execute("BEGIN IMMEDIATE")
                current = self._bind(db, session_id, owner, session_exp)
                if current["revoked"] or current["active_id"] != operation or session_exp <= int(time.time()):
                    raise ChatError("session_expired", 401, "Tu sesión expiró. Vuelve a ingresar.")
                db.execute("UPDATE chat_sessions SET conversation_id = ? WHERE session_id = ?",
                           (returned_conversation, session_id))
                db.executemany("INSERT INTO chat_messages(session_id,operation,role,text,selection_json) VALUES (?,?,?,?,?)", [
                    (session_id, operation, "user", public_message.strip(),
                     json.dumps(public_selection, ensure_ascii=False, allow_nan=False) if public_selection else None),
                    (session_id, operation, "assistant", reply, None),
                ])
            return {"reply": reply, "mode": "flujo", "status": status}
        finally:
            with self._connection() as db:
                db.execute("UPDATE chat_sessions SET active_id = NULL, active_until = 0 WHERE session_id = ? AND active_id = ?",
                           (session_id, operation))

    @staticmethod
    def _public_reply(result: dict[str, Any]) -> tuple[str, str, str]:
        try:
            conversation = result["conversation_id"]
            status = result["status"]
            reply = result["choices"][0]["message"]["content"]
            if (not isinstance(conversation, str) or not _CONVERSATION.fullmatch(conversation)
                    or status not in {"completed", "waiting_for_input"}
                    or not isinstance(reply, str) or not reply.strip() or len(reply) > 32768):
                raise ValueError()
            return reply, conversation, status
        except (KeyError, IndexError, TypeError, ValueError):
            raise ChatError("chat_invalid_response", 502, "No se pudo verificar la respuesta de FLUJO.") from None

    def queue_revoke(self, customer_id: str, session_id: str, session_exp: int) -> str:
        """Atomically deny local chat and persist an idempotent worker revoke intent.

        The caller must do this before deleting the browser session. A storage
        error propagates, so it cannot be mistaken for a worker acknowledgement.
        """
        identity = self._revoke_identity(customer_id, session_id, session_exp)
        now = int(time.time())
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if identity is None:
                row = db.execute("SELECT expires,customer_id FROM chat_sessions WHERE session_id=?",
                                 (session_id,)).fetchone()
                if row is None:
                    return "unavailable"
                if row["expires"] != session_exp or (row["customer_id"] and row["customer_id"] != customer_id):
                    raise ChatError("session_mismatch", 401, "La sesión del asistente no está disponible.")
                # Legacy records may predate admission identity persistence.
                # This durable marker is recovered into the retry queue once
                # approved config returns; it remains operator-visible meanwhile.
                db.execute("UPDATE chat_sessions SET revoked=1 WHERE session_id=?", (session_id,))
                return "unresolved"
            subject, owner = identity
            row = self._bind(db, session_id, owner, session_exp)
            if row["subject"] is None and row["customer_id"] is None:
                db.execute("UPDATE chat_sessions SET subject=?,customer_id=? WHERE session_id=?",
                           (subject, customer_id, session_id))
            elif row["subject"] != subject or row["customer_id"] != customer_id:
                raise ChatError("session_mismatch", 401, "La sesión del asistente no está disponible.")
            db.execute("UPDATE chat_sessions SET revoked = 1 WHERE session_id = ?", (session_id,))
            db.execute("""INSERT OR IGNORE INTO pending_revocations
                (session_id,owner,subject,expires,state,next_attempt_at,created_at,updated_at)
                VALUES (?,?,?,?,'pending',?,?,?)""",
                (session_id, owner, subject, session_exp, now, now, now))
            row = db.execute("SELECT owner,subject,expires,state FROM pending_revocations WHERE session_id=?",
                             (session_id,)).fetchone()
            if (row is None or row["owner"] != owner or row["subject"] != subject
                    or row["expires"] != session_exp):
                raise ChatError("session_mismatch", 401, "La sesión del asistente no está disponible.")
            return row["state"]

    def _claim_revoke(self, session_id: str) -> tuple[sqlite3.Row, str] | str:
        now = int(time.time())
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM pending_revocations WHERE session_id=?", (session_id,)).fetchone()
            if row is None:
                return "absent"
            if row["state"] != "pending":
                return row["state"]
            if row["lease_token"] and row["lease_until"] > now:
                return "pending"
            if row["expires"] <= now:
                db.execute("""UPDATE pending_revocations SET state='expired_unconfirmed',
                    lease_token=NULL,lease_until=0,last_error_code='revoke_session_expired',updated_at=?
                    WHERE session_id=? AND state='pending'""", (now, session_id))
                return "expired_unconfirmed"
            if row["next_attempt_at"] > now:
                return "pending"
            lease = str(uuid.uuid4())
            attempts = row["attempts"] + 1
            db.execute("""UPDATE pending_revocations SET attempts=?,next_attempt_at=?,
                lease_token=?,lease_until=?,updated_at=? WHERE session_id=? AND state='pending'""",
                (attempts, now + min(2 ** min(attempts, 5), 30), lease,
                 now + _REVOKE_LEASE, now, session_id))
            return row, lease

    def _finish_revoke(self, session_id: str, lease: str, *, confirmed: bool,
                       error_code: str | None = None) -> str:
        now = int(time.time())
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state,attempts,lease_token FROM pending_revocations WHERE session_id=?",
                             (session_id,)).fetchone()
            if row is None:
                return "absent"
            if row["state"] == "confirmed":
                return "confirmed"
            if confirmed:
                # An exact worker acknowledgement remains authoritative even
                # if this lease expired while the response was in flight.
                db.execute("""UPDATE pending_revocations SET state='confirmed',lease_token=NULL,
                    lease_until=0,last_error_code=NULL,updated_at=? WHERE session_id=?""", (now, session_id))
                return "confirmed"
            if row["lease_token"] != lease:
                return row["state"]
            if row["state"] == "expired_unconfirmed":
                return "expired_unconfirmed"
            delay = min(2 ** min(row["attempts"], 5), 30)
            db.execute("""UPDATE pending_revocations SET lease_token=NULL,lease_until=0,
                next_attempt_at=?,last_error_code=?,updated_at=? WHERE session_id=? AND state='pending'""",
                (now + delay, error_code or "revoke_internal_error", now, session_id))
            return "pending"

    async def attempt_revoke(self, session_id: str) -> str:
        """Deliver one due revoke with a fresh assertion; response loss is retried."""
        claim = self._claim_revoke(session_id)
        if isinstance(claim, str):
            return claim
        row, lease = claim
        with self._connection() as db:
            binding = db.execute("""SELECT owner,expires,subject,customer_id FROM chat_sessions
                WHERE session_id=?""", (session_id,)).fetchone()
        mapped_customer = self._approved_subject_customers.get(row["subject"]) if self._configured else None
        if (not binding or binding["owner"] != row["owner"] or binding["expires"] != row["expires"]
                or (binding["subject"] and binding["subject"] != row["subject"])
                or not mapped_customer or (binding["customer_id"] and binding["customer_id"] != mapped_customer)
                or row["owner"] != self._owner_for_subject(row["subject"])):
            return self._finish_revoke(session_id, lease, confirmed=False,
                                       error_code="revoke_configuration_unavailable")
        try:
            result = await self._post("/v1/banking/session/revoke",
                self._headers(row["subject"], session_id, row["expires"]), {},
                timeout_seconds=_REVOKE_TIMEOUT)
            if result != {"revoked": True}:
                raise ChatError("chat_revocation_failed", 502, "No se pudo confirmar el cierre del asistente.")
        except asyncio.CancelledError:
            self._finish_revoke(session_id, lease, confirmed=False,
                                error_code="revoke_interrupted")
            raise
        except ChatError as exc:
            return self._finish_revoke(session_id, lease, confirmed=False, error_code=exc.code)
        except Exception:
            # Neither response bodies nor credential-bearing exceptions enter
            # persistent diagnostics. The intent remains retryable.
            return self._finish_revoke(session_id, lease, confirmed=False,
                                       error_code="revoke_internal_error")
        return self._finish_revoke(session_id, lease, confirmed=True)

    async def revoke(self, customer_id: str, session_id: str, session_exp: int) -> str:
        """Compatibility helper for callers that do not own session deletion."""
        state = self.queue_revoke(customer_id, session_id, session_exp)
        return await self.attempt_revoke(session_id) if state == "pending" else state

    def revocation_diagnostics(self) -> dict[str, Any]:
        """Aggregate operator state; contains no principal, session, or token."""
        now = int(time.time())
        with self._connection() as db:
            counts = {row["state"]: row["total"] for row in db.execute(
                "SELECT state,COUNT(*) AS total FROM pending_revocations GROUP BY state")}
            retrying = db.execute("""SELECT COUNT(*) FROM pending_revocations
                WHERE state='pending' AND lease_token IS NOT NULL AND lease_until>?""", (now,)).fetchone()[0]
            unresolved = db.execute("""SELECT COUNT(*) FROM chat_sessions s WHERE s.revoked=1
                AND s.expires>? AND NOT EXISTS
                (SELECT 1 FROM pending_revocations p WHERE p.session_id=s.session_id)""", (now,)).fetchone()[0]
            legacy_expired_unknown = db.execute("""SELECT COUNT(*) FROM chat_sessions s WHERE s.revoked=1
                AND s.expires<=? AND NOT EXISTS
                (SELECT 1 FROM pending_revocations p WHERE p.session_id=s.session_id)""", (now,)).fetchone()[0]
            error = db.execute("""SELECT last_error_code FROM pending_revocations
                WHERE last_error_code IS NOT NULL ORDER BY updated_at DESC LIMIT 1""").fetchone()
        return {"configured": self._configured, "pending": counts.get("pending", 0),
                "retrying": retrying, "confirmed": counts.get("confirmed", 0),
                "unresolved": unresolved,
                "legacy_expired_unknown": legacy_expired_unknown,
                "expired_unconfirmed": counts.get("expired_unconfirmed", 0),
                "last_error_code": error[0] if error else None}

    async def retry_pending_loop(self, stop: asyncio.Event, *, poll_seconds: float = _REVOKE_POLL) -> None:
        """Resume persisted intents at startup and retry with bounded backoff."""
        while not stop.is_set():
            now = int(time.time())
            with self._connection() as db:
                due = [row[0] for row in db.execute("""SELECT session_id FROM pending_revocations
                    WHERE state='pending' AND (next_attempt_at<=? OR expires<=?)
                    AND (lease_token IS NULL OR lease_until<=?)
                    ORDER BY next_attempt_at LIMIT 16""", (now, now, now))]
            for session_id in due:
                if stop.is_set():
                    return
                await self.attempt_revoke(session_id)
            try:
                await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
            except TimeoutError:
                pass
