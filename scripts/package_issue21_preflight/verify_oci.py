"""Read-only OCI export bridge. Runtime CLI is restricted to remote Linux CI.

No archive extraction, image loading, application import or process execution.
Pure helpers accept fictional local archives for source-only tests.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import tarfile
import zlib


CHECKPOINT = "banking-package-issue21/v2"
INDEX_TYPE = "application/vnd.oci.image.index.v1+json"
MANIFEST_TYPE = "application/vnd.oci.image.manifest.v1+json"
CONFIG_TYPE = "application/vnd.oci.image.config.v1+json"
PLAIN_LAYER = "application/vnd.oci.image.layer.v1.tar"
GZIP_LAYER = PLAIN_LAYER + "+gzip"
CHUNK = 1024 * 1024
MAX_JSON = 8 * CHUNK
MAX_MEMBERS = 2048
MAX_LAYER_BYTES = 16 * 1024 * CHUNK
MAX_TOTAL_LAYER_BYTES = 64 * 1024 * CHUNK
SAFE_CONFIG = ("Cmd", "Entrypoint", "WorkingDir", "User")
METADATA_FILES = {"index": "oci-index.json", "manifest": "oci-manifest.json", "config": "oci-config.json"}
PUBLIC_LAUNCHER = {"Cmd": ["node", "scripts/launch-next.mjs", "start", "-p", "4200", "-H", "0.0.0.0"],
                   "Entrypoint": ["docker-entrypoint.sh"], "WorkingDir": "/app", "User": "node"}
HISTORY_SAFETY_BASIS = (
    "exact audited Git contexts and fixed public build arguments; no credential, policy, "
    "dataset or secrets input; inherited public base/dependency bytes observed, not independently certified"
)


class OciError(ValueError):
    """Fixed error codes; never expose arbitrary archive/config contents."""


def insist(condition: bool, code: str) -> None:
    if not condition:
        raise OciError(code)


def digest(value: object) -> str:
    insist(isinstance(value, str) and re.fullmatch(r"sha256:[a-f0-9]{64}", value) is not None,
           "unsupported_or_invalid_digest")
    return value


def revision(value: object) -> str:
    insist(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{40}", value) is not None,
           "invalid_source_revision")
    return value


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        insist(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def reject_constant(value: str):
    raise OciError("invalid_json_constant")


def json_object(content: bytes) -> dict:
    try:
        value = json.loads(content, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise OciError("invalid_json") from None
    insist(isinstance(value, dict), "invalid_json_object")
    return value


def safe_name(member: tarfile.TarInfo) -> str:
    name = member.name
    # Harmless leading './' is canonicalized; duplicate canonical paths fail.
    if name.startswith("./"):
        name = name[2:]
    if member.isdir() and name.endswith("/"):
        name = name[:-1]
    if member.isdir() and name in {"", "."}:
        return "."
    insist(bool(name) and not name.startswith("/") and "\\" not in name
           and all(part not in {"", ".", ".."} for part in name.split("/")),
           "unsafe_archive_path")
    if member.isdir():
        insist(name in {"blobs", "blobs/sha256"}, "unexpected_archive_directory")
    else:
        insist(member.isreg() and not member.issparse(), "unsupported_archive_entry")
        insist(name in {"index.json", "oci-layout"}
               or re.fullmatch(r"blobs/sha256/[a-f0-9]{64}", name) is not None,
               "unexpected_archive_file")
    return name


def inventory(archive: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    result = {}
    for member in archive:
        insist(len(result) < MAX_MEMBERS, "archive_inventory_limit")
        name = safe_name(member)
        insist(name not in result, "duplicate_archive_entry")
        result[name] = member
    # tarfile stops at its first end marker. Reject hidden concatenated content.
    archive.fileobj.seek(archive.offset)
    for block in iter(lambda: archive.fileobj.read(CHUNK), b""):
        insist(not block.strip(b"\0"), "nonzero_archive_trailer")
    return result


def read_json(archive: tarfile.TarFile, entries: dict, name: str) -> tuple[dict, bytes]:
    member = entries.get(name)
    insist(member is not None and member.isreg() and member.size <= MAX_JSON,
           "json_blob_missing_or_too_large")
    with archive.extractfile(member) as source:
        content = source.read(MAX_JSON + 1)
    insist(len(content) == member.size, "archive_member_size_mismatch")
    return json_object(content), content


def descriptor(value: object, media_types: set[str], *, platform_allowed: bool = False) -> dict:
    insist(isinstance(value, dict), "invalid_descriptor")
    allowed = {"mediaType", "digest", "size", "annotations"}
    if platform_allowed:
        allowed.add("platform")
    insist(not set(value) - allowed, "unsupported_descriptor_fields")
    insist(value.get("mediaType") in media_types, "unsupported_media_type")
    digest(value.get("digest"))
    insist(type(value.get("size")) is int and value["size"] >= 0, "invalid_descriptor_size")
    if "platform" in value:
        insist(value["platform"] == {"architecture": "amd64", "os": "linux"},
               "unsupported_platform")
    if "annotations" in value:
        insist(isinstance(value["annotations"], dict)
               and all(isinstance(key, str) and isinstance(item, str)
                       for key, item in value["annotations"].items()), "invalid_annotations")
    return value


def blob_path(value: dict) -> str:
    return "blobs/sha256/" + value["digest"].split(":", 1)[1]


def descriptor_json(archive: tarfile.TarFile, entries: dict, value: dict) -> tuple[dict, bytes]:
    data, content = read_json(archive, entries, blob_path(value))
    insist(len(content) == value["size"], "descriptor_size_mismatch")
    insist("sha256:" + hashlib.sha256(content).hexdigest() == value["digest"], "blob_digest_mismatch")
    return data, content


class HashingReader:
    def __init__(self, source):
        self.source = source
        self.hash = hashlib.sha256()
        self.bytes = 0

    def read(self, size: int = -1) -> bytes:
        value = self.source.read(size)
        self.hash.update(value)
        self.bytes += len(value)
        return value


def verify_layer(archive: tarfile.TarFile, entries: dict, value: dict, expected_diff_id: str) -> dict:
    member = entries.get(blob_path(value))
    insist(member is not None and member.isreg() and member.size == value["size"],
           "layer_missing_or_size_mismatch")
    uncompressed = hashlib.sha256()
    total = 0
    with archive.extractfile(member) as raw:
        source = HashingReader(raw)
        reader = gzip.GzipFile(fileobj=source, mode="rb") if value["mediaType"] == GZIP_LAYER else source
        try:
            for block in iter(lambda: reader.read(CHUNK), b""):
                total += len(block)
                insist(total <= MAX_LAYER_BYTES, "layer_uncompressed_limit")
                uncompressed.update(block)
        except (OSError, EOFError, zlib.error):
            raise OciError("invalid_gzip_layer") from None
        finally:
            if isinstance(reader, gzip.GzipFile):
                reader.close()
        insist(source.read(CHUNK) == b"", "unread_layer_content")
        insist(source.bytes == member.size, "layer_read_size_mismatch")
        insist("sha256:" + source.hash.hexdigest() == value["digest"], "blob_digest_mismatch")
    observed_diff = "sha256:" + uncompressed.hexdigest()
    insist(observed_diff == expected_diff_id, "layer_diff_id_mismatch")
    return {"blob_digest": value["digest"], "compressed_bytes": value["size"],
            "media_type": value["mediaType"], "uncompressed_bytes": total,
            "verified_diff_id": observed_diff}


def safe_config(value: object) -> dict:
    insist(isinstance(value, dict), "missing_image_config")
    result = {key: value.get(key) for key in SAFE_CONFIG}
    for key in ("Cmd", "Entrypoint"):
        insist(result[key] is None or (isinstance(result[key], list)
               and all(isinstance(item, str) for item in result[key])), "invalid_safe_launcher_config")
    for key in ("WorkingDir", "User"):
        insist(isinstance(result[key], str), "invalid_safe_launcher_config")
    return result


def public_labels(flujo: str, banking: str) -> dict:
    return {"io.flujo.application.version": "3.46.1", "io.flujo.snapshot.format": "2",
            "io.flujo.workspace.layout": "2", "io.flujo.worker.protocol": "1",
            "org.opencontainers.image.version": "3.46.1",
            "org.opencontainers.image.revision": flujo,
            "org.opencontainers.image.source": "https://github.com/mario-andreschak/FLUJO",
            "io.flujo.banking.source.revision": banking,
            "io.flujo.banking.package.scope": "private-remote-preflight-no-model-no-action",
            "io.flujo.banking.package.checkpoint": CHECKPOINT}


def public_env(value: object, flujo: str) -> dict:
    insist(isinstance(value, list) and len(value) <= 32, "unsafe_raw_config_env")
    result = {}
    for entry in value:
        insist(isinstance(entry, str) and len(entry) <= 1024 and "=" in entry,
               "unsafe_raw_config_env")
        name, content = entry.split("=", 1)
        insist(name not in result, "unsafe_raw_config_env")
        result[name] = content
    fixed = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
             "NODE_ENV": "production", "FLUJO_BUILD_REVISION": flujo,
             "FLUJO_CONTAINER": "1", "FLUJO_APP_ROOT": "/app", "FLUJO_DATA_DIR": "/app/data",
             "PLAYWRIGHT_BROWSERS_PATH": "/home/node/.cache/ms-playwright",
             "PIP_BREAK_SYSTEM_PACKAGES": "1", "HOME": "/home/node",
             "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
    insist(set(result) == set(fixed) | {"NODE_VERSION", "YARN_VERSION"}
           and all(result.get(name) == expected for name, expected in fixed.items())
           and re.fullmatch(r"22\.\d+\.\d+", result.get("NODE_VERSION", "")) is not None
           and re.fullmatch(r"1\.22\.\d+", result.get("YARN_VERSION", "")) is not None,
           "unsafe_raw_config_env")
    return result


def validate_raw_config(config: dict, daemon_config: dict, flujo: str, banking: str) -> dict:
    """Validate exact runtime fields; public build provenance is the history basis.

    History commands are retained unredacted. They are bounded and typed, not
    certified by guessed upstream command patterns or a secret-word blacklist.
    """
    insist(not set(config) - {"created", "author", "architecture", "os", "variant", "os.version",
                              "os.features", "config", "rootfs", "history"}, "unsupported_raw_config_fields")
    runtime = config["config"]
    insist(not set(runtime) - {"User", "ExposedPorts", "Env", "Entrypoint", "Cmd", "Volumes",
                               "WorkingDir", "Labels", "StopSignal", "ArgsEscaped", "Healthcheck"},
           "unsupported_raw_runtime_config_fields")
    insist(safe_config(runtime) == PUBLIC_LAUNCHER, "unsafe_raw_config_launcher")
    env = public_env(runtime.get("Env"), flujo)
    insist(env == public_env(daemon_config.get("Env"), flujo), "raw_config_env_differs_from_daemon")
    expected_labels = public_labels(flujo, banking)
    insist(runtime.get("Labels") == expected_labels and daemon_config.get("Labels") == expected_labels,
           "unsafe_raw_config_labels")
    insist(runtime.get("Volumes") in (None, {}) and runtime.get("ArgsEscaped", False) is False
           and runtime.get("StopSignal") in (None, "SIGTERM", "15"), "unsupported_raw_runtime_config_values")
    ports = runtime.get("ExposedPorts")
    insist(ports is None or ports == {"4200/tcp": {}, "4201/tcp": {}}, "unsafe_raw_config_ports")
    healthcheck = runtime.get("Healthcheck")
    if healthcheck is not None:
        insist(isinstance(healthcheck, dict)
               and not set(healthcheck) - {"Test", "Interval", "Timeout", "StartPeriod", "StartInterval", "Retries"}
               and healthcheck.get("Test") == ["CMD", "node", "scripts/healthcheck.mjs"]
               and all(type(item) is int and 0 <= item <= 10**12
                       for key, item in healthcheck.items() if key != "Test"), "unsafe_raw_config_healthcheck")
    for key in ("created", "author"):
        insist(key not in config or (isinstance(config[key], str) and len(config[key].encode()) <= 1024),
               "invalid_raw_config_metadata")
    history = config.get("history", [])
    insist(isinstance(history, list) and len(history) <= 1024
           and len(json.dumps(history, ensure_ascii=False).encode()) <= 2 * CHUNK,
           "raw_config_history_limit")
    for entry in history:
        insist(isinstance(entry, dict)
               and not set(entry) - {"created", "created_by", "author", "comment", "empty_layer"},
               "invalid_raw_config_history")
        for key, content in entry.items():
            if key == "empty_layer":
                insist(type(content) is bool, "invalid_raw_config_history")
            else:
                insist(isinstance(content, str) and len(content.encode()) <= 64 * 1024,
                       "invalid_raw_config_history")
    return {"env_names": sorted(env), "exact_public_labels_verified": True,
            "exact_public_launcher_verified": True, "history_entries": len(history),
            "history_safety_basis": HISTORY_SAFETY_BASIS,
            "redaction": False, "history_command_certification": False}


def export_metadata(directory: Path, receipt_directory: Path, metadata: dict[str, bytes], receipt: dict) -> None:
    """Write only the bounded, already verified raw JSON graph to a fresh folder."""
    parent = receipt_directory.resolve(strict=True)
    target = directory.resolve()
    insist(target.parent == parent and target != parent and not directory.exists() and not directory.is_symlink(),
           "metadata_directory_must_be_fresh_receipt_child")
    insist(set(metadata) == set(METADATA_FILES.values())
           and all(isinstance(content, bytes) and len(content) <= MAX_JSON for content in metadata.values()),
           "invalid_verified_metadata_inventory")
    records = receipt["raw_metadata"]["files"]
    insist(len(records) == 3 and {item["filename"] for item in records} == set(metadata),
           "invalid_verified_metadata_inventory")
    for item in records:
        content = metadata[item["filename"]]
        insist(item["bytes"] == len(content) and item["sha256"] == hashlib.sha256(content).hexdigest(),
               "verified_metadata_changed_before_export")
    target.mkdir(mode=0o700)
    for item in records:
        path = target / item["filename"]
        with path.open("xb") as output:
            output.write(metadata[item["filename"]])
        retained = path.read_bytes()
        insist(len(retained) == item["bytes"] and hashlib.sha256(retained).hexdigest() == item["sha256"],
               "metadata_copy_mismatch")
        item["receipt_path"] = path.relative_to(parent).as_posix()


def verify(archive_path: Path, final: dict, *, candidate: str, flujo: str, banking: str,
           metadata: dict[str, bytes] | None = None) -> dict:
    revision(candidate)
    revision(flujo)
    revision(banking)
    insist(isinstance(final, dict) and final.get("Architecture") == "amd64"
           and final.get("Os") == "linux", "unsupported_daemon_platform")
    daemon_id = digest(final.get("Id"))
    daemon_config = final.get("Config")
    daemon_safe = safe_config(daemon_config)
    labels = daemon_config.get("Labels", {})
    expected_labels = {"org.opencontainers.image.revision": flujo,
                       "io.flujo.banking.source.revision": banking}
    insist(isinstance(labels, dict) and all(labels.get(key) == value for key, value in expected_labels.items()),
           "daemon_source_labels_mismatch")
    daemon_rootfs = final.get("RootFS")
    insist(isinstance(daemon_rootfs, dict) and daemon_rootfs.get("Type") == "layers"
           and isinstance(daemon_rootfs.get("Layers"), list) and daemon_rootfs["Layers"],
           "invalid_daemon_rootfs")
    daemon_layers = [digest(item) for item in daemon_rootfs["Layers"]]
    insist(not archive_path.is_symlink() and archive_path.is_file(), "archive_not_regular_file")
    with archive_path.open("rb") as archive_source:
        before = os.fstat(archive_source.fileno())
        archive_hash = hashlib.sha256()
        for block in iter(lambda: archive_source.read(CHUNK), b""):
            archive_hash.update(block)
        archive_source.seek(0)
        try:
            archive = tarfile.open(fileobj=archive_source, mode="r:")
        except tarfile.TarError:
            raise OciError("unsupported_archive_format") from None
        with archive:
            entries = inventory(archive)
            layout, _ = read_json(archive, entries, "oci-layout")
            insist(layout == {"imageLayoutVersion": "1.0.0"}, "unsupported_oci_layout")
            index, index_bytes = read_json(archive, entries, "index.json")
            insist(type(index.get("schemaVersion")) is int and index["schemaVersion"] == 2
                   and index.get("mediaType", INDEX_TYPE) == INDEX_TYPE
                   and not set(index) - {"schemaVersion", "mediaType", "manifests", "annotations"},
                   "unsupported_index")
            manifests = index.get("manifests")
            insist(isinstance(manifests, list) and len(manifests) == 1, "ambiguous_manifest_inventory")
            selected = descriptor(manifests[0], {MANIFEST_TYPE}, platform_allowed=True)
            manifest, manifest_bytes = descriptor_json(archive, entries, selected)
            insist(type(manifest.get("schemaVersion")) is int and manifest["schemaVersion"] == 2
                   and manifest.get("mediaType") == MANIFEST_TYPE
                   and not set(manifest) - {"schemaVersion", "mediaType", "config", "layers", "annotations"},
                   "unsupported_manifest")
            config_descriptor = descriptor(manifest.get("config"), {CONFIG_TYPE})
            config, config_bytes = descriptor_json(archive, entries, config_descriptor)
            insist(config.get("architecture") == "amd64" and config.get("os") == "linux"
                   and config.get("variant", "") == ""
                   and config.get("os.version", "") == ""
                   and config.get("os.features", []) == [], "unsupported_platform")
            rootfs = config.get("rootfs")
            insist(isinstance(rootfs, dict) and set(rootfs) == {"type", "diff_ids"}
                   and rootfs["type"] == "layers" and isinstance(rootfs["diff_ids"], list),
                   "invalid_oci_rootfs")
            diff_ids = [digest(item) for item in rootfs["diff_ids"]]
            insist(diff_ids == daemon_layers, "exported_rootfs_differs_from_inspected_image")
            image_config = config.get("config")
            exported_safe = safe_config(image_config)
            insist(exported_safe == daemon_safe, "exported_launcher_differs_from_inspected_image")
            exported_labels = image_config.get("Labels", {})
            insist(isinstance(exported_labels, dict)
                   and all(exported_labels.get(key) == value for key, value in expected_labels.items()),
                   "exported_source_labels_mismatch")
            layers = manifest.get("layers")
            insist(isinstance(layers, list) and len(layers) == len(diff_ids)
                   and len(layers) <= MAX_MEMBERS - 4, "layer_count_mismatch")
            layer_descriptors = [descriptor(item, {PLAIN_LAYER, GZIP_LAYER}) for item in layers]
            expected_files = {"index.json", "oci-layout", blob_path(selected), blob_path(config_descriptor)}
            expected_files.update(blob_path(item) for item in layer_descriptors)
            actual_files = {name for name, entry in entries.items() if entry.isreg()}
            insist(actual_files == expected_files, "unreferenced_or_missing_archive_content")
            verified_layers = []
            total_bytes = 0
            for item, diff_id in zip(layer_descriptors, diff_ids, strict=True):
                checked = verify_layer(archive, entries, item, diff_id)
                total_bytes += checked["uncompressed_bytes"]
                insist(total_bytes <= MAX_TOTAL_LAYER_BYTES, "total_uncompressed_limit")
                verified_layers.append(checked)
        after = os.fstat(archive_source.fileno())
        insist((before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino)
               == (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino), "archive_changed_during_read")
    receipt = {"schema_version": 2, "checkpoint": CHECKPOINT,
            "proof_kind": "verified_oci_export_bridge", "status": "passed",
            "candidate_revision": candidate, "flujo_source_revision": flujo,
            "banking_source_revision": banking, "daemon_final_image_id": daemon_id,
            "archive": {"bytes": before.st_size, "sha256": archive_hash.hexdigest()},
            "index_sha256": hashlib.sha256(index_bytes).hexdigest(),
            "manifest_digest": selected["digest"], "config_digest": config_descriptor["digest"],
            "platform": {"os": "linux", "architecture": "amd64"},
            "verified_rootfs_diff_ids": diff_ids, "verified_layers": verified_layers,
            "safe_launcher_config": exported_safe,
            "healthcheck": {"daemon_present": daemon_config.get("Healthcheck") is not None,
                            "oci_present": image_config.get("Healthcheck") is not None,
                            "retention_verified": False},
            "verified": ["archive_and_index_hashes", "manifest_and_config_blob_digests",
                         "every_manifest_layer_blob_digest", "every_uncompressed_layer_diff_id",
                         "ordered_rootfs_matches_daemon_inspect", "safe_launcher_matches_daemon_inspect",
                         "exact_source_labels", "single_linux_amd64_image", "no_unreferenced_archive_files"],
            "unproven": ["healthcheck_retention_in_oci", "image_load_or_roundtrip",
                         "deployment", "model_or_provider_readiness", "joined_runtime_acceptance",
                         "independent_base_or_dependency_certification", "bit_for_bit_reproducibility"]}
    if metadata is not None:
        safety = validate_raw_config(config, daemon_config, flujo, banking)
        payloads = {METADATA_FILES["index"]: index_bytes, METADATA_FILES["manifest"]: manifest_bytes,
                    METADATA_FILES["config"]: config_bytes}
        receipt["raw_metadata"] = {"safety": safety, "files": [
            {"kind": kind, "filename": name, "bytes": len(payloads[name]),
             "sha256": hashlib.sha256(payloads[name]).hexdigest(),
             "digest": "sha256:" + hashlib.sha256(payloads[name]).hexdigest(),
             "descriptor_digest": selected["digest"] if kind == "manifest"
                 else config_descriptor["digest"] if kind == "config" else None}
            for kind, name in METADATA_FILES.items()]}
        metadata.update(payloads)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--final-inspect", required=True, type=Path)
    parser.add_argument("--candidate-revision", required=True)
    parser.add_argument("--expected-flujo-revision", required=True)
    parser.add_argument("--expected-bank-revision", required=True)
    parser.add_argument("--metadata-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if os.environ.get("GITHUB_ACTIONS") != "true" or platform.system() != "Linux":
        print("OCI bridge refused: remote_github_actions_linux_required")
        return 1
    try:
        inspect_content = args.final_inspect.read_bytes()
        inspected = json.loads(inspect_content, object_pairs_hook=unique_object, parse_constant=reject_constant)
        insist(isinstance(inspected, list) and len(inspected) == 1, "ambiguous_daemon_inspect")
        metadata = {}
        receipt = verify(args.archive, inspected[0], candidate=args.candidate_revision,
                         flujo=args.expected_flujo_revision, banking=args.expected_bank_revision,
                         metadata=metadata)
        receipt["daemon_inspect_sha256"] = hashlib.sha256(inspect_content).hexdigest()
        export_metadata(args.metadata_dir, args.out.parent, metadata, receipt)
    except Exception as error:
        receipt = {"schema_version": 2, "checkpoint": CHECKPOINT,
                   "proof_kind": "verified_oci_export_bridge", "status": "failed",
                   "failure": str(error) if isinstance(error, OciError) else "verification_failed",
                   "exception_type": type(error).__name__}
    args.out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print("OCI export bridge " + receipt["status"] + ". No image load or runtime acceptance.")
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
