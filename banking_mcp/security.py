"""Request authority and opaque references; none of these are model arguments."""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import jwt
import rfc8785

from .config import Config

ASSERTION_META = "com.flujo.bank/assertion"
TOKEN_TYPE = "bank-mcp+jwt"
MAX_ASSERTION_TTL = 60


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
    """One SQLite connection per operation, durable replay/revocation and capability state."""
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS replays(jti TEXT PRIMARY KEY, expires INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS revoked(session TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS capabilities(
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, binding TEXT NOT NULL,
                    expires INTEGER NOT NULL, payload TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
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

    def authorize(self, tool: str, args: dict, meta: dict | None) -> Principal:
        if self.config.mode == "synthetic-demo":
            return Principal("synthetic-demo", self.config.demo_customer, "synthetic-demo",
                             "synthetic-demo", int(time.time()) + MAX_ASSERTION_TTL)
        token = (meta or {}).get(ASSERTION_META)
        if not isinstance(token, str):
            raise BankError("authorization_required")
        if len(token) > 8192:
            raise BankError("authorization_denied")
        try:
            header = jwt.get_unverified_header(token)
            if set(header) != {"typ", "alg", "kid"} or header["typ"] != TOKEN_TYPE or header["alg"] != "EdDSA":
                raise ValueError("header")
            key = self.config.public_keys[header["kid"]]
            claims = jwt.decode(token, key, algorithms=["EdDSA"], audience=self.config.audience,
                                issuer=self.config.issuer, leeway=0,
                                options={"require": ["iss", "aud", "sub", "iat", "nbf", "exp", "jti",
                                                     "session_id", "conversation_id", "run_id", "graph_revision",
                                                     "tool", "scope", "args_sha256"]})
            for name in ("sub", "jti", "session_id", "conversation_id", "run_id", "graph_revision"):
                if not isinstance(claims[name], str) or not 1 <= len(claims[name]) <= 128:
                    raise ValueError("claim")
            if any(type(claims[k]) is not int for k in ("iat", "nbf", "exp")):
                raise ValueError("time")
            if not 0 < claims["exp"] - claims["iat"] <= MAX_ASSERTION_TTL or claims["nbf"] != claims["iat"]:
                raise ValueError("ttl")
            if claims["aud"] != self.config.audience or claims["tool"] != tool or claims["scope"] != ["bank:read"]:
                raise ValueError("scope")
            if not secrets.compare_digest(claims["args_sha256"], arguments_digest(args)):
                raise ValueError("arguments")
            customer = self.config.principal_customers[claims["sub"]]
            principal = Principal(claims["sub"], customer, claims["session_id"],
                                  claims["conversation_id"], claims["exp"])
            self.assert_current(principal)
            self.store.consume(claims["jti"], claims["exp"])
            return principal
        except BankError:
            raise
        except (jwt.PyJWTError, ValueError, TypeError, KeyError):
            raise BankError("authorization_denied") from None

    def assert_current(self, principal: Principal):
        if principal.expires <= time.time() or self.store.is_revoked(principal.session):
            raise BankError("authorization_denied")
