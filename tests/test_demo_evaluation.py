"""Frozen evaluation identity, independent authorship and reporting scope."""
import tempfile
import unittest
from pathlib import Path

from demo.evaluate_router import HOLDOUT, frozen_cases


class EvaluationIdentityTests(unittest.TestCase):
    def test_frozen_diagnostic_mix_and_authorship(self):
        cases = frozen_cases()
        self.assertEqual(len(cases), 120)
        self.assertEqual(sum(row["lang"] == "pt" for row in cases), 60)

    def test_any_byte_change_rejected_before_model_evaluation(self):
        with tempfile.TemporaryDirectory(prefix="router-freeze-") as temporary:
            path = Path(temporary) / "tampered.csv"
            path.write_bytes(HOLDOUT.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "holdout_hash_mismatch"):
                frozen_cases(path)


if __name__ == "__main__":
    unittest.main()
