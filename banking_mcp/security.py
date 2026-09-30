"""Verified authority and opaque references. Selectors alone never authorize bound reads."""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import jwt
import rfc8785

from .config import Config

ASSERTION_META = "com.flujo.bank/assertion"
TOKEN_TYPE = "bank-mcp+jwt"
MAX_ASSERTION_TTL = 60


class _DatabaseGate:
    def __init__(self):
        self.lock = threading.RLock()


_GATES: weakref.WeakValueDictionary[Path, _DatabaseGate] = weakref.WeakValueDictionary()
_GATES_LOCK = threading.Lock()


def _database_gate(path: Path) -> _DatabaseGate:
    # Separate StateStore objects for the same file must share admission too.
    # Weak values release the registry entry once its last store is gone.
    with _GATES_LOCK:
        gate = _GATES.get(path)
        if gate is None:
            gate = _DatabaseGate()
            _GATES[path] = gate
        return gate


class BankError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def arguments_digest(args: dict) -> str:
    return hashlib.sha256(rfc8785.dumps(args)).hexdigest()


@dataclass(frozen=True)
class Principal:
    subject: str
    customer: str
    session: str
    conversation: str
    expires: int

    def binding(self) -> str:
        return arguments_digest({"sub": self.subject, "customer": self.customer,
                                 "session": self.session, "conversation": self.conversation})


