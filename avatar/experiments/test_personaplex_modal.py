"""Local-only protocol, admission and artifact checks. Never import/dispatch Modal."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
import wave

spec = importlib.util.spec_from_file_location("personaplex_smoke", Path(__file__).with_name("personaplex_modal.py"))
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class SmokeTests(unittest.TestCase):
    def test_default_plan_reads_no_credential_and_builds_no_app(self):
        with patch.object(smoke, "existing_token", side_effect=AssertionError("credential read")), patch.object(smoke, "build_app", side_effect=AssertionError("cloud app")), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(smoke.main([]), 0)
        plan = json.loads(output.getvalue())
        self.assertEqual(plan["gpu"], "A100-80GB")
        self.assertEqual(plan["timeout_seconds"], 600)
        self.assertEqual(plan["max_containers"], 1)
        self.assertLess(plan["runtime_startup_idle_estimate_usd"], 0.60)

    def test_unapproved_model_access_never_dispatches_even_when_execute_requested(self):
        with patch.object(smoke, "existing_token", return_value="private-sentinel"), patch.object(smoke, "check_access", return_value=403), patch.object(smoke, "build_app", side_effect=AssertionError("cloud app")), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(smoke.main(["--execute"]), 2)
        self.assertEqual(json.loads(output.getvalue()), {"model_access_status": 403, "existing_access_allowed": False, "cloud_dispatched": False})
        self.assertNotIn("private-sentinel", output.getvalue())

    def test_model_head_never_follows_redirect_or_prints_credentials(self):
        for status in (200, 302, 403, 0):
            self.assertEqual(smoke.access_allowed(status), status in (200, 302))
        self.assertIsNone(smoke.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://attacker.example"))

    def test_audio_outputs_reject_wrong_profile_and_unbounded_artifacts(self):
        value = io.BytesIO()
        with wave.open(value, "wb") as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(24000)
            audio.writeframes(b"\0\0" * 2400)
        self.assertEqual(smoke.audio_profile(value.getvalue())["seconds"], 0.1)
        for invalid in (b"not-a-wave", b"x" * (3 * 1024 * 1024 + 1)):
            with self.assertRaises(RuntimeError): smoke.audio_profile(invalid)

    def test_archive_reads_only_known_regular_voice_and_does_not_extract_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "voices.tgz"
            destination = Path(directory) / smoke.VOICE
            with tarfile.open(archive, "w:gz") as output:
                for name, value in (("voices/" + smoke.VOICE, b"embedding"), ("../foreign", b"attacker")):
                    info = tarfile.TarInfo(name); info.size = len(value)
                    output.addfile(info, io.BytesIO(value))
            smoke.extract_voice(archive, destination)
            self.assertEqual(destination.read_bytes(), b"embedding")
            self.assertFalse((Path(directory).parent / "foreign").exists())
            with tarfile.open(archive, "w:gz") as output:
                link = tarfile.TarInfo("voices/" + smoke.VOICE); link.type = tarfile.SYMTYPE; link.linkname = "/etc/passwd"
                output.addfile(link)
            with self.assertRaises(RuntimeError): smoke.extract_voice(archive, destination)

    def test_missing_credential_has_only_fixed_prerequisite_error(self):
        with patch.object(smoke, "existing_token", side_effect=RuntimeError("private-sentinel")), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(smoke.main(["--check-access"]), 2)
        self.assertNotIn("private-sentinel", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["status"], "blocked")

    def test_one_bounded_input_is_cancelled_and_container_terminated_on_failure_or_client_timeout(self):
        for timeout in (False, True):
            job = Mock()
            if timeout: job.get.side_effect = TimeoutError("private-diagnostic")
            else: job.get.return_value = {"status": "failed", "stage": "inference", "reason": "Fixed failure."}
            function = Mock(); function.spawn.return_value = job
            app = Mock(); app.run.return_value = contextlib.nullcontext()
            with patch.object(smoke, "existing_token", return_value="private-sentinel"), patch.object(smoke, "check_access", return_value=302), patch.object(smoke, "build_app", return_value=(app, function)), patch.object(smoke, "write_failure", return_value=Path("safe-report.json")), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(smoke.main(["--execute"]), 1)
            function.spawn.assert_called_once_with()
            job.get.assert_called_once_with(timeout=675)
            job.cancel.assert_called_once_with(terminate_containers=True)
            app.run.assert_called_once_with(detach=False)
            self.assertNotIn("private", output.getvalue())

    def test_diagnostics_recognize_runtime_mismatch_without_forwarding_private_message(self):
        InvalidError = type("InvalidError", (Exception,), {})
        error = InvalidError("serialized=True Python3.13 must be compatible with image Python3.11; private-token https://provider.example/?signed=secret")
        self.assertEqual(smoke.diagnostic(error, "app_start"), {"stage": "app_start", "failure_code": "client_python_incompatible", "error_class": "InvalidError"})
        self.assertNotIn("private", json.dumps(smoke.diagnostic(error, "app_start")))


if __name__ == "__main__":
    unittest.main()
