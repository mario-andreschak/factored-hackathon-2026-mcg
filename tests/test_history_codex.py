"""Fixture-based checks for local Codex history completeness and boundaries."""

from pathlib import Path
from contextlib import closing
import json
import sqlite3
import tempfile
import unittest

from scripts.history_sources.codex import collect, _inside, _utc, _time_key


def record(timestamp, kind, payload, ordinal=0):
    return {"timestamp": timestamp, "type": kind, "payload": payload, "ordinal": ordinal}


def message(timestamp, identity, role, text, phase=None, ordinal=1):
    payload = {"type": "message", "id": identity, "role": role, "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}]}
    if phase:
        payload["phase"] = phase
    return record(timestamp, "response_item", payload, ordinal)


class CodexHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.repo, self.home = root / "project", root / "codex"
        self.repo.mkdir()
        self.home.mkdir()

    def rollout(self, identity, entries, cwd=None, archived=False, **meta):
        directory = self.home / ("archived_sessions" if archived else "sessions")
        directory.mkdir(exist_ok=True)
        path = directory / f"rollout-{identity}.jsonl"
        payload = {"id": identity, "timestamp": "2026-09-25T22:00:00.000Z", "cwd": str(cwd or self.repo), **meta}
        data = [record(payload["timestamp"], "session_meta", payload), *entries]
        path.write_text("\n".join(json.dumps(value) for value in data) + "\n", encoding="utf-8")
        return path

    def collect(self, **options):
        return collect(self.repo, {"codex": {"home": str(self.home), "user_actor": "Test developer", **options}})

    def test_full_messages_projections_privacy_and_stable_rebuild(self):
        long_text = "All visible details survive.\n" * 2000
        credential = "ghp_" + "Z" * 36
        path = self.rollout("main", [
            message("2026-09-25T22:00:01.000Z", "ambient", "user", f"<environment_context><cwd>{self.repo}</cwd></environment_context>"),
            message("2026-09-25T22:00:02.123456789Z", "request", "user", 'Build the timeline. access_token="' + credential + '"'),
            record("2026-09-25T22:00:02.130Z", "event_msg", {"type": "item_completed", "turn_id": "turn1", "item": {"type": "UserMessage", "id": "ui-request", "content": [{"type": "text", "text": 'Build the timeline. access_token="' + credential + '"'}]}}),
            message("2026-09-25T22:00:03.000Z", "hidden-system", "system", "SYSTEM PRIVATE"),
            message("2026-09-25T22:00:03.000Z", "hidden-developer", "developer", "DEVELOPER PRIVATE"),
            message("2026-09-25T22:00:03.000Z", "hidden-analysis", "assistant", "HIDDEN REASONING", "analysis"),
            record("2026-09-25T22:00:03.000Z", "response_item", {"type": "reasoning", "summary": "HIDDEN REASONING"}),
            record("2026-09-25T22:00:04.000Z", "event_msg", {"type": "item_completed", "item": {"type": "AgentMessage", "id": "answer", "phase": "final_answer", "content": [{"type": "Text", "text": long_text}]}}),
            message("2026-09-25T22:00:04.010Z", "answer", "assistant", long_text, "final_answer"),
            record("2026-09-25T22:00:04.020Z", "event_msg", {"type": "task_complete", "last_agent_message": long_text}),
            record("2026-09-25T22:00:05.000Z", "response_item", {"type": "custom_tool_call", "call_id": "call1", "name": "functions.exec", "input": "SECRET TOOL INPUT"}),
            record("2026-09-25T22:00:06.000Z", "response_item", {"type": "custom_tool_call_output", "call_id": "call1", "output": "SECRET TOOL OUTPUT"}),
        ])
        first = self.collect(include_tools=True)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(len(first["events"]), 3)
        request = next(event for event in first["events"] if event["kind"] == "user_message")
        answer = next(event for event in first["events"] if event["kind"] == "assistant_final")
        self.assertEqual(request["timestamp"], "2026-09-25T22:00:02.123456789Z")
        self.assertEqual(request["metadata"]["turnId"], "turn1")
        self.assertEqual(answer["body"], long_text)
        self.assertIn("[REDACTED]", request["body"])
        self.assertNotIn(credential, json.dumps(first))
        for private in ("SYSTEM PRIVATE", "DEVELOPER PRIVATE", "HIDDEN REASONING", "SECRET TOOL INPUT", "SECRET TOOL OUTPUT"):
            self.assertNotIn(private, json.dumps(first))
        self.assertEqual(first["stats"]["duplicates"], 3)
        self.assertEqual(first["stats"]["toolActions"], 1)
        original_ids = {event["id"] for event in first["events"]}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(message("2026-09-25T22:01:00.000Z", "later", "assistant", "The next update.", "commentary")) + "\n")
        second = self.collect(include_tools=True)
        self.assertTrue(original_ids.issubset({event["id"] for event in second["events"]}))
        self.assertEqual(len(second["events"]), 4)

    def test_archives_repo_boundary_forks_and_subagent_inheritance(self):
        self.rollout("parent", [message("2026-09-25T22:00:01Z", "parent-message", "assistant", "Original development update.", "commentary")])
        self.rollout("unrelated", [message("2026-09-25T22:00:01Z", "unrelated", "user", "PRIVATE OTHER PROJECT")], cwd=Path(str(self.repo) + "-other"))
        self.rollout("archive", [message("2026-09-25T22:00:04Z", "archived", "user", "Archived project request.")], cwd=self.repo / "nested", archived=True)
        self.rollout("child", [
            message("2026-09-25T22:00:01Z", "parent-message", "assistant", "Original development update.", "commentary", ordinal=2),
            message("2026-09-25T22:00:05Z", "child-message", "assistant", "Child development update.", "final_answer", ordinal=11),
        ], timestamp="2026-09-25T22:00:03Z", parent_thread_id="parent", forked_from_id="parent", subagent_history_start_ordinal=10, agent_path="/root/security_review")
        result = self.collect()
        self.assertEqual(result["stats"]["threads"], 3)
        self.assertEqual(result["stats"]["archivedThreads"], 1)
        self.assertEqual(result["stats"]["subagentThreads"], 1)
        self.assertEqual(len(result["events"]), 3)
        self.assertNotIn("PRIVATE OTHER PROJECT", json.dumps(result))
        child = next(event for event in result["events"] if event["threadId"] == "child")
        self.assertEqual(child["metadata"]["parentThreadId"], "parent")
        self.assertEqual(child["metadata"]["agentPath"], "/root/security_review")

    def test_index_only_session_and_malformed_tail_report_partial(self):
        path = self.rollout("present", [message("2026-09-25T22:00:01Z", "valid", "user", "Retained despite the incomplete tail.")])
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"timestamp":')
        database = self.home / "state_5.sqlite"
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("CREATE TABLE threads(id TEXT,cwd TEXT,rollout_path TEXT,name TEXT)")
            connection.execute("INSERT INTO threads VALUES(?,?,?,?)", ("missing", str(self.repo), str(self.home / "missing.jsonl"), "Missing local rollout"))
            connection.commit()
        original = database.read_bytes()
        result = self.collect()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["stats"]["missingIndexedSessions"], 1)
        self.assertEqual(result["stats"]["malformedLines"], 1)
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(database.read_bytes(), original)

    def test_automation_scope_explicit_timestamps_and_snapshot(self):
        self.rollout("supervisor", [])
        for identity, prompt, target in (("project-ci", "Run daily Modal CI for factored-hackathon-2026 at 10:30 America/Bogota.", "supervisor"), ("other", "Unrelated private project", "elsewhere")):
            directory = self.home / "automations" / identity
            directory.mkdir(parents=True)
            values = {"id": identity, "name": identity, "kind": "heartbeat", "prompt": prompt, "status": "ACTIVE", "rrule": "FREQ=DAILY;BYHOUR=10;BYMINUTE=30", "target_thread_id": target, "created_at": 1790373600000, "updated_at": 1790377200000}
            text = "\n".join(f"{key} = {json.dumps(value)}" for key, value in values.items())
            (directory / "automation.toml").write_text(text, encoding="utf-8")
        result = self.collect()
        self.assertEqual(len(result["automations"]), 1)
        self.assertEqual(len(result["events"]), 2)
        self.assertEqual(result["automations"][0]["schedule"], "Daily at 10:30 (America/Bogota)")
        self.assertTrue(all(event["metadata"]["configurationIsCurrentSnapshot"] for event in result["events"]))
        self.assertTrue(all(event["metadata"]["timestampField"] in {"created_at", "updated_at"} for event in result["events"]))
        self.assertNotIn("Unrelated private project", json.dumps(result))

    def test_timestamp_normalization_and_windows_extended_prefix(self):
        self.assertEqual(_utc("2026-09-25T17:00:00.123456789-05:00"), "2026-09-25T22:00:00.123456789Z")
        self.assertIsNone(_utc("2026-09-25T17:00:00"))
        self.assertTrue(_inside(r"\\?\C:\Users\Moe\Project\subfolder", Path("C:/Users/Moe/Project")))
        self.assertFalse(_inside("C:/Users/Moe/Project-extra", Path("C:/Users/Moe/Project")))
        self.assertLess(_time_key("2026-09-25T22:00:00.123Z"), _time_key("2026-09-25T22:00:00.123456789Z"))


if __name__ == "__main__":
    unittest.main()
