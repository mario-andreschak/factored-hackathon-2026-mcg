"""Pure gates only. Never starts HTTP, Docker, MCP, bank state or a generator."""
import copy
import hashlib
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/synthetic_integration"))
import contract as c
import consume_package as consumer
import checkpoint
import dataset
import fixture_coverage as coverage
import scenarios

ENV = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted",
       "RUNNER_OS": "Linux", "GITHUB_REPOSITORY": c.REPOSITORY, "GITHUB_SHA": "a" * 40}


def review():
    return {"schema": "banking-synthetic-integration-review/v1", "reviewed_head": "a" * 40,
            "root_review": "approved", "scenario_mode": "stock-and-authored-coverage",
            "fixture_pin_sha256": c.FIXTURE_PIN_SHA, "frontend_gate_source": c.FRONTEND_GATE_HEAD,
            "bundle": {"artifact_id": 17, "run_id": 18, "source_head": "d" * 40,
                       **{key: "e" * 64 for key in ("zip_sha256", "manifest_sha256", "graph_sha256",
                               "policy_template_sha256", "fixture_provider_sha256")}}}


def runtime_config():
    return {"Cmd": ["npm", "start"], "Entrypoint": ["docker-entrypoint.sh"],
            "WorkingDir": "/app", "User": "node", "Env": ["NODE_ENV=production"],
            "Labels": {"source": "reviewed"}, "ExposedPorts": {"4200/tcp": {}, "4201/tcp": {}},
            "ArgsEscaped": True}


def counts():
    return {"cases": 0, "receipts": 0, "handoffs": 0, "pending": 0, "tool_calls": {},
            "external_network_attempts": 0, "fixture_provider_calls": 1,
            "forwarded_faults": 0, "forbidden_dispatch_attempts": 0}


