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
_MAX_RESPONSE = 4 * 1024 * 1024
_TIMEOUT = 450


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
        self._db_path = Path(state_dir) / "frontend-chat.sqlite3"
        # Injectable only by trusted server/test code, never request data.
        self._transport: httpx.AsyncBaseTransport | None = None
        if not config:
            return
        try:
            self._configure(config)
        except (ValueError, TypeError, KeyError, OSError):
            self._reason = "La conexión segura del asistente requiere configuración."
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires INTEGER NOT NULL,
                conversation_id TEXT, revoked INTEGER NOT NULL DEFAULT 0,
                active_id TEXT, active_until INTEGER NOT NULL DEFAULT 0
            )""")
        self._configured = True

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
                "read_only": True,
                **({} if available else {"reason": self._reason if not self._configured
                    else "El asistente no está habilitado para este perfil de demostración."})}

    def _identity(self, customer_id: str, session_id: str, session_exp: int) -> tuple[str, str]:
        if not self.status(customer_id)["available"]:
            raise ChatError("chat_unavailable", 503, self.status(customer_id)["reason"])
        now = int(time.time())
        if (not isinstance(session_id, str) or not 16 <= len(session_id) <= 128
                or not isinstance(session_exp, int) or isinstance(session_exp, bool)
                or session_exp <= now or session_exp > now + 8 * 3600):
            raise ChatError("session_expired", 401, "Tu sesión expiró. Vuelve a ingresar.")
        subject = self._customer_subjects[customer_id]
        owner = hashlib.sha256(json.dumps([self._issuer, subject, self._model],
                                         separators=(",", ":")).encode()).hexdigest()
        return subject, owner

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

    async def send(self, customer_id: str, session_id: str, session_exp: int, message: str) -> dict[str, Any]:
        subject, owner = self._identity(customer_id, session_id, session_exp)
        if (not isinstance(message, str) or not message.strip() or len(message.strip()) > 4096
                or len(message.encode("utf-8")) > 12000):
            raise ChatError("invalid_message", 400, "Escribe una consulta de hasta 4096 caracteres.")
        operation = str(uuid.uuid4())
        now = int(time.time())
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._bind(db, session_id, owner, session_exp)
            if row["revoked"]:
                raise ChatError("session_expired", 401, "Tu sesión expiró. Vuelve a ingresar.")
            if row["active_until"] > now:
                raise ChatError("chat_busy", 429, "Espera la respuesta de tu consulta anterior.")
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

    async def revoke(self, customer_id: str, session_id: str, session_exp: int) -> None:
        if not self.status(customer_id)["available"]:
            return
        subject, owner = self._identity(customer_id, session_id, session_exp)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._bind(db, session_id, owner, session_exp)
            db.execute("UPDATE chat_sessions SET revoked = 1 WHERE session_id = ?", (session_id,))
        # Local revocation is durable before requesting the worker's independent
        # durable revocation, which also aborts all matching admitted work.
        result = await self._post("/v1/banking/session/revoke", self._headers(subject, session_id, session_exp), {},
                                  timeout_seconds=10)
        if result != {"revoked": True}:
            raise ChatError("chat_revocation_failed", 502, "No se pudo confirmar el cierre del asistente.")
