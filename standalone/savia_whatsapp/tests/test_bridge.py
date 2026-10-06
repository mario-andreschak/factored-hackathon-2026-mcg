import asyncio
from pathlib import Path
from types import SimpleNamespace as Object

import pytest

from standalone.savia_whatsapp import bridge as bridge_module
from standalone.savia_whatsapp.bridge import Bridge, DeliveryUncertain, Journal


class WhatsApp:
    def __init__(self, fail=False, voice_fail=False):
        self.sent = []
        self.fail = fail
        self.voice_fail = voice_fail
        self.downloads = []

    async def send_text(self, text):
        self.sent.append(text)
        if self.fail:
            raise TimeoutError("possibly delivered")
        return Object(id="out-1")

    async def send_voice_note(self, data, mime):
        self.sent.append(data)
        if self.voice_fail:
            raise TimeoutError("voice note possibly delivered")
        return Object(id="out-2")

    async def download_media(self, identifier, chat_id):
        self.downloads.append((identifier, chat_id))
        raise AssertionError("The bridge must not download its own voice reply")


class Savia:
    def __init__(self):
        self.calls = []

    async def converse(self, **kwargs):
        self.calls.append(kwargs)
        return Object(text="Hola", voice_turns=(Object(wav=b"audio"),))


def message(identifier="in-1", body="!savia Hola", timestamp=101):
    return Object(id=identifier, body=body, timestamp=timestamp, type="chat", has_media=False,
                  from_me=True, chat_id="123456789@c.us")


def make(tmp_path, fail=False):
    journal = Journal(tmp_path / "delivery.sqlite3")
    wa, savia = WhatsApp(fail), Savia()
    bridge = Bridge(wa, savia, journal)
    bridge.started_at = 100
    return bridge, wa, savia, journal


def test_self_message_reply_and_outbound_loop_suppression(tmp_path):
    bridge, wa, savia, journal = make(tmp_path)
    asyncio.run(bridge.process(message()))
    asyncio.run(bridge.process(message("out-2")))
    asyncio.run(bridge.process(message()))
    assert len(savia.calls) == 1
    assert len(wa.sent) == 2
    assert bridge.last_state == "delivered_not_playback_verified"
    journal.close()


def test_old_or_unaddressed_text_cannot_trigger_provider(tmp_path):
    bridge, wa, savia, journal = make(tmp_path)
    asyncio.run(bridge.process(message(timestamp=99)))
    asyncio.run(bridge.process(message(body="ordinary personal text")))
    assert not savia.calls and not wa.sent
    journal.close()


def test_unknown_delivery_halts_and_is_never_replayed(tmp_path):
    bridge, wa, savia, journal = make(tmp_path, fail=True)
    asyncio.run(bridge.process(message()))
    assert journal.blocked()
    assert not bridge.running
    journal.acknowledge_uncertain()
    asyncio.run(bridge.process(message()))
    assert len(wa.sent) == 1
    journal.close()


def test_process_crash_is_uncertain_after_restart(tmp_path):
    journal = Journal(tmp_path / "delivery.sqlite3")
    journal.set("in-1", "sending")
    journal.close()
    journal = Journal(tmp_path / "delivery.sqlite3")
    assert journal.blocked() and journal.known("in-1")
    journal.close()


def test_generation_crash_does_not_create_uncertain_send_or_authorize_replay(tmp_path):
    journal = Journal(tmp_path / "delivery.sqlite3")
    journal.set("in-1", "processing")
    journal.close()
    restored = Journal(tmp_path / "delivery.sqlite3")
    assert not restored.blocked() and restored.known("in-1")
    wa, savia = WhatsApp(), Savia()
    restarted = Bridge(wa, savia, restored)
    restarted.started_at = 100
    asyncio.run(restarted.process(message()))
    assert not wa.sent and not savia.calls
    restored.close()


def test_serialized_whatsapp_identifiers_deduplicate_without_persisting_phone(tmp_path):
    file = tmp_path / "delivery.sqlite3"
    inbound = "true_123456789@c.us_AAAA000011112222"
    outbound = "true_123456789@c.us_BBBB000011112222"
    journal = Journal(file)
    journal.set(inbound, "delivered")
    journal.sent(outbound)
    journal.close()
    assert b"123456789" not in file.read_bytes()
    assert inbound.encode() not in file.read_bytes() and outbound.encode() not in file.read_bytes()
    restored = Journal(file)
    assert restored.known(inbound) and restored.known(outbound)
    restored.close()


