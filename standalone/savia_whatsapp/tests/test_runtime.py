import asyncio
import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from standalone.savia_whatsapp import runtime, whatsapp


class Process:
    def __init__(self, *args, **kwargs):
        self.dead = False

    def poll(self):
        return 0 if self.dead else None

    def terminate(self):
        self.dead = True

    def wait(self, *args):
        return 0


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(runtime, "ensure_ports_available", lambda: None)
    monkeypatch.setattr(runtime, "provider_key", lambda _: "")
    monkeypatch.setattr(runtime.subprocess, "Popen", Process)


def test_local_control_rejects_wrong_host_and_cross_site_mutation(tmp_path, offline):
    app = runtime.create_control(tmp_path, tmp_path / "mcp", None)
    with TestClient(app, base_url="http://127.0.0.1:43980") as client:
        assert client.get("/status").json()["running"] is False
        assert client.get("/", headers={"Host": "evil.test"}).status_code == 403
        assert client.post("/configure", json={"phone": "123456789"}).status_code == 403
        assert client.post("/configure", headers={"Origin": "http://evil.test"},
                           json={"phone": "123456789"}).status_code == 403
        assert not (tmp_path / "local-config.json").exists()
    assert not (tmp_path / "active.lock").exists()


def test_connection_lifetime_stays_in_owner_task(tmp_path, offline, monkeypatch):
    tasks = []
    class Adapter:
        def __init__(self, config):
            pass
        async def __aenter__(self):
            tasks.append(asyncio.current_task())
            return self
        async def __aexit__(self, *_):
            tasks.append(asyncio.current_task())
        async def status(self):
            return SimpleNamespace(authenticated=False)
    monkeypatch.setattr(whatsapp, "WhatsAppMcpAdapter", Adapter)
    app = runtime.create_control(tmp_path, tmp_path / "mcp", None)
    with TestClient(app, base_url="http://127.0.0.1:43980") as client:
        assert client.post("/configure", headers={"Origin": "http://127.0.0.1:43980"},
                           json={"phone": "+123456789"}).status_code == 200
        assert client.get("/status").json()["configured"]
    assert len(tasks) == 2 and tasks[0] is tasks[1]


def test_second_owner_does_not_mutate_delivery_state(tmp_path, offline):
    (tmp_path / "active.lock").write_text("owner")
    db = sqlite3.connect(tmp_path / "delivery.sqlite3")
    db.execute("CREATE TABLE messages (id TEXT PRIMARY KEY,state TEXT)")
    db.execute("INSERT INTO messages VALUES ('active','sending')")
    db.commit()
    app = runtime.create_control(tmp_path, tmp_path / "mcp", None)
    with pytest.raises(FileExistsError):
        with TestClient(app):
            pass
    assert db.execute("SELECT state FROM messages").fetchone()[0] == "sending"
    db.close()
