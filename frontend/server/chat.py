"""Durable banking host and separate, untrusted generic language guidance."""
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
import uuid

from .bank_rpc import BankContext, BankRPC, BankRPCError
from .bank_controller import BankController
from .language import GenericLanguageClient, LanguageConfig, MinimizedFacts, render_guidance

from .review import review_reference
from .action import (handoff_questions, matches_selected_transaction, normalize_handoff_questions,
                     project_action_result)


_CONVERSATION = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$")
_PUBLIC_TRANSACTION = re.compile(r"^txn_[a-f0-9]{24}$")
_PENDING_HANDLE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
_REQUEST_ID = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$")
_LEDGER_GENERATION = re.compile(r"^[a-f0-9]{64}$")
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
_PREPARE_STALE_SECONDS = 50
_PREPARE_RECOVERY_TIMEOUT = 20
_PREPARE_RECOVERY_WINDOW = 570
_PREPARE_RECOVERY_MAX_ATTEMPTS = 6


class ChatError(Exception):
    """Public, fixed errors; upstream responses and credentials are never echoed."""

    def __init__(self, code: str, status_code: int, message: str, *, possibly_sent: bool | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.message = message
        # Internal delivery provenance; never serialized into a customer error.
        self.possibly_sent = possibly_sent


class ChatService:
    def __init__(self, config: dict[str, Any] | None, state_dir: Path):
        self._configured = False
        self._reason = "El asistente de FLUJO todavía no está conectado a esta demo."
        self._customer_subjects: dict[str, str] = {}
        self._action_enabled = False
        self._ledger_continuity_approved = False
        self._ledger_generation: str | None = None
        self._approved_subject_customers: dict[str, str] = {}
        self._approved_owner_subjects: dict[str, tuple[str, str]] = {}
        self._db_path = Path(state_dir) / "frontend-chat.sqlite3"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            # Never reinterpret a worker-owned capability as direct host state.
            # Inspect before any legacy schema migration or row mutation.
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            marker = ("chat_migrations" in tables and db.execute(
                "SELECT 1 FROM chat_migrations WHERE name='host-direct-mcp-v1'").fetchone())
            if not marker:
                for table in ("chat_sessions", "action_status", "pending_revocations", "chat_messages"):
                    if table in tables and db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                        raise RuntimeError("Legacy worker-bound state requires isolated state and explicit reconciliation")
            # Inspect the original pin and every retained authority before any
            # migration/outbox repair. Old direct-host rows are not new grants.
            self._ledger_generation = self._retained_ledger_generation(db, tables)
            candidate = config.get("ledger_generation") if isinstance(config, dict) else None
            if self._ledger_generation is not None and candidate is not None and candidate != self._ledger_generation:
                raise RuntimeError("Bank ledger generation changed; preserve state and reconcile explicitly")
            db.execute("""CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires INTEGER NOT NULL,
                conversation_id TEXT, revoked INTEGER NOT NULL DEFAULT 0,
                active_id TEXT, active_until INTEGER NOT NULL DEFAULT 0,
                subject TEXT, customer_id TEXT, bank_context_id TEXT, language_policy TEXT,
                ledger_generation TEXT NOT NULL
            )""")
            # Persist the approved admission identity, never credentials. An
            # existing volume gets the same columns without discarding history.
            columns = {row[1] for row in db.execute("PRAGMA table_info(chat_sessions)")}
            if "subject" not in columns:
                db.execute("ALTER TABLE chat_sessions ADD COLUMN subject TEXT")
            if "customer_id" not in columns:
                db.execute("ALTER TABLE chat_sessions ADD COLUMN customer_id TEXT")
            if "bank_context_id" not in columns:
                db.execute("ALTER TABLE chat_sessions ADD COLUMN bank_context_id TEXT")
            if "language_policy" not in columns:
                db.execute("ALTER TABLE chat_sessions ADD COLUMN language_policy TEXT")
            if "ledger_generation" not in columns:
                db.execute("ALTER TABLE chat_sessions ADD COLUMN ledger_generation TEXT")
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
                action_id TEXT, target_reference TEXT, revision INTEGER NOT NULL DEFAULT 0,
                prepare_transaction_id TEXT, prepare_snapshot TEXT,
                prepare_conversation_id TEXT, prepare_expected_json TEXT,
                prepare_recovery_attempts INTEGER NOT NULL DEFAULT 0,
                prepare_recovery_after INTEGER NOT NULL DEFAULT 0,
                prepare_recovery_deadline INTEGER NOT NULL DEFAULT 0
            )""")
            action_columns = {row[1] for row in db.execute("PRAGMA table_info(action_status)")}
            if "prepare_expected_json" not in action_columns:
                db.execute("ALTER TABLE action_status ADD COLUMN prepare_expected_json TEXT")
            if "action_id" not in action_columns:
                db.execute("ALTER TABLE action_status ADD COLUMN action_id TEXT")
            if "target_reference" not in action_columns:
                db.execute("ALTER TABLE action_status ADD COLUMN target_reference TEXT")
            if "revision" not in action_columns:
                db.execute("ALTER TABLE action_status ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
            if "prepare_transaction_id" not in action_columns:
                db.execute("ALTER TABLE action_status ADD COLUMN prepare_transaction_id TEXT")
            if "prepare_snapshot" not in action_columns:
                db.execute("ALTER TABLE action_status ADD COLUMN prepare_snapshot TEXT")
            if "prepare_conversation_id" not in action_columns:
                db.execute("ALTER TABLE action_status ADD COLUMN prepare_conversation_id TEXT")
            if "prepare_recovery_attempts" not in action_columns:
                db.execute("ALTER TABLE action_status ADD COLUMN prepare_recovery_attempts INTEGER NOT NULL DEFAULT 0")
            if "prepare_recovery_after" not in action_columns:
                db.execute("ALTER TABLE action_status ADD COLUMN prepare_recovery_after INTEGER NOT NULL DEFAULT 0")
            if "prepare_recovery_deadline" not in action_columns:
                db.execute("ALTER TABLE action_status ADD COLUMN prepare_recovery_deadline INTEGER NOT NULL DEFAULT 0")
            # Legacy status can still be recovered, but without a saved public
            # target it cannot authorize a new confirmation.
            db.execute("UPDATE action_status SET action_id=lower(hex(randomblob(16))) WHERE action_id IS NULL")
            db.execute("CREATE TABLE IF NOT EXISTS chat_migrations (name TEXT PRIMARY KEY)")
            db.execute("INSERT OR IGNORE INTO chat_migrations VALUES ('host-direct-mcp-v1')")
            db.execute("CREATE TABLE IF NOT EXISTS host_policy (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS pending_revocations (
                session_id TEXT PRIMARY KEY, owner TEXT NOT NULL, subject TEXT NOT NULL,
                expires INTEGER NOT NULL, ledger_generation TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('pending','confirmed','expired_unconfirmed')),
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at INTEGER NOT NULL,
                lease_token TEXT, lease_until INTEGER NOT NULL DEFAULT 0,
                last_error_code TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
            )""")
            revoke_columns = {row[1] for row in db.execute("PRAGMA table_info(pending_revocations)")}
            if "ledger_generation" not in revoke_columns:
                db.execute("ALTER TABLE pending_revocations ADD COLUMN ledger_generation TEXT")
            db.execute("CREATE INDEX IF NOT EXISTS pending_revocations_due ON pending_revocations(state, next_attempt_at)")
        # Preserve local denial during temporary configuration loss. With a
        # candidate authority present, check its pin before repairing the outbox;
        # a rejected authority must not mutate the original bank binding.
        if not config:
            self._restore_pending_revocations()
            return
        try:
            self._configure(config)
        except (ValueError, TypeError, KeyError, OSError):
            self._reason = "La conexión segura del asistente requiere configuración."
            self._restore_pending_revocations()
            return
        self._configured = True
        self._restore_pending_revocations()

    def _configure(self, config: dict[str, Any]) -> None:
        if not isinstance(config, dict) or config.get("mode") != "host-direct-mcp/v1":
            raise ValueError("Direct host configuration required")
        if (set(config) - {"mode", "namespace", "host_revision", "action_enabled", "ledger_generation",
                          "ledger_continuity_approved", "bank", "language", "principal_customers"}
                or not isinstance(config.get("action_enabled", False), bool)
                or type(config.get("ledger_continuity_approved", False)) is not bool
                or not isinstance(config.get("ledger_generation"), str)
                or not _LEDGER_GENERATION.fullmatch(config["ledger_generation"])
                or not isinstance(config.get("host_revision"), str)
                or not re.fullmatch(r"[a-f0-9]{40}", config["host_revision"])
                or not isinstance(config.get("namespace"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", config["namespace"])):
            raise ValueError("Invalid host configuration")
        self._bank = BankRPC(config["bank"])
        self._language = GenericLanguageClient(LanguageConfig(**config["language"]))
        if config["bank"]["service_token"] == config["language"]["service_token"]:
            raise ValueError("Separate bank and language credentials required")
        self._language_policy = hashlib.sha256(json.dumps(config["language"],
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self._issuer = config["bank"]["issuer"]
        self._namespace, self._host_revision = config["namespace"], config["host_revision"]
        mappings = config["principal_customers"]
        if not isinstance(mappings, dict) or not mappings or len(mappings) > 1000:
            raise ValueError("Approved principal mapping required")
        for subject, customer in mappings.items():
            if not all(isinstance(value, str) and 1 <= len(value) <= 128 for value in [subject, customer]):
                raise ValueError("Invalid principal mapping")
            self._approved_subject_customers[subject] = customer
            self._approved_owner_subjects[self._owner_for_subject(subject)] = (subject, customer)
            self._customer_subjects.setdefault(customer, subject)
        policy = hashlib.sha256(json.dumps({"mode": config["mode"], "namespace": self._namespace,
            "issuer": self._issuer, "audience": config["bank"]["audience"], "principals": mappings,
            "bank_authority": self._bank.authority_identity,
            "ledger_generation": config["ledger_generation"]},
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            generation = db.execute("SELECT value FROM host_policy WHERE key='ledger_generation'").fetchone()
            if generation and generation[0] != config["ledger_generation"]:
                raise RuntimeError("Bank ledger generation changed; preserve state and reconcile explicitly")
            old = db.execute("SELECT value FROM host_policy WHERE key='bank_binding'").fetchone()
            if old and old[0] != policy:
                raise RuntimeError("Bank authority policy changed; isolate state and reconcile revocation explicitly")
            db.execute("INSERT OR IGNORE INTO host_policy VALUES ('bank_binding', ?)", (policy,))
            db.execute("INSERT OR IGNORE INTO host_policy VALUES ('ledger_generation', ?)",
                       (config["ledger_generation"],))
        self._ledger_generation = config["ledger_generation"]
        self._action_enabled = config.get("action_enabled", False)
        self._ledger_continuity_approved = config.get("ledger_continuity_approved", False)

    @staticmethod
    def _retained_ledger_generation(db: sqlite3.Connection, tables: set[str]) -> str | None:
        pin = (db.execute("SELECT value FROM host_policy WHERE key='ledger_generation'").fetchone()
               if "host_policy" in tables else None)
        nonempty = any(table in tables and db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                       for table in ("chat_sessions", "action_status", "pending_revocations", "chat_messages"))
        if pin is None and not nonempty:
            return None
        if pin is None or not isinstance(pin[0], str) or not _LEDGER_GENERATION.fullmatch(pin[0]):
            raise RuntimeError("Unpinned bank history requires explicit reconciliation; no generation adoption")
        for table in ("chat_sessions", "pending_revocations"):
            if table in tables:
                columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                if "ledger_generation" not in columns or db.execute(
                        f"SELECT 1 FROM {table} WHERE ledger_generation IS NULL OR ledger_generation != ? LIMIT 1",
                        (pin[0],)).fetchone():
                    raise RuntimeError("Bank history generation is unverified; preserve state and reconcile explicitly")
        return pin[0]

    def _assert_ledger_binding(self, db: sqlite3.Connection) -> str:
        expected = self._ledger_generation
        pin = db.execute("SELECT value FROM host_policy WHERE key='ledger_generation'").fetchone()
        if (not isinstance(expected, str) or not _LEDGER_GENERATION.fullmatch(expected)
                or pin is None or pin[0] != expected):
            raise ChatError("authorization_denied", 503, "La continuidad de la solicitud no está verificada.")
        return expected

    def _require_action_admission(self, db: sqlite3.Connection | None = None) -> None:
        if not self._action_enabled:
            raise ChatError("action_unavailable", 503, "La recepción simulada no está habilitada.")
        if not self._ledger_continuity_approved:
            raise ChatError("action_unverified", 503, "La continuidad de la solicitud requiere revisión.")
        if db is not None:
            self._assert_ledger_binding(db)

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
                "read_only": not (available and self._action_enabled and self._ledger_continuity_approved),
                "sandbox_intake_available": available and self._action_enabled and self._ledger_continuity_approved,
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
    def _general_handoff(packet: dict[str, Any]) -> bool:
        return (packet.get("facts") == {} and packet.get("snapshot") is None
                and packet.get("transaction_provenance") is None
                and packet.get("transaction_currentness") == "not_applicable")

    @staticmethod
    def _action_result(row: sqlite3.Row) -> dict[str, Any]:
        result = json.loads(row["result_json"])
        if not isinstance(result, dict):
            raise ChatError("action_invalid_state", 503, "No se pudo verificar la recepción simulada.")
        # Only the authenticated durable row supplies the public target binding.
        if row["target_reference"]:
            result["target_reference"] = row["target_reference"]
        else:
            result.pop("target_reference", None)
        result = project_action_result(result)
        if (result.get("state") == "handoff_verified" and row["target_reference"] is None
                and not result.get("pending_handle")
                and not ChatService._general_handoff(result["handoff"])):
            # No selected owner row binds transaction-bearing evidence here.
            # Keep its immutable retry identity, but never unlock this request.
            result = {"state": "handoff_unverified", **{key: result[key] for key in
                ("reason", "request_id", "unanswered_questions", "prior_handoff") if key in result}}
        if row["target_reference"]:
            result["target_reference"] = row["target_reference"]
        return result

    @classmethod
    def _retained_evidence(cls, row: sqlite3.Row | None, target_reference: str | None) -> dict[str, Any]:
        """Keep earlier readback for display; it never resolves the active intent."""
        if not row or row["target_reference"] != target_reference:
            return {}
        prior = cls._action_result(row)
        retained = {key: prior[key] for key in ("prior_receipt", "prior_handoff") if key in prior}
        if (target_reference and prior.get("state") in {"intake_verified", "existing_case_verified"}
                and cls._verified_terminal(prior)):
            retained["prior_receipt"] = {"target_reference": target_reference, "receipt": prior["receipt"]}
        if (target_reference is None and prior.get("state") == "handoff_verified"
                and cls._verified_terminal(prior) and cls._general_handoff(prior["handoff"])):
            retained["prior_handoff"] = {"target_reference": None, "handoff": prior["handoff"]}
        return retained

    @staticmethod
    def _verified_terminal(result: dict[str, Any]) -> bool:
        projected = project_action_result(result)
        return (projected["state"] in {"intake_verified", "existing_case_verified", "handoff_verified"}
                and projected["state"] == result.get("state"))

    @classmethod
    def _safe_prepare_result(cls, result: dict[str, Any], expected_snapshot: str | None = None,
                             expected_transaction: dict[str, Any] | None = None) -> dict[str, Any]:
        """Only a verified host result may resolve a saved prepare intent."""
        projected = project_action_result(result)
        if projected.get("state") in {"handoff_verified", "existing_case_verified", "pending_confirmation"}:
            if (not isinstance(projected.get("snapshot"), str)
                    or projected.get("transaction") is None
                    or (expected_snapshot is not None and projected["snapshot"] != expected_snapshot)
                    or (expected_transaction is not None and not matches_selected_transaction(
                        projected["transaction"], expected_transaction))):
                return {"state": "prepare_unverified"}
            if projected["state"] == "handoff_verified" and (
                    projected["handoff"]["snapshot"] != projected["snapshot"]
                    or projected["handoff"]["facts"] != projected["transaction"]
                    or (result.get("reason") is not None and result["reason"] != projected["handoff"]["reason"])):
                return {"state": "prepare_unverified"}
            return projected
        if (result.get("state") == "handoff_unverified"
                and isinstance(result.get("reason"), str) and result["reason"] in _RECOVERABLE_HANDOFF_REASONS
                and isinstance(result.get("pending_handle"), str)
                and _PENDING_HANDLE.fullmatch(result["pending_handle"])):
            return result
        return {"state": "prepare_unverified"}

    def _assert_action_session(self, db: sqlite3.Connection, session_id: str,
                               owner: str, session_exp: int) -> None:
        generation = self._assert_ledger_binding(db)
        session = db.execute("SELECT owner,expires,revoked,ledger_generation FROM chat_sessions WHERE session_id=?",
                             (session_id,)).fetchone()
        if (not session or session["owner"] != owner or session["expires"] != session_exp
                or session["revoked"] or session_exp <= int(time.time())):
            raise ChatError("session_expired", 401, "Tu sesión expiró. Vuelve a ingresar.")
        if session["ledger_generation"] != generation:
            raise ChatError("authorization_denied", 503, "La continuidad de la solicitud no está verificada.")

    def _reserve_action(self, session_id: str, owner: str, session_exp: int,
                        target_reference: str | None, initial: dict[str, Any],
                        *, prepare_transaction_id: str | None = None,
                        prepare_snapshot: str | None = None,
                        prepare_conversation_id: str | None = None,
                        prepare_expected: dict[str, Any] | None = None
                        ) -> tuple[str, int, sqlite3.Row | None]:
        now = int(time.time())
        action_id = str(uuid.uuid4())
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_action_admission(db)
            self._assert_action_session(db, session_id, owner, session_exp)
            row = self._action_row(db, session_id, owner, session_exp)
            if row and not self._verified_terminal(self._action_result(row)):
                raise ChatError("action_in_progress", 409,
                                "Primero resuelve o revisa la solicitud anterior con Savia.")
            revision = row["revision"] + 1 if row else 1
            result = dict(initial)
            if target_reference:
                result["target_reference"] = target_reference
            result.update(self._retained_evidence(row, target_reference))
            db.execute("""INSERT INTO action_status
                (session_id,owner,expires,result_json,updated_at,action_id,target_reference,revision,
                 prepare_transaction_id,prepare_snapshot,prepare_conversation_id,prepare_expected_json,
                 prepare_recovery_attempts,prepare_recovery_after,prepare_recovery_deadline)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET
                result_json=excluded.result_json,updated_at=excluded.updated_at,
                action_id=excluded.action_id,target_reference=excluded.target_reference,
                revision=excluded.revision,
                prepare_transaction_id=excluded.prepare_transaction_id,
                prepare_snapshot=excluded.prepare_snapshot,
                prepare_conversation_id=excluded.prepare_conversation_id,
                prepare_expected_json=excluded.prepare_expected_json,
                prepare_recovery_attempts=0,prepare_recovery_after=0,
                prepare_recovery_deadline=excluded.prepare_recovery_deadline""",
                (session_id, owner, session_exp, json.dumps(result), now, action_id,
                 target_reference, revision, prepare_transaction_id, prepare_snapshot,
                 prepare_conversation_id, json.dumps(prepare_expected, allow_nan=False) if prepare_expected else None, 0, 0,
                 now + _PREPARE_RECOVERY_WINDOW if prepare_transaction_id else 0))
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
                    target_reference=?,revision=?,prepare_transaction_id=?,prepare_snapshot=?,
                    prepare_conversation_id=?,prepare_expected_json=?,prepare_recovery_attempts=?,prepare_recovery_after=?,
                    prepare_recovery_deadline=?
                    WHERE session_id=?""",
                    (previous["result_json"], int(time.time()), previous["action_id"],
                     previous["target_reference"], revision + 1,
                     previous["prepare_transaction_id"], previous["prepare_snapshot"],
                     previous["prepare_conversation_id"], previous["prepare_expected_json"], previous["prepare_recovery_attempts"],
                     previous["prepare_recovery_after"], previous["prepare_recovery_deadline"], session_id))

    def _advance_action(self, session_id: str, owner: str, session_exp: int,
                        action_id: str, revision: int, result: dict[str, Any]) -> tuple[dict[str, Any], int]:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._assert_action_session(db, session_id, owner, session_exp)
            row = self._action_row(db, session_id, owner, session_exp)
            if not row or row["action_id"] != action_id or row["revision"] != revision:
                raise ChatError("action_changed", 409,
                                "La solicitud cambió. Actualiza su estado antes de continuar.")
            # Earlier proof comes only from this owner-bound saved row, never
            # from an upstream response or a browser-selected wrapper.
            result = {key: value for key, value in result.items() if key not in {"prior_receipt", "prior_handoff"}}
            if row["target_reference"]:
                result["target_reference"] = row["target_reference"]
            else:
                result.pop("target_reference", None)
            saved = project_action_result(result)
            if self._verified_terminal(saved) or saved.get("state") == "pending_confirmation":
                self._require_action_admission(db)
            saved.update(self._retained_evidence(row, row["target_reference"]))
            if saved.get("state") in {"action_unverified", "handoff_unverified"}:
                prior = self._action_result(row)
                for field in ("snapshot", "transaction", "unanswered_questions"):
                    if field in prior:
                        saved.setdefault(field, prior[field])
            if row["target_reference"]:
                saved["target_reference"] = row["target_reference"]
            retain_prepare = saved.get("state") in {"preparing", "prepare_unverified"}
            db.execute("""UPDATE action_status SET result_json=?,updated_at=?,revision=?,
                prepare_transaction_id=?,prepare_snapshot=?,prepare_conversation_id=?,prepare_expected_json=?,
                prepare_recovery_attempts=?,prepare_recovery_after=?,prepare_recovery_deadline=?
                WHERE session_id=? AND action_id=? AND revision=?""",
                (json.dumps(saved), int(time.time()), revision + 1,
                 row["prepare_transaction_id"] if retain_prepare else None,
                 row["prepare_snapshot"] if retain_prepare else None,
                 row["prepare_conversation_id"] if retain_prepare else None,
                 row["prepare_expected_json"] if retain_prepare else None,
                 row["prepare_recovery_attempts"] if retain_prepare else 0,
                 row["prepare_recovery_after"] if retain_prepare else 0,
                 row["prepare_recovery_deadline"] if retain_prepare else 0,
                 session_id, action_id, revision))
        return saved, revision + 1

    def _current_action(self, session_id: str, owner: str,
                        session_exp: int) -> tuple[sqlite3.Row | None, dict[str, Any] | None]:
        with self._connection() as db:
            self._assert_action_session(db, session_id, owner, session_exp)
            row = self._action_row(db, session_id, owner, session_exp)
        return row, self._action_result(row) if row else None

    def _claim_prepare_recovery(self, session_id: str, owner: str, session_exp: int,
                                action_id: str, revision: int, conversation: str
                                ) -> tuple[dict[str, Any], int, int] | None:
        """Claim one bounded exact replay without changing the action CAS revision.

        A status read can run beside the original POST or another status read.
        The persisted delay admits only one replay at a time and survives a
        process restart. The MCP idempotency key makes a later replay
        return the original pending identity, never a second prepare.
        """
        now = int(time.time())
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_action_admission(db)
            self._assert_action_session(db, session_id, owner, session_exp)
            row = self._action_row(db, session_id, owner, session_exp)
            if not row or row["action_id"] != action_id or row["revision"] != revision:
                return None
            saved = self._action_result(row)
            state = saved.get("state")
            if state not in {"preparing", "prepare_unverified"}:
                return None
            if state == "preparing" and now < row["updated_at"] + _PREPARE_STALE_SECONDS:
                return None
            if row["prepare_recovery_after"] > now:
                return None
            if (row["prepare_recovery_attempts"] >= _PREPARE_RECOVERY_MAX_ATTEMPTS
                    or now + _PREPARE_RECOVERY_TIMEOUT >= row["prepare_recovery_deadline"]):
                return None
            request_id = saved.get("request_id")
            transaction_id = row["prepare_transaction_id"]
            snapshot = row["prepare_snapshot"]
            stored_conversation = row["prepare_conversation_id"]
            try:
                expected = json.loads(row["prepare_expected_json"])
            except (TypeError, ValueError):
                return None
            if (not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id)
                    or not isinstance(expected, dict)
                    or not isinstance(transaction_id, str) or not 1 <= len(transaction_id) <= 128
                    or not isinstance(snapshot, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", snapshot)
                    or not isinstance(stored_conversation, str)
                    or not _CONVERSATION.fullmatch(stored_conversation)
                    or stored_conversation != conversation
                    or not isinstance(row["target_reference"], str)
                    or not _PUBLIC_TRANSACTION.fullmatch(row["target_reference"])):
                # Old/invalid rows cannot choose a new target or be cleared by
                # an uncorrelated MCP response.
                return None
            attempts = row["prepare_recovery_attempts"] + 1
            delay = min(2 ** attempts, 60)
            db.execute("""UPDATE action_status SET prepare_recovery_attempts=?,
                prepare_recovery_after=? WHERE session_id=? AND action_id=? AND revision=?""",
                (attempts, now + _PREPARE_RECOVERY_TIMEOUT + delay,
                 session_id, action_id, revision))
        return {"conversationId": stored_conversation, "operation": "prepare",
                "transactionId": transaction_id, "snapshot": snapshot,
                "requestId": request_id, "expected_transaction": expected}, revision, attempts

    def _release_rejected_prepare_recovery(self, session_id: str, owner: str, session_exp: int,
                                           action_id: str, revision: int, reserved_attempt: int) -> None:
        """Release only this proven unadmitted reservation, never the action."""
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._assert_action_session(db, session_id, owner, session_exp)
            row = self._action_row(db, session_id, owner, session_exp)
            if (row and row["action_id"] == action_id and row["revision"] == revision
                    and row["prepare_recovery_attempts"] == reserved_attempt
                    and self._action_result(row).get("state") in {"preparing", "prepare_unverified"}):
                db.execute("""UPDATE action_status SET prepare_recovery_attempts=?,
                    prepare_recovery_after=? WHERE session_id=? AND action_id=? AND revision=?""",
                    (max(row["prepare_recovery_attempts"] - 1, 0), int(time.time()) + 2,
                     session_id, action_id, revision))

    async def action(self, customer_id: str, session_id: str, session_exp: int,
                     operation: dict[str, Any], *, target_reference: str | None = None,
                     expected_snapshot: str | None = None,
                     expected_transaction: dict[str, Any] | None = None) -> dict[str, Any]:
        """A trusted frontend control, separate from model text and tool arguments."""
        self._require_action_admission()
        kind = operation.get("operation")
        if kind not in {"prepare", "confirm", "handoff"}:
            raise ChatError("invalid_action", 400, "La solicitud no está disponible.")
        operation = dict(operation)
        supplied_questions = operation.get("unansweredQuestions") if "unansweredQuestions" in operation else None
        if kind == "handoff" and "unansweredQuestions" in operation:
            supplied_questions = normalize_handoff_questions(supplied_questions)
            if supplied_questions is None:
                raise ChatError("invalid_action", 400, "La solicitud no está disponible.")
            operation["unansweredQuestions"] = supplied_questions
        supplied_request_id = operation.get("requestId")
        if kind != "prepare" and supplied_request_id is not None and (not isinstance(supplied_request_id, str)
                or not _REQUEST_ID.fullmatch(supplied_request_id)):
            raise ChatError("invalid_action", 400, "La solicitud no está disponible.")
        if kind == "prepare":
            if (not isinstance(operation.get("transactionId"), str)
                    or not 1 <= len(operation["transactionId"]) <= 128
                    or not isinstance(operation.get("snapshot"), str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", operation["snapshot"])
                    or not isinstance(expected_transaction, dict)):
                raise ChatError("invalid_action", 400, "La solicitud no está disponible.")
            # The browser cannot choose an idempotency key or bind it to a
            # different charge. Mint it before the durable intent and POST.
            operation["requestId"] = str(uuid.uuid4())
        if kind == "confirm" and operation.get("confirmed") is not True:
            raise ChatError("confirmation_required", 400, "Confirma explícitamente la solicitud.")
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
            conversation = row["bank_context_id"]
            if row["subject"] is None and row["customer_id"] is None:
                db.execute("UPDATE chat_sessions SET subject=?,customer_id=? WHERE session_id=?",
                           (subject, customer_id, session_id))
            elif row["subject"] != subject or row["customer_id"] != customer_id:
                raise ChatError("session_mismatch", 401, "La sesión del asistente no está disponible.")
            if row["active_until"] > int(time.time()):
                raise ChatError("chat_busy", 429, "Espera la respuesta de tu consulta anterior.")
        if not isinstance(conversation, str) or not _CONVERSATION.fullmatch(conversation):
            raise ChatError("inquiry_required", 409,
                            "Primero consulta el movimiento con Savia para iniciar una conversación segura.")
        action_id: str | None = None
        revision: int | None = None
        previous: sqlite3.Row | None = None
        confirm_handoff_retry = False
        bound_snapshot: str | None = None
        bound_transaction: dict[str, Any] | None = None
        if kind == "prepare":
            action_id, revision, previous = self._reserve_action(session_id, owner, session_exp,
                target_reference, {"state": "preparing", "request_id": operation["requestId"]},
                prepare_transaction_id=operation.get("transactionId"),
                prepare_snapshot=operation.get("snapshot"),
                prepare_conversation_id=conversation, prepare_expected=expected_transaction)
        elif kind == "confirm" or handle:
            if not isinstance(handle, str) or not _PENDING_HANDLE.fullmatch(handle):
                raise ChatError("action_mismatch", 409, "La solicitud no corresponde al movimiento seleccionado.")
            current, saved = self._current_action(session_id, owner, session_exp)
            if (not current or current["target_reference"] != target_reference
                    or saved.get("pending_handle") != handle):
                raise ChatError("action_mismatch", 409, "La solicitud no corresponde al movimiento seleccionado.")
            bound_snapshot = saved.get("snapshot")
            bound_transaction = saved.get("transaction")
            if kind == "confirm" and saved.get("state") == "pending_confirmation" and (
                    (expected_snapshot is not None and saved.get("snapshot") != expected_snapshot)
                    or (expected_transaction is not None and not matches_selected_transaction(
                        saved.get("transaction"), expected_transaction))):
                raise ChatError("action_mismatch", 409,
                                "El movimiento o la instantánea cambió. Revisa la solicitud guardada antes de continuar.")
            if kind == "confirm" and saved.get("state") == "intake_verified" and self._verified_terminal(saved):
                return saved
            if kind == "handoff" and saved.get("state") == "handoff_verified" and self._verified_terminal(saved):
                if ((saved.get("reason") or saved["handoff"]["reason"]) != operation["reason"]
                        or (supplied_questions is not None and supplied_questions != saved["handoff"]["unanswered_questions"])
                        or (supplied_request_id is not None and supplied_request_id != saved.get("request_id"))):
                    raise ChatError("action_mismatch", 409, "La solicitud no corresponde a la revisión guardada.")
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
                questions = saved.get("unanswered_questions", [])
                if handoff_questions(questions) is None or (supplied_questions is not None and supplied_questions != questions):
                    raise ChatError("action_mismatch", 409, "Las preguntas no corresponden a la revisión guardada.")
                operation["unansweredQuestions"] = list(questions)
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
                # Continue the server-created prepare identity; a browser UUID
                # cannot select a second handoff key for this pending charge.
                saved_request_id = saved.get("request_id")
                operation["requestId"] = (saved_request_id
                    if isinstance(saved_request_id, str) and _REQUEST_ID.fullmatch(saved_request_id)
                    else str(uuid.uuid4()))
                operation.setdefault("unansweredQuestions", [])
            allowed = ({"pending_confirmation"} if kind == "confirm" else
                       {"pending_confirmation", "existing_case_verified", "action_unverified", "handoff_unverified"})
            if saved.get("state") not in allowed:
                raise ChatError("action_in_progress", 409,
                                "Primero revisa el estado de la solicitud anterior.")
            action_id, revision = current["action_id"], current["revision"]
            previous = current
            uncertain = {"state": "action_unverified" if kind == "confirm" or confirm_handoff_retry
                         else "handoff_unverified",
                         "pending_handle": handle}
            for field in ("snapshot", "transaction"):
                if field in saved:
                    uncertain[field] = saved[field]
            if confirm_handoff_retry:
                uncertain["handoff"] = {"state": "handoff_unverified"}
            if request_id := operation.get("requestId"):
                uncertain["request_id"] = request_id
            if reason := operation.get("reason"):
                uncertain["reason"] = reason
            if kind == "handoff":
                uncertain["unanswered_questions"] = operation["unansweredQuestions"]
            _, revision = self._advance_action(session_id, owner, session_exp,
                                               action_id, revision, uncertain)
        else:
            # A general handoff has no transaction target or pending handle,
            # but still needs an identity before the upstream write begins.
            current, saved = self._current_action(session_id, owner, session_exp)
            if (current and saved.get("state") == "handoff_verified"
                    and not saved.get("pending_handle")
                    and current["target_reference"] is None
                    and supplied_request_id is not None
                    and saved.get("request_id") == supplied_request_id
                    and self._verified_terminal(saved)):
                # This identity already has its complete readback. A replay
                # must not reserve another row or replace its saved questions.
                if ((saved.get("reason") or saved["handoff"]["reason"]) != operation["reason"]
                        or (supplied_questions is not None
                            and supplied_questions != saved["handoff"]["unanswered_questions"])):
                    raise ChatError("action_mismatch", 409, "La solicitud no corresponde a la revisión guardada.")
                return saved
            if (current and saved.get("state") == "handoff_unverified"
                    and not saved.get("pending_handle")
                    and current["target_reference"] is None
                    and saved.get("reason") == operation["reason"]
                    and saved.get("request_id") == supplied_request_id):
                action_id, revision = current["action_id"], current["revision"]
                previous = current
                questions = saved.get("unanswered_questions", [])
                if handoff_questions(questions) is None or (supplied_questions is not None and supplied_questions != questions):
                    raise ChatError("action_mismatch", 409, "Las preguntas no corresponden a la revisión guardada.")
                operation["unansweredQuestions"] = list(questions)
                _, revision = self._advance_action(session_id, owner, session_exp,
                    action_id, revision, {"state": "handoff_unverified",
                                          "reason": operation["reason"],
                                          "unanswered_questions": operation["unansweredQuestions"],
                                          "request_id": supplied_request_id})
            else:
                if operation["reason"] not in _CUSTOMER_HANDOFF_REASONS:
                    raise ChatError("action_mismatch", 409,
                                    "La solicitud no corresponde a una revisión pendiente.")
                operation["requestId"] = str(uuid.uuid4())
                operation.setdefault("unansweredQuestions", [])
                initial = {"state": "handoff_unverified",
                           "unanswered_questions": operation["unansweredQuestions"],
                           "request_id": operation["requestId"], "reason": operation["reason"]}
                action_id, revision, previous = self._reserve_action(session_id, owner,
                                                                       session_exp, None, initial)

        payload = {"conversationId": conversation, **operation}
        if kind == "prepare":
            payload["expected_transaction"] = expected_transaction
        elif handle:
            payload["expected_transaction"] = bound_transaction
            payload["expected_snapshot"] = bound_snapshot
        if kind == "handoff":
            # The project MCP schema uses this snake_case wire field;
            # the local operation retains its frozen request representation.
            payload["unanswered_questions"] = payload.pop("unansweredQuestions")

        def finish(result: dict[str, Any]) -> dict[str, Any]:
            nonlocal revision
            projected = project_action_result(result)
            if projected.get("state") == "intake_verified" and (
                    not bound_snapshot or not bound_transaction
                    or projected["receipt"]["snapshot"] != bound_snapshot
                    or projected["receipt"]["transaction"] != bound_transaction):
                projected = {"state": "action_unverified"}
            packet_state = projected.get("handoff") if projected.get("state") == "action_unverified" else projected
            packet = packet_state.get("handoff") if isinstance(packet_state, dict) else None
            if isinstance(packet, dict) and packet_state.get("state") == "handoff_verified":
                mismatched = (kind == "handoff" and (packet.get("reason") != operation["reason"]
                    or packet.get("unanswered_questions") != operation["unansweredQuestions"]))
                if handle:
                    mismatched = mismatched or (not bound_snapshot or not bound_transaction
                        or packet.get("snapshot") != bound_snapshot or packet.get("facts") != bound_transaction)
                elif kind == "handoff":
                    mismatched = mismatched or not self._general_handoff(packet)
                if mismatched:
                    projected = ({"state": "action_unverified", "handoff": {"state": "handoff_unverified"}}
                                 if projected.get("state") == "action_unverified" else {"state": "handoff_unverified"})
            saved = ({"state": "action_unverified", "reason": "action_unverified",
                      "handoff": projected} if confirm_handoff_retry else projected)
            if handle:
                saved["pending_handle"] = handle
            if request_id := operation.get("requestId"):
                saved["request_id"] = request_id
            if reason := operation.get("reason"):
                saved["reason"] = reason
            if kind == "handoff":
                saved["unanswered_questions"] = list(operation["unansweredQuestions"])
            if action_id is not None and revision is not None:
                saved, revision = self._advance_action(session_id, owner, session_exp,
                                                       action_id, revision, saved)
            return saved
        try:
            result = await self._bank_post(subject, session_id, session_exp, payload, timeout_seconds=45,
                                           expected_action=(action_id, revision))
            if kind == "prepare":
                return finish(self._safe_prepare_result(result, operation["snapshot"], expected_transaction))
            if kind == "confirm" and result.get("state") == "handoff_unverified" and (
                    isinstance(result.get("reason"), str) and result["reason"] in {
                        "high_risk", "missing_evidence", "action_unverified"}):
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
                    retry = await self._bank_post(subject, session_id, session_exp, payload, timeout_seconds=20,
                                                  expected_action=(action_id, revision))
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
                receipt = await self._bank_post(subject, session_id, session_exp,
                    {"conversationId": conversation, "operation": "receipt",
                     "pendingHandle": handle}, timeout_seconds=20, expected_action=(action_id, revision))
            except ChatError as receipt_error:
                if receipt_error.code not in {"chat_timeout", "chat_unreachable", "chat_upstream_failed"}:
                    raise
                return finish({"state": "action_unverified"})
            if receipt.get("state") == "intake_verified" and self._verified_terminal(receipt):
                return finish(receipt)
            # Receipt absence does not establish the outcome of an uncertain
            # confirmation. Never invent a follow-up write.
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
        self._require_action_admission()
        subject, owner = self._identity(customer_id, session_id, session_exp)
        with self._connection() as db:
            session = db.execute("SELECT owner,expires,revoked,bank_context_id FROM chat_sessions WHERE session_id=?",
                                 (session_id,)).fetchone()
        if (not session or session["owner"] != owner or session["expires"] != session_exp
                or session["revoked"]):
            raise ChatError("session_mismatch", 401, "La sesión del asistente no está disponible.")
        row, saved = self._current_action(session_id, owner, session_exp)
        if not row:
            return {"state": "none"}
        if saved.get("state") in {"preparing", "prepare_unverified"}:
            claim = self._claim_prepare_recovery(session_id, owner, session_exp,
                                                 row["action_id"], row["revision"],
                                                 session["bank_context_id"])
            if claim:
                payload, revision, reserved_attempt = claim
                try:
                    replayed = await self._bank_post(subject, session_id, session_exp, payload,
                        timeout_seconds=_PREPARE_RECOVERY_TIMEOUT, expected_action=(row["action_id"], revision))
                except ChatError as exc:
                    if exc.code == "chat_busy" or (exc.possibly_sent is False
                            and exc.code in {"authorization_denied", "action_unverified"}):
                        self._release_rejected_prepare_recovery(session_id, owner, session_exp,
                                                                row["action_id"], revision, reserved_attempt)
                        if exc.code != "chat_busy":
                            raise
                    elif exc.code not in {"chat_timeout", "chat_unreachable", "chat_upstream_failed", "action_changed"}:
                        raise
                else:
                    recovered = self._safe_prepare_result(replayed, payload["snapshot"], payload["expected_transaction"])
                    recovered["request_id"] = saved["request_id"]
                    try:
                        result, _ = self._advance_action(session_id, owner, session_exp,
                            row["action_id"], revision, recovered)
                        if result.get("state") != "prepare_unverified":
                            return result
                    except ChatError as changed:
                        if changed.code != "action_changed":
                            raise
                        # The original POST or another status already advanced
                        # this exact action. Never replace their result.
        if saved.get("state") == "action_unverified" and isinstance(saved.get("pending_handle"), str):
            try:
                receipt = await self._bank_post(subject, session_id, session_exp,
                    {"conversationId": session["bank_context_id"], "operation": "receipt",
                     "pendingHandle": saved["pending_handle"]}, timeout_seconds=20,
                    expected_action=(row["action_id"], row["revision"]))
            except ChatError as exc:
                # A lost receipt response leaves the durable uncertain state.
                # Local ownership/revocation errors must still propagate.
                if exc.code not in {"chat_timeout", "chat_unreachable", "chat_upstream_failed", "action_changed"}:
                    raise
            else:
                if (self._verified_terminal(receipt) and receipt.get("state") == "intake_verified"
                        and receipt["receipt"]["snapshot"] == saved.get("snapshot")
                        and receipt["receipt"]["transaction"] == saved.get("transaction")):
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
        latest_row, latest = self._current_action(session_id, owner, session_exp)
        if (latest_row and latest.get("state") in {"preparing", "prepare_unverified"}
                and (latest_row["prepare_recovery_attempts"] >= _PREPARE_RECOVERY_MAX_ATTEMPTS
                     or int(time.time()) + _PREPARE_RECOVERY_TIMEOUT >= latest_row["prepare_recovery_deadline"])):
            latest["recovery_exhausted"] = True
            if reference := review_reference(latest_row["action_id"]):
                latest["review_reference"] = reference
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
        return hashlib.sha256(json.dumps(["direct-host-v1", self._namespace, self._issuer, subject],
                                         separators=(",", ":")).encode()).hexdigest()

    def _restore_pending_revocations(self) -> None:
        """Queue older local revoke markers without inventing a subject.

        Retrying an already applied revoke is safe under the bank's idempotent
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
            rows = db.execute("""SELECT s.session_id,s.owner,s.expires,s.subject,s.customer_id,s.ledger_generation FROM chat_sessions s
                WHERE s.revoked=1 AND s.expires>? AND NOT EXISTS
                (SELECT 1 FROM pending_revocations p WHERE p.session_id=s.session_id)""",
                (now,)).fetchall()
            for row in rows:
                approved = self._approved_owner_subjects.get(row["owner"])
                subject = (row["subject"] if row["subject"] and row["customer_id"] else
                           approved[0] if approved else None)
                if subject:
                    db.execute("""INSERT OR IGNORE INTO pending_revocations
                        (session_id,owner,subject,expires,ledger_generation,state,next_attempt_at,created_at,updated_at)
                        VALUES (?,?,?,?,?,'pending',?,?,?)""",
                        (row["session_id"], row["owner"], subject, row["expires"], row["ledger_generation"], now, now, now))

    def _bind(self, db: sqlite3.Connection, session_id: str, owner: str, session_exp: int) -> sqlite3.Row:
        generation = self._assert_ledger_binding(db)
        db.execute("""INSERT OR IGNORE INTO chat_sessions
                   (session_id, owner, expires, bank_context_id, ledger_generation) VALUES (?, ?, ?, ?, ?)""",
                   (session_id, owner, session_exp, str(uuid.uuid4()), generation))
        row = db.execute("SELECT * FROM chat_sessions WHERE session_id = ?", (session_id,)).fetchone()
        if (row is None or row["owner"] != owner or row["expires"] != session_exp
                or not isinstance(row["bank_context_id"], str) or not _CONVERSATION.fullmatch(row["bank_context_id"])):
            raise ChatError("session_mismatch", 401, "La sesión del asistente no está disponible.")
        if row["ledger_generation"] != generation:
            raise ChatError("authorization_denied", 503, "La continuidad de la solicitud no está verificada.")
        return row

    def _bank_context(self, subject: str, session_id: str, session_exp: int,
                      conversation: str, operation_id: str, *, ledger_generation: str,
                      admission_check=None) -> BankContext:
        bank_session = hashlib.sha256(json.dumps(["direct-host-v1", self._namespace,
            self._issuer, session_id], separators=(",", ":")).encode()).hexdigest()
        return BankContext(subject=subject, session_id=bank_session, conversation_id=conversation,
                           operation_id=operation_id, host_revision=self._host_revision,
                           session_expires=session_exp, ledger_generation=ledger_generation,
                           admission_check=admission_check)

    async def _bank_post(self, subject: str, session_id: str, session_exp: int,
                         payload: dict, *, timeout_seconds: float = 45,
                         expected_action: tuple[str, int] | None = None) -> dict:
        conversation = payload.get("conversationId")
        owner = self._owner_for_subject(subject)
        with self._connection() as db:
            self._assert_action_session(db, session_id, owner, session_exp)
            session = db.execute("SELECT ledger_generation FROM chat_sessions WHERE session_id=?", (session_id,)).fetchone()
            generation = session["ledger_generation"]
        def admitted():
            with self._connection() as db:
                db.execute("BEGIN")
                try:
                    self._require_action_admission(db)
                    self._assert_action_session(db, session_id, owner, session_exp)
                except ChatError as exc:
                    if exc.code in {"action_unavailable", "action_unverified", "authorization_denied"}:
                        raise BankRPCError("authorization_denied" if exc.code == "authorization_denied"
                                           else "action_unverified") from None
                    raise
                row = db.execute("SELECT bank_context_id,ledger_generation FROM chat_sessions WHERE session_id=?", (session_id,)).fetchone()
                if not row or row["bank_context_id"] != conversation:
                    raise ChatError("session_mismatch", 401, "La sesión del asistente no está disponible.")
                if row["ledger_generation"] != generation:
                    raise BankRPCError("authorization_denied")
                if expected_action:
                    action = self._action_row(db, session_id, owner, session_exp)
                    if not action or (action["action_id"], action["revision"]) != expected_action:
                        raise ChatError("action_changed", 409,
                                        "La solicitud cambió. Actualiza su estado antes de continuar.")
        try:
            admitted()
            context = self._bank_context(subject, session_id, session_exp, conversation, str(uuid.uuid4()),
                                         ledger_generation=generation, admission_check=admitted)
            return await BankController(self._bank, admitted).execute(payload, context, timeout_seconds=timeout_seconds)
        except BankRPCError as exc:
            if exc.code == "action_unverified":
                # This may be a final fence after a durable write. Leave the
                # original locked intent/counters intact, with no write replay.
                raise ChatError("action_unverified", 503, "La continuidad de la solicitud requiere revisión.",
                                possibly_sent=exc.possibly_sent) from None
            if exc.code == "authorization_denied":
                raise ChatError("authorization_denied", 503, "La conexión segura no está disponible.",
                                possibly_sent=exc.possibly_sent) from None
            if exc.code == "server_busy" and not exc.possibly_sent:
                raise ChatError("chat_busy", 429, "El servicio está ocupado. Inténtalo en un momento.") from None
            if exc.code in {"authorization_required", "reference_unavailable"}:
                raise ChatError("chat_authorization_failed", 503, "La conexión segura no está disponible.") from None
            # A fixed MCP error or uncertain transport does not authorize replay
            # of confirm. Preserve the durable pending/uncertain state.
            raise ChatError("chat_upstream_failed", 502, "No se pudo verificar la solicitud.") from None

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
                   display_message: str | None = None, selection: dict[str, Any] | None = None,
                   facts: MinimizedFacts | None = None, language: str = "es") -> dict[str, Any]:
        subject, owner = self._identity(customer_id, session_id, session_exp)
        if (not isinstance(message, str) or not message.strip() or len(message.strip()) > 4096
                or len(message.encode("utf-8")) > 12000 or language not in {"es", "pt"}
                or facts is not None and type(facts) is not MinimizedFacts):
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
            bank_context = row["bank_context_id"]
            conversation = row["conversation_id"]
            context_reset = bool(conversation and row["language_policy"] != self._language_policy)
            if not conversation or context_reset:
                # Generic metadata accepts a new caller-owned conversation UUID.
                # Persist before dispatch, independently of model output/timeout.
                conversation = str(uuid.uuid4())
                db.execute("UPDATE chat_sessions SET conversation_id=?,language_policy=? WHERE session_id=?",
                           (conversation, self._language_policy, session_id))
            pending = db.execute("SELECT prepare_transaction_id,result_json FROM action_status WHERE session_id=?", (session_id,)).fetchone()
            forbidden = [customer_id, subject, session_id, bank_context,
                row["ledger_generation"],
                self._bank_context(subject, session_id, session_exp, bank_context, operation,
                                   ledger_generation=row["ledger_generation"]).session_id]
            forbidden.extend(value for value in (getattr(self._bank, "_service_token", None),
                getattr(getattr(self._language, "config", None), "service_token", None)) if isinstance(value, str))
            if public_selection:
                forbidden.append(public_selection["reference"])
            if pending:
                if pending["prepare_transaction_id"]:
                    forbidden.append(pending["prepare_transaction_id"])
                result = json.loads(pending["result_json"])
                forbidden.extend(result[key] for key in ("pending_handle", "request_id", "snapshot", "target_reference")
                                 if isinstance(result.get(key), str))
            db.execute("UPDATE chat_sessions SET active_id = ?, active_until = ? WHERE session_id = ?",
                       (operation, min(now + _TIMEOUT + 15, session_exp), session_id))
        try:
            # Worker receives only the typed display projection, sanitized text,
            # generic bearer and its own conversation. Model text is never shown.
            guided = await self._language.guide(message.strip(), language, facts=facts,
                conversation_id=conversation, forbidden_values=tuple(forbidden))
            reply = render_guidance(guided.guidance, language, facts)
            if context_reset:
                reply = (("La conexión del asistente cambió; esta consulta inicia un nuevo contexto. " if language == "es"
                          else "A conexão do assistente mudou; esta consulta inicia um novo contexto. ") + reply)
            returned_conversation = guided.conversation_id or conversation
            if (returned_conversation is not None and (not _CONVERSATION.fullmatch(returned_conversation)
                    or returned_conversation == bank_context)
                    or conversation and returned_conversation != conversation):
                raise ChatError("chat_invalid_response", 502, "No se pudo verificar la respuesta del asistente.")
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
            return {"reply": reply, "mode": "flujo", "status": "completed",
                    "guidance": guided.guidance, "banking_authority": False,
                    "language_context_reset": context_reset}
        finally:
            with self._connection() as db:
                db.execute("UPDATE chat_sessions SET active_id = NULL, active_until = 0 WHERE session_id = ? AND active_id = ?",
                           (session_id, operation))

    def queue_revoke(self, customer_id: str, session_id: str, session_exp: int) -> str:
        """Atomically deny local chat and persist an idempotent bank revoke intent.

        The caller must do this before deleting the browser session. A storage
        error propagates, so it cannot be mistaken for a bank acknowledgement.
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
                (session_id,owner,subject,expires,ledger_generation,state,next_attempt_at,created_at,updated_at)
                VALUES (?,?,?,?,?,'pending',?,?,?)""",
                (session_id, owner, subject, session_exp, row["ledger_generation"], now, now, now))
            generation = row["ledger_generation"]
            row = db.execute("SELECT owner,subject,expires,state,ledger_generation FROM pending_revocations WHERE session_id=?",
                             (session_id,)).fetchone()
            if (row is None or row["owner"] != owner or row["subject"] != subject
                    or row["expires"] != session_exp or row["ledger_generation"] != generation):
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

    def _finish_revoke(self, session_id: str, lease: str, *, expected_intent: tuple[str, str, int, str], confirmed: bool,
                       error_code: str | None = None) -> str:
        now = int(time.time())
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT owner,subject,expires,ledger_generation,state,attempts,lease_token
                FROM pending_revocations WHERE session_id=?""",
                             (session_id,)).fetchone()
            if row is None:
                return "absent"
            if (row["owner"], row["subject"], row["expires"], row["ledger_generation"]) != expected_intent:
                # A late ACK/failed lease belongs to the original intent only.
                # Never confirm or clean up a replacement/reconciled authority.
                return "unresolved"
            if row["state"] == "confirmed":
                return "confirmed"
            if confirmed:
                # An exact bank acknowledgement remains authoritative even
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
        expected_intent = (row["owner"], row["subject"], row["expires"], row["ledger_generation"])
        with self._connection() as db:
            binding = db.execute("""SELECT owner,expires,subject,customer_id,bank_context_id,ledger_generation FROM chat_sessions
                WHERE session_id=?""", (session_id,)).fetchone()
        mapped_customer = self._approved_subject_customers.get(row["subject"]) if self._configured else None
        if (not binding or binding["owner"] != row["owner"] or binding["expires"] != row["expires"]
                or not isinstance(row["ledger_generation"], str) or not _LEDGER_GENERATION.fullmatch(row["ledger_generation"])
                or binding["ledger_generation"] != row["ledger_generation"]
                or (binding["subject"] and binding["subject"] != row["subject"])
                or not mapped_customer or (binding["customer_id"] and binding["customer_id"] != mapped_customer)
                or row["owner"] != self._owner_for_subject(row["subject"])):
            return self._finish_revoke(session_id, lease, expected_intent=expected_intent, confirmed=False,
                                       error_code="revoke_configuration_unavailable")
        try:
            context = self._bank_context(row["subject"], session_id, row["expires"],
                                         binding["bank_context_id"], str(uuid.uuid4()),
                                         ledger_generation=row["ledger_generation"])
            await self._bank.revoke(context, timeout_seconds=_REVOKE_TIMEOUT)
        except asyncio.CancelledError:
            self._finish_revoke(session_id, lease, expected_intent=expected_intent, confirmed=False,
                                error_code="revoke_interrupted")
            raise
        except (ChatError, BankRPCError) as exc:
            return self._finish_revoke(session_id, lease, expected_intent=expected_intent, confirmed=False, error_code=exc.code)
        except Exception:
            # Neither response bodies nor credential-bearing exceptions enter
            # persistent diagnostics. The intent remains retryable.
            return self._finish_revoke(session_id, lease, expected_intent=expected_intent, confirmed=False,
                                       error_code="revoke_internal_error")
        return self._finish_revoke(session_id, lease, expected_intent=expected_intent, confirmed=True)

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
