"""Offline policy and actual MCP-schema checks; no WhatsApp connection or sends."""

import base64
import json
import unittest

from standalone.savia_whatsapp.whatsapp import (
    ChatPolicyError, UncertainSendError, WhatsAppConfig, WhatsAppMcpAdapter, WhatsAppMcpError,
)


SELF = "573001234567@c.us"
TEST = "573009876543@c.us"
OTHER = "573001111111@c.us"


def result(data):
    return {"content": [{"type": "text", "text": json.dumps(data)}], "isError": False}


def message(message_id="voice-1", timestamp=100, chat=SELF, **updates):
    value = {
        "id": message_id, "chatId": chat, "body": "", "type": "ptt", "timestamp": timestamp,
        "fromMe": True, "hasMedia": True,
    }
    value.update(updates)
    return value


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def call_tool(self, name, arguments, **kwargs):
        self.calls.append((name, arguments))
        if not self.responses:
            raise AssertionError("An unexpected MCP call was made.")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class ConfigPolicyTests(unittest.TestCase):
    def test_rejects_unknown_target_and_groups(self):
        with self.assertRaises(ChatPolicyError):
            WhatsAppConfig(chat_jid=OTHER, self_jid=SELF)
        for bad in ("123456-45678@g.us", "status@broadcast", "573001234567", "", "../secret"):
            with self.subTest(bad=bad), self.assertRaises(ChatPolicyError):
                WhatsAppConfig(chat_jid=bad, self_jid=SELF, allowlisted_test_jids=(bad,))

    def test_phone_aliases_and_explicit_test_chat(self):
        WhatsAppConfig(chat_jid=SELF.replace("@c.us", "@s.whatsapp.net"), self_jid=SELF)
        WhatsAppConfig(chat_jid=TEST, self_jid=SELF, allowlisted_test_jids=(TEST,))
        WhatsAppConfig(chat_jid="123456789012345@lid", self_jid=SELF,
                       allowlisted_test_jids=("123456789012345@lid",))

    def test_refuses_remote_or_credentialed_mcp_endpoints(self):
        for url in ("http://example.com/mcp", "http://127.0.0.1/other", "http://user:pass@localhost/mcp",
                    "http://localhost/mcp?token=x", "file:///mcp", "http://127.0.0.1/mcp#x"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                WhatsAppConfig(chat_jid=SELF, self_jid=SELF, url=url)


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def adapter(self, *responses):
        session = FakeSession(*responses)
        return WhatsAppMcpAdapter(WhatsAppConfig(chat_jid=SELF, self_jid=SELF), session=session), session

    async def test_status_is_typed_and_does_not_fetch_contact_or_history(self):
        adapter, session = self.adapter(result({
            "backend": "baileys", "authenticated": True,
            "history": {"state": "syncing", "messageCount": 12, "chatCount": 2, "contactCount": 3,
                        "note": "Only locally synchronized history."},
        }))
        status = await adapter.status()
        self.assertTrue(status.authenticated)
        self.assertEqual(status.history_state, "syncing")
        self.assertEqual(status.message_count, 12)
        self.assertEqual(session.calls, [("get_backend_status", {})])

    async def test_qr_png_and_not_yet_available(self):
        image = b"example-qr-bytes"
        adapter, session = self.adapter(
            {"content": [{"type": "image", "mimeType": "image/png", "data": base64.b64encode(image).decode()}]},
            {"content": [{"type": "text", "text": "No QR code is currently available."}]},
        )
        self.assertEqual(await adapter.pairing_qr(), image)
        self.assertIsNone(await adapter.pairing_qr())
        self.assertEqual(session.calls, [("get_qr_code", {}), ("get_qr_code", {})])

    async def test_inclusive_cursor_handles_same_second_and_self_from_me(self):
        adapter, session = self.adapter(result([
            message("later", 101), message("seen", 100), message("same-second-new", 100), message("old", 99),
        ]))
        values = await adapter.list_messages(100, seen_ids=("seen",))
        self.assertEqual([item.id for item in values], ["same-second-new", "later"])
        self.assertTrue(values[0].from_me)
        self.assertEqual(session.calls, [("list_messages", {"chat_id": SELF, "limit": 50})])

    async def test_poll_rejects_off_chat_projection_before_exposing_results(self):
        adapter, _ = self.adapter(result([message("safe"), message("private", chat=OTHER)]))
        with self.assertRaises(ChatPolicyError):
            await adapter.list_messages(0)
        self.assertEqual(len(adapter._observed_messages), 0)

    async def test_poll_rejects_malformed_flags_and_inconsistent_ids(self):
        for values in ([message(fromMe="false")], [message(timestamp=True)],
                       [message("duplicate", 100), message("duplicate", 101)]):
            adapter, _ = self.adapter(result(values))
            with self.subTest(values=values), self.assertRaises(WhatsAppMcpError):
                await adapter.list_messages(0)

    async def test_download_unknown_or_off_chat_id_does_not_call_any_tool(self):
        adapter, session = self.adapter()
        for chat in (SELF, OTHER, "123-45@g.us"):
            with self.subTest(chat=chat), self.assertRaises(ChatPolicyError):
                await adapter.download_media("arbitrary-personal-message", chat)
        self.assertEqual(session.calls, [])

    async def test_audio_download_rechecks_message_chat_then_uses_actual_audio_block(self):
        audio = b"opus-ogg-test"
        adapter, session = self.adapter(
            result([message()]), result(message()),
            {"content": [
                {"type": "text", "text": '{"mimetype":"audio/ogg; codecs=opus"}'},
                {"type": "audio", "mimeType": "audio/ogg; codecs=opus", "data": base64.b64encode(audio).decode()},
            ]},
        )
        await adapter.list_messages(100)
        media = await adapter.download_media("voice-1", SELF)
        self.assertEqual(media.data, audio)
        self.assertEqual(media.mime_type, "audio/ogg; codecs=opus")
        self.assertEqual(session.calls[1:], [
            ("get_message_by_id", {"message_id": "voice-1"}),
            ("download_media", {"message_id": "voice-1", "include_full_data": True}),
        ])

    async def test_media_is_not_downloaded_if_message_chat_changes(self):
        adapter, session = self.adapter(result([message()]), result(message(chat=OTHER)))
        await adapter.list_messages(100)
        with self.assertRaises(ChatPolicyError):
            await adapter.download_media("voice-1", SELF)
        self.assertEqual(len(session.calls), 2)

    async def test_invalid_or_non_audio_download_fails_closed(self):
        for block in (
            {"type": "audio", "mimeType": "audio/ogg", "data": "not base64"},
            {"type": "image", "mimeType": "image/png", "data": "AA=="},
        ):
            adapter, _ = self.adapter(result([message()]), result(message()), {"content": [block]})
            await adapter.list_messages(100)
            with self.subTest(block=block), self.assertRaises(WhatsAppMcpError):
                await adapter.download_media("voice-1", SELF)

    async def test_send_text_returns_receipt_and_suppresses_own_echo(self):
        adapter, session = self.adapter(
            result({"success": True, "messageId": "outbound", "timestamp": 101}),
            result([message("outbound", 101), message("user-note", 101)]),
        )
        receipt = await adapter.send_text("Hola")
        self.assertEqual(receipt.id, "outbound")
        self.assertEqual(session.calls[0], ("send_message", {"recipient_jid": SELF, "message": "Hola"}))
        self.assertEqual([item.id for item in await adapter.list_messages(100)], ["user-note"])

    async def test_voice_send_sets_ptt_flag_and_actual_base64_schema(self):
        adapter, session = self.adapter(result({"success": True, "messageId": "ptt-out"}))
        receipt = await adapter.send_voice_note(b"wav-test", "audio/wav")
        self.assertEqual(receipt.id, "ptt-out")
        self.assertEqual(session.calls, [("send_media", {
            "recipient_jid": SELF, "media_content": base64.b64encode(b"wav-test").decode(),
            "mime_type": "audio/wav", "as_audio_message": True, "include_full_data": False,
        })])

    async def test_ambiguous_send_receipts_and_transport_errors_are_never_retried(self):
        for response in (result({"success": True}), result({"success": True, "messageId": ""}),
                         result({"success": True, "messageId": "   "}),
                         result({"success": False, "messageId": "x"}),
                         {"isError": True, "content": [{"type": "text", "text": "private error detail"}]},
                         RuntimeError("connection dropped after send")):
            adapter, session = self.adapter(response)
            with self.subTest(response=response), self.assertRaises(UncertainSendError):
                await adapter.send_text("Hola")
            self.assertEqual(len(session.calls), 1)

    async def test_invalid_audio_input_is_rejected_without_mcp_call(self):
        adapter, session = self.adapter()
        for audio, mime in ((b"", "audio/wav"), (b"wav", "image/png"), (b"wav", "audio/wav\nInjected")):
            with self.subTest(mime=mime), self.assertRaises(ValueError):
                await adapter.send_voice_note(audio, mime)
        self.assertEqual(session.calls, [])

    async def test_poll_size_and_audio_size_limits_are_enforced(self):
        adapter, _ = self.adapter(result([message("one"), message("two")]))
        with self.assertRaises(WhatsAppMcpError):
            await adapter.list_messages(0, limit=1)
        session = FakeSession()
        adapter = WhatsAppMcpAdapter(WhatsAppConfig(chat_jid=SELF, self_jid=SELF, max_media_bytes=3), session=session)
        with self.assertRaises(ValueError):
            await adapter.send_voice_note(b"four")
        with self.assertRaises(WhatsAppMcpError):
            adapter._decode_media(base64.b64encode(b"four").decode())
        self.assertEqual(session.calls, [])


if __name__ == "__main__":
    unittest.main()
