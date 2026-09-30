"""Opt-in, one-shot confirm-response loss for an isolated generated fixture.

The real host normally recovers inline with its same-handle receipt POST. This
helper withholds only the confirm response; it never retries confirm or blocks
receipt/status recovery. No server, network transport, clock or CLI is created.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import re
import tempfile
from typing import Awaitable, Callable
from urllib.parse import urlsplit

import httpx
import rfc8785

from frontend.server.action import verified_receipt
from .frontend_fault import (
    FaultVerificationError, FileConsumedJournal, FixtureScope, HostPrepareIntent,
    IdentityVerifier, InnerFactory, PrepareBinding, VerifiedIdentity,
    _binding_valid, _hash, _intent_valid, _json, _observe, _timestamp, canonical_digest,
)


_MAX_BODY = 4 * 1024 * 1024


@dataclass(frozen=True)
class ConfirmScope:
    fixture: FixtureScope
    original_intent: HostPrepareIntent
    target_reference: str
    pending_handle_sha256: str

    def __post_init__(self) -> None:
        if (not isinstance(self.fixture, FixtureScope) or self.fixture.expected_outcome != "pending_confirmation"
                or not isinstance(self.original_intent, HostPrepareIntent)
                or not _binding_valid(self.fixture, self.original_intent.binding)
                or not _intent_valid(self.fixture, self.original_intent.binding, self.original_intent)
                or not isinstance(self.target_reference, str) or not re.fullmatch(r"txn_[a-f0-9]{24}", self.target_reference)
                or not _hash(self.pending_handle_sha256)):
            raise FaultVerificationError("invalid original-bound confirmation scope")

    @property
    def digest(self) -> str:
        return canonical_digest({"schema": "synthetic-confirm-scope/v1", "fixture_scope_digest": self.fixture.digest,
                                 "original_intent": asdict(self.original_intent), "target_reference": self.target_reference,
                                 "pending_handle_sha256": self.pending_handle_sha256})


@dataclass(frozen=True)
class ConfirmCommitProof:
    """Actual read-only MCP row proof; no raw capability or receipt body retained."""
    scope_digest: str
    binding: PrepareBinding
    pending_handle_sha256: str
    response_sha256: str
    pending_row_digest: str
    case_id: str
    case_row_digest: str
    receipt_row_digest: str
    receipt_sha256: str


@dataclass(frozen=True)
class ConfirmConsumedDrop:
    scope_digest: str
    intent: HostPrepareIntent
    proof: ConfirmCommitProof
    digest: str


ConfirmationResolver = Callable[[HostPrepareIntent, str, str], Awaitable[HostPrepareIntent | None]]
ConfirmationVerifier = Callable[[ConfirmScope, str, dict], Awaitable[ConfirmCommitProof | None]]
ConfirmRecorder = Callable[[ConfirmConsumedDrop], Awaitable[bool]]


def _confirmation_intent_valid(scope: ConfirmScope, intent: object) -> bool:
    return (_intent_valid(scope.fixture, scope.original_intent.binding, intent)
            and intent.action_id == scope.original_intent.action_id
            and intent.revision > scope.original_intent.revision)


def _proof_valid(scope: ConfirmScope, proof: object, *, response_digest: str | None = None,
                 receipt: dict | None = None) -> bool:
    return (isinstance(proof, ConfirmCommitProof) and proof.scope_digest == scope.digest
            and proof.binding == scope.original_intent.binding
            and proof.pending_handle_sha256 == scope.pending_handle_sha256
            and all(_hash(value) for value in (proof.response_sha256, proof.pending_row_digest,
                                               proof.case_row_digest, proof.receipt_row_digest, proof.receipt_sha256))
            and isinstance(proof.case_id, str) and re.fullmatch(r"CMP-SBX-[A-Za-z0-9_-]{8}", proof.case_id) is not None
            and (response_digest is None or response_digest == proof.response_sha256)
            and (receipt is None or proof.case_id == receipt["id"] and proof.receipt_sha256 == canonical_digest(receipt)))


def _marker_digest(scope_digest: str, intent: HostPrepareIntent, proof: ConfirmCommitProof) -> str:
    return canonical_digest({"schema": "synthetic-confirm-drop/v1", "scope_digest": scope_digest,
                             "intent": asdict(intent), "proof": asdict(proof)})


def validate_confirm_consumed(scope: ConfirmScope, marker: object) -> None:
    if (not isinstance(marker, ConfirmConsumedDrop) or marker.scope_digest != scope.digest
            or not _confirmation_intent_valid(scope, marker.intent) or not _proof_valid(scope, marker.proof)
            or marker.digest != _marker_digest(scope.digest, marker.intent, marker.proof)):
        raise FaultVerificationError("confirm consumption is not bound to the original intent")


def _loaded_marker(value: object) -> ConfirmConsumedDrop:
    try:
        if not isinstance(value, dict) or set(value) != {"scope_digest", "intent", "proof", "digest"}:
            raise ValueError()
        intent, proof = value["intent"], value["proof"]
        if (not isinstance(intent, dict) or set(intent) != {"scope_digest", "binding", "action_id", "revision", "session_exp"}
                or not isinstance(proof, dict) or set(proof) != {"scope_digest", "binding", "pending_handle_sha256",
                    "response_sha256", "pending_row_digest", "case_id", "case_row_digest", "receipt_row_digest", "receipt_sha256"}):
            raise ValueError()
        for nested in (intent, proof):
            if not isinstance(nested["binding"], dict) or set(nested["binding"]) != {
                    "request_id", "conversation_id", "transaction_id", "snapshot"}:
                raise ValueError()
        return ConfirmConsumedDrop(value["scope_digest"],
            HostPrepareIntent(**{**intent, "binding": PrepareBinding(**intent["binding"])}),
            ConfirmCommitProof(**{**proof, "binding": PrepareBinding(**proof["binding"])}), value["digest"])
    except (TypeError, ValueError, KeyError):
        raise FaultVerificationError("invalid confirm consumption schema") from None


class FileConfirmJournal(FileConsumedJournal):
    """Same explicit provenance/path/publication rules, separate confirm schema."""

    def __init__(self, scope: ConfirmScope, *, fixture_root: Path, path: Path):
        super().__init__(scope.fixture, fixture_root=fixture_root, path=path)
        self.confirm_scope = scope

    def load(self) -> ConfirmConsumedDrop | None:
        self._provenance()
        try:
            if not self.path.exists():
                return None
            if not self.path.resolve(strict=True).is_relative_to(self.root) or self.path.stat().st_size > 32768:
                raise ValueError()
            marker = _loaded_marker(_json(self.path.read_bytes()))
            validate_confirm_consumed(self.confirm_scope, marker)
            return marker
        except (OSError, ValueError, UnicodeError):
            raise FaultVerificationError("confirm journal cannot be verified") from None

    async def record(self, marker: ConfirmConsumedDrop) -> bool:
        self._provenance()
        validate_confirm_consumed(self.confirm_scope, marker)
        existing = self.load()
        if existing is not None:
            if existing != marker:
                raise FaultVerificationError("confirm journal cannot replace a different marker")
            return True
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix=".confirm-drop-", dir=self.path.parent)
            with os.fdopen(fd, "wb") as stream:
                stream.write(rfc8785.dumps(asdict(marker)))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, self.path)
            except FileExistsError:
                pass
            if self.load() != marker:
                raise FaultVerificationError("confirm consumption publication did not match")
            return True
        except OSError:
            raise FaultVerificationError("confirm consumption could not be durably published") from None
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)


class ConfirmDropTransport(httpx.AsyncBaseTransport):
    """Forward one real confirm; after consumed, block any repeat of that confirm.

    The trusted resolver must read the host's current action_unverified row,
    which legitimately omits request_id, against the captured prepare intent.
    Receipt POSTs and other requests pass through with fresh original headers.
    """

    def __init__(self, scope: ConfirmScope, *, inner_factory: InnerFactory,
                 verify_identity: IdentityVerifier, resolve_confirmation_intent: ConfirmationResolver,
                 verify_confirmation_commit: ConfirmationVerifier, record_consumed: ConfirmRecorder,
                 consumed: ConfirmConsumedDrop | None = None):
        self.scope = scope
        self._inner_factory = inner_factory
        self._verify_identity = verify_identity
        self._resolve_confirmation_intent = resolve_confirmation_intent
        self._verify_confirmation_commit = verify_confirmation_commit
        self._record_consumed = record_consumed
        self._consumed = consumed
        self._lock = asyncio.Lock()
        if consumed is not None:
            validate_confirm_consumed(scope, consumed)

    @property
    def consumed(self) -> ConfirmConsumedDrop | None:
        return self._consumed

    async def aclose(self) -> None:
        # The host's per-POST client teardown owns no shared inner resource.
        pass

    async def _forward(self, request: httpx.Request) -> httpx.Response:
        inner = self._inner_factory()
        if not isinstance(inner, httpx.AsyncBaseTransport) or inner is self:
            raise FaultVerificationError("inner factory must return a fresh async transport")
        response = None
        try:
            response = await inner.handle_async_request(request)
            await response.aread()
            if len(response.content) > _MAX_BODY:
                raise FaultVerificationError("upstream response exceeds harness bound")
            return response
        finally:
            if response is not None:
                await response.aclose()
            await inner.aclose()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        fixed, actual = urlsplit(self.scope.fixture.worker_origin), urlsplit(str(request.url))
        if ((actual.scheme, actual.hostname, actual.port) != (fixed.scheme, fixed.hostname, fixed.port)
                or actual.username is not None or actual.password is not None):
            raise FaultVerificationError("request is outside the fixed worker origin")
        if request.method != "POST" or actual.path != "/v1/banking/action" or actual.query or actual.fragment:
            return await self._forward(request)
        content = await request.aread()
        try:
            body = _json(content) if len(content) <= _MAX_BODY else None
        except (ValueError, UnicodeError):
            body = None
        if (not isinstance(body, dict) or set(body) != {"operation", "conversationId", "pendingHandle", "confirmed"}
                or body.get("operation") != "confirm" or body.get("confirmed") is not True
                or not isinstance(body.get("pendingHandle"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{32,64}", body["pendingHandle"])
                or hashlib.sha256(body["pendingHandle"].encode()).hexdigest() != self.scope.pending_handle_sha256):
            return await self._forward(request)
        if body.get("conversationId") != self.scope.original_intent.binding.conversation_id:
            raise FaultVerificationError("confirm conversation changed")
        handle = body["pendingHandle"]  # Never retained beyond this call.
        async with self._lock:
            if self._consumed is not None:
                raise FaultVerificationError("the consumed confirmation must not be repeated")
            identity = await _observe(self._verify_identity, request.headers)
            fixture = self.scope.fixture
            assertion = request.headers.get("X-Flujo-User-Assertion", "")
            if (not isinstance(identity, VerifiedIdentity) or not assertion
                    or identity.issuer != fixture.issuer or identity.subject != fixture.subject
                    or identity.frontend_session_id != fixture.frontend_session_id
                    or identity.session_exp != fixture.frontend_session_exp
                    or type(identity.jwt_exp) is not int or identity.jwt_exp > identity.session_exp
                    or identity.audience != "flujo-banking-ingress"
                    or identity.assertion_sha256 != hashlib.sha256(assertion.encode()).hexdigest()):
                raise FaultVerificationError("verified confirmation identity does not match")
            intent = await _observe(self._resolve_confirmation_intent, self.scope.original_intent, handle, self.scope.target_reference)
            if not _confirmation_intent_valid(self.scope, intent):
                raise FaultVerificationError("saved confirmation intent does not match")
            response = await self._forward(request)
            if response.status_code != 200:
                return response
            try:
                result = _json(response.content)
            except (ValueError, UnicodeError):
                raise FaultVerificationError("successful confirmation is not JSON evidence") from None
            if not isinstance(result, dict) or result.get("state") != "intake_verified":
                raise FaultVerificationError("confirmation did not return verified intake")
            receipt = verified_receipt(result.get("receipt"))
            if (receipt is None or receipt != result["receipt"] or receipt["snapshot"] != fixture.snapshot
                    or canonical_digest(receipt["transaction"]) != fixture.facts_sha256
                    or not _timestamp(receipt["created_at"], utc=True)):
                raise FaultVerificationError("confirmation receipt does not match saved fixture")
            proof = await _observe(self._verify_confirmation_commit, self.scope, handle, result)
            if not _proof_valid(self.scope, proof, response_digest=canonical_digest(result), receipt=receipt):
                raise FaultVerificationError("actual confirmation commit proof does not match")
            checked = await _observe(self._resolve_confirmation_intent, self.scope.original_intent, handle, self.scope.target_reference)
            if not _confirmation_intent_valid(self.scope, checked) or checked.revision < intent.revision:
                raise FaultVerificationError("confirmation intent changed during commit verification")
            marker = ConfirmConsumedDrop(self.scope.digest, intent, proof, _marker_digest(self.scope.digest, intent, proof))
            if await _observe(self._record_consumed, marker) is not True:
                raise FaultVerificationError("confirmation consumption was not durably recorded")
            self._consumed = marker
            raise httpx.ReadError("synthetic confirm response withheld after verified commit", request=request)
