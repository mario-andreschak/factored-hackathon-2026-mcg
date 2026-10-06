"""Pinned Baileys identity checks using fictional keys and offline MCP replies."""
import asyncio
import base64
import json
from types import SimpleNamespace

import pytest

from standalone.savia_whatsapp.bridge import Bridge, Journal
from standalone.savia_whatsapp.whatsapp import (
    ChatPolicyError, UncertainSendError, WhatsAppConfig, WhatsAppMcpAdapter, WhatsAppMcpError,
)

SELF = "573001234567@c.us"
PN = SELF.replace("@c.us", "@s.whatsapp.net")
LID = "123456789012345@lid"
OTHER = "573009876543@s.whatsapp.net"


def opaque(remote=PN, identifier="VOICE001", from_me=True, **extra):
    value = dict(remoteJid=remote, id=identifier, fromMe=from_me, **extra)
    return "b1:" + base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")


def result(value):
    return {"content": [{"type": "text", "text": json.dumps(value)}]}


def projection(identifier, *, chat=PN, from_me=True, body="", kind="ptt"):
    return dict(id=identifier, chatId=chat, fromMe=from_me, body=body, type=kind,
                timestamp=102, hasMedia=kind == "ptt")


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def call_tool(self, name, arguments, **_):
        self.calls.append((name, arguments))
        assert self.responses, "No unplanned MCP calls are allowed"
        return self.responses.pop(0)


def adapter(*responses, chat=SELF):
    session = Session(*responses)
    config = WhatsAppConfig(chat_jid=chat, self_jid=SELF,
                            allowlisted_test_jids=(chat,) if chat != SELF else ())
    return WhatsAppMcpAdapter(config, session=session), session


@pytest.mark.parametrize("receipt_remote,echo_remote", [(PN, LID), (LID, PN)])
def test_phone_lid_echo_is_excluded_without_changing_raw_receipt(receipt_remote, echo_remote):
    receipt_id, echo_id = opaque(receipt_remote), opaque(echo_remote)
    wa, session = adapter(result(dict(success=True, messageId=receipt_id)),
                          result([projection(echo_id)]))

    async def run():
        receipt = await wa.send_voice_note(b"fictional-audio")
        assert receipt.id == receipt_id and receipt.dedupe_id != receipt_id
        assert await wa.list_messages(100) == []

    asyncio.run(run())
    assert session.calls[0][1]["recipient_jid"] == SELF
    assert session.calls[1] == ("list_messages", {"chat_id": SELF, "limit": 50})


def test_direction_and_unrelated_chat_cannot_collide_with_outbound_identity():
    receipt_id = opaque(PN)
    incoming = opaque(LID, from_me=False)
    wa, _ = adapter(result(dict(success=True, messageId=receipt_id)),
                    result([projection(incoming, from_me=False)]))

    async def run():
        receipt = await wa.send_voice_note(b"fictional-audio")
        message = (await wa.list_messages(100))[0]
        assert message.id == incoming and message.dedupe_id != receipt.dedupe_id
        other, _ = adapter(chat=OTHER)
        different = other._project_message(projection(opaque(OTHER), chat=OTHER))
        assert different.dedupe_id != receipt.dedupe_id

    asyncio.run(run())


def test_from_me_never_authorizes_an_unmapped_lid_or_another_phone():
    wa, _ = adapter()
    for value in [projection(opaque(LID), chat=LID), projection(opaque(OTHER), chat=OTHER),
                  projection(opaque(OTHER), chat=PN)]:
        with pytest.raises(ChatPolicyError):
            wa._project_message(value)


def test_lid_projection_preserves_exact_opaque_identifier_for_media_download():
    raw = opaque(LID, "USERVOICE001")
    audio = b"fictional-ogg"
    wa, session = adapter(result([projection(raw)]), result(projection(raw)),
                          {"content": [{"type": "audio", "mimeType": "audio/ogg",
                                        "data": base64.b64encode(audio).decode()}]})

    async def run():
        message = (await wa.list_messages(100))[0]
        assert message.id == raw
        assert (await wa.download_media(message.id, message.chat_id)).data == audio

    asyncio.run(run())
    assert session.calls[1:] == [("get_message_by_id", {"message_id": raw}),
                                ("download_media", {"message_id": raw, "include_full_data": True})]


def test_persistent_receipt_suppresses_lid_voice_echo_after_adapter_restart(tmp_path):
    text_raw, voice_raw = opaque(PN, "TEXT001"), opaque(PN)
    wa, session = adapter(result(dict(success=True, messageId=text_raw)),
                          result(dict(success=True, messageId=voice_raw)))
    calls = []

    class Savia:
        async def converse(self, **arguments):
            calls.append(arguments)
            return SimpleNamespace(text="Hola", voice_turns=(SimpleNamespace(wav=b"fictional-audio"),))

    file = tmp_path / "delivery.sqlite3"
    journal = Journal(file)
    bridge = Bridge(wa, Savia(), journal)
    bridge.started_at = 100
    user = wa._project_message(projection(opaque(PN, "USER001"), kind="chat", body="!savia Hola"))
    asyncio.run(bridge.process(user))
    assert len(session.calls) == 2 and len(calls) == 1
    journal.close()

    restarted, fresh_session = adapter()
    echo = restarted._project_message(projection(opaque(LID)))
    restored = Journal(file)
    assert restored.known(echo.dedupe_id)
    next_bridge = Bridge(restarted, Savia(), restored)
    next_bridge.started_at = 100
    asyncio.run(next_bridge.process(echo))
    assert len(calls) == 1 and fresh_session.calls == []
    assert not restored.blocked()
    restored.close()
    assert b"573001234567" not in file.read_bytes() and voice_raw.encode() not in file.read_bytes()


@pytest.mark.parametrize("bad", ["b1:!bad", opaque(extra="unknown"), opaque(from_me=False),
                                  "b1:" + base64.urlsafe_b64encode(
                                      b'{"remoteJid":"123456789@lid","id":"a","id":"b","fromMe":true}'
                                  ).decode().rstrip("=")])
def test_malformed_pinned_key_cannot_become_a_successful_outbound_receipt(bad):
    wa, _ = adapter(result(dict(success=True, messageId=bad)))
    with pytest.raises(UncertainSendError):
        asyncio.run(wa.send_text("Fictional test"))


def test_ambiguous_alias_duplicate_with_different_content_fails_closed():
    wa, _ = adapter(result([projection(opaque(PN), body="first"),
                            projection(opaque(LID), body="different")]))
    with pytest.raises(WhatsAppMcpError):
        asyncio.run(wa.list_messages(100))


def test_same_alias_key_is_one_message_but_explicit_participants_remain_distinct():
    wa, _ = adapter(result([projection(opaque(PN)), projection(opaque(LID))]))
    assert len(asyncio.run(wa.list_messages(100))) == 1
    first = wa._project_message(projection(opaque(PN, participant=PN)))
    second = wa._project_message(projection(opaque(PN, participant=OTHER)))
    assert first.dedupe_id != second.dedupe_id
