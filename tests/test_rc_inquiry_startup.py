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


@pytest.mark.parametrize("configured", [False, True])
def test_main_reads_explicit_private_settings_before_starting_host(tmp_path, monkeypatch, configured):
    import httpx
    import uvicorn

    inquiries = {"mode": "bootstrap"} if configured else {}
    monkeypatch.delenv("BANKING_CONFIG_FILE", raising=False)
    if configured:
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
    assert seen["inquiry_config"] == inquiries
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


def test_application_preserves_fixture_ledger_chat_voice_and_bootstrap(tmp_path, monkeypatch):
    import frontend.server.app

    private = tmp_path / "fictional-rc"
    run.prepare(private)
    settings_seen = []
    sentinel = object()
    monkeypatch.setattr(frontend.server.app, "create_app",
                        lambda settings, **kwargs: settings_seen.append(settings) or sentinel)
    voice = run.native_voice_config()
    disabled_fleet = json.loads((run.ROOT / "docs/submission/assistant/fleet-config.example.json")
                               .read_text(encoding="utf-8"))["inquiries"]
    for inquiries in (None, disabled_fleet):
        app, bank = run.application(private, port=43900, base_url="http://localhost:43420",
                                    model_id="model-offline", voice_config=voice,
                                    inquiry_config=inquiries)
        bank.close()
        assert app is sentinel
    default, configured = settings_seen
    assert default.inquiries == {}
    assert configured.inquiries == disabled_fleet
    assert default.chat == configured.chat
    assert default.chat["mode"] == "dispute-host/v1"
    assert default.chat["ledger_generation"]
    assert default.voice == configured.voice == voice
    assert default.profiles == configured.profiles
    assert default.state_dir == configured.state_dir == private / "instance"
    assert default.auth_fingerprint() == configured.auth_fingerprint()
