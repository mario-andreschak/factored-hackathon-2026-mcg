"""One frozen, offline core-engine qualification; all artifacts start in ignored scratch."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

TESTS = [
    "tests/test_dispute_policy.py",
    "tests/test_dispute_query_policy.py",
    "tests/test_dispute_acceptance.py",
    "tests/test_dispute_response.py",
    "tests/test_dispute_bank_read.py",
    "tests/test_dispute_action_host.py",
    "tests/test_dispute_prior_receipts.py",
    "tests/test_dispute_state.py",
    "tests/test_dispute_handoff.py",
    "tests/test_dispute_query_state.py",
    "tests/test_dispute_source_reads.py",
    "tests/test_case_handoff_schema.py",
    "tests/test_case_handoff_receipts.py",
    "tests/test_owned_case_projection.py",
]
SOURCE_PREFIXES = ("dispute_workflow/", "banking_mcp/", "frontend/server/",
    "pipeline/", "savia_assistant/", "contracts/", "config/", "resources/", "tests/")
PACKAGES = ["pytest", "duckdb", "fastapi", "httpx", "PyJWT", "cryptography",
    "rfc8785", "PyYAML", "mcp", "pydantic", "starlette", "uvicorn", "tzdata"]


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def snapshot(root):
    names = git(root, "ls-files").splitlines()
    names = [name for name in names if name.startswith(SOURCE_PREFIXES)
             or name.startswith("requirements-") or name == "frontend/requirements.txt"]
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
              for name in sorted(names)}
    return {"git_head": git(root, "rev-parse", "HEAD"),
            "git_tree": git(root, "rev-parse", "HEAD^{tree}"),
            "git_status": git(root, "status", "--porcelain=v1"),
            "files": hashes,
            "manifest_sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True,
                separators=(",", ":")).encode()).hexdigest()}


def worker(root, output):
    os.chdir(root)
    sys.path.insert(0, str(root))
    # Selected suites use actual domain code with fictional local observations.
    # Deny external Python DNS/connect attempts while permitting event-loop
    # socket pairs/loopback plumbing. No credentials are inspected or serialized.
    import socket
    blocked = []
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo
    def permitted(address):
        return not isinstance(address, tuple) or address[0] in ("127.0.0.1", "::1", "localhost")
    def connect(sock, address):
        if not permitted(address):
            blocked.append("external_socket_connect")
            raise RuntimeError("External network access is disabled during core qualification")
        return real_connect(sock, address)
    def connect_ex(sock, address):
        if not permitted(address):
            blocked.append("external_socket_connect_ex")
            raise RuntimeError("External network access is disabled during core qualification")
        return real_connect_ex(sock, address)
    def getaddrinfo(host, *args, **kwargs):
        if host not in (None, "127.0.0.1", "::1", "localhost"):
            blocked.append("external_dns_lookup")
            raise RuntimeError("External DNS access is disabled during core qualification")
        return real_getaddrinfo(host, *args, **kwargs)
    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
    socket.getaddrinfo = getaddrinfo
    import pytest
    code = int(pytest.main(["-q", "--import-mode=importlib", "-p", "no:cacheprovider",
        *TESTS, "--junitxml=" + str(output / "junit.xml")]))
    (output / "network-guard.json").write_text(json.dumps({
        "external_python_dns_and_connect_disabled": True,
        "blocked_external_attempts": len(blocked),
        "test_scope": "generated local stores and fixture observations; no provider tests",
    }, indent=2) + "\n", encoding="utf-8")
    return code if not blocked else 1


def run(root, expected, output):
    root, output = root.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = snapshot(root)
    if before["git_head"] != expected or before["git_status"]:
        raise RuntimeError("Qualification requires the exact frozen clean commit before execution")
    dependency_versions = {name: importlib.metadata.version(name) for name in PACKAGES}
    started = datetime.now(timezone.utc).isoformat()
    clock = time.perf_counter()
    actual = [sys.executable, str(Path(__file__).resolve()), "_pytest", str(root), str(output)]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    result = subprocess.run(actual, cwd=root, env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=300)
    elapsed = time.perf_counter() - clock
    after = snapshot(root)
    (output / "pytest-output.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    if (output / "junit.xml").exists():
        for suite in ET.parse(output / "junit.xml").getroot().iter("testsuite"):
            for name in counts:
                counts[name] += int(suite.attrib.get(name, 0))
    counts["passed"] = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
    guard = json.loads((output / "network-guard.json").read_text()) if (output / "network-guard.json").exists() else None
    unchanged = before == after
    passed = (result.returncode == 0 and unchanged and counts["tests"] > 0
        and counts["failures"] == counts["errors"] == 0
        and guard is not None and guard["blocked_external_attempts"] == 0)
    command = ["python", "-m", "pytest", "-q", "--import-mode=importlib",
        "-p", "no:cacheprovider", *TESTS, "--junitxml=<output>/junit.xml"]
    receipt = {"schema": "savia-core-engine-source-qualification/v1",
        "scope": "deterministic R0-R18 dispute core, local state/ownership/consent/receipt and guarded response contracts",
        "started_at_utc": started, "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "expected_source_git_head": expected, "source_before": before, "source_after": after,
        "source_unchanged": unchanged, "command": command,
        "harness": {"sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "timeout_seconds": 300, "python_external_network_guard": True},
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
            "dependencies": dependency_versions, "pytest_plugin_autoload": False,
            "bytecode_writes": False},
        "elapsed_seconds": round(elapsed, 3), "pytest_exit_code": result.returncode,
        "junit_counts": counts, "network_guard": guard, "passed": passed,
        "provider_requests": 0 if passed else None,
        "live_banking_actions": 0,
        "artifacts": {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
            for name in ("junit.xml", "pytest-output.txt", "network-guard.json")
            if (output / name).exists()},
        "limitations": ["Source qualification over generated fixtures and doubles; no deployed customer acceptance or model quality claim.",
            "Voice, fleet/swarm, exact compiler installation and full cross-platform CI are separate scopes."]}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": passed, "source": expected, "counts": counts,
        "elapsed_seconds": round(elapsed, 3), "source_unchanged": unchanged,
        "output": str(output)}))
    return 0 if passed else 1


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "_pytest":
        raise SystemExit(worker(Path(sys.argv[2]), Path(sys.argv[3])))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    raise SystemExit(run(args.repo, args.expected_head, args.out))
