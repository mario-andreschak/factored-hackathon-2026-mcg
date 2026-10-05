"""Explicit locale and owned display facts survive failed language stages."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from dispute_workflow.prompts import StageError
from dispute_workflow.runtime import Workflow
from dispute_workflow.state import ConversationStore
from frontend.server.app import create_app
from frontend.server.dispute_chat import DisputeChatService, selected_fallback
from frontend.server.language import MinimizedFacts
from frontend.tests.direct_host_fixtures import make_direct_config
from frontend.tests.test_api import settings, login


class UnavailableStages:
    async def run(self, stage, inputs, **kwargs):
        raise StageError(stage, "timeout")


class NoBankRead:
    async def read(self, *args, **kwargs):
        pytest.fail("Failed preflight must not authorize a bank read")


def test_pt_fallback_uses_explicit_locale_and_replay_binds_it(tmp_path):
    async def journey():
        now = datetime.now(timezone.utc)
        binding = dict(owner="fictional-owner", customer_id="fictional-customer",
            session_id="fictional-session", conversation_id="fictional-chat", expires_at=now + timedelta(hours=1))
        workflow = Workflow(UnavailableStages(), NoBankRead(), ConversationStore(tmp_path / "workflow.sqlite3"))
        state = await workflow.run(binding, "Não reconheço esta cobrança.", turn_id="locale-turn", response_language="pt")
        assert state["response"]["language"] == "pt"
        assert "Não consegui" in state["response"]["message"]
        assert "español" not in state["response"]["message"]
        with pytest.raises(ValueError, match="replay mismatch"):
            await workflow.run(binding, "Não reconheço esta cobrança.", turn_id="locale-turn", response_language="es")
    asyncio.run(journey())


def test_host_persists_helpful_owned_facts_in_pt_during_language_outage(tmp_path):
    async def journey():
        material = make_direct_config(tmp_path / "keys")
        service = DisputeChatService({"mode": "dispute-host/v1", "base_url": "http://flujo:4200",
            "model": "flow-Dispute", "execution_token": "generated-execution-token",
            "frontend_signing_key_file": material["bank"]["signing_key_file"],
            "frontend_kid": "generated", "frontend_issuer": "generated",
            "frontend_audience": "flujo-banking-ingress", "principal_customers": {"subject-a": "customer-a"}}, tmp_path / "state")
        workflow = Workflow(UnavailableStages(), NoBankRead(), ConversationStore(tmp_path / "workflow.sqlite3"))
        sid, expiry = str(uuid.uuid4()), int(time.time()) + 3600
        result = await service.send("customer-a", sid, expiry, "Não reconheço esta cobrança.",
            workflow=workflow, language="pt", facts=MinimizedFacts("2026-10-01", "25.50", "USD", "Mercado Fictício", "approved"))
        assert "25,50 USD" in result["reply"] and "Mercado Fictício" in result["reply"]
        assert "Nenhuma solicitação foi confirmada" in result["reply"]
        assert service.history("customer-a", sid, expiry)["messages"][-1]["text"] == result["reply"]
    asyncio.run(journey())


def test_customer_fallback_has_human_dates_status_and_explicit_next_step():
    text = selected_fallback(MinimizedFacts("2026-10-02", "4280.75", "MXN", "Nébula Market", "approved"), "es", "CONFIRM_ACTION")
    assert "4.280,75 MXN" in text and "2 de octubre de 2026" in text
    assert "aprobado" in text and "Revisar recepción simulada" in text
    assert "txn_" not in text and "Approved" not in text and "T00:" not in text
    assert "Responder en el chat no registra" in text


def test_fresh_authenticated_followup_view_does_not_expire_login(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/followups").status_code == 401
        assert login(client).status_code == 200
        assert client.get("/api/followups?language=pt").json() == {"items": []}
        assert client.get("/api/auth/me").status_code == 200
        assert client.post("/api/followups/check", json={"language": "pt"}).json() == {"items": []}
        assert client.post("/api/followups", json={"language": "pt", "pending_handle": "untrusted"}).status_code == 422


def test_fresh_dispute_action_status_preserves_bank_login_in_both_locales(settings, tmp_path):
    material = make_direct_config(tmp_path / "keys")
    configured = replace(settings, chat={"mode": "dispute-host/v1", "base_url": "http://flujo:4200",
        "model": "flow-Dispute", "execution_token": "generated-execution-token",
        "frontend_signing_key_file": material["bank"]["signing_key_file"],
        "frontend_kid": "generated", "frontend_issuer": "generated",
        "frontend_audience": "flujo-banking-ingress", "action_enabled": True,
        "principal_customers": {"subject-a": "private-customer-co"}})
    with TestClient(create_app(configured, dispute_factory=lambda *args: None)) as client:
        assert client.get("/api/action/status").status_code == 401
        assert login(client).status_code == 200
        for language in ("es", "pt"):
            response = client.get(f"/api/action/status?language={language}")
            assert response.status_code == 200 and response.json() == {"state": "none"}
            assert client.get("/api/auth/me").status_code == 200
        with client.app.state.chat_service._connection() as db:
            assert db.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0] == 0


def test_standalone_frontend_preserves_login_without_optional_inquiry_package(settings, monkeypatch):
    import builtins
    original_import = builtins.__import__

    def standalone_import(name, *args, **kwargs):
        if name == "savia_assistant":
            raise ModuleNotFoundError("Standalone optional module absent", name=name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", standalone_import)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/assistant/cases").status_code == 401
        assert login(client).status_code == 200
        assert client.get("/api/assistant/cases").json() == {"items": []}
        assert client.post("/api/assistant/cases", json={"message": "Ayuda", "language": "es"}).status_code == 503
        assert client.get("/api/auth/me").status_code == 200
