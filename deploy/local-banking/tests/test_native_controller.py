"""Local controller source regressions; no Docker, DATA or authority lifecycle.

Run under the repository's serialized capped Windows test controller. The
observer test uses only isolated temporary scripts and actual Windows read locks.
It is not a retirement observation or application/runtime acceptance receipt.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "native-controller.py"
MODULE_SPEC = importlib.util.spec_from_file_location("native_controller_under_test", SOURCE)
CONTROLLER = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(CONTROLLER)


class NativeControllerSourceTests(unittest.TestCase):
    def test_observed_failed_source_refuses_before_any_external_operation(self):
        spec = {"schema": "savia-local-native-controller/v1",
                "applicationRevision": "676466111e7013136488b0aa7a0cf1ecbee45a86"}
        with patch.object(CONTROLLER, "committed_source") as committed, \
                patch.object(CONTROLLER, "command") as command:
            with self.assertRaisesRegex(CONTROLLER.Refused,
                                        "source_has_observed_provider_component_failure"):
                CONTROLLER.preflight(spec, None)
        committed.assert_not_called()
        command.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "actual Windows sharing locks required")
    def test_observer_replacement_is_denied_before_python_reopens_the_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_directory = root / "observer-source"
            source_directory.mkdir()
            observer = source_directory / "guard.py"
            proof = root / "retirement.private.json"
            proof.write_text("{}", encoding="utf-8")
            outside = root / "outside-sentinel.txt"
            outside.write_text("untouched", encoding="utf-8")
            replacement = root / "replacement.py"
            replacement.write_text(
                "from pathlib import Path\n"
                f"Path({str(outside)!r}).write_text('replacement executed')\n"
                "raise RuntimeError('replacement must never execute')\n", encoding="utf-8")
            observer.write_text(
                "import hashlib, json, sys\n"
                "from pathlib import Path\n"
                "result = {\n"
                " 'schema': 'savia-local-native-retirement-observation/v1',\n"
                " 'method': 'actual-docker-read-only',\n"
                " 'observerSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),\n"
                " 'dockerDaemonId': 'temporary-source-test-daemon',\n"
                " 'authorityProofSha256': '" + "a" * 64 + "',\n"
                " 'canonicalBankVolume': 'hackathon-banking-mcp-state',\n"
                " 'state': 'authority-disabled-no-respawn', 'consumers': [],\n"
                " 'scriptFile': __file__, 'argv': sys.argv,\n"
                " 'isolated': sys.flags.isolated, 'noBytecode': sys.dont_write_bytecode\n"
                "}\n"
                "print(json.dumps(result))\n", encoding="utf-8")
            original = observer.read_bytes()
            digest = hashlib.sha256(original).hexdigest()
            proof_digest = hashlib.sha256(proof.read_bytes()).hexdigest()
            spec = {"_retirement": {
                "guardObserver": {"path": str(observer), "sha256": digest},
                "retiredRwConsumers": [], "dockerDaemonId": "temporary-source-test-daemon",
                "authorityProofSha256": "a" * 64},
                "evidence": {"retirement": {"path": str(proof), "sha256": proof_digest}}}
            expected_args = [sys.executable, "-I", "-B", str(observer),
                             "--retirement-proof", str(proof),
                             "--retirement-proof-sha256", proof_digest]
            observed = []
            original_json_command = CONTROLLER.json_command

            def replace_at_former_digest_to_execution_seam(arguments, **options):
                self.assertEqual(arguments, expected_args)
                self.assertEqual(observer.read_bytes(), original)
                # These actual file-system operations occur after digest approval
                # and immediately before the original child interpreter opens it.
                with self.assertRaises(PermissionError):
                    observer.write_bytes(replacement.read_bytes())
                with self.assertRaises(PermissionError):
                    os.replace(replacement, observer)
                with self.assertRaises(PermissionError):
                    source_directory.rename(root / "renamed-observer-source")
                result = original_json_command(arguments, **options)
                observed.append(result)
                return result

            with patch.object(CONTROLLER, "json_command",
                              side_effect=replace_at_former_digest_to_execution_seam):
                CONTROLLER.observe_retirement(spec)
            self.assertEqual(len(observed), 1)
            self.assertEqual(observed[0]["observerSha256"], digest)
            self.assertEqual(observed[0]["scriptFile"], str(observer))
            self.assertEqual(observed[0]["argv"], expected_args[3:])
            self.assertEqual(observed[0]["isolated"], 1)
            self.assertTrue(observed[0]["noBytecode"])
            self.assertEqual(outside.read_text(encoding="utf-8"), "untouched")
            self.assertEqual(observer.read_bytes(), original)
            # The source-only invocation must release its own locks afterward.
            os.replace(replacement, observer)
            self.assertIn(b"replacement must never execute", observer.read_bytes())


if __name__ == "__main__":
    unittest.main()
