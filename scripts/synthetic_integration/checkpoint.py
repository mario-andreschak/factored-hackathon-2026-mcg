"""Held hosted-runner orchestration. Never invoke locally or dispatch this revision."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import re

import contract
from contract import CheckpointError, require, safe_path, sha256, strict_json
from consume_package import (api, assert_artifact, consume, download, typed_equal,
                             verify_installed_source, verify_filemap, check_runtime_config)


def require_execution_release() -> None:
    require(contract.PREPARATION_ONLY is False, "integration_checkpoint_held")


def prepare_bundle(review: dict, root: Path) -> Path:
    bundle = review["bundle"]
    run = api(f"/repos/{contract.REPOSITORY}/actions/runs/{bundle['run_id']}")
    require(run.get("head_sha") == bundle["source_head"] and run.get("status") == "completed"
            and run.get("conclusion") == "success", "fixture_bundle_source_run_required")
    metadata = api(f"/repos/{contract.REPOSITORY}/actions/artifacts/{bundle['artifact_id']}")
    assert_artifact(metadata, bundle["artifact_id"], bundle["run_id"], bundle["source_head"],
                    bundle["zip_sha256"])
    source = root / "bundle.zip"
    download(bundle["artifact_id"], source, bundle["zip_sha256"], 64 * 1024 * 1024)
    target = root / "bundle"
    contract.extract_zip(source, target, max_bytes=64 * 1024 * 1024)
    manifest = target / "source-manifest.json"
    require(sha256(manifest) == bundle["manifest_sha256"], "fixture_manifest_binding")
    contents = strict_json(manifest.read_bytes())
    require(set(contents) == {"schema", "source_head", "fixture_pin_sha256", "frontend_gate_source", "scenario_mode", "files"}
            and contents["schema"] == "banking-synthetic-fixture-source/v1"
            and contents["source_head"] == bundle["source_head"]
            and all(contents[key] == review[key] for key in
                    ("fixture_pin_sha256", "frontend_gate_source", "scenario_mode")),
            "fixture_source_binding")
    files = contents["files"]
    require(isinstance(files, dict) and files, "fixture_file_inventory_required")
    for relative, digest in files.items():
        relative = safe_path(relative)
        parts = relative.split("/")
        require(parts[0] in {"banking", "frontend", "fixture"}
                and not any(p.startswith(".") or p in {"node_modules", "__pycache__", "data", "state"}
                            for p in parts)
                and (Path(relative).suffix in {".py", ".txt", ".json", ".md", ".mjs", ".cjs",
                                              ".js", ".ts", ".tsx", ".css", ".html", ".toml"}
                     or relative == "banking/pipeline/contracts.yaml"
                     or relative == "fixture/dataset_source/source/pipeline/contracts.yaml"),
                "fixture_code_only_required")
        path = target / relative
        require(path.is_file() and not path.is_symlink() and sha256(path) == digest,
                "fixture_source_file_mismatch")
    actual = {p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()}
    require(actual == set(files) | {"source-manifest.json"}, "fixture_unreferenced_file")
    for relative, digest in contract.DATASET_FILES.items():
        require(files.get("fixture/dataset_source/" + relative) == digest,
                "dataset_portable_source_binding")
    for relative, digest in contract.FRONTEND_FILES.items():
        require(files.get("fixture/frontend_helpers/" + relative) == digest, "frontend_helper_source_binding")
    require({"fixture/integration_provider.py", "banking/requirements-mcp.txt",
             "fixture/flow-snapshot.json", "fixture/policy-template.json",
             "fixture/deterministic_provider.py",
             "frontend/requirements.txt", "frontend/server/app.py", "frontend/server/chat.py"} <= set(files),
            "fixture_required_source_missing")
    for filename, field in (("flow-snapshot.json", "graph_sha256"),
                            ("policy-template.json", "policy_template_sha256"),
                            ("deterministic_provider.py", "fixture_provider_sha256")):
        require(sha256(target / "fixture" / filename) == bundle[field], "bootstrap_source_binding")
    return target


def verify_stock_bundle(bundle: Path, receipts: Path) -> None:
    inventory = json.loads((receipts / "runtime/installed-source-inventory.json").read_bytes())
    expected = {row["path"]: row["sha256"] for row in inventory}
    observed = {p.relative_to(bundle / "banking").as_posix(): sha256(p)
                for p in (bundle / "banking").rglob("*") if p.is_file()}
    require(expected == observed, "stock_bank_source_modified")


def validate_derived(image: dict, restored: dict, raw: dict, bridge: dict, review: dict) -> None:
    require(image["Os"] == "linux" and image["Architecture"] == "amd64"
            and re.fullmatch(r"sha256:[a-f0-9]{64}", image["Id"]), "derived_platform")
    layers = image["RootFS"]["Layers"]
    prefix = restored["rootfs_diff_ids"]
    require(len(layers) > len(prefix) and layers[:len(prefix)] == prefix, "derived_base_layer_prefix")
    runtime = image["Config"]
    expected = dict(raw)
    expected.update(Entrypoint=["/opt/fixture-front/.venv/bin/python", "/opt/integration/harness/inside.py"],
                    Cmd=runtime.get("Cmd"), WorkingDir="/opt/integration/harness", User="node")
    require(runtime.get("Cmd") is None or runtime.get("Cmd") == [], "derived_no_extra_command")
    labels = dict(raw["Labels"])
    labels.update({"io.flujo.integration.scope": "derived-fictional-no-model-assembly",
                   "io.flujo.integration.fixture.source": review["fixture_pin_sha256"],
                   "io.flujo.integration.frontend.source": review["frontend_gate_source"]})
    expected["Labels"] = labels
    def env_map(values):
        require(isinstance(values, list) and all(isinstance(v, str) and "=" in v for v in values),
                "derived_environment_shape")
        result = {}
        for value in values:
            key, data = value.split("=", 1)
            require(key not in result, "derived_duplicate_environment")
            result[key] = data
        return result
    env = env_map(raw["Env"])
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1",
               PYTHONPATH="/opt/integration/harness:/opt/integration/fixture:/opt/fixture-front",
               SCENARIO_MODE=review["scenario_mode"])
    require(env_map(runtime["Env"]) == env, "derived_environment_mismatch")
    expected["Env"] = runtime["Env"]  # mapped equality checked without ordering assumptions
    check_runtime_config(runtime, expected, bridge)


def verify_bundle_in_image(image_id: str, bundle: Path, harness: Path, destination: Path) -> int:
    files = {}
    roots = {"banking": "/opt/fixture-bank/", "frontend": "/opt/fixture-front/frontend/",
             "fixture": "/opt/integration/fixture/"}
    for source, installed in roots.items():
        for path in (bundle / source).rglob("*"):
            if path.is_file():
                files[installed + path.relative_to(bundle / source).as_posix()] = sha256(path)
    for path in harness.rglob("*"):
        if path.is_file():
            files["/opt/integration/harness/" + path.relative_to(harness).as_posix()] = sha256(path)
    return verify_filemap(image_id, files, destination)


def main() -> int:
    contract.validate_remote(dict(os.environ))
    require_execution_release()
    review = contract.validate_review(
        strict_json(os.environ["CHECKPOINT_REVIEW"]), os.environ["GITHUB_SHA"])
    root = Path(os.environ["RUNNER_TEMP"]) / "synthetic-integration"
    require(not root.exists(), "fresh_runner_directory_required")
    root.mkdir(mode=0o700)
    evidence = root / "evidence"
    evidence.mkdir()
    evidence.chmod(0o777)  # this new controlled directory contains only sanitized evidence
    result = {"status": "failed", "failure": "checkpoint_failed",
              "proof_kind": "deterministic_no_model_assembly_safety"}
    try:
        bundle = prepare_bundle(review, root)
        restored = consume(root / "package")
        os.environ.pop("GH_TOKEN", None)
        verify_stock_bundle(bundle, root / "package/receipts")
        context = root / "context"
        context.mkdir()
        shutil.copytree(bundle, context / "bundle")
        shutil.copytree(Path(__file__).parent, context / "harness",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(Path(__file__).parent / "Dockerfile", context / "Dockerfile")
        # Build contains code/dependencies only. Secrets and fictional data are
        # generated later, inside the isolated network-none runtime.
        iidfile = root / "derived-image.id"
        # OCI named context is bound to the verified manifest digest, never a
        # mutable FROM tag. Buildx --iidfile supplies the loaded image ID.
        context_uri = "oci-layout://" + str(root / "package/verified-layout") + "@" + restored["manifest_digest"]
        subprocess.run(["docker", "buildx", "build", "--builder", "default", "--load",
                        "--iidfile", str(iidfile), "--build-context", "restored-package=" + context_uri,
                        "--build-arg", "FIXTURE_SOURCE=" + review["fixture_pin_sha256"],
                        "--build-arg", "FRONTEND_GATE_SOURCE=" + review["frontend_gate_source"],
                        "--build-arg", "SCENARIO_MODE=" + review["scenario_mode"], str(context)],
                       check=True, timeout=1800, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Source identity of the original image was checked before deriving.
        # The original package ID and derived fixture ID are distinct records.
        image_id = iidfile.read_text().strip()
        require(re.fullmatch(r"sha256:[a-f0-9]{64}", image_id), "derived_image_id_required")
        derived = json.loads(subprocess.check_output(
            ["docker", "image", "inspect", image_id], timeout=60))[0]
        require(derived["Id"] == image_id, "derived_image_id_mismatch")
        bridge = strict_json((root / "package/receipts/oci-export-bridge.json").read_bytes())
        raw = strict_json((root / "package/receipts/oci-metadata/oci-config.json").read_bytes())["config"]
        validate_derived(derived, restored, raw, bridge, review)
        original_count = verify_installed_source(image_id, root / "package/receipts",
                                                root / "derived-original-source")
        fixture_count = verify_bundle_in_image(image_id, bundle, context / "harness",
                                              root / "derived-fixture-source")
        identities = {"restored_package": restored, "derived_image_id": derived["Id"],
                      "fixture_pin_sha256": review["fixture_pin_sha256"],
                      "bundle_source_head": review["bundle"]["source_head"],
                      "frontend_gate_source": review["frontend_gate_source"],
                      "bundle_manifest_sha256": review["bundle"]["manifest_sha256"],
                      "integration_source": review["reviewed_head"],
                      "scenario_mode": review["scenario_mode"],
                      "derived_original_files_verified": original_count,
                      "derived_fixture_files_verified": fixture_count}
        (evidence / "source-identities.json").write_text(json.dumps(identities, indent=2) + "\n")
        # Single disposable container: frontend -> loopback FLUJO -> stdio MCP.
        # No host ports, Docker socket, provider network, shared paths or token.
        release = {"schema": "banking-synthetic-runtime-release/v1",
                   "reviewed_head": review["reviewed_head"], "root_review": review["root_review"],
                   "package_head": contract.PACKAGE_HEAD, "restored_image_id": restored["image_id"],
                   "derived_image_id": image_id, "artifact_content_verified": True,
                   "derived_source_verified": True, "fixture_pin_sha256": review["fixture_pin_sha256"],
                   "bundle_source_head": review["bundle"]["source_head"],
                   "bundle_manifest_sha256": review["bundle"]["manifest_sha256"],
                   "frontend_gate_source": review["frontend_gate_source"]}
        release_file = root / "release.json"
        release_file.write_text(json.dumps(release) + "\n")
        completed = subprocess.run([
            "docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit", "256",
            "--memory", "3g", "--cpus", "2",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=512m,mode=1777",
            "--tmpfs", "/run/synthetic-integration:rw,nosuid,nodev,size=512m,mode=1777",
            "--mount", f"type=bind,src={evidence},dst=/evidence",
            "--mount", f"type=bind,src={release_file},dst=/run/review/release.json,readonly",
            "--env", "GITHUB_ACTIONS=true", "--env", "RUNNER_ENVIRONMENT=github-hosted",
            "--env", "RUNNER_OS=Linux", "--env", "GITHUB_REPOSITORY=" + contract.REPOSITORY,
            "--env", "GITHUB_SHA=" + review["reviewed_head"],
            image_id], timeout=600, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        require(completed.returncode == 0, "runtime_checkpoint_failed")
        observations = strict_json((evidence / "observations.json").read_bytes())
        require(observations.get("status") == "passed", "runtime_observations_failed")
        result = {"status": "passed", "proof_kind": observations["proof_kind"],
                  "integration_source": review["reviewed_head"],
                  "package_head": contract.PACKAGE_HEAD, "package_run": contract.PACKAGE_RUN,
                  "scenario_mode": review["scenario_mode"],
                  "unproven": observations["unproven"]}
    except Exception:
        # Never echo upstream URLs, credentials, exception strings or raw logs.
        result = {"status": "failed", "failure": "checkpoint_failed",
                  "proof_kind": "deterministic_no_model_assembly_safety"}
    finally:
        os.environ.pop("GH_TOKEN", None)
        (evidence / "checkpoint.json").write_text(json.dumps(result, indent=2) + "\n")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except CheckpointError:
        print("Synthetic integration remains held; no runtime was started.")
        sys.exit(1)
    except Exception:
        print("Synthetic integration refused before runtime.")
        sys.exit(1)
