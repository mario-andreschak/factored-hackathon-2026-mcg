import sys
from types import SimpleNamespace

import pytest

from standalone.savia_whatsapp import __main__ as cli


@pytest.mark.parametrize("flags,expected_host", [
    ([], "127.0.0.1"),
    (["--container", "--fly-private"], "fly-local-6pn"),
])
def test_private_fly_binding_overrides_container_wildcard(tmp_path, monkeypatch, flags, expected_host):
    import uvicorn

    mcp = tmp_path / "mcp"
    (mcp / "dist").mkdir(parents=True)
    (mcp / "dist/index.js").write_text("// offline binding test")
    app = SimpleNamespace(state=SimpleNamespace())
    monkeypatch.setattr(cli, "create_control", lambda *_, **__: app)
    observed = []

    class Server:
        def __init__(self, config):
            observed.append(config)
        def run(self):
            pass

    monkeypatch.setattr(uvicorn, "Server", Server)
    monkeypatch.setattr(sys, "argv", ["savia-whatsapp", "serve", "--state", str(tmp_path / "state"),
                                     "--mcp-dir", str(mcp), *flags])
    cli.main()
    assert len(observed) == 1
    assert observed[0].host == expected_host
    assert observed[0].port == 43980
    assert observed[0].app is app