class SourceGates(unittest.TestCase):
    def reject(self, fn, *args, **kwargs):
        with self.assertRaises(c.CheckpointError):
            fn(*args, **kwargs)

    def test_strict_json(self):
        for raw in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '[]', '{broken'):
            with self.subTest(raw=raw):
                self.reject(c.strict_json, raw)
        self.assertEqual(c.strict_json('{"x":null}'), {"x": None})

    def test_paths(self):
        for value in ("../a", "a/../b", "a//b", "/a", "C:a", "a\\b", "a/./b", "a\x00"):
            with self.subTest(value=value):
                self.reject(c.safe_path, value)
        self.assertEqual(c.safe_path("fixture/dataset_source/source/pipeline/contracts.yaml"),
                         "fixture/dataset_source/source/pipeline/contracts.yaml")

    def test_zip_rejects_traversal_duplicate_link_and_limit(self):
        for kind in ("traversal", "duplicate", "link", "limit"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with zipfile.ZipFile(root / "source.zip", "w") as archive:
                    if kind == "traversal":
                        archive.writestr("../escaped", b"x")
                    elif kind == "duplicate":
                        import warnings
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            archive.writestr("same", b"a")
                            archive.writestr("same", b"b")
                    elif kind == "link":
                        entry = zipfile.ZipInfo("link")
                        entry.create_system = 3
                        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                        archive.writestr(entry, "target")
                    else:
                        archive.writestr("large", b"123")
                self.reject(c.extract_zip, root / "source.zip", root / "out", max_bytes=2)
                self.assertFalse((root / "out").exists())

    def test_zip_exact_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with zipfile.ZipFile(root / "source.zip", "w") as archive:
                archive.writestr("candidate.oci.tar", b"bytes")
            c.extract_zip(root / "source.zip", root / "out", max_bytes=5, only={"candidate.oci.tar"})
            self.assertEqual((root / "out/candidate.oci.tar").read_bytes(), b"bytes")

    def test_remote_identity(self):
        c.validate_remote(ENV)
        for field in ENV.keys() - {"GITHUB_SHA"}:
            self.reject(c.validate_remote, {**ENV, field: "local"})

    def test_review_exact_source_and_dependency(self):
        c.validate_review(review(), "a" * 40)
        self.reject(c.validate_review, review(), "f" * 40)
        for field, wrong in (("fixture_pin_sha256", c.BANK), ("frontend_gate_source", None),
                             ("frontend_gate_source", "b" * 40),
                             ("root_review", "pending"), ("scenario_mode", "future-clock")):
            bad = review()
            bad[field] = wrong
            self.reject(c.validate_review, bad, "a" * 40)
        bad = review()
        bad["bundle"]["artifact_id"] = True
        self.reject(c.validate_review, bad, "a" * 40)

    def test_source_hold_stops_network_process_and_bank_setup(self):
        with patch.dict("os.environ", ENV, clear=True), \
             patch("subprocess.run", side_effect=AssertionError("process forbidden")), \
             patch("subprocess.check_output", side_effect=AssertionError("process forbidden")), \
             patch("urllib.request.build_opener", side_effect=AssertionError("HTTP forbidden")):
            self.assertIs(c.PREPARATION_ONLY, True)
            self.reject(checkpoint.require_execution_release)
            self.reject(consumer.api, "/repos/" + c.REPOSITORY)
            self.reject(consumer.download, 1, Path("unused"), "0" * 64, 2)
            self.reject(consumer.verify_filemap, "sha256:" + "0" * 64, {}, Path("unused"))
            self.reject(consumer.restore_and_verify, Path("unused"), Path("unused"), {}, {})
            self.reject(dataset.generate, Path("unused"), Path("unused"))
            self.reject(coverage.initialize, Path("unused"), Path("unused"), generated_dir=Path("unused"), out=Path("unused"))
            browser = scenarios.Browser("http://127.0.0.1:9999")
            self.reject(browser.request, "GET", "/api/action/status")

    def test_file_pinned_dataset_closure(self):
        dataset.verify_source(ROOT / "scripts/synthetic_integration/dataset_source")
        with tempfile.TemporaryDirectory() as temporary:
            import shutil
            source = Path(temporary) / "copy"
            shutil.copytree(ROOT / "scripts/synthetic_integration/dataset_source", source)
            with (source / "generate_fixture.py").open("ab") as stream:
                stream.write(b"# changed\n")
            self.reject(dataset.verify_source, source)

    def test_preparation_source_manifest(self):
        manifest = c.strict_json((ROOT / "scripts/synthetic_integration/source-inputs.sha256.json").read_bytes())
        self.assertEqual(manifest["schema"], "banking-synthetic-source-input-manifest/v1")
        self.assertIs(manifest["execution_enabled"], False)
        for relative, digest in manifest["files"].items():
            self.assertEqual(c.sha256(ROOT / c.safe_path(relative)), digest, relative)

    def test_scoped_paths_reject_parent_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            self.assertEqual(dataset.scoped_path(root / "new", root, exists=False), root / "new")
            self.reject(dataset.scoped_path, root / "a/../new", root, exists=False)
            self.reject(dataset.scoped_path, root.parent / "outside", root, exists=False)

    def test_source_release_identity_even_if_future_hold_removed(self):
        release = {"schema": "banking-synthetic-runtime-release/v1", "reviewed_head": "a" * 40,
                   "root_review": "approved", "package_head": c.PACKAGE_HEAD,
                   "restored_image_id": "sha256:" + "1" * 64, "derived_image_id": "sha256:" + "2" * 64,
                   "artifact_content_verified": True, "derived_source_verified": True,
                   "fixture_pin_sha256": c.FIXTURE_PIN_SHA, "frontend_gate_source": c.FRONTEND_GATE_HEAD,
                   "bundle_source_head": "d" * 40, "bundle_manifest_sha256": "e" * 64}
        with patch.object(c, "PREPARATION_ONLY", False):
            c.require_runtime_release(ENV, release)
            self.reject(c.require_runtime_release, ENV, {**release, "derived_source_verified": 1})
            self.reject(c.require_runtime_release, ENV, {**release, "reviewed_head": "f" * 40})
            self.reject(c.require_runtime_release, ENV, {**release, "fixture_pin_sha256": c.BANK})

    def test_successful_private_package_origin(self):
        run = {"id": c.PACKAGE_RUN, "head_sha": c.PACKAGE_HEAD, "run_attempt": 1,
               "status": "completed", "conclusion": "success",
               "path": ".github/workflows/banking-package-issue21-preflight.yml"}
        repo = {"full_name": c.REPOSITORY, "private": True}
        c.assert_package_run(run, repo)
        self.reject(c.assert_package_run, {**run, "conclusion": "failure"}, repo)
        self.reject(c.assert_package_run, {**run, "head_sha": "a" * 40}, repo)
        self.reject(c.assert_package_run, run, {**repo, "private": False})

    def test_expired_or_substituted_artifact(self):
        artifact = {"id": c.OCI_ID, "expired": False, "digest": "sha256:" + c.OCI_ZIP_SHA,
                    "workflow_run": {"id": c.PACKAGE_RUN, "head_sha": c.PACKAGE_HEAD}}
        c.assert_artifact(artifact, c.OCI_ID, c.PACKAGE_RUN, c.PACKAGE_HEAD, c.OCI_ZIP_SHA)
        for bad in ({**artifact, "expired": True}, {**artifact, "digest": "sha256:" + "0" * 64},
                    {**artifact, "workflow_run": {"id": c.PACKAGE_RUN, "head_sha": "a" * 40}}):
            self.reject(c.assert_artifact, bad, c.OCI_ID, c.PACKAGE_RUN, c.PACKAGE_HEAD, c.OCI_ZIP_SHA)

    def test_runtime_configuration_and_strict_types(self):
        raw = runtime_config()
        bridge = {"healthcheck": {"daemon_present": True, "oci_present": False}}
        semantics = consumer.check_runtime_config(copy.deepcopy(raw), raw, bridge)
        self.assertFalse(semantics["inherited_docker_healthcheck_survival_claim"])
        for field, bad_value in (("ArgsEscaped", 1), ("Healthcheck", {"Test": ["NONE"]}),
                                 ("Volumes", {"/shared": {}}), ("StopSignal", "SIGKILL"),
                                 ("ExposedPorts", {"4200/tcp": {}}), ("User", "root")):
            self.reject(consumer.check_runtime_config, {**raw, field: bad_value}, raw, bridge)

    def test_derived_image_layer_prefix_and_controlled_config(self):
        raw = runtime_config()
        configured = copy.deepcopy(raw)
        configured.update(Entrypoint=["/opt/fixture-front/.venv/bin/python", "/opt/integration/harness/inside.py"],
                          Cmd=[], WorkingDir="/opt/integration/harness")
        configured["Labels"].update({"io.flujo.integration.scope": "derived-fictional-no-model-assembly",
                "io.flujo.integration.fixture.source": c.FIXTURE_PIN_SHA,
                "io.flujo.integration.frontend.source": c.FRONTEND_GATE_HEAD})
        configured["Env"] += ["PYTHONDONTWRITEBYTECODE=1", "PYTHONUNBUFFERED=1",
                              "PYTHONPATH=/opt/integration/harness:/opt/integration/fixture:/opt/fixture-front",
                              "SCENARIO_MODE=stock-and-authored-coverage"]
        image = {"Os": "linux", "Architecture": "amd64", "Id": "sha256:" + "1" * 64,
                 "RootFS": {"Layers": ["sha256:" + "2" * 64, "sha256:" + "3" * 64]}, "Config": configured}
        restored = {"rootfs_diff_ids": image["RootFS"]["Layers"][:1]}
        bridge = {"healthcheck": {"daemon_present": True, "oci_present": False}}
        checkpoint.validate_derived(image, restored, raw, bridge, review())
        bad = copy.deepcopy(image)
        bad["RootFS"]["Layers"].reverse()
        self.reject(checkpoint.validate_derived, bad, restored, raw, bridge, review())
        bad = copy.deepcopy(image)
        bad["Config"]["Env"].append("GH_TOKEN=forbidden")
        self.reject(checkpoint.validate_derived, bad, restored, raw, bridge, review())

    def test_history_binds_generation_owners_input_snapshot_and_gap(self):
        inputs = {"anchor_epoch": 200000, "coverage_start": 110000,
                  "owner_source_sha256": "1" * 64, "fixture_inputs_sha256": "2" * 64,
                  "fixture_pin_sha256": c.FIXTURE_PIN_SHA,
                  "owners": ["CUS900000", "CUS900001", "CUS900002"],
                  "source_files_sha256": {"closed_history.json": "3" * 64}}
        bindings = {"close_epoch": 200005, "generation": "4" * 64, "build": "fixture-build",
                    "fingerprint": "5" * 64, "snapshot_sha256": "6" * 64, "inputs": inputs,
                    "release": {"reviewed_head": "a" * 40, "bundle_source_head": "b" * 40,
                                "bundle_manifest_sha256": "c" * 64}}
        history = coverage.make_history(**bindings)
        start, provenance = coverage.validate_history(history, **bindings)
        self.assertEqual(start, 110000)
        self.assertTrue(provenance.startswith("synthetic:"))
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "authored-history.json"
            artifact.write_bytes(coverage.canonical_bytes(history))
            self.assertEqual(provenance.split(":")[-1], c.sha256(artifact))
            artifact.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
            self.assertNotEqual(provenance.split(":")[-1], c.sha256(artifact))
        for key, changed in (("generation", "7" * 64), ("snapshot_sha256", "8" * 64), ("close_epoch", 200006)):
            self.reject(coverage.validate_history, history, **{**bindings, key: changed})
        bad = copy.deepcopy(history)
        bad["setup_gap"]["events"] = [{"seeded_case": True}]
        self.reject(coverage.validate_history, bad, **bindings)
        bad = copy.deepcopy(history)
        bad["action_counts_before_api"]["sandbox_cases"] = False
        self.reject(coverage.validate_history, bad, **bindings)
        self.reject(coverage.make_history, **{**bindings, "close_epoch": 199999})

    def test_same_owner_snapshot_must_match_actual_input_bytes(self):
        expected = {"customers.csv": {"bytes": 10, "sha256": "1" * 64, "etag": "sha256:" + "1" * 32},
                    "products.csv": {"bytes": 20, "sha256": "2" * 64, "etag": "sha256:" + "2" * 32},
                    "transactions/year=2026/month=09/day=30/present-fixture.csv":
                        {"bytes": 30, "sha256": "3" * 64, "etag": "sha256:" + "3" * 32}}
        objects = {key: {"key": key, "bytes": value["bytes"], "etag": value["etag"]}
                   for key, value in expected.items()}
        binding = hashlib.sha256()
        for key in sorted(objects):
            binding.update(f"{key}|{objects[key]['etag']}|{objects[key]['bytes']}\n".encode())
        fingerprint = binding.hexdigest()[:16]
        coverage.verify_snapshot_sources(objects, expected, fingerprint)
        bad = copy.deepcopy(objects)
        bad["customers.csv"]["bytes"] = 11
        self.reject(coverage.verify_snapshot_sources, bad, expected, fingerprint)
        bad = copy.deepcopy(objects)
        bad["customers.csv"]["etag"] = "sha256:" + "4" * 32
        self.reject(coverage.verify_snapshot_sources, bad, expected, fingerprint)
        self.reject(coverage.verify_snapshot_sources, {**objects, "extra.csv": {}}, expected, fingerprint)
        self.reject(coverage.verify_snapshot_sources, objects, expected, "5" * 16)

    def test_denial_cannot_create_pending_or_dispatch(self):
        before = counts()
        scenarios.denied_unchanged(before, copy.deepcopy(before))
        self.reject(scenarios.denied_unchanged, before, {**before, "pending": 1})
        self.reject(scenarios.denied_unchanged, before, {**before, "tool_calls": {"prepare_unrecognized_charge": 1}})
        # Ordinary prepares legitimately change pending; use the narrower write check.
        scenarios.unchanged(before, {**before, "pending": 1})

    def test_completed_correlated_fault_marker_required(self):
        marker = {"operation": "confirm", "target_matches": True, "completed_upstream": True,
                  "consumed": True, "consent": True, "receipt": {"id": "CMP-SBX-actual"}, "handoff_id": None}
        class Provider:
            def read_consumed_fault(self, *args):
                return marker
        scenarios.consumed_fault(Provider(), "es", "confirm", "private-handle", receipt=marker["receipt"])
        for key, value in (("consumed", False), ("target_matches", False), ("consent", 1), ("receipt", None)):
            old = marker[key]
            marker[key] = value
            self.reject(scenarios.consumed_fault, Provider(), "es", "confirm", "private-handle", receipt={"id": "CMP-SBX-actual"})
            marker[key] = old

    def test_independent_absent_coverage_observation(self):
        observed = {"rows": 0, "configured_start_matches": False, "generation_matches": False, "complete": False}
        class Provider:
            def read_coverage(self):
                return observed
        scenarios.coverage(Provider(), complete=False)
        observed["complete"] = True
        self.reject(scenarios.coverage, Provider(), complete=False)

    def test_prepare_recovery_retains_actual_host_identity(self):
        observed = {"host_request_id": "11111111-1111-4111-8111-111111111111",
                    "action_id": "22222222-2222-4222-8222-222222222222", "revision": 1,
                    "conversation_sha256": "1" * 64, "pending_handle_sha256": "2" * 64,
                    "pending_identity_count": 1, "handoff_id": "HOF-abcd1234",
                    "handoff_packet_sha256": "3" * 64, "ledger_generation": "4" * 64,
                    "target_matches": True, "completed_upstream": True, "consumed": True}
        class Provider:
            def read_prepare_recovery(self, *args):
                return observed
        before = scenarios.prepare_recovery_identity(Provider(), "es", "private-cookie")
        scenarios.compare_prepare_recovery(before, {**before, "revision": 2})
        for field, wrong in (("host_request_id", "33333333-3333-4333-8333-333333333333"),
                             ("pending_handle_sha256", "5" * 64), ("ledger_generation", "6" * 64),
                             ("handoff_packet_sha256", "7" * 64), ("revision", 0)):
            self.reject(scenarios.compare_prepare_recovery, before, {**before, field: wrong})
        observed["pending_identity_count"] = 2
        self.reject(scenarios.prepare_recovery_identity, Provider(), "es", "private-cookie")


if __name__ == "__main__":
    unittest.main()
