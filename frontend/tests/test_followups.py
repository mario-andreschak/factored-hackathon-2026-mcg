"""Receipt follow-ups exercise the real host controller with an isolated fake transport."""
import asyncio
from copy import deepcopy
import json
import time
import uuid

import pytest

from frontend.server.chat import ChatError, ChatService
from frontend.server.followups import Followups
from frontend.tests.action_fixtures import action_selected
from frontend.tests.direct_host_fixtures import attach_direct_fakes, make_direct_config


def test_opt_in_read_only_followup_survives_restart_and_reports_failure(tmp_path):
    async def journey():
        config = make_direct_config(tmp_path / "config", action_enabled=True)
        service = ChatService(config, tmp_path / "state")
        bank, _ = attach_direct_fakes(service)
        sid, expiry = str(uuid.uuid4()), int(time.time()) + 3600
        tracker = Followups(tmp_path / "state", service)
        assert tracker.list("customer-a", sid, expiry) == {"items": []}
        with pytest.raises(ChatError):
            tracker.enroll("customer-a", sid, expiry)
        prepared = await service.action("customer-a", sid, expiry,
            {"operation": "prepare", "transactionId": "private-a", "snapshot": "test"},
            target_reference="txn_" + "a" * 24, expected_transaction=action_selected())
        with pytest.raises(ChatError):
            tracker.enroll("customer-a", sid, expiry)
        await service.action("customer-a", sid, expiry,
            {"operation": "confirm", "pendingHandle": prepared["pending_handle"], "confirmed": True},
            target_reference="txn_" + "a" * 24, expected_snapshot="test", expected_transaction=action_selected())
        tracker.enroll("customer-a", sid, expiry)
        tracker.enroll("customer-a", sid, expiry)  # Double click cannot create duplicate polling.
        assert len(tracker.list("customer-a", sid, expiry)["items"]) == 1
        bank.calls.clear()
        await tracker.check()
        view = tracker.list("customer-a", sid, expiry)["items"][0]
        assert view["state"] == "checked" and view["last_checked_at"] < view["next_check_at"]
        assert "Aún no hay decisión del banco" in view["message"]
        assert view["receipt_id"] in view["next_step"]
        assert "150,00 COP" in view["next_step"] and "17 de junio de 2026" in view["next_step"]
        assert "T12:" not in view["next_step"]
        assert [call[0] for call in bank.calls] == ["read_intake_receipt"]
        await tracker.check(session_id=sid, force=True)
        assert len(tracker.list("customer-a", sid, expiry)["items"][0]["updates"]) == 1
        view = tracker.list("customer-a", sid, expiry)["items"][0]
        public = json.dumps(view)
        assert prepared["pending_handle"] not in public and sid not in public and "private-a" not in public
        restarted = ChatService(config, tmp_path / "state")
        attach_direct_fakes(restarted, bank=bank)
        tracker = Followups(tmp_path / "state", restarted)
        assert tracker.list("customer-a", sid, expiry)["items"][0] == view
        assert tracker.list("customer-a", sid, expiry, "pt")["items"][0]["message"].startswith("Conferi")
        with pytest.raises(ChatError):
            tracker.list("customer-b", sid, expiry)
        original = deepcopy(bank.receipt)
        bank.receipt = {**original, "id": "CMP-SBX-xxxxxxxx"}
        await tracker.check(session_id=sid, force=True)
        failed = tracker.list("customer-a", sid, expiry)["items"][0]
        assert failed["state"] == "unavailable" and failed["receipt_id"] == view["receipt_id"]
        restarted.queue_revoke("customer-a", sid, expiry)
        bank.calls.clear()
        await tracker.check(session_id=sid, force=True)
        assert bank.calls == []
        with tracker.connection() as db:
            row = db.execute("SELECT state,next_check_at FROM followups").fetchone()
        assert row["state"] == "paused" and row["next_check_at"] is None
    asyncio.run(journey())


def test_followup_leases_prevent_concurrent_receipt_checks(tmp_path):
    async def journey():
        service = ChatService(make_direct_config(tmp_path / "config", action_enabled=True), tmp_path / "state")
        bank, _ = attach_direct_fakes(service)
        sid, expiry = str(uuid.uuid4()), int(time.time()) + 3600
        prepared = await service.action("customer-a", sid, expiry,
            {"operation": "prepare", "transactionId": "private-a", "snapshot": "test"},
            target_reference="txn_" + "a" * 24, expected_transaction=action_selected())
        await service.action("customer-a", sid, expiry,
            {"operation": "confirm", "pendingHandle": prepared["pending_handle"], "confirmed": True},
            target_reference="txn_" + "a" * 24, expected_snapshot="test", expected_transaction=action_selected())
        tracker = Followups(tmp_path / "state", service)
        tracker.enroll("customer-a", sid, expiry)
        started, release = asyncio.Event(), asyncio.Event()
        async def delayed(tool, arguments, context):
            started.set()
            await release.wait()
            return bank.answer(tool, arguments)
        bank.calls.clear()
        bank.call_handler = delayed
        first = asyncio.create_task(tracker.check())
        await started.wait()
        await tracker.check(session_id=sid, force=True)
        release.set()
        await first
        assert len(bank.calls) == 1
    asyncio.run(journey())
