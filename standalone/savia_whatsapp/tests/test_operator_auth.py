from fastapi.testclient import TestClient
import pytest

from standalone.savia_whatsapp import runtime
from standalone.savia_whatsapp.operator_auth import TOKEN_ENV, OperatorAuth
from standalone.savia_whatsapp.tests.test_runtime import offline


TOKEN = "fictional-operator-token-for-offline-tests-12345"
ORIGIN = {"Origin": "http://127.0.0.1:43980"}


@pytest.mark.parametrize("token", ["", "short", "a" * 31, "has spaces" * 8, "é" * 40])
def test_hosted_mode_requires_an_explicit_strong_operator_secret(monkeypatch, token):
    monkeypatch.setenv(TOKEN_ENV, token)
    with pytest.raises(ValueError, match=TOKEN_ENV):
        OperatorAuth(True)
    assert not OperatorAuth(False).enabled


def test_host_origin_spoof_cannot_read_or_mutate_hosted_account(tmp_path, offline, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    app = runtime.create_control(tmp_path, tmp_path / "mcp", None, hosted=True)
    with TestClient(app, base_url="http://127.0.0.1:43980") as client:
        assert client.get("/", follow_redirects=False).status_code == 303
        assert client.get("/login").status_code == 200
        for path in ("/status", "/qr", "/missing"):
            assert client.get(path).status_code == 401
        for path in ("/configure", "/start", "/stop", "/shutdown", "/skip-uncertain", "/logout"):
            assert client.post(path, headers=ORIGIN, json={}).status_code == 401
        assert not (tmp_path / "local-config.json").exists()
        assert client.post("/login", headers=ORIGIN, json={"token": "wrong"}).status_code == 401
        assert client.post("/login", json={"token": TOKEN}).status_code == 403
        assert client.get("/status", headers={"Authorization": "Bearer " + TOKEN}).status_code == 200
        assert client.get("/status", headers={"Authorization": "Bearer " + TOKEN, "Host": "evil.test"}).status_code == 403


def test_private_browser_session_hides_secret_and_logout_revokes_it(tmp_path, offline, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    app = runtime.create_control(tmp_path, tmp_path / "mcp", None, hosted=True)
    with TestClient(app, base_url="http://127.0.0.1:43980") as client:
        response = client.post("/login", headers=ORIGIN, json={"token": TOKEN})
        assert response.status_code == 200
        session = response.json()["access_token"]
        assert TOKEN not in response.text and "set-cookie" not in response.headers
        authorization = {"Authorization": "Bearer " + session}
        assert client.get("/status", headers=authorization).json()["operator_authentication"] is True
        assert client.get("/status", headers={"Cookie": f"operator={session}"}).status_code == 401
        assert client.post("/logout", headers={**ORIGIN, **authorization}).status_code == 200
        assert client.get("/status", headers=authorization).status_code == 401


def test_session_expiry_and_forged_cookie_do_not_bypass_gate(tmp_path, offline, monkeypatch):
    from standalone.savia_whatsapp import operator_auth
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    clock = [100.0]
    monkeypatch.setattr(OperatorAuth, "_now", lambda _: clock[0])
    app = runtime.create_control(tmp_path, tmp_path / "mcp", None, hosted=True)
    with TestClient(app, base_url="http://127.0.0.1:43980") as client:
        assert client.get("/status", headers={"Authorization": "Bearer " + 'A' * 43}).status_code == 401
        response = client.post("/login", headers=ORIGIN, json={"token": TOKEN})
        assert response.status_code == 200
        clock[0] += operator_auth.SESSION_SECONDS + 1
        assert client.get("/status", headers={"Authorization": "Bearer " + response.json()["access_token"]}).status_code == 401


def test_hosted_credentials_do_not_reach_whatsapp_child(tmp_path, offline, monkeypatch):
    from standalone.savia_whatsapp.tests.test_runtime import Process
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    monkeypatch.setenv("OPENROUTER_API_KEY", "fictional-provider-test-key")
    environments = []
    def process(*args, **kwargs):
        environments.append(kwargs["env"])
        return Process()
    monkeypatch.setattr(runtime.subprocess, "Popen", process)
    app = runtime.create_control(tmp_path, tmp_path / "mcp", None, hosted=True)
    with TestClient(app, base_url="http://127.0.0.1:43980"):
        assert environments
        assert TOKEN_ENV not in environments[0]
        assert "OPENROUTER_API_KEY" not in environments[0]
