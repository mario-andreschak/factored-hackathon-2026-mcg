"""Representative MCP public readback shapes for frontend boundary tests."""
def action_facts(selected=None):
    selected = selected or {"occurred_at": "2026-06-17T12:00:00", "amount": 150,
                            "currency": "COP", "status": "Approved", "merchant": None,
                            "type": "Deposit", "channel": "App"}
    return {"transaction_reference": "txn_" + "a" * 12,
            "transaction_date": selected["occurred_at"],
            "process_date": selected.get("process_date", selected["occurred_at"][:10]),
            "amount": f'{selected["amount"]:.2f}', "currency": selected["currency"],
            "status": selected["status"], "merchant": selected["merchant"],
            "transaction_type": selected["type"], "channel": selected.get("channel", "App"),
            "product": "Cuenta Ahorro"}


def action_receipt(receipt_id="CMP-SBX-abcdefgh", *, snapshot="test", selected=None):
    return {"id": receipt_id, "kind": "simulated_intake", "simulated": True,
            "status": "received",
            "snapshot": snapshot, "created_at": "2026-09-29T15:00:00Z",
            "transaction": action_facts(selected)}


def action_handoff(handoff_id="HOF-abcdefgh", *, reason="customer_request", snapshot="test",
                   selected=None, questions=None):
    facts = action_facts(selected) if snapshot is not None else {}
    return {"id": handoff_id, "reason": reason, "snapshot": snapshot,
            "created_at": "2026-09-29T15:00:00Z", "human_responded": False,
            "facts": facts, "transaction_currentness": "same_snapshot" if snapshot else "not_applicable",
            "packet": {"schema": "banking-sandbox-handoff/v1", "transaction": dict(facts) if snapshot else None,
                       "transaction_provenance": {"source": "owned_serving_snapshot", "snapshot": snapshot,
                                                  "as_of": "2026-09-29T15:00:00Z"} if snapshot else None,
                       "reason": reason, "unanswered_questions": questions or [], "human_responded": False}}
