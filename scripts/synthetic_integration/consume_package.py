"""Remote-only artifact consumption; no application startup or model calls."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.error
import urllib.parse
import urllib.request

from contract import (BANK, FLUJO, PACKAGE_HEAD, PACKAGE_RUN, RECEIPTS_ID, RECEIPTS_SHA,
                      OCI_ID, OCI_ZIP_SHA, OCI_TAR_SHA, OCI_TAR_BYTES, REPOSITORY,
                      CheckpointError, assert_artifact, assert_bridge, assert_package_run,
                      extract_zip, require, safe_path, sha256, strict_json, validate_remote,
                      require_remote_execution)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def api(path: str) -> dict:
    require_remote_execution()
    require(path == "/repos/" + REPOSITORY or path.startswith("/repos/" + REPOSITORY + "/"),
            "unapproved_github_api_path")
    request = urllib.request.Request("https://api.github.com" + path, headers={
        "Authorization": "Bearer " + os.environ["GH_TOKEN"],
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    # Never forward the GitHub token across a redirect.
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=60) as response:
        return strict_json(response.read(4 * 1024 * 1024))


def download(artifact_id: int, target: Path, expected: str, limit: int) -> None:
    require_remote_execution()
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip",
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"]})
    try:
        urllib.request.build_opener(NoRedirect()).open(request, timeout=60)
    except urllib.error.HTTPError as error:
        require(error.code == 302, "artifact_download_redirect_required")
        location = error.headers.get("Location", "")
    else:
        raise CheckpointError("artifact_download_redirect_required")
    parsed = urllib.parse.urlsplit(location)
    require(parsed.scheme == "https" and parsed.hostname is not None
            and (parsed.hostname.endswith(".blob.core.windows.net")
                 or parsed.hostname.endswith(".actions.githubusercontent.com"))
            and parsed.username is None and parsed.password is None,
            "unapproved_artifact_download_origin")
    # Signed artifact URL is used without Authorization and is never logged.
    with urllib.request.build_opener(NoRedirect()).open(location, timeout=60) as response:
        total = 0
        with target.open("xb") as output:
            for block in iter(lambda: response.read(1024 * 1024), b""):
                total += len(block)
                require(total <= limit, "artifact_download_size_limit")
                output.write(block)
    require(sha256(target) == expected, "artifact_zip_hash_mismatch")


def verify_receipts(root: Path) -> dict:
    sums = (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    seen = set()
    for row in sums:
        digest, path = row.split("  ", 1)
        path = safe_path(path.removeprefix("./"))
        require(path not in seen, "duplicate_receipt_path")
        seen.add(path)
        # The separate OCI archive is checked against a fixed digest below.
        if path == "candidate.oci.tar":
            require(digest == OCI_TAR_SHA, "receipt_archive_hash_mismatch")
        else:
            file = root / path
            require(file.is_file() and not file.is_symlink() and sha256(file) == digest,
                    "receipt_file_hash_mismatch")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    require(actual == (seen - {"candidate.oci.tar"}) | {"SHA256SUMS"}, "receipt_inventory_mismatch")
    bridge = strict_json((root / "oci-export-bridge.json").read_bytes())
    assert_bridge(bridge)
    return bridge


def verify_archive(path: Path, bridge: dict) -> dict:
    """Replay content hashes/layers. Original daemon/base observations stay separate."""
    require(path.stat().st_size == OCI_TAR_BYTES and sha256(path) == OCI_TAR_SHA,
            "oci_tar_binding_mismatch")
    verifier = Path(__file__).parents[1] / "package_issue21_preflight" / "verify_oci.py"
    spec = importlib.util.spec_from_file_location("package_oci_content", verifier)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tarfile.open(path, "r:") as archive:
        entries = module.inventory(archive)
        layout, _ = module.read_json(archive, entries, "oci-layout")
        require(layout == {"imageLayoutVersion": "1.0.0"}, "oci_layout_mismatch")
        index, index_bytes = module.read_json(archive, entries, "index.json")
        require(len(index.get("manifests", [])) == 1, "oci_manifest_inventory")
        descriptor = module.descriptor(index["manifests"][0], {module.MANIFEST_TYPE},
                                       platform_allowed=True, public_reference_allowed=True)
        manifest, _ = module.descriptor_json(archive, entries, descriptor)
        config_descriptor = module.descriptor(manifest["config"], {module.CONFIG_TYPE})
        config, _ = module.descriptor_json(archive, entries, config_descriptor)
        require(descriptor["digest"] == bridge["manifest_digest"]
                and config_descriptor["digest"] == bridge["config_digest"], "oci_object_binding")
        import hashlib
        require(hashlib.sha256(index_bytes).hexdigest() == bridge["index_sha256"], "oci_index_binding")
        layers = manifest["layers"]
        diff_ids = config["rootfs"]["diff_ids"]
        require(diff_ids == bridge["verified_rootfs_diff_ids"]
                and len(layers) == len(diff_ids), "oci_layer_inventory")
        expected_files = {"index.json", "oci-layout", module.blob_path(descriptor),
                          module.blob_path(config_descriptor)}
        checked = []
        for layer, diff_id in zip(layers, diff_ids, strict=True):
            module.descriptor(layer, {module.PLAIN_LAYER, module.GZIP_LAYER})
            expected_files.add(module.blob_path(layer))
            checked.append(module.verify_layer(archive, entries, layer, diff_id))
        require({n for n, e in entries.items() if e.isreg()} == expected_files,
                "oci_unreferenced_content")
        require(checked == bridge["verified_layers"], "oci_layer_receipt_mismatch")
    return config


def typed_equal(left, right) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(typed_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(typed_equal(a, b) for a, b in zip(left, right))
    return left == right


def check_runtime_config(observed: dict, raw: dict, bridge: dict) -> dict:
    for field in ("Cmd", "Entrypoint", "WorkingDir", "User", "Env", "Labels", "ExposedPorts"):
        require(typed_equal(observed.get(field), raw.get(field)), "restored_runtime_config_mismatch")
    expected_health = raw.get("Healthcheck")
    require(typed_equal(observed.get("Healthcheck"), expected_health), "restored_healthcheck_mismatch")
    require(bridge["healthcheck"]["oci_present"] is (expected_health is not None),
            "healthcheck_receipt_mismatch")
    if "ArgsEscaped" in raw:
        require(type(raw["ArgsEscaped"]) is bool and type(observed.get("ArgsEscaped")) is bool
                and observed["ArgsEscaped"] is raw["ArgsEscaped"], "restored_args_escaped_mismatch")
    else:
        require(observed.get("ArgsEscaped") is None or observed.get("ArgsEscaped") is False,
                "restored_args_escaped_mismatch")
    require(raw.get("Volumes") in (None, {}) and observed.get("Volumes") in (None, {})
            and (observed.get("Volumes") is None or type(observed["Volumes"]) is dict),
            "restored_volumes_mismatch")
    require(raw.get("StopSignal") in (None, "") and observed.get("StopSignal") in (None, "")
            and (observed.get("StopSignal") is None or type(observed["StopSignal"]) is str),
            "restored_stop_signal_mismatch")
    return {"raw_healthcheck_present": expected_health is not None,
            "restored_healthcheck_present": observed.get("Healthcheck") is not None,
            "original_daemon_healthcheck_present": bridge["healthcheck"]["daemon_present"],
            "inherited_docker_healthcheck_survival_claim": False,
            "args_escaped_strict_match": True, "no_declared_volumes_or_stop_signal": True,
            "exposed_ports_strict_match": True}


def verify_installed_source(image_id: str, receipts: Path, copied: Path) -> int:
    inventory = json.loads((receipts / "runtime/installed-source-inventory.json").read_bytes())
    flujo = strict_json((receipts / "runtime/flujo-compiled-provenance.json").read_bytes())
    files = {"/opt/banking-mcp/" + safe_path(r["path"]): r["sha256"] for r in inventory}
    files.update({"/app/" + safe_path(path): digest for path, digest in flujo["fileHashes"].items()})
    launcher = flujo["observedBaseLauncher"]
    require(launcher["installedPath"] == "/usr/local/bin/docker-entrypoint.sh",
            "observed_base_launcher_path")
    files[launcher["installedPath"]] = launcher["sha256"]
    require(len(inventory) == 23, "banking_runtime_inventory_mismatch")
    return verify_filemap(image_id, files, copied)


def verify_filemap(image_id: str, files: dict, copied: Path) -> int:
    require_remote_execution()
    import re
    require(re.fullmatch(r"sha256:[a-f0-9]{64}", image_id), "immutable_image_id_required")
    cid = subprocess.check_output(["docker", "create", "--network", "none", image_id],
                                  text=True, timeout=60).strip()
    copied.mkdir()
    try:
        for ordinal, (installed, digest) in enumerate(files.items()):
            target = copied / str(ordinal)
            subprocess.run(["docker", "cp", cid + ":" + installed, str(target)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
            require(target.is_file() and not target.is_symlink() and sha256(target) == digest,
                    "restored_installed_source_mismatch")
    finally:
        subprocess.run(["docker", "rm", cid], check=True, stdout=subprocess.DEVNULL, timeout=60)
    return len(files)


def materialize_layout(archive: Path, destination: Path) -> None:
    """Only after the fixed tar/layer hashes passed; no extractall or links."""
    require(not destination.exists(), "oci_layout_destination_exists")
    destination.mkdir()
    with tarfile.open(archive, "r:") as source:
        for entry in source:
            name = entry.name.removeprefix("./").rstrip("/")
            if entry.isdir():
                if name and name != ".":
                    (destination / safe_path(name)).mkdir(parents=True, exist_ok=True)
                continue
            require(entry.isreg() and not entry.issparse(), "oci_layout_regular_files_required")
            target = destination / safe_path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(entry) as data, target.open("xb") as output:
                for block in iter(lambda: data.read(1024 * 1024), b""):
                    output.write(block)
    require(sha256(archive) == OCI_TAR_SHA, "oci_archive_changed")


def restore_and_verify(archive: Path, root: Path, bridge: dict, raw: dict) -> dict:
    require_remote_execution()
    tag = "banking-synthetic-restored:" + str(os.environ["GITHUB_RUN_ID"])
    subprocess.run(["skopeo", "copy", "oci-archive:" + str(archive),
                    "docker-daemon:" + tag], check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=1800)
    inspection = json.loads(subprocess.check_output(["docker", "image", "inspect", tag], timeout=60))[0]
    require(inspection["Id"] == bridge["config_digest"]
            and inspection["RootFS"]["Layers"] == bridge["verified_rootfs_diff_ids"]
            and inspection["Os"] == "linux" and inspection["Architecture"] == "amd64",
            "restored_image_identity_mismatch")
    semantics = check_runtime_config(inspection["Config"], raw["config"], bridge)
    # Copy without starting the application or MCP. No GitHub credentials enter Docker.
    count = verify_installed_source(inspection["Id"], root / "receipts", root / "restored-source")
    return {"image_id": inspection["Id"], "source_files_verified": count,
            "bank_source": BANK, "flujo_source": FLUJO,
            "original_daemon_image_id": bridge["daemon_final_image_id"],
            "original_base_inspect_replayed": False,
            "runtime_semantics": semantics,
            "manifest_digest": bridge["manifest_digest"],
            "rootfs_diff_ids": bridge["verified_rootfs_diff_ids"]}


def consume(root: Path) -> dict:
    validate_remote(dict(os.environ))
    repository = api(f"/repos/{REPOSITORY}")
    run = api(f"/repos/{REPOSITORY}/actions/runs/{PACKAGE_RUN}")
    assert_package_run(run, repository)
    root.mkdir(parents=True, exist_ok=False)
    for artifact_id, digest, kind, limit in (
        (RECEIPTS_ID, RECEIPTS_SHA, "receipts", 16 * 1024 * 1024),
        (OCI_ID, OCI_ZIP_SHA, "oci", OCI_TAR_BYTES + 1024 * 1024)):
        metadata = api(f"/repos/{REPOSITORY}/actions/artifacts/{artifact_id}")
        assert_artifact(metadata, artifact_id, PACKAGE_RUN, PACKAGE_HEAD, digest,
                        name=f"banking-package-issue21-v2-{kind}-{PACKAGE_HEAD}-1")
        zip_path = root / (kind + ".zip")
        download(artifact_id, zip_path, digest, limit)
        extract_zip(zip_path, root / kind, max_bytes=limit,
                    only={"candidate.oci.tar"} if kind == "oci" else None)
    bridge = verify_receipts(root / "receipts")
    archive = root / "oci/candidate.oci.tar"
    raw = verify_archive(archive, bridge)
    restored = restore_and_verify(archive, root, bridge, raw)
    materialize_layout(archive, root / "verified-layout")
    return restored
