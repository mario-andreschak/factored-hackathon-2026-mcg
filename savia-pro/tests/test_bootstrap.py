"""Mock bootstrap tools; never install packages, compile data or start a server."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _sandbox(tmp_path, script):
    app = tmp_path / "app"
    (app / "web").mkdir(parents=True)
    shutil.copyfile(ROOT / script, app / script)
    return app, tmp_path / "calls.log"


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("bash") is None, reason="Bash launcher is qualified on Linux")
@pytest.mark.parametrize("failure", ["pip", "serving", "npm-ci", "npm-build", "none", "custom-serving"])
def test_bash_bootstrap_stops_after_failed_native_stage(tmp_path, failure):
    app, trace = _sandbox(tmp_path, "run.sh")
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("python3", "npm"):
        tool = tools / name
        tool.write_text("""#!/usr/bin/env bash
printf '%s|%s\\n' "$(basename "$0")" "$*" >> "$TRACE"
case "$(basename "$0")|$*" in
  "python3|-m pip"*) [[ "$FAIL_STAGE" != pip ]] || exit 17 ;;
  "python3|tools/build_serving.py"*) [[ "$FAIL_STAGE" != serving ]] || exit 17 ;;
  "npm|ci"*) [[ "$FAIL_STAGE" != npm-ci ]] || exit 17 ;;
  "npm|run build"*) [[ "$FAIL_STAGE" != npm-build ]] || exit 17 ;;
esac
exit 0
""", encoding="utf-8")
        tool.chmod(0o700)
    env = {**os.environ, "PATH": str(tools) + os.pathsep + os.environ.get("PATH", ""),
           "TRACE": str(trace), "FAIL_STAGE": failure}
    if failure == "custom-serving":
        custom = tmp_path / "custom-serving.duckdb"
        custom.write_bytes(b"synthetic existing marker, no database opened")
        env["SAVIA_SERVING"] = str(custom)
    else:
        env.pop("SAVIA_SERVING", None)
    result = subprocess.run([shutil.which("bash"), str(app / "run.sh")], env=env,
                            capture_output=True, text=True, timeout=30)
    calls = trace.read_text(encoding="utf-8").splitlines()
    server_calls = [call for call in calls if "server.main" in call]
    if failure in ("none", "custom-serving"):
        assert result.returncode == 0, result.stderr
        assert len(server_calls) == 1
    else:
        assert result.returncode != 0
        assert not server_calls
        expected_count = {"pip": 1, "serving": 2, "npm-ci": 3, "npm-build": 4}[failure]
        assert len(calls) == expected_count
    if failure == "custom-serving":
        assert not any("build_serving.py" in call for call in calls)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell launcher is qualified on Windows")
@pytest.mark.parametrize("failure", ["pip", "serving", "npm-ci", "npm-build", "none", "custom-serving"])
def test_powershell_bootstrap_checks_last_exit_code(tmp_path, failure):
    app, trace = _sandbox(tmp_path, "run.ps1")
    shell = shutil.which("powershell") or shutil.which("pwsh")
    assert shell is not None, "The documented Windows launcher requires PowerShell"
    custom = tmp_path / "custom-serving.duckdb"
    if failure == "custom-serving":
        custom.write_bytes(b"synthetic existing marker, no database opened")
    # Functions emulate native commands setting LASTEXITCODE. The actual
    # launcher invokes/checks each result; no pip, npm or API process exists.
    wrapper = tmp_path / "mock-tools.ps1"
    launcher = str(app / "run.ps1").replace("'", "''")
    wrapper.write_text("""$ErrorActionPreference = 'Stop'
function global:Get-Command {
    [CmdletBinding()] param([string[]]$Name)
    if ($Name[0] -eq 'python') { [pscustomobject]@{ Source='FakePython' } }
    elseif ($Name[0] -eq 'npm') { [pscustomobject]@{ Source='FakeNpm' } }
}
function global:FakePython {
    $text = $args -join ' '
    Add-Content -LiteralPath $env:TRACE -Value "python|$text"
    $global:LASTEXITCODE = 0
    if (($text -like '-m pip*' -and $env:FAIL_STAGE -eq 'pip') -or
        ($text -like 'tools/build_serving.py*' -and $env:FAIL_STAGE -eq 'serving')) {
        $global:LASTEXITCODE = 17
    }
}
function global:FakeNpm {
    $text = $args -join ' '
    Add-Content -LiteralPath $env:TRACE -Value "npm|$text"
    $global:LASTEXITCODE = 0
    if (($text -like 'ci*' -and $env:FAIL_STAGE -eq 'npm-ci') -or
        ($text -eq 'run build' -and $env:FAIL_STAGE -eq 'npm-build')) {
        $global:LASTEXITCODE = 17
    }
}
try { & '""" + launcher + """'; exit 0 } catch { Write-Error $_ -ErrorAction Continue; exit 17 }
""", encoding="utf-8")
    env = {**os.environ, "TRACE": str(trace), "FAIL_STAGE": failure}
    if failure == "custom-serving":
        env["SAVIA_SERVING"] = str(custom)
    else:
        env.pop("SAVIA_SERVING", None)
    result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(wrapper)], env=env, capture_output=True,
                            text=True, timeout=30)
    calls = trace.read_text(encoding="utf-8-sig").splitlines()
    server_calls = [call for call in calls if "server.main" in call]
    if failure in ("none", "custom-serving"):
        assert result.returncode == 0, result.stderr
        assert len(server_calls) == 1
    else:
        assert result.returncode != 0
        assert not server_calls
        expected_count = {"pip": 1, "serving": 2, "npm-ci": 3, "npm-build": 4}[failure]
        assert len(calls) == expected_count
    if failure == "custom-serving":
        assert not any("build_serving.py" in call for call in calls)
