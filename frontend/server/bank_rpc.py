"""Private host-to-MCP transport. This module grants no domain consent or retry.

``run_id`` and ``graph_revision`` are legacy MCP claim names carrying the actual
host operation UUID and reviewed host revision, never a claimed language run.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import inspect
import json
import math
from pathlib import Path
import re
import ssl
import time
from typing import Any, Callable
from urllib.parse import urlsplit
import uuid

import httpx
import jwt
import rfc8785
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


PROTOCOL_VERSION = "2025-11-25"
ASSERTION_META = "com.flujo.bank/assertion"
_MAX_REQUEST = 65536
_MAX_RESPONSE = 4 * 1024 * 1024
_SCOPES = {
    "banking_status": "bank:read",
    "list_my_transactions": "bank:read",
    "get_my_transaction": "bank:read",
    "prepare_unrecognized_charge": "bank:prepare",
    "confirm_simulated_intake": "bank:write",
    "read_intake_receipt": "bank:receipt",
    "create_verified_handoff": "bank:handoff",
    "read_verified_handoff": "bank:handoff-read",
}
_ERRORS = frozenset({
    "authorization_required", "authorization_denied", "invalid_arguments",
    "reference_unavailable", "snapshot_changed", "risk_data_unavailable",
    "handoff_required", "confirmation_required", "action_unverified",
    "dataset_unavailable", "data_quality_error", "invalid_date_window",
    "source_verification_unavailable", "service_unavailable", "server_busy",
    "bank_timeout", "bank_unreachable", "bank_http_error",
    "bank_invalid_response", "bank_authority_expired", "bank_tool_forbidden",
})


def _text(value: object) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= 128 and value == value.strip()
            and not any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value))


def _uuid(value: object) -> bool:
    try:
        return isinstance(value, str) and uuid.UUID(value).version == 4 and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


@dataclass(frozen=True)
class BankContext:
    """Trusted, persisted host authority; never constructed from model metadata."""
    subject: str
    session_id: str
    conversation_id: str
    operation_id: str
    host_revision: str
    session_expires: int
    ledger_generation: str
    admission_check: Callable[[], None] | None = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if (not all(_text(value) for value in (self.subject, self.session_id, self.conversation_id))
                or not _uuid(self.operation_id)
                or not isinstance(self.host_revision, str)
                or re.fullmatch(r"[a-f0-9]{40}", self.host_revision) is None
                or type(self.session_expires) is not int or self.session_expires <= 0
                or not isinstance(self.ledger_generation, str)
                or re.fullmatch(r"[a-f0-9]{64}", self.ledger_generation) is None
                or (self.admission_check is not None and
                    (not callable(self.admission_check) or inspect.iscoroutinefunction(self.admission_check)))):
            raise ValueError("invalid_bank_context")


class BankRPCError(Exception):
    """Fixed codes only. Delivery uncertainty must not cause an automatic retry."""
    def __init__(self, code: str, *, possibly_sent: bool = False):
        self.code = code if code in _ERRORS else "service_unavailable"
        self.possibly_sent = bool(possibly_sent)
        super().__init__(self.code)


def _json(value: bytes | str) -> Any:
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = item
        return result

    def constant(_):
        raise ValueError("nonfinite_json_number")

    return json.loads(value, object_pairs_hook=pairs, parse_constant=constant)


class BankRPC:
    """A separately configured bank signer and stateless JSON-RPC client.

    Injected transports are trusted server/test dependencies, never browser data.
    A fresh AsyncClient owns each call's transport lifetime. Shared injected
    transports must implement suitable ``aclose`` semantics themselves.
    """
    def __init__(self, config: dict[str, Any], *, transport: httpx.AsyncBaseTransport | None = None):
        keys = {"base_url", "service_token", "issuer", "audience", "kid", "signing_key_file", "ca_file"}
        if not isinstance(config, dict) or set(config) != keys:
            raise ValueError("invalid_bank_configuration")
        if (not isinstance(config["base_url"], str)
                or any(char.isspace() or ord(char) < 32 or ord(char) == 127
                       or 0xD800 <= ord(char) <= 0xDFFF for char in config["base_url"])):
            raise ValueError("invalid_bank_configuration")
        try:
            origin = urlsplit(config["base_url"])
            port = origin.port
        except ValueError:
            raise ValueError("invalid_bank_configuration") from None
        if (origin.scheme != "https" or not origin.hostname or origin.username or origin.password
                or origin.path not in {"", "/"} or origin.query or origin.fragment or port == 0
                or not isinstance(config["service_token"], str) or not 32 <= len(config["service_token"]) <= 4096
                or any(not 33 <= ord(char) <= 126 for char in config["service_token"])
                or not _text(config["issuer"]) or not _text(config["kid"])
                or config["audience"] != "banking-mcp"
                or not isinstance(config["signing_key_file"], str)
                or not isinstance(config["ca_file"], str)):
            raise ValueError("invalid_bank_configuration")
        key_file = Path(config["signing_key_file"])
        ca_file = Path(config["ca_file"])
        if not key_file.is_absolute() or not ca_file.is_absolute():
            raise ValueError("invalid_bank_configuration")
        try:
            key = serialization.load_pem_private_key(key_file.read_bytes(), password=None)
            ca_bytes = ca_file.read_bytes()
            self._tls = ssl.create_default_context(cafile=str(ca_file))
        except (OSError, ValueError, TypeError, ssl.SSLError):
            raise ValueError("invalid_bank_configuration") from None
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("invalid_bank_configuration")
        self._base_url = config["base_url"].rstrip("/")
        self._service_token = config["service_token"]
        self._issuer, self._audience, self._kid, self._key = config["issuer"], config["audience"], config["kid"], key
        self._transport = transport
        self.authority_identity = {"endpoint": self._base_url, "kid": self._kid,
            "signer_sha256": hashlib.sha256(key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw)).hexdigest(),
            "tls_ca_sha256": hashlib.sha256(ca_bytes).hexdigest()}

    @staticmethod
    def _timeout(value: float) -> float:
        if (type(value) not in {int, float} or not math.isfinite(value) or not 1 <= value <= 60):
            raise ValueError("invalid_bank_timeout")
        return float(value)

    @staticmethod
    def _current(context: BankContext, *, possibly_sent: bool = False) -> None:
        if not isinstance(context, BankContext):
            raise ValueError("invalid_bank_context")
        if context.session_expires <= time.time():
            raise BankRPCError("bank_authority_expired", possibly_sent=possibly_sent)
        if context.admission_check is not None:
            try:
                allowed = context.admission_check()
            except BankRPCError as exc:
                raise BankRPCError(exc.code, possibly_sent=possibly_sent or exc.possibly_sent) from None
            if inspect.isawaitable(allowed):
                if inspect.iscoroutine(allowed):
                    allowed.close()
                raise BankRPCError("authorization_denied", possibly_sent=possibly_sent)
            if allowed is False:
                raise BankRPCError("authorization_denied", possibly_sent=possibly_sent)

    def _assertion(self, tool: str, args: dict, context: BankContext, scope: str,
                   token_type: str, deadline: float) -> str:
        self._current(context)
        now = int(time.time())
        expires = min(now + 60, context.session_expires, math.floor(deadline))
        if expires <= now:
            raise BankRPCError("bank_authority_expired")
        return jwt.encode({"iss": self._issuer, "aud": self._audience, "sub": context.subject,
            "iat": now, "nbf": now, "exp": expires, "jti": str(uuid.uuid4()),
            "session_id": context.session_id, "conversation_id": context.conversation_id,
            "run_id": context.operation_id, "graph_revision": context.host_revision,
            "ledger_generation": context.ledger_generation,
            "tool": tool, "scope": [scope], "args_sha256": hashlib.sha256(rfc8785.dumps(args)).hexdigest()},
            self._key, algorithm="EdDSA", headers={"typ": token_type, "kid": self._kid})

    def _headers(self, *, protocol: bool = False) -> dict[str, str]:
        result = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                  "Authorization": "Bearer " + self._service_token}
        if protocol:
            result["MCP-Protocol-Version"] = PROTOCOL_VERSION
        return result

    async def _post(self, client: httpx.AsyncClient, path: str, body: dict, *,
                    protocol: bool, notification: bool = False, possibly_sent: bool = False) -> Any:
        try:
            wire = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise BankRPCError("invalid_arguments") from None
        if len(wire) > _MAX_REQUEST:
            raise BankRPCError("invalid_arguments")
        async with client.stream("POST", self._base_url + path, headers=self._headers(protocol=protocol),
                                 content=wire) as response:
            expected_status = 202 if notification else 200
            if response.status_code != expected_status:
                code = "authorization_denied" if response.status_code in {401, 403} else "bank_http_error"
                raise BankRPCError(code, possibly_sent=possibly_sent)
            if "mcp-session-id" in response.headers:
                raise BankRPCError("bank_invalid_response", possibly_sent=possibly_sent)
            parts, size = [], 0
            async for part in response.aiter_bytes():
                size += len(part)
                if size > _MAX_RESPONSE:
                    raise BankRPCError("bank_invalid_response", possibly_sent=possibly_sent)
                parts.append(part)
            raw = b"".join(parts)
            if notification:
                if raw:
                    raise BankRPCError("bank_invalid_response", possibly_sent=possibly_sent)
                return None
            if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise BankRPCError("bank_invalid_response", possibly_sent=possibly_sent)
            try:
                return _json(raw)
            except (ValueError, TypeError, UnicodeError, RecursionError):
                raise BankRPCError("bank_invalid_response", possibly_sent=possibly_sent) from None

    @staticmethod
    def _result(envelope: Any, request_id: str, *, possibly_sent: bool) -> dict:
        if (not isinstance(envelope, dict) or envelope.get("jsonrpc") != "2.0"
                or envelope.get("id") != request_id or set(envelope) != {"jsonrpc", "id", "result"}
                or not isinstance(envelope["result"], dict)):
            raise BankRPCError("bank_invalid_response", possibly_sent=possibly_sent)
        return envelope["result"]

    async def call(self, tool: str, arguments: dict, context: BankContext, *, timeout_seconds: float = 45) -> dict:
        """One tool dispatch. Raw results are not verified public action states."""
        if not isinstance(tool, str) or tool not in _SCOPES:
            raise BankRPCError("bank_tool_forbidden")
        if not isinstance(arguments, dict) or "customer_id" in arguments or "conversation_id" in arguments:
            raise BankRPCError("invalid_arguments")
        try:
            # Freeze caller data before the first await, and reject non-JSON values.
            args = _json(rfc8785.dumps(arguments))
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise BankRPCError("invalid_arguments") from None
        self._current(context)
        timeout = self._timeout(timeout_seconds)
        deadline = time.time() + timeout
        sent = False
        try:
            async with asyncio.timeout(timeout), httpx.AsyncClient(
                    timeout=httpx.Timeout(timeout, connect=min(10, timeout)), transport=self._transport,
                    verify=self._tls, trust_env=False, follow_redirects=False) as client:
                initialize_id = str(uuid.uuid4())
                initialized = await self._post(client, "/mcp", {"jsonrpc": "2.0", "id": initialize_id,
                    "method": "initialize", "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                    "clientInfo": {"name": "hackathon-bank-host", "version": "host-direct-mcp/v1"}}}, protocol=False)
                result = self._result(initialized, initialize_id, possibly_sent=False)
                if (result.get("protocolVersion") != PROTOCOL_VERSION or not isinstance(result.get("capabilities"), dict)
                        or not isinstance(result["capabilities"].get("tools"), dict)
                        or not isinstance(result.get("serverInfo"), dict)
                        or result["serverInfo"].get("name") != "banking-mcp"
                        or not _text(result["serverInfo"].get("version"))):
                    raise BankRPCError("bank_invalid_response")
                await self._post(client, "/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"},
                                 protocol=True, notification=True)
                assertion = self._assertion(tool, args, context, _SCOPES[tool], "bank-mcp+jwt", deadline)
                request_id = str(uuid.uuid4())
                sent = True
                response = await self._post(client, "/mcp", {"jsonrpc": "2.0", "id": request_id,
                    "method": "tools/call", "params": {"name": tool, "arguments": args,
                    "_meta": {ASSERTION_META: assertion}}}, protocol=True, possibly_sent=True)
                result = self._result(response, request_id, possibly_sent=True)
                structured, content = result.get("structuredContent"), result.get("content")
                is_error = result.get("isError", False)
                if (not isinstance(structured, dict) or type(is_error) is not bool
                        or set(result) - {"structuredContent", "content", "isError"}
                        or not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], dict)
                        or set(content[0]) != {"type", "text"}
                        or content[0].get("type") != "text" or not isinstance(content[0].get("text"), str)
                        or len(content[0]["text"]) > 65536):
                    raise BankRPCError("bank_invalid_response", possibly_sent=True)
                try:
                    coherent = rfc8785.dumps(_json(content[0]["text"])) == rfc8785.dumps(structured)
                except (ValueError, TypeError, UnicodeError, RecursionError):
                    coherent = False
                if not coherent:
                    raise BankRPCError("bank_invalid_response", possibly_sent=True)
                if is_error:
                    if set(structured) != {"error"} or not isinstance(structured["error"], str):
                        raise BankRPCError("bank_invalid_response", possibly_sent=True)
                    raise BankRPCError(structured["error"], possibly_sent=structured["error"] != "server_busy")
                if "error" in structured:
                    raise BankRPCError("bank_invalid_response", possibly_sent=True)
                self._current(context, possibly_sent=True)
                return structured
        except BankRPCError:
            raise
        except (httpx.TimeoutException, TimeoutError):
            raise BankRPCError("bank_timeout", possibly_sent=sent) from None
        except httpx.HTTPError:
            raise BankRPCError("bank_unreachable", possibly_sent=sent) from None

    async def revoke(self, context: BankContext, *, timeout_seconds: float = 10) -> None:
        """One fresh signed revocation attempt; the host owns durable delivery."""
        self._current(context)
        timeout = self._timeout(timeout_seconds)
        assertion = self._assertion("revoke_session", {}, context, "bank:revoke", "bank-revoke+jwt",
                                    time.time() + timeout)
        try:
            async with asyncio.timeout(timeout), httpx.AsyncClient(
                    timeout=httpx.Timeout(timeout, connect=min(10, timeout)), transport=self._transport,
                    verify=self._tls, trust_env=False, follow_redirects=False) as client:
                result = await self._post(client, "/internal/revoke", {"assertion": assertion},
                                          protocol=False, possibly_sent=True)
                if result != {"revoked": True} or result.get("revoked") is not True:
                    raise BankRPCError("bank_invalid_response", possibly_sent=True)
        except BankRPCError:
            raise
        except (httpx.TimeoutException, TimeoutError):
            raise BankRPCError("bank_timeout", possibly_sent=True) from None
        except httpx.HTTPError:
            raise BankRPCError("bank_unreachable", possibly_sent=True) from None
