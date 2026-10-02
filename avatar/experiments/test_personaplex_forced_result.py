"""Prepared experiment checks, without importing model dependencies or Modal."""
import contextlib
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import personaplex_forced_result as experiment
from personaplex_pcm_core import FRAME_BYTES, FRAME_SAMPLES, MAX_PLAN_FRAMES


def fixed_encoder(word):
    # Deterministic lexical stand-in; real worker uses the pinned SentencePiece.
    return [10 + len(word), 100 + ord(word[0])]


class PreparedExperimentTests(unittest.TestCase):
    def test_absolute_source_entrypoint_imports_from_unrelated_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.run([sys.executable, str(Path(experiment.__file__).resolve()), "--plan"],
                                     cwd=directory, capture_output=True, text=True, timeout=5)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["status"], "prepared_not_dispatched")

    def test_default_plan_never_accesses_credentials_network_or_modal(self):
        output = io.StringIO()
        with patch.object(experiment.base, "existing_token", side_effect=AssertionError("credential")), \
             patch.object(experiment.base, "check_access", side_effect=AssertionError("network")), \
             patch.object(experiment, "build_app", side_effect=AssertionError("cloud")), \
             contextlib.redirect_stdout(output):
            self.assertEqual(experiment.main([]), 0)
        plan = json.loads(output.getvalue())
        self.assertEqual(plan["status"], "prepared_not_dispatched")
        self.assertFalse(plan["banking_access"])
        self.assertFalse(plan["persistent_service"])
        self.assertEqual(plan["source_revision"], experiment.base.SOURCE_REVISION)
        self.assertEqual(plan["model_revision"], experiment.base.MODEL_REVISION)
        self.assertEqual(plan["timeout_seconds"], 600)
        self.assertLessEqual(plan["clock"]["max_seconds"], 41)

    def test_explicit_word_pad_and_end_padding_schedule(self):
        candidate = experiment.candidate_plan(fixed_encoder)
        self.assertEqual(len(candidate.words), len(experiment.PUBLIC_REPLY.split()))
        for word in candidate.words:
            schedule = candidate.tokens[word["start_frame"]:word["end_frame_exclusive"]]
            pads = experiment.SENTENCE_PAD_FRAMES if word["word"].endswith(".") else experiment.WORD_PAD_FRAMES
            self.assertEqual(schedule, tuple(fixed_encoder(word["word"]) + [3] * pads + [0]))
        self.assertLessEqual(len(candidate.tokens), MAX_PLAN_FRAMES)

    def test_candidate_rejects_special_or_unbounded_lexical_tokens(self):
        for lexical in ([], [0], [1], [2], [3], [32_000], [True], [4] * MAX_PLAN_FRAMES):
            with self.subTest(lexical=lexical), self.assertRaises(ValueError):
                experiment.candidate_plan(lambda word: lexical)

    def test_timeline_preserves_public_audio_and_fixed_silence_clock(self):
        candidate = experiment.candidate_plan(fixed_encoder)
        prelude = struct.pack("<h", 1000) * (experiment.PRELUDE_FRAMES * FRAME_SAMPLES)
        continuation = struct.pack("<h", -2000) * (experiment.CONTINUATION_FRAMES * FRAME_SAMPLES)
        labels, pcm = experiment.build_timeline(prelude + continuation, candidate)
        start = labels.index("forced_public_reply")
        after = labels.index("continuation")
        self.assertEqual(start, experiment.PRELUDE_FRAMES + experiment.READY_SILENCE_FRAMES)
        self.assertEqual(labels.count("forced_public_reply"), len(candidate.tokens))
        self.assertEqual(pcm[:len(prelude)], prelude)
        self.assertEqual(pcm[after * FRAME_BYTES:after * FRAME_BYTES + len(continuation)], continuation)
        self.assertFalse(any(pcm[start * FRAME_BYTES:after * FRAME_BYTES]))
        self.assertEqual(len(pcm), len(labels) * FRAME_BYTES)

    def test_one_continuous_callback_receives_forced_tokens_then_free_audio(self):
        candidate = experiment.candidate_plan(fixed_encoder)
        public = struct.pack("<h", 1000) * ((experiment.PRELUDE_FRAMES + experiment.CONTINUATION_FRAMES) * FRAME_SAMPLES)
        labels, pcm = experiment.build_timeline(public, candidate)
        calls = []

        def fake_model(raw_frame, forced):
            calls.append((raw_frame, forced))
            return {"lm_offset_before": len(calls) - 1, "lm_offset_after": len(calls)}

        records = experiment.run_timeline(labels, pcm, candidate, fake_model)
        start = labels.index("forced_public_reply")
        end = start + len(candidate.tokens)
        self.assertEqual([forced for _, forced in calls[start:end]], list(candidate.tokens))
        self.assertTrue(all(forced is None for _, forced in calls[:start] + calls[end:]))
        continuation = labels.index("continuation")
        self.assertTrue(any(calls[continuation][0]))
        self.assertEqual(len(calls), len(labels))
        self.assertEqual([record["lm_offset_after"] for record in records], list(range(1, len(labels) + 1)))
        self.assertEqual(b"".join(raw for raw, _ in calls), pcm)

    def test_output_profile_is_pcm16_mono24k_and_bounded(self):
        value = experiment.wav_bytes(bytes(FRAME_BYTES * 2))
        profile = experiment.pcm_profile(value)
        self.assertEqual(profile["seconds"], 0.16)
        self.assertEqual((profile["sample_rate"], profile["channels"], profile["sample_width_bytes"]), (24000, 1, 2))
        with self.assertRaises(ValueError):
            experiment.pcm_profile(experiment.wav_bytes(bytes((experiment.MAX_CLOCK_FRAMES + 2) * FRAME_BYTES)))
        with self.assertRaises(ValueError):
            experiment.build_timeline(b"\x00", experiment.candidate_plan(fixed_encoder))

    def test_contiguous_token_evidence_does_not_match_missing_or_reordered_ids(self):
        self.assertEqual(experiment.exact_subsequence([9, 40, 3, 0, 41, 8], (40, 3, 0, 41)), 1)
        self.assertIsNone(experiment.exact_subsequence([40, 3, 41], (40, 3, 0, 41)))
        self.assertIsNone(experiment.exact_subsequence([40, 0, 3, 41], (40, 3, 0, 41)))

    def test_client_timeout_cancels_one_input_and_redacts_arbitrary_errors(self):
        calls = []

        class Job:
            def get(self, timeout):
                calls.append(("get", timeout))
                raise TimeoutError("private credential and signed-url detail")

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
        with patch.object(experiment.base, "existing_token", return_value="fake-existing-read-token"), \
             patch.object(experiment.base, "check_access", return_value=302), \
             patch.object(experiment, "build_app", return_value=(App(), Function())), \
             contextlib.redirect_stdout(output):
            self.assertEqual(experiment.main(["--execute"]), 1)
        self.assertEqual(sum(call[0] == "spawn" for call in calls), 1)
        self.assertIn(("get", 675), calls)
        self.assertIn(("cancel", True), calls)
        self.assertIn(("run", False), calls)
        self.assertNotIn("private", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["failure_code"], "deadline_exceeded")


if __name__ == "__main__":
    unittest.main()
