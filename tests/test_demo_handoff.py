"""Local receipt oracle: no runtime, customer flows, credentials or model calls."""
import json
import unittest

from demo.handoff import HandoffContext, TransactionEvidence, prepare_handoff, verify_ticket_receipt


def bank_result():
    return {"transaction": {"transaction_reference": "txn_012345abcdef",
            "transaction_date": "2026-06-02T12:00:00", "process_date": "2026-06-02",
            "amount": "120.40", "currency": "MXN", "status": "Pending", "merchant": None,
            "transaction_type": "Purchase", "channel": "POS", "product": "Credit Card"},
            "snapshot": "fixture-build", "freshness": "derived_snapshot", "read_only": True}


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.context = HandoffContext("approved-A", "slack-" + "a" * 48, "banking-flow")
        result = bank_result()
        self.evidence = TransactionEvidence.from_bank_result(self.context, result)
        self.prepared = prepare_handoff(self.context, request="Quiero hablar con una persona", reason="requested_human",
                                        language="es", evidence=self.evidence, unresolved_questions=("¿Reconoce el cargo?",))

    def ticket(self):
        return {"id": "local-ticket-1", "conversationId": self.context.conversation_id,
                "flowId": self.context.flow_id, "message": self.prepared.message, "status": "open"}

    def test_receipt_requires_persisted_matching_facts_and_context(self):
        receipt = {"created": True, "id": "local-ticket-1"}
        self.assertTrue(verify_ticket_receipt(self.prepared, receipt, self.ticket())["readback_verified"])
        self.assertNotIn("approved-A", self.prepared.message)
        for field, value in [("id", "other"), ("conversationId", "foreign-B"), ("flowId", "foreign-flow"),
                             ("status", "unknown"), ("message", "Created a dispute")]:
            ticket = {**self.ticket(), field: value}
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "unverified_handoff_receipt"):
                verify_ticket_receipt(self.prepared, receipt, ticket)
        with self.assertRaises(ValueError):
            verify_ticket_receipt(self.prepared, receipt, None)

    def test_model_cannot_invent_verified_facts_or_actions(self):
        envelope = json.loads(self.prepared.message)
        for field, value in [("verified_facts", {"amount": "9999.00"}), ("bank_action_taken", True),
                             ("dispute_submitted", True)]:
            forged = json.dumps({**envelope, field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_ticket_receipt(self.prepared, {"created": True, "id": "local-ticket-1"},
                                      {**self.ticket(), "message": forged})

    def test_foreign_customer_and_conversation_evidence_rejected(self):
        for context in [HandoffContext("approved-B", self.context.conversation_id, self.context.flow_id),
                        HandoffContext("approved-A", "other-thread", self.context.flow_id)]:
            with self.assertRaisesRegex(ValueError, "foreign_handoff_evidence"):
                prepare_handoff(context, request="Ajuda", reason="requested_human", language="pt", evidence=self.evidence)

    def test_security_handoff_without_transaction_and_receipt_not_a_bank_action(self):
        prepared = prepare_handoff(self.context, request="Perdi o cartão, preciso de um atendente",
                                   reason="security_concern", language="pt")
        envelope = json.loads(prepared.message)
        self.assertEqual(envelope["verified_facts"], {})
        self.assertFalse(envelope["dispute_submitted"])
        self.assertEqual(envelope["actions_taken"], [])

    def test_evidence_is_copied_and_restricted_fields_are_rejected(self):
        result = bank_result()
        evidence = TransactionEvidence.from_bank_result(self.context, result)
        result["transaction"]["amount"] = "999.00"
        self.assertEqual(dict(evidence.facts)["amount"], "120.40")
        for field, value in [("is_fraud", True), ("customer_id", "foreign-B"), ("source_key", "private")]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                TransactionEvidence.from_bank_result(self.context, {**bank_result(),
                    "transaction": {**bank_result()["transaction"], field: value}})
        for amount in ["NaN", "Infinity", "invalid"]:
            result = bank_result()
            result["transaction"]["amount"] = amount
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                TransactionEvidence.from_bank_result(self.context, result)

    def test_failed_tool_receipts_and_duplicate_json_keys_rejected(self):
        for receipt in [{"created": False, "id": "local-ticket-1"}, {"created": 1, "id": "local-ticket-1"},
                        {"created": True, "id": "../escape"}, {"created": True, "id": "local-ticket-1", "error": "failed"}]:
            with self.subTest(receipt=receipt), self.assertRaises(ValueError):
                verify_ticket_receipt(self.prepared, receipt, self.ticket())
        message = self.prepared.message[:-1] + ',"dispute_submitted":false}'
        with self.assertRaises(ValueError):
            verify_ticket_receipt(self.prepared, {"created": True, "id": "local-ticket-1"},
                                  {**self.ticket(), "message": message})

    def test_sensitive_or_unbounded_input_fails_without_echoing_it(self):
        for request in ["Bearer private-test-secret", "xoxb-private-test-secret", "x" * 601, ""]:
            with self.assertRaisesRegex(ValueError, "^invalid_handoff_input$"):
                prepare_handoff(self.context, request=request, reason="requested_human", language="es")


if __name__ == "__main__":
    unittest.main()
