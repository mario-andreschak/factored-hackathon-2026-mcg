"""Authenticated public transcript restoration with a mocked private worker."""
from __future__ import annotations

from dataclasses import replace
import json
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
import httpx
import pytest

from frontend.server.app import COOKIE, create_app
from frontend.tests.test_api import login, settings


@pytest.fixture()
def history_settings(settings, tmp_path):
    signer = Ed25519PrivateKey.generate()
    key = tmp_path / "frontend-signer.pem"
    key.write_bytes(signer.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
    chat = {"base_url": "http://flujo:4200", "model": "flow-Banking_Customer",
            "execution_token": "private-worker-execution-credential",
            "frontend_signing_key_file": str(key), "frontend_kid": "fixture-front",
            "frontend_issuer": "fixture-frontend", "frontend_audience": "flujo-banking-ingress",
            "principal_customers": {"private-subject-co": "private-customer-co",
                                    "private-subject-mx": "private-customer-mx"}}
    return replace(settings, chat=chat)


def worker(request):
    if request.url.path.endswith("revoke"):
        return httpx.Response(200, json={"revoked": True})
    body = json.loads(request.content)
    conversation = body["metadata"].get("conversationId", str(uuid.uuid4()))
    return httpx.Response(200, json={"conversation_id": conversation, "status": "completed",
        "choices": [{"message": {"role": "assistant", "content": "Respuesta de la prueba sintética."}}],
        "messages": [{"role": "tool", "content": "private-model-tool-facts"}]})


def attach_worker(client):
    client.app.state.chat_service._transport = httpx.MockTransport(worker)


def test_authenticated_history_restores_after_restart_without_private_context(history_settings):
    with TestClient(create_app(history_settings)) as client:
        attach_worker(client)
        assert client.get("/api/chat/history").status_code == 401
        assert login(client).status_code == 200
        empty = client.get("/api/chat/history").json()
        assert empty["available"] and empty["messages"] == [] and not empty["active"]
        selected = client.get("/api/overview").json()["transactions"][0]
        sent = client.post("/api/chat/messages", json={"message": "Ayúdame con este movimiento",
                                                     "transaction_reference": selected["reference"]})
        assert sent.status_code == 200
        history = client.get("/api/chat/history")
        assert history.status_code == 200
        public = history.json()["messages"]
        assert public[0] == {"role": "user", "text": "Ayúdame con este movimiento",
                            "selection": {k: selected[k] for k in
                                          ("reference", "occurred_at", "type", "amount", "currency", "status")}}
        assert public[1] == {"role": "assistant", "text": "Respuesta de la prueba sintética."}
        for private in ["private-", "conversation_id", "X-Flujo-User-Assertion", "PRIVATE KEY",
                        "Movimiento seleccionado en la banca", "selection_handle"]:
            assert private not in history.text
        cookie = client.cookies.get(COOKIE)
        with TestClient(create_app(history_settings)) as restarted:
            attach_worker(restarted)
            restarted.cookies.set(COOKIE, cookie)
            assert restarted.get("/api/chat/history").json()["messages"] == public


def test_profile_rotation_and_logout_never_restore_previous_session_transcript(history_settings):
    with TestClient(create_app(history_settings)) as client:
        attach_worker(client)
        login(client)
        assert client.post("/api/chat/messages", json={"message": "Consulta de Colombia"}).status_code == 200
        old_cookie = client.cookies.get(COOKIE)
        assert login(client, "mexico").status_code == 200
        assert client.get("/api/chat/history").json()["messages"] == []
        assert client.post("/api/chat/messages", json={"message": "Consulta de México"}).status_code == 200
        history = client.get("/api/chat/history").json()["messages"]
        assert history[0]["text"] == "Consulta de México" and len(history) == 2
        with TestClient(create_app(history_settings)) as revoked:
            attach_worker(revoked)
            revoked.cookies.set(COOKIE, old_cookie)
            assert revoked.get("/api/chat/history").status_code == 401
        current_cookie = client.cookies.get(COOKIE)
        assert client.post("/api/auth/logout", json={}).status_code == 204
        client.cookies.set(COOKIE, current_cookie)
        assert client.get("/api/chat/history").status_code == 401


def test_unconfigured_authenticated_history_is_empty_and_unavailable(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/chat/history").status_code == 401
        login(client)
        assert client.get("/api/chat/history").json() == {"available": False, "messages": [], "active": False}
