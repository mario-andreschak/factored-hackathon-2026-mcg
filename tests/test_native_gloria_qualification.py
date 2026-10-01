"""Host admission lifecycle tests; actual native provider evidence is separate."""
import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest

from scripts.native_gloria_qualification import NativeGloriaPort, BOUNDARY_CASES, CAPABILITY_CASES, public_report


class PublicQualificationReportTests(unittest.TestCase):
    def report_fixture(self):
        checksum = "a" * 64
        return {"pass": True, "installed": True, "flujoRevision": "0" * 40,
                "imageIdentity": "sha256:" + checksum, "externalManifestSha256": checksum,
                "imageCredentialAudit": {"checked": 5, "credential_files_present": 0},
                "sourceContext": {"application_revision": "1" * 40,
                    "application_files": {"gloria_workflow/tool.py": checksum},
                    "flujo_files": {"package-lock.json": checksum}},
                "installedSourceHashes": {"pass": True, "manifest_sha256": checksum,
                    "application_files": 1, "flujo_files": 1},
                "nativeProfile": {"verifiedCliVersion": "0.157.1", "verifiedCliSha256": checksum,
                    "verifiedModelCatalogSha256": checksum, "private_path": "PRIVATE_MARKER"},
                "installedModel": {"id": "gloria-native-model", "name": "gpt-6-sol", "provider": "codex",
                    "adapter": "codex-cli", "reasoningEffort": "low", "ApiKey": "PRIVATE_MARKER"},
                "cases": [{"case": name, "pass": True, "httpStatus": 200, "seconds": 1,
                    "private_response": "PRIVATE_MARKER", "bank_calls": ["PRIVATE_MARKER"],
                    "model_observations": [{"stage": "detect_intent", "status": "ok", "latency_ms": 1,
                        "model_content": "PRIVATE_MARKER"}]} for name in sorted(BOUNDARY_CASES)],
                "nativeCapabilityProbes": {"bridgeSourceSha256": checksum, "fixtureSha256": checksum,
                    "cases": [{"model": model, "tool": tool, "passed": True,
                               "private_output": "PRIVATE_MARKER"} for model, tool in sorted(CAPABILITY_CASES)]},
                "admissions": [{"token": "PRIVATE_MARKER"}]}

    def test_public_report_excludes_private_payloads_and_retains_measurements(self):
        published = public_report(self.report_fixture())
        self.assertNotIn("PRIVATE_MARKER", json.dumps(published))
        self.assertEqual(published["boundary_cases"]["count"], 14)
        self.assertEqual(published["native_capability_probes"]["count"], 14)
        self.assertEqual(published["boundary_cases"]["cases"][0]["bank_read_count"], 1)
        self.assertTrue(published["installed_source_equality"]["manifest_equals_external_context"])

    def test_incomplete_or_source_drift_report_cannot_be_published(self):
        for mutate in (lambda value: value["cases"].pop(),
                       lambda value: value["nativeCapabilityProbes"]["cases"].pop(),
                       lambda value: value["nativeCapabilityProbes"]["cases"].__setitem__(0,
                           value["nativeCapabilityProbes"]["cases"][1].copy()),
                       lambda value: value.update({"pass": False}),
                       lambda value: value["installedSourceHashes"].update(manifest_sha256="b" * 64),
                       lambda value: value["imageCredentialAudit"].update(credential_files_present=1)):
            fixture = self.report_fixture()
            mutate(fixture)
            with self.assertRaises(ValueError):
                public_report(fixture)


