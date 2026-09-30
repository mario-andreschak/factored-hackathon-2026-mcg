"""Produce code-only review files from immutable Git blobs. Starts no runtime.

This is NOT an execution release or a successful hosted artifact. GitHub's outer
artifact ID/digest/run/head must be obtained and separately reviewed later.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

from contract import BANK, DATASET_FILES, FIXTURE_PIN_SHA, FRONTEND_FILES, FRONTEND_GATE_HEAD, require, safe_path

FIXTURE_FILES = ("deterministic_provider.py", "dispatch_observer.cjs", "fixture_setup.py", "flow-snapshot.json",
                 "integration_provider.py", "observer_adapter.py", "policy-template.json")


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, timeout=30).stdout


def blob(repo: Path, head: str, relative: str) -> bytes:
    require(re.fullmatch(r"[a-f0-9]{40}", head) is not None, "immutable_source_head_required")
    return git(repo, "show", head + ":" + safe_path(relative))


def build(repo: Path, frontend_repo: Path, *, head: str) -> tuple[dict[str, bytes], dict]:
    require(git(repo, "rev-parse", head + "^{commit}").decode().strip() == head, "source_commit_required")
    files = {}
    inventory = json.loads(blob(repo, head, "scripts/synthetic_integration/bank-source.sha256.json"))
    require(len(inventory) == 23, "bank_source_closure")
    for relative, digest in inventory.items():
        raw = blob(repo, BANK, relative)
        require(hashlib.sha256(raw).hexdigest() == digest, "bank_source_blob_mismatch")
        files["banking/" + relative] = raw
    # Production frontend remains the reviewed stock source; include Python API
    # and requirements only. Browser bundles/static builds are outside this phase.
    paths = git(frontend_repo, "ls-tree", "-r", "--name-only", FRONTEND_GATE_HEAD, "frontend/server").decode().splitlines()
    paths = sorted(path for path in paths if path.endswith(".py")) + ["frontend/requirements.txt"]
    require({"frontend/server/app.py", "frontend/server/chat.py", "frontend/requirements.txt"} <= set(paths),
            "frontend_api_closure")
    for relative in paths:
        raw = blob(frontend_repo, FRONTEND_GATE_HEAD, relative)
        require(raw == blob(repo, BANK, relative), "frontend_production_source_changed")
        files[relative] = raw
    for relative, digest in FRONTEND_FILES.items():
        raw = blob(frontend_repo, FRONTEND_GATE_HEAD, "scripts/synthetic_integration/" + relative)
        require(hashlib.sha256(raw).hexdigest() == digest, "frontend_helper_blob_mismatch")
        files["fixture/frontend_helpers/" + relative] = raw
    for relative, digest in DATASET_FILES.items():
        raw = blob(repo, head, "scripts/synthetic_integration/dataset_source/" + relative)
        require(hashlib.sha256(raw).hexdigest() == digest, "dataset_blob_mismatch")
        files["fixture/dataset_source/" + relative] = raw
    for relative in FIXTURE_FILES:
        files["fixture/" + relative] = blob(repo, head, "scripts/synthetic_integration/fixture/" + relative)
    manifest = {"schema": "banking-synthetic-fixture-source/v1", "source_head": head,
                "fixture_pin_sha256": FIXTURE_PIN_SHA, "frontend_gate_source": FRONTEND_GATE_HEAD,
                "scenario_mode": "stock-and-authored-coverage",
                "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(files.items())}}
    return files, manifest


def publish_source(files: dict[str, bytes], manifest: dict, destination: Path) -> dict:
    require(destination.is_absolute() and not destination.exists(), "fresh_source_output_required")
    destination.mkdir(mode=0o700)
    manifest_raw = (json.dumps(manifest, indent=2) + "\n").encode()
    zip_path = destination / "private-source-review.zip"
    with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted({**files, "source-manifest.json": manifest_raw}.items()):
            info = zipfile.ZipInfo(safe_path(name), date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system, info.external_attr = 3, 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, raw)
    (destination / "source-manifest.json").write_bytes(manifest_raw)
    identities = {"schema": "private-synthetic-source-review/v1", "source_head": manifest["source_head"],
                  "execution_enabled": False, "runtime_claims": 0, "hosted_artifact": None,
                  "files": len(files), "zip_sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
                  "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
                  **{field: manifest["files"]["fixture/" + filename] for filename, field in (
                      ("flow-snapshot.json", "graph_sha256"), ("policy-template.json", "policy_template_sha256"),
                      ("deterministic_provider.py", "fixture_provider_sha256"),
                      ("dispatch_observer.cjs", "dispatch_observer_sha256"),
                      ("integration_provider.py", "integration_provider_sha256"),
                      ("observer_adapter.py", "observer_adapter_sha256"))}}
    (destination / "source-review.json").write_text(json.dumps(identities, indent=2) + "\n", encoding="utf-8", newline="\n")
    return identities


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--frontend-repo", type=Path, required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    files, manifest = build(args.repo, args.frontend_repo, head=args.source_head)
    print(json.dumps(publish_source(files, manifest, args.output), indent=2))