def test_own_voice_note_echo_is_suppressed_by_persistent_receipt(tmp_path):
    bridge, wa, savia, journal = make(tmp_path)
    asyncio.run(bridge.process(message()))
    journal.close()
    # Restart without the adapter's in-memory send exclusions. The persistent
    # outbound receipt must still suppress a fromMe ptt event in the self chat.
    restored = Journal(tmp_path / "delivery.sqlite3")
    restarted = Bridge(wa, savia, restored)
    restarted.started_at = 100
    echo = message("out-2", body="", timestamp=102)
    echo.type, echo.has_media = "ptt", True
    asyncio.run(restarted.process(echo))
    assert len(savia.calls) == 1 and len(wa.sent) == 2
    assert wa.downloads == []
    assert not restored.blocked()
    restored.close()


def test_text_receipt_survives_uncertain_audio_and_neither_send_is_replayed(tmp_path):
    journal = Journal(tmp_path / "delivery.sqlite3")
    wa, savia = WhatsApp(voice_fail=True), Savia()
    bridge = Bridge(wa, savia, journal)
    bridge.started_at = 100
    asyncio.run(bridge.process(message()))
    assert len(wa.sent) == 2 and len(savia.calls) == 1
    assert journal.known("out-1") and journal.blocked()
    assert bridge.last_state == "operator_review_required" and not bridge.busy
    journal.close()

    restored = Journal(tmp_path / "delivery.sqlite3")
    restarted = Bridge(wa, savia, restored)
    restarted.started_at = 100
    with pytest.raises(DeliveryUncertain):
        asyncio.run(restarted.run())
    assert restored.known("out-1") and restored.blocked()
    restored.acknowledge_uncertain()
    asyncio.run(restarted.process(message()))
    asyncio.run(restarted.process(message("out-1")))
    assert len(wa.sent) == 2 and len(savia.calls) == 1
    restored.close()


def test_initial_baseline_failure_reports_stopped_state_and_unblocks_readiness(tmp_path):
    class FailedBaseline(WhatsApp):
        async def list_messages(self, after_timestamp):
            raise ConnectionError("offline MCP")

    journal = Journal(tmp_path / "delivery.sqlite3")
    wa, savia = FailedBaseline(), Savia()
    bridge = Bridge(wa, savia, journal)
    asyncio.run(bridge.run())
    assert not bridge.running and bridge.last_state == "startup_failed"
    assert bridge.ready.is_set()
    assert not journal.blocked() and not savia.calls and not wa.sent
    journal.close()


def test_same_second_baseline_is_ignored_but_fresh_input_is_processed(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge_module.time, "time", lambda: 100)
    baseline = message("baseline", timestamp=100)
    fresh = message("fresh", timestamp=100)

    class PollingWhatsApp(WhatsApp):
        def __init__(self):
            super().__init__()
            self.polls = 0

        async def list_messages(self, after_timestamp):
            self.polls += 1
            if self.polls == 1:
                assert after_timestamp == 0
                return [baseline]
            if self.polls == 2:
                assert bridge.ready.is_set()
                assert after_timestamp == 100
                return [baseline, fresh]
            bridge.stop()
            return []

    journal = Journal(tmp_path / "delivery.sqlite3")
    wa, savia = PollingWhatsApp(), Savia()
    bridge = Bridge(wa, savia, journal, poll_seconds=0)
    asyncio.run(bridge.run())
    assert len(savia.calls) == 1 and len(wa.sent) == 2
    assert bridge.processed == 1 and not bridge.running
    assert journal.known("baseline") and journal.known("fresh")
    journal.close()


def test_stop_during_generation_finishes_active_turn_and_skips_queued_input(tmp_path):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        class DelayedSavia(Savia):
            async def converse(self, **kwargs):
                entered.set()
                await release.wait()
                return await super().converse(**kwargs)

        class PollingWhatsApp(WhatsApp):
            def __init__(self):
                super().__init__()
                self.polls = 0

            async def list_messages(self, after_timestamp):
                self.polls += 1
                if self.polls == 1:
                    return []
                return [message("active", timestamp=bridge.started_at + 1),
                        message("queued", timestamp=bridge.started_at + 2)]

        journal = Journal(tmp_path / "delivery.sqlite3")
        wa, savia = PollingWhatsApp(), DelayedSavia()
        bridge = Bridge(wa, savia, journal, poll_seconds=0)
        task = asyncio.create_task(bridge.run())
        await asyncio.wait_for(entered.wait(), timeout=2)
        assert bridge.busy and bridge.running
        bridge.stop()
        release.set()
        await asyncio.wait_for(task, timeout=2)
        assert not bridge.running and not bridge.busy
        assert bridge.processed == 1 and len(savia.calls) == 1 and len(wa.sent) == 2
        assert journal.known("active") and not journal.known("queued")
        journal.close()

    asyncio.run(run())
