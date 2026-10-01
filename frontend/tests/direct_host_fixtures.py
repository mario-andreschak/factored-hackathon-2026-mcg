"""Generated direct-host test material and recording fakes; no shared state paths."""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import uuid

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID

from frontend.server.bank_rpc import BankContext
from frontend.server.language import LanguageResult
from frontend.tests.action_fixtures import action_facts, action_handoff, action_receipt, action_selected


GENERATED_LEDGER_GENERATION = "d" * 64


def make_direct_config(root: Path, *, principal_customers=None, action_enabled=False,
                       ledger_continuity_approved=True) -> dict:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    signer = root / "generated-bank-signer.pem"
    if not signer.exists():
        signer.write_bytes(Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    ca_file = root / "generated-bank-ca.pem"
    if not ca_file.exists():
        key = Ed25519PrivateKey.generate()
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Generated isolated test CA")])
        now = datetime.now(UTC)
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(key, algorithm=None))
        ca_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return {"mode": "host-direct-mcp/v1", "namespace": "generated-direct-host-tests",
        "host_revision": "a" * 40, "action_enabled": action_enabled,
        # This isolated fake bank represents one explicitly approved ledger.
        # Quarantine tests opt out; production defaults remain deny-first.
        "ledger_generation": GENERATED_LEDGER_GENERATION,
        "ledger_continuity_approved": ledger_continuity_approved,
        "principal_customers": dict(principal_customers or {"subject-a": "customer-a", "subject-b": "customer-b"}),
        "bank": {"base_url": "https://banking-mcp:8000", "ca_file": str(ca_file.resolve()),
            "service_token": "generated-bank-only-token-" + "b" * 32, "issuer": "approved-bank-host",
            "audience": "banking-mcp", "kid": "generated-bank-signer", "signing_key_file": str(signer.resolve())},
        "language": {"base_url": "http://flujo:4200", "flow_id": "123e4567-e89b-42d3-a456-426614174100",
            "flow_name": "Generic_Guidance", "service_token": "generated-language-only-token"}}


class RecordingBank:
    def __init__(self):
        self.calls = []
        self.revocations = []
        self.call_handler = None
        self.revoke_handler = None
        self.receipt = None
        self.handoff = None
        self.selected = action_selected()
        self.pending_handle = "a" * 43
        self.pending = {}

    async def call(self, tool, arguments, context, *, timeout_seconds=45):
        assert type(context) is BankContext
        self.calls.append((tool, deepcopy(arguments), context))
        if self.call_handler is not None:
            return await self.call_handler(tool, arguments, context)
        return self.answer(tool, arguments)

    def answer(self, tool, arguments):
        flags = {"synthetic": False, "operator_test": False}
        if tool == "prepare_unrecognized_charge":
            facts = action_facts(self.selected)
            self.pending[self.pending_handle] = (arguments["snapshot"], deepcopy(self.selected))
            return {**flags, "action": "simulated_intake", "decision": "intake", "reason": None,
                "snapshot": arguments["snapshot"], "transaction": facts, "pending_handle": self.pending_handle,
                "existing_case": {"state": "not_found", "receipt": None, "coverage": "sandbox_only", "source": "sandbox_cases"},
                "risk": {"unrecognized_count_24h": 1, "risk_data_complete": True, "coverage": "sandbox_only",
                    "source": "sandbox_cases", "window_start": "2026-09-28T15:00:00Z", "window_end": "2026-09-29T15:00:00Z"}}
        if tool == "confirm_simulated_intake":
            snapshot, selected = self.pending[arguments["pending_handle"]]
            self.receipt = action_receipt(snapshot=snapshot, selected=selected)
            return {**flags, "state": "created", "receipt": deepcopy(self.receipt)}
        if tool == "read_intake_receipt":
            return {**flags, "state": "created" if self.receipt is not None else "action_unverified",
                "receipt": deepcopy(self.receipt)}
        if tool == "create_verified_handoff":
            saved = self.pending.get(arguments.get("pending_handle"))
            snapshot, selected = saved if saved else (None, None)
            self.handoff = action_handoff(reason=arguments["reason"], snapshot=snapshot, selected=selected,
                questions=arguments["unanswered_questions"])
            return {**flags, "state": "created", "handoff": deepcopy(self.handoff)}
        if tool == "read_verified_handoff":
            assert self.handoff is not None and arguments["handoff_id"] == self.handoff["id"]
            return {**flags, "state": "created", "handoff": deepcopy(self.handoff)}
        raise AssertionError("Unexpected tool in generated direct-host fixture")

    async def revoke(self, context, *, timeout_seconds=10):
        assert type(context) is BankContext
        self.revocations.append(context)
        if self.revoke_handler is not None:
            return await self.revoke_handler(context)
        return None


class RecordingLanguage:
    def __init__(self, conversation=None):
        self.conversation = conversation or str(uuid.uuid4())
        self.calls = []
        self.handler = None

    async def guide(self, user_text, language, *, facts=None, conversation_id=None, forbidden_values=()):
        self.calls.append({"user_text": user_text, "language": language, "facts": facts,
            "conversation_id": conversation_id, "forbidden_values": forbidden_values})
        if self.handler is not None:
            return await self.handler(user_text, language, facts, conversation_id)
        return LanguageResult("Only the host renders this guidance", "ask_selection",
            conversation_id or self.conversation, True)


def attach_direct_fakes(service, *, bank=None, language=None):
    bank = bank if bank is not None else RecordingBank()
    language = language if language is not None else RecordingLanguage()
    # These private fixture values exercise the host exclusion list without
    # crossing any network boundary. Production credentials are never used.
    if not hasattr(bank, "_service_token"):
        bank._service_token = "generated-bank-only-token-" + "b" * 32
    if not hasattr(language, "config"):
        language.config = SimpleNamespace(service_token="generated-language-only-token")
    service._bank, service._language = bank, language
    return bank, language


@contextmanager
def client_with_direct_fakes(settings, *, bank=None, language=None, **client_kwargs):
    """Attach fakes before lazy startup, retaining the patch through shutdown.

    App/TestClient imports stay inside this invoked API-test context, so the
    shared module remains usable by pure source and temporary-state tests.
    Nested contexts capture the prior constructor and retain distinct fakes.
    """
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from frontend.server.app import create_app
    from frontend.server.chat import ChatService

    bank = bank if bank is not None else RecordingBank()
    language = language if language is not None else RecordingLanguage()

    def construct(config, state_dir):
        service = ChatService(config, state_dir)
        attach_direct_fakes(service, bank=bank, language=language)
        return service

    with patch("frontend.server.chat.ChatService", new=construct):
        with TestClient(create_app(settings), **client_kwargs) as client:
            yield client
