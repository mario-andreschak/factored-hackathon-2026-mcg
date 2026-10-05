"""Ensure source outage/retention cannot undo the snapshot start date."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_dev_history as builder


CAPTURE = "2026-10-01T04:00:00Z"


def event(identity, time):
    return {"id": identity, "source": "github", "timestamp": time,
            "body": identity, "metadata": {}}


def snapshot():
    return {"status": "ok", "events": [
        event("earlier", "2026-09-25T04:59:59.999999Z"),
        event("friday", "2026-09-25T05:00:00Z")], "stats": {"events": 2}}


class HistoryScopePipelineTests(unittest.TestCase):
    def test_offline_and_live_outage_purge_old_cache_without_changing_capture_time(self):
        for offline in (True, False):
            with self.subTest(offline=offline), tempfile.TemporaryDirectory() as directory:
                cache = Path(directory)
                file = cache / "github.json"
                builder.atomic_json(file, {"collectedAt": CAPTURE, "result": snapshot()})
                failure = AssertionError("No live collector during offline replay") if offline else RuntimeError("Source outage")
                with patch.object(builder.importlib, "import_module", side_effect=failure):
                    result = builder.source_result("github", {}, cache, offline)
                self.assertEqual([row["id"] for row in result["events"]], ["friday"])
                saved = json.loads(file.read_text(encoding="utf-8"))
                self.assertEqual(saved["collectedAt"], CAPTURE)
                self.assertEqual([row["id"] for row in saved["result"]["events"]], ["friday"])
                self.assertEqual(saved["result"]["scopeExcludedEventIds"], ["earlier"])

    def test_live_refresh_and_retention_both_obey_start_date(self):
        fresh = {"status": "ok", "events": [
            event("fresh-earlier", "2026-09-24T23:00:00-05:00"),
            event("fresh-friday", "2026-09-25T00:00:01-05:00")], "notes": []}
        collector = SimpleNamespace(collect=lambda *_: copy.deepcopy(fresh))
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            builder.atomic_json(cache / "github.json", {"collectedAt": CAPTURE, "result": snapshot()})
            with patch.object(builder.importlib, "import_module", return_value=collector):
                result = builder.source_result("github", {}, cache, False)
            self.assertEqual({row["id"] for row in result["events"]}, {"friday", "fresh-friday"})
            retained = next(row for row in result["events"] if row["id"] == "friday")
            self.assertTrue(retained["metadata"]["retainedFromPriorCapture"])
            self.assertEqual(retained["metadata"]["lastCapturedAt"], CAPTURE)
            self.assertEqual(result["stats"]["retainedEvents"], 1)
            self.assertEqual(set(result["scopeExcludedEventIds"]), {"earlier", "fresh-earlier"})


if __name__ == "__main__":
    unittest.main()