class NativeHostAdmissionTests(unittest.IsolatedAsyncioTestCase):
    def binding(self, owner="owner-A", session="session-A", conversation="conversation-A"):
        return {"owner": owner, "customer_id": "public-synthetic", "session_id": session,
                "conversation_id": conversation, "expires_at": time.time() + 60}

    async def test_exact_original_and_trusted_controls_reach_workflow_and_admission_is_revoked(self):
        with tempfile.TemporaryDirectory() as directory:
            location = Path(directory) / "admissions.json"
            selection = {"reference": "opaque-synthetic", "snapshot_id": "snapshot"}
            binding = self.binding()
            expected = {"response": {"message": "Respuesta validada"}}
            class Workflow:
                async def run(inner, admitted, message, **kwargs):
                    records = json.loads(location.read_text(encoding="utf-8"))
                    self.assertEqual(len(records), 1)
                    self.assertEqual(records[0]["message"], "Original exacto")
                    self.assertEqual(records[0]["mode"], "language_only")
                    self.assertNotIn("selection", records[0])
                    self.assertEqual(admitted, binding)
                    self.assertEqual(message, "Original exacto")
                    self.assertEqual(kwargs["selection"], selection)
                    self.assertEqual(kwargs["query_scope_id"], "query-A")
                    self.assertEqual(inner.model.model_id, "model-gloria-native-model")
                    self.assertEqual(len(records[0]["bindingFingerprint"]), 64)
                    return expected
            def factory(model):
                workflow = Workflow(); workflow.model = model; return workflow
            port = NativeGloriaPort(factory, "http://127.0.0.1:43921", directory)
            actual = await port.run(binding, "Original exacto", turn_id="turn-A", selection=selection, query_scope_id="query-A")
            self.assertIs(actual, expected)
            self.assertEqual(json.loads(location.read_text()), [])
            self.assertTrue((Path(directory) / ".admissions-host.lock").exists())
            with port._edit_admissions() as records:
                self.assertEqual(records, [])

    async def test_failed_workflow_revokes_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            class Workflow:
                async def run(self, *_args, **_kwargs):
                    raise RuntimeError("synthetic_failure")
            port = NativeGloriaPort(lambda _model: Workflow(), "http://127.0.0.1:43921", directory)
            with self.assertRaisesRegex(RuntimeError, "synthetic_failure"):
                await port.run(self.binding(), "Original", turn_id="turn-A")
            self.assertEqual(json.loads((Path(directory) / "admissions.json").read_text()), [])

    async def test_simultaneous_owners_have_distinct_tokens_bindings_and_scoped_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            ready = asyncio.Event()
            entered = []
            class Workflow:
                async def run(inner, binding, message, **_kwargs):
                    entered.append(binding["owner"])
                    if len(entered) == 2:
                        records = json.loads((Path(directory) / "admissions.json").read_text())
                        self.assertEqual(len({item["stageToken"] for item in records}), 2)
                        self.assertEqual(len({item["bindingFingerprint"] for item in records}), 2)
                        self.assertEqual({item["owner"] for item in records}, {"owner-A", "owner-B"})
                        ready.set()
                    await asyncio.wait_for(ready.wait(), 2)
                    return {"owner": binding["owner"], "message": message}
            port = NativeGloriaPort(lambda _model: Workflow(), "http://127.0.0.1:43921", directory)
            values = await asyncio.gather(port.run(self.binding(), "Message A", turn_id="turn-A"),
                port.run(self.binding("owner-B", "session-B", "conversation-B"), "Message B", turn_id="turn-B"))
            self.assertEqual({item["owner"] for item in values}, {"owner-A", "owner-B"})
            self.assertEqual(json.loads((Path(directory) / "admissions.json").read_text()), [])

    async def test_expired_or_unauthenticated_binding_creates_no_admission(self):
        for change in ({"expires_at": time.time() - 1}, {"authenticated": False}):
            with tempfile.TemporaryDirectory() as directory:
                port = NativeGloriaPort(lambda _model: self.fail("must not construct workflow"), "http://127.0.0.1:43921", directory)
                with self.assertRaises(ValueError):
                    await port.run({**self.binding(), **change}, "Original", turn_id="turn-A")
                self.assertFalse((Path(directory) / "admissions.json").exists())

    async def test_abandoned_marker_does_not_block_new_host_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / ".admissions-host.lock").touch()
            class Workflow:
                async def run(self, *_args, **_kwargs):
                    return {"validated": True}
            port = NativeGloriaPort(lambda _model: Workflow(), "http://127.0.0.1:43921", directory)
            self.assertEqual(await port.run(self.binding(), "Original", turn_id="turn-A"), {"validated": True})


if __name__ == "__main__":
    unittest.main()
