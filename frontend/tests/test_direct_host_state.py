"""Pure direct-host state boundaries; generated SQLite and recording fakes only."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from dataclasses import replace
import sqlite3
import time
from types import SimpleNamespace
import uuid

import httpx
import pytest

from frontend.server.bank_rpc import BankContext, BankRPCError
from frontend.server.chat import ChatError, ChatService
from frontend.server.language import GenericLanguageClient, LanguageConfig, LanguageResult, MinimizedFacts
from frontend.server.state import State
from frontend.tests.action_fixtures import action_facts, action_handoff, action_receipt, action_selected
from frontend.tests.direct_host_fixtures import make_direct_config


TARGET = "txn_" + "a" * 24
HANDLE = "a" * 43


def run(awaitable):
    return asyncio.run(awaitable)


class RecordingBank:
    def __init__(self):
        self.calls = []
        self.revocations = []
        self.handler = None
        self.revoke_error = None
        self.receipt = None
        self.handoff = None

    async def call(self, tool, arguments, context, *, timeout_seconds=45):
        assert type(context) is BankContext
        self.calls.append((tool, deepcopy(arguments), context))
        if self.handler is not None:
            return await self.handler(tool, arguments, context)
        return self.answer(tool, arguments)

    def answer(self, tool, arguments):
        flags = {"synthetic": False, "operator_test": False}
        if tool == "prepare_unrecognized_charge":
            return {**flags, "action": "simulated_intake", "decision": "intake", "reason": None,
                    "snapshot": arguments["snapshot"], "transaction": action_facts(), "pending_handle": HANDLE,
                    "existing_case": {"state": "not_found", "receipt": None,
                                      "coverage": "sandbox_only", "source": "sandbox_cases"},
                    "risk": {"unrecognized_count_24h": 1, "risk_data_complete": True,
                             "coverage": "sandbox_only", "source": "sandbox_cases",
                             "window_start": "2026-09-28T15:00:00Z", "window_end": "2026-09-29T15:00:00Z"}}
        if tool == "confirm_simulated_intake":
            self.receipt = action_receipt()
            return {**flags, "state": "created", "receipt": deepcopy(self.receipt)}
        if tool == "read_intake_receipt":
            return ({**flags, "state": "created", "receipt": deepcopy(self.receipt)} if self.receipt is not None
                    else {**flags, "state": "action_unverified", "receipt": None})
        if tool == "create_verified_handoff":
            self.handoff = action_handoff(reason=arguments["reason"],
                snapshot="test" if arguments.get("pending_handle") else None,
                questions=arguments["unanswered_questions"])
            return {**flags, "state": "created", "handoff": deepcopy(self.handoff)}
        if tool == "read_verified_handoff":
            assert self.handoff is not None and arguments["handoff_id"] == self.handoff["id"]
            return {**flags, "state": "created", "handoff": deepcopy(self.handoff)}
        raise AssertionError("Unexpected bank tool in pure host fixture")

    async def revoke(self, context, *, timeout_seconds=10):
        assert type(context) is BankContext
        self.revocations.append(context)
        if self.revoke_error is not None:
            raise self.revoke_error


class RecordingLanguage:
    def __init__(self, conversation=None):
        self.conversation = conversation or str(uuid.uuid4())
        self.calls = []
        self.handler = None

    async def guide(self, user_text, language, *, facts=None, conversation_id=None, forbidden_values=()):
        self.calls.append({"user_text": user_text, "language": language, "facts": facts,
                           "conversation_id": conversation_id, "forbidden_values": forbidden_values})
        if self.handler is not None:
            return await self.handler(user_text, language, facts, conversation_id)
        return LanguageResult("Selecciona el movimiento para consultarlo.", "ask_selection",
                              conversation_id or self.conversation, True)


@pytest.fixture
def host(tmp_path):
    config = make_direct_config(tmp_path / "generated-host-authority", action_enabled=True)
    bank, language = RecordingBank(), RecordingLanguage()
    bank._service_token = config["bank"]["service_token"]
    language.config = SimpleNamespace(service_token=config["language"]["service_token"])
    directory = tmp_path / "generated-host-state"

    def make_service(*, selected_config=None, selected_directory=None, selected_language=None):
        service = ChatService(config if selected_config is None else selected_config, selected_directory or directory)
        service._bank = bank
        service._language = selected_language or language
        return service

    return SimpleNamespace(service=make_service(), make_service=make_service, config=config, bank=bank,
                           language=language, directory=directory, session=str(uuid.uuid4()),
                           expiry=int(time.time()) + 3600)


def session_row(host, service=None):
    with (service or host.service)._connection() as db:
        row = db.execute("SELECT * FROM chat_sessions WHERE session_id=?", (host.session,)).fetchone()
        return dict(row) if row is not None else None


async def inquire(host, service=None):
    return await (service or host.service).send("customer-a", host.session, host.expiry, "Quiero consultar un movimiento")


async def prepare(host, service=None, **changes):
    operation = {"operation": "prepare", "transactionId": "private-charge-a", "snapshot": "test", **changes}
    return await (service or host.service).action("customer-a", host.session, host.expiry, operation,
        target_reference=TARGET, expected_snapshot="test", expected_transaction=action_selected())


def test_language_conversation_never_becomes_bank_context_and_restart_keeps_both(host):
    async def scenario():
        response = await inquire(host)
        assert response["banking_authority"] is False
        before = session_row(host)
        assert before["conversation_id"] == host.language.calls[0]["conversation_id"]
        assert uuid.UUID(before["conversation_id"]).version == 4
        assert before["conversation_id"] != host.language.conversation
        assert uuid.UUID(before["bank_context_id"]).version == 4
        assert before["bank_context_id"] != before["conversation_id"]
        prepared = await prepare(host)
        assert prepared["state"] == "pending_confirmation"
        tool, arguments, context = host.bank.calls[-1]
        assert tool == "prepare_unrecognized_charge"
        assert context.conversation_id == before["bank_context_id"]
        assert context.session_id != host.session
        assert context.host_revision == host.config["host_revision"]
        assert uuid.UUID(context.operation_id).version == 4
        assert uuid.UUID(arguments["request_id"]).version == 4
        restarted = host.make_service(selected_language=RecordingLanguage())
        assert session_row(host, restarted)["bank_context_id"] == before["bank_context_id"]
        await inquire(host, restarted)
        assert restarted._language.calls[-1]["conversation_id"] == before["conversation_id"]
        assert session_row(host, restarted)["bank_context_id"] == before["bank_context_id"]
    run(scenario())


@pytest.mark.parametrize("failure", ["invalid_guidance", "timeout"])
def test_language_failure_retains_host_context_and_never_grants_bank_authority(host, failure):
    async def scenario():
        requests = []
        def respond(request):
            body = json.loads(request.content)
            requests.append(body)
            conversation = body["metadata"]["conversationId"]
            if len(requests) == 1 and failure == "timeout":
                raise httpx.ReadTimeout("generated fixture response loss")
            guidance = "confirmed_intake" if len(requests) == 1 else "ask_selection"
            return httpx.Response(200, json={"status": "completed", "conversation_id": conversation,
                "choices": [{"message": {"role": "assistant", "content": json.dumps({
                    "schema": "host-language-guidance/v1", "language": "es", "guidance": guidance})}}]})
        client = GenericLanguageClient(LanguageConfig(**host.config["language"]), transport=httpx.MockTransport(respond))
        service = host.make_service(selected_language=client)
        prepared = await prepare(host, service)
        first = await inquire(host, service)
        row = session_row(host, service)
        assert row["conversation_id"] == requests[0]["metadata"]["conversationId"]
        assert uuid.UUID(row["conversation_id"]).version == 4
        assert first["banking_authority"] is False
        assert "confirmed_intake" not in first["reply"] and "CMP-" not in first["reply"]
        restarted = host.make_service(selected_language=client)
        await inquire(host, restarted)
        assert requests[1]["metadata"]["conversationId"] == row["conversation_id"]
        assert session_row(host, restarted)["bank_context_id"] == row["bank_context_id"]
        assert (await restarted.action_status("customer-a", host.session, host.expiry)) == prepared
        assert [call[0] for call in host.bank.calls] == ["prepare_unrecognized_charge"]
    run(scenario())


def test_language_config_change_resets_only_language_and_preserves_consent_and_revoke(host):
    async def scenario():
        prepared = await prepare(host)
        await inquire(host)
        before = session_row(host)
        with host.service._connection() as db:
            saved_action = dict(db.execute("SELECT * FROM action_status WHERE session_id=?", (host.session,)).fetchone())
        changed = deepcopy(host.config)
        changed["language"]["flow_id"] = str(uuid.uuid4())
        language = RecordingLanguage()
        restarted = host.make_service(selected_config=changed, selected_language=language)
        response = await inquire(host, restarted)
        after = session_row(host, restarted)
        assert response["language_context_reset"] is True
        assert "nuevo contexto" in response["reply"]
        assert after["conversation_id"] != before["conversation_id"]
        assert after["conversation_id"] == language.calls[-1]["conversation_id"]
        for field in ("owner", "expires", "subject", "customer_id", "bank_context_id"):
            assert after[field] == before[field]
        with restarted._connection() as db:
            assert dict(db.execute("SELECT * FROM action_status WHERE session_id=?", (host.session,)).fetchone()) == saved_action
        assert (await restarted.action_status("customer-a", host.session, host.expiry)) == prepared
        confirmed = await restarted.action("customer-a", host.session, host.expiry,
            {"operation": "confirm", "pendingHandle": HANDLE, "confirmed": True}, target_reference=TARGET,
            expected_snapshot="test", expected_transaction=action_selected())
        assert confirmed["state"] == "intake_verified"
        assert [call[0] for call in host.bank.calls].count("confirm_simulated_intake") == 1
        assert all(context.conversation_id == before["bank_context_id"] for _, _, context in host.bank.calls)
        assert restarted.queue_revoke("customer-a", host.session, host.expiry) == "pending"
        assert await restarted.attempt_revoke(host.session) == "confirmed"
        assert host.bank.revocations[0].conversation_id == before["bank_context_id"]
        assert host.bank.revocations[0].session_id == host.bank.calls[0][2].session_id
    run(scenario())


@pytest.mark.parametrize("pin", ["base_url", "signing_key_file", "ca_file", "kid"])
def test_bank_authority_pin_change_rejects_existing_capabilities_without_state_changes(host, pin):
    async def scenario():
        await prepare(host)
        assert host.service.queue_revoke("customer-a", host.session, host.expiry) == "pending"
        path = host.directory / "frontend-chat.sqlite3"
        before = path.read_bytes()
        another = make_direct_config(host.directory.parent / "different-generated-bank-authority", action_enabled=True)
        changed = deepcopy(host.config)
        changed["bank"][pin] = ({"base_url": "https://banking-mcp:8443", "kid": "different-bank-key"}.get(pin)
                                or another["bank"][pin])
        with pytest.raises(RuntimeError, match="Bank authority policy changed"):
            host.make_service(selected_config=changed)
        assert path.read_bytes() == before
        assert [call[0] for call in host.bank.calls] == ["prepare_unrecognized_charge"]
        assert host.bank.revocations == []
        with host.service._connection() as db:
            assert db.execute("SELECT state FROM pending_revocations WHERE session_id=?", (host.session,)).fetchone()[0] == "pending"
    run(scenario())


def test_legacy_ingress_configuration_cannot_enable_direct_authority(host):
    legacy = {"base_url": "http://flujo:4200", "model": "flow-Banking_Customer",
              "execution_token": "legacy-private-execution-token", "principal_customers": {"subject-a": "customer-a"}}
    service = host.make_service(selected_config=legacy, selected_directory=host.directory.parent / "legacy-config")
    assert service.status("customer-a")["available"] is False
    with pytest.raises(ChatError):
        run(inquire(host, service))
    assert host.bank.calls == [] and host.language.calls == []


@pytest.mark.parametrize("table", ["chat_sessions", "action_status", "pending_revocations", "chat_messages"])
def test_old_worker_rows_are_rejected_before_schema_or_identity_transplant(host, table):
    directory = host.directory.parent / ("old-worker-" + table)
    directory.mkdir()
    path = directory / "frontend-chat.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(f"CREATE TABLE {table} (legacy_record TEXT)")
        db.execute(f"INSERT INTO {table} VALUES (?)", ("old-worker-private-capability",))
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="Legacy worker-bound state"):
        ChatService(host.config, directory)
    assert path.read_bytes() == before
    with sqlite3.connect(path) as db:
        assert db.execute(f"SELECT legacy_record FROM {table}").fetchall() == [("old-worker-private-capability",)]
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [(table,)]
    assert host.bank.calls == [] and host.language.calls == []


def test_prepare_does_not_require_a_language_conversation_or_accept_it_as_authority(host):
    prepared = run(prepare(host))
    assert prepared["state"] == "pending_confirmation"
    row = session_row(host)
    assert row["conversation_id"] is None
    assert host.bank.calls[0][2].conversation_id == row["bank_context_id"]
    assert host.language.calls == []


def test_language_reply_claims_have_no_action_authority(host):
    async def scenario():
        async def claims_completion(user_text, language, facts, conversation_id):
            return LanguageResult("Ya confirmé CMP-SBX-abcdefgh y un reembolso.", "ask_selection",
                                  conversation_id, True)
        host.language.handler = claims_completion
        response = await inquire(host)
        assert response["banking_authority"] is False
        assert (await host.service.action_status("customer-a", host.session, host.expiry))["state"] == "none"
        assert host.bank.calls == [] and host.bank.revocations == []
        assert host.language.calls and session_row(host)["bank_context_id"] != session_row(host)["conversation_id"]
        displayed = json.dumps({"response": response,
            "history": host.service.history("customer-a", host.session, host.expiry)}, ensure_ascii=False)
        for fabricated in ("CMP-SBX-abcdefgh", "HOF-", "reembolso", "Ya confirmé"):
            assert fabricated not in displayed
    run(scenario())


def test_language_cannot_replace_its_conversation_with_the_host_bank_context(host):
    async def scenario():
        await prepare(host)
        bank_context = session_row(host)["bank_context_id"]
        async def alias_bank_context(user_text, language, facts, conversation_id):
            return LanguageResult("Untrusted conversation", "ask_selection", bank_context, True)
        host.language.handler = alias_bank_context
        calls = list(host.bank.calls)
        with pytest.raises(ChatError, match="No se pudo verificar"):
            await inquire(host)
        row = session_row(host)
        assert row["conversation_id"] == host.language.calls[-1]["conversation_id"]
        assert row["conversation_id"] != bank_context and row["bank_context_id"] == bank_context
        assert host.service.history("customer-a", host.session, host.expiry)["messages"] == []
        assert host.bank.calls == calls
    run(scenario())


def test_host_passes_minimized_facts_and_private_exclusions_to_generic_language(host):
    async def scenario():
        prepared = await prepare(host)
        facts = MinimizedFacts("2026-06-17", "150.00", "COP", None, "approved")
        selection = {"reference": TARGET, "occurred_at": "2026-06-17T12:00:00", "type": "Deposit",
                     "amount": 150, "currency": "COP", "status": "Approved"}
        await host.service.send("customer-a", host.session, host.expiry, "Ayúdame con el movimiento",
                                selection=selection, facts=facts)
        call = host.language.calls[-1]
        assert call["facts"] is facts and call["conversation_id"] == session_row(host)["conversation_id"]
        bank_context = host.bank.calls[0][2]
        for value in ("subject-a", "customer-a", host.session, bank_context.session_id,
                      bank_context.conversation_id, HANDLE, TARGET, prepared["request_id"], "test",
                      host.config["bank"]["service_token"], host.config["language"]["service_token"]):
            assert value in call["forbidden_values"]
            assert value not in json.dumps(facts.public())
        assert len(host.bank.calls) == 1
    run(scenario())


@pytest.mark.parametrize("invalid", ["synthetic", "operator_test", "missing_flags", "extra_key", "full_fact_target"])
def test_prepare_rejects_untrusted_raw_results_before_any_followup_action(host, invalid):
    async def scenario():
        async def untrusted_prepare(tool, arguments, context):
            assert tool == "prepare_unrecognized_charge"
            response = host.bank.answer(tool, arguments)
            if invalid in {"synthetic", "operator_test"}: response[invalid] = True
            if invalid == "missing_flags":
                response.pop("synthetic")
                response.pop("operator_test")
            if invalid == "extra_key": response["operator_claim"] = "authorized"
            if invalid == "full_fact_target":
                response["transaction"] = action_facts(action_selected(channel="foreign-channel"))
                response.update(decision="handoff", reason="missing_evidence")
                response["risk"].update(risk_data_complete=False, unrecognized_count_24h=None)
            return response
        host.bank.handler = untrusted_prepare
        result = await prepare(host)
        assert result["state"] == "prepare_unverified"
        assert [call[0] for call in host.bank.calls] == ["prepare_unrecognized_charge"]
        with host.service._connection() as db:
            row = db.execute("SELECT prepare_transaction_id,prepare_snapshot,prepare_expected_json FROM action_status").fetchone()
        assert row["prepare_transaction_id"] == "private-charge-a" and row["prepare_snapshot"] == "test"
        assert json.loads(row["prepare_expected_json"]) == action_selected()
        assert host.bank.handoff is None and host.bank.receipt is None
    run(scenario())


@pytest.mark.parametrize("possibly_sent", [False, True])
def test_only_definitive_pre_admission_busy_rolls_back_prepare(host, possibly_sent):
    async def scenario():
        async def busy(tool, arguments, context):
            raise BankRPCError("server_busy", possibly_sent=possibly_sent)
        host.bank.handler = busy
        if possibly_sent:
            assert (await prepare(host))["state"] == "prepare_unverified"
            with host.service._connection() as db:
                assert db.execute("SELECT COUNT(*) FROM action_status").fetchone()[0] == 1
        else:
            with pytest.raises(ChatError) as error:
                await prepare(host)
            assert error.value.code == "chat_busy"
            assert (await host.service.action_status("customer-a", host.session, host.expiry))["state"] == "none"
        assert [call[0] for call in host.bank.calls] == ["prepare_unrecognized_charge"]
    run(scenario())


@pytest.mark.parametrize("change", ["customer", "expiry", "target", "snapshot", "facts", "handle", "consent"])
def test_confirm_denies_changed_owner_target_fullfacts_handle_or_consent_before_dispatch(host, change):
    async def scenario():
        await inquire(host)
        await prepare(host)
        customer, expiry, target = "customer-a", host.expiry, TARGET
        operation = {"operation": "confirm", "pendingHandle": HANDLE, "confirmed": True}
        expected = {"expected_snapshot": "test", "expected_transaction": action_selected()}
        if change == "customer": customer = "customer-b"
        if change == "expiry": expiry += 1
        if change == "target": target = "txn_" + "b" * 24
        if change == "snapshot": expected["expected_snapshot"] = "foreign-build"
        if change == "facts": expected["expected_transaction"] = action_selected(channel="foreign-channel")
        if change == "handle": operation["pendingHandle"] = "b" * 43
        if change == "consent": operation["confirmed"] = False
        before = list(host.bank.calls)
        with pytest.raises(ChatError):
            await host.service.action(customer, host.session, expiry, operation, target_reference=target, **expected)
        assert host.bank.calls == before
        assert (await host.service.action_status("customer-a", host.session, host.expiry))["state"] == "pending_confirmation"
    run(scenario())


def test_lost_prepare_replays_only_saved_host_uuid_and_exact_bank_tuple_after_restart(host):
    async def scenario():
        await inquire(host)
        calls = 0
        async def lose_first(tool, arguments, context):
            nonlocal calls
            assert tool == "prepare_unrecognized_charge"
            calls += 1
            if calls == 1:
                raise BankRPCError("bank_timeout", possibly_sent=True)
            return host.bank.answer(tool, arguments)
        host.bank.handler = lose_first
        browser_id = str(uuid.uuid4())
        uncertain = await prepare(host, requestId=browser_id)
        assert uncertain["state"] == "prepare_unverified"
        assert uncertain["request_id"] != browser_id
        assert uuid.UUID(uncertain["request_id"]).version == 4
        first = host.bank.calls[0]
        assert first[1]["request_id"] == uncertain["request_id"]
        restarted = host.make_service()
        with restarted._connection() as db:
            db.execute("UPDATE action_status SET prepare_recovery_after=0 WHERE session_id=?", (host.session,))
        recovered = await restarted.action_status("customer-a", host.session, host.expiry)
        assert recovered["state"] == "pending_confirmation"
        assert recovered["request_id"] == uncertain["request_id"]
        assert host.bank.calls[1][:2] == first[:2]
        assert replace(host.bank.calls[1][2], operation_id=first[2].operation_id) == first[2]
        assert host.bank.calls[1][2].operation_id != first[2].operation_id
        assert "private-charge-a" not in json.dumps(recovered)
    run(scenario())


def test_uncertain_confirm_only_reads_receipt_and_cannot_replay_write_or_guess_handoff(host):
    async def scenario():
        await inquire(host)
        await prepare(host)
        async def lose_confirm(tool, arguments, context):
            if tool == "confirm_simulated_intake":
                raise BankRPCError("bank_timeout", possibly_sent=True)
            return host.bank.answer(tool, arguments)
        host.bank.handler = lose_confirm
        operation = {"operation": "confirm", "pendingHandle": HANDLE, "confirmed": True}
        result = await host.service.action("customer-a", host.session, host.expiry, operation,
            target_reference=TARGET, expected_snapshot="test", expected_transaction=action_selected())
        assert result["state"] == "action_unverified"
        assert [call[0] for call in host.bank.calls] == ["prepare_unrecognized_charge", "confirm_simulated_intake", "read_intake_receipt"]
        with pytest.raises(ChatError):
            await host.service.action("customer-a", host.session, host.expiry, operation, target_reference=TARGET)
        with pytest.raises(ChatError):
            await host.service.action("customer-a", host.session, host.expiry,
                {"operation": "handoff", "pendingHandle": HANDLE, "reason": "customer_request"}, target_reference=TARGET)
        restarted = host.make_service()
        assert (await restarted.action_status("customer-a", host.session, host.expiry))["state"] == "action_unverified"
        assert [call[0] for call in host.bank.calls].count("confirm_simulated_intake") == 1
        assert all(call[0] != "create_verified_handoff" for call in host.bank.calls)
        host.bank.receipt = action_receipt()
        recovered = await restarted.action_status("customer-a", host.session, host.expiry)
        assert recovered["state"] == "intake_verified" and recovered["receipt"] == action_receipt()
    run(scenario())


def test_explicit_confirm_verifies_independent_receipt_instead_of_write_response_claim(host):
    async def scenario():
        await inquire(host)
        await prepare(host)
        async def false_write_claim(tool, arguments, context):
            if tool == "confirm_simulated_intake":
                return {"state": "created", "receipt": action_receipt(), "synthetic": False, "operator_test": False}
            return host.bank.answer(tool, arguments)
        host.bank.handler = false_write_claim
        result = await host.service.action("customer-a", host.session, host.expiry,
            {"operation": "confirm", "pendingHandle": HANDLE, "confirmed": True}, target_reference=TARGET,
            expected_snapshot="test", expected_transaction=action_selected())
        assert result["state"] == "action_unverified" and "receipt" not in result
        assert host.bank.calls[-1][0] == "read_intake_receipt"
    run(scenario())


def test_late_receipt_read_cannot_overwrite_a_new_host_action(host):
    async def scenario():
        await inquire(host)
        await prepare(host)
        owner = host.service._owner_for_subject("subject-a")
        host.service._remember_action(host.session, owner, host.expiry,
                                      {"state": "action_unverified", "pending_handle": HANDLE})
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed_receipt(tool, arguments, context):
            if tool == "read_intake_receipt":
                entered.set()
                await release.wait()
                return {"state": "created", "receipt": action_receipt(), "synthetic": False, "operator_test": False}
            prepared = host.bank.answer(tool, arguments)
            prepared["pending_handle"] = "b" * 43
            return prepared
        host.bank.handler = delayed_receipt
        pending_read = asyncio.create_task(host.service.action_status("customer-a", host.session, host.expiry))
        await asyncio.wait_for(entered.wait(), 10)
        try:
            # Another verified observation completes the predecessor while its
            # earlier receipt read is still in flight, permitting a new action.
            host.service._remember_action(host.session, owner, host.expiry,
                {"state": "intake_verified", "receipt": action_receipt(), "pending_handle": HANDLE})
            newer = await host.service.action("customer-a", host.session, host.expiry,
                {"operation": "prepare", "transactionId": "private-charge-b", "snapshot": "test"},
                target_reference="txn_" + "b" * 24, expected_snapshot="test", expected_transaction=action_selected())
            release.set()
            late = await asyncio.wait_for(pending_read, 10)
            assert late == newer
            latest = await host.service.action_status("customer-a", host.session, host.expiry)
            assert latest == newer and latest["state"] == "pending_confirmation"
            assert latest["target_reference"] == "txn_" + "b" * 24 and "receipt" not in latest
        finally:
            release.set()
            if not pending_read.done():
                pending_read.cancel()
                await asyncio.gather(pending_read, return_exceptions=True)
    run(scenario())


@pytest.mark.parametrize("drift", ["missing_packet", "questions", "provenance", "human_pickup", "facts"])
def test_handoff_needs_exact_whole_packet_independent_readback(host, drift):
    async def scenario():
        await inquire(host)
        async def changed_packet(tool, arguments, context):
            result = host.bank.answer(tool, arguments)
            if tool == "read_verified_handoff":
                packet = result["handoff"]
                if drift == "missing_packet": packet.pop("packet")
                if drift == "questions": packet["packet"]["unanswered_questions"] = ["Different question"]
                if drift == "provenance": packet["packet"]["transaction_provenance"] = {"source": "invented"}
                if drift == "human_pickup": packet["packet"]["human_responded"] = True
                if drift == "facts": packet["packet"]["transaction"] = action_facts()
            return result
        host.bank.handler = changed_packet
        result = await host.service.action("customer-a", host.session, host.expiry,
            {"operation": "handoff", "reason": "customer_request", "unansweredQuestions": ["Next step?"]})
        assert result["state"] == "handoff_unverified" and "handoff" not in result
        assert [call[0] for call in host.bank.calls] == ["create_verified_handoff", "read_verified_handoff"]
        with pytest.raises(ChatError):
            await prepare(host)
    run(scenario())


def test_general_handoff_freezes_questions_and_original_bank_context_across_restart(host):
    async def scenario():
        await inquire(host)
        async def lose_first(tool, arguments, context):
            if len(host.bank.calls) == 1:
                raise BankRPCError("bank_timeout", possibly_sent=True)
            return host.bank.answer(tool, arguments)
        host.bank.handler = lose_first
        uncertain = await host.service.action("customer-a", host.session, host.expiry,
            {"operation": "handoff", "reason": "customer_request", "unansweredQuestions": ["  Next step?  "]})
        assert uncertain["state"] == "handoff_unverified"
        first = host.bank.calls[0]
        restarted = host.make_service()
        with pytest.raises(ChatError):
            await restarted.action("customer-a", host.session, host.expiry,
                {"operation": "handoff", "reason": "customer_request", "requestId": uncertain["request_id"],
                 "unansweredQuestions": ["Changed consent"]})
        assert len(host.bank.calls) == 1
        verified = await restarted.action("customer-a", host.session, host.expiry,
            {"operation": "handoff", "reason": "customer_request", "requestId": uncertain["request_id"]})
        assert verified["state"] == "handoff_verified"
        assert verified["handoff"]["unanswered_questions"] == ["Next step?"]
        assert host.bank.calls[1][:2] == first[:2]
        assert replace(host.bank.calls[1][2], operation_id=first[2].operation_id) == first[2]
        assert host.bank.calls[1][2].operation_id != first[2].operation_id
        assert verified["handoff"]["human_responded"] is False
    run(scenario())


def test_revocation_between_handoff_create_and_readback_denies_second_mcp_call(host):
    async def scenario():
        await inquire(host)
        async def revoke_after_create(tool, arguments, context):
            assert tool == "create_verified_handoff"
            result = host.bank.answer(tool, arguments)
            assert host.service.queue_revoke("customer-a", host.session, host.expiry) == "pending"
            return result
        host.bank.handler = revoke_after_create
        with pytest.raises(ChatError):
            await host.service.action("customer-a", host.session, host.expiry,
                {"operation": "handoff", "reason": "customer_request"})
        assert [call[0] for call in host.bank.calls] == ["create_verified_handoff"]
        with pytest.raises(ChatError):
            await host.service.action_status("customer-a", host.session, host.expiry)
    run(scenario())


def test_local_revoke_suppresses_late_language_reply_and_transcript(host):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed_language(user_text, language, facts, conversation_id):
            entered.set()
            await release.wait()
            return LanguageResult("Late guidance must not be published", "ask_selection", conversation_id, True)
        host.language.handler = delayed_language
        pending = asyncio.create_task(inquire(host))
        await asyncio.wait_for(entered.wait(), 10)
        try:
            assert host.service.queue_revoke("customer-a", host.session, host.expiry) == "pending"
            release.set()
            with pytest.raises(ChatError):
                await asyncio.wait_for(pending, 10)
            with host.service._connection() as db:
                assert db.execute("SELECT COUNT(*) FROM chat_messages WHERE session_id=?", (host.session,)).fetchone()[0] == 0
            assert host.bank.calls == []
        finally:
            release.set()
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
    run(scenario())


def test_durable_revoke_precedes_cookie_deletion_and_retries_bank_only_after_restart(host):
    async def scenario():
        state = State(host.directory)
        state.bind("colombia", "customer-a")
        cookie, session = state.create_session("colombia", 3600)
        host.session, host.expiry = session.id, session.expires_at
        await inquire(host)
        language_calls = list(host.language.calls)
        host.bank.revoke_error = BankRPCError("bank_timeout", possibly_sent=True)
        assert host.service.queue_revoke("customer-a", host.session, host.expiry) == "pending"
        with host.service._connection() as db:
            assert db.execute("SELECT state FROM pending_revocations WHERE session_id=?", (host.session,)).fetchone()[0] == "pending"
            assert db.execute("SELECT revoked FROM chat_sessions WHERE session_id=?", (host.session,)).fetchone()[0] == 1
        assert state.session(cookie) == session
        state.delete_session(session)
        assert state.session(cookie) is None
        assert await host.service.attempt_revoke(host.session) == "pending"
        with pytest.raises(ChatError):
            await inquire(host)
        restarted = host.make_service()
        with restarted._connection() as db:
            db.execute("UPDATE pending_revocations SET next_attempt_at=0 WHERE session_id=?", (host.session,))
        host.bank.revoke_error = None
        assert await restarted.attempt_revoke(host.session) == "confirmed"
        assert host.bank.revocations[0].session_id == host.bank.revocations[1].session_id
        assert host.bank.revocations[0].conversation_id == host.bank.revocations[1].conversation_id
        assert host.language.calls == language_calls
        public = json.dumps(restarted.revocation_diagnostics())
        for private in (cookie, host.session, "subject-a", "customer-a", host.config["bank"]["service_token"]):
            assert private not in public
    run(scenario())


@pytest.mark.parametrize("pin", ["base_url", "signing_key_file", "ca_file", "kid"])
def test_rejected_bank_pin_cannot_repair_original_revocation_outbox(host, pin):
    async def scenario():
        await prepare(host)
        host.service.queue_revoke("customer-a", host.session, host.expiry)
        with host.service._connection() as db:
            db.execute("DELETE FROM pending_revocations")
        path = host.directory / "frontend-chat.sqlite3"
        before = path.read_bytes()
        other = make_direct_config(host.directory.parent / "unaccepted-generated-authority", action_enabled=True)
        changed = deepcopy(host.config)
        changed["bank"][pin] = ({"base_url": "https://banking-mcp:8443", "kid": "unaccepted-bank-key"}.get(pin)
                                or other["bank"][pin])
        with pytest.raises(RuntimeError, match="Bank authority policy changed"):
            host.make_service(selected_config=changed)
        assert path.read_bytes() == before
        with host.service._connection() as db:
            assert db.execute("SELECT COUNT(*) FROM pending_revocations").fetchone()[0] == 0
        restored = host.make_service()
        assert restored.revocation_diagnostics()["pending"] == 1
        assert host.bank.revocations == []
    run(scenario())
