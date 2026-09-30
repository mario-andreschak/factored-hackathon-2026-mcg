"""Pure gates for a separate, held synthetic assembly checkpoint."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

REPOSITORY = "mario-andreschak/factored-hackathon-2026-mcg"
BANK = "71ac0f020303abfd0073302a148752f0d2c9f23b"
FLUJO = "51ff39fc5bac84cbbb49bbd2b21b5ab89de8b14b"
PACKAGE_HEAD = "6ebeaf73b57e7d79c691e2e48763e2adc7928398"
PACKAGE_RUN = 36679668855
PACKAGE_ATTEMPT = 1
RECEIPTS_ID = 11081194098
RECEIPTS_SHA = "31a8ce432309d4154dc67f6a45ac83dcb6c382dc3c9fc495db20e9a8f3a84120"
OCI_ID = 11080919734
OCI_ZIP_SHA = "1853f64b4a732af88880862a6b79f2d655261b9ed6eddc2e90c72562e7699202"
OCI_TAR_SHA = "ddf7cd40b2b6545ddfa458c235494789e52076747bffb52dd8ceb2b636cbd5a9"
OCI_TAR_BYTES = 1867014144
FIXTURE_PIN_SHA = "7fbd438c1b58a7bfc68132f979f0bfbd2422f289b6b849522d50b79001d9a405"
DATASET_FILES = {
    "fixture_pin.json": FIXTURE_PIN_SHA,
    "generate_fixture.py": "23cade81be79ccf70392602bbf3f7cf5c5724821c5f9106d7717cba2f59aabf1",
    "source_cache.json": "1ddabccb0329ca7c6eb0d77c63563d2d1fb4fff6fe303aa350398c4f27b474f9",
    "source/pipeline/contracts.yaml": "98f0add581f437c79a119682a90723451722de025b6af867e892487d8693972a",
}
# Removing this hold requires another exact-source review. No dispatch can
# enable runtime in this preparation revision.
PREPARATION_ONLY = True


class CheckpointError(Exception):
    """Fixed public codes only: never include secrets or upstream body text."""


def require(value: object, code: str) -> None:
    if not value:
        raise CheckpointError(code)


def strict_json(content: bytes | str) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate_json_key")
            result[key] = value
        return result

    def nonfinite(_):
        raise CheckpointError("nonfinite_json")

    try:
        value = json.loads(content, object_pairs_hook=unique, parse_constant=nonfinite)
    except (ValueError, UnicodeError):
        raise CheckpointError("invalid_json") from None
    require(isinstance(value, dict), "expected_json_object")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_path(value: object) -> str:
    require(isinstance(value, str) and value and "\\" not in value and ":" not in value
            and not value.startswith("/") and not any(ord(c) < 32 for c in value),
            "unsafe_path")
    parts = value.split("/")
    require(all(p not in {"", ".", ".."} for p in parts), "unsafe_path")
    require(str(PurePosixPath(value)) == value, "unsafe_path")
    return value


def extract_zip(source: Path, target: Path, *, max_bytes: int,
                only: set[str] | None = None) -> None:
    require(not target.exists(), "extract_destination_exists")
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        require(0 < len(entries) <= 10000, "zip_inventory_limit")
        names, total = set(), 0
        for entry in entries:
            name = safe_path(entry.filename.rstrip("/") if entry.is_dir() else entry.filename)
            require(name not in names, "duplicate_zip_path")
            names.add(name)
            kind = stat.S_IFMT(entry.external_attr >> 16)
            require(kind in {0, stat.S_IFREG, stat.S_IFDIR}, "zip_special_entry")
            require(not entry.flag_bits & 1, "encrypted_zip")
            require(only is None or name in only, "unexpected_zip_file")
            total += entry.file_size
            require(total <= max_bytes, "zip_size_limit")
        target.mkdir(parents=True)
        for entry in entries:
            path = target / entry.filename
            if entry.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as stream, path.open("xb") as output:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        output.write(block)


def validate_remote(env: dict[str, str]) -> None:
    require(env.get("GITHUB_ACTIONS") == "true"
            and env.get("RUNNER_ENVIRONMENT") == "github-hosted"
            and env.get("RUNNER_OS") == "Linux"
            and env.get("GITHUB_REPOSITORY") == REPOSITORY,
            "private_hosted_linux_runner_required")


def require_remote_execution() -> None:
    import os
    validate_remote(dict(os.environ))
    require(PREPARATION_ONLY is False, "integration_checkpoint_held")


def require_runtime_release(env: dict[str, str], release: dict | None = None) -> dict:
    validate_remote(env)
    require(PREPARATION_ONLY is False, "integration_checkpoint_held")
    if release is None:
        release = strict_json(Path("/run/review/release.json").read_bytes())
    require(set(release) == {"schema", "reviewed_head", "root_review", "package_head",
                            "restored_image_id", "derived_image_id", "artifact_content_verified",
                            "derived_source_verified", "fixture_pin_sha256", "frontend_gate_source",
                            "bundle_source_head", "bundle_manifest_sha256"},
            "runtime_release_fields")
    require(release["schema"] == "banking-synthetic-runtime-release/v1"
            and release["reviewed_head"] == env.get("GITHUB_SHA")
            and re.fullmatch(r"[a-f0-9]{40}", release["reviewed_head"])
            and release["root_review"] == "approved"
            and release["package_head"] == PACKAGE_HEAD
            and release["artifact_content_verified"] is True
            and release["derived_source_verified"] is True
            and all(isinstance(release[k], str) and re.fullmatch(r"sha256:[a-f0-9]{64}", release[k])
                    for k in ("restored_image_id", "derived_image_id"))
            and release["fixture_pin_sha256"] == FIXTURE_PIN_SHA
            and isinstance(release["bundle_manifest_sha256"], str)
            and re.fullmatch(r"[a-f0-9]{64}", release["bundle_manifest_sha256"])
            and all(isinstance(release[k], str) and re.fullmatch(r"[a-f0-9]{40}", release[k])
                    for k in ("bundle_source_head", "frontend_gate_source")), "runtime_release_binding")
    return release


def validate_review(review: dict, head: str) -> dict:
    require(set(review) == {"schema", "reviewed_head", "root_review", "scenario_mode",
                            "fixture_pin_sha256", "frontend_gate_source", "bundle"}, "review_fields")
    require(review["schema"] == "banking-synthetic-integration-review/v1"
            and review["reviewed_head"] == head and re.fullmatch(r"[a-f0-9]{40}", head)
            and review["root_review"] == "approved", "exact_source_review_required")
    require(review["fixture_pin_sha256"] == FIXTURE_PIN_SHA, "dataset_file_pin_required")
    require(isinstance(review["frontend_gate_source"], str)
            and re.fullmatch(r"[a-f0-9]{40}", review["frontend_gate_source"]),
            "reviewed_dependency_required")
    require(review["scenario_mode"] == "stock-and-authored-coverage",
            "scenario_mode_invalid")
    bundle = review["bundle"]
    require(isinstance(bundle, dict) and set(bundle) == {
        "artifact_id", "run_id", "source_head", "zip_sha256", "manifest_sha256",
        "graph_sha256", "policy_template_sha256", "fixture_provider_sha256"},
        "bundle_fields")
    require(all(type(bundle[k]) is int and bundle[k] > 0 for k in ("artifact_id", "run_id"))
            and isinstance(bundle["source_head"], str)
            and re.fullmatch(r"[a-f0-9]{40}", bundle["source_head"])
            and all(isinstance(bundle[k], str) and re.fullmatch(r"[a-f0-9]{64}", bundle[k])
                    for k in ("zip_sha256", "manifest_sha256", "graph_sha256",
                              "policy_template_sha256", "fixture_provider_sha256")),
            "bundle_identity_required")
    return review


def assert_package_run(run: dict, repository: dict) -> None:
    require(repository.get("full_name") == REPOSITORY and repository.get("private") is True,
            "private_repository_required")
    require(run.get("id") == PACKAGE_RUN and run.get("head_sha") == PACKAGE_HEAD
            and run.get("run_attempt") == PACKAGE_ATTEMPT and run.get("status") == "completed"
            and run.get("conclusion") == "success"
            and run.get("path") == ".github/workflows/banking-package-issue21-preflight.yml",
            "exact_successful_package_run_required")


def assert_artifact(meta: dict, artifact_id: int, run_id: int, head: str, digest: str,
                    *, name: str | None = None) -> None:
    origin = meta.get("workflow_run", {})
    require(meta.get("id") == artifact_id and meta.get("expired") is False
            and meta.get("digest") == "sha256:" + digest
            and origin.get("id") == run_id and origin.get("head_sha") == head
            and (name is None or meta.get("name") == name), "artifact_binding_mismatch")


def assert_bridge(bridge: dict) -> None:
    require(bridge.get("checkpoint") == "banking-package-issue21/v2"
            and bridge.get("proof_kind") == "verified_oci_export_bridge"
            and bridge.get("status") == "passed"
            and bridge.get("candidate_revision") == PACKAGE_HEAD
            and bridge.get("banking_source_revision") == BANK
            and bridge.get("flujo_source_revision") == FLUJO
            and bridge.get("archive") == {"bytes": OCI_TAR_BYTES, "sha256": OCI_TAR_SHA}
            and bridge.get("platform") == {"os": "linux", "architecture": "amd64"},
            "package_bridge_binding_mismatch")
