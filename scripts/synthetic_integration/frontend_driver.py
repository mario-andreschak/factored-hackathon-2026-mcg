"""Test-only frontend API journey; caller supplies the client and fixture provenance.

There is no transport construction, CLI, clock override or automatic confirmation.
The coordinator must independently establish the generated-only mount and supply a
fresh cookie jar. These checks do not establish browser consent or model grounding.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Callable, Protocol
from uuid import uuid4

from frontend.server.action import (
    matches_selected_transaction,
    normalize_handoff_questions,
    project_action_result,
    verified_handoff,
    verified_receipt,
)


class Response(Protocol):
    status_code: int

    def json(self) -> dict: ...


class Client(Protocol):
    async def get(self, path: str) -> Response: ...

    async def post(self, path: str, *, json: dict) -> Response: ...


class DriverError(ValueError):
    """The API result cannot establish the declared test journey."""


@dataclass(frozen=True)
class GeneratedFixture:
    fixture_id: str
    build_id: str
    source_fingerprint: str
    profile: str
    generated_only: bool
    origin: str = "team-generated-prototype"

    def __post_init__(self):
        if (self.generated_only is not True or self.origin != "team-generated-prototype"
                or self.profile not in {"colombia", "mexico", "argentina"}
                or not isinstance(self.fixture_id, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", self.fixture_id)
                or not isinstance(self.build_id, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", self.build_id)
                or not isinstance(self.source_fingerprint, str)
                or not re.fullmatch(r"[a-f0-9]{12,64}", self.source_fingerprint)):
            raise DriverError("A declared generated-only fixture is required")


@dataclass(frozen=True)
class AttestedPhaseEvidence:
    """Immutable setup evidence supplied by the independent backend coordinator.

    This records an authored closed synthetic period, not 24 hours of observed
    operation. The driver does not inspect or change the ledger or its clock.
    """
    fixture_id: str
    fixture_sha256: str  # Exact authored closed-history artifact hash, not the assembly pin.
    build_id: str
    source_fingerprint: str
    ledger_generation: str
    coverage_start: int
    provenance: str
    independent_verification_sha256: str

    def __post_init__(self):
        if (not isinstance(self.fixture_sha256, str)
                or not re.fullmatch(r"[a-f0-9]{64}", self.fixture_sha256)
                or not isinstance(self.independent_verification_sha256, str)
                or not re.fullmatch(r"[a-f0-9]{64}", self.independent_verification_sha256)
                or not isinstance(self.provenance, str) or not 16 <= len(self.provenance) <= 160
                or not self.provenance.startswith("synthetic:")
                or not self.provenance.endswith(":" + self.fixture_sha256)
                or not re.fullmatch(r"[A-Za-z0-9:_-]+", self.provenance)
                or not isinstance(self.ledger_generation, str)
                or not re.fullmatch(r"[a-f0-9]{64}", self.ledger_generation)
                or isinstance(self.coverage_start, bool) or not isinstance(self.coverage_start, int)
                or self.coverage_start < 1):
            raise DriverError("Independent generation-bound attested-phase evidence required")


_REFERENCE = re.compile(r"^txn_[a-f0-9]{24}$")
_UUID = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$")
_HANDLE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
_TERMINAL = {"intake_verified", "existing_case_verified", "handoff_verified"}
LIMITATIONS = (
    "Generated-only origin is a coordinator declaration, not authenticated by a browser label.",
    "Demo-mode metadata can label a generated mount organizer-snapshot.",
    "Inquiry completion uses a disclosed deterministic provider fixture; actual model grounding is unproven.",
    "Programmatic confirmation is not browser-button or human-consent evidence.",
    "Frontend status GET can trigger the host's exact idempotent prepare recovery upstream.",
    "No bank dispute, refund, human pickup, live-model acceptance or real-clock eligibility is established by this driver.",
)


class FrontendDriver:
    def __init__(self, client: Client, fixture: GeneratedFixture, *, language: str = "es"):
        if not isinstance(fixture, GeneratedFixture) or language not in {"es", "pt"}:
            raise DriverError("Declared fixture and ES/PT language required")
        self.client, self.fixture, self.language = client, fixture, language
        self.selection: dict | None = None
        self.action: dict = {"state": "none"}
        self.request_id: str | None = None
        self.target_reference: str | None = None
        self.pending_handle: str | None = None
        self.facts: dict | None = None
        self.receipt: dict | None = None
        self.handoff: dict | None = None
        self.questions: list[str] | None = None
        self.reason: str | None = None
        self.confirmation_attempted = False
        self.inquiry_completed = False
        self.dataset_label: str | None = None
        self.recorded_evidence: list[dict] = []
        self.attested_phase: AttestedPhaseEvidence | None = None
        self.previous_request_id: str | None = None
        self.existing_case_check = False

    @staticmethod
    def _body(response: Response) -> dict:
        if response.status_code != 200:
            raise DriverError(f"Frontend request failed with status {response.status_code}")
        body = response.json()
        if not isinstance(body, dict):
            raise DriverError("Frontend returned a non-object response")
        return body

    def _overview(self, body: dict) -> list[dict]:
        metadata, profile = body.get("metadata"), body.get("profile")
        if (not isinstance(metadata, dict) or not isinstance(profile, dict)
                or profile.get("id") != self.fixture.profile
                or metadata.get("build_id") != self.fixture.build_id
                or metadata.get("source_fingerprint") != self.fixture.source_fingerprint
                or metadata.get("dataset") not in {"organizer-snapshot", "team-synthetic-fixture"}):
            raise DriverError("Profile or fixture snapshot changed")
        rows = body.get("transactions")
        if (not isinstance(rows, list) or not rows
                or any(not isinstance(row, dict) or not isinstance(row.get("reference"), str)
                       or not _REFERENCE.fullmatch(row["reference"]) for row in rows)
                or len({row["reference"] for row in rows}) != len(rows)):
            raise DriverError("Owned overview has no unique public selection")
        self.dataset_label = metadata["dataset"]
        return rows

    async def login_and_select(self, code: str, *, selector: Callable[[list[dict]], str] | None = None) -> dict:
        if self.selection is not None:
            raise DriverError("This driver already has a selected session")
        if (await self.client.get("/api/auth/me")).status_code != 401:
            raise DriverError("A fresh unauthenticated client is required")
        login = self._body(await self.client.post("/api/auth/login", json={
            "profile": self.fixture.profile, "code": code}))
        if (login.get("authenticated") is not True or login.get("auth_mode") != "demo"
                or not isinstance(login.get("profile"), dict)
                or login["profile"].get("id") != self.fixture.profile):
            raise DriverError("Fresh demo authentication did not bind the fixture profile")
        rows = self._overview(self._body(await self.client.get("/api/overview")))
        reference = selector(deepcopy(rows)) if selector else rows[0]["reference"]
        selected = [row for row in rows if row["reference"] == reference]
        if len(selected) != 1:
            raise DriverError("Selection is not an owned overview reference")
        self.selection = deepcopy(selected[0])
        return deepcopy(self.selection)

    async def inquire(self, message: str) -> dict:
        if self.selection is None or not isinstance(message, str) or not 1 <= len(message.strip()) <= 3600:
            raise DriverError("Select an owned charge and supply a bounded inquiry")
        body = self._body(await self.client.post("/api/chat/messages", json={
            "message": message.strip(), "transaction_reference": self.selection["reference"]}))
        if (body.get("status") != "completed" or body.get("mode") != "flujo"
                or not isinstance(body.get("reply"), str) or not body["reply"].strip()):
            raise DriverError("The disclosed fixture inquiry has not completed")
        self.inquiry_completed = True
        return deepcopy(body)

    def _accept(self, body: dict) -> dict:
        projected = project_action_result(body)
        if projected["state"] != body.get("state") or projected["state"] == "none":
            raise DriverError("Action evidence is missing or malformed")
        if projected["state"] == "intake_verified" and not self.confirmation_attempted:
            raise DriverError("A new intake cannot precede explicit confirmation")
        request_id = projected.get("request_id")
        # Confirm and receipt recovery legitimately omit a wire UUID. Preserve
        # the observed prepare UUID internally only under the exact saved tuple;
        # do not add it to the returned API evidence.
        if (request_id is None and self.confirmation_attempted
                and projected["state"] in {"intake_verified", "action_unverified"}
                and self.request_id is not None and self.pending_handle is not None
                and projected.get("pending_handle") == self.pending_handle
                and projected.get("target_reference") == self.target_reference
                and self.facts is not None
                and ((projected["state"] == "intake_verified"
                      and projected["receipt"]["snapshot"] == self.fixture.build_id
                      and projected["receipt"]["transaction"] == self.facts)
                     or (projected["state"] == "action_unverified"
                         and projected.get("snapshot") == self.fixture.build_id
                         and projected.get("transaction") == self.facts))):
            request_id = self.request_id
        if not isinstance(request_id, str) or not _UUID.fullmatch(request_id):
            raise DriverError("Action has no valid saved request UUID")
        if self.request_id is not None and request_id != self.request_id:
            raise DriverError("Saved request UUID changed")
        if self.request_id is None and (request_id == self.previous_request_id
                or any(request_id == record["request_id"] for record in self.recorded_evidence)):
            raise DriverError("A deliberate new phase reused the completed request UUID")
        if self.existing_case_check and projected["state"] not in {
                "existing_case_verified", "preparing", "prepare_unverified"}:
            raise DriverError("Existing-receipt review cannot authorize another intake")
        if projected.get("target_reference") != self.target_reference:
            raise DriverError("Saved action target changed")
        handle = projected.get("pending_handle")
        if self.pending_handle is not None and handle != self.pending_handle:
            raise DriverError("Saved pending handle changed")
        if handle is not None and (not isinstance(handle, str) or not _HANDLE.fullmatch(handle)):
            raise DriverError("Invalid pending handle")
        facts = projected.get("transaction")
        if facts is not None:
            if (self.target_reference is None or self.selection is None
                    or projected.get("snapshot") != self.fixture.build_id
                    or not matches_selected_transaction(facts, self.selection)
                    or (self.facts is not None and facts != self.facts)):
                raise DriverError("Prepared facts conflict with the owned fixture charge")
        if projected["state"] == "pending_confirmation" and (facts is None or handle is None):
            raise DriverError("Pending consent has no complete saved charge")
        receipt = projected.get("receipt")
        if receipt is not None:
            if (verified_receipt(receipt) is None or self.target_reference is None
                    or self.selection is None or not matches_selected_transaction(receipt["transaction"], self.selection)
                    or (self.facts is not None and receipt["transaction"] != self.facts)
                    or (projected["state"] == "intake_verified" and receipt["snapshot"] != self.fixture.build_id)
                    or (self.receipt is not None and receipt != self.receipt)):
                raise DriverError("Receipt conflicts with saved charge evidence")
        packet = projected.get("handoff")
        if projected["state"] == "action_unverified" and isinstance(packet, dict):
            packet = packet.get("handoff") if packet.get("state") == "handoff_verified" else None
        if packet is not None:
            if verified_handoff(packet) is None:
                raise DriverError("Handoff is not a verified packet")
            if self.target_reference is None:
                if packet["snapshot"] is not None or packet["facts"] != {}:
                    raise DriverError("General handoff contains charge facts")
            elif (self.selection is None or packet["snapshot"] != self.fixture.build_id
                    or not matches_selected_transaction(packet["facts"], self.selection)
                    or (facts is not None and packet["facts"] != facts)
                    or (self.facts is not None and packet["facts"] != self.facts)):
                raise DriverError("Handoff conflicts with the saved selected charge")
            if (self.reason is not None and packet["reason"] != self.reason
                    or self.questions is not None and packet["unanswered_questions"] != self.questions
                    or self.handoff is not None and packet != self.handoff
                    or projected.get("reason", packet["reason"]) != packet["reason"]):
                raise DriverError("Handoff reason, questions or recorded packet changed")
        if self.reason is not None and projected.get("reason", self.reason) != self.reason:
            raise DriverError("Saved handoff reason changed")
        if self.questions is not None and projected.get("unanswered_questions", self.questions) != self.questions:
            raise DriverError("Saved handoff questions changed")
        records = []
        for kind, evidence in (("receipt", receipt), ("handoff", packet)):
            if evidence is not None:
                records.append({"kind": kind, "target_reference": self.target_reference,
                                "request_id": request_id, "evidence": evidence})
        for key, kind in (("prior_receipt", "receipt"), ("prior_handoff", "handoff")):
            if key in body:
                wrapper = projected.get(key)
                if wrapper is None:
                    raise DriverError("Retained evidence is malformed or belongs to another target")
                records.append({"kind": kind, "target_reference": wrapper["target_reference"],
                                "request_id": None, "evidence": wrapper[kind]})
        for record in records:
            for old in self.recorded_evidence:
                if (record["kind"] == old["kind"] and record["evidence"]["id"] == old["evidence"]["id"]
                        and (record["evidence"] != old["evidence"]
                             or record["target_reference"] != old["target_reference"])):
                    raise DriverError("Previously recorded evidence changed")
        for record in records:
            if not any(record["kind"] == old["kind"] and record["evidence"] == old["evidence"]
                       and record["target_reference"] == old["target_reference"] for old in self.recorded_evidence):
                self.recorded_evidence.append(deepcopy(record))
        self.request_id, self.pending_handle = request_id, handle
        self.facts = deepcopy(facts) if facts is not None else self.facts
        self.receipt = deepcopy(receipt) if receipt is not None else self.receipt
        self.handoff = deepcopy(packet) if packet is not None else self.handoff
        self.action = deepcopy(projected)
        return deepcopy(self.action)

    async def prepare(self) -> dict:
        if not self.inquiry_completed or self.selection is None or self.action["state"] != "none":
            raise DriverError("Complete the inquiry before a single prepare intent")
        self.target_reference = self.selection["reference"]
        body = self._body(await self.client.post("/api/action/prepare", json={
            "transaction_reference": self.target_reference, "language": self.language}))
        if body.get("state") == "intake_verified":
            raise DriverError("Preparation cannot claim a new confirmed intake")
        return self._accept(body)

    async def explicit_confirm(self, *, confirmed: bool) -> dict:
        if (self.attested_phase is None or confirmed is not True or self.action["state"] != "pending_confirmation"
                or self.facts is None or self.pending_handle is None or self.confirmation_attempted):
            raise DriverError("Independent attested setup and separate explicit programmatic confirmation required")
        self.confirmation_attempted = True
        return self._accept(self._body(await self.client.post("/api/action/confirm", json={
            "pending_handle": self.pending_handle, "transaction_reference": self.target_reference,
            "confirmed": True, "language": self.language})))

    def begin_attested_phase(self, evidence: AttestedPhaseEvidence) -> None:
        """Authorize a distinct prepare intent only after the stock coverage handoff."""
        if (not isinstance(evidence, AttestedPhaseEvidence) or self.attested_phase is not None
                or self.action["state"] != "handoff_verified" or self.handoff is None
                or self.handoff["reason"] != "missing_evidence" or self.target_reference is None
                or evidence.fixture_id != self.fixture.fixture_id
                or evidence.build_id != self.fixture.build_id
                or evidence.source_fingerprint != self.fixture.source_fingerprint):
            raise DriverError("Attested phase does not match the completed stock fixture phase")
        self.attested_phase = evidence
        self.previous_request_id = self.request_id
        self.request_id, self.pending_handle, self.facts = None, None, None
        self.handoff, self.reason, self.questions = None, None, None
        self.action = {"state": "none"}

    def begin_existing_case_check(self) -> None:
        """Start a distinct same-charge readback intent after verified intake."""
        if (self.action["state"] != "intake_verified" or self.receipt is None
                or self.selection is None or self.target_reference != self.selection["reference"]
                or self.attested_phase is None or self.existing_case_check):
            raise DriverError("A verified same-charge intake is required for existing-case review")
        self.previous_request_id = self.request_id
        self.request_id, self.pending_handle, self.facts = None, None, None
        self.handoff, self.reason, self.questions = None, None, None
        self.existing_case_check = True
        self.action = {"state": "none"}

    def begin_independent_attested_phase(self, evidence: AttestedPhaseEvidence) -> None:
        """Use a separately verified fresh ledger generation before any action.

        The recommended positive assembly has its own driver/client and never
        inherits the stock missing-coverage assembly's ledger or action row.
        """
        if (not isinstance(evidence, AttestedPhaseEvidence) or self.attested_phase is not None
                or not self.inquiry_completed or self.selection is None
                or self.action["state"] != "none" or self.request_id is not None
                or self.receipt is not None or self.handoff is not None or self.recorded_evidence
                or evidence.fixture_id != self.fixture.fixture_id
                or evidence.build_id != self.fixture.build_id
                or evidence.source_fingerprint != self.fixture.source_fingerprint):
            raise DriverError("Independent attested setup requires a matching fresh action-free assembly")
        self.attested_phase = evidence

    async def request_general_handoff(self, questions: list[str]) -> dict:
        normalized = normalize_handoff_questions(questions)
        if (not self.inquiry_completed or normalized is None
                or self.action["state"] not in _TERMINAL | {"none"}):
            raise DriverError("A fresh explicit general human request is unavailable")
        self.target_reference, self.pending_handle, self.facts = None, None, None
        self.existing_case_check = False
        self.request_id, self.reason, self.questions = str(uuid4()), "customer_request", normalized
        self.handoff = None
        return self._accept(self._body(await self.client.post("/api/action/handoff", json={
            "request_id": self.request_id, "reason": self.reason,
            "unanswered_questions": normalized, "language": self.language})))

    async def retry_handoff(self) -> dict:
        if self.action["state"] != "handoff_unverified" or self.request_id is None or self.reason is None:
            raise DriverError("No frozen human request is awaiting explicit retry")
        body = {"request_id": self.request_id, "reason": self.reason, "language": self.language}
        if self.target_reference is not None:
            body["transaction_reference"] = self.target_reference
        if self.pending_handle is not None:
            body["pending_handle"] = self.pending_handle
        # Omission reuses the host's frozen questions; no edited questions enter a retry.
        return self._accept(self._body(await self.client.post("/api/action/handoff", json=body)))

    async def read_status(self) -> dict:
        if not self.inquiry_completed or self.target_reference is None and self.request_id is None:
            raise DriverError("No saved intent is available for status recovery")
        return self._accept(self._body(await self.client.get(f"/api/action/status?language={self.language}")))

    async def recover(self, client: Client | None = None) -> dict:
        """After an external restart, use the retained cookie jar and only frontend GETs."""
        if self.selection is None:
            raise DriverError("No owned selection is available to recover")
        if client is not None:
            self.client = client
        identity = self._body(await self.client.get("/api/auth/me"))
        if (identity.get("authenticated") is not True or identity.get("auth_mode") != "demo"
                or not isinstance(identity.get("profile"), dict)
                or identity["profile"].get("id") != self.fixture.profile):
            raise DriverError("Restart lost the authenticated fixture profile")
        rows = self._overview(self._body(await self.client.get("/api/overview")))
        if self.selection not in rows:
            raise DriverError("Restart changed the selected owned charge")
        return await self.read_status()

    def report(self) -> dict:
        def without_handles(value):
            if isinstance(value, dict):
                return {key: without_handles(item) for key, item in value.items() if key != "pending_handle"}
            if isinstance(value, list):
                return [without_handles(item) for item in value]
            return value
        return deepcopy(without_handles({"scope": "test-only-generated-fixture", "fixture_id": self.fixture.fixture_id,
            "build_id": self.fixture.build_id, "source_fingerprint": self.fixture.source_fingerprint,
            "profile": self.fixture.profile, "dataset_label": self.dataset_label,
            "actual_browser": False, "actual_model_grounding": False,
            "human_button_consent": False, "inquiry_evidence": "deterministic-provider-fixture-completion"
            if self.inquiry_completed else "not_completed", "selection": self.selection,
            "action": self.action, "receipt": self.receipt, "handoff": self.handoff,
            "saved_prepare_request_id": self.request_id if self.target_reference is not None else None,
            "recorded_evidence": self.recorded_evidence,
            "attested_phase": None if self.attested_phase is None else {
                **self.attested_phase.__dict__, "basis": "authored-closed-generated-past-period",
                "observed_24_hour_operation": False},
            "programmatic_confirmation_attempted": self.confirmation_attempted,
            "limitations": list(LIMITATIONS)}))
