"""Joined RC settings checks use the full dispute application's dependencies."""
import json

from deploy.rc import run


def test_application_preserves_fixture_ledger_chat_voice_and_bootstrap(tmp_path, monkeypatch):
    import frontend.server.app
    import socket

    def denied(*args, **kwargs):
        raise AssertionError("startup settings tests must not access the network")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    private = tmp_path / "fictional-rc"
    run.prepare(private)
    # public_start.py uses umask(0o077); retain that private state boundary here.
    (private / "instance").mkdir(mode=0o700)
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
