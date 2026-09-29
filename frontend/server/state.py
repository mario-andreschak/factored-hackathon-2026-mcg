from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Session:
    id: str
    profile_id: str
    expires_at: int
    token_hash: str


class State:
    """Secrets, profile bindings and revocable sessions persist across restarts."""

    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "frontend.sqlite3"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY, customer_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, id TEXT UNIQUE NOT NULL,
                    profile_id TEXT NOT NULL, expires_at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS login_failures (client TEXT NOT NULL, occurred_at INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS failures_client ON login_failures(client, occurred_at);
            """)
            db.execute("INSERT OR IGNORE INTO settings VALUES ('reference_secret', ?)", (secrets.token_hex(32),))
            self.secret = bytes.fromhex(db.execute("SELECT value FROM settings WHERE key='reference_secret'").fetchone()[0])

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def customer(self, profile_id: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT customer_id FROM profiles WHERE id=?", (profile_id,)).fetchone()
            return row[0] if row else None

    def bind(self, profile_id: str, customer_id: str):
        with self.connect() as db:
            old = db.execute("SELECT customer_id FROM profiles WHERE id=?", (profile_id,)).fetchone()
            if not old or old[0] != customer_id:
                db.execute("DELETE FROM sessions WHERE profile_id=?", (profile_id,))
            db.execute("INSERT INTO profiles VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET customer_id=excluded.customer_id",
                       (profile_id, customer_id))

    def sessions_invalidated_by(self, fingerprint: str,
                                invite_bindings: dict[str, str] | None = None,
                                demo_bindings: dict[str, str] | None = None) -> list[tuple[Session, str | None]]:
        """Preview active sessions that the next auth reconciliation will remove.

        The caller persists any admitted FLUJO revocations before deleting these
        banking sessions. This runs during single-replica startup, before serving
        requests, so no other local writer can create new sessions meanwhile.
        """
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='auth_fingerprint'").fetchone()
            changed = bool(row and row[0] != fingerprint)
            rotate_all = changed or row is None
            rows = db.execute("""SELECT s.id,s.profile_id,s.expires_at,s.token_hash,p.customer_id
                FROM sessions s LEFT JOIN profiles p ON p.id=s.profile_id
                WHERE s.expires_at>?""", (int(time.time()),)).fetchall()
        invalidated = []
        for session_id, profile_id, expires_at, token_hash, old_customer in rows:
            target = ((invite_bindings or {}).get(profile_id) if invite_bindings is not None
                      else (demo_bindings or {}).get(profile_id))
            rebinding = target is not None and target != old_customer
            removed = invite_bindings is not None and profile_id not in invite_bindings
            if rotate_all or removed or rebinding:
                invalidated.append((Session(session_id, profile_id, expires_at, token_hash), old_customer))
        return invalidated

    def reconcile_auth(self, fingerprint: str, invite_bindings: dict[str, str] | None = None):
        """Rotate sessions with auth policy, and discard every stale invite binding."""
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='auth_fingerprint'").fetchone()
            changed = bool(row and row[0] != fingerprint)
            # An unversioned legacy session has no authenticated policy binding.
            # Retire it on the first migration, after startup queued any admitted
            # FLUJO revocation intent.
            if changed or row is None:
                db.execute("DELETE FROM sessions")
            if changed and invite_bindings is None:
                # Returning to the local demo must not reuse synthetic bindings.
                db.execute("DELETE FROM profiles")
            if invite_bindings is not None:
                allowed = tuple(invite_bindings)
                placeholders = ",".join("?" for _ in allowed)
                db.execute(f"DELETE FROM sessions WHERE profile_id NOT IN ({placeholders})", allowed)
                db.execute(f"DELETE FROM profiles WHERE id NOT IN ({placeholders})", allowed)
                for profile_id, customer_id in invite_bindings.items():
                    old = db.execute("SELECT customer_id FROM profiles WHERE id=?", (profile_id,)).fetchone()
                    if not old or old[0] != customer_id:
                        db.execute("DELETE FROM sessions WHERE profile_id=?", (profile_id,))
                    db.execute("INSERT INTO profiles VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET customer_id=excluded.customer_id",
                               (profile_id, customer_id))
            db.execute("INSERT INTO settings VALUES ('auth_fingerprint', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (fingerprint,))

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def create_session(self, profile_id: str, seconds: int) -> tuple[str, Session]:
        token = secrets.token_urlsafe(32)
        session = Session(secrets.token_urlsafe(24), profile_id, int(time.time()) + seconds, self.token_hash(token))
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires_at<=?", (int(time.time()),))
            db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)",
                       (session.token_hash, session.id, session.profile_id, session.expires_at))
        return token, session

    def session(self, token: str | None) -> Session | None:
        if not token or len(token) > 128:
            return None
        with self.connect() as db:
            row = db.execute("SELECT id, profile_id, expires_at, token_hash FROM sessions WHERE token_hash=? AND expires_at>?",
                             (self.token_hash(token), int(time.time()))).fetchone()
        return Session(*row) if row else None

    def delete_session(self, session: Session):
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (session.token_hash,))

    def login_allowed(self, client: str) -> bool:
        now = int(time.time())
        with self.connect() as db:
            db.execute("DELETE FROM login_failures WHERE occurred_at<?", (now - 300,))
            count = db.execute("SELECT count(*) FROM login_failures WHERE client=?", (client,)).fetchone()[0]
        return count < 10

    def record_failure(self, client: str):
        with self.connect() as db:
            db.execute("INSERT INTO login_failures VALUES (?, ?)", (client, int(time.time())))
