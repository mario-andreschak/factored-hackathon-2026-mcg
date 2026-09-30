"""Fictional OCI bytes only; no Docker, extraction, subprocess or bank imports."""
from __future__ import annotations

import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts.package_issue21_preflight import verify_oci as verifier


def encoded(value):
    return json.dumps(value, sort_keys=True).encode()


def sha(value):
    return "sha256:" + hashlib.sha256(value).hexdigest()


def layer_tar(name, value):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        info = tarfile.TarInfo(name)
        info.size = len(value)
        archive.addfile(info, io.BytesIO(value))
    return stream.getvalue()


class OciFixtures(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "fictional.oci.tar"
        self.candidate, self.flujo, self.banking = "a" * 40, "b" * 40, "c" * 40
        plain = layer_tar("fictional-first", b"fictional contents")
        second = layer_tar("fictional-second", b"more fictional contents")
        self.layer_contents = [plain, gzip.compress(second, mtime=0)]
        self.diff_ids = [sha(plain), sha(second)]
        self.config = {"architecture": "amd64", "os": "linux",
                       "rootfs": {"type": "layers", "diff_ids": self.diff_ids},
                       "config": {"User": "node", "WorkingDir": "/app",
                                  "Cmd": ["node", "scripts/launch-next.mjs"],
                                  "Entrypoint": ["docker-entrypoint.sh"],
                                  "Env": ["NEVER_PRINT_THIS=private-fictional-sentinel"],
                                  "Labels": {"org.opencontainers.image.revision": self.flujo,
                                             "io.flujo.banking.source.revision": self.banking}}}
        self.final = {"Architecture": "amd64", "Os": "linux", "Id": "sha256:" + "d" * 64,
                      "RootFS": {"Type": "layers", "Layers": self.diff_ids},
                      "Config": {**copy.deepcopy(self.config["config"]),
                                 "Healthcheck": {"Test": ["CMD", "node", "scripts/healthcheck.mjs"]}}}

    def descriptor(self, media_type, content):
        return {"mediaType": media_type, "digest": sha(content), "size": len(content)}

    def files(self, *, config=None, layer_types=None, index_transform=None, manifest_transform=None):
        config_bytes = encoded(self.config if config is None else config)
        layer_types = layer_types or [verifier.PLAIN_LAYER, verifier.GZIP_LAYER]
        layer_descriptors = [self.descriptor(kind, value)
                             for kind, value in zip(layer_types, self.layer_contents, strict=True)]
        manifest = {"schemaVersion": 2, "mediaType": verifier.MANIFEST_TYPE,
                    "config": self.descriptor(verifier.CONFIG_TYPE, config_bytes),
                    "layers": layer_descriptors}
        if manifest_transform:
            manifest_transform(manifest)
        manifest_bytes = encoded(manifest)
        index = {"schemaVersion": 2, "mediaType": verifier.INDEX_TYPE,
                 "manifests": [self.descriptor(verifier.MANIFEST_TYPE, manifest_bytes)]}
        if index_transform:
            index_transform(index)
        files = {"oci-layout": encoded({"imageLayoutVersion": "1.0.0"}),
                 "index.json": encoded(index),
                 "blobs/sha256/" + sha(manifest_bytes)[7:]: manifest_bytes,
                 "blobs/sha256/" + sha(config_bytes)[7:]: config_bytes}
        for content in self.layer_contents:
            files["blobs/sha256/" + sha(content)[7:]] = content
        return files

    def write(self, files, *, duplicate=None, extra=None, trailer=b""):
        with tarfile.open(self.path, mode="w") as archive:
            for name, content in files.items():
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
            if duplicate:
                member = tarfile.TarInfo(duplicate)
                member.size = len(files["index.json"])
                archive.addfile(member, io.BytesIO(files["index.json"]))
            if extra:
                archive.addfile(extra)
        if trailer:
            with self.path.open("ab") as output:
                output.write(trailer)

    def check(self, **kwargs):
        return verifier.verify(self.path, self.final, candidate=self.candidate,
                               flujo=self.flujo, banking=self.banking, **kwargs)

    def public_config(self):
        fixed = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                 "NODE_VERSION": "22.19.0", "YARN_VERSION": "1.22.22", "NODE_ENV": "production",
                 "FLUJO_BUILD_REVISION": self.flujo, "FLUJO_CONTAINER": "1", "FLUJO_APP_ROOT": "/app",
                 "FLUJO_DATA_DIR": "/app/data", "PLAYWRIGHT_BROWSERS_PATH": "/home/node/.cache/ms-playwright",
                 "PIP_BREAK_SYSTEM_PACKAGES": "1", "HOME": "/home/node", "PYTHONDONTWRITEBYTECODE": "1",
                 "PYTHONUNBUFFERED": "1"}
        self.config["config"] = {**copy.deepcopy(verifier.PUBLIC_LAUNCHER),
                                 "Env": [name + "=" + value for name, value in fixed.items()],
                                 "Labels": verifier.public_labels(self.flujo, self.banking),
                                 "ExposedPorts": {"4200/tcp": {}, "4201/tcp": {}}}
        self.config["history"] = [{"created_by": "public inherited Node/Debian build command", "empty_layer": False},
                                  {"created_by": "public FLUJO build command", "empty_layer": False}]
        self.final["Config"] = copy.deepcopy(self.config["config"])

    def fails(self, code):
        with self.assertRaisesRegex(verifier.OciError, "^" + code + "$"):
            self.check()

    def inherited_true_fixture(self):
        self.public_config()
        self.config["config"]["ArgsEscaped"] = True
        self.final["Config"] = copy.deepcopy(self.config["config"])
        base = copy.deepcopy(self.final)
        base["Id"] = "sha256:" + "e" * 64
        base["RootFS"]["Layers"] = self.diff_ids[:1]
        base["Config"]["Labels"] = {key: value for key, value in base["Config"]["Labels"].items()
                                     if not key.startswith("io.flujo.banking.")}
        base["Config"]["Env"] = [item for item in base["Config"]["Env"]
                                  if not item.startswith(("PYTHONDONTWRITEBYTECODE=", "PYTHONUNBUFFERED="))]
        return base

    def test_plain_and_gzip_layers_bridge_to_daemon_without_image_id_equivalence(self):
        self.write(self.files())
        receipt = self.check()
        self.assertEqual(receipt["schema_version"], 2)
        self.assertEqual(receipt["checkpoint"], verifier.CHECKPOINT)
        self.assertEqual(receipt["archive"]["sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(receipt["verified_rootfs_diff_ids"], self.diff_ids)
        self.assertEqual([item["verified_diff_id"] for item in receipt["verified_layers"]], self.diff_ids)
        self.assertEqual(receipt["safe_launcher_config"], {key: self.final["Config"][key]
                                                         for key in verifier.SAFE_CONFIG})
        self.assertNotEqual(receipt["config_digest"], receipt["daemon_final_image_id"])
        self.assertEqual(receipt["healthcheck"], {"daemon_present": True, "oci_present": False,
                                                 "retention_verified": False})
        rendered = json.dumps(receipt)
        self.assertNotIn("NEVER_PRINT_THIS", rendered)
        self.assertNotIn("private-fictional-sentinel", rendered)
        self.assertNotIn('"Env"', rendered)
        self.assertNotIn('"Config"', rendered)
        self.assertIn("image_load_or_roundtrip", receipt["unproven"])
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), [self.path.name])

    def test_present_oci_healthcheck_still_makes_no_retention_claim(self):
        self.config["config"]["Healthcheck"] = {"Test": ["CMD", "false"]}
        self.write(self.files())
        healthcheck = self.check()["healthcheck"]
        self.assertTrue(healthcheck["oci_present"])
        self.assertFalse(healthcheck["retention_verified"])

    def test_safe_launcher_difference_is_rejected(self):
        for key, value in {"Cmd": ["other"], "Entrypoint": None,
                           "WorkingDir": "/other", "User": "root"}.items():
            with self.subTest(key=key):
                altered = copy.deepcopy(self.config)
                altered["config"][key] = value
                self.write(self.files(config=altered))
                self.fails("exported_launcher_differs_from_inspected_image")

    def test_source_label_differences_are_rejected(self):
        self.config["config"]["Labels"]["io.flujo.banking.source.revision"] = "f" * 40
        self.write(self.files())
        self.fails("exported_source_labels_mismatch")
        self.final["Config"]["Labels"]["org.opencontainers.image.revision"] = "f" * 40
        self.fails("daemon_source_labels_mismatch")

    def test_daemon_rootfs_must_match_exported_config_in_order(self):
        self.final["RootFS"]["Layers"] = list(reversed(self.diff_ids))
        self.write(self.files())
        self.fails("exported_rootfs_differs_from_inspected_image")

    def test_forged_config_and_daemon_diff_id_is_rejected_by_actual_layer_bytes(self):
        self.config["rootfs"]["diff_ids"] = ["sha256:" + "e" * 64, self.diff_ids[1]]
        self.final["RootFS"]["Layers"] = self.config["rootfs"]["diff_ids"]
        self.write(self.files())
        self.fails("layer_diff_id_mismatch")

    def test_layer_blob_tampering_is_rejected(self):
        files = self.files()
        name = "blobs/sha256/" + sha(self.layer_contents[0])[7:]
        files[name] = b"X" + files[name][1:]
        self.write(files)
        self.fails("blob_digest_mismatch")

    def test_config_blob_tampering_is_rejected(self):
        files = self.files()
        name = "blobs/sha256/" + sha(encoded(self.config))[7:]
        files[name] = files[name].replace(b"launch-next", b"launch-fake")
        self.write(files)
        self.fails("blob_digest_mismatch")

    def test_descriptor_size_mismatch_is_rejected(self):
        self.write(self.files(manifest_transform=lambda manifest: manifest["config"].update(size=1)))
        self.fails("descriptor_size_mismatch")

    def test_unsupported_layer_compression_is_rejected(self):
        self.write(self.files(layer_types=[verifier.PLAIN_LAYER + "+zstd", verifier.GZIP_LAYER]))
        self.fails("unsupported_media_type")

    def test_invalid_gzip_is_rejected_instead_of_guessed_plain(self):
        self.write(self.files(layer_types=[verifier.GZIP_LAYER, verifier.GZIP_LAYER]))
        self.fails("invalid_gzip_layer")

    def test_duplicate_tar_paths_include_canonical_leading_dot_duplicates(self):
        for name in ("index.json", "./index.json"):
            with self.subTest(name=name):
                self.write(self.files(), duplicate=name)
                self.fails("duplicate_archive_entry")

    def test_path_escapes_links_and_unknown_files_are_rejected_without_extraction(self):
        for name, kind, code in [("../escape", tarfile.REGTYPE, "unsafe_archive_path"),
                                  ("/absolute", tarfile.REGTYPE, "unsafe_archive_path"),
                                  ("blobs\\escape", tarfile.REGTYPE, "unsafe_archive_path"),
                                  ("unexpected", tarfile.REGTYPE, "unexpected_archive_file"),
                                  ("index-link", tarfile.SYMTYPE, "unsupported_archive_entry")]:
            with self.subTest(name=name):
                extra = tarfile.TarInfo(name)
                extra.type = kind
                extra.linkname = "index.json"
                self.write(self.files(), extra=extra)
                self.fails(code)
                self.assertFalse((self.root.parent / "escape").exists())

    def test_hidden_archive_after_end_marker_is_rejected(self):
        self.write(self.files(), trailer=b"hidden second archive")
        self.fails("nonzero_archive_trailer")

    def test_unreferenced_blobs_are_rejected(self):
        files = self.files()
        files["blobs/sha256/" + sha(b"unreferenced")[7:]] = b"unreferenced"
        self.write(files)
        self.fails("unreferenced_or_missing_archive_content")

    def test_duplicate_json_keys_are_rejected(self):
        files = self.files()
        files["index.json"] = files["index.json"].replace(b'"schemaVersion": 2',
                                                        b'"schemaVersion": 2, "schemaVersion": 2')
        self.write(files)
        self.fails("duplicate_json_key")

    def test_non_json_numeric_constants_are_rejected(self):
        files = self.files()
        files["index.json"] = files["index.json"].replace(b'"schemaVersion": 2',
                                                        b'"schemaVersion": NaN')
        self.write(files)
        self.fails("invalid_json_constant")

    def test_ambiguous_manifest_list_is_rejected(self):
        def add(index):
            index["manifests"].append(copy.deepcopy(index["manifests"][0]))
        self.write(self.files(index_transform=add))
        self.fails("ambiguous_manifest_inventory")

    def test_unsupported_index_platform_is_rejected(self):
        def alter(index):
            index["manifests"][0]["platform"] = {"os": "linux", "architecture": "arm64"}
        self.write(self.files(index_transform=alter))
        self.fails("unsupported_platform")

    def test_exact_supported_index_platform_is_accepted(self):
        def alter(index):
            index["manifests"][0]["platform"] = {"os": "linux", "architecture": "amd64"}
        self.write(self.files(index_transform=alter))
        self.assertEqual(self.check()["platform"], {"os": "linux", "architecture": "amd64"})

    def test_unsupported_config_and_daemon_platforms_are_rejected(self):
        for field, value in (("architecture", "arm64"), ("os", "windows"), ("variant", "v8"),
                             ("os.version", "unsupported"), ("os.features", ["unsupported"])):
            with self.subTest(field=field):
                altered = copy.deepcopy(self.config)
                altered[field] = value
                self.write(self.files(config=altered))
                self.fails("unsupported_platform")
        self.final["Architecture"] = "arm64"
        self.write(self.files())
        self.fails("unsupported_daemon_platform")

    def test_external_descriptor_sources_and_other_digest_algorithms_are_rejected(self):
        def external(manifest):
            manifest["layers"][0]["urls"] = ["https://example.invalid/forbidden"]
        self.write(self.files(manifest_transform=external))
        self.fails("unsupported_descriptor_fields")
        def other(manifest):
            manifest["layers"][0]["digest"] = "sha512:" + "a" * 128
        self.write(self.files(manifest_transform=other))
        self.fails("unsupported_or_invalid_digest")

    def test_streaming_uncompressed_limit_is_enforced(self):
        self.write(self.files())
        with patch.object(verifier, "MAX_LAYER_BYTES", 1):
            self.fails("layer_uncompressed_limit")
        with patch.object(verifier, "MAX_TOTAL_LAYER_BYTES", 1):
            self.fails("total_uncompressed_limit")

    def test_raw_metadata_exports_are_exact_verified_bytes_with_hash_size_and_path(self):
        self.public_config()
        files = self.files()
        self.write(files)
        metadata = {}
        receipt = self.check(metadata=metadata)
        destination = self.root / "oci-metadata"
        verifier.export_metadata(destination, self.root, metadata, receipt)
        manifest = json.loads(files["index.json"])["manifests"][0]
        manifest_bytes = files[verifier.blob_path(manifest)]
        config = json.loads(manifest_bytes)["config"]
        expected = {"oci-index.json": files["index.json"], "oci-manifest.json": manifest_bytes,
                    "oci-config.json": files[verifier.blob_path(config)]}
        self.assertEqual(metadata, expected)
        self.assertEqual(sorted(path.name for path in destination.iterdir()), sorted(expected))
        for record in receipt["raw_metadata"]["files"]:
            retained = self.root / record["receipt_path"]
            self.assertEqual(retained.read_bytes(), expected[record["filename"]])
            self.assertEqual(record["bytes"], len(retained.read_bytes()))
            self.assertEqual(record["sha256"], hashlib.sha256(retained.read_bytes()).hexdigest())
            self.assertEqual(record["digest"], "sha256:" + record["sha256"])
            if record["kind"] == "index":
                self.assertEqual(record["sha256"], receipt["index_sha256"])
            else:
                self.assertEqual("sha256:" + record["sha256"], receipt[record["kind"] + "_digest"])
                self.assertEqual(record["descriptor_digest"], receipt[record["kind"] + "_digest"])
        retained_config = (destination / "oci-config.json").read_bytes()
        self.assertIn(b'"Env"', retained_config)
        self.assertIn(b"public inherited Node/Debian build command", retained_config)
        self.assertFalse(receipt["raw_metadata"]["safety"]["redaction"])
        self.assertFalse(receipt["raw_metadata"]["safety"]["history_command_certification"])
        self.assertIn("no credential", receipt["raw_metadata"]["safety"]["history_safety_basis"])
        self.assertIn("independent_base_or_dependency_certification", receipt["unproven"])

    def test_unsafe_env_fails_before_any_raw_metadata_is_retained(self):
        self.public_config()
        self.config["config"]["Env"].append("AWS_SECRET_ACCESS_KEY=fictional-secret")
        self.final["Config"] = copy.deepcopy(self.config["config"])
        self.write(self.files())
        metadata = {}
        with self.assertRaisesRegex(verifier.OciError, "^unsafe_raw_config_env$"):
            self.check(metadata=metadata)
        self.assertEqual(metadata, {})
        self.assertFalse((self.root / "oci-metadata").exists())

    def test_env_duplicate_unknown_missing_and_changed_values_fail_retention(self):
        mutations = [lambda env: env.append(env[0]), lambda env: env.append("UNKNOWN=public-looking"),
                     lambda env: env.pop(), lambda env: env.__setitem__(0, "PATH=/unsafe"),
                     lambda env: env.__setitem__(1, "NODE_VERSION=secret-looking-value")]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.public_config()
                mutate(self.config["config"]["Env"])
                self.final["Config"] = copy.deepcopy(self.config["config"])
                self.write(self.files())
                with self.assertRaisesRegex(verifier.OciError, "^unsafe_raw_config_env$"):
                    self.check(metadata={})

    def test_raw_export_env_must_also_match_inspected_daemon(self):
        self.public_config()
        self.final["Config"]["Env"] = [item.replace("NODE_VERSION=22.19.0", "NODE_VERSION=22.20.0")
                                        for item in self.final["Config"]["Env"]]
        self.write(self.files())
        with self.assertRaisesRegex(verifier.OciError, "^raw_config_env_differs_from_daemon$"):
            self.check(metadata={})

    def test_unknown_or_changed_public_labels_fail_raw_retention(self):
        for name, value in (("credential", "fictional-secret"), ("io.flujo.application.version", "bad")):
            with self.subTest(name=name):
                self.public_config()
                self.config["config"]["Labels"][name] = value
                self.final["Config"] = copy.deepcopy(self.config["config"])
                self.write(self.files())
                with self.assertRaisesRegex(verifier.OciError, "^unsafe_raw_config_labels$"):
                    self.check(metadata={})

    def test_unknown_raw_config_fields_and_unreviewed_launchers_fail(self):
        self.public_config()
        self.config["config"]["Credentials"] = "fictional-secret"
        self.write(self.files())
        with self.assertRaisesRegex(verifier.OciError, "^unsupported_raw_runtime_config_fields$"):
            self.check(metadata={})
        self.public_config()
        self.config["config"]["Cmd"] = ["public-looking-unreviewed-command"]
        self.final["Config"] = copy.deepcopy(self.config["config"])
        self.write(self.files())
        with self.assertRaisesRegex(verifier.OciError, "^unsafe_raw_config_launcher$"):
            self.check(metadata={})

    def test_raw_history_is_bounded_and_typed_without_guessed_command_patterns(self):
        for history, code in [([{"created_by": "x" * (64 * 1024 + 1)}], "invalid_raw_config_history"),
                               ([{}] * 1025, "raw_config_history_limit"),
                               ([{"created_by": "public command", "unknown": "value"}], "invalid_raw_config_history"),
                               ([{"empty_layer": 1}], "invalid_raw_config_history")]:
            with self.subTest(code=code):
                self.public_config()
                self.config["history"] = history
                self.write(self.files())
                metadata = {}
                with self.assertRaisesRegex(verifier.OciError, "^" + code + "$"):
                    self.check(metadata=metadata)
                self.assertEqual(metadata, {})

    def test_raw_metadata_cannot_be_changed_before_export_or_overwrite_existing_output(self):
        self.public_config()
        self.write(self.files())
        metadata = {}
        receipt = self.check(metadata=metadata)
        metadata["oci-config.json"] += b" "
        destination = self.root / "oci-metadata"
        with self.assertRaisesRegex(verifier.OciError, "^verified_metadata_changed_before_export$"):
            verifier.export_metadata(destination, self.root, metadata, receipt)
        self.assertFalse(destination.exists())
        metadata = {}
        receipt = self.check(metadata=metadata)
        destination.mkdir()
        with self.assertRaisesRegex(verifier.OciError, "^metadata_directory_must_be_fresh_receipt_child$"):
            verifier.export_metadata(destination, self.root, metadata, receipt)

    def test_raw_metadata_directory_cannot_escape_private_receipt_directory(self):
        self.public_config()
        self.write(self.files())
        metadata = {}
        receipt = self.check(metadata=metadata)
        with self.assertRaisesRegex(verifier.OciError, "^metadata_directory_must_be_fresh_receipt_child$"):
            verifier.export_metadata(self.root / ".." / "unexpected-export", self.root, metadata, receipt)

    def annotation_files(self, location, value, *, absent=False):
        def set_field(target):
            if absent:
                target.pop("annotations", None)
            else:
                target["annotations"] = value
        def transform_index(index):
            if location == "index":
                set_field(index)
            elif location == "selected_descriptor":
                set_field(index["manifests"][0])
        def transform_manifest(manifest):
            if location == "manifest":
                set_field(manifest)
            elif location == "config_descriptor":
                set_field(manifest["config"])
            elif location == "layer_descriptor":
                set_field(manifest["layers"][0])
        return self.files(index_transform=transform_index, manifest_transform=transform_manifest)

    def test_absent_and_empty_annotations_are_allowed_at_every_reviewed_location(self):
        self.public_config()
        for location in ("index", "manifest", "selected_descriptor", "config_descriptor", "layer_descriptor"):
            for absent in (True, False):
                with self.subTest(location=location, absent=absent):
                    self.write(self.annotation_files(location, {}, absent=absent))
                    metadata = {}
                    receipt = self.check(metadata=metadata)
                    self.assertEqual(receipt["status"], "passed")
                    self.assertEqual(len(metadata), 3)

    def test_only_selected_image_descriptor_accepts_exact_public_reference(self):
        self.public_config()
        reference = {"org.opencontainers.image.ref.name": "banking-preflight"}
        self.write(self.annotation_files("selected_descriptor", reference))
        metadata = {}
        self.assertEqual(self.check(metadata=metadata)["status"], "passed")
        self.assertEqual(json.loads(metadata["oci-index.json"])["manifests"][0]["annotations"], reference)
        for location in ("index", "manifest", "config_descriptor", "layer_descriptor"):
            with self.subTest(location=location):
                self.write(self.annotation_files(location, reference))
                output = {}
                with self.assertRaisesRegex(verifier.OciError, "^unapproved_oci_annotations$"):
                    self.check(metadata=output)
                self.assertEqual(output, {})

    def test_foreign_or_invalid_annotations_fail_before_raw_retention_at_every_location(self):
        self.public_config()
        invalid = [None, "fictional-secret", [], 1, {"credential": "fictional-secret"},
                   {"org.opencontainers.image.ref.name": "unreviewed-reference"},
                   {"org.opencontainers.image.ref.name": "banking-preflight", "extra": "fictional-secret"},
                   {"org.opencontainers.image.ref.name": ["banking-preflight"]}]
        for location in ("index", "manifest", "selected_descriptor", "config_descriptor", "layer_descriptor"):
            for value in invalid:
                with self.subTest(location=location, value=value):
                    self.write(self.annotation_files(location, value))
                    output = {}
                    with self.assertRaisesRegex(verifier.OciError, "^unapproved_oci_annotations$"):
                        self.check(metadata=output)
                    self.assertEqual(output, {})
                    self.assertFalse((self.root / "oci-metadata").exists())

    def test_compatibility_failure_diagnostics_do_not_echo_sensitive_values(self):
        cases = [("Volumes", {"/private/fictional-secret": {}}, "unsupported_raw_config_volumes",
                  {"field": "Volumes", "present": True, "value_type": "object", "empty_object": False}),
                 ("ArgsEscaped", True, "unsupported_raw_config_args_escaped",
                  {"field": "ArgsEscaped", "present": True, "value_type": "boolean", "boolean": True}),
                 ("ArgsEscaped", None, "unsupported_raw_config_args_escaped",
                  {"field": "ArgsEscaped", "present": True, "value_type": "null", "null": True}),
                 ("ArgsEscaped", "fictional-secret", "unsupported_raw_config_args_escaped",
                  {"field": "ArgsEscaped", "present": True, "value_type": "string"}),
                 ("StopSignal", "", "unsupported_raw_config_stop_signal",
                  {"field": "StopSignal", "present": True, "value_type": "string", "blank": True}),
                 ("StopSignal", "SIGQUIT", "unsupported_raw_config_stop_signal",
                  {"field": "StopSignal", "present": True, "value_type": "string", "recognized_unix_signal": "SIGQUIT"}),
                 ("StopSignal", "fictional-secret", "unsupported_raw_config_stop_signal",
                  {"field": "StopSignal", "present": True, "value_type": "string"})]
        for field, value, code, expected in cases:
            with self.subTest(field=field, value=value):
                self.public_config()
                self.config["config"][field] = value
                self.final["Config"] = copy.deepcopy(self.config["config"])
                self.write(self.files())
                output = {}
                with self.assertRaisesRegex(verifier.OciError, "^" + code + "$") as found:
                    self.check(metadata=output)
                self.assertEqual(found.exception.safe_diagnostic, expected)
                self.assertNotIn("fictional-secret", json.dumps(found.exception.safe_diagnostic))
                self.assertEqual(output, {})

    def test_compatibility_accepted_values_are_unchanged(self):
        for field, accepted in (("Volumes", (None, {})), ("ArgsEscaped", (False,)),
                                ("StopSignal", (None, "SIGTERM", "15"))):
            for value in accepted:
                with self.subTest(field=field, value=value):
                    self.public_config()
                    self.config["config"][field] = value
                    self.final["Config"] = copy.deepcopy(self.config["config"])
                    self.write(self.files())
                    self.assertEqual(self.check(metadata={})["status"], "passed")
            self.public_config()
            self.config["config"].pop(field, None)
            self.final["Config"] = copy.deepcopy(self.config["config"])
            self.write(self.files())
            self.assertEqual(self.check(metadata={})["status"], "passed")

    def test_inherited_literal_true_linux_exec_vector_retains_exact_raw_flag_and_basis(self):
        base = self.inherited_true_fixture()
        self.write(self.files())
        metadata = {}
        receipt = self.check(metadata=metadata, base=base)
        self.assertIs(json.loads(metadata["oci-config.json"])["config"]["ArgsEscaped"], True)
        self.assertEqual(receipt["args_escaped_compatibility"]["mode"], "observed_inherited_linux_exec_vector")
        for key in ("raw_value", "daemon_base_value", "daemon_final_value"):
            self.assertIs(receipt["args_escaped_compatibility"][key], True)
        self.assertFalse(receipt["args_escaped_compatibility"]["runtime_or_roundtrip_proof"])
        self.assertEqual(receipt["daemon_base_image_id"], base["Id"])
        self.assertEqual(receipt["base_inheritance"]["base_rootfs_diff_ids"], self.diff_ids[:1])
        self.assertTrue(receipt["base_inheritance"]["ordered_base_layers_retained"])
        self.assertEqual(self.check(base=base)["status"], "passed")

    def test_true_requires_actual_base_and_final_literal_bools_not_coercible_values(self):
        for location in ("raw", "base", "final"):
            for value in (None, False, 1, 0, "true", [], {}):
                with self.subTest(location=location, value=value):
                    base = self.inherited_true_fixture()
                    target = {"raw": self.config["config"], "base": base["Config"],
                              "final": self.final["Config"]}[location]
                    target["ArgsEscaped"] = value
                    # Literal false remains accepted for the raw case.
                    if location == "raw" and value is False:
                        continue
                    self.write(self.files())
                    output = {}
                    with self.assertRaisesRegex(verifier.OciError, "^unsupported_raw_config_args_escaped$"):
                        self.check(metadata=output, base=base)
                    self.assertEqual(output, {})
        for location in ("base", "final"):
            with self.subTest(missing=location):
                base = self.inherited_true_fixture()
                target = base["Config"] if location == "base" else self.final["Config"]
                del target["ArgsEscaped"]
                self.write(self.files())
                with self.assertRaisesRegex(verifier.OciError, "^unsupported_raw_config_args_escaped$"):
                    self.check(metadata={}, base=base)
        self.inherited_true_fixture()
        self.write(self.files())
        with self.assertRaisesRegex(verifier.OciError, "^unsupported_raw_config_args_escaped$"):
            self.check(metadata={})

    def test_true_rejects_changed_launcher_in_raw_final_or_base(self):
        for location in ("raw", "final", "base"):
            for field, value in (("Cmd", ["node", "unreviewed.mjs"]),
                                 ("Entrypoint", ["sh", "-c"]), ("User", "root"),
                                 ("WorkingDir", "/unreviewed")):
                with self.subTest(location=location, field=field):
                    base = self.inherited_true_fixture()
                    target = {"raw": self.config["config"], "base": base["Config"],
                              "final": self.final["Config"]}[location]
                    target[field] = value
                    if location == "raw":
                        self.final["Config"][field] = copy.deepcopy(value)
                    self.write(self.files())
                    output = {}
                    with self.assertRaises(verifier.OciError):
                        self.check(metadata=output, base=base)
                    self.assertEqual(output, {})

    def test_true_rejects_unsupported_base_or_final_platforms(self):
        for location in ("base", "final", "raw"):
            for field, value in (("Os", "windows"), ("Architecture", "arm64")):
                with self.subTest(location=location, field=field):
                    base = self.inherited_true_fixture()
                    target = {"base": base, "final": self.final, "raw": self.config}[location]
                    target[field.lower() if location == "raw" else field] = value
                    self.write(self.files())
                    output = {}
                    with self.assertRaises(verifier.OciError):
                        self.check(metadata=output, base=base)
                    self.assertEqual(output, {})

    def test_true_requires_base_source_version_build_revision_and_exact_layers(self):
        mutations = [
            (lambda base: base["Config"]["Labels"].__setitem__("org.opencontainers.image.revision", "f" * 40),
             "base_daemon_source_labels_mismatch"),
            (lambda base: base["Config"]["Labels"].__setitem__("io.flujo.application.version", "other"),
             "base_daemon_source_labels_mismatch"),
            (lambda base: base["Config"]["Env"].remove("FLUJO_BUILD_REVISION=" + self.flujo),
             "base_daemon_build_revision_mismatch"),
            (lambda base: base["Config"]["Env"].append("FLUJO_BUILD_REVISION=" + "f" * 40),
             "base_daemon_build_revision_mismatch"),
            (lambda base: base["RootFS"].__setitem__("Layers", []), "invalid_base_daemon_rootfs"),
            (lambda base: base["RootFS"].__setitem__("Layers", self.diff_ids), "base_layers_not_strict_retained_prefix"),
            (lambda base: base["RootFS"].__setitem__("Layers", self.diff_ids[1:]), "base_layers_not_strict_retained_prefix"),
            (lambda base: base.__setitem__("Id", "not-a-digest"), "unsupported_or_invalid_digest"),
        ]
        for mutate, code in mutations:
            with self.subTest(code=code):
                base = self.inherited_true_fixture()
                mutate(base)
                self.write(self.files())
                output = {}
                with self.assertRaisesRegex(verifier.OciError, "^" + code + "$"):
                    self.check(metadata=output, base=base)
                self.assertEqual(output, {})

    def test_inherited_true_still_rejects_unapproved_annotations_before_retention(self):
        base = self.inherited_true_fixture()
        self.write(self.annotation_files("manifest", {"credential": "fictional-secret"}))
        output = {}
        with self.assertRaisesRegex(verifier.OciError, "^unapproved_oci_annotations$"):
            self.check(metadata=output, base=base)
        self.assertEqual(output, {})

    def test_inspect_reader_requires_one_object_and_rejects_duplicate_keys(self):
        path = self.root / "fictional-inspect.json"
        for contents, code in ((b"[]", "ambiguous_daemon_inspect"),
                                (b"[{},{}]", "ambiguous_daemon_inspect"),
                                (b"[null]", "ambiguous_daemon_inspect"),
                                (b"{}", "ambiguous_daemon_inspect"),
                                (b'[{"Config":{"ArgsEscaped":false,"ArgsEscaped":true}}]', "duplicate_json_key"),
                                (b"[{\"Config\":NaN}]", "invalid_json_constant")):
            with self.subTest(code=code, contents=contents):
                path.write_bytes(contents)
                with self.assertRaisesRegex(verifier.OciError, "^" + code + "$"):
                    verifier.read_inspect(path)
        contents = encoded([self.inherited_true_fixture()])
        path.write_bytes(contents)
        inspected, retained_bytes = verifier.read_inspect(path)
        self.assertEqual(retained_bytes, contents)
        self.assertEqual(inspected["Id"], "sha256:" + "e" * 64)

    def test_inspect_reader_rejects_missing_and_bounded_oversize_inputs(self):
        path = self.root / "missing-inspect.json"
        with self.assertRaisesRegex(verifier.OciError, "^inspect_not_regular_or_too_large$"):
            verifier.read_inspect(path)
        path.write_bytes(b"[{}]")
        with patch.object(verifier, "MAX_JSON", 3):
            with self.assertRaisesRegex(verifier.OciError, "^inspect_not_regular_or_too_large$"):
                verifier.read_inspect(path)

    def test_raw_validator_cannot_allow_true_without_bound_inspect_evidence(self):
        self.inherited_true_fixture()
        with self.assertRaisesRegex(verifier.OciError, "^unsupported_raw_config_args_escaped$"):
            verifier.validate_raw_config(self.config, self.final["Config"], self.flujo, self.banking)

    def test_local_main_refuses_before_reading_input_or_creating_receipt(self):
        output = self.root / "must-not-exist.json"
        with patch.dict("os.environ", {"GITHUB_ACTIONS": "false"}), \
                patch.object(verifier, "verify") as verify:
            result = verifier.main(["--archive", str(self.path), "--final-inspect", "missing.json",
                                    "--base-inspect", "also-missing.json",
                                    "--candidate-revision", self.candidate,
                                    "--expected-flujo-revision", self.flujo,
                                    "--expected-bank-revision", self.banking,
                                    "--metadata-dir", str(self.root / "must-not-exist"), "--out", str(output)])
        self.assertEqual(result, 1)
        verify.assert_not_called()
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
