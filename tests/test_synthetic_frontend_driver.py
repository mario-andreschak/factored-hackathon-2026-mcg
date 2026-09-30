"""Pure injected-client tests: no app, socket, provider, CLI or clock override."""
from copy import deepcopy
import json
import unittest

from scripts.synthetic_integration.frontend_driver import (
    AttestedPhaseEvidence, DriverError, FrontendDriver, GeneratedFixture,
)


REFERENCE = "txn_" + "a" * 24
REQUEST_ID = "11111111-1111-4111-8111-111111111111"
HANDLE = "p" * 43
SELECTED = {"reference": REFERENCE, "occurred_at": "2026-09-20T12:00:00",
            "process_date": "2026-09-20", "type": "Purchase", "amount": 42,
            "currency": "COP", "status": "Approved", "merchant": "Mercado sintético", "channel": "Card"}
FACTS = {"transaction_reference": "txn_" + "b" * 12, "transaction_date": SELECTED["occurred_at"],
         "process_date": SELECTED["process_date"], "transaction_type": SELECTED["type"],
         "amount": "42.00", "currency": "COP", "status": "Approved",
         "merchant": SELECTED["merchant"], "channel": "Card", "product": "Tarjeta Crédito"}
IDENTITY = {"authenticated": True, "auth_mode": "demo", "profile": {"id": "colombia"}}
OVERVIEW = {"profile": {"id": "colombia"}, "transactions": [SELECTED],
            "metadata": {"build_id": "fixture-1", "source_fingerprint": "a" * 16,
                         "dataset": "organizer-snapshot"}}
FIXTURE = GeneratedFixture("generated-1", "fixture-1", "a" * 16, "colombia", True)
ATTESTED = AttestedPhaseEvidence("generated-1", "c" * 64, "fixture-1", "a" * 16,
    "e" * 64, 1790000000, "synthetic:present-v1:" + "c" * 64, "d" * 64)
NEXT_REQUEST_ID = "22222222-2222-4222-8222-222222222222"


def pending(**changes):
    return {"state": "pending_confirmation", "request_id": REQUEST_ID, "pending_handle": HANDLE,
            "target_reference": REFERENCE, "snapshot": "fixture-1", "transaction": deepcopy(FACTS), **changes}


def receipt(**changes):
    return {"id": "CMP-SBX-abcdefgh", "kind": "simulated_intake", "simulated": True,
            "status": "received", "snapshot": "fixture-1", "created_at": "2026-09-20T12:01:00Z",
            "transaction": deepcopy(FACTS), **changes}


def handoff(*, general=False, questions=None, reason="missing_evidence", **changes):
    snapshot = None if general else "fixture-1"
    return {"id": "HOF-abcdefgh" if not general else "HOF-ijklmnop", "reason": reason,
            "snapshot": snapshot, "created_at": "2026-09-20T12:02:00Z", "human_responded": False,
            "facts": {} if general else deepcopy(FACTS),
            "transaction_currentness": "not_applicable" if general else "same_snapshot",
            "transaction_provenance": None if general else {"source": "owned_serving_snapshot",
                "snapshot": snapshot, "as_of": "2026-09-20T12:01:00Z"},
            "unanswered_questions": questions or [], **changes}


class FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return deepcopy(self.body)


class FakeClient:
    def __init__(self, steps=()):
        self.steps, self.calls = list(steps), []

    def add(self, method, path, body, status=200):
        self.steps.append((method, path, body, status))

    async def _request(self, method, path, body=None):
        self.calls.append((method, path, deepcopy(body)))
        expected_method, expected_path, response, status = self.steps.pop(0)
        assert (method, path) == (expected_method, expected_path)
        return FakeResponse(response(body) if callable(response) else response, status)

    async def get(self, path):
        return await self._request("GET", path)

    async def post(self, path, *, json):
        return await self._request("POST", path, json)


def fresh_client():
    client = FakeClient()
    client.add("GET", "/api/auth/me", {}, 401)
    client.add("POST", "/api/auth/login", IDENTITY)
    client.add("GET", "/api/overview", OVERVIEW)
    client.add("POST", "/api/chat/messages", {"status": "completed", "mode": "flujo", "reply": "Fixture completado."})
    return client


