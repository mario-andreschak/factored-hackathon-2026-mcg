"""Generated malformed private configuration must not disclose inputs at startup."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("kind", ["short_token", "missing_delegated_mapping", "unpaired_rates"])
def test_invalid_private_config_stderr_omits_generated_secret_and_starts_no_service(tmp_path, kind):
    root = Path(__file__).resolve().parents[1]
    secret = "DUMMYX_STARTUP_SECRET" if kind == "short_token" else "DUMMYX_STARTUP_SECRET" * 3
    state, authority = tmp_path / "state", tmp_path / "authority"
    config = {"service_token": secret, "data_dir": str(tmp_path / "data"),
              "state_db": str(state / "bank-ledger.sqlite3")}
    if kind == "unpaired_rates":
        config["event_rates_file"] = str(tmp_path / "generated-rates.csv")
    path = tmp_path / "generated-private-config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if not key.startswith("BANKING_")}
    result = subprocess.run([sys.executable, str(root / "scripts/run_dispute.py"),
        "--state-dir", str(state), "--bank-config-file", str(path),
        "--native-url", "http://127.0.0.1:43921", "--native-authority-dir", str(authority)],
        cwd=root, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert "ValidationError" in result.stderr
    assert "DUMMYX" not in result.stdout + result.stderr
    assert "input_value=" not in result.stdout + result.stderr
    assert not state.exists() and not authority.exists()
