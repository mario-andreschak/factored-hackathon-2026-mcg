"""Read-only callbacks for an explicitly generated, ephemeral integration fixture.

Imports start nothing. The marker and generated-only scope are assembly inputs,
not proof of a generator/source pin or permission to execute a hosted checkpoint.
No service, application, network client or production state writer is constructed.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
from typing import Iterator

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .frontend_fault import (FixtureScope, HostPrepareIntent, PrepareBinding,
                             PrepareCommitProof, VerifiedIdentity, canonical_digest)
from .frontend_driver import AttestedPhaseEvidence


_UUID4 = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$")
_HANDLE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
_TARGET = re.compile(r"^txn_[a-f0-9]{24}$")


class ObservationRejected(AssertionError):
    """Fixed, secret-free rejection; absent evidence is never commit proof."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ObservationRejected(code)


def _object(raw: str | bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result

    try:
        _require(len(raw) <= 256 * 1024, "invalid_record")
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        _require(isinstance(value, dict), "invalid_record")
        canonical_digest(value)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ObservationRejected("invalid_record") from None


@dataclass(frozen=True, repr=False)
class GeneratedFixturePaths:
    fixture_root: Path
    synthetic_provenance: Path
    frontend_state_db: Path
    frontend_chat_db: Path
    mcp_state_db: Path

    def contained_file(self, path: Path) -> Path:
        try:
            root, resolved = self.fixture_root.resolve(strict=True), path.resolve(strict=True)
            _require(root.is_dir() and resolved.is_file() and resolved.is_relative_to(root), "fixture_path_rejected")
            return resolved
        except (OSError, ValueError):
            raise ObservationRejected("fixture_path_rejected") from None


def _provenance(paths: GeneratedFixturePaths, snapshot: str, fingerprint: str) -> None:
    try:
        marker = _object(paths.contained_file(paths.synthetic_provenance).read_bytes())
        _require(marker == {"kind": "team_synthetic_fixture", "build_id": snapshot,
                            "source_fingerprint": fingerprint}, "fixture_provenance_mismatch")
    except OSError:
        raise ObservationRejected("fixture_provenance_unavailable") from None


@contextmanager
def _read(paths: GeneratedFixturePaths, path: Path) -> Iterator[sqlite3.Connection]:
    db = None
    try:
        db = sqlite3.connect(paths.contained_file(path).as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("BEGIN")
        yield db
    except sqlite3.Error:
        raise ObservationRejected("fixture_record_unavailable") from None
    finally:
        if db is not None:
            db.close()


def _one(db: sqlite3.Connection, sql: str, parameters: tuple) -> sqlite3.Row:
    rows = db.execute(sql, parameters).fetchall()
    _require(len(rows) == 1, "fixture_record_missing_or_ambiguous")
    return rows[0]


@dataclass(frozen=True, repr=False)
class LoginSession:
    session_id: str
    session_exp: int


@dataclass(frozen=True)
class LedgerObservation:
    scope_digest: str
    generation: str
    observed_at: int
    row_counts: dict[str, int]
    row_sha256: dict[str, str]


def read_login_session(paths: GeneratedFixturePaths, *, cookie: str, expected_profile: str,
                       expected_customer: str, snapshot: str, source_fingerprint: str) -> LoginSession:
    """Bind the injected client's private cookie to its actual saved fixture login.

    Cookie/token hashes are not retained, returned, logged or echoed in errors.
    This lookup is evidence only; it does not authenticate an application request.
    """
    _provenance(paths, snapshot, source_fingerprint)
    _require(isinstance(cookie, str) and 1 <= len(cookie) <= 128, "fixture_login_rejected")
    with _read(paths, paths.frontend_state_db) as db:
        row = _one(db, """SELECT s.id,s.profile_id,s.expires_at,p.customer_id FROM sessions s
            JOIN profiles p ON p.id=s.profile_id WHERE s.token_hash=?""",
            (hashlib.sha256(cookie.encode()).hexdigest(),))
    _require(row["profile_id"] == expected_profile and row["customer_id"] == expected_customer
             and isinstance(row["id"], str) and 16 <= len(row["id"]) <= 128
             and type(row["expires_at"]) is int and time.time() < row["expires_at"] <= time.time() + 8 * 3600,
             "fixture_login_rejected")
    return LoginSession(row["id"], row["expires_at"])


def frontend_owner(issuer: str, subject: str, model: str) -> str:
    # ChatService._owner_for_subject uses compact JSON with default ensure_ascii.
    return hashlib.sha256(json.dumps([issuer, subject, model], separators=(",", ":")).encode()).hexdigest()


def bank_session_id(deployment_id: str, issuer: str, frontend_session: str) -> str:
    # authority.ts bankSessionId hashes UTF-8 JSON.stringify (no ASCII escaping).
    return hashlib.sha256(json.dumps([deployment_id, issuer, frontend_session],
                                     ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


class FrontendObservers:
    def __init__(self, paths: GeneratedFixturePaths, scope: FixtureScope,
                 trusted_public_keys: dict[str, Ed25519PublicKey]):
        self.paths, self.scope = paths, scope
        self._keys = dict(trusted_public_keys)
        self._attested_inputs: dict | None = None
        self._confirmation_baselines: dict[HostPrepareIntent, tuple[float, LedgerObservation]] = {}
        self._browser_baselines: dict[str, tuple[HostPrepareIntent, str]] = {}
        _require(bool(self._keys) and all(isinstance(key, Ed25519PublicKey) for key in self._keys.values()),
                 "fixture_trust_rejected")
        self._check_scope(scope)

    def _check_scope(self, scope: FixtureScope) -> None:
        _require(type(scope) is FixtureScope and scope == self.scope
                 and scope.generated_only is True and scope.origin == "team-generated-prototype"
                 and scope.expected_outcome in {"pending_confirmation", "handoff_verified"}
                 and scope.frontend_owner == frontend_owner(scope.issuer, scope.subject, scope.frontend_model)
                 and scope.bank_session_id == bank_session_id(scope.bank_deployment_id, scope.issuer,
                                                              scope.frontend_session_id)
                 and type(scope.frontend_session_exp) is int
                 and time.time() < scope.frontend_session_exp <= time.time() + 8 * 3600,
                 "fixture_scope_rejected")
        _provenance(self.paths, scope.snapshot, scope.source_fingerprint)
        resolved = [self.paths.contained_file(path) for path in
                    (self.paths.frontend_state_db, self.paths.frontend_chat_db, self.paths.mcp_state_db)]
        _require(len(set(resolved)) == 3 and all(not left.samefile(right)
                                                for i, left in enumerate(resolved) for right in resolved[i + 1:]),
                 "fixture_path_rejected")
        with _read(self.paths, self.paths.mcp_state_db) as db:
            _require(self._generation(db) == scope.ledger_generation, "ledger_generation_rejected")

    def _login(self, scope: FixtureScope) -> None:
        with _read(self.paths, self.paths.frontend_state_db) as db:
            login = _one(db, """SELECT s.profile_id,s.expires_at,p.customer_id FROM sessions s
                JOIN profiles p ON p.id=s.profile_id WHERE s.id=?""", (scope.frontend_session_id,))
        _require(login["profile_id"] == scope.profile_id and login["customer_id"] == scope.customer_id
                 and type(login["expires_at"]) is int and login["expires_at"] == scope.frontend_session_exp,
                 "fixture_login_rejected")

    async def identity_verifier(self, headers: httpx.Headers) -> VerifiedIdentity:
        """Verify the real ingress assertion clock/signature without admitting it."""
        self._check_scope(self.scope)
        self._login(self.scope)
        values = headers.get_list("X-Flujo-User-Assertion")
        _require(len(values) == 1 and 1 <= len(values[0]) <= 8192, "ingress_assertion_rejected")
        token = values[0]
        try:
            segments = token.split(".")
            _require(len(segments) == 3, "ingress_assertion_rejected")
            protected = _object(base64.urlsafe_b64decode(segments[0] + "=" * (-len(segments[0]) % 4)))
            _require(set(protected) == {"alg", "kid", "typ"} and protected["alg"] == "EdDSA"
                     and protected["typ"] == "flujo-ingress+jwt" and protected["kid"] in self._keys,
                     "ingress_assertion_rejected")
            raw = _object(base64.urlsafe_b64decode(segments[1] + "=" * (-len(segments[1]) % 4)))
            claims = jwt.decode(token, self._keys[protected["kid"]], algorithms=["EdDSA"],
                                issuer=self.scope.issuer, audience="flujo-banking-ingress", leeway=0,
                                options={"require": ["iss", "aud", "sub", "session_id", "session_exp",
                                                     "iat", "nbf", "exp", "jti", "scope"]})
            now = time.time()
            _require(set(claims) == {"iss", "aud", "sub", "session_id", "session_exp", "iat", "nbf", "exp", "jti", "scope"}
                     and canonical_digest(raw) == canonical_digest(claims)
                     and claims["iss"] == self.scope.issuer and claims["sub"] == self.scope.subject
                     and claims["aud"] == "flujo-banking-ingress"
                     and claims["session_id"] == self.scope.frontend_session_id
                     and claims["session_exp"] == self.scope.frontend_session_exp
                     and all(type(claims[field]) is int for field in ("iat", "nbf", "exp", "session_exp"))
                     and claims["nbf"] == claims["iat"] <= now
                     and 0 < claims["exp"] - claims["iat"] <= 120
                     and now < claims["exp"] <= claims["session_exp"]
                     and claims["session_exp"] - claims["iat"] <= 8 * 3600
                     and isinstance(claims["jti"], str) and 16 <= len(claims["jti"]) <= 128
                     and claims["scope"] == ["bank:read"], "ingress_assertion_rejected")
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, UnicodeError):
            raise ObservationRejected("ingress_assertion_rejected") from None
        return VerifiedIdentity(issuer=claims["iss"], subject=claims["sub"],
                                frontend_session_id=claims["session_id"], session_exp=claims["session_exp"],
                                jwt_exp=claims["exp"], assertion_sha256=hashlib.sha256(token.encode()).hexdigest())

    async def resolve_host_intent(self, scope: FixtureScope, binding: PrepareBinding) -> HostPrepareIntent:
        self._check_scope(scope)
        _require(type(binding) is PrepareBinding and isinstance(binding.request_id, str)
                 and isinstance(binding.conversation_id, str) and _UUID4.fullmatch(binding.request_id) is not None
                 and _UUID4.fullmatch(binding.conversation_id) is not None
                 and binding.transaction_id == scope.transaction_id and binding.snapshot == scope.snapshot,
                 "host_prepare_rejected")
        self._login(scope)
        with _read(self.paths, self.paths.frontend_chat_db) as db:
            session = _one(db, "SELECT * FROM chat_sessions WHERE session_id=?", (scope.frontend_session_id,))
            action = _one(db, "SELECT * FROM action_status WHERE session_id=?", (scope.frontend_session_id,))
        saved = _object(action["result_json"])
        _require(session["owner"] == action["owner"] == scope.frontend_owner
                 and session["expires"] == action["expires"] == scope.frontend_session_exp
                 and session["subject"] == scope.subject and session["customer_id"] == scope.customer_id
                 and session["revoked"] == 0
                 and session["conversation_id"] == action["prepare_conversation_id"] == binding.conversation_id
                 and action["prepare_transaction_id"] == binding.transaction_id
                 and action["prepare_snapshot"] == binding.snapshot
                 and saved.get("state") in {"preparing", "prepare_unverified"}
                 and saved.get("request_id") == binding.request_id
                 and isinstance(action["target_reference"], str) and _TARGET.fullmatch(action["target_reference"]) is not None
                 and saved.get("target_reference", action["target_reference"]) == action["target_reference"]
                 and isinstance(action["action_id"], str) and _UUID4.fullmatch(action["action_id"]) is not None
                 and type(action["revision"]) is int and action["revision"] >= 1,
                 "host_prepare_rejected")
        return HostPrepareIntent(scope_digest=canonical_digest(asdict(scope)), binding=binding,
                                 action_id=action["action_id"], revision=action["revision"],
                                 session_exp=action["expires"])

    async def verify_commit(self, scope: FixtureScope, binding: PrepareBinding,
                            response_json: dict) -> PrepareCommitProof:
        await self.resolve_host_intent(scope, binding)
        if scope.expected_outcome == "pending_confirmation":
            _require(self._attested_inputs is not None, "authored_phase_evidence_required")
            self.verify_attested_phase(**self._attested_inputs)
        _require(isinstance(response_json, dict) and response_json.get("state") == scope.expected_outcome,
                 "prepare_response_rejected")
        handle = response_json.get("pending_handle")
        _require(isinstance(handle, str) and _HANDLE.fullmatch(handle) is not None, "prepare_response_rejected")
        owner_binding = canonical_digest({"sub": scope.subject, "customer": scope.customer_id,
                                          "session": scope.bank_session_id, "conversation": binding.conversation_id})
        request_key = hashlib.sha256(json.dumps([owner_binding, binding.request_id]).encode()).hexdigest()
        with _read(self.paths, self.paths.mcp_state_db) as db:
            session = _one(db, "SELECT subject,customer FROM sessions WHERE session=?", (scope.bank_session_id,))
            _require(session["subject"] == scope.subject and session["customer"] == scope.customer_id
                     and not db.execute("SELECT 1 FROM revoked WHERE session=?", (scope.bank_session_id,)).fetchone(),
                     "mcp_session_rejected")
            pending = _one(db, "SELECT * FROM action_pending WHERE request_key=?", (request_key,))
            facts, result = _object(pending["facts"]), _object(pending["result_json"])
            decision, reason = ("intake", None) if scope.expected_outcome == "pending_confirmation" else ("handoff", "missing_evidence")
            _require(pending["id"] == hashlib.sha256(handle.encode()).hexdigest()
                     and pending["binding"] == owner_binding and pending["customer"] == scope.customer_id
                     and pending["transaction_id"] == binding.transaction_id and pending["snapshot"] == binding.snapshot
                     and pending["action"] == "simulated_intake" and pending["decision"] == decision
                     and pending["reason"] == reason and pending["confirmation_state"] == "prepared"
                     and type(pending["expires"]) in {int, float} and math.isfinite(pending["expires"])
                     and time.time() < pending["expires"] <= time.time() + 600
                     and canonical_digest(facts) == scope.facts_sha256
                     and {"snapshot", "action", "decision", "reason", "transaction", "risk", "existing_case"} <= set(result)
                     and isinstance(result.get("risk"), dict) and isinstance(result.get("existing_case"), dict)
                     and all(result.get(field) == value and response_json.get(field) == value
                             for field, value in (("snapshot", binding.snapshot), ("action", "simulated_intake"),
                                                   ("decision", decision), ("reason", reason)))
                     and canonical_digest(result.get("transaction")) == canonical_digest(facts)
                     and canonical_digest(response_json.get("transaction")) == canonical_digest(facts),
                     "mcp_pending_rejected")
            _require(self._generation(db) == scope.ledger_generation, "ledger_generation_rejected")
            risk = result["risk"]
            try:
                start = datetime.fromisoformat(risk["window_start"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(risk["window_end"].replace("Z", "+00:00"))
                _require(start.tzinfo is not None and end.tzinfo is not None
                         and start.utcoffset().total_seconds() == end.utcoffset().total_seconds() == 0
                         and abs(end.timestamp() - (pending["expires"] - 600)) < 0.01
                         and abs(end.timestamp() - start.timestamp() - 86400) < 0.01,
                         "ledger_risk_rejected")
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                raise ObservationRejected("ledger_risk_rejected") from None
            _require(risk.get("coverage") == "sandbox_only" and risk.get("source") == "sandbox_cases"
                     and ("risk" not in response_json or canonical_digest(response_json["risk"]) == canonical_digest(risk)),
                     "ledger_risk_rejected")
            if scope.expected_outcome == "handoff_verified":
                _require(not db.execute("SELECT 1 FROM sandbox_coverage").fetchone()
                         and db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 0
                         and db.execute("SELECT count(*) FROM sandbox_case_receipts").fetchone()[0] == 0
                         and risk.get("risk_data_complete") is False and risk.get("unrecognized_count_24h") is None,
                         "stock_missing_coverage_rejected")
            else:
                coverage = _one(db, "SELECT coverage_start FROM sandbox_coverage WHERE id=1", ())
                prior = db.execute("""SELECT count(DISTINCT transaction_id) FROM sandbox_cases
                    WHERE customer=? AND transaction_id<>? AND action=? AND created_at>=? AND created_at<?""",
                    (scope.customer_id, scope.transaction_id, "simulated_intake", start.timestamp(), end.timestamp())).fetchone()[0]
                _require(risk.get("risk_data_complete") is True
                         and type(risk.get("unrecognized_count_24h")) is int
                         and risk["unrecognized_count_24h"] == prior + 1 < 3
                         and coverage["coverage_start"] <= start.timestamp(), "attested_risk_rejected")
            _require(scope.expected_outcome != "pending_confirmation" or "handoff" not in response_json,
                     "prepare_response_rejected")
            handoff_id = packet_digest = row_digest = None
            if scope.expected_outcome == "handoff_verified":
                handoff = _one(db, "SELECT * FROM sandbox_handoffs WHERE idempotency_key=?", (request_key,))
                packet, handoff_facts = _object(handoff["packet_json"]), _object(handoff["facts"])
                proof = response_json.get("handoff")
                provenance = packet.get("transaction_provenance")
                _require(isinstance(provenance, dict) and set(provenance) == {"source", "snapshot", "as_of"}
                         and provenance["source"] == "owned_serving_snapshot" and provenance["snapshot"] == binding.snapshot,
                         "mcp_handoff_rejected")
                try:
                    moment = datetime.fromisoformat(provenance["as_of"].replace("Z", "+00:00"))
                    _require(moment.tzinfo is not None and moment.utcoffset().total_seconds() == 0
                             and pending["expires"] - 601 <= moment.timestamp() <= handoff["created_at"] + 1
                             and type(handoff["created_at"]) in {int, float} and math.isfinite(handoff["created_at"])
                             and pending["expires"] - 601 <= handoff["created_at"] <= time.time(), "mcp_handoff_rejected")
                except (ValueError, TypeError, AttributeError, OverflowError):
                    raise ObservationRejected("mcp_handoff_rejected") from None
                expected_packet = {"schema": "banking-sandbox-handoff/v1", "transaction": facts,
                                   "transaction_provenance": provenance, "reason": "missing_evidence",
                                   "unanswered_questions": [], "human_responded": False}
                _require(handoff["binding"] == owner_binding and handoff["customer"] == scope.customer_id
                         and handoff["transaction_id"] == binding.transaction_id and handoff["snapshot"] == binding.snapshot
                         and handoff["reason"] == "missing_evidence" and canonical_digest(handoff_facts) == canonical_digest(facts)
                         and canonical_digest(packet) == canonical_digest(expected_packet)
                         and isinstance(handoff["id"], str) and re.fullmatch(r"HOF-[A-Za-z0-9_-]{8}", handoff["id"]) is not None
                         and isinstance(proof, dict), "mcp_handoff_rejected")
                expected_readback = {"id": handoff["id"], "reason": "missing_evidence", "snapshot": binding.snapshot,
                                     "created_at": datetime.fromtimestamp(handoff["created_at"], timezone.utc).isoformat().replace("+00:00", "Z"),
                                     "facts": facts, "packet": packet, "transaction_currentness": "same_snapshot", "human_responded": False}
                _require(canonical_digest(proof) == canonical_digest(expected_readback), "mcp_handoff_readback_rejected")
                handoff_id, packet_digest, row_digest = handoff["id"], canonical_digest(packet), canonical_digest(dict(handoff))
        return PrepareCommitProof(scope_digest=canonical_digest(asdict(scope)), binding=binding,
                                  pending_handle=handle, response_sha256=canonical_digest(response_json),
                                  pending_row_digest=canonical_digest(dict(pending)), handoff_id=handoff_id,
                                  handoff_packet_sha256=packet_digest, handoff_row_digest=row_digest)

    def verify_attested_phase(self, *, fixture_artifact: Path, fixture_sha256: str,
                              expected_generation: str, expected_coverage_start: int,
                              declared_closed_interval_end: int, expected_provenance: str) -> AttestedPhaseEvidence:
        """Observe an existing authored-interval attestation; never create one.

        The closure boundary is a trusted assembly declaration. Exact artifact
        bytes and ledger correlation do not prove authoring completeness,
        observed 24-hour operation, source approval or release eligibility.
        """
        self._check_scope(self.scope)
        now = time.time()
        _require(isinstance(fixture_sha256, str) and re.fullmatch(r"[a-f0-9]{64}", fixture_sha256) is not None
                 and isinstance(expected_generation, str) and re.fullmatch(r"[a-f0-9]{64}", expected_generation) is not None
                 and type(expected_coverage_start) is int and 0 < expected_coverage_start <= now - 86400
                 and type(declared_closed_interval_end) is int
                 and expected_coverage_start + 86400 <= declared_closed_interval_end <= now,
                 "authored_interval_rejected")
        _require(isinstance(expected_provenance, str) and 16 <= len(expected_provenance) <= 160
                 and expected_provenance.startswith("synthetic:")
                 and expected_provenance.endswith(":" + fixture_sha256)
                 and not any(ord(char) < 32 for char in expected_provenance), "authored_provenance_rejected")
        try:
            artifact_hash = hashlib.sha256(self.paths.contained_file(fixture_artifact).read_bytes()).hexdigest()
        except OSError:
            raise ObservationRejected("authored_fixture_unavailable") from None
        _require(artifact_hash == fixture_sha256, "authored_fixture_mismatch")
        provenance = expected_provenance
        with _read(self.paths, self.paths.mcp_state_db) as db:
            identity = _one(db, "SELECT * FROM sandbox_ledger_identity WHERE id=1", ())
            coverage = _one(db, "SELECT * FROM sandbox_coverage WHERE id=1", ())
        _require(identity["generation"] == coverage["generation"] == expected_generation
                 and type(coverage["coverage_start"]) is int and coverage["coverage_start"] == expected_coverage_start
                 and coverage["provenance_digest"] == hashlib.sha256(provenance.encode()).hexdigest()
                 and type(coverage["attested_at"]) is int
                 and declared_closed_interval_end <= coverage["attested_at"] <= time.time(),
                 "attested_ledger_rejected")
        evidence = AttestedPhaseEvidence(fixture_id=self.scope.fixture_id, fixture_sha256=fixture_sha256,
                                        build_id=self.scope.snapshot, source_fingerprint=self.scope.source_fingerprint,
                                        ledger_generation=identity["generation"], coverage_start=coverage["coverage_start"],
                                        provenance=provenance, independent_verification_sha256=canonical_digest({
                                            "scope_digest": self.scope.digest, "artifact_sha256": artifact_hash,
                                            "declared_closed_interval_end": declared_closed_interval_end,
                                            "ledger_identity": dict(identity), "coverage": dict(coverage)}))
        self._attested_inputs = {"fixture_artifact": fixture_artifact, "fixture_sha256": fixture_sha256,
                                 "expected_generation": expected_generation, "expected_coverage_start": expected_coverage_start,
                                 "declared_closed_interval_end": declared_closed_interval_end,
                                 "expected_provenance": expected_provenance}
        return evidence

    def _context(self, conversation_id: str) -> str:
        self._check_scope(self.scope)
        self._login(self.scope)
        _require(isinstance(conversation_id, str) and _UUID4.fullmatch(conversation_id) is not None,
                 "fixture_context_rejected")
        with _read(self.paths, self.paths.frontend_chat_db) as db:
            session = _one(db, "SELECT * FROM chat_sessions WHERE session_id=?", (self.scope.frontend_session_id,))
        _require(session["owner"] == self.scope.frontend_owner and session["subject"] == self.scope.subject
                 and session["customer_id"] == self.scope.customer_id and session["expires"] == self.scope.frontend_session_exp
                 and session["revoked"] == 0 and session["conversation_id"] == conversation_id, "fixture_context_rejected")
        return canonical_digest({"sub": self.scope.subject, "customer": self.scope.customer_id,
                                 "session": self.scope.bank_session_id, "conversation": conversation_id})

    def _bank_session(self, db: sqlite3.Connection) -> None:
        _require(self._generation(db) == self.scope.ledger_generation, "ledger_generation_rejected")
        row = _one(db, "SELECT subject,customer FROM sessions WHERE session=?", (self.scope.bank_session_id,))
        _require(row["subject"] == self.scope.subject and row["customer"] == self.scope.customer_id
                 and not db.execute("SELECT 1 FROM revoked WHERE session=?", (self.scope.bank_session_id,)).fetchone(),
                 "mcp_session_rejected")

    def _selected_action(self, binding: PrepareBinding, handle: str, target: str,
                         allowed_states: set[str], original: HostPrepareIntent | None = None):
        _require(type(binding) is PrepareBinding and isinstance(binding.request_id, str)
                 and _UUID4.fullmatch(binding.request_id) is not None
                 and binding.transaction_id == self.scope.transaction_id and binding.snapshot == self.scope.snapshot
                 and isinstance(handle, str) and _HANDLE.fullmatch(handle) is not None
                 and isinstance(target, str) and _TARGET.fullmatch(target) is not None, "selected_action_rejected")
        owner = self._context(binding.conversation_id)
        with _read(self.paths, self.paths.frontend_chat_db) as db:
            action = _one(db, "SELECT * FROM action_status WHERE session_id=?", (self.scope.frontend_session_id,))
        saved = _object(action["result_json"])
        selected_snapshot, selected_facts = saved.get("snapshot"), saved.get("transaction")
        if saved.get("state") == "intake_verified":
            from frontend.server.action import verified_receipt
            receipt = verified_receipt(saved.get("receipt"))
            _require(receipt is not None, "selected_action_rejected")
            _require(("snapshot" not in saved or saved["snapshot"] == receipt["snapshot"])
                     and ("transaction" not in saved or canonical_digest(saved["transaction"]) == canonical_digest(receipt["transaction"])),
                     "selected_action_rejected")
            selected_snapshot, selected_facts = receipt["snapshot"], receipt["transaction"]
        _require(action["owner"] == self.scope.frontend_owner and action["expires"] == self.scope.frontend_session_exp
                 and action["target_reference"] == target and saved.get("target_reference", target) == target
                 and saved.get("state") in allowed_states and saved.get("pending_handle") == handle
                 and selected_snapshot == binding.snapshot
                 and canonical_digest(selected_facts) == self.scope.facts_sha256
                 and isinstance(action["action_id"], str) and _UUID4.fullmatch(action["action_id"]) is not None
                 and type(action["revision"]) is int and action["revision"] >= 1
                 and (saved.get("request_id") == binding.request_id or original is not None and "request_id" not in saved),
                 "selected_action_rejected")
        if original is not None:
            _require(type(original) is HostPrepareIntent and original.scope_digest == self.scope.digest
                     and original.binding == binding and original.action_id == action["action_id"]
                     and original.session_exp == action["expires"] and action["revision"] > original.revision,
                     "confirmation_identity_rejected")
        return action, saved, owner

    def _selected_pending(self, db, binding: PrepareBinding, handle: str, owner: str):
        self._bank_session(db)
        key = hashlib.sha256(json.dumps([owner, binding.request_id]).encode()).hexdigest()
        pending = _one(db, "SELECT * FROM action_pending WHERE request_key=?", (key,))
        facts, prepared = _object(pending["facts"]), _object(pending["result_json"])
        _require(pending["id"] == hashlib.sha256(handle.encode()).hexdigest() and pending["binding"] == owner
                 and pending["customer"] == self.scope.customer_id and pending["transaction_id"] == binding.transaction_id
                 and pending["snapshot"] == binding.snapshot and pending["action"] == "simulated_intake"
                 and type(pending["expires"]) in {int, float} and math.isfinite(pending["expires"])
                 and time.time() < pending["expires"] <= time.time() + 600
                 and canonical_digest(facts) == self.scope.facts_sha256
                 and all(prepared.get(field) == pending[field] for field in ("snapshot", "action", "decision", "reason"))
                 and canonical_digest(prepared.get("transaction")) == self.scope.facts_sha256, "mcp_pending_rejected")
        return pending, facts

    def capture_confirmation_base(self, target_reference: str, pending_handle: str) -> HostPrepareIntent:
        """Read the actual saved pending-confirmation UUID after prepare fields clear."""
        _require(self._attested_inputs is not None, "authored_phase_evidence_required")
        self.verify_attested_phase(**self._attested_inputs)
        with _read(self.paths, self.paths.frontend_chat_db) as db:
            action = _one(db, "SELECT * FROM action_status WHERE session_id=?", (self.scope.frontend_session_id,))
            session = _one(db, "SELECT conversation_id FROM chat_sessions WHERE session_id=?", (self.scope.frontend_session_id,))
        saved = _object(action["result_json"])
        binding = PrepareBinding(saved.get("request_id"), session["conversation_id"], self.scope.transaction_id, self.scope.snapshot)
        action, _, owner = self._selected_action(binding, pending_handle, target_reference, {"pending_confirmation"})
        with _read(self.paths, self.paths.mcp_state_db) as db:
            pending, _ = self._selected_pending(db, binding, pending_handle, owner)
            _require(not db.execute("SELECT 1 FROM sandbox_cases WHERE customer=? AND transaction_id=? AND action=?",
                                    (self.scope.customer_id, self.scope.transaction_id, "simulated_intake")).fetchone(),
                     "confirmation_case_already_exists")
        _require(pending["decision"] == "intake" and pending["reason"] is None
                 and pending["confirmation_state"] == "prepared", "confirmation_identity_rejected")
        original = HostPrepareIntent(self.scope.digest, binding, action["action_id"], action["revision"], action["expires"])
        baseline = self.ledger_observation(binding.conversation_id)
        _require(baseline.row_counts["selected_cases"] == baseline.row_counts["selected_receipts"] == 0,
                 "confirmation_case_already_exists")
        self._confirmation_baselines[original] = (time.time(), baseline)
        return original

    async def resolve_confirmation_intent(self, original_intent: HostPrepareIntent, pending_handle: str,
                                           target_reference: str) -> HostPrepareIntent:
        _require(type(original_intent) is HostPrepareIntent, "confirmation_identity_rejected")
        _require(original_intent in self._confirmation_baselines, "confirmation_baseline_required")
        action, _, owner = self._selected_action(original_intent.binding, pending_handle, target_reference,
                                                 {"action_unverified"}, original_intent)
        with _read(self.paths, self.paths.mcp_state_db) as db:
            pending, _ = self._selected_pending(db, original_intent.binding, pending_handle, owner)
        _require(pending["decision"] == "intake" and pending["reason"] is None
                 and pending["confirmation_state"] in {"prepared", "attempted", "verified"}, "confirmation_identity_rejected")
        return HostPrepareIntent(self.scope.digest, original_intent.binding, action["action_id"], action["revision"], action["expires"])

    def _generation(self, db) -> str:
        value = _one(db, "SELECT generation FROM sandbox_ledger_identity WHERE id=1", ())["generation"]
        _require(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None, "ledger_generation_rejected")
        return value

    def verify_receipt(self, original_intent: HostPrepareIntent, pending_handle: str,
                       target_reference: str, readback_receipt: dict) -> dict:
        """Actual case/receipt evidence, never browser consent or a live-bank action."""
        _require(self._attested_inputs is not None, "authored_phase_evidence_required")
        _require(type(original_intent) is HostPrepareIntent, "confirmation_identity_rejected")
        self.verify_attested_phase(**self._attested_inputs)
        action, saved, owner = self._selected_action(original_intent.binding, pending_handle, target_reference,
                                                     {"action_unverified", "intake_verified", "existing_case_verified"}, original_intent)
        with _read(self.paths, self.paths.mcp_state_db) as db:
            generation = self._generation(db)
            pending, facts = self._selected_pending(db, original_intent.binding, pending_handle, owner)
            _require((pending["decision"] == "intake" and pending["confirmation_state"] == "verified")
                     or (saved["state"] == "existing_case_verified" and pending["decision"] == "existing_case"
                         and pending["confirmation_state"] == "prepared"), "receipt_evidence_rejected")
            case = _one(db, "SELECT * FROM sandbox_cases WHERE customer=? AND transaction_id=? AND action=?",
                        (self.scope.customer_id, self.scope.transaction_id, "simulated_intake"))
            receipt = _one(db, "SELECT * FROM sandbox_case_receipts WHERE case_id=?", (case["id"],))
            _require(isinstance(case["id"], str) and re.fullmatch(r"CMP-SBX-[A-Za-z0-9_-]{8}", case["id"]) is not None
                     and case["snapshot"] == self.scope.snapshot and canonical_digest(_object(case["facts"])) == self.scope.facts_sha256
                     and type(case["created_at"]) in {int, float} and math.isfinite(case["created_at"])
                     and 0 <= case["created_at"] <= time.time(), "receipt_evidence_rejected")
            expected = {"id": case["id"], "kind": "simulated_intake", "simulated": True, "snapshot": case["snapshot"],
                        "created_at": datetime.fromtimestamp(case["created_at"], timezone.utc).isoformat().replace("+00:00", "Z"),
                        "status": "received", "transaction": facts}
            _require(canonical_digest(_object(receipt["receipt_json"])) == canonical_digest(expected)
                     and canonical_digest(readback_receipt) == canonical_digest(expected)
                     and ("receipt" not in saved or canonical_digest(saved["receipt"]) == canonical_digest(expected)),
                     "receipt_readback_rejected")
        return {"generation": generation, "scope_digest": self.scope.digest, "case_id": case["id"],
                "pending_row_digest": canonical_digest(dict(pending)), "case_row_digest": canonical_digest(dict(case)),
                "receipt_row_digest": canonical_digest(dict(receipt)), "receipt_sha256": canonical_digest(expected)}

    def verify_fresh_confirmation(self, original_intent: HostPrepareIntent, pending_handle: str,
                                   target_reference: str, readback_receipt: dict) -> dict:
        _require(original_intent in self._confirmation_baselines, "confirmation_baseline_required")
        captured_at, baseline = self._confirmation_baselines[original_intent]
        observed = self.verify_receipt(original_intent, pending_handle, target_reference, readback_receipt)
        try:
            created = datetime.fromisoformat(readback_receipt["created_at"].replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ObservationRejected("fresh_receipt_rejected") from None
        current = self.ledger_observation(original_intent.binding.conversation_id)
        comparison = self.compare_ledger_observations(baseline, current)
        _require(created >= captured_at and observed["generation"] == baseline.generation
                 and current.row_counts["selected_cases"] == current.row_counts["selected_receipts"] == 1
                 and all(comparison["net_row_count_delta"][table] == delta for table, delta in
                         (("sandbox_cases", 1), ("sandbox_case_receipts", 1), ("action_pending", 0), ("sandbox_handoffs", 0))),
                 "fresh_receipt_rejected")
        return {**observed, "fresh": True, "baseline_sha256": canonical_digest({"captured_at": captured_at,
                                                                                 "rows": asdict(baseline)})}

    async def verify_confirmation_commit(self, confirm_scope, pending_handle: str, response_json: dict):
        from .frontend_confirm_fault import ConfirmScope, ConfirmCommitProof
        _require(type(confirm_scope) is ConfirmScope and confirm_scope.fixture == self.scope
                 and isinstance(response_json, dict) and response_json.get("state") == "intake_verified"
                 and isinstance(pending_handle, str) and _HANDLE.fullmatch(pending_handle) is not None
                 and hashlib.sha256(pending_handle.encode()).hexdigest() == confirm_scope.pending_handle_sha256,
                 "confirmation_response_rejected")
        observed = self.verify_fresh_confirmation(confirm_scope.original_intent, pending_handle, confirm_scope.target_reference,
                                                  response_json.get("receipt"))
        return ConfirmCommitProof(scope_digest=confirm_scope.digest, binding=confirm_scope.original_intent.binding,
                                  pending_handle_sha256=confirm_scope.pending_handle_sha256,
                                  response_sha256=canonical_digest(response_json), **{key: observed[key] for key in
                                      ("pending_row_digest", "case_id", "case_row_digest", "receipt_row_digest", "receipt_sha256")})

    def verify_general_handoff(self, request_id: str, conversation_id: str, expected_questions: list[str],
                                readback_handoff: dict) -> dict:
        from frontend.server.action import verified_handoff
        owner = self._context(conversation_id)
        _require(isinstance(request_id, str) and _UUID4.fullmatch(request_id) is not None, "general_handoff_rejected")
        with _read(self.paths, self.paths.frontend_chat_db) as db:
            action = _one(db, "SELECT * FROM action_status WHERE session_id=?", (self.scope.frontend_session_id,))
        saved = _object(action["result_json"])
        _require(action["owner"] == self.scope.frontend_owner and action["expires"] == self.scope.frontend_session_exp
                 and action["target_reference"] is None and saved.get("request_id") == request_id
                 and saved.get("state") in {"handoff_verified", "handoff_unverified"}
                 and saved.get("reason", "customer_request") == "customer_request"
                 and isinstance(expected_questions, list) and saved.get("unanswered_questions") == expected_questions,
                 "general_handoff_rejected")
        key = hashlib.sha256(json.dumps([owner, request_id]).encode()).hexdigest()
        with _read(self.paths, self.paths.mcp_state_db) as db:
            self._bank_session(db)
            generation = self._generation(db)
            row = _one(db, "SELECT * FROM sandbox_handoffs WHERE idempotency_key=?", (key,))
        packet = _object(row["packet_json"])
        expected_packet = {"schema": "banking-sandbox-handoff/v1", "transaction": None, "transaction_provenance": None,
                           "reason": "customer_request", "unanswered_questions": expected_questions, "human_responded": False}
        _require(row["binding"] == owner and row["customer"] == self.scope.customer_id and row["transaction_id"] is None
                 and row["snapshot"] is None and row["reason"] == "customer_request" and _object(row["facts"]) == {}
                 and canonical_digest(packet) == canonical_digest(expected_packet)
                 and type(row["created_at"]) in {int, float} and math.isfinite(row["created_at"])
                 and 0 <= row["created_at"] <= time.time(), "general_handoff_rejected")
        expected = {"id": row["id"], "reason": "customer_request", "snapshot": None,
                    "created_at": datetime.fromtimestamp(row["created_at"], timezone.utc).isoformat().replace("+00:00", "Z"),
                    "facts": {}, "human_responded": False, "unanswered_questions": expected_questions,
                    "transaction_provenance": None, "transaction_currentness": "not_applicable"}
        _require(canonical_digest(verified_handoff(readback_handoff)) == canonical_digest(expected)
                 and ("handoff" not in saved or canonical_digest(verified_handoff(saved["handoff"])) == canonical_digest(expected)),
                 "general_handoff_readback_rejected")
        return {"generation": generation, "scope_digest": self.scope.digest, "handoff_id": row["id"],
                "handoff_row_digest": canonical_digest(dict(row)), "handoff_packet_sha256": canonical_digest(packet),
                "handoff_readback_sha256": canonical_digest(expected), "human_pickup": "unproven"}

    def ledger_observation(self, conversation_id: str) -> LedgerObservation:
        """Observe generated-ledger rows, not an audit of transient intervening writes."""
        owner = self._context(conversation_id)
        counts, digests = {}, {}
        with _read(self.paths, self.paths.mcp_state_db) as db:
            self._bank_session(db)
            generation = self._generation(db)
            for table, order in (("action_pending", "id"), ("sandbox_cases", "id"),
                                 ("sandbox_case_receipts", "case_id"), ("sandbox_handoffs", "id")):
                rows = [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY {order}")]
                counts[table] = len(rows)
                digests[table] = canonical_digest(rows)
            selections = {
                "selected_pending": ("SELECT * FROM action_pending WHERE customer=? AND transaction_id=? ORDER BY id", (self.scope.customer_id, self.scope.transaction_id)),
                "selected_cases": ("SELECT * FROM sandbox_cases WHERE customer=? AND transaction_id=? ORDER BY id", (self.scope.customer_id, self.scope.transaction_id)),
                "selected_receipts": ("SELECT r.* FROM sandbox_case_receipts r JOIN sandbox_cases c ON c.id=r.case_id WHERE c.customer=? AND c.transaction_id=? ORDER BY r.case_id", (self.scope.customer_id, self.scope.transaction_id)),
                "owner_handoffs": ("SELECT * FROM sandbox_handoffs WHERE customer=? AND binding=? ORDER BY id", (self.scope.customer_id, owner)),
                "general_owner_handoffs": ("SELECT * FROM sandbox_handoffs WHERE customer=? AND binding=? AND transaction_id IS NULL ORDER BY id", (self.scope.customer_id, owner)),
            }
            for name, (sql, params) in selections.items():
                selected = [dict(row) for row in db.execute(sql, params)]
                counts[name] = len(selected)
                digests[name] = canonical_digest(selected)
        return LedgerObservation(self.scope.digest, generation, int(time.time()), counts, digests)

    @staticmethod
    def compare_ledger_observations(before: LedgerObservation, after: LedgerObservation) -> dict:
        _require(type(before) is LedgerObservation and type(after) is LedgerObservation
                 and before.scope_digest == after.scope_digest and before.generation == after.generation
                 and set(before.row_counts) == set(after.row_counts), "ledger_observations_not_comparable")
        return {"scope_digest": before.scope_digest, "generation": before.generation,
                "scope": "business_ledger_rows_only",
                "net_row_count_delta": {table: after.row_counts[table] - before.row_counts[table] for table in before.row_counts},
                "observed_rows_unchanged": before.row_sha256 == after.row_sha256,
                "intervening_transient_writes": "unproven"}

    def _browser_cookie(self, cookie_sha256: str) -> None:
        _require(isinstance(cookie_sha256, str) and re.fullmatch(r"[a-f0-9]{64}", cookie_sha256) is not None,
                 "browser_cookie_rejected")
        with _read(self.paths, self.paths.frontend_state_db) as db:
            row = _one(db, "SELECT token_hash FROM sessions WHERE id=?", (self.scope.frontend_session_id,))
        _require(row["token_hash"] == cookie_sha256, "browser_cookie_rejected")

    async def pending(self, saved, cookie_sha256: str):
        """Concrete browser predecessor from actual owner rows, not a True stub."""
        from .frontend_browser import SavedTuple, PendingTruth, digest
        _require(type(saved) is SavedTuple and saved.snapshot == self.scope.snapshot
                 and canonical_digest(saved.facts) == self.scope.facts_sha256, "browser_pending_rejected")
        self._browser_cookie(cookie_sha256)
        original = self.capture_confirmation_base(saved.target_reference, saved.pending_handle)
        _require(saved.request_id == original.binding.request_id, "browser_pending_rejected")
        captured_at, baseline = self._confirmation_baselines[original]
        key = digest(saved.public())
        self._browser_baselines[key] = (original, cookie_sha256)
        return PendingTruth(key, cookie_sha256, baseline.generation,
                            canonical_digest({"intent": asdict(original), "captured_at": captured_at,
                                              "business_rows": asdict(baseline)}), True)

    async def fresh_receipt(self, saved, cookie_sha256: str):
        from .frontend_browser import SavedTuple, ReceiptTruth, digest
        _require(type(saved) is SavedTuple, "browser_receipt_rejected")
        self._browser_cookie(cookie_sha256)
        key = digest(saved.public())
        _require(key in self._browser_baselines and self._browser_baselines[key][1] == cookie_sha256,
                 "browser_receipt_baseline_required")
        original, _ = self._browser_baselines[key]
        with _read(self.paths, self.paths.frontend_chat_db) as db:
            row = _one(db, "SELECT result_json FROM action_status WHERE session_id=?", (self.scope.frontend_session_id,))
        result = _object(row["result_json"])
        _require(result.get("state") == "intake_verified", "browser_receipt_rejected")
        receipt = result.get("receipt")
        proof = self.verify_fresh_confirmation(original, saved.pending_handle, saved.target_reference, receipt)
        return ReceiptTruth(key, cookie_sha256, proof["generation"], canonical_digest(proof),
                            proof["receipt_sha256"], receipt, True)
