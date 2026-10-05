import asyncio
import json

import pytest

from savia_assistant import InquiryService
from frontend.server.language import MinimizedFacts


def test_actual_concurrent_contracts_followup_quiet_and_resolution(tmp_path):
    now = [1000]
    calls, active = [], []
    async def model(stage, system, user):
        calls.append((stage, json.loads(user)))
        active.append(stage)
        await asyncio.sleep(.01)
        assert len(active) == 2
        return json.dumps({"suggestion": "review_merchant" if stage.endswith("evidence") else "ask_human"})
    service = InquiryService(tmp_path, model, clock=lambda: now[0])
    case = service.create("alice", "No reconozco el cargo", facts=MinimizedFacts("2026-10-04","25.00","USD","Café ficticio","approved"))
    asyncio.run(service.check())
    item = service.list("alice")["items"][0]
    assert len(calls) == 2 and item["state"] == "team_completed"
    assert all("alice" not in json.dumps(prompt) for _,prompt in calls)
    assert len([e for e in item["events"] if e["kind"] == "worker_completed"]) == 2
    assert "Café ficticio" in item["workers"][0]["suggestion"]
    now[0] += service.interval
    asyncio.run(service.check())
    item = service.list("alice")["items"][0]
    assert item["state"] == "awaiting_customer"
    count = len(item["events"])
    now[0] += service.interval
    asyncio.run(service.check())
    assert len(service.list("alice")["items"][0]["events"]) == count
    with pytest.raises(KeyError):
        service.resolve("bob", case)
    service.resolve("alice", case)
    assert service.list("alice")["items"][0]["next_check_at"] is None
    now[0] += service.interval
    asyncio.run(service.check())
    assert len(calls) == 2
    assert "explicación" in service.list("alice")["items"][0]["next_step"]


def test_scoped_mcp_tick_cannot_run_another_owner_and_no_replay_after_crash(tmp_path):
    now = [1000]
    service = InquiryService(tmp_path, clock=lambda: now[0])
    alice = service.create("alice", "Ayuda con la fecha")
    service.create("bob", "Ayuda con el comercio")
    asyncio.run(service.check(owner="alice"))
    assert service.list("bob")["items"][0]["state"] == "queued"
    assert service.list("alice")["items"][0]["state"] == "needs_attention"
    with service.connection() as db:
        db.execute("UPDATE inquiries SET state='team_working',lease='lost',lease_until=1010 WHERE id=?", (alice,))
    now[0] = 1011
    restarted = InquiryService(tmp_path, clock=lambda: now[0])
    asyncio.run(restarted.check(owner="alice"))
    assert restarted.list("alice")["items"][0]["state"] == "needs_attention"


def test_reject_sensitive_inputs_and_unverified_model_prose(tmp_path):
    async def model(*args):
        return '{"suggestion":"bank_refunded"}'
    service = InquiryService(tmp_path, model)
    for message in ("txn_"+"f"*24, "https://private.example", "4111 1111 1111 1111"):
        with pytest.raises(ValueError):
            service.create("alice", message)
    service.create("alice", "Ayúdame con este cargo")
    asyncio.run(service.check())
    item = service.list("alice")["items"][0]
    assert item["state"] == "needs_attention"
    assert "bank_refunded" not in json.dumps(item)
    assert "human_working" not in json.dumps(item)


def test_week_tracking_no_bank_authority_and_explicit_operator_acceptance(tmp_path):
    now = [1000]
    service = InquiryService(tmp_path, clock=lambda: now[0])
    case = service.create("alice", "Necesito otra explicación")
    asyncio.run(service.check())
    with pytest.raises(ValueError):
        service.accept_human("alice", case, accepted_by="")
    service.accept_human("alice", case, accepted_by="actual-test-operator")
    assert service.list("alice")["items"][0]["state"] == "human_working"
    now[0] += service.horizon
    asyncio.run(service.check())
    item = service.list("alice")["items"][0]
    assert item["next_check_at"] is None and item["bank_authority"] is False
    assert "terminó" in item["next_step"]
