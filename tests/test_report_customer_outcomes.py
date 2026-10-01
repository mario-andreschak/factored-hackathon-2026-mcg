import copy
import unittest

from scripts.report_customer_outcomes import InputError, aggregate


def fixture():
    cases = [
        {"case_id": "ES-1", "language": "es", "labels": {
            "review_status": "human_reviewed_locked", "expected_route": "inquiry",
            "requires_handoff": False, "in_scope": True}},
        {"case_id": "PT-1", "language": "pt", "labels": {
            "review_status": "human_reviewed_locked", "expected_route": "human",
            "requires_handoff": True, "in_scope": True}},
    ]

    def attempt(case_id, system, outcome, latency, cost):
        return {"case_id": case_id, "system": system, "repeat": 1,
                "actual_outcome": outcome, "automation_attempted": True,
                "authorized_dispatch": False, "safe_inquiry_resolution": outcome == "safe_inquiry",
                "intake_completed": False, "transferred": outcome == "correct_handoff",
                "handoff_packet_complete": outcome == "correct_handoff",
                "unsafe_outcome": outcome == "unsafe", "latency_ms": latency,
                "cost_usd": cost, "cost_basis": "unknown" if cost is None else "measured"}
    return {
        "schema": "customer-outcomes/v1",
        "provenance": {"source_sha": "a" * 40, "fixture_id": "fictional",
                       "fixture_version": "v1", "data_origin": "team_generated_synthetic",
                       "evidence_tier": "source_mock", "trace_reference": "private/mock"},
        "lock": {"workload_id": "locked-1", "case_set_sha256": "a" * 64,
                 "locked_at_utc": "2026-10-01T00:00:00Z", "rubric_version": "v1",
                 "status": "human_reviewed_locked", "reviewers": ["reviewer-A", "reviewer-B"]},
        "cases": cases,
        "attempts": [attempt("ES-1", "baseline", "unresolved", 10, None),
                     attempt("PT-1", "baseline", "unresolved", 20, None),
                     attempt("ES-1", "proposed", "safe_inquiry", 30, 0.01),
                     attempt("PT-1", "proposed", "correct_handoff", 40, None)],
    }


class OutcomeReportTests(unittest.TestCase):
    def test_denominators_latency_failure_unknown_cost_and_handoff(self):
        report = aggregate(fixture())
        base = report["systems"]["baseline"]["overall"]
        proposed = report["systems"]["proposed"]["overall"]
        self.assertEqual(base["safe_inquiry_resolution"], {"count": 0, "denominator": 2})
        self.assertEqual(base["cost_usd"]["per_safe_resolution"]["status"], "undefined_no_success")
        self.assertEqual(base["latency_ms"]["p95"], 19.5)
        self.assertEqual(proposed["safe_inquiry_resolution"], {"count": 1, "denominator": 2})
        self.assertEqual(proposed["correct_handoff"], {"count": 1, "denominator": 1})
        self.assertEqual(proposed["cost_usd"]["unknown_count"], 1)
        self.assertEqual(proposed["cost_usd"]["per_safe_resolution"]["status"], "unknown_cost")
        self.assertEqual(report["systems"]["proposed"]["es"]["attempts"], 1)

    def test_missing_pair_duplicate_and_unlocked_labels_rejected(self):
        for change in ("missing", "duplicate", "unlocked"):
            data = fixture()
            if change == "missing":
                data["attempts"].pop()
            elif change == "duplicate":
                data["attempts"].append(copy.deepcopy(data["attempts"][0]))
            else:
                data["lock"]["status"] = "draft"
            with self.subTest(change=change), self.assertRaises(InputError):
                aggregate(data)

    def test_missing_fields_receipt_and_unknown_cost_rejected(self):
        for change in ("outcome", "latency", "cost", "receipt"):
            data = fixture()
            row = data["attempts"][2]
            if change == "receipt":
                row["actual_outcome"] = "verified_simulated_intake"
                row["safe_inquiry_resolution"] = False
                row["intake_completed"] = True
            elif change == "cost":
                row["cost_usd"] = 0
                row["cost_basis"] = "unknown"
            else:
                del row["actual_outcome" if change == "outcome" else "latency_ms"]
            with self.subTest(change=change), self.assertRaises(InputError):
                aggregate(data)

    def test_incomplete_handoff_packet_is_missed(self):
        data = fixture()
        data["attempts"][3]["handoff_packet_complete"] = False
        data["attempts"][3]["actual_outcome"] = "unresolved"
        metrics = aggregate(data)["systems"]["proposed"]["pt"]
        self.assertEqual(metrics["correct_handoff"], {"count": 0, "denominator": 1})
        self.assertEqual(metrics["missed_handoff"], {"count": 1, "denominator": 1})

    def test_repeats_are_complete_and_visible_separately(self):
        data = fixture()
        repeat_two = copy.deepcopy(data["attempts"])
        for row in repeat_two:
            row["repeat"] = 2
        data["attempts"].extend(repeat_two)
        report = aggregate(data)
        self.assertEqual(report["systems"]["proposed"]["overall"]["attempts"], 4)
        self.assertEqual(report["systems"]["proposed"]["by_repeat"]["2"]["es"]["attempts"], 1)
        data["attempts"].pop()
        with self.assertRaises(InputError):
            aggregate(data)

    def test_receipt_must_match_all_bound_fields(self):
        data = fixture()
        row = data["attempts"][2]
        row["actual_outcome"] = "verified_simulated_intake"
        row["safe_inquiry_resolution"] = False
        row["intake_completed"] = True
        row["receipt_readback"] = {key: True for key in
                                  ("verified", "owner_match", "session_match", "query_match",
                                   "target_match", "snapshot_match")}
        self.assertEqual(aggregate(data)["systems"]["proposed"]["es"]["verified_simulated_intake"]["count"], 1)
        row["receipt_readback"]["owner_match"] = False
        with self.assertRaises(InputError):
            aggregate(data)


if __name__ == "__main__":
    unittest.main()
