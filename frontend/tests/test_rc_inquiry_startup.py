"""Public RC startup carries private inquiry settings without replacing bank state."""
import json
from types import SimpleNamespace

import pytest

from deploy.rc import run


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import socket

    def denied(*args, **kwargs):
        raise AssertionError("startup settings tests must not access the network")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


@pytest.mark.parametrize("inquiries", [None, {"mode": "bootstrap"},
                                      {"mode": "recovered-fleet/v1", "owner_approved": False}])
def test_main_reads_explicit_private_settings_before_starting_host(tmp_path, monkeypatch, inquiries):
    import httpx
    import uvicorn

    monkeypatch.delenv("BANKING_CONFIG_FILE", raising=False)
    if inquiries is not None:
        config = tmp_path / "private-settings.json"
        config.write_text(json.dumps({"inquiries": inquiries}), encoding="utf-8")
        monkeypatch.setenv("BANKING_CONFIG_FILE", str(config))
    monkeypatch.setattr("sys.argv", ["run.py", "--private-dir", str(tmp_path),
                                    "--model", "model-offline"])
    monkeypatch.setattr(httpx, "get", lambda *a, **k: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {"data": [{"id": "model-offline"}]}))
    seen = {}
    app = object()
    bank = SimpleNamespace(close=lambda: seen.update(closed=True))

    def application(root, **kwargs):
        seen.update(root=root, **kwargs)
        return app, bank

    monkeypatch.setattr(run, "application", application)
    monkeypatch.setattr(uvicorn, "run", lambda actual, **kwargs: seen.update(app=actual))
    run.main()
    assert seen["inquiry_config"] == (inquiries or {})
    assert seen["root"] == tmp_path.resolve()
    assert seen["provider"] == "flujo"
    assert seen["app"] is app and seen["closed"] is True


def test_invalid_private_config_fails_before_provider_or_host_start(tmp_path, monkeypatch):
    import httpx

    config = tmp_path / "invalid.json"
    config.write_text("[]", encoding="utf-8")
    monkeypatch.setenv("BANKING_CONFIG_FILE", str(config))
    monkeypatch.setattr("sys.argv", ["run.py", "--private-dir", str(tmp_path)])
    monkeypatch.setattr(httpx, "get", lambda *a, **k: pytest.fail("provider contacted before config validation"))
    monkeypatch.setattr(run, "application", lambda *a, **k: pytest.fail("host started with invalid config"))
    with pytest.raises(ValueError, match="Banking configuration must be an object"):
        run.main()


