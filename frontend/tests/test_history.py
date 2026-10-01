"""Authenticated public transcript restoration with direct-host recording fakes."""
from __future__ import annotations

from dataclasses import replace
import pytest

from frontend.server.app import COOKIE
from frontend.server.language import MinimizedFacts, render_guidance
from frontend.tests.direct_host_fixtures import client_with_direct_fakes, make_direct_config
from frontend.tests.test_api import login, settings


@pytest.fixture()
def history_settings(settings, tmp_path):
    chat = make_direct_config(tmp_path / "generated-history-host",
        principal_customers={"private-subject-co": "private-customer-co",
                             "private-subject-mx": "private-customer-mx"})
    return replace(settings, chat=chat)


def test_authenticated_history_restores_after_restart_without_private_context(history_settings):
    with client_with_direct_fakes(history_settings) as client:
        bank, language = client.app.state.chat_service._bank, client.app.state.chat_service._language
        assert client.get("/api/chat/history").status_code == 401
        assert login(client).status_code == 200
        empty = client.get("/api/chat/history").json()
        assert empty["available"] and empty["messages"] == [] and not empty["active"]
        selected = client.get("/api/overview").json()["transactions"][0]
        sent = client.post("/api/chat/messages", json={"message": "Ayúdame con este movimiento",
                                                     "transaction_reference": selected["reference"]})
        assert sent.status_code == 200
        assert bank.calls == []
        assert language.calls[-1]["user_text"] == "Ayúdame con este movimiento"
        assert type(language.calls[-1]["facts"]) is MinimizedFacts
        assert language.calls[-1]["facts"].event_date == selected["occurred_at"][:10]
        assert language.calls[-1]["language"] == "es"
        history = client.get("/api/chat/history")
        assert history.status_code == 200
        public = history.json()["messages"]
        assert public[0] == {"role": "user", "text": "Ayúdame con este movimiento",
                            "selection": {k: selected[k] for k in
                                          ("reference", "occurred_at", "type", "amount", "currency", "status")}}
        assert public[1] == {"role": "assistant", "text": render_guidance("ask_selection", "es")}
        for private in ["private-", "conversation_id", "X-Flujo-User-Assertion", "PRIVATE KEY",
                        "Movimiento seleccionado en la banca", "selection_handle"]:
            assert private not in history.text
        cookie = client.cookies.get(COOKIE)
        with client_with_direct_fakes(history_settings) as restarted:
            restarted_bank = restarted.app.state.chat_service._bank
            restarted_language = restarted.app.state.chat_service._language
            restarted.cookies.set(COOKIE, cookie)
            assert restarted.get("/api/chat/history").json()["messages"] == public
            assert restarted_bank.calls == [] and restarted_language.calls == []


def test_profile_rotation_and_logout_never_restore_previous_session_transcript(history_settings):
    with client_with_direct_fakes(history_settings) as client:
        bank, language = client.app.state.chat_service._bank, client.app.state.chat_service._language
        login(client)
        assert client.post("/api/chat/messages", json={"message": "Consulta de Colombia"}).status_code == 200
        old_cookie = client.cookies.get(COOKIE)
        assert login(client, "mexico").status_code == 200
        assert client.get("/api/chat/history").json()["messages"] == []
        assert client.post("/api/chat/messages", json={"message": "Consulta de México"}).status_code == 200
        history = client.get("/api/chat/history").json()["messages"]
        assert history[0]["text"] == "Consulta de México" and len(history) == 2
        with client_with_direct_fakes(history_settings) as revoked:
            revoked.cookies.set(COOKIE, old_cookie)
            assert revoked.get("/api/chat/history").status_code == 401
        current_cookie = client.cookies.get(COOKIE)
        assert client.post("/api/auth/logout", json={}).status_code == 204
        client.cookies.set(COOKIE, current_cookie)
        assert client.get("/api/chat/history").status_code == 401
        assert bank.calls == []
        with client.app.state.chat_service._connection() as db:
            assert db.execute("SELECT COUNT(*) FROM chat_sessions WHERE revoked=1").fetchone()[0] == 2
        assert len(language.calls) == 2


def test_unconfigured_authenticated_history_is_empty_and_unavailable(settings):
    with client_with_direct_fakes(settings) as client:
        assert client.get("/api/chat/history").status_code == 401
        login(client)
        assert client.get("/api/chat/history").json() == {"available": False, "messages": [], "active": False}
