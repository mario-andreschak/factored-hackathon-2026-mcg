"""Offline review boundaries: read-only projection, honest unknowns and inert data."""
import hashlib
from contextlib import closing
import json
import runpy
from pathlib import Path
import sqlite3
import tempfile
import unittest

from analytics.extract import SCHEMA
from bank_review.__main__ import main
from bank_review.report import build_page, demo_packet, read_analytics


class BankReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "analytics.sqlite3"
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript(SCHEMA)
            db.executemany("INSERT INTO meta VALUES (?,?)", [("schema_version", "1"), ("built_at", "test-snapshot")])
            for index in range(4):
                db.execute("""INSERT INTO turns(turn_id,source,conversation_id,language,response_mode,
                    grounding_violation,handoff_required,handoff_created,customer_ref,slots_present)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (f"turn-{index}", "workflow", f"conversation-{index}", "es" if index % 2 else "pt",
                     "HANDOFF" if index == 1 else "INFORM", 1 if index == 3 else 0,
                     1 if index == 1 else None, None, "PRIVATE-CUSTOMER", '["PRIVATE-SLOT"]'))

    def test_projection_is_read_only_bounded_and_excludes_private_fields(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        packet = read_analytics(self.db, 2)
        self.assertEqual(packet["total_turns"], 4)
        self.assertEqual(len(packet["rows"]), 2)
        self.assertEqual(packet["rows"][0]["turn_id"], "turn-3")
        self.assertEqual(packet["languages"], {"es": 2, "pt": 2})
        self.assertEqual(before, hashlib.sha256(self.db.read_bytes()).hexdigest())
        self.assertNotIn("PRIVATE-CUSTOMER", json.dumps(packet))
        self.assertNotIn("PRIVATE-SLOT", json.dumps(packet))
        self.assertNotIn("customer_ref", packet["rows"][0])

    def test_missing_host_evidence_is_not_promoted_to_verified_handoff(self):
        row = next(row for row in read_analytics(self.db)["rows"] if row["turn_id"] == "turn-1")
        self.assertEqual(row["signals"], ["Human review requested"])
        self.assertIsNone(row["handoff_created"])
        self.assertIsNone(read_analytics(self.db)["comparison"])

    def test_empty_analytics_has_no_fabricated_results(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("DELETE FROM turns")
        packet = read_analytics(self.db)
        self.assertEqual(packet["rows"], [])
        self.assertEqual(packet["total_turns"], 0)
        self.assertIsNone(packet["comparison"])

    def test_schema_and_input_bounds_fail_closed(self):
        for limit in (0, 5001, True):
            with self.assertRaises(ValueError):
                read_analytics(self.db, limit)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE meta SET value='future' WHERE key='schema_version'")
        with self.assertRaisesRegex(ValueError, "unsupported analytics schema"):
            read_analytics(self.db)

    def test_untrusted_text_cannot_break_out_of_the_inert_json_script(self):
        packet = demo_packet()
        attack = '</script><script>alert("private")</script>&<img src=x onerror=alert(1)>'
        packet["rows"][0]["turn_id"] = attack
        page = build_page(packet)
        payload = page.split('<script id="review-data" type="application/json">', 1)[1].split('</script>', 1)[0]
        self.assertEqual(json.loads(payload)["rows"][0]["turn_id"], attack)
        self.assertNotIn(attack, page)
        self.assertNotIn("<", payload)
        self.assertIn("connect-src 'none'", page)

    def test_cli_refuses_to_overwrite_database_or_report(self):
        before = self.db.read_bytes()
        with self.assertRaises(SystemExit) as caught:
            main(["--analytics-db", str(self.db), "--out", str(self.db)])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.db.read_bytes(), before)
        output = self.root / "bank-review.html"
        main(["--demo", "--out", str(output)])
        original = output.read_bytes()
        with self.assertRaises(SystemExit):
            main(["--demo", "--out", str(output)])
        self.assertEqual(output.read_bytes(), original)

    def test_drafts_cannot_become_locked_comparison(self):
        draft = self.root / "drafts.json"
        draft.write_text(json.dumps({"schema": "bank-review-drafts/v1", "status": "draft_unadjudicated"}), encoding="utf-8")
        output = self.root / "report.html"
        with self.assertRaises(SystemExit) as caught:
            main(["--analytics-db", str(self.db), "--outcome-input", str(draft), "--out", str(output)])
        self.assertEqual(caught.exception.code, 2)
        self.assertFalse(output.exists())

    def test_demo_has_unknown_timings_and_no_evaluation(self):
        packet = demo_packet()
        self.assertEqual(packet["origin"], "fictional_walkthrough")
        self.assertEqual(packet["languages"], {"es": 4, "pt": 4})
        self.assertIsNone(packet["comparison"])
        self.assertTrue(all(row["node_latency_ms"] is None for row in packet["rows"]))

    def test_valid_comparison_uses_existing_scorer_and_preserves_unknown_cost(self):
        fixture = runpy.run_path(str(Path(__file__).with_name("test_report_customer_outcomes.py")))["fixture"]
        input_path = self.root / "locked.json"
        input_path.write_text(json.dumps(fixture()), encoding="utf-8")
        output = self.root / "comparison.html"
        main(["--analytics-db", str(self.db), "--outcome-input", str(input_path), "--out", str(output)])
        payload = output.read_text(encoding="utf-8").split('<script id="review-data" type="application/json">', 1)[1].split('</script>', 1)[0]
        packet = json.loads(payload)
        report = packet["comparison"]
        self.assertEqual(report["systems"]["proposed"]["overall"]["correct_handoff"], {"count": 1, "denominator": 1})
        self.assertEqual(report["systems"]["proposed"]["overall"]["cost_usd"]["per_attempt"]["status"], "unknown_cost")
        self.assertNotIn("cases", report)
        self.assertIn("not independently verified", report["qualification"])
        self.assertEqual(packet["comparison_failure_counts"]["baseline"]["overall"]["unresolved"], 2)
        self.assertEqual(packet["comparison_failure_counts"]["baseline"]["pt"]["unresolved"], 1)

    def test_demo_refuses_to_mix_with_locked_results(self):
        with self.assertRaises(SystemExit) as caught:
            main(["--demo", "--outcome-input", "unused.json", "--out", str(self.root / "demo.html")])
        self.assertEqual(caught.exception.code, 2)
        self.assertFalse((self.root / "demo.html").exists())


if __name__ == "__main__":
    unittest.main()
