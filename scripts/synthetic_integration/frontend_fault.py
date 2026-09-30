"""Opt-in synthetic harness transport; no production activation or network default.

Every request is forwarded unchanged through a caller-owned factory. A matching
prepare response is withheld only after actual upstream success and injected
read-only observers verify the durable host intent and MCP commit. This is a
controlled ReadError after HTTP 200, not a literal socket drop or HTTP 429.

The factory must return a fresh transport for each request. ChatService closes
its AsyncClient after every POST; this wrapper's aclose deliberately owns no
shared resources. Attach it to the lifespan-created ChatService, not a second
service instance. Callbacks must inspect isolated generated-fixture state only.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Awaitable, Callable, Literal
from urllib.parse import urlsplit

import httpx
import rfc8785


_UUID = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}")
_HASH = re.compile(r"[a-f0-9]{64}")
_HANDLE = re.compile(r"[A-Za-z0-9_-]{32,64}")
_SNAPSHOT = re.compile(r"[A-Za-z0-9_-]{1,96}")
_FACT_LIMITS = {"transaction_reference": 16, "transaction_date": 40,
                "process_date": 10, "amount": 64, "currency": 8, "status": 80,
                "merchant": 160, "transaction_type": 80, "channel": 80, "product": 80}
_MAX_BODY = 4 * 1024 * 1024


class FaultVerificationError(RuntimeError):
    """Harness proof/configuration failed; never masquerades as a dropped response."""


def canonical_digest(value: object) -> str:
    """RFC 8785 SHA256, shared with read-only observers; contains no JWT material."""
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def _plain(value: object, limit: int) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= limit
            and not any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value))


def _hash(value: object) -> bool:
    return isinstance(value, str) and _HASH.fullmatch(value) is not None


@dataclass(frozen=True)
class FixtureScope:
    fixture_id: str
    source_fingerprint: str
    profile_id: str
    worker_origin: str
    issuer: str
    subject: str
    frontend_session_id: str
    frontend_session_exp: int
    frontend_model: str
    frontend_owner: str
    bank_deployment_id: str
    bank_session_id: str
    customer_id: str
    transaction_id: str
    snapshot: str
    facts_sha256: str
    ledger_generation: str
    expected_outcome: Literal["pending_confirmation", "handoff_verified"]
    generated_only: bool = True
    origin: str = "team-generated-prototype"

    def __post_init__(self) -> None:
        plain_fields = {"fixture_id": 128, "source_fingerprint": 256, "profile_id": 128,
                        "issuer": 512, "subject": 128, "frontend_session_id": 128,
                        "frontend_model": 256, "bank_deployment_id": 128,
                        "customer_id": 128, "transaction_id": 128}
        if not _plain(self.worker_origin, 512):
            raise FaultVerificationError("invalid fixed worker origin")
        parsed = urlsplit(self.worker_origin)
        if (any(not _plain(getattr(self, name), limit) for name, limit in plain_fields.items())
                or not isinstance(self.snapshot, str) or not _SNAPSHOT.fullmatch(self.snapshot)
                or not all(_hash(value) for value in (self.frontend_owner, self.bank_session_id,
                                                      self.facts_sha256, self.ledger_generation))
                or type(self.frontend_session_exp) is not int or self.frontend_session_exp <= 0
                or self.expected_outcome not in {"pending_confirmation", "handoff_verified"}
                or self.generated_only is not True or self.origin != "team-generated-prototype"
                or parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            raise FaultVerificationError("invalid generated fixture scope")
        # Force malformed port rejection without starting any networking.
        try:
            parsed.port
        except ValueError:
            raise FaultVerificationError("invalid fixed worker origin") from None

    @property
    def digest(self) -> str:
        return canonical_digest(asdict(self))


@dataclass(frozen=True)
class PrepareBinding:
    request_id: str
    conversation_id: str
    transaction_id: str
    snapshot: str


@dataclass(frozen=True)
class VerifiedIdentity:
    """Returned only after signature, issuer, audience and real-clock verification."""
    issuer: str
    subject: str
    frontend_session_id: str
    session_exp: int
    jwt_exp: int
    assertion_sha256: str
    audience: str = "flujo-banking-ingress"


@dataclass(frozen=True)
class HostPrepareIntent:
    scope_digest: str
    binding: PrepareBinding
    action_id: str
    revision: int
    session_exp: int


@dataclass(frozen=True)
class PrepareCommitProof:
    """Opaque read-only observer proof of the actual pending row and optional HOF.

    A verifier must read and compare actual isolated MCP rows, not derive this
    object from response prose. Digests describe those rows; no credentials are
    retained. HOF proof includes the saved packet, independent of currentness.
    """
    scope_digest: str
    binding: PrepareBinding
    pending_handle: str
    response_sha256: str
    pending_row_digest: str
    handoff_id: str | None = None
    handoff_packet_sha256: str | None = None
    handoff_row_digest: str | None = None


@dataclass(frozen=True)
class ConsumedCommitProof:
    """Journal-safe projection: even the pending capability is retained as a hash."""
    scope_digest: str
    binding: PrepareBinding
    pending_handle_sha256: str
    response_sha256: str
    pending_row_digest: str
    handoff_id: str | None = None
    handoff_packet_sha256: str | None = None
    handoff_row_digest: str | None = None


@dataclass(frozen=True)
class ConsumedDrop:
    scope_digest: str
    intent: HostPrepareIntent
    proof: ConsumedCommitProof
    digest: str


IdentityVerifier = Callable[[httpx.Headers], Awaitable[VerifiedIdentity | None]]
IntentResolver = Callable[[FixtureScope, PrepareBinding], Awaitable[HostPrepareIntent | None]]
CommitVerifier = Callable[[FixtureScope, PrepareBinding, dict], Awaitable[PrepareCommitProof | None]]
ConsumedRecorder = Callable[[ConsumedDrop], Awaitable[bool]]
InnerFactory = Callable[[], httpx.AsyncBaseTransport]


def _binding_valid(scope: FixtureScope, binding: object) -> bool:
    return (isinstance(binding, PrepareBinding)
            and isinstance(binding.request_id, str) and _UUID.fullmatch(binding.request_id) is not None
            and isinstance(binding.conversation_id, str) and _UUID.fullmatch(binding.conversation_id) is not None
            and binding.transaction_id == scope.transaction_id and binding.snapshot == scope.snapshot)


def _intent_valid(scope: FixtureScope, binding: PrepareBinding, intent: object) -> bool:
    return (isinstance(intent, HostPrepareIntent) and intent.scope_digest == scope.digest
            and intent.binding == binding and isinstance(intent.action_id, str)
            and _UUID.fullmatch(intent.action_id) is not None
            and type(intent.revision) is int and intent.revision >= 1
            and type(intent.session_exp) is int and intent.session_exp == scope.frontend_session_exp)


def _timestamp(value: object, *, utc: bool = False) -> bool:
    if not _plain(value, 40):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return not utc or parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0
    except (ValueError, TypeError):
        return False


def _facts_valid(facts: object) -> bool:
    if not isinstance(facts, dict) or set(facts) != set(_FACT_LIMITS):
        return False
    for key, limit in _FACT_LIMITS.items():
        value = facts[key]
        if key == "merchant" and value is None:
            continue
        if key in {"transaction_type", "channel", "product"} and value == "":
            continue
        if not _plain(value, limit):
            return False
    if (not re.fullmatch(r"txn_[a-f0-9]{12}", facts["transaction_reference"])
            or not _timestamp(facts["transaction_date"])
            or not re.fullmatch(r"[A-Z]{3}", facts["currency"])
            or not re.fullmatch(r"-?(?:0|[1-9]\d{0,15})(?:\.\d{1,2})?", facts["amount"])):
        return False
    try:
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", facts["process_date"])) and bool(date.fromisoformat(facts["process_date"]))
    except (ValueError, TypeError):
        return False


def _response_evidence(scope: FixtureScope, result: dict) -> tuple[str, str | None, str | None]:
    facts = result.get("transaction")
    handle = result.get("pending_handle")
    if (result.get("state") != scope.expected_outcome or result.get("snapshot") != scope.snapshot
            or result.get("action") != "simulated_intake" or not _facts_valid(facts)
            or canonical_digest(facts) != scope.facts_sha256
            or not isinstance(handle, str) or not _HANDLE.fullmatch(handle)):
        raise FaultVerificationError("prepare response does not match fixed fixture")
    if scope.expected_outcome == "pending_confirmation":
        if result.get("decision") != "intake" or result.get("reason") is not None or "handoff" in result:
            raise FaultVerificationError("unexpected pending prepare decision")
        return handle, None, None
    handoff = result.get("handoff")
    if (result.get("decision") != "handoff" or result.get("reason") != "missing_evidence"
            or not isinstance(handoff, dict)):
        raise FaultVerificationError("unexpected policy handoff decision")
    packet = handoff.get("packet")
    if (not isinstance(handoff.get("id"), str) or not re.fullmatch(r"HOF-[A-Za-z0-9_-]{8}", handoff["id"])
            or handoff.get("reason") != "missing_evidence" or handoff.get("snapshot") != scope.snapshot
            or handoff.get("facts") != facts or handoff.get("human_responded") is not False
            or not _timestamp(handoff.get("created_at"), utc=True)
            or handoff.get("transaction_currentness") not in {"same_snapshot", "different_snapshot", "unknown"}
            or not isinstance(packet, dict)
            or set(packet) != {"schema", "transaction", "transaction_provenance", "reason", "unanswered_questions", "human_responded"}
            or packet.get("schema") != "banking-sandbox-handoff/v1" or packet.get("transaction") != facts
            or packet.get("reason") != "missing_evidence" or packet.get("unanswered_questions") != []
            or packet.get("human_responded") is not False):
        raise FaultVerificationError("policy handoff readback is incomplete")
    provenance = packet.get("transaction_provenance")
    if (not isinstance(provenance, dict) or set(provenance) != {"source", "snapshot", "as_of"}
            or provenance.get("source") != "owned_serving_snapshot" or provenance.get("snapshot") != scope.snapshot
            or not _timestamp(provenance.get("as_of"), utc=True)
            or any(key in handoff and handoff[key] != packet[key]
                   for key in ("unanswered_questions", "transaction_provenance"))):
        raise FaultVerificationError("policy handoff provenance is incomplete")
    return handle, handoff["id"], canonical_digest(packet)


def _proof_valid(scope: FixtureScope, binding: PrepareBinding, proof: object,
                 *, response_digest: str | None = None, evidence: tuple | None = None) -> bool:
    if (not isinstance(proof, PrepareCommitProof) or proof.scope_digest != scope.digest or proof.binding != binding
            or not isinstance(proof.pending_handle, str) or not _HANDLE.fullmatch(proof.pending_handle)
            or not _hash(proof.response_sha256) or not _hash(proof.pending_row_digest)
            or response_digest is not None and proof.response_sha256 != response_digest):
        return False
    if scope.expected_outcome == "pending_confirmation":
        valid = proof.handoff_id is None and proof.handoff_packet_sha256 is None and proof.handoff_row_digest is None
    else:
        valid = (isinstance(proof.handoff_id, str) and re.fullmatch(r"HOF-[A-Za-z0-9_-]{8}", proof.handoff_id) is not None
                 and _hash(proof.handoff_packet_sha256) and _hash(proof.handoff_row_digest))
    return valid and (evidence is None or evidence == (proof.pending_handle, proof.handoff_id, proof.handoff_packet_sha256))


def _consumed_proof_valid(scope: FixtureScope, binding: PrepareBinding, proof: object) -> bool:
    if (not isinstance(proof, ConsumedCommitProof) or proof.scope_digest != scope.digest or proof.binding != binding
            or not all(_hash(value) for value in (proof.pending_handle_sha256, proof.response_sha256, proof.pending_row_digest))):
        return False
    if scope.expected_outcome == "pending_confirmation":
        return proof.handoff_id is None and proof.handoff_packet_sha256 is None and proof.handoff_row_digest is None
    return (isinstance(proof.handoff_id, str) and re.fullmatch(r"HOF-[A-Za-z0-9_-]{8}", proof.handoff_id) is not None
            and _hash(proof.handoff_packet_sha256) and _hash(proof.handoff_row_digest))


def _marker_digest(scope_digest: str, intent: HostPrepareIntent, proof: ConsumedCommitProof) -> str:
    return canonical_digest({"schema": "synthetic-prepare-drop/v1", "scope_digest": scope_digest,
                             "intent": asdict(intent), "proof": asdict(proof)})


def validate_consumed(scope: FixtureScope, marker: object) -> None:
    if (not isinstance(marker, ConsumedDrop) or marker.scope_digest != scope.digest
            or not isinstance(marker.intent, HostPrepareIntent)
            or not _binding_valid(scope, marker.intent.binding)
            or not _intent_valid(scope, marker.intent.binding, marker.intent)
            or not _consumed_proof_valid(scope, marker.intent.binding, marker.proof)
            or marker.digest != _marker_digest(scope.digest, marker.intent, marker.proof)):
        raise FaultVerificationError("consumed marker is not bound to this fixture")


def _object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _json(content: bytes) -> object:
    def reject_constant(value: str) -> None:
        raise ValueError("non-JSON numeric constant")
    return json.loads(content, object_pairs_hook=_object, parse_constant=reject_constant)


def _loaded_marker(value: object) -> ConsumedDrop:
    try:
        if not isinstance(value, dict) or set(value) != {"scope_digest", "intent", "proof", "digest"}:
            raise ValueError()
        intent, proof = value["intent"], value["proof"]
        if (not isinstance(intent, dict) or set(intent) != {"scope_digest", "binding", "action_id", "revision", "session_exp"}
                or not isinstance(proof, dict) or set(proof) != {"scope_digest", "binding", "pending_handle_sha256", "response_sha256",
                    "pending_row_digest", "handoff_id", "handoff_packet_sha256", "handoff_row_digest"}):
            raise ValueError()
        for nested in (intent, proof):
            if not isinstance(nested["binding"], dict) or set(nested["binding"]) != {
                    "request_id", "conversation_id", "transaction_id", "snapshot"}:
                raise ValueError()
        return ConsumedDrop(value["scope_digest"],
                            HostPrepareIntent(**{**intent, "binding": PrepareBinding(**intent["binding"])}),
                            ConsumedCommitProof(**{**proof, "binding": PrepareBinding(**proof["binding"])}), value["digest"])
    except (TypeError, ValueError, KeyError):
        raise FaultVerificationError("invalid consumed marker schema") from None


class FileConsumedJournal:
    """Explicit generated-fixture journal; no path defaults, overwrite or secrets.

    Publication uses a same-directory temporary file, file fsync and exclusive
    hard link, so another harness cannot replace an existing consumption. This
    covers process restart; no portable claim of power-loss directory durability
    is made. The caller supplies an isolated local filesystem supporting links.
    """

    def __init__(self, scope: FixtureScope, *, fixture_root: Path, path: Path):
        self.scope = scope
        if not Path(fixture_root).is_absolute() or not Path(path).is_absolute():
            raise FaultVerificationError("fixture and journal paths must be explicit absolute paths")
        self.root = Path(fixture_root).resolve(strict=True)
        self.path = Path(path).resolve(strict=False)
        if not self.root.is_dir() or self.path == self.root or not self.path.is_relative_to(self.root):
            raise FaultVerificationError("journal must be inside the explicit generated fixture root")
        if not self.path.parent.is_dir():
            raise FaultVerificationError("journal parent must already exist")
        self._provenance()

    def _provenance(self) -> None:
        try:
            path = (self.root / "synthetic_provenance.json").resolve(strict=True)
            if not path.is_relative_to(self.root) or path.stat().st_size > 4096:
                raise ValueError()
            value = _json(path.read_bytes())
            if value != {"kind": "team_synthetic_fixture", "build_id": self.scope.snapshot,
                         "source_fingerprint": self.scope.source_fingerprint}:
                raise ValueError()
        except (OSError, ValueError, UnicodeError):
            raise FaultVerificationError("generated fixture provenance does not match") from None

    def load(self) -> ConsumedDrop | None:
        self._provenance()
        try:
            if not self.path.exists():
                return None
            if not self.path.resolve(strict=True).is_relative_to(self.root) or self.path.stat().st_size > 32768:
                raise ValueError()
            marker = _loaded_marker(_json(self.path.read_bytes()))
            validate_consumed(self.scope, marker)
            return marker
        except (OSError, ValueError, UnicodeError):
            raise FaultVerificationError("consumed journal cannot be verified") from None

    async def record(self, marker: ConsumedDrop) -> bool:
        self._provenance()
        validate_consumed(self.scope, marker)
        existing = self.load()
        if existing is not None:
            if existing != marker:
                raise FaultVerificationError("consumed journal cannot replace a different marker")
            return True
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix=".prepare-drop-", dir=self.path.parent)
            with os.fdopen(fd, "wb") as stream:
                stream.write(rfc8785.dumps(asdict(marker)))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, self.path)
            except FileExistsError:
                # Another writer won publication; only its identical record is
                # acceptable. Never truncate or replace the published marker.
                pass
            if self.load() != marker:
                raise FaultVerificationError("consumed publication did not match")
            return True
        except OSError:
            raise FaultVerificationError("consumed marker could not be durably published") from None
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)


async def _observe(callback: Callable, *args: object) -> object:
    try:
        return await callback(*args)
    except FaultVerificationError:
        raise
    except Exception:
        # Never turn callback errors into the intended transport fault or expose
        # credential-bearing exception text. Cancellation remains cancellation.
        raise FaultVerificationError("fixture proof callback failed") from None


class PrepareDropTransport(httpx.AsyncBaseTransport):
    """One exact generated-fixture fault, dynamically bound to a saved host UUID.

    Observer failures raise FaultVerificationError, not a simulated transport
    fault. The recorder must return literal True only after durable consumption.
    Reload its exact ConsumedDrop on restart; a wrong marker is rejected. Later
    valid reserved intents pass through without re-arming the original fault.
    No callback output constitutes proof of successful integration by itself.
    """

    def __init__(self, scope: FixtureScope, *, inner_factory: InnerFactory,
                 verify_identity: IdentityVerifier, resolve_host_intent: IntentResolver,
                 verify_commit: CommitVerifier, record_consumed: ConsumedRecorder,
                 consumed: ConsumedDrop | None = None):
        self.scope = scope
        self._inner_factory = inner_factory
        self._verify_identity = verify_identity
        self._resolve_host_intent = resolve_host_intent
        self._verify_commit = verify_commit
        self._record_consumed = record_consumed
        self._lock = asyncio.Lock()
        self._consumed = consumed
        if consumed is not None:
            validate_consumed(scope, consumed)

    @property
    def consumed(self) -> ConsumedDrop | None:
        return self._consumed

    async def aclose(self) -> None:
        # Each request's fresh inner transport is already closed in _forward.
        # Host AsyncClient teardown must not disarm or close a shared wrapper.
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
        fixed, actual = urlsplit(self.scope.worker_origin), urlsplit(str(request.url))
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
        if (not isinstance(body, dict) or body.get("operation") != "prepare"
                or set(body) != {"operation", "conversationId", "requestId", "transactionId", "snapshot"}
                or body.get("transactionId") != self.scope.transaction_id or body.get("snapshot") != self.scope.snapshot):
            return await self._forward(request)
        binding = PrepareBinding(body["requestId"], body["conversationId"], body["transactionId"], body["snapshot"])
        if not _binding_valid(self.scope, binding):
            raise FaultVerificationError("prepare tuple is invalid")
        async with self._lock:
            try:
                identity = await _observe(self._verify_identity, request.headers)
                assertion = request.headers.get("X-Flujo-User-Assertion", "")
                if (not isinstance(identity, VerifiedIdentity) or not assertion
                        or identity.issuer != self.scope.issuer or identity.subject != self.scope.subject
                        or identity.frontend_session_id != self.scope.frontend_session_id
                        or identity.session_exp != self.scope.frontend_session_exp
                        or type(identity.jwt_exp) is not int or identity.jwt_exp > identity.session_exp
                        or identity.audience != "flujo-banking-ingress"
                        or identity.assertion_sha256 != hashlib.sha256(assertion.encode()).hexdigest()):
                    raise FaultVerificationError("verified fixture identity does not match")
                intent = await _observe(self._resolve_host_intent, self.scope, binding)
                if not _intent_valid(self.scope, binding, intent):
                    raise FaultVerificationError("server-reserved prepare intent does not match")
                if self._consumed is not None:
                    original = self._consumed.intent
                    if binding == original.binding:
                        if intent.action_id != original.action_id or intent.revision < original.revision:
                            raise FaultVerificationError("consumed fault intent identity changed")
                    elif intent.action_id == original.action_id or intent.revision <= original.revision:
                        raise FaultVerificationError("later prepare is not a new reserved intent")
                    return await self._forward(request)
                response = await self._forward(request)
                if response.status_code != 200:
                    return response
                try:
                    result = _json(response.content)
                except (ValueError, UnicodeError):
                    raise FaultVerificationError("successful prepare response is not JSON evidence") from None
                if not isinstance(result, dict):
                    raise FaultVerificationError("successful prepare response is not an object")
                evidence = _response_evidence(self.scope, result)
                proof = await _observe(self._verify_commit, self.scope, binding, result)
                if not _proof_valid(self.scope, binding, proof, response_digest=canonical_digest(result), evidence=evidence):
                    raise FaultVerificationError("actual MCP commit proof does not match")
                checked_intent = await _observe(self._resolve_host_intent, self.scope, binding)
                if (not _intent_valid(self.scope, binding, checked_intent)
                        or checked_intent.action_id != intent.action_id
                        or checked_intent.revision < intent.revision):
                    raise FaultVerificationError("host prepare intent changed during commit verification")
                saved_proof = ConsumedCommitProof(proof.scope_digest, proof.binding,
                    hashlib.sha256(proof.pending_handle.encode()).hexdigest(), proof.response_sha256,
                    proof.pending_row_digest, proof.handoff_id, proof.handoff_packet_sha256, proof.handoff_row_digest)
                marker = ConsumedDrop(self.scope.digest, intent, saved_proof,
                                      _marker_digest(self.scope.digest, intent, saved_proof))
                if await _observe(self._record_consumed, marker) is not True:
                    raise FaultVerificationError("one-shot consumption was not durably recorded")
                self._consumed = marker
            except FaultVerificationError:
                raise
            except httpx.HTTPError:
                # An actual upstream connection/read failure is still an actual
                # transport failure; it has not consumed the postcommit fault.
                raise
            except Exception:
                # Callback errors must not imitate the intended upstream loss or
                # reveal credential-bearing exception details to harness logs.
                raise FaultVerificationError("fixture proof callback failed") from None
            raise httpx.ReadError("synthetic prepare response withheld after verified commit", request=request)