class StateStore:
    """Short serialized SQLite operations; durable replay/revocation and capability state.

    SQLite has one writer. Serialize the entire connection lifetime within this
    process, including reads/close, to prevent writer starvation and overlapping
    last-connection WAL checkpoints/recovery on Windows. No data/provider work
    runs under this gate. Other processes still use SQLite locking and timeout.
    """
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path.resolve()
        self._gate = _database_gate(self.path)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS replays(jti TEXT PRIMARY KEY, expires INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS revoked(session TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS sessions(session TEXT PRIMARY KEY, subject TEXT NOT NULL, customer TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS capabilities(
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, binding TEXT NOT NULL,
                    expires INTEGER NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS action_pending(
                    id TEXT PRIMARY KEY, binding TEXT NOT NULL, customer TEXT NOT NULL,
                    transaction_id TEXT NOT NULL, snapshot TEXT NOT NULL,
                    action TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT,
                    facts TEXT NOT NULL, expires INTEGER NOT NULL,
                    evidence_digest TEXT, request_key TEXT, result_json TEXT,
                    confirmation_state TEXT);
                CREATE TABLE IF NOT EXISTS sandbox_cases(
                    id TEXT PRIMARY KEY, customer TEXT NOT NULL, transaction_id TEXT NOT NULL,
                    action TEXT NOT NULL, snapshot TEXT NOT NULL, created_at REAL NOT NULL,
                    facts TEXT NOT NULL, UNIQUE(customer, transaction_id, action));
                CREATE INDEX IF NOT EXISTS sandbox_cases_recent ON sandbox_cases(customer, created_at);
                CREATE TABLE IF NOT EXISTS sandbox_case_receipts(
                    case_id TEXT PRIMARY KEY, receipt_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sandbox_handoffs(
                    id TEXT PRIMARY KEY, binding TEXT NOT NULL, customer TEXT NOT NULL,
                    transaction_id TEXT, snapshot TEXT, reason TEXT NOT NULL,
                    created_at INTEGER NOT NULL, facts TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS sandbox_ledger_identity(
                    id INTEGER PRIMARY KEY CHECK(id=1), generation TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sandbox_coverage(
                    id INTEGER PRIMARY KEY CHECK(id=1), generation TEXT NOT NULL,
                    coverage_start INTEGER NOT NULL, provenance_digest TEXT NOT NULL,
                    attested_at INTEGER NOT NULL);
            """)
            # Pending handles from an earlier local prototype schema must not
            # become confirmable without the new pinned evidence check.
            columns = {row[1] for row in db.execute("PRAGMA table_info(action_pending)")}
            if "evidence_digest" not in columns:
                db.execute("ALTER TABLE action_pending ADD COLUMN evidence_digest TEXT")
            if "request_key" not in columns:
                db.execute("ALTER TABLE action_pending ADD COLUMN request_key TEXT")
            if "result_json" not in columns:
                db.execute("ALTER TABLE action_pending ADD COLUMN result_json TEXT")
            if "confirmation_state" not in columns:
                # NULL preserves uncertainty for legacy prepared records.
                # Only a new authorized prepare may mark an intent prepared.
                db.execute("ALTER TABLE action_pending ADD COLUMN confirmation_state TEXT")
            handoff_columns = {row[1] for row in db.execute("PRAGMA table_info(sandbox_handoffs)")}
            if "packet_json" not in handoff_columns:
                # Legacy packets remain unverified; initialization must not
                # manufacture saved questions or charge evidence for them.
                db.execute("ALTER TABLE sandbox_handoffs ADD COLUMN packet_json TEXT")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS action_pending_request_key ON action_pending(request_key)")
            db.execute("INSERT OR IGNORE INTO sandbox_ledger_identity VALUES (1, ?)",
                       (secrets.token_hex(32),))

    def attest_sandbox_coverage(self, start: int, provenance: str) -> None:
        """Explicit trusted initialization; config alone never backdates a new DB."""
        if (type(start) is not int or start <= 0 or start > int(time.time()) - 86400
                or not isinstance(provenance, str) or not provenance.startswith("synthetic:")
                or not 16 <= len(provenance) <= 160):
            raise ValueError("invalid sandbox coverage attestation")
        digest = hashlib.sha256(provenance.encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            identity = db.execute("SELECT generation FROM sandbox_ledger_identity WHERE id=1").fetchone()
            if not identity or len(identity[0]) != 64:
                raise BankError("risk_data_unavailable")
            existing = db.execute("SELECT generation,coverage_start,provenance_digest FROM sandbox_coverage WHERE id=1").fetchone()
            if existing:
                if existing != (identity[0], start, digest):
                    raise BankError("risk_data_unavailable")
                return
            db.execute("INSERT INTO sandbox_coverage VALUES (1,?,?,?,?)",
                       (identity[0], start, digest, int(time.time())))

    @staticmethod
    def sandbox_coverage_complete(db: sqlite3.Connection, configured_start: int | None, now: float) -> bool:
        if configured_start is None or configured_start > now - 86400:
            return False
        row = db.execute("""SELECT i.generation,c.generation,c.coverage_start,c.provenance_digest
            FROM sandbox_ledger_identity i LEFT JOIN sandbox_coverage c ON c.id=1 WHERE i.id=1""").fetchone()
        return bool(row and isinstance(row[0], str) and len(row[0]) == 64
                    and row[1] == row[0] and type(row[2]) is int
                    and row[2] == configured_start and isinstance(row[3], str)
                    and len(row[3]) == 64)

    @contextmanager
    def connect(self):
        with self._gate.lock:
            db = sqlite3.connect(self.path, timeout=10)
            try:
                with db:
                    yield db
            finally:
                db.close()

    def consume(self, jti: str, expires: int):
        with self.connect() as db:
            db.execute("DELETE FROM replays WHERE expires < ?", (int(time.time()) - 5,))
            try:
                db.execute("INSERT INTO replays VALUES (?,?)", (jti, expires))
            except sqlite3.IntegrityError:
                raise BankError("authorization_denied") from None

    def bind_session(self, principal: Principal):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO sessions VALUES (?,?,?)",
                       (principal.session, principal.subject, principal.customer))
            row = db.execute("SELECT subject,customer FROM sessions WHERE session=?", (principal.session,)).fetchone()
            if row != (principal.subject, principal.customer):
                raise BankError("authorization_denied")

    def revoke(self, session: str):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO revoked VALUES (?)", (session,))

    def is_revoked(self, session: str) -> bool:
        with self.connect() as db:
            return db.execute("SELECT 1 FROM revoked WHERE session=?", (session,)).fetchone() is not None

    def put(self, kind: str, principal: Principal, payload: dict) -> str:
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("DELETE FROM capabilities WHERE expires < ?", (int(time.time()),))
            db.execute("INSERT INTO capabilities VALUES (?,?,?,?,?)", (
                hashlib.sha256(token.encode()).hexdigest(), kind, principal.binding(),
                int(time.time()) + 900, json.dumps(payload)))
        return token

    def get(self, token: str, kind: str, principal: Principal) -> dict:
        if not isinstance(token, str) or not 32 <= len(token) <= 64:
            raise BankError("reference_unavailable")
        with self.connect() as db:
            row = db.execute("SELECT binding, expires, payload FROM capabilities WHERE id=? AND kind=?",
                             (hashlib.sha256(token.encode()).hexdigest(), kind)).fetchone()
        if not row or row[1] <= time.time() or not secrets.compare_digest(row[0], principal.binding()):
            raise BankError("reference_unavailable")
        return json.loads(row[2])


class Authorizer:
    def __init__(self, config: Config, store: StateStore):
        self.config, self.store = config, store

    def authorize(self, tool: str, args: dict, meta: dict | None, scope: str = "bank:read") -> Principal:
        if self.config.mode == "operator-test":
            customer, conversation = args.get("customer_id"), args.get("conversation_id")
            if (not isinstance(customer, str) or customer not in self.config.approved_customers
                or not isinstance(conversation, str) or not 1 <= len(conversation) <= 128
                or any(c.isspace() or ord(c) < 32 for c in conversation)
                or "@" in conversation or "${" in conversation):
                raise BankError("authorization_denied")
            # A/B selection is intentionally permitted in a private test thread. Handles
            # still bind its customer and conversation independently, including on restart.
            principal = Principal("operator-test", customer, "operator-test", conversation,
                                  int(time.time()) + MAX_ASSERTION_TTL)
        elif self.config.mode == "synthetic-demo":
            principal = Principal("synthetic-demo", self.config.demo_customer, "synthetic-demo",
                                  "synthetic-demo", int(time.time()) + MAX_ASSERTION_TTL)
        else:
            token = (meta or {}).get(ASSERTION_META)
            principal = self._verify(token, tool, args, TOKEN_TYPE, scope)
        # Even a validly signed caller cannot change the mapped customer or conversation.
        for name, expected in (("customer_id", principal.customer), ("conversation_id", principal.conversation)):
            if name in args and args[name] != expected:
                raise BankError("authorization_denied")
        return principal

    def revoke_assertion(self, token: str):
        if self.config.mode != "delegated":
            raise BankError("authorization_denied")
        principal = self._verify(token, "revoke_session", {}, "bank-revoke+jwt", "bank:revoke", revocation=True)
        self.store.revoke(principal.session)

    def _verify(self, token, tool: str, args: dict, token_type: str, scope: str, revocation=False) -> Principal:
        if not isinstance(token, str):
            raise BankError("authorization_required")
        if len(token) > 8192:
            raise BankError("authorization_denied")
        try:
            header = jwt.get_unverified_header(token)
            if set(header) != {"typ", "alg", "kid"} or header["typ"] != token_type or header["alg"] != "EdDSA":
                raise ValueError("header")
            key = self.config.public_keys[header["kid"]]
            claims = jwt.decode(token, key, algorithms=["EdDSA"], audience=self.config.audience,
                                issuer=self.config.issuer, leeway=0,
                                options={"require": ["iss", "aud", "sub", "iat", "nbf", "exp", "jti",
                                                     "session_id", "conversation_id", "run_id", "graph_revision",
                                                     "tool", "scope", "args_sha256"]})
            if set(claims) != {"iss", "aud", "sub", "iat", "nbf", "exp", "jti", "session_id",
                               "conversation_id", "run_id", "graph_revision", "tool", "scope", "args_sha256"}:
                raise ValueError("claims")
            for name in ("sub", "jti", "session_id", "conversation_id", "run_id", "graph_revision"):
                if not isinstance(claims[name], str) or not 1 <= len(claims[name]) <= 128:
                    raise ValueError("claim")
            if any(type(claims[k]) is not int for k in ("iat", "nbf", "exp")):
                raise ValueError("time")
            if not 0 < claims["exp"] - claims["iat"] <= MAX_ASSERTION_TTL or claims["nbf"] != claims["iat"]:
                raise ValueError("ttl")
            if claims["aud"] != self.config.audience or claims["tool"] != tool or claims["scope"] != [scope]:
                raise ValueError("scope")
            if not secrets.compare_digest(claims["args_sha256"], arguments_digest(args)):
                raise ValueError("arguments")
            customer = self.config.principal_customers[claims["sub"]]
            principal = Principal(claims["sub"], customer, claims["session_id"],
                                  claims["conversation_id"], claims["exp"])
            self.store.bind_session(principal)
            if not revocation:
                self.assert_current(principal)
            self.store.consume(claims["jti"], claims["exp"])
            return principal
        except BankError:
            raise
        except (jwt.PyJWTError, ValueError, TypeError, KeyError):
            raise BankError("authorization_denied") from None

    def assert_current(self, principal: Principal):
        if principal.expires <= time.time():
            raise BankError("authorization_denied")
        # A state operation can wait behind a writer. Recheck expiry after that
        # wait, including at the final result fence; never extend the assertion.
        if self.store.is_revoked(principal.session) or principal.expires <= time.time():
            raise BankError("authorization_denied")
