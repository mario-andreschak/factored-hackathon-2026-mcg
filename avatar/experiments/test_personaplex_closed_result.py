"""Closed-reply qualification checks: stdlib only, no model/cloud/provider calls."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import personaplex_closed_result as experiment
from personaplex_pcm_core import FRAME_BYTES, FRAME_SAMPLES, MAX_PLAN_FRAMES


def encoder(word):
    return [100 + len(word), 200 + ord(word[0])]


def public_fixture():
    return (struct.pack("<h", 1000) * (experiment.PRELUDE_FRAMES * FRAME_SAMPLES)
            + struct.pack("<h", -2000) * (experiment.CONTINUATION_FRAMES * FRAME_SAMPLES))


def receipt(audio):
    return {"status": "completed", "experiment": experiment.EXPERIMENT,
            "synthetic_public_reply": experiment.PUBLIC_REPLY,
            "source_revision": experiment.pinned.SOURCE_REVISION, "model_revision": experiment.pinned.MODEL_REVISION,
            "forced_output_ids_match": True, "gate_permanently_closed": True,
            "continuous_lm_cache_preserved": True, "post_reply_public_audio_frames": 0,
            "post_reply_public_caption_tokens": 0, "banking_access": False, "production_enabled": False,
            "public_audio_sha256": hashlib.sha256(audio).hexdigest(), "public_audio_frames": 2}


class ClosedResultTests(unittest.TestCase):
    def test_default_plan_reads_no_cache_credentials_modal_or_network(self):
        output = io.StringIO()
        with patch.object(experiment, "cache_reference", side_effect=AssertionError("cache")), \
             patch.object(experiment.pinned, "existing_token", side_effect=AssertionError("HF credential")), \
             patch.object(experiment.pinned, "check_access", side_effect=AssertionError("HF network")), \
             patch.object(experiment, "existing_openrouter_key", side_effect=AssertionError("ASR credential")), \
             patch.object(experiment, "build_app", side_effect=AssertionError("cloud")), \
             contextlib.redirect_stdout(output):
            self.assertEqual(experiment.main([]), 0)
        plan = json.loads(output.getvalue())
        self.assertEqual(plan["status"], "prepared_not_dispatched")
        self.assertEqual(plan["timeout_seconds"], 600)
        self.assertEqual(plan["max_containers"], 1)
        self.assertEqual(plan["retries"], 0)
        self.assertFalse(plan["banking_access"])
        self.assertFalse(plan["production_enabled"])
        self.assertFalse(plan["pronunciation_verified"])
        self.assertNotIn("Mira", plan["fixed_synthetic_reply"])
        self.assertGreater(plan["schedule"]["word_pad3_frames"], experiment.prior.WORD_PAD_FRAMES)

    def test_absolute_entrypoint_plan_needs_no_repository_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.run([sys.executable, str(Path(experiment.__file__).resolve()), "--plan"],
                                     cwd=directory, capture_output=True, text=True, timeout=5)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["experiment"], experiment.EXPERIMENT)

    def test_exact_source_overlay_imports_without_original_checkout_transitive_modules(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as unrelated:
            stage = Path(directory)
            source = Path(experiment.__file__).parent
            for module in experiment.SOURCE_MODULES:
                shutil.copyfile(source / (module + ".py"), stage / (module + ".py"))
            clean_env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
            process = subprocess.run([sys.executable, str(stage / "personaplex_closed_result.py"), "--plan"],
                                     cwd=unrelated, env=clean_env, capture_output=True, text=True, timeout=5)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["status"], "prepared_not_dispatched")

    def test_reply_pacing_and_explicit_forced_tail_fit_native_plan_bound(self):
        candidate = experiment.candidate_plan(encoder)
        for word in candidate.words:
            expected_pad = 10 if word["word"].endswith(".") else 4
            self.assertEqual(candidate.tokens[word["start_frame"]:word["end_frame_exclusive"]],
                             tuple(encoder(word["word"]) + [3] * expected_pad + [0]))
        self.assertEqual(candidate.tokens[candidate.reply_frames:], tuple([3] * 16 + [0]))
        self.assertEqual(candidate.phoneme_tail_frames, 17)
        self.assertLessEqual(len(candidate.tokens), MAX_PLAN_FRAMES)
        for bad in ([], [1], [2], [3], [True], [32_000], [10] * MAX_PLAN_FRAMES):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                experiment.candidate_plan(lambda word: bad)

    def test_closed_gate_suppresses_free_future_promise_and_next_user_input_without_reset(self):
        candidate = experiment.candidate_plan(encoder)
        labels, pcm = experiment.build_timeline(public_fixture(), candidate)
        calls, history = [], []
        delay = 2

        def fake_model(raw, forced):
            index = len(calls)
            calls.append((raw, forced))
            history.append(forced if forced is not None else 700)
            text_id = history[index - delay] if index >= delay else 700
            return {"pcm": struct.pack("<h", index + 1) * FRAME_SAMPLES,
                    "model_text_id": text_id, "model_text_piece": "No action will be taken.",
                    "continuous_cache_preserved": True, "lm_offset_before": 100 + index,
                    "lm_offset_after": 101 + index, "frame_total_ms": 1.0}

        result = experiment.run_timeline(labels, pcm, candidate, fake_model, delay)
        start, end = result.first_output_frame, result.end_output_frame
        self.assertEqual(start, labels.index("forced_reply") + delay)
        self.assertEqual(end - start, len(candidate.tokens))
        self.assertEqual(b"".join(raw for raw, _ in calls), pcm)
        self.assertEqual([r["lm_offset_after"] for r in result.records], list(range(101, 101 + len(labels))))
        self.assertFalse(any(result.gated_pcm[:start * FRAME_BYTES]))
        self.assertFalse(any(result.gated_pcm[end * FRAME_BYTES:]))
        self.assertEqual(result.closed_reply_pcm, result.native_pcm[start * FRAME_BYTES:end * FRAME_BYTES])
        self.assertEqual(result.discarded_continuation_pcm, result.native_pcm[end * FRAME_BYTES:])
        self.assertTrue(any(result.discarded_continuation_pcm))
        self.assertTrue(all(not r["public_output"] for r in result.records[end:]))
        next_input = labels.index("closed_next_input")
        self.assertTrue(any(calls[next_input][0]))
        self.assertTrue(all(forced is None for _, forced in calls[next_input:]))
        self.assertTrue(all(not r["public_output"] for r in result.records[next_input:]))
        self.assertIn("No action will be taken.", result.records[next_input]["model_text_piece"])

    def test_gate_cannot_reopen_from_later_matching_tokens_and_rejects_bad_clocks(self):
        candidate = experiment.candidate_plan(encoder)
        gate = experiment.ClosedOutputGate(candidate, 1, 2)
        self.assertFalse(gate.consider(0, 999))
        self.assertFalse(gate.consider(1, 999))
        self.assertFalse(gate.consider(2, 999))
        for index, token in enumerate(candidate.tokens, start=3):
            self.assertTrue(gate.consider(index, token))
        self.assertTrue(gate.closed)
        self.assertFalse(gate.consider(gate.end_output, candidate.tokens[0]))
        self.assertFalse(gate.consider(gate.end_output + 1, candidate.tokens[1]))
        with self.assertRaises(ValueError):
            gate.consider(gate.end_output + 3, candidate.tokens[0])
        for bad in (-1, True, 17, 1000):
            with self.subTest(delay=bad), self.assertRaises(ValueError):
                experiment.ClosedOutputGate(candidate, 1, bad)

    def test_caption_token_mismatch_closes_before_any_public_frame_is_admitted(self):
        candidate = experiment.candidate_plan(encoder)
        gate = experiment.ClosedOutputGate(candidate, 1, 0)
        self.assertFalse(gate.consider(0, 700))
        with self.assertRaises(ValueError):
            gate.consider(1, 700)
        self.assertTrue(gate.closed)
        self.assertEqual(gate.accepted, 0)

    def test_native_partial_frame_or_changed_cache_fails_instead_of_exporting_a_reply(self):
        candidate = experiment.candidate_plan(encoder)
        labels, pcm = experiment.build_timeline(public_fixture(), candidate)
        for result in ({"pcm": b"\0\0", "continuous_cache_preserved": True, "model_text_id": 3},
                       {"pcm": bytes(FRAME_BYTES), "continuous_cache_preserved": False, "model_text_id": 3}):
            with self.subTest(result=len(result["pcm"])), self.assertRaises(ValueError):
                experiment.run_timeline(labels, pcm, candidate, lambda raw, forced: result, 0)
        with self.assertRaises(ValueError):
            experiment.build_timeline(b"\0", candidate)

    def test_missing_cached_reference_stops_before_cloud_definition_and_never_checks_HF(self):
        output = io.StringIO()
        with patch.object(experiment, "cache_reference", side_effect=ValueError("private image detail")), \
             patch.object(experiment, "build_app", side_effect=AssertionError("cloud")), \
             patch.object(experiment.pinned, "existing_token", side_effect=AssertionError("HF")), \
             patch.object(experiment.pinned, "check_access", side_effect=AssertionError("network")), \
             contextlib.redirect_stdout(output):
            self.assertEqual(experiment.main(["--execute"]), 1)
        self.assertNotIn("private image detail", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["stage"], "cached_image_reference")

    def test_definition_reuses_private_image_without_secrets_downloads_or_persistent_workers(self):
        calls = {}

        class Image:
            @classmethod
            def from_id(cls, reference):
                calls["reference"] = reference
                return cls()

            def add_local_python_source(self, *modules, **kwargs):
                calls["modules"], calls["copy"] = modules, kwargs
                return self

        class App:
            def __init__(self, name):
                calls["name"] = name

            def function(self, **kwargs):
                calls["function"] = kwargs
                return lambda function: function

        with patch.dict(sys.modules, {"modal": types.SimpleNamespace(Image=Image, App=App)}), \
             patch.object(experiment.pinned, "build_image", side_effect=AssertionError("new weight image")):
            _, function = experiment.build_app("im-existingPrivateCache")
        self.assertIs(function, experiment.gpu_closed_result)
        self.assertEqual(calls["reference"], "im-existingPrivateCache")
        self.assertEqual(calls["copy"], {"copy": True})
        self.assertIn("modal_diagnostic", calls["modules"])
        self.assertEqual(calls["function"]["gpu"], "A100-80GB")
        self.assertEqual(calls["function"]["timeout"], 600)
        self.assertEqual(calls["function"]["max_containers"], 1)
        self.assertEqual(calls["function"]["min_containers"], 0)
        self.assertEqual(calls["function"]["retries"], 0)
        self.assertFalse(calls["function"]["serialized"])
        self.assertNotIn("secrets", calls["function"])

    def test_timeout_cancels_one_input_and_never_reflects_provider_detail(self):
        calls = []

        class Job:
            def get(self, timeout):
                calls.append(("get", timeout))
                raise TimeoutError("secret signed-url detail")

            def cancel(self, terminate_containers):
                calls.append(("cancel", terminate_containers))

        class Function:
            def spawn(self):
                calls.append(("spawn",))
                return Job()

        class App:
            def run(self, detach):
                calls.append(("run", detach))
                return self

            def __enter__(self):
                return self

            def __exit__(self, *args):
                calls.append(("exit",))

        output = io.StringIO()
        with patch.object(experiment, "cache_reference", return_value="im-fixed"), \
             patch.object(experiment, "build_app", return_value=(App(), Function())), \
             contextlib.redirect_stdout(output):
            self.assertEqual(experiment.main(["--execute"]), 1)
        self.assertEqual(calls.count(("spawn",)), 1)
        self.assertIn(("get", 675), calls)
        self.assertIn(("cancel", True), calls)
        self.assertIn(("run", False), calls)
        self.assertNotIn("secret", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["failure_code"], "deadline_exceeded")

    def test_existing_key_reads_plain_and_BOM_ignored_env_without_printing(self):
        fake_key = "test-only-authorized-key-1234"
        for bom in (False, True):
            with self.subTest(bom=bom), tempfile.TemporaryDirectory() as directory, \
                 patch.object(experiment, "ROOT", Path(directory)), \
                 patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
                content = '# Local test fixture only\nOPENROUTER_API_KEY="' + fake_key + '"\n'
                (Path(directory) / "openrouter.env").write_bytes(
                    (b"\xef\xbb\xbf" if bom else b"") + content.encode("utf-8"))
                output = io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    self.assertEqual(experiment.existing_openrouter_key(), fake_key)
                self.assertEqual(output.getvalue(), "")

    def test_independent_ASR_requires_completed_hashed_gate_evidence_before_reading_key(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(experiment, "DIRECTORY", Path(directory)), \
             patch.object(experiment, "existing_openrouter_key", side_effect=AssertionError("provider key")):
            result = Path(directory) / "completed"
            result.mkdir()
            audio = experiment.prior.wav_bytes(bytes(FRAME_BYTES * 2))
            (result / "closed-result.wav").write_bytes(audio)
            report = receipt(audio)
            report["gate_permanently_closed"] = False
            (result / "report.json").write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                experiment.verify_asr(result)
            report["gate_permanently_closed"] = True
            report["public_audio_sha256"] = "wrong"
            (result / "report.json").write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                experiment.verify_asr(result)
            with self.assertRaises(ValueError):
                experiment.verify_asr(Path(directory).parent / "other-recording")

    def test_ASR_compares_exact_amount_and_status_and_rejects_unsupported_continuation(self):
        for text in (experiment.PUBLIC_REPLY,
                     "The payment amount is $42.17. There is no open dispute. No action was taken.",
                     "The payment amount is forty-two dollars and seventeen cents. There is no open dispute. No action was taken."):
            with self.subTest(text=text):
                verdict = experiment.asr_verdict(text)
                self.assertEqual(verdict["status"], "synthetic_asr_passed")
                self.assertTrue(verdict["exact_propositions_without_extra_text"])
                self.assertFalse(verdict["human_listening_verified"])
                self.assertFalse(verdict["production_bank_narration_enabled"])
        for text in (experiment.PUBLIC_REPLY + " No action will be taken.",
                     experiment.PUBLIC_REPLY.replace("forty two", "forty three"),
                     experiment.PUBLIC_REPLY.replace("no open dispute", "an open dispute"),
                     experiment.PUBLIC_REPLY.replace("No action was taken", "A refund was issued")):
            with self.subTest(text=text):
                self.assertEqual(experiment.asr_verdict(text)["status"], "synthetic_asr_failed")

    def test_existing_ASR_receipt_prevents_another_paid_request_before_reading_key(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(experiment, "validated_asr_audio", return_value=b"approved-synthetic-WAV"), \
             patch.object(experiment, "existing_openrouter_key", side_effect=AssertionError("provider key")), \
             patch.object(experiment.urllib.request, "build_opener", side_effect=AssertionError("repeat request")):
            (Path(directory) / "private-asr.json").write_text("{}")
            with self.assertRaises(ValueError):
                experiment.verify_asr(Path(directory))

    def test_ASR_sends_only_approved_synthetic_WAV_once_to_fixed_no_redirect_endpoint(self):
        calls = []
        audio = experiment.prior.wav_bytes(bytes(FRAME_BYTES * 2))

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self, size):
                calls.append(("read", size))
                return json.dumps({"text": experiment.PUBLIC_REPLY}).encode()

        class Opener:
            def open(self, request, timeout):
                calls.append((request, timeout))
                return Response()

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(experiment, "validated_asr_audio", return_value=audio), \
             patch.object(experiment, "existing_openrouter_key", return_value="fake-authorized-key"), \
             patch.object(experiment.urllib.request, "build_opener", return_value=Opener()) as opener:
            verdict = experiment.verify_asr(Path(directory))
            saved = json.loads((Path(directory) / "private-asr.json").read_text())
        self.assertEqual(verdict["status"], "synthetic_asr_passed")
        self.assertEqual(len([call for call in calls if not isinstance(call[0], str)]), 1)
        request, timeout = calls[0]
        self.assertEqual(request.full_url, "https://openrouter.ai/api/v1/audio/transcriptions")
        self.assertEqual(timeout, 45)
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], "openai/whisper-large-v3")
        self.assertEqual(payload["language"], "en")
        self.assertEqual(payload["input_audio"]["format"], "wav")
        redirect_handler = opener.call_args.args[0]
        if isinstance(redirect_handler, type):
            redirect_handler = redirect_handler()
        self.assertIsInstance(redirect_handler, experiment.pinned.NoRedirect)
        self.assertIsNone(redirect_handler.redirect_request(None, None, 302, "Found", {}, "https://other.example/"))
        self.assertNotIn("fake-authorized-key", json.dumps(saved))

    def test_GPU_preflight_rejects_mounted_HF_secret_without_any_download(self):
        with patch.dict(experiment.os.environ, {"HF_TOKEN": "fake-disallowed-runtime-token"}), \
             patch.object(experiment.subprocess, "run", side_effect=AssertionError("runtime network or worker")):
            result = experiment.gpu_closed_result()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["stage"], "offline_cache")
        self.assertNotIn("fake-disallowed-runtime-token", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
