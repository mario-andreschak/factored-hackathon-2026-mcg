"""Exercise fresh RC startup against its real POSIX durable-pin permission gate."""

import os
import stat
import sys

import pytest


@pytest.mark.skipif(os.name != "posix", reason="The durable-pin directory permission check is POSIX-specific")
def test_cli_rc_initializes_real_fixture_with_private_ledger_permissions(tmp_path, monkeypatch):
    from standalone.savia_whatsapp import __main__ as cli
    from standalone.savia_whatsapp import runtime
    import uvicorn

    # Real RC initialization belongs to the admitted source package. The image
    # qualification runs this test with genuine source and permission checks.
    if not (runtime.ROOT / "standalone-package.json").is_file():
        pytest.skip("Real RC startup requires an admitted exported bundle")

    previous_umask = os.umask(0o022)
    try:
        # No account state, retained bank ledger, consent, or authorization gate
        # is modified. This fixture is new authored fiction for this one test.
        state = tmp_path / "fresh-rc"
        runtime.rc_module().prepare(state)
        observed = []

        def observe_start(app, **kwargs):
            # Construct the actual RC app and its middleware, but do not bind a
            # listener or execute a provider request. The bank closes normally
            # in serve_rc's finally block after this stub returns.
            observed.append((app, kwargs))

        monkeypatch.setattr(uvicorn, "run", observe_start)
        monkeypatch.setenv("OPENROUTER_API_KEY", "offline-fiction-fixture-test")
        monkeypatch.setattr(sys, "argv", ["savia-whatsapp", "rc", "--state", str(state), "--port", "43982"])
        cli.main()

        assert len(observed) == 1
        assert observed[0][1]["host"] == "127.0.0.1"
        assert observed[0][1]["port"] == 43982
        instance = state / "instance"
        pin = instance / "dispute-bank-generation.json"
        assert stat.S_IMODE(instance.stat().st_mode) == 0o700
        assert stat.S_IMODE(pin.stat().st_mode) == 0o600
        assert pin.stat().st_uid == os.geteuid()
        assert pin.stat().st_nlink == 1
        assert os.umask(0o077) == 0o077
    finally:
        os.umask(previous_umask)