async def selected_driver(result, language="es"):
    client = fresh_client()
    client.add("POST", "/api/action/prepare", result)
    driver = FrontendDriver(client, FIXTURE, language=language)
    await driver.login_and_select("ephemeral-fixture-code")
    await driver.inquire("No reconozco este cargo sintético")
    await driver.prepare()
    return driver, client


class SyntheticFrontendDriverTests(unittest.IsolatedAsyncioTestCase):
    def test_requires_generated_only_declaration(self):
        for changes in ({"generated_only": False}, {"origin": "organizer"}, {"source_fingerprint": "bad"}):
            values = {**FIXTURE.__dict__, **changes}
            with self.assertRaises(DriverError):
                GeneratedFixture(**values)

    async def test_owned_inquiry_prepare_policy_handoff_uses_actual_route_shapes(self):
        result = pending(state="handoff_verified", reason="missing_evidence", handoff=handoff())
        driver, client = await selected_driver(result, "pt")
        self.assertEqual(client.calls[3][2], {"message": "No reconozco este cargo sintético",
                                           "transaction_reference": REFERENCE})
        self.assertEqual(client.calls[4][2], {"transaction_reference": REFERENCE, "language": "pt"})
        self.assertNotIn("request_id", client.calls[4][2])
        self.assertEqual(driver.request_id, REQUEST_ID)
        self.assertEqual(driver.report()["handoff"], handoff())
        self.assertFalse(driver.report()["actual_browser"])
        self.assertFalse(driver.report()["actual_model_grounding"])
        self.assertFalse(driver.report()["human_button_consent"])
        self.assertEqual(driver.report()["dataset_label"], "organizer-snapshot")
        with self.assertRaises(DriverError):
            await driver.explicit_confirm(confirmed=True)
        self.assertFalse(any(path == "/api/action/confirm" for _, path, _ in client.calls))

    async def test_foreign_selector_and_changed_fixture_are_rejected_before_inquiry(self):
        client = fresh_client()
        driver = FrontendDriver(client, FIXTURE)
        with self.assertRaises(DriverError):
            await driver.login_and_select("fixture", selector=lambda rows: "txn_" + "c" * 24)
        self.assertEqual(len(client.calls), 3)
        client = fresh_client()
        client.steps[2] = ("GET", "/api/overview", {**OVERVIEW, "metadata": {
            **OVERVIEW["metadata"], "source_fingerprint": "b" * 16}}, 200)
        with self.assertRaises(DriverError):
            await FrontendDriver(client, FIXTURE).login_and_select("fixture")

    async def test_confirmation_is_separate_explicit_and_never_repeated(self):
        driver, client = await selected_driver(pending(state="handoff_verified", handoff=handoff()))
        self.assertEqual(len(client.calls), 5)
        with self.assertRaises(DriverError):
            await driver.explicit_confirm(confirmed=False)
        driver.begin_attested_phase(ATTESTED)
        client.add("POST", "/api/action/prepare", pending(request_id=NEXT_REQUEST_ID))
        await driver.prepare()
        with self.assertRaises(DriverError):
            await driver.explicit_confirm(confirmed=False)
        client.add("POST", "/api/action/confirm", pending(state="intake_verified",
            request_id=NEXT_REQUEST_ID, receipt=receipt()))
        await driver.explicit_confirm(confirmed=True)
        self.assertEqual(client.calls[-1][2], {"pending_handle": HANDLE,
            "transaction_reference": REFERENCE, "confirmed": True, "language": "es"})
        with self.assertRaises(DriverError):
            await driver.explicit_confirm(confirmed=True)
        self.assertEqual(sum(path == "/api/action/confirm" for _, path, _ in client.calls), 1)
        self.assertFalse(driver.report()["attested_phase"]["observed_24_hour_operation"])

    async def test_pending_without_attested_predecessor_cannot_confirm(self):
        driver, client = await selected_driver(pending())
        with self.assertRaises(DriverError):
            await driver.explicit_confirm(confirmed=True)
        self.assertEqual(len(client.calls), 5)

    async def test_confirm_and_receipt_status_can_omit_wire_uuid_without_inventing_api_evidence(self):
        client = fresh_client()
        driver = FrontendDriver(client, FIXTURE)
        await driver.login_and_select("fixture")
        await driver.inquire("Consulta sintética")
        driver.begin_independent_attested_phase(ATTESTED)
        client.add("POST", "/api/action/prepare", pending())
        await driver.prepare()
        uncertain = {key: value for key, value in pending(state="action_unverified").items() if key != "request_id"}
        client.add("POST", "/api/action/confirm", uncertain)
        await driver.explicit_confirm(confirmed=True)
        self.assertEqual(driver.request_id, REQUEST_ID)
        self.assertNotIn("request_id", driver.action)
        completed = {"state": "intake_verified", "receipt": receipt(),
                     "pending_handle": HANDLE, "target_reference": REFERENCE}
        client.add("GET", "/api/action/status?language=es", completed)
        await driver.read_status()
        self.assertEqual(driver.request_id, REQUEST_ID)
        self.assertNotIn("request_id", driver.report()["action"])
        self.assertEqual(driver.report()["saved_prepare_request_id"], REQUEST_ID)

    async def test_terminal_receipt_shape_binds_saved_facts_without_top_level_fields(self):
        for drift in ({}, {"snapshot": "different"}, {"transaction": {**FACTS, "amount": "43.00"}}):
            with self.subTest(drift=drift):
                client = fresh_client()
                driver = FrontendDriver(client, FIXTURE)
                await driver.login_and_select("fixture")
                await driver.inquire("Consulta sintética")
                driver.begin_independent_attested_phase(ATTESTED)
                client.add("POST", "/api/action/prepare", pending())
                await driver.prepare()
                client.add("POST", "/api/action/confirm", {"state": "intake_verified",
                    "receipt": receipt(**drift), "pending_handle": HANDLE, "target_reference": REFERENCE})
                if drift:
                    with self.assertRaises(DriverError):
                        await driver.explicit_confirm(confirmed=True)
                else:
                    await driver.explicit_confirm(confirmed=True)
                    self.assertEqual(driver.receipt, receipt())
                    self.assertEqual(driver.request_id, REQUEST_ID)

    async def test_status_cannot_claim_new_intake_without_explicit_confirmation(self):
        driver, client = await selected_driver(pending())
        client.add("GET", "/api/action/status?language=es", pending(state="intake_verified", receipt=receipt()))
        with self.assertRaises(DriverError):
            await driver.read_status()
        self.assertFalse(driver.confirmation_attempted)
        self.assertEqual(driver.action, pending())

    async def test_entire_report_is_capability_free_including_nested_evidence(self):
        driver, _ = await selected_driver(pending())
        driver.action["handoff"] = {"state": "handoff_verified", "pending_handle": HANDLE,
                                    "nested": [{"pending_handle": HANDLE}]}
        driver.selection["nested"] = {"pending_handle": HANDLE}
        driver.recorded_evidence.append({"nested": [{"pending_handle": HANDLE}]})
        serialized = json.dumps(driver.report(), ensure_ascii=False)
        self.assertNotIn("pending_handle", serialized)
        self.assertNotIn(HANDLE, serialized)

    async def test_separate_fresh_attested_assembly_can_prepare_without_stock_handoff(self):
        client = fresh_client()
        driver = FrontendDriver(client, FIXTURE)
        await driver.login_and_select("fixture")
        await driver.inquire("Consulta sintética")
        driver.begin_independent_attested_phase(ATTESTED)
        client.add("POST", "/api/action/prepare", pending())
        await driver.prepare()
        self.assertEqual(driver.request_id, REQUEST_ID)
        self.assertEqual(driver.recorded_evidence, [])
        client.add("POST", "/api/action/confirm", pending(state="intake_verified", receipt=receipt()))
        await driver.explicit_confirm(confirmed=True)
        with self.assertRaises(DriverError):
            driver.begin_independent_attested_phase(ATTESTED)

    async def test_deliberate_existing_case_check_uses_fresh_prepare_uuid_and_keeps_history(self):
        driver, client = await selected_driver(pending(state="handoff_verified", handoff=handoff()))
        driver.begin_attested_phase(ATTESTED)
        client.add("POST", "/api/action/prepare", pending(request_id=NEXT_REQUEST_ID))
        await driver.prepare()
        client.add("POST", "/api/action/confirm", pending(state="intake_verified",
            request_id=NEXT_REQUEST_ID, receipt=receipt()))
        await driver.explicit_confirm(confirmed=True)
        driver.begin_existing_case_check()
        existing_id = "33333333-3333-4333-8333-333333333333"
        client.add("POST", "/api/action/prepare", pending(state="existing_case_verified",
            request_id=existing_id, pending_handle="e" * 43, receipt=receipt()))
        await driver.prepare()
        self.assertEqual((driver.request_id, driver.target_reference), (existing_id, REFERENCE))
        self.assertEqual(driver.receipt, receipt())
        self.assertEqual([record["kind"] for record in driver.report()["recorded_evidence"]], ["handoff", "receipt"])
        self.assertEqual(sum(path == "/api/action/confirm" for _, path, _ in client.calls), 1)
        with self.assertRaises(DriverError):
            await driver.explicit_confirm(confirmed=True)
        client.add("POST", "/api/action/handoff", lambda body: {"state": "handoff_verified",
            "request_id": body["request_id"], "reason": "customer_request",
            "handoff": handoff(general=True, reason="customer_request")})
        await driver.request_general_handoff([])
        self.assertEqual(driver.action["state"], "handoff_verified")

    async def test_lost_confirm_preserves_attempt_and_status_never_confirms_again(self):
        driver, client = await selected_driver(pending(state="handoff_verified", handoff=handoff()))
        driver.begin_attested_phase(ATTESTED)
        client.add("POST", "/api/action/prepare", pending(request_id=NEXT_REQUEST_ID))
        await driver.prepare()
        def lost(body):
            raise RuntimeError("fixture response lost")
        client.add("POST", "/api/action/confirm", lost)
        with self.assertRaises(RuntimeError):
            await driver.explicit_confirm(confirmed=True)
        self.assertTrue(driver.confirmation_attempted)
        client.add("GET", "/api/action/status?language=es", pending(state="action_unverified", request_id=NEXT_REQUEST_ID))
        await driver.read_status()
        with self.assertRaises(DriverError):
            await driver.explicit_confirm(confirmed=True)
        self.assertEqual(sum(path == "/api/action/confirm" for _, path, _ in client.calls), 1)
        self.assertNotIn("pending_handle", driver.report()["action"])

    async def test_prepare_cannot_claim_new_intake_before_confirmation(self):
        with self.assertRaises(DriverError):
            await selected_driver(pending(state="intake_verified", receipt=receipt()))

    async def test_attested_phase_requires_matching_independent_evidence_and_fresh_uuid(self):
        driver, client = await selected_driver(pending(state="handoff_verified", handoff=handoff()))
        with self.assertRaises(DriverError):
            driver.begin_attested_phase(AttestedPhaseEvidence(**{
                **ATTESTED.__dict__, "build_id": "different-build"}))
        driver.begin_attested_phase(ATTESTED)
        client.add("POST", "/api/action/prepare", pending())
        with self.assertRaises(DriverError):
            await driver.prepare()

    async def test_restart_status_preserves_host_uuid_target_and_uses_only_gets(self):
        unresolved = {"state": "prepare_unverified", "request_id": REQUEST_ID, "target_reference": REFERENCE}
        driver, _ = await selected_driver(unresolved)
        restarted = FakeClient()
        restarted.add("GET", "/api/auth/me", IDENTITY)
        restarted.add("GET", "/api/overview", OVERVIEW)
        restarted.add("GET", "/api/action/status?language=es", pending())
        await driver.recover(restarted)
        self.assertEqual((driver.request_id, driver.target_reference, driver.pending_handle),
                         (REQUEST_ID, REFERENCE, HANDLE))
        self.assertTrue(all(method == "GET" for method, _, _ in restarted.calls))
        self.assertFalse(driver.confirmation_attempted)

    async def test_changed_uuid_target_handle_or_charge_cannot_recover(self):
        for changes in ({"request_id": "22222222-2222-4222-8222-222222222222"},
                        {"target_reference": "txn_" + "c" * 24}, {"pending_handle": "q" * 43},
                        {"transaction": {**FACTS, "amount": "43.00"}}):
            with self.subTest(changes=changes):
                driver, client = await selected_driver(pending())
                client.add("GET", "/api/action/status?language=es", pending(**changes))
                with self.assertRaises(DriverError):
                    await driver.read_status()
                self.assertEqual(driver.action, pending())

    async def test_conflicting_receipt_and_handoff_are_rejected(self):
        for invalid in (pending(state="intake_verified", receipt=receipt(transaction={**FACTS, "amount": "43.00"})),
                        pending(state="intake_verified", receipt=receipt(simulated=False)),
                        pending(state="handoff_verified", handoff=handoff(human_responded=True)),
                        pending(state="handoff_verified", reason="high_risk", handoff=handoff()),
                        pending(state="handoff_verified", handoff=handoff(facts={**FACTS, "channel": "Branch"}))):
            with self.subTest(state=invalid["state"]):
                with self.assertRaises(DriverError):
                    await selected_driver(invalid)
        driver, client = await selected_driver(pending(state="handoff_verified", handoff=handoff()))
        client.add("GET", "/api/action/status?language=es", pending(state="handoff_verified",
            handoff=handoff(created_at="2026-09-20T12:03:00Z")))
        with self.assertRaises(DriverError):
            await driver.read_status()

    async def test_general_questions_retry_omits_edits_and_keeps_original_uuid_after_restart(self):
        driver, client = await selected_driver(pending(state="handoff_verified", handoff=handoff()), "pt")
        questions = ["¿Cuál es el próximo paso? ÁÉ 😊", "Qual o próximo passo?"]
        client.add("POST", "/api/action/handoff", lambda body: {
            "state": "handoff_unverified", "request_id": body["request_id"],
            "reason": "customer_request", "unanswered_questions": body["unanswered_questions"]})
        await driver.request_general_handoff(["  " + questions[0] + "  ", questions[1]])
        new_id = driver.request_id
        self.assertNotEqual(new_id, REQUEST_ID)
        self.assertEqual(client.calls[-1][2]["unanswered_questions"], questions)
        self.assertNotIn("transaction_reference", client.calls[-1][2])
        restarted = FakeClient()
        restarted.add("GET", "/api/auth/me", IDENTITY)
        restarted.add("GET", "/api/overview", OVERVIEW)
        restarted.add("GET", "/api/action/status?language=pt", deepcopy(driver.action))
        await driver.recover(restarted)
        restarted.add("POST", "/api/action/handoff", {"state": "handoff_verified", "request_id": new_id,
            "reason": "customer_request", "handoff": handoff(general=True, reason="customer_request", questions=questions)})
        await driver.retry_handoff()
        self.assertEqual(restarted.calls[-1][2], {"request_id": new_id, "reason": "customer_request", "language": "pt"})
        records = driver.report()["recorded_evidence"]
        self.assertEqual([record["target_reference"] for record in records], [REFERENCE, None])
        self.assertEqual(records[0]["evidence"], handoff())

    async def test_general_packet_cannot_claim_charge_facts_or_changed_questions(self):
        for packet in (handoff(reason="customer_request"),
                       handoff(general=True, reason="customer_request", questions=["Changed?"])):
            driver, client = await selected_driver(pending(state="handoff_verified", handoff=handoff()))
            client.add("POST", "/api/action/handoff", lambda body: {"state": "handoff_verified",
                "request_id": body["request_id"], "reason": "customer_request", "handoff": packet})
            with self.assertRaises(DriverError):
                await driver.request_general_handoff(["Original?"])

    async def test_restart_authentication_change_stops_before_status(self):
        driver, _ = await selected_driver(pending())
        restarted = FakeClient()
        restarted.add("GET", "/api/auth/me", {**IDENTITY, "profile": {"id": "mexico"}})
        with self.assertRaises(DriverError):
            await driver.recover(restarted)
        self.assertEqual(len(restarted.calls), 1)
