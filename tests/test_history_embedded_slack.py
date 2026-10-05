"""Embedded Slack privacy applies across JSON wrappers and source boundaries."""
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from history_sources.privacy import OMITTED_SLACK_HISTORY, scrub_embedded_slack


class EmbeddedSlackPrivacyTests(unittest.TestCase):
    def test_excluded_formatted_history_in_flujo_tool_wrapper(self):
        returned = {"messages": "Channel: #technical-help (ID: C0123456789)\n=== Message from Synthetic Person at 2026-10-01 ===\nMessage TS: 1790831126.342\nprivate fixture text", "pagination_info": "No more pages"}
        original = {"id": "flujo:thread:message", "source": "flujo", "timestamp": "2026-10-01T05:00:00Z", "threadId": "thread",
            "body": json.dumps({"content": [{"type": "text", "text": json.dumps(returned)}]}), "metadata": {"origin": "conversation-state"}}
        clean = scrub_embedded_slack(original)
        self.assertEqual(clean["id"], original["id"])
        self.assertEqual(clean["timestamp"], original["timestamp"])
        self.assertEqual(clean["threadId"], original["threadId"])
        self.assertNotIn("private fixture text", clean["body"])
        self.assertNotIn("technical-help", clean["body"])
        self.assertEqual(json.loads(clean["body"])["content"][0]["text"], OMITTED_SLACK_HISTORY)

    def test_structured_dm_and_mpim_history_with_flags_or_ids(self):
        for channel in ({"id": "D0123456789"}, {"id": "G0123456789", "is_mpim": True}, {"id": "G0123456789", "type": "mpim"}, {"name": "DM with Synthetic Person", "is_im": "true"}):
            with self.subTest(channel=channel):
                original = {"channel": channel, "messages": [{"ts": "1790831126.342", "text": "private fixture text", "user": "U0123456789"}]}
                self.assertEqual(scrub_embedded_slack(original), OMITTED_SLACK_HISTORY)
        original = {"channel_id": "D0123456789", "messages": [], "has_more": False}
        self.assertEqual(scrub_embedded_slack(original), OMITTED_SLACK_HISTORY)

    def test_canonical_event_with_private_metadata_keeps_identity_and_time(self):
        event = {"id": "codex:tool:123", "source": "codex", "timestamp": "2026-10-01T05:00:00Z",
            "metadata": {"channelId": "D0123456789", "tool": "slack_read_thread"},
            "body": "=== Message from Synthetic Person at 2026-10-01 ===\nMessage TS: 1790831126.342\nprivate fixture text"}
        clean = scrub_embedded_slack(event)
        self.assertEqual(clean["body"], OMITTED_SLACK_HISTORY)
        self.assertEqual(clean["id"], event["id"])
        self.assertEqual(clean["timestamp"], event["timestamp"])
        self.assertEqual(clean["metadata"]["channelId"], event["metadata"]["channelId"])

    def test_channel_lists_omit_only_excluded_or_dm_entries(self):
        original = {"channels": [{"id": "C0123456789", "name": "equipo-team", "type": "public_channel"},
            {"id": "C1123456789", "name": "find-a-team", "type": "public_channel"}, {"id": "D0123456789", "name": "Synthetic Person", "type": "im"}]}
        self.assertEqual(scrub_embedded_slack(original), {"channels": [original["channels"][0]]})
        formatted = "Available Slack channels\n### #equipo-team\n**ID:** C0123456789\n**Type:** public_channel\nKeep this channel\n### #challenge-help\n**ID:** C1123456789\n**Type:** public_channel\nExclude this block\n### DM with Synthetic Person\n**ID:** D0123456789\n**Type:** im\nExclude this DM block\n"
        clean = scrub_embedded_slack(formatted)
        self.assertIn("Keep this channel", clean)
        self.assertNotIn("challenge-help", clean)
        self.assertNotIn("Synthetic Person", clean)
        self.assertEqual(clean.count(OMITTED_SLACK_HISTORY), 2)

    def test_empty_excluded_channel_result_and_custom_exclusions(self):
        response = {"messages": "Channel: #challenge-help\nNo messages returned", "pagination_info": "No more pages"}
        self.assertEqual(scrub_embedded_slack(response), OMITTED_SLACK_HISTORY)
        other = {"channel": {"id": "C0123456789", "name": "private-meeting"}, "messages": [{"ts": "1790831126.342", "text": "private fixture text"}]}
        self.assertEqual(scrub_embedded_slack(other, {"slack_exclude_channels": ["private-meeting"]}), OMITTED_SLACK_HISTORY)

    def test_ordinary_prose_source_code_and_payment_channels_are_preserved(self):
        samples = ["Do not import technical-help, challenge-help or find-a-team; continue the backend work.",
            'EXCLUDED_CHANNEL_NAMES = {"find-a-team", "challenge-help", "technical-help"}',
            're.compile(r"Channel: #technical-help\\nMessage TS: \\d+")',
            "### challenge-help\nDiscuss why this channel is excluded from the history.",
            {"channel": "DebitoAutomatico", "messages": [{"role": "user", "content": "Banking development", "timestamp": 1790831126}]},
            {"channel": {"id": "C0123456789", "name": "equipo-team"}, "messages": [{"ts": "1790831126.342", "user": "U0123456789", "text": "Backend development"}]},
            {"channel": {"id": "G0123456789", "type": "private_channel", "name": "equipo-team"}, "messages": [{"ts": "1790831126.342", "text": "Backend development"}]},
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(scrub_embedded_slack(sample), sample)

    def test_idempotence_and_wrapped_mixed_payloads_preserve_allowed_history(self):
        allowed = {"channel_id": "C0123456789", "messages": [{"ts": "1790831126.342", "text": "Allowed development"}]}
        excluded = {"channel_id": "D0123456789", "messages": [{"ts": "1790831126.342", "text": "Private fixture"}]}
        wrapper = {"content": [{"text": json.dumps([allowed, excluded])}]}
        once = scrub_embedded_slack(wrapper)
        self.assertEqual(scrub_embedded_slack(once), once)
        parsed = json.loads(once["content"][0]["text"])
        self.assertEqual(parsed, [allowed, OMITTED_SLACK_HISTORY])
        self.assertNotIn("Private fixture", json.dumps(once))
        twice_encoded = json.dumps(json.dumps(excluded))
        self.assertNotIn("Private fixture", scrub_embedded_slack(twice_encoded))


if __name__ == "__main__":
    unittest.main()
